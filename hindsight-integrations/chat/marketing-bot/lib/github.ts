/**
 * GitHub API helpers for webhook verification and content fetching.
 */

import { createHmac, timingSafeEqual } from 'node:crypto';
import { basename } from 'node:path';

/**
 * Verify a GitHub webhook signature (HMAC-SHA256).
 * Returns true if the signature matches.
 */
export function verifyWebhookSignature(
  payload: string,
  signature: string,
  secret: string
): boolean {
  const expected = 'sha256=' + createHmac('sha256', secret).update(payload).digest('hex');
  if (expected.length !== signature.length) return false;
  return timingSafeEqual(Buffer.from(expected), Buffer.from(signature));
}

/**
 * Check if a filename is a blog file we should ingest.
 * Accepts root-level .md files, skips README.md, CLAUDE.md, and files in subdirectories.
 */
export function isBlogFile(filename: string): boolean {
  const lower = filename.toLowerCase();
  if (!lower.endsWith('.md')) return false;
  // Skip known non-blog files
  const base = basename(filename).toLowerCase();
  if (base === 'readme.md' || base === 'claude.md') return false;
  // Accept root-level files or files in blog/ directory
  const depth = filename.split('/').length;
  if (depth > 2) return false; // skip deeply nested files
  return true;
}

interface PullRequestFile {
  filename: string;
  status: string; // 'added' | 'modified' | 'removed' | 'renamed' | ...
}

/**
 * List files changed in a pull request.
 */
export async function listPullRequestFiles(
  owner: string,
  repo: string,
  prNumber: number,
  token?: string
): Promise<PullRequestFile[]> {
  const headers: Record<string, string> = {
    Accept: 'application/vnd.github+json',
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(
    `https://api.github.com/repos/${owner}/${repo}/pulls/${prNumber}/files`,
    { headers }
  );
  if (!res.ok) {
    throw new Error(`GitHub API error listing PR files: ${res.status} ${await res.text()}`);
  }
  return res.json() as Promise<PullRequestFile[]>;
}

/**
 * Fetch raw file content from a GitHub repo at a given ref.
 */
export async function fetchFileContent(
  owner: string,
  repo: string,
  path: string,
  ref: string,
  token?: string
): Promise<string> {
  const headers: Record<string, string> = {
    Accept: 'application/vnd.github.raw+json',
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(
    `https://api.github.com/repos/${owner}/${repo}/contents/${path}?ref=${ref}`,
    { headers }
  );
  if (!res.ok) {
    throw new Error(`GitHub API error fetching ${path}: ${res.status} ${await res.text()}`);
  }
  return res.text();
}

/**
 * Extract blog title from the first `# Heading` line.
 * Falls back to a cleaned-up version of the filename.
 */
export function parseBlogTitle(content: string, filename: string): string {
  const match = content.match(/^#\s+(.+)$/m);
  if (match) return match[1].trim();
  // Fallback: clean filename — strip extension, replace separators with spaces
  return basename(filename, '.md')
    .replace(/[-_]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}
