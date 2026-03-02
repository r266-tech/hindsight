/**
 * GitHub Webhook Endpoint
 *
 * Listens for merged PRs on the blog content repo. When a PR merges:
 * 1. Fetches new/modified markdown files
 * 2. Ingests them into Hindsight
 * 3. Generates social content and DMs the user to collect blog links
 * 4. Once links are received, posts the final social content to the channel
 */

import { after, NextResponse } from 'next/server';
import { generateText } from 'ai';
import { openai } from '@ai-sdk/openai';
import {
  verifyWebhookSignature,
  isBlogFile,
  listPullRequestFiles,
  fetchFileContent,
  parseBlogTitle,
} from '@/lib/github';
import { hindsight } from '@/lib/hindsight';
import { postToChannel, sendDM } from '@/lib/slack';
import { storePendingPost } from '@/lib/pending-posts';

const BANK_ID = process.env.HINDSIGHT_BANK_ID ?? 'marketing-posts';
const WEBHOOK_SECRET = process.env.GITHUB_WEBHOOK_SECRET;
const GITHUB_TOKEN = process.env.GITHUB_TOKEN;
const SOCIAL_CHANNEL_ID = process.env.SLACK_SOCIAL_CHANNEL_ID;
const DM_USER_ID = process.env.SLACK_DM_USER_ID;

export async function POST(request: Request) {
  // --- Signature verification ---
  if (!WEBHOOK_SECRET) {
    return NextResponse.json({ error: 'Webhook secret not configured' }, { status: 500 });
  }

  const body = await request.text();
  const signature = request.headers.get('x-hub-signature-256') ?? '';

  if (!verifyWebhookSignature(body, signature, WEBHOOK_SECRET)) {
    return NextResponse.json({ error: 'Invalid signature' }, { status: 401 });
  }

  // --- Filter to merged pull requests ---
  const event = request.headers.get('x-github-event');
  if (event !== 'pull_request') {
    return NextResponse.json({ ok: true, skipped: 'not a pull_request event' });
  }

  const payload = JSON.parse(body);
  if (payload.action !== 'closed' || !payload.pull_request?.merged) {
    return NextResponse.json({ ok: true, skipped: 'not a merged PR' });
  }

  const pr = payload.pull_request;
  const owner = payload.repository.owner.login;
  const repo = payload.repository.name;
  const prNumber: number = pr.number;
  const mergeRef: string = pr.merge_commit_sha;

  // Return 200 immediately, process in background
  after(async () => {
    try {
      await processMergedPR(owner, repo, prNumber, mergeRef);
    } catch (err) {
      console.error('[github-webhook] Error processing merged PR:', err);
    }
  });

  return NextResponse.json({ ok: true, processing: true });
}

async function processMergedPR(
  owner: string,
  repo: string,
  prNumber: number,
  mergeRef: string
) {
  const files = await listPullRequestFiles(owner, repo, prNumber, GITHUB_TOKEN);

  const blogFiles = files.filter(
    (f) => (f.status === 'added' || f.status === 'modified') && isBlogFile(f.filename)
  );

  if (blogFiles.length === 0) {
    console.log(`[github-webhook] PR #${prNumber}: no blog files changed, skipping.`);
    return;
  }

  console.log(
    `[github-webhook] PR #${prNumber}: processing ${blogFiles.length} blog file(s)...`
  );

  for (const file of blogFiles) {
    try {
      // 1. Fetch content
      const content = await fetchFileContent(owner, repo, file.filename, mergeRef, GITHUB_TOKEN);
      const title = parseBlogTitle(content, file.filename);

      // 2. Ingest into Hindsight
      await hindsight.retain(BANK_ID, content, {
        tags: ['marketing', 'blog'],
        metadata: { filename: file.filename, title },
        documentId: `blog:${file.filename}`,
      });
      console.log(`[github-webhook]   retained: ${file.filename} — "${title}"`);

      // 3. Generate social content
      const { description, suggestions } = await generateSocialContent(title, content);

      // 4. DM user for links, or post directly if no DM user configured
      if (DM_USER_ID && SOCIAL_CHANNEL_ID) {
        const dmText = [
          `*New blog post ingested:* "${title}"`,
          '',
          `*Description:*`,
          description,
          '',
          `*Quote retweet suggestions:*`,
          ...suggestions.map((s, i) => `${i + 1}. ${s}`),
          '',
          `Reply to this thread with the blog links so I can post to the social channel.`,
          `Send them one per line in any order — I'll figure out which is which:`,
          `\u2022 Blog URL`,
          `\u2022 Twitter/X URL`,
          `\u2022 LinkedIn URL`,
          '',
          `Or reply *skip* to post without links.`,
        ].join('\n');

        const { channelId, ts } = await sendDM(DM_USER_ID, dmText);
        storePendingPost(channelId, {
          title,
          filename: file.filename,
          description,
          suggestions,
          dmThreadTs: ts,
        });
        console.log(`[github-webhook]   DM sent for link collection`);
      } else if (SOCIAL_CHANNEL_ID) {
        // No DM user configured — post directly without links
        const text = formatSocialPost({ title, description, suggestions });
        await postToChannel(SOCIAL_CHANNEL_ID, text);
        console.log(`[github-webhook]   posted to social channel`);
      }
    } catch (err) {
      console.error(`[github-webhook]   error processing ${file.filename}:`, err);
    }
  }
}

async function generateSocialContent(
  title: string,
  content: string
): Promise<{ description: string; suggestions: string[] }> {
  const { text } = await generateText({
    model: openai('gpt-4o-mini'),
    prompt: [
      `Blog post title: "${title}"\n\nContent:\n`,
      content.slice(0, 3000),
      '\n\n---\n\n',
      'Write the following about this blog post:\n\n',
      'DESCRIPTION: A 2-3 sentence summary of the blog post. Write in third person. No marketing hype, no emojis.\n\n',
      'SUGGESTION_1: A quote-retweet style post for X/Twitter under 280 characters. Write as if sharing the post from a company account. No hashtags, no emojis.\n\n',
      'SUGGESTION_2: A second quote-retweet style post for X/Twitter under 280 characters. Different angle than the first. No hashtags, no emojis.\n\n',
      'Respond in exactly this format with each on its own line:\nDESCRIPTION: ...\nSUGGESTION_1: ...\nSUGGESTION_2: ...',
    ].join(''),
  });

  const descMatch = text.match(/DESCRIPTION:\s*(.+)/);
  const s1Match = text.match(/SUGGESTION_1:\s*(.+)/);
  const s2Match = text.match(/SUGGESTION_2:\s*(.+)/);

  return {
    description: descMatch?.[1]?.trim() ?? text,
    suggestions: [s1Match?.[1]?.trim(), s2Match?.[1]?.trim()].filter(Boolean) as string[],
  };
}

export function formatSocialPost(opts: {
  title: string;
  description: string;
  suggestions: string[];
  links?: { blog?: string; twitter?: string; linkedin?: string };
}): string {
  const lines: string[] = [
    `*${opts.title}*`,
    '',
    opts.description,
  ];

  if (opts.links && (opts.links.blog || opts.links.twitter || opts.links.linkedin)) {
    lines.push('', '*Links*');
    if (opts.links.blog) lines.push(`\u2022 <${opts.links.blog}|Read on our blog>`);
    if (opts.links.twitter) lines.push(`\u2022 <${opts.links.twitter}|View on X>`);
    if (opts.links.linkedin) lines.push(`\u2022 <${opts.links.linkedin}|View on LinkedIn>`);
  }

  lines.push('', '*Quote Retweet Suggestions*');
  opts.suggestions.forEach((s, i) => {
    lines.push(`${i + 1}. ${s}`);
  });

  return lines.join('\n');
}
