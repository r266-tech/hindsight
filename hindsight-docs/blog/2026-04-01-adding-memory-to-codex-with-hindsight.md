---
title: "The Memory Upgrade Every Codex User Needs"
authors: [benfrank241]
date: 2026-04-01T09:00
tags: [codex, memory, hindsight, tutorial]
image: /img/blog/adding-memory-to-codex-with-hindsight.png
description: "Codex has no persistent memory — every session starts from scratch. The Hindsight plugin hooks in automatically: facts extracted from your conversations, recalled before every prompt."
hide_table_of_contents: true
---

![The Memory Upgrade Every Codex User Needs](/img/blog/adding-memory-to-codex-with-hindsight.png)

## TL;DR

<!-- truncate -->

- Codex has no persistent memory built in. Every session starts fresh — no recollection of past decisions, preferences, or codebase context.
- The Hindsight plugin hooks into Codex via three Python scripts with zero `pip install` required. One curl command gets you running.
- Auto-recall queries your memory bank before every prompt and injects relevant facts as invisible context. Codex sees them; you don't have to repeat them.
- Auto-retain fires at the end of every session, extracts facts from the transcript, and stores them for future recall.
- For teams, point everyone's config at a shared Hindsight server with a fixed `bankId`. See [Shared Memory for AI Coding Agents](/blog/2026/03/31/team-shared-memory-ai-coding-agents).

## The Problem

[Codex](https://github.com/openai/codex) is OpenAI's open-source coding agent CLI. You give it a task, it reads your files, runs commands, and iterates until it's done. It's capable and fast — but it has no memory.

Every session starts from nothing. Codex doesn't know which libraries your project uses, which patterns you've standardized on, which areas of the codebase are fragile, or what you were working on yesterday. You re-establish this context at the start of every session, either by explaining it directly or by pointing at an `AGENTS.md` file you've manually maintained.

`AGENTS.md` helps — it's a static markdown file that tells Codex baseline facts about your project on startup. But it captures what you remembered to write down, not what you actually encountered. The Redis TTL discrepancy you noticed Tuesday at 3pm, the JWT edge case that surfaced during code review, the reason you stopped using SQLAlchemy — these live in session transcripts that vanish when the window closes. Nobody updated `AGENTS.md`. Next session, that knowledge is gone.

## The Approach

[Hindsight](https://github.com/vectorize-io/hindsight) adds a persistent memory layer to Codex by hooking into its lifecycle at two points: before every prompt and after every session.

**Auto-recall.** On every user prompt, the recall hook queries Hindsight for memories relevant to what you're about to ask. The results are injected into Codex as `additionalContext` — prepended to the conversation before the model sees it, but not visible in your terminal output. Codex has the context; you didn't have to repeat it.

**Auto-retain.** When a Codex session ends (the `Stop` hook fires), the retain hook takes the session transcript, strips any injected memory tags to prevent feedback loops, and sends it to Hindsight. The extraction model reads it and pulls out discrete facts — decisions made, patterns observed, bugs found. These land in your memory bank, available for every future session.

**Full-session upsert.** The transcript is stored using the session ID as the document key. If a session is retained multiple times (in chunked mode), the content is upserted rather than duplicated. No accumulation of near-identical entries.

**Minimal dependencies.** The hook scripts use Python stdlib only — no pip install, no virtualenv, no version conflicts. Local daemon mode requires [`uvx`](https://docs.astral.sh/uv/) to run `hindsight-embed`; Cloud mode has no local prerequisites at all.

```
┌──────────────┐     UserPromptSubmit      ┌─────────────────────────┐
│    Codex     │ ─────────────────────────▶ │  recall.py              │
│    CLI       │ ◀───────────────────────── │  queries Hindsight,     │
│              │   additionalContext inject  │  injects as context     │
│              │                            └─────────────────────────┘
│              │     Stop                  ┌─────────────────────────┐
│              │ ─────────────────────────▶ │  retain.py              │
└──────────────┘                            │  strips tags, sends     │
                                            │  transcript to Hindsight│
                                            └─────────────────────────┘
```

## Installing

```bash
curl -fsSL https://hindsight.vectorize.io/get-codex | bash
```

The installer guides you through choosing local or cloud mode and writes the hook scripts to `~/.hindsight/codex/`. It also enables `codex_hooks = true` in your `~/.codex/config.toml` automatically.

Start a new Codex session — memory is live immediately. The first few sessions build up your bank. By the third or fourth, recall starts surfacing useful context you didn't have to re-explain.

To uninstall:

```bash
curl -fsSL https://hindsight.vectorize.io/get-codex | bash -s -- --uninstall
```

## Connecting to Hindsight Cloud

The default setup runs a local `hindsight-embed` daemon on your machine. For memory that follows you across machines, connect to Hindsight Cloud instead. Edit `~/.hindsight/codex.json`:

```json
{
  "hindsightApiUrl": "https://api.hindsight.vectorize.io",
  "hindsightApiToken": "hsk_your_token"
}
```

Create an account and API key at [hindsight.vectorize.io](https://ui.hindsight.vectorize.io/signup). No daemon to manage — the cloud server handles extraction.

## What Gets Recalled

The recall hook fires on every `UserPromptSubmit` event. It takes your prompt (and optionally the previous turn for context), queries Hindsight, and injects the most relevant memories as a block at the top of the conversation:

```
<hindsight_memories>
Relevant memories from past conversations...
Current time - 2026-03-28 09:14

- Project uses FastAPI with asyncpg — not SQLAlchemy [world] (2026-03-26)
- Preferred testing framework: pytest with pytest-asyncio [world] (2026-03-26)
- Redis TTL in production is 15 minutes — README says 30, README is wrong [world] (2026-03-27)
</hindsight_memories>
```

Codex sees this block; it doesn't appear in your terminal output. The result: Codex starts every response with relevant context from past sessions, without you having to provide it.

You can tune how much to inject with `recallBudget` (`"low"`, `"mid"`, `"high"`) and `recallMaxTokens`.

## Per-Project Memory

By default all Codex sessions share a single bank. To give each project its own isolated memory:

```json
{
  "dynamicBankId": true,
  "dynamicBankGranularity": ["agent", "project"]
}
```

With this config, running Codex in `~/projects/api` and `~/projects/frontend` maintains separate banks. Bank IDs are derived from the working directory path — switching projects automatically switches memory context.

## Key Configuration Options

Settings live in `~/.hindsight/codex.json`. Every setting can also be set via environment variable.

| Setting | Default | What it does |
|---------|---------|--------------|
| `retainMission` | generic | Steers fact extraction — tell it what to focus on |
| `retainEveryNTurns` | `10` | How often to retain mid-session in chunked mode |
| `recallBudget` | `"mid"` | Search depth: `"low"` (fast) / `"mid"` / `"high"` (thorough) |
| `autoRecall` | `true` | Master switch for recall |
| `autoRetain` | `true` | Master switch for retention |
| `dynamicBankId` | `false` | Enable per-project bank isolation |
| `debug` | `false` | Logs all Hindsight activity to stderr |

Example `retainMission` for a focused memory bank:

```json
{
  "retainMission": "Extract technical decisions, known bugs and their workarounds, architecture choices, and coding conventions. Do not retain one-off debugging steps or editor preferences."
}
```

## Pitfalls

**Hooks not firing.** The installer sets `codex_hooks = true` in `~/.codex/config.toml` automatically, but if you installed manually or the file already existed, this may have been missed. Check the file and add the setting under `[features]` if it's missing.

**No memories recalled in the first session.** Recall returns results only after something has been retained. Complete one session first, or seed your bank manually using the [cookbook example](https://github.com/vectorize-io/hindsight-cookbook/tree/main/applications/codex-memory).

**Retention seems delayed.** `retainEveryNTurns` defaults to `10` in chunked mode — retain fires every 10 turns. In full-session mode (the default), retention fires once at session end. If you're testing, add `"retainEveryNTurns": 1` to your config.

**Nothing happening?** Check `~/.hindsight/codex/error.log` first — hook failures are written there. For a full trace of what each hook is doing, enable debug logging:

**Debug mode.** Add `"debug": true` to `~/.hindsight/codex.json` to log detailed activity to `~/.hindsight/codex/debug.log`:

```
[Hindsight] Recalling from bank 'codex', query length: 42
[Hindsight] Injecting 3 memories
[Hindsight] Retaining to bank 'codex', doc 'sess-abc123', 2 messages, 847 chars
```

## Tradeoffs

A few things worth knowing before you commit.

**Recall adds latency.** Every prompt triggers a Hindsight query before Codex sees it. In practice this is 100–300ms with Hindsight Cloud on a fast connection. For interactive sessions it's imperceptible; for automated scripts it may matter. Use `"recallBudget": "low"` or `"autoRecall": false` if you need to skip it.

**Retention is asynchronous.** The `retain.py` hook fires asynchronously so it doesn't block your session from exiting. Facts are typically available within seconds of retention completing, but timing depends on server load — they may appear sooner or later than the next session.

**Extraction quality depends on conversation quality.** Hindsight extracts facts from what's actually in the transcript. If you work through a problem entirely in file edits without narrating what you're doing, there may be little for the extraction model to work with. Brief explanations in your prompts help.

## Recap

| | Codex default | With Hindsight |
|---|---|---|
| Memory across sessions | None | Automatic |
| Memory setup | Manual `AGENTS.md` | Extracted from transcripts |
| Recall mechanism | File content on startup | Semantic search, injected per prompt |
| Per-project isolation | No | Optional via `dynamicBankId` |
| Team shared memory | No | Shared bank via Hindsight Cloud |

## Next Steps

- **Install**: `curl -fsSL https://hindsight.vectorize.io/get-codex | bash`
- **Config reference**: [Codex integration docs](/sdks/integrations/codex)
- **Team memory**: [Shared Memory for AI Coding Agents](/blog/2026/03/31/team-shared-memory-ai-coding-agents)
- **Hindsight Cloud**: [ui.hindsight.vectorize.io](https://ui.hindsight.vectorize.io/signup)
- **Cookbook**: [applications/codex-memory](https://github.com/vectorize-io/hindsight-cookbook/tree/main/applications/codex-memory)
