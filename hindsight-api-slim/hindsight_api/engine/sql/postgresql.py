"""PostgreSQL SQL dialect implementation.

Provides PostgreSQL-specific SQL fragments for parameter binding, JSON operators,
vector distance (pgvector), full-text search (VectorChord BM25 / tsvector),
and other non-portable patterns.
"""

from .base import SQLDialect


class PostgreSQLDialect(SQLDialect):
    """SQL dialect for PostgreSQL (asyncpg)."""

    # -- Parameter binding -----------------------------------------------

    def param(self, n: int) -> str:
        return f"${n}"

    # -- Type casting ----------------------------------------------------

    def cast(self, param: str, type_name: str) -> str:
        return f"{param}::{type_name}"

    # -- Vector operations -----------------------------------------------

    def vector_distance(self, col: str, param: str) -> str:
        return f"{col} <=> {param}::vector"

    def vector_similarity(self, col: str, param: str) -> str:
        return f"1 - ({col} <=> {param}::vector)"

    # -- JSON operations -------------------------------------------------

    def json_extract_text(self, col: str, key: str) -> str:
        return f"{col} ->> '{key}'"

    def json_contains(self, col: str, param: str) -> str:
        return f"{col} @> {param}::jsonb"

    def json_merge(self, col: str, param: str) -> str:
        return f"{col} || {param}::jsonb"

    # -- Text search -----------------------------------------------------

    def text_search_score(self, col: str, query_param: str, *, index_name: str | None = None) -> str:
        if index_name:
            # VectorChord BM25
            return f"-({col} <@> to_bm25query({query_param}, '{index_name}'))"
        # Fallback to tsvector
        return f"ts_rank_cd({col}, to_tsquery({query_param}))"

    def text_search_order(self, col: str, query_param: str, *, index_name: str | None = None) -> str:
        if index_name:
            # VectorChord BM25 — lower distance = better, so ASC
            return f"{col} <@> to_bm25query({query_param}, '{index_name}') ASC"
        return f"ts_rank_cd({col}, to_tsquery({query_param})) DESC"

    # -- Fuzzy string matching -------------------------------------------

    def similarity(self, col: str, param: str) -> str:
        return f"similarity({col}, {param})"

    # -- Upsert ----------------------------------------------------------

    def upsert(
        self,
        table: str,
        columns: list[str],
        conflict_columns: list[str],
        update_columns: list[str],
    ) -> str:
        col_list = ", ".join(columns)
        placeholders = ", ".join(f"${i + 1}" for i in range(len(columns)))
        conflict = ", ".join(conflict_columns)

        if not update_columns:
            return f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) ON CONFLICT ({conflict}) DO NOTHING"

        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_columns)
        return (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) ON CONFLICT ({conflict}) DO UPDATE SET {updates}"
        )

    # -- Bulk operations -------------------------------------------------

    def bulk_unnest(self, param_types: list[tuple[str, str]]) -> str:
        args = ", ".join(f"{p}::{t}" for p, t in param_types)
        return f"unnest({args})"

    # -- Pagination ------------------------------------------------------

    def limit_offset(self, limit_param: str, offset_param: str) -> str:
        return f"LIMIT {limit_param} OFFSET {offset_param}"

    # -- RETURNING clause ------------------------------------------------

    def returning(self, columns: list[str]) -> str:
        return f"RETURNING {', '.join(columns)}"

    # -- Pattern matching ------------------------------------------------

    def ilike(self, col: str, param: str) -> str:
        return f"{col} ILIKE {param}"

    # -- Array operations ------------------------------------------------

    def array_any(self, param: str) -> str:
        return f"= ANY({param})"

    def array_all(self, param: str) -> str:
        return f"!= ALL({param})"

    def array_contains(self, col: str, param: str) -> str:
        return f"{col} @> {param}::varchar[]"

    # -- Locking ---------------------------------------------------------

    def for_update_skip_locked(self) -> str:
        return "FOR UPDATE SKIP LOCKED"

    def advisory_lock(self, id_param: str) -> str:
        return f"pg_try_advisory_lock({id_param})"

    # -- UUID generation -------------------------------------------------

    def generate_uuid(self) -> str:
        return "gen_random_uuid()"

    # -- Misc ------------------------------------------------------------

    def greatest(self, *args: str) -> str:
        return f"GREATEST({', '.join(args)})"

    def current_timestamp(self) -> str:
        return "now()"

    def array_agg(self, expr: str) -> str:
        return f"array_agg({expr})"
