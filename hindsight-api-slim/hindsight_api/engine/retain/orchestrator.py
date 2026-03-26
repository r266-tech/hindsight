"""
Main orchestrator for the retain pipeline.

Coordinates all retain pipeline modules to store memories efficiently.
"""

import logging
import time
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from ..db_utils import acquire_with_retry, retry_with_backoff
from . import bank_utils


def utcnow():
    """Get current UTC time."""
    return datetime.now(UTC)


def parse_datetime_flexible(value: Any) -> datetime:
    """
    Parse a datetime value that could be either a datetime object or an ISO string.

    This handles datetime values from both direct Python calls and deserialized JSON
    (where datetime objects are serialized as ISO strings).

    Args:
        value: Either a datetime object or an ISO format string

    Returns:
        datetime object (timezone-aware)

    Raises:
        TypeError: If value is neither datetime nor string
        ValueError: If string is not a valid ISO datetime
    """
    if isinstance(value, datetime):
        # Ensure timezone-aware
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
    elif isinstance(value, str):
        # Parse ISO format string (handles both 'Z' and '+00:00' timezone formats)
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # Ensure timezone-aware
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt
    else:
        raise TypeError(f"Expected datetime or string, got {type(value).__name__}")


import asyncpg

from ..response_models import TokenUsage
from . import (
    chunk_storage,
    embedding_processing,
    entity_processing,
    fact_extraction,
    fact_storage,
    link_creation,
)
from .types import EntityLink, ExtractedFact, ProcessedFact, RetainContent, RetainContentDict

logger = logging.getLogger(__name__)


def _build_retain_params(contents_dicts, document_tags=None, doc_contents=None):
    """Build retain_params and merged_tags from content dicts."""
    if doc_contents is not None:
        # Per-document mode: doc_contents is list of (idx, content_dict)
        items = [item for _, item in doc_contents]
    else:
        items = contents_dicts

    all_tags = set(document_tags or [])
    for item in items:
        item_tags = item.get("tags", []) or []
        all_tags.update(item_tags)
    merged_tags = list(all_tags)

    retain_params = {}
    if items:
        first_item = items[0]
        if first_item.get("context"):
            retain_params["context"] = first_item["context"]
        if first_item.get("event_date"):
            retain_params["event_date"] = (
                first_item["event_date"].isoformat()
                if hasattr(first_item["event_date"], "isoformat")
                else str(first_item["event_date"])
            )
        if first_item.get("metadata"):
            retain_params["metadata"] = first_item["metadata"]

    return retain_params, merged_tags


async def retain_batch(
    pool,
    embeddings_model,
    llm_config,
    entity_resolver,
    format_date_fn,
    bank_id: str,
    contents_dicts: list[RetainContentDict],
    config,
    document_id: str | None = None,
    is_first_batch: bool = True,
    fact_type_override: str | None = None,
    confidence_score: float | None = None,
    document_tags: list[str] | None = None,
    operation_id: str | None = None,
    schema: str | None = None,
    outbox_callback: Callable[["asyncpg.Connection"], Awaitable[None]] | None = None,
) -> tuple[list[list[str]], TokenUsage]:
    """
    Process a batch of content through the retain pipeline.

    Supports delta retain: when upserting a document that already has chunks,
    only re-processes chunks whose content has changed. Unchanged chunks keep
    their existing facts, entities, and links.

    Args:
        pool: Database connection pool
        embeddings_model: Embeddings model for generating embeddings
        llm_config: LLM configuration for fact extraction
        entity_resolver: Entity resolver for entity processing
        format_date_fn: Function to format datetime to readable string
        bank_id: Bank identifier
        contents_dicts: List of content dictionaries
        config: Resolved HindsightConfig for this bank
        document_id: Optional document ID
        is_first_batch: Whether this is the first batch
        fact_type_override: Override fact type for all facts
        confidence_score: Confidence score for opinions
        document_tags: Tags applied to all items in this batch

    Returns:
        Tuple of (unit ID lists, token usage for fact extraction)
    """
    start_time = time.time()
    total_chars = sum(len(item.get("content", "")) for item in contents_dicts)

    # Buffer all logs
    log_buffer = []
    log_buffer.append(f"{'=' * 60}")
    log_buffer.append(f"RETAIN_BATCH START: {bank_id}")
    log_buffer.append(f"Batch size: {len(contents_dicts)} content items, {total_chars:,} chars")
    log_buffer.append(f"{'=' * 60}")

    # Get bank profile
    profile = await bank_utils.get_bank_profile(pool, bank_id)
    agent_name = profile["name"]

    # Convert dicts to RetainContent objects
    contents = []
    for item in contents_dicts:
        # Merge item-level tags with document-level tags
        item_tags = item.get("tags", []) or []
        merged_tags = list(set(item_tags + (document_tags or [])))

        # Handle event_date: distinguish "not provided" (default to now) from
        # "explicitly None" (caller opted into no timestamp).
        if "event_date" in item and item["event_date"] is None:
            event_date_value = None  # Caller explicitly signalled "unknown date"
        elif item.get("event_date"):
            event_date_value = parse_datetime_flexible(item["event_date"])
        else:
            event_date_value = utcnow()  # Backward-compatible default

        content = RetainContent(
            content=item["content"],
            context=item.get("context", ""),
            event_date=event_date_value,
            metadata=item.get("metadata", {}),
            entities=item.get("entities", []),
            tags=merged_tags,
            observation_scopes=item.get("observation_scopes"),
        )
        contents.append(content)

    # --- Delta retain: check if we can skip unchanged chunks ---
    # Delta retain applies when:
    # 1. There's a document_id (single-doc mode or per-item)
    # 2. is_first_batch is True (upsert scenario)
    # 3. The document already has chunks in the DB
    delta_result = None
    if is_first_batch:
        delta_result = await _try_delta_retain(
            pool,
            embeddings_model,
            llm_config,
            entity_resolver,
            format_date_fn,
            bank_id,
            contents_dicts,
            contents,
            config,
            document_id,
            fact_type_override,
            document_tags,
            agent_name,
            log_buffer,
            start_time,
            operation_id,
            schema,
            outbox_callback,
        )
    if delta_result is not None:
        return delta_result

    # --- Full retain path (no delta possible) ---
    return await _full_retain(
        pool,
        embeddings_model,
        llm_config,
        entity_resolver,
        format_date_fn,
        bank_id,
        contents_dicts,
        contents,
        config,
        document_id,
        is_first_batch,
        fact_type_override,
        confidence_score,
        document_tags,
        agent_name,
        log_buffer,
        start_time,
        operation_id,
        schema,
        outbox_callback,
    )


async def _try_delta_retain(
    pool,
    embeddings_model,
    llm_config,
    entity_resolver,
    format_date_fn,
    bank_id,
    contents_dicts,
    contents,
    config,
    document_id,
    fact_type_override,
    document_tags,
    agent_name,
    log_buffer,
    start_time,
    operation_id,
    schema,
    outbox_callback,
):
    """
    Attempt delta retain for a document upsert. Returns result tuple if delta
    was performed, or None if we should fall back to full retain.

    Delta retain works by:
    1. Chunking the new content
    2. Loading existing chunk hashes
    3. Comparing by content hash
    4. Only extracting facts for changed/new chunks
    5. Deleting removed/changed chunks (cascade deletes their facts/links)
    6. Storing new/changed chunks + their facts
    """
    # Determine the effective document_id(s)
    # For delta, we need a single document_id (either the legacy param or per-item)
    effective_doc_id = document_id
    if not effective_doc_id:
        # Check per-item document_ids — delta only works with a single doc
        doc_ids = {item.get("document_id") for item in contents_dicts if item.get("document_id")}
        if len(doc_ids) != 1:
            return None  # Multiple or no doc IDs — can't do delta
        effective_doc_id = doc_ids.pop()

    # Load existing chunks for this document
    async with acquire_with_retry(pool) as conn:
        existing_chunks = await chunk_storage.load_existing_chunks(conn, bank_id, effective_doc_id)

    if not existing_chunks:
        return None  # No existing chunks — fall back to full retain

    # Check if any existing chunks lack content_hash (pre-migration data)
    if any(c.content_hash is None for c in existing_chunks):
        logger.info(f"Delta retain skipped for {effective_doc_id}: existing chunks lack content_hash (pre-migration)")
        return None

    # Chunk the new content (same way fact_extraction does it)
    # We need to run the chunking step to compare
    step_start = time.time()
    new_chunks_with_contents = _chunk_contents_for_delta(contents, config)
    log_buffer.append(
        f"[delta] Chunked new content: {len(new_chunks_with_contents)} chunks in {time.time() - step_start:.3f}s"
    )

    # Build hash maps
    existing_by_index = {c.chunk_index: c for c in existing_chunks}
    new_hashes = {idx: chunk_storage.compute_chunk_hash(text) for idx, text in new_chunks_with_contents.items()}

    # Classify chunks
    unchanged_indices = []  # Chunk indices that haven't changed
    changed_indices = []  # Chunk indices that exist but content changed
    new_indices = []  # Chunk indices that are new (didn't exist before)
    removed_indices = []  # Chunk indices that existed but aren't in new content

    for idx, new_hash in new_hashes.items():
        existing = existing_by_index.get(idx)
        if existing and existing.content_hash == new_hash:
            unchanged_indices.append(idx)
        elif existing:
            changed_indices.append(idx)
        else:
            new_indices.append(idx)

    for idx in existing_by_index:
        if idx not in new_hashes:
            removed_indices.append(idx)

    log_buffer.append(
        f"[delta] Chunk diff: {len(unchanged_indices)} unchanged, "
        f"{len(changed_indices)} changed, {len(new_indices)} new, "
        f"{len(removed_indices)} removed"
    )

    # If everything changed, fall back to full retain (no benefit from delta)
    if not unchanged_indices:
        logger.info(f"Delta retain: no unchanged chunks for {effective_doc_id}, falling back to full retain")
        return None

    # Determine which chunks need fact extraction
    chunks_to_process = changed_indices + new_indices

    if not chunks_to_process and not removed_indices:
        # Nothing changed — just update document metadata/tags
        log_buffer.append("[delta] No chunk changes detected — updating document metadata only")
        return await _delta_metadata_only(
            pool,
            entity_resolver,
            bank_id,
            contents_dicts,
            contents,
            effective_doc_id,
            document_tags,
            log_buffer,
            start_time,
            outbox_callback,
        )

    # Build RetainContent items containing only the changed/new chunks
    # We create synthetic content items from just the chunks that need processing
    delta_contents, delta_chunk_map = _build_delta_contents(
        contents, new_chunks_with_contents, chunks_to_process, config
    )

    if not delta_contents:
        # Edge case: chunks_to_process identified but no content to extract
        return await _delta_metadata_only(
            pool,
            entity_resolver,
            bank_id,
            contents_dicts,
            contents,
            effective_doc_id,
            document_tags,
            log_buffer,
            start_time,
            outbox_callback,
        )

    # Extract facts only for changed/new chunks
    step_start = time.time()
    extracted_facts, new_chunk_metadata, usage = await fact_extraction.extract_facts_from_contents(
        delta_contents, llm_config, agent_name, config, pool, operation_id, schema
    )
    log_buffer.append(
        f"[delta] Extract facts: {len(extracted_facts)} facts from {len(delta_contents)} "
        f"changed contents ({len(chunks_to_process)} chunks) in {time.time() - step_start:.3f}s"
    )

    # Apply fact_type_override if provided
    if fact_type_override:
        for fact in extracted_facts:
            fact.fact_type = fact_type_override

    # Generate embeddings for new facts
    if extracted_facts:
        step_start = time.time()
        augmented_texts = embedding_processing.augment_texts_with_dates(extracted_facts, format_date_fn)
        embeddings = await embedding_processing.generate_embeddings_batch(embeddings_model, augmented_texts)
        log_buffer.append(f"[delta] Generate embeddings: {len(embeddings)} in {time.time() - step_start:.3f}s")

        processed_facts = [ProcessedFact.from_extracted_fact(ef, emb) for ef, emb in zip(extracted_facts, embeddings)]
    else:
        processed_facts = []

    # --- Database transaction ---
    result_unit_ids: list[list[str]] = []
    log_buffer_pre_db = len(log_buffer)

    async def _run_delta_db_work() -> None:
        nonlocal result_unit_ids
        del log_buffer[log_buffer_pre_db:]

        # Reset per-fact mutations for retry
        for pf in processed_facts:
            pf.document_id = None
            pf.chunk_id = None
        entity_resolver.discard_pending_stats()

        async with acquire_with_retry(pool) as conn:
            async with conn.transaction():
                # Step 1: Update document metadata (no delete)
                step_start = time.time()
                combined_content = "\n".join([c.get("content", "") for c in contents_dicts])
                retain_params, merged_tags = _build_retain_params(contents_dicts, document_tags)
                await fact_storage.handle_document_tracking(
                    conn,
                    bank_id,
                    effective_doc_id,
                    combined_content,
                    True,
                    retain_params,
                    merged_tags,
                    delta_mode=True,
                )
                log_buffer.append(f"[delta-db] Document tracking (update) in {time.time() - step_start:.3f}s")

                # Step 2: Delete changed and removed chunks (cascades to their memory_units and links)
                step_start = time.time()
                chunks_to_delete = []
                for idx in changed_indices + removed_indices:
                    existing = existing_by_index.get(idx)
                    if existing:
                        chunks_to_delete.append(existing.chunk_id)
                await chunk_storage.delete_chunks_by_ids(conn, chunks_to_delete)
                log_buffer.append(
                    f"[delta-db] Deleted {len(chunks_to_delete)} chunks "
                    f"({len(changed_indices)} changed + {len(removed_indices)} removed) "
                    f"in {time.time() - step_start:.3f}s"
                )

                # Step 3: Update tags on unchanged chunks' memory units
                step_start = time.time()
                all_tags = set(document_tags or [])
                for item in contents_dicts:
                    item_tags = item.get("tags", []) or []
                    all_tags.update(item_tags)
                updated_count = await fact_storage.update_memory_units_tags(
                    conn, bank_id, effective_doc_id, list(all_tags)
                )
                log_buffer.append(
                    f"[delta-db] Updated tags on {updated_count} existing memory units in {time.time() - step_start:.3f}s"
                )

                # Step 4: Store new/changed chunks
                step_start = time.time()
                chunk_id_map_by_doc = {}
                if new_chunk_metadata:
                    # Remap chunk indices to match the original document's chunk indices
                    remapped_chunks = []
                    for cm in new_chunk_metadata:
                        # delta_chunk_map maps delta content_index -> original chunk_index
                        original_chunk_idx = delta_chunk_map.get(cm.chunk_index, cm.chunk_index)
                        from .types import ChunkMetadata as CM

                        remapped_chunks.append(
                            CM(
                                chunk_text=cm.chunk_text,
                                fact_count=cm.fact_count,
                                content_index=cm.content_index,
                                chunk_index=original_chunk_idx,
                            )
                        )
                    chunk_id_map = await chunk_storage.store_chunks_batch(
                        conn, bank_id, effective_doc_id, remapped_chunks
                    )
                    for chunk_idx, chunk_id in chunk_id_map.items():
                        chunk_id_map_by_doc[(effective_doc_id, chunk_idx)] = chunk_id
                    log_buffer.append(
                        f"[delta-db] Stored {len(remapped_chunks)} new/changed chunks in {time.time() - step_start:.3f}s"
                    )

                # Step 5: Map chunk_ids and document_ids to processed facts
                for ef, pf in zip(extracted_facts, processed_facts):
                    pf.document_id = effective_doc_id
                    if ef.chunk_index is not None:
                        # Map the delta chunk index to original chunk index
                        original_idx = delta_chunk_map.get(ef.chunk_index, ef.chunk_index)
                        chunk_id = chunk_id_map_by_doc.get((effective_doc_id, original_idx))
                        if chunk_id:
                            pf.chunk_id = chunk_id

                # Step 6: Insert new facts
                step_start = time.time()
                unit_ids = await fact_storage.insert_facts_batch(conn, bank_id, processed_facts)
                log_buffer.append(f"[delta-db] Insert facts: {len(unit_ids)} units in {time.time() - step_start:.3f}s")

                if unit_ids:
                    # Step 7: Process entities for new facts
                    step_start = time.time()
                    user_entities_per_content = {
                        idx: content.entities for idx, content in enumerate(contents) if content.entities
                    }
                    entity_links = await entity_processing.process_entities_batch(
                        entity_resolver,
                        conn,
                        bank_id,
                        unit_ids,
                        processed_facts,
                        log_buffer,
                        user_entities_per_content=user_entities_per_content,
                        entity_labels=getattr(config, "entity_labels", None),
                    )
                    log_buffer.append(
                        f"[delta-db] Process entities: {len(entity_links)} links in {time.time() - step_start:.3f}s"
                    )

                    # Step 8: Create temporal links
                    step_start = time.time()
                    temporal_link_count = await link_creation.create_temporal_links_batch(conn, bank_id, unit_ids)
                    log_buffer.append(
                        f"[delta-db] Temporal links: {temporal_link_count} in {time.time() - step_start:.3f}s"
                    )

                    # Step 9: Create semantic links
                    step_start = time.time()
                    embeddings_for_links = [fact.embedding for fact in processed_facts]
                    semantic_link_count = await link_creation.create_semantic_links_batch(
                        conn, bank_id, unit_ids, embeddings_for_links
                    )
                    log_buffer.append(
                        f"[delta-db] Semantic links: {semantic_link_count} in {time.time() - step_start:.3f}s"
                    )

                    # Step 10: Insert entity links
                    step_start = time.time()
                    if entity_links:
                        await entity_processing.insert_entity_links_batch(conn, entity_links)
                    log_buffer.append(
                        f"[delta-db] Entity links: {len(entity_links) if entity_links else 0} in {time.time() - step_start:.3f}s"
                    )

                    # Step 11: Create causal links
                    step_start = time.time()
                    causal_link_count = await link_creation.create_causal_links_batch(conn, unit_ids, processed_facts)
                    log_buffer.append(
                        f"[delta-db] Causal links: {causal_link_count} in {time.time() - step_start:.3f}s"
                    )

                # Map results back to original content items
                result_unit_ids = _map_results_to_contents(contents, extracted_facts, unit_ids if unit_ids else [])

                if outbox_callback:
                    await outbox_callback(conn)

            # Flush entity stats after commit
            await entity_resolver.flush_pending_stats()

            total_time = time.time() - start_time
            log_buffer.append(f"{'=' * 60}")
            log_buffer.append(
                f"DELTA RETAIN COMPLETE: {len(unit_ids) if extracted_facts else 0} new units, "
                f"{len(unchanged_indices)} chunks unchanged in {total_time:.3f}s"
            )
            log_buffer.append(f"Document: {effective_doc_id}")
            log_buffer.append(f"{'=' * 60}")
            logger.info("\n" + "\n".join(log_buffer) + "\n")

    await retry_with_backoff(_run_delta_db_work)
    return result_unit_ids, usage


async def _delta_metadata_only(
    pool,
    entity_resolver,
    bank_id,
    contents_dicts,
    contents,
    document_id,
    document_tags,
    log_buffer,
    start_time,
    outbox_callback,
):
    """Handle the case where no chunks changed — just update document metadata and tags."""
    async with acquire_with_retry(pool) as conn:
        async with conn.transaction():
            combined_content = "\n".join([c.get("content", "") for c in contents_dicts])
            retain_params, merged_tags = _build_retain_params(contents_dicts, document_tags)
            await fact_storage.handle_document_tracking(
                conn,
                bank_id,
                document_id,
                combined_content,
                True,
                retain_params,
                merged_tags,
                delta_mode=True,
            )
            # Update tags on existing memory units
            await fact_storage.update_memory_units_tags(conn, bank_id, document_id, merged_tags)

            if outbox_callback:
                await outbox_callback(conn)

    total_time = time.time() - start_time
    log_buffer.append(f"DELTA RETAIN (no changes): metadata updated in {total_time:.3f}s")
    logger.info("\n" + "\n".join(log_buffer) + "\n")
    return [[] for _ in contents], TokenUsage()


def _chunk_contents_for_delta(contents: list[RetainContent], config) -> dict[int, str]:
    """
    Chunk contents the same way fact_extraction does, returning a map of
    global_chunk_index -> chunk_text.

    This must produce identical chunks to what extract_facts_from_contents would produce,
    so that hash comparison is valid.
    """
    result = {}
    global_chunk_idx = 0

    for content in contents:
        chunk_size = getattr(config, "retain_chunk_size", 120000)
        chunks = fact_extraction.chunk_text(content.content, chunk_size)
        for chunk_text in chunks:
            result[global_chunk_idx] = chunk_text
            global_chunk_idx += 1

    return result


def _build_delta_contents(
    original_contents: list[RetainContent],
    new_chunks_with_contents: dict[int, str],
    chunks_to_process: list[int],
    config,
) -> tuple[list[RetainContent], dict[int, int]]:
    """
    Build RetainContent items containing only the chunks that need processing.

    Returns:
        - List of RetainContent items (one per chunk to process)
        - Map of delta_chunk_index -> original_chunk_index
    """
    if not chunks_to_process:
        return [], {}

    delta_contents = []
    delta_chunk_map = {}  # Maps delta chunk index -> original chunk index

    # For each chunk that needs processing, create a RetainContent with just that chunk's text.
    # We use the first original content's metadata (context, event_date, etc.) since
    # all chunks in a single-doc retain share the same metadata.
    template_content = original_contents[0] if original_contents else None
    if not template_content:
        return [], {}

    for original_chunk_idx in sorted(chunks_to_process):
        chunk_text = new_chunks_with_contents.get(original_chunk_idx)
        if not chunk_text:
            continue

        # Create a RetainContent with this single chunk as its content.
        # Make the chunk small enough that extract_facts_from_contents won't re-chunk it.
        delta_content = RetainContent(
            content=chunk_text,
            context=template_content.context,
            event_date=template_content.event_date,
            metadata=template_content.metadata,
            entities=template_content.entities,
            tags=template_content.tags,
            observation_scopes=template_content.observation_scopes,
        )
        delta_contents.append(delta_content)

        # The delta content at index len(delta_contents)-1 will produce chunk at
        # global index len(delta_contents)-1 (since each content is one chunk).
        # Map that back to the original chunk index.
        delta_idx = len(delta_contents) - 1
        delta_chunk_map[delta_idx] = original_chunk_idx

    return delta_contents, delta_chunk_map


async def _full_retain(
    pool,
    embeddings_model,
    llm_config,
    entity_resolver,
    format_date_fn,
    bank_id,
    contents_dicts,
    contents,
    config,
    document_id,
    is_first_batch,
    fact_type_override,
    confidence_score,
    document_tags,
    agent_name,
    log_buffer,
    start_time,
    operation_id,
    schema,
    outbox_callback,
):
    """Original full-retain path (no delta optimization)."""
    # Step 1: Extract facts from all contents
    step_start = time.time()

    extracted_facts, chunks, usage = await fact_extraction.extract_facts_from_contents(
        contents, llm_config, agent_name, config, pool, operation_id, schema
    )
    log_buffer.append(
        f"[1] Extract facts: {len(extracted_facts)} facts, {len(chunks)} chunks from {len(contents)} contents in {time.time() - step_start:.3f}s"
    )

    if not extracted_facts:
        # Still need to create document if document_id was provided or chunks exist
        docs_tracked = 0
        async with acquire_with_retry(pool) as conn:
            async with conn.transaction():
                # Group contents by document_id (consistent with normal path)
                contents_by_doc_early = defaultdict(list)
                for idx, content_dict in enumerate(contents_dicts):
                    doc_id = content_dict.get("document_id")
                    contents_by_doc_early[doc_id].append((idx, content_dict))

                if document_id:
                    # Legacy: single document_id parameter
                    combined_content = "\n".join([c.get("content", "") for c in contents_dicts])
                    retain_params, merged_tags = _build_retain_params(contents_dicts, document_tags)

                    await fact_storage.handle_document_tracking(
                        conn, bank_id, document_id, combined_content, is_first_batch, retain_params, merged_tags
                    )
                    docs_tracked += 1
                else:
                    # Handle per-item document_ids and/or chunks (mirrors normal path logic)
                    has_any_doc_ids = any(item.get("document_id") for item in contents_dicts)

                    if has_any_doc_ids or chunks:
                        for original_doc_id, doc_contents in contents_by_doc_early.items():
                            should_create_doc = (original_doc_id is not None) or chunks
                            if not should_create_doc:
                                continue

                            actual_doc_id = original_doc_id
                            if actual_doc_id is None:
                                # No document_id but have chunks - generate one
                                actual_doc_id = str(uuid.uuid4())

                            combined_content = "\n".join([c.get("content", "") for _, c in doc_contents])
                            retain_params, merged_tags = _build_retain_params(
                                contents_dicts, document_tags, doc_contents=doc_contents
                            )

                            await fact_storage.handle_document_tracking(
                                conn,
                                bank_id,
                                actual_doc_id,
                                combined_content,
                                is_first_batch,
                                retain_params,
                                merged_tags,
                            )
                            docs_tracked += 1

        total_time = time.time() - start_time
        doc_status = f"{docs_tracked} document(s) tracked" if docs_tracked > 0 else "no document tracked"
        logger.info(
            f"RETAIN_BATCH COMPLETE: 0 facts extracted from {len(contents)} contents in {total_time:.3f}s ({doc_status}, no facts)"
        )
        return [[] for _ in contents], usage

    # Apply fact_type_override if provided
    if fact_type_override:
        for fact in extracted_facts:
            fact.fact_type = fact_type_override

    # Step 2: Augment texts and generate embeddings
    step_start = time.time()
    augmented_texts = embedding_processing.augment_texts_with_dates(extracted_facts, format_date_fn)
    embeddings = await embedding_processing.generate_embeddings_batch(embeddings_model, augmented_texts)
    log_buffer.append(f"[2] Generate embeddings: {len(embeddings)} embeddings in {time.time() - step_start:.3f}s")

    # Step 3: Convert to ProcessedFact objects (without chunk_ids yet)
    processed_facts = [
        ProcessedFact.from_extracted_fact(extracted_fact, embedding)
        for extracted_fact, embedding in zip(extracted_facts, embeddings)
    ]

    # Group contents by document_id for document tracking and chunk storage
    contents_by_doc = defaultdict(list)
    for idx, content_dict in enumerate(contents_dicts):
        doc_id = content_dict.get("document_id")
        contents_by_doc[doc_id].append((idx, content_dict))

    # Step 4: Database transaction (retried on deadlock)
    result_unit_ids: list[list[str]] = []

    log_buffer_pre_db = len(log_buffer)

    async def _run_db_work() -> None:
        nonlocal result_unit_ids

        # Reset per-fact mutations and log buffer so each retry attempt starts clean
        del log_buffer[log_buffer_pre_db:]
        document_ids_added: list[str] = []
        for pf in processed_facts:
            pf.document_id = None
            pf.chunk_id = None

        # Discard any leftover pending stats from a previous failed attempt so
        # retries don't double-count or accumulate unbounded state.
        entity_resolver.discard_pending_stats()

        async with acquire_with_retry(pool) as conn:
            async with conn.transaction():
                # Handle document tracking for all documents
                step_start = time.time()
                # Map None document_id to generated UUIDs
                doc_id_mapping = {}  # Maps original doc_id (including None) to actual doc_id used

                if document_id:
                    # Legacy: single document_id parameter
                    combined_content = "\n".join([c.get("content", "") for c in contents_dicts])
                    retain_params, merged_tags = _build_retain_params(contents_dicts, document_tags)

                    await fact_storage.handle_document_tracking(
                        conn, bank_id, document_id, combined_content, is_first_batch, retain_params, merged_tags
                    )
                    document_ids_added.append(document_id)
                    doc_id_mapping[None] = document_id  # For backwards compatibility
                else:
                    # Handle per-item document_ids (create documents if any item has document_id or if chunks exist)
                    has_any_doc_ids = any(item.get("document_id") for item in contents_dicts)

                    if has_any_doc_ids or chunks:
                        for original_doc_id, doc_contents in contents_by_doc.items():
                            actual_doc_id = original_doc_id

                            # Only create document record if:
                            # 1. Item has explicit document_id, OR
                            # 2. There are chunks (need document for chunk storage)
                            should_create_doc = (original_doc_id is not None) or chunks

                            if should_create_doc:
                                if actual_doc_id is None:
                                    # No document_id but have chunks - generate one
                                    actual_doc_id = str(uuid.uuid4())

                                # Store mapping for later use
                                doc_id_mapping[original_doc_id] = actual_doc_id

                                # Combine content for this document
                                combined_content = "\n".join([c.get("content", "") for _, c in doc_contents])
                                retain_params, merged_tags = _build_retain_params(
                                    contents_dicts, document_tags, doc_contents=doc_contents
                                )

                                await fact_storage.handle_document_tracking(
                                    conn,
                                    bank_id,
                                    actual_doc_id,
                                    combined_content,
                                    is_first_batch,
                                    retain_params,
                                    merged_tags,
                                )
                                document_ids_added.append(actual_doc_id)

                if document_ids_added:
                    log_buffer.append(
                        f"[2.5] Document tracking: {len(document_ids_added)} documents in {time.time() - step_start:.3f}s"
                    )

                # Store chunks and map to facts for all documents
                step_start = time.time()
                chunk_id_map_by_doc = {}  # Maps (doc_id, chunk_index) -> chunk_id

                if chunks:
                    # Group chunks by their source document
                    chunks_by_doc = defaultdict(list)
                    for chunk in chunks:
                        # chunk.content_index tells us which content this chunk came from
                        original_doc_id = contents_dicts[chunk.content_index].get("document_id")
                        # Map to actual document_id (handles None -> generated UUID mapping)
                        actual_doc_id = doc_id_mapping.get(original_doc_id, original_doc_id)
                        if actual_doc_id is None and document_id:
                            actual_doc_id = document_id
                        chunks_by_doc[actual_doc_id].append(chunk)

                    # Store chunks for each document
                    for doc_id, doc_chunks in chunks_by_doc.items():
                        chunk_id_map = await chunk_storage.store_chunks_batch(conn, bank_id, doc_id, doc_chunks)
                        # Store mapping with document context
                        for chunk_idx, chunk_id in chunk_id_map.items():
                            chunk_id_map_by_doc[(doc_id, chunk_idx)] = chunk_id

                    log_buffer.append(
                        f"[3] Store chunks: {len(chunks)} chunks for {len(chunks_by_doc)} documents in {time.time() - step_start:.3f}s"
                    )

                    # Map chunk_ids and document_ids to facts
                    for fact, processed_fact in zip(extracted_facts, processed_facts):
                        # Get the original document_id for this fact's source content
                        original_doc_id = contents_dicts[fact.content_index].get("document_id")
                        # Map to actual document_id (handles None -> generated UUID mapping)
                        actual_doc_id = doc_id_mapping.get(original_doc_id, original_doc_id)
                        if actual_doc_id is None and document_id:
                            actual_doc_id = document_id

                        # Set document_id on the fact
                        processed_fact.document_id = actual_doc_id

                        # Map chunk_id if this fact came from a chunk
                        if fact.chunk_index is not None:
                            # Look up chunk_id using (doc_id, chunk_index)
                            chunk_id = chunk_id_map_by_doc.get((actual_doc_id, fact.chunk_index))
                            if chunk_id:
                                processed_fact.chunk_id = chunk_id
                else:
                    # No chunks - still need to set document_id on facts
                    for fact, processed_fact in zip(extracted_facts, processed_facts):
                        original_doc_id = contents_dicts[fact.content_index].get("document_id")
                        # Map to actual document_id (handles None -> generated UUID mapping)
                        actual_doc_id = doc_id_mapping.get(original_doc_id, original_doc_id)
                        if actual_doc_id is None and document_id:
                            actual_doc_id = document_id
                        processed_fact.document_id = actual_doc_id

                non_duplicate_facts = processed_facts

                # Insert facts (document_id is now stored per-fact)
                step_start = time.time()
                unit_ids = await fact_storage.insert_facts_batch(conn, bank_id, non_duplicate_facts)
                log_buffer.append(f"[5] Insert facts: {len(unit_ids)} units in {time.time() - step_start:.3f}s")

                # Process entities
                step_start = time.time()
                # Build map of content_index -> user entities for merging
                user_entities_per_content = {
                    idx: content.entities for idx, content in enumerate(contents) if content.entities
                }
                entity_links = await entity_processing.process_entities_batch(
                    entity_resolver,
                    conn,
                    bank_id,
                    unit_ids,
                    non_duplicate_facts,
                    log_buffer,
                    user_entities_per_content=user_entities_per_content,
                    entity_labels=getattr(config, "entity_labels", None),
                )
                log_buffer.append(f"[6] Process entities: {len(entity_links)} links in {time.time() - step_start:.3f}s")

                # Create temporal links
                step_start = time.time()
                temporal_link_count = await link_creation.create_temporal_links_batch(conn, bank_id, unit_ids)
                log_buffer.append(f"[7] Temporal links: {temporal_link_count} links in {time.time() - step_start:.3f}s")

                # Create semantic links
                step_start = time.time()
                embeddings_for_links = [fact.embedding for fact in non_duplicate_facts]
                semantic_link_count = await link_creation.create_semantic_links_batch(
                    conn, bank_id, unit_ids, embeddings_for_links
                )
                log_buffer.append(f"[8] Semantic links: {semantic_link_count} links in {time.time() - step_start:.3f}s")

                # Insert entity links
                step_start = time.time()
                if entity_links:
                    await entity_processing.insert_entity_links_batch(conn, entity_links)
                log_buffer.append(
                    f"[9] Entity links: {len(entity_links) if entity_links else 0} links in {time.time() - step_start:.3f}s"
                )

                # Create causal links
                step_start = time.time()
                causal_link_count = await link_creation.create_causal_links_batch(conn, unit_ids, non_duplicate_facts)
                log_buffer.append(f"[10] Causal links: {causal_link_count} links in {time.time() - step_start:.3f}s")

                # Map results back to original content items
                result_unit_ids = _map_results_to_contents(contents, extracted_facts, unit_ids)

                # Transactional outbox: queue any side-effect tasks (e.g. webhook deliveries)
                # inside the same transaction so they are atomically committed with the retain data.
                if outbox_callback:
                    await outbox_callback(conn)

            # Flush entity stats (mention_count / last_seen) now that the transaction
            # has committed.  Uses a fresh pool connection — no locks held.
            await entity_resolver.flush_pending_stats()

            # Log final summary
            total_time = time.time() - start_time
            log_buffer.append(f"{'=' * 60}")
            log_buffer.append(f"RETAIN_BATCH COMPLETE: {len(unit_ids)} units in {total_time:.3f}s")
            if document_ids_added:
                log_buffer.append(f"Documents: {', '.join(document_ids_added)}")
            log_buffer.append(f"{'=' * 60}")

            logger.info("\n" + "\n".join(log_buffer) + "\n")

    await retry_with_backoff(_run_db_work)
    return result_unit_ids, usage


def _map_results_to_contents(
    contents: list[RetainContent],
    extracted_facts: list[ExtractedFact],
    unit_ids: list[str],
) -> list[list[str]]:
    """Map created unit IDs back to original content items."""
    facts_by_content: dict[int, list[int]] = {i: [] for i in range(len(contents))}
    for i, fact in enumerate(extracted_facts):
        facts_by_content[fact.content_index].append(i)

    result_unit_ids = []
    unit_idx = 0
    for content_index in range(len(contents)):
        content_unit_ids = []
        for _ in facts_by_content[content_index]:
            content_unit_ids.append(unit_ids[unit_idx])
            unit_idx += 1
        result_unit_ids.append(content_unit_ids)

    return result_unit_ids
