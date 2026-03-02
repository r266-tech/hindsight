import { after } from 'next/server';
import { bot } from '@/lib/bot';
import { findPendingPost, removePendingPost } from '@/lib/pending-posts';
import { postToChannel, replyInThread } from '@/lib/slack';
import { formatSocialPost } from '@/app/api/webhooks/github/route';

type Platform = keyof typeof bot.webhooks;

const SOCIAL_CHANNEL_ID = process.env.SLACK_SOCIAL_CHANNEL_ID;

export async function POST(
  request: Request,
  context: { params: Promise<{ platform: string }> }
) {
  const { platform } = await context.params;

  // --- Intercept Slack DM replies for pending social posts ---
  if (platform === 'slack') {
    const cloned = request.clone();
    try {
      const body = await cloned.json();

      console.log('[slack-intercept] event type:', body.type, 'event:', body.event?.type, 'channel_type:', body.event?.channel_type, 'bot_id:', body.event?.bot_id);

      if (body.type === 'event_callback' && body.event?.type === 'message') {
        const event = body.event;
        // DM message (not from a bot)
        if (event.channel_type === 'im' && !event.bot_id && event.user) {
          const pending = findPendingPost(event.channel);
          console.log('[slack-intercept] DM from user, channel:', event.channel, 'pending:', !!pending, 'text:', event.text?.slice(0, 50));
          if (pending) {
            // Handle synchronously to ensure it runs before response
            try {
              await handleLinkReply(event.channel, pending.dmThreadTs, event.text, pending);
            } catch (err) {
              console.error('[slack-link-reply] Error:', err);
              await replyInThread(
                event.channel,
                pending.dmThreadTs,
                'Something went wrong posting to the social channel. Try again?'
              );
            }
            return new Response('', { status: 200 });
          }
        }
      }
    } catch {
      // Not JSON or parse error — fall through to chat framework
    }
  }

  const handler = bot.webhooks[platform as Platform];
  if (!handler) {
    return new Response(`Unknown platform: ${platform}`, { status: 404 });
  }

  return handler(request, {
    waitUntil: (task) => after(() => task),
  });
}

function parseLinks(text: string): { blog?: string; twitter?: string; linkedin?: string } {
  const urls = text.match(/https?:\/\/[^\s>|]+/g) || [];
  const links: { blog?: string; twitter?: string; linkedin?: string } = {};
  for (const url of urls) {
    const lower = url.toLowerCase();
    if (lower.includes('twitter.com') || lower.includes('x.com')) {
      links.twitter = url;
    } else if (lower.includes('linkedin.com')) {
      links.linkedin = url;
    } else {
      links.blog = url;
    }
  }
  return links;
}

async function handleLinkReply(
  channelId: string,
  threadTs: string,
  text: string,
  pending: { title: string; description: string; suggestions: string[] }
) {
  const skip = text.trim().toLowerCase() === 'skip';
  const links = skip ? undefined : parseLinks(text);

  if (!skip && !links?.blog && !links?.twitter && !links?.linkedin) {
    await replyInThread(
      channelId,
      threadTs,
      'No URLs found. Send the links (blog, Twitter/X, LinkedIn) or reply *skip* to post without them.'
    );
    return;
  }

  if (!SOCIAL_CHANNEL_ID) {
    await replyInThread(channelId, threadTs, 'No social channel configured.');
    removePendingPost(channelId);
    return;
  }

  const message = formatSocialPost({
    title: pending.title,
    description: pending.description,
    suggestions: pending.suggestions,
    links,
  });

  await postToChannel(SOCIAL_CHANNEL_ID, message);
  removePendingPost(channelId);

  await replyInThread(channelId, threadTs, 'Posted to the social channel.');
}
