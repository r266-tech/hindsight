/**
 * In-memory store for pending social posts awaiting blog links from the user.
 *
 * Uses globalThis to survive Next.js HMR and share state across route handlers.
 */

export interface PendingPost {
  title: string;
  filename: string;
  description: string;
  suggestions: string[];
  dmThreadTs: string;
}

// Attach to globalThis so the Map is shared across Next.js route modules
const g = globalThis as unknown as { __pendingPosts?: Map<string, PendingPost> };
if (!g.__pendingPosts) g.__pendingPosts = new Map();
const store = g.__pendingPosts;

export function storePendingPost(channelId: string, post: PendingPost) {
  store.set(channelId, post);
}

export function findPendingPost(channelId: string): PendingPost | undefined {
  return store.get(channelId);
}

export function removePendingPost(channelId: string) {
  store.delete(channelId);
}
