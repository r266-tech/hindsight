---
title: "OpenClaude: Build a Claude Code Agent with Long-Term Memory — and Take It Everywhere"
authors: [fabioscarsi, nicoloboschi]
date: 2026-03-25
tags: [claude-code, telegram, hindsight, memory, mcp, agents, tutorial]
hide\_table\_of\_contents: true
---

Anthropic just launched **Channels** for Claude Code — persistent background sessions connected to messaging platforms. This means Claude Code can now operate as a fully autonomous agent, reachable also from your phone, always running against your codebase.

Claude Code has a built-in memory system based on markdown files (`CLAUDE.md`, auto-memory), and it works well for static preferences and project instructions. But it wasn't designed for conversational memory — it doesn't extract facts from your discussions, doesn't recall relevant context by semantic similarity, and doesn't build up structured knowledge over time. Close the session, and some richness and depth of what you discussed is gone.

This guide fixes that. We'll set up Claude Code on Telegram and wire it to [Hindsight][1] for true long-term memory — automatic fact extraction, semantic recall, and a knowledge base that grows with every conversation. The result is a persistent AI coding assistant you can talk to from anywhere, that actually learns from your interactions.

If you've been watching what [Openclaw][2] does with Hindsight — this is the same idea, built entirely on Claude Code.

<!-- truncate -->

---

## What We're Building

By the end of this tutorial, you'll have:

1. **A Telegram bot** connected to Claude Code — send it messages from your phone, get responses backed by your full codebase
2. **Automatic memory** powered by Hindsight — every conversation is retained, relevant context is recalled on every prompt
3. **A persistent agent** that gets smarter over time — it remembers your projects, your preferences, your architectural decisions

The stack is simple: Claude Code does the thinking, Telegram provides the interface, Hindsight provides the memory. No custom code, no infrastructure beyond what runs on your machine.

---

## Part 1: Claude Code on Telegram

### Prerequisites

- **Claude Code** installed (`curl -fsSL https://claude.ai/install.sh | bash`)
- **Bun** installed (`curl -fsSL https://bun.sh/install | bash`) — the Telegram plugin requires Bun specifically; Node.js and Deno are not supported
- A **Telegram account**

### Step 1: Create a Telegram Bot

Open Telegram and start a chat with [@BotFather][3].

Send `/newbot` and follow the prompts — pick a name and a username (must end in `bot`). BotFather will give you a token like:

```
1234567890:ABCDefghIJKlmnOPQrstUVwxyz
```

Keep this token for Step 3.

### Step 2: Install the Telegram Plugin

In your Claude Code session, run:

```
/plugin install telegram@claude-plugins-official
/reload-plugins
```

This installs the Telegram MCP plugin and reloads the plugin registry.

### Step 3: Set Your Bot Token

```bash
mkdir -p ~/.claude/channels/telegram
echo "TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN" > ~/.claude/channels/telegram/.env
```

Replace `YOUR_BOT_TOKEN` with the token from BotFather. This file contains a secret — restrict permissions with `chmod 600 ~/.claude/channels/telegram/.env`. You can also export `TELEGRAM_BOT_TOKEN` as a shell environment variable instead (shell takes precedence over the file).

:::note
The `/telegram:configure` skill is only available inside a session running with the `--channels` flag (Step 4). Do not try to run it in a plain Claude Code session.
:::

### Step 4: Launch Claude Code with Channels

Exit your current session and restart with the Telegram channel:

```bash
claude --channels plugin:telegram@claude-plugins-official
```

Claude Code is now running with the Telegram plugin active.

### Step 5: Pair Your Telegram Account

1. Open Telegram and send any message to your bot (e.g. "hello")
2. The bot replies with a 6-character pairing code
3. Back in Claude Code, run:

```
/telegram:access pair <code>
```

Your device is now paired.

### Step 6: Lock Down Access

Switch to allowlist mode so only you can use the bot:

```
/telegram:access policy allowlist
```

Find your Telegram user ID by messaging [@userinfobot][4], then:

```
/telegram:access allow <your_user_id>
```

Anyone not on the allowlist will be silently ignored.

### A Note on Permissions

Claude Code has a permission system that prompts for approval before running certain tools (shell commands, file writes, etc.). These prompts appear in the terminal — **not in Telegram**. If you're interacting purely through your phone, Claude may silently block waiting for approval you can't see.

There are two approaches:

1. **Run with full permissions**: launch with `claude --dangerously-skip-permissions --channels ...` — this gives the agent full autonomy. Appropriate if the bot is only accessible to you (which is why Step 6 matters).
2. **Keep the terminal visible**: leave the Claude Code terminal open on your machine so you can approve permission requests when they come in.

For a truly autonomous Telegram agent, option 1 is the practical choice. Just make sure your allowlist is locked down first.

### What You Have So Far

A working Claude Code agent on Telegram. You can send it messages from your phone, and it responds with full access to your codebase — reading files, running commands, making changes.

But the memory is limited. Claude Code's built-in markdown memory captures preferences and instructions, but it doesn't retain the substance of your conversations — the decisions you explored, the trade-offs you weighed, the context behind why things are the way they are. Restart the session, and that conversational depth is lost. For quick tasks, that's fine. For a long-running assistant, it's a ceiling.

Let's fix that.

---

## Part 2: Adding Long-Term Memory with Hindsight

[Hindsight][5] is a biomimetic memory engine — it doesn't just store conversations, it *understands* them. When you retain a conversation, Hindsight extracts discrete, structured facts: decisions, preferences, relationships, technical context. When you recall, it retrieves facts by semantic relevance to your current query, not by timestamp or keyword. The result is memory that behaves more like human recollection than a search index — surfacing what matters, filtering out what doesn't.

The [Openclaw integration][6] has been doing this for Openclaw agents since day one. Now there's a [Claude Code integration][7] that brings the same capability to Claude Code.

The plugin hooks into Claude Code's lifecycle:

- **Before every prompt**: queries Hindsight for relevant memories and injects them as context — Claude sees them, the chat transcript doesn't
- **Periodically after responses**: extracts conversation chunks and retains them to Hindsight for long-term storage (every N turns, with overlap for continuity)
- **On session start**: health-checks the Hindsight server
- **On session end**: cleans up the daemon if the plugin started one

This is completely automatic. Once installed, every conversation builds your agent's memory, and every new prompt benefits from everything it has learned.

### Step 7: Set Up Hindsight

You need a running Hindsight server. There are three options:

**Option A: Local daemon (easiest)**

The plugin can auto-manage a local `hindsight-embed` daemon. You just need [uv][8] installed and an LLM API key for fact extraction:

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Set an LLM provider — Hindsight uses it to extract facts from conversations
# Pick one:
export OPENAI_API_KEY="sk-your-key"          # Uses gpt-4o-mini
# or
export ANTHROPIC_API_KEY="your-key"           # Uses claude-3-5-haiku
# or
export GEMINI_API_KEY="your-key"              # Uses gemini-2.5-flash
# or
export GROQ_API_KEY="your-key"                # Uses groq
```

That's it — the plugin will download and start `hindsight-embed` automatically on first use.

**Option B: External Hindsight server**

If you have a Hindsight server running (cloud or self-hosted), you can point the plugin at it directly. No local LLM needed — the server handles fact extraction.

**Option C: Manual local server**

If you prefer to manage the daemon yourself:

```bash
uvx hindsight-embed@latest daemon start
# Runs on port 9077 by default
```

### Step 8: Install the Hindsight Plugin

In your Claude Code session:

```
/plugin install hindsight-memory@claude-plugins-official
/reload-plugins
```

The plugin is pure Python with zero external dependencies — no `pip install` required.

### Step 9: Configure the Connection

Edit the plugin's `settings.json` to match your setup.

**For Option A (auto-managed daemon)** — no changes needed. The defaults work out of the box. The plugin will start a daemon on port `9077` and auto-detect your LLM provider from environment variables.

**For Option B (external server)** — set your server URL:

```json
{
  "hindsightApiUrl": "https://your-hindsight-server.com",
  "hindsightApiToken": "your-token-if-needed"
}
```

**For Option C (manual local server)** — if your server runs on the default port (`9077`), no changes needed. The plugin will detect it automatically.

### Step 10: Customize Your Agent's Memory

These are the settings that shape how your agent remembers. The defaults work well, but here's what you might want to tune:

```json
{
  "bankId": "my-telegram-agent",
  "bankMission": "You are a senior software engineer assistant. Focus on architectural decisions, code patterns, project context, and the user's preferences.",
  "retainMission": "Extract technical decisions, architectural choices, user preferences, project context, and relationships between people and tools. Ignore routine greetings and transient operational details."
}
```

| Setting              | Default              | What it does                                                                                          |
| -------------------- | -------------------- | ----------------------------------------------------------------------------------------------------- |
| `bankId`             | `"claude_code"`      | Names the memory bank. Change this to isolate memory per agent.                                       |
| `bankMission`        | generic assistant    | Tells Hindsight who this agent is — helps it extract more relevant facts.                             |
| `retainMission`      | technical extraction | Guides what Hindsight should remember from conversations.                                             |
| `retainEveryNTurns`  | `10`                 | Retains every 10th turn in a sliding window — avoids API bombardment while maintaining full coverage. |
| `retainOverlapTurns` | `2`                  | Includes 2 extra turns of overlap between retention windows for continuity.                           |
| `recallBudget`       | `"mid"`              | How hard Hindsight searches for relevant memories. `"low"` for speed, `"high"` for thoroughness.      |
| `recallMaxTokens`    | `1024`               | Max tokens of memory context injected per prompt.                                                     |

The full configuration reference with all 34 options is in the [plugin README][9].

### Step 11: Relaunch and Verify

Restart Claude Code with both plugins:

```bash
claude --channels plugin:telegram@claude-plugins-official
```

Send your bot a few messages. Then check the logs — with `"debug": true` in settings.json, you'll see:

```
[Hindsight] Recalling from bank 'my-telegram-agent', query length: 142
[Hindsight] Injecting 3 memories
[Hindsight] Retaining to bank 'my-telegram-agent', doc '...', 8 messages, 2341 chars
```

Memory is flowing. Every prompt gets relevant context injected. Every conversation gets retained.

Turn off debug mode once you've verified:

```json
{
  "debug": false
}
```

---

## What This Looks Like in Practice

To understand what changes, you need to understand what Hindsight actually does under the hood. It doesn't just log conversations — it *extracts structured facts* from them. When you tell your agent "we decided to use Postgres because the team already knows it and we need JSONB support," Hindsight doesn't store the raw transcript. It extracts discrete facts: the technology choice, the rationale, the team constraint. These facts are typed (world knowledge, experience, observation), timestamped, and stored in a way that makes them retrievable by semantic relevance — not just keyword matching.

This is what makes the recall useful. When you ask your agent to design a new service a week later, Hindsight doesn't dump your entire conversation history into the prompt. It surfaces the 3-4 facts that are actually relevant to what you're asking right now: your database choice, your naming conventions, the architectural patterns you've established. The agent receives precisely the context it needs, nothing more.

Here's what that progression looks like:

**Day 1**: You tell your bot about a new project. It has no memories — it's working from what you tell it and what it can read in the codebase.

**Day 3**: You ask "what was the database schema we discussed?" Hindsight matches your query against extracted facts from Day 1 and injects them as context. The bot picks up exactly where you left off — not because it replayed the old conversation, but because it recalled the specific decisions that are relevant.

**Week 2**: You ask it to refactor a module. Hindsight recalls your architectural preferences, the naming conventions you established, the patterns you rejected. The agent doesn't ask you to repeat yourself — it already has those facts, extracted from prior conversations and ranked by relevance.

**Month 2**: Your bot has retained hundreds of conversations. Hindsight has extracted thousands of discrete facts. The agent knows your codebase intimately — not just the code (it can always read that), but the *decisions behind the code*. Why you chose Postgres over SQLite. Why the auth middleware was rewritten. Who asked for the API change. Context that lives nowhere in the code itself, distilled into structured memory.

This is the difference between a stateless tool and a contextual collaborator. Claude Code provides the reasoning and the codebase access. Hindsight provides the continuity — the ability to accumulate understanding over time, session after session, and bring exactly the right slice of that understanding to bear on each new question. Together, they produce an agent whose quality of response improves the more you use it.

---

## Why Claude Code

If you know [Openclaw][10], this will sound familiar. Openclaw has had Hindsight integration for months — it's what gives some Openclaw agents their memory. This setup achieves the same result using a different stack. The question is: which fits your workflow better?

The choice depends on your needs and what you're already using.

Both Openclaw and Claude Code can read your files, run commands, and interact with messaging platforms. The feature sets overlap significantly. The differences are in architecture and trade-offs.

**Claude Code** is Anthropic's official CLI — maintained by the same team that builds Claude. It offers a well-defined hook lifecycle, sandboxed execution, a granular permission model, and a plugin architecture designed for autonomous operation. The Channels system, the MCP integration, the permission model — these are first-party features that ship with the product and evolve with it.

**Openclaw** is a community-driven agent framework with a broader model ecosystem — it supports multiple LLM providers, multiple messaging channels out of the box, and has a mature plugin ecosystem built by its community. The Hindsight integration originated here, and it remains the more flexible option if you need multi-model or multi-platform setups.

For developers who are already invested in Claude and want a streamlined, single-vendor stack with strong security defaults, Claude Code is a natural fit. For those who want model flexibility or are already running Openclaw agents, the Openclaw integration is equally capable — same Hindsight, same memory quality, different runtime.

|                     | Openclaw + Hindsight                             | Claude Code + Telegram + Hindsight                         |
| ------------------- | ------------------------------------------------ | ---------------------------------------------------------- |
| **Runtime**         | Openclaw gateway                                 | Claude Code with Channels                                  |
| **Maintainer**      | Community (open-source)                          | Anthropic (first-party)                                    |
| **Model**           | Configurable (OpenAI, Claude, etc.)              | Claude (via Anthropic API)                                 |
| **Interface**       | Multi-channel (Telegram, Discord, Slack, web, …) | Any Channel plugin (Telegram, Discord today — more coming) |
| **Memory**          | hindsight-openclaw (TypeScript)                  | hindsight-claude-code (Python)                             |
| **Codebase access** | Native (read, write, edit, exec)                 | Native (Read, Edit, Write, Bash, Git, PR workflows)        |
| **Plugin system**   | Openclaw plugin format                           | Claude Code hooks (structured lifecycle)                   |
| **Setup**           | Openclaw config + plugin install                 | Claude Code + Channel + plugin install                     |

The Hindsight plugin for Claude Code is a [complete port of the Openclaw plugin][11] — same architecture, same configuration options, same recall/retain logic. If you're already using Hindsight with Openclaw, the concepts are identical. The difference is the foundation you're building on.

---

## Dynamic Memory Banks

For advanced setups, the plugin supports dynamic bank IDs — isolating memory per project, per channel, or per user:

```json
{
  "dynamicBankId": true,
  "dynamicBankGranularity": ["agent", "project"]
}
```

With this configuration, each project directory gets its own memory bank. Your frontend project's memories stay separate from your backend project's memories. You can also add `"channel"` and `"user"` dimensions for multi-user or multi-channel agents, by setting `HINDSIGHT_CHANNEL_ID` and `HINDSIGHT_USER_ID` environment variables.

---

## Troubleshooting

**Bot doesn't respond**: Make sure Claude Code is running with `--channels plugin:telegram@claude-plugins-official`. The plugin only works in an active session.

**Pairing code not appearing**: Check that your bot token is correctly set in `~/.claude/channels/telegram/.env`.

**"Bun not found" error**: Install Bun with `curl -fsSL https://bun.sh/install | bash` and restart your terminal.

**No memories being recalled**: Memories need at least one retain cycle before they're available. Send a few messages, wait for the async retain to process, then check on the next prompt. Enable `"debug": true` to see the recall/retain flow.

**Hindsight daemon not starting**: Ensure `uvx` is on your PATH (`pip install uv` or `brew install uv`). Check that an LLM API key is set. Review logs at `~/.hindsight/profiles/claude-code.log`.

**High latency on recall**: The recall hook has a 12-second timeout (the API call itself times out at 10s, with margin for processing). Try `"recallBudget": "low"` for faster responses, or reduce `"recallMaxTokens"`.

---

## What's Next

This setup — Claude Code, Telegram, Hindsight — gives you a persistent AI coding assistant with long-term memory, accessible from everywhere and also from your phone. It's the kind of thing that was only possible with dedicated agent frameworks until now.

The Hindsight plugin for Claude Code is [open source][12] and works with any Claude Code Channel, not just Telegram. Discord is already supported, and as more Channel plugins ship, the memory layer stays the same.

Set it up, use it for a week, and see the difference.

[1]:	https://vectorize.io/hindsight
[2]:	https://openclaw.ai
[3]:	https://t.me/botfather
[4]:	https://t.me/userinfobot
[5]:	https://vectorize.io/hindsight
[6]:	https://github.com/vectorize-io/hindsight/tree/main/hindsight-integrations/openclaw
[7]:	https://github.com/vectorize-io/hindsight/tree/main/hindsight-integrations/claude-code
[8]:	https://docs.astral.sh/uv/
[9]:	https://github.com/vectorize-io/hindsight/tree/main/hindsight-integrations/claude-code
[10]:	https://openclaw.ai
[11]:	https://github.com/vectorize-io/hindsight/tree/main/hindsight-integrations/claude-code
[12]:	https://github.com/vectorize-io/hindsight/tree/main/hindsight-integrations/claude-code
