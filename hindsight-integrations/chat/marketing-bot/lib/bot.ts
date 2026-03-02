/**
 * Marketing Post Tracker Bot
 *
 * A Slack bot that helps the team track marketing posts. Team members @mention
 * the bot to log posts (platform, topic, URL) or ask questions about past posts.
 *
 * Required env vars:
 *   SLACK_BOT_TOKEN=xoxb-...
 *   SLACK_SIGNING_SECRET=...
 *   OPENAI_API_KEY=sk-...
 *   HINDSIGHT_API_URL=http://localhost:8888   (default)
 *   HINDSIGHT_BANK_ID=marketing-posts         (default)
 *
 * GitHub webhook env vars (for blog ingestion via /api/webhooks/github):
 *   GITHUB_WEBHOOK_SECRET=...                 (required for webhook)
 *   GITHUB_TOKEN=ghp_...                      (optional, avoids rate limits)
 *   SLACK_SOCIAL_CHANNEL_ID=C0123456789       (optional, channel for social suggestions)
 *   SLACK_DM_USER_ID=U0123456789              (optional, DM this user for blog links before posting)
 */

import { Chat } from 'chat';
import { createSlackAdapter } from '@chat-adapter/slack';
import { createMemoryState } from '@chat-adapter/state-memory';
import { withHindsightChat } from '@vectorize-io/hindsight-chat';
import { generateText } from 'ai';
import { openai } from '@ai-sdk/openai';
import { hindsight } from './hindsight';

const BANK_ID = process.env.HINDSIGHT_BANK_ID ?? 'marketing-posts';

const SYSTEM_PROMPT = `You are a Marketing Post Tracker bot. Your job is to help the team track and recall marketing posts across platforms (LinkedIn, Twitter/X, blog, YouTube, etc.).

You handle two kinds of requests:

**Logging a post:** When a team member tells you about a post they made (e.g. "I posted a blog about AI agents on LinkedIn"), acknowledge it and confirm the details you captured (platform, topic, URL if provided, author). Be concise — a short confirmation is enough.

**Querying past posts:** When someone asks about past posts (e.g. "What have we posted this week?" or "Any posts about AI?"), recall what you know and summarize clearly. List posts with platform, topic, date if known, and author.

Keep responses brief and useful. Use bullet points for listing multiple posts.`;

export const bot = new Chat({
  userName: 'marketing-tracker',
  adapters: { slack: createSlackAdapter() },
  state: createMemoryState(),
});

// --- @mention handler: log posts or answer queries ---
bot.onNewMention(
  withHindsightChat(
    {
      client: hindsight,
      bankId: () => BANK_ID,
      retain: { enabled: true, tags: ['marketing'] },
    },
    async (thread, message, ctx) => {
      await thread.subscribe();

      const memories = ctx.memoriesAsSystemPrompt();
      const system = [
        SYSTEM_PROMPT,
        memories
          ? `\nHere is what you know about past marketing posts:\n${memories}`
          : '\nYou have no records of past marketing posts yet.',
      ].join('\n');

      const { text } = await generateText({
        model: openai('gpt-4o-mini'),
        system,
        prompt: message.text,
      });

      await thread.post(text);

      await ctx.retain(
        `User: ${message.text}\nAssistant: ${text}`
      );
    }
  )
);

// --- Thread follow-up handler ---
bot.onSubscribedMessage(
  withHindsightChat(
    {
      client: hindsight,
      bankId: () => BANK_ID,
    },
    async (thread, message, ctx) => {
      const memories = ctx.memoriesAsSystemPrompt();
      const system = [
        SYSTEM_PROMPT,
        'This is a follow-up message in an ongoing thread.',
        memories
          ? `\nHere is what you know about past marketing posts:\n${memories}`
          : '',
      ].join('\n');

      const { text } = await generateText({
        model: openai('gpt-4o-mini'),
        system,
        prompt: message.text,
      });

      await thread.post(text);

      await ctx.retain(
        `User (follow-up): ${message.text}\nAssistant: ${text}`
      );
    }
  )
);
