/**
 * Blog Ingestion Script
 *
 * Ingests markdown blog posts into Hindsight for the marketing bot.
 * Parses frontmatter (title, date, author, tags) and retains each post
 * with appropriate metadata.
 *
 * Usage: npx tsx scripts/ingest-blog.ts /path/to/blog/repo/content
 *
 * Env vars:
 *   HINDSIGHT_API_URL=http://localhost:8888   (default)
 *   HINDSIGHT_BANK_ID=marketing-posts         (default)
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative, extname } from 'node:path';

const BASE_URL = process.env.HINDSIGHT_API_URL ?? 'http://localhost:8888';
const BANK_ID = process.env.HINDSIGHT_BANK_ID ?? 'marketing-posts';

// --- Frontmatter parser ---

interface Frontmatter {
  title?: string;
  date?: string;
  author?: string;
  tags?: string[];
  [key: string]: unknown;
}

function parseFrontmatter(content: string): { data: Frontmatter; body: string } {
  const match = content.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$/);
  if (!match) {
    // No frontmatter — try to extract title from first # heading
    const headingMatch = content.match(/^#\s+(.+)$/m);
    const data: Frontmatter = {};
    if (headingMatch) data.title = headingMatch[1].trim();
    return { data, body: content };
  }

  const raw = match[1];
  const body = match[2];
  const data: Frontmatter = {};

  for (const line of raw.split('\n')) {
    const colonIdx = line.indexOf(':');
    if (colonIdx === -1) continue;

    const key = line.slice(0, colonIdx).trim();
    let value = line.slice(colonIdx + 1).trim();

    // Remove surrounding quotes
    if ((value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }

    // Parse YAML-style inline arrays: [tag1, tag2]
    if (value.startsWith('[') && value.endsWith(']')) {
      data[key] = value
        .slice(1, -1)
        .split(',')
        .map((s) => s.trim().replace(/^["']|["']$/g, ''))
        .filter(Boolean);
    } else {
      (data as Record<string, unknown>)[key] = value;
    }
  }

  return { data, body };
}

// --- File discovery ---

function findMarkdownFiles(dir: string): string[] {
  const results: string[] = [];

  function walk(currentDir: string) {
    for (const entry of readdirSync(currentDir)) {
      const fullPath = join(currentDir, entry);
      const stat = statSync(fullPath);

      if (stat.isDirectory()) {
        if (entry === 'node_modules' || entry === '.git') continue;
        walk(fullPath);
      } else {
        const ext = extname(entry).toLowerCase();
        if (ext === '.md' || ext === '.mdx') {
          results.push(fullPath);
        }
      }
    }
  }

  walk(dir);
  return results;
}

// --- Hindsight API ---

async function ensureBank() {
  await fetch(`${BASE_URL}/v1/default/banks/${BANK_ID}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  });
}

async function retainPost(
  content: string,
  options: {
    tags: string[];
    metadata: Record<string, string>;
    timestamp?: string;
    documentId: string;
  }
) {
  const res = await fetch(`${BASE_URL}/v1/default/banks/${BANK_ID}/memories`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      items: [
        {
          content,
          tags: options.tags,
          metadata: options.metadata,
          timestamp: options.timestamp,
          document_id: options.documentId,
        },
      ],
      async: false,
    }),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`retain failed (${res.status}): ${text}`);
  }

  return res.json();
}

// --- Main ---

async function main() {
  const dir = process.argv[2];
  if (!dir) {
    console.error('Usage: npx tsx scripts/ingest-blog.ts /path/to/blog/content');
    process.exit(1);
  }

  console.log(`Scanning ${dir} for markdown files...`);
  const files = findMarkdownFiles(dir);
  console.log(`Found ${files.length} markdown file(s).`);

  if (files.length === 0) return;

  await ensureBank();
  console.log(`Bank "${BANK_ID}" ensured.\n`);

  let ingested = 0;
  let failed = 0;

  for (const filePath of files) {
    const relPath = relative(dir, filePath);
    const raw = readFileSync(filePath, 'utf-8');
    const { data, body } = parseFrontmatter(raw);

    const tags = ['marketing', 'blog'];
    if (Array.isArray(data.tags)) {
      tags.push(...data.tags.map(String));
    }

    const metadata: Record<string, string> = { filename: relPath };
    if (data.title) metadata.title = String(data.title);
    if (data.author) metadata.author = String(data.author);
    if (data.date) metadata.date = String(data.date);

    try {
      await retainPost(body, {
        tags,
        metadata,
        timestamp: data.date ? String(data.date) : undefined,
        documentId: `blog:${relPath}`,
      });
      ingested++;
      console.log(`  [ok] ${relPath}${data.title ? ` — "${data.title}"` : ''}`);
    } catch (err) {
      failed++;
      console.error(`  [fail] ${relPath}: ${err}`);
    }
  }

  console.log(`\nDone. Ingested: ${ingested}, Failed: ${failed}`);
}

main();
