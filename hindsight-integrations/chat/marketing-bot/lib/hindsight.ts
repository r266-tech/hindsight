import type { HindsightClient, RecallResponse, RetainResponse, ReflectResponse } from '@vectorize-io/hindsight-chat';

const BASE_URL = process.env.HINDSIGHT_API_URL ?? 'http://localhost:8888';
const API_KEY = process.env.HINDSIGHT_API_KEY;

function headers(): Record<string, string> {
  const h: Record<string, string> = { 'Content-Type': 'application/json' };
  if (API_KEY) h['Authorization'] = `Bearer ${API_KEY}`;
  return h;
}

const ensuredBanks = new Set<string>();

async function ensureBank(bankId: string) {
  if (ensuredBanks.has(bankId)) return;
  await fetch(`${BASE_URL}/v1/default/banks/${bankId}`, {
    method: 'PUT',
    headers: headers(),
    body: JSON.stringify({}),
  });
  ensuredBanks.add(bankId);
}

/**
 * Minimal Hindsight client that talks directly to the REST API.
 * No SDK dependency needed for testing.
 */
export const hindsight: HindsightClient = {
  async retain(bankId, content, options) {
    await ensureBank(bankId);
    const res = await fetch(`${BASE_URL}/v1/default/banks/${bankId}/memories`, {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify({
        items: [
          {
            content,
            timestamp: options?.timestamp,
            context: options?.context,
            metadata: options?.metadata,
            document_id: options?.documentId,
            tags: options?.tags,
          },
        ],
        async: options?.async ?? false,
      }),
    });
    if (!res.ok) throw new Error(`retain failed: ${res.status} ${await res.text()}`);
    return (await res.json()) as RetainResponse;
  },

  async recall(bankId, query, options) {
    await ensureBank(bankId);
    const res = await fetch(`${BASE_URL}/v1/default/banks/${bankId}/memories/recall`, {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify({
        query,
        types: options?.types,
        max_tokens: options?.maxTokens,
        budget: options?.budget ?? 'mid',
        trace: options?.trace ?? false,
        query_timestamp: options?.queryTimestamp,
        include_entities: options?.includeEntities ?? false,
        max_entity_tokens: options?.maxEntityTokens,
        include_chunks: options?.includeChunks ?? false,
        max_chunk_tokens: options?.maxChunkTokens,
      }),
    });
    if (!res.ok) throw new Error(`recall failed: ${res.status} ${await res.text()}`);
    return (await res.json()) as RecallResponse;
  },

  async reflect(bankId, query, options) {
    await ensureBank(bankId);
    const res = await fetch(`${BASE_URL}/v1/default/banks/${bankId}/reflect`, {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify({
        query,
        context: options?.context,
        budget: options?.budget ?? 'mid',
        max_tokens: options?.maxTokens,
      }),
    });
    if (!res.ok) throw new Error(`reflect failed: ${res.status} ${await res.text()}`);
    return (await res.json()) as ReflectResponse;
  },
};
