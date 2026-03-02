/**
 * Slack helpers — proactive posting, DMs, and thread replies.
 *
 * Uses the same SLACK_BOT_TOKEN as the chat adapter.
 */

import { WebClient } from '@slack/web-api';

let client: WebClient | null = null;

function getClient(): WebClient {
  if (!client) {
    const token = process.env.SLACK_BOT_TOKEN;
    if (!token) throw new Error('SLACK_BOT_TOKEN is not set');
    client = new WebClient(token);
  }
  return client;
}

/** Post a message to a Slack channel. Returns the message timestamp. */
export async function postToChannel(channelId: string, text: string): Promise<string> {
  const result = await getClient().chat.postMessage({ channel: channelId, text });
  return result.ts!;
}

/** Reply in a thread. */
export async function replyInThread(
  channelId: string,
  threadTs: string,
  text: string
): Promise<void> {
  await getClient().chat.postMessage({
    channel: channelId,
    thread_ts: threadTs,
    text,
  });
}

/** Send a DM to a user. Returns the DM channel ID and message timestamp. */
export async function sendDM(
  userId: string,
  text: string
): Promise<{ channelId: string; ts: string }> {
  const c = getClient();
  const { channel } = await c.conversations.open({ users: userId });
  const result = await c.chat.postMessage({
    channel: channel!.id!,
    text,
  });
  return { channelId: channel!.id!, ts: result.ts! };
}
