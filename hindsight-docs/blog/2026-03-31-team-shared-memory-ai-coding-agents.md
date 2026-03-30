---
title: "Shared Memory for AI Coding Agents: A Team Setup Guide"
authors: [benfrank241]
date: 2026-03-31T09:00
tags: [claude-code, codex, memory, teams, tutorial]
image: /img/blog/team-memory-coding-agents.png
description: "Every dev's AI coding agent learns in isolation. Hindsight's shared memory bank lets Claude Code and Codex agents share knowledge automatically. One config change."
hide_table_of_contents: true
---

Every developer on your team is running an AI coding agent. Each one is getting smarter, learning your codebase, picking up your preferences, remembering what worked. But without shared memory, that learning stays private.

Dev A's agent figures out the right way to handle pagination in your API. Dev B's agent reinvents it two weeks later. Dev C spends forty minutes debugging a known issue in the auth middleware that Dev D already solved last month. Every agent starts from scratch.

It doesn't have to work this way.

<!-- truncate -->

Hindsight supports a shared memory bank, a single store that every developer's AI coding agent reads from and writes to. Architecture decisions, coding conventions, known bugs, team context. One config change, and your whole team's agents share one brain.

With both [Claude Code](/blog/openclaude-build-a-claude-code-agent-with-long-term-memory) and [Codex](/sdks/integrations/codex) integrations now available, this works whether your team uses Anthropic's or OpenAI's tooling, or both.

---

## What Team Memory Actually Means

The core idea is simple. In Hindsight, a **memory bank** is an isolated store; all the facts an agent has extracted and retained from past conversations. By default, each developer's agent uses its own bank. That's fine for personal context, but it means nothing is shared.

Flip the bank to a shared one, and everything changes:

```
Without shared memory: With shared memory (team bank):

Dev A's agent → bank-A Dev A's agent ─┐
Dev B's agent → bank-B Dev B's agent ─┼──→ team-brain
Dev C's agent → bank-C Dev C's agent ─┘
```

Every agent still has the same capabilities and workflow. The difference is where memories go, and where they come from.

---

## What Goes Into Team Memory

Not everything that happens in a coding session belongs in shared memory. You don't want one developer's debugging tangents or editor preferences cluttering every other agent's context. What you do want is the knowledge that would otherwise live in Slack, Confluence, or someone's head, the stuff that disappears when people leave or forget to document it.

Good candidates for team memory:

- **Conventions**: "We use snake_case for DB columns, camelCase in the API layer, never mix them."
- **Known bugs and gotchas**: "There's a race condition in the refresh token handler, see PR #441 for context. Don't touch the token expiry logic without understanding that first."
- **Architecture decisions**: "We moved off SQLAlchemy to asyncpg in March, all new DB code uses asyncpg."
- **External system quirks**: "The Redis TTL in production is 15 minutes, not 30 as the README says. The README is wrong."
- **Off-limits areas**: "The legacy billing service is being migrated by Q2. Don't add new features to it."
- **Process and deployment**: "CI runs on every push. Production requires a signed tag, branch pushes don't auto-deploy."

This is institutional knowledge. The kind of thing a senior engineer carries around in their head and slowly transfers to new hires over months of pairing sessions. With a shared memory bank, every AI coding agent on the team has it from day one.

---

## Why Not Just Use CLAUDE.md or AGENTS.md?

A fair question. Most teams using Claude Code or Codex already put project context into a `CLAUDE.md` or `AGENTS.md` file checked into the repo. That file tells every agent the same baseline facts on startup. So what does a shared memory bank add?

Static config files are snapshots. They capture what someone thought to write down, when they thought to write it. A shared memory bank is a living record. It captures what agents actually encounter during real work sessions, the Redis TTL discrepancy someone discovered at 3pm on a Tuesday, the JWT edge case that surfaced during a code review, the migration status that changed last sprint. Nobody filed a ticket. Nobody updated the CLAUDE.md. But the agent retained it, and now the whole team has it.

The two are complementary. Put stable, deliberate context in your config file, project conventions, setup instructions, directory structure. Let Hindsight handle the dynamic layer, the things that get discovered, decided, and resolved in the flow of actual work. Together they give every AI coding agent both the foundation and the living memory of the team.

---

## Setting Up a Shared Memory Bank

The mechanism is straightforward: every developer points their plugin at the same Hindsight server with the same bank ID. When any agent retains something, it lands in the shared bank. When any agent recalls, it pulls from that same pool.

### Claude Code

[Claude Code](https://docs.anthropic.com/en/docs/claude-code) is Anthropic's official CLI. Edit `~/.hindsight/claude-code.json` on each developer's machine:

```json
{
 "hindsightApiUrl": "https://api.hindsight.vectorize.io",
 "hindsightApiToken": "hsk_your_team_token",
 "bankId": "team-brain",
 "bankMission": "Shared memory bank for the engineering team. Stores architectural decisions, coding conventions, known bugs, and institutional knowledge.",
 "retainMission": "Extract and retain facts about the codebase architecture, coding standards and conventions, known bugs and their workarounds, team decisions and their rationale, and external system behaviors. Do not retain personal preferences, task-specific context, or anything that only applies to one developer's session."
}
```

That's it. Every developer with this config writes to and reads from the same `team-brain` bank.

### Codex

[Codex](https://github.com/openai/codex) is OpenAI's open-source coding agent CLI. Same pattern, edit `~/.hindsight/codex.json` on each machine:

```json
{
 "hindsightApiUrl": "https://api.hindsight.vectorize.io",
 "hindsightApiToken": "hsk_your_team_token",
 "bankId": "team-brain",
 "bankMission": "Shared memory bank for the engineering team. Stores architectural decisions, coding conventions, known bugs, and institutional knowledge.",
 "retainMission": "Extract and retain facts about the codebase architecture, coding standards and conventions, known bugs and their workarounds, team decisions and their rationale, and external system behaviors. Do not retain personal preferences, task-specific context, or anything that only applies to one developer's session."
}
```

Same bank ID, same server, same result. Claude Code and Codex agents on your team all pull from the same memory.

---

## Controlling What Gets Retained

This is where `retainMission` earns its keep. It tells Hindsight's fact extraction exactly what to capture, and by implication, what to ignore.

Without a focused `retainMission`, agents retain a mix of everything: coding decisions, personal habits, random tangents. That degrades recall quality for the whole team. With a clear mission, only team-relevant facts make it through.

A few examples depending on your team's needs:

**Product-focused team:**
```json
{
 "retainMission": "Extract technical decisions, API design choices, data model changes, and known issues. Retain the rationale behind decisions, not just the decision itself. Ignore one-off debugging sessions and personal editor preferences."
}
```

**Infrastructure team:**
```json
{
 "retainMission": "Extract facts about infrastructure configuration, deployment processes, service dependencies, known failure modes, and operational runbooks. Retain version constraints, environment-specific behavior, and incident learnings."
}
```

**Platform/SDK team:**
```json
{
 "retainMission": "Extract API contracts, breaking changes, deprecation decisions, and compatibility notes. Retain examples of correct usage patterns and anti-patterns to avoid."
}
```

The more specific the mission, the more useful the shared memory becomes. Think of it as defining the terms of reference for your team's knowledge base.

---

## What It Looks Like in Practice

Here's a concrete week on a team using shared memory.

**Monday morning**, Dev A starts working on a new endpoint. Before writing a line of code, their agent already knows: the codebase uses asyncpg (not SQLAlchemy), the Redis TTL issue in production, and the naming convention for DB columns. This context came from the team bank, none of it required Dev A to ask anyone.

**Monday afternoon**, While debugging a session handling issue, Dev A's agent discovers something new: the JWT validation library silently ignores the `aud` claim in certain edge cases. Dev A tells their agent: *"Document this for the team, the JWT library doesn't validate audience claim when the token has multiple audiences. You need to check it manually."*

The agent retains this to the team bank. It's extracted as a fact: *"The JWT validation library does not validate the audience claim for tokens with multiple audiences. Manual validation required."*

**Tuesday morning**, Dev B starts working on a feature that touches authentication. Their agent recalls the JWT issue automatically, before Dev B has even started writing code. No Slack message. No code review comment. No one getting paged at 2am.

**Six weeks later**, a production incident surfaces: tokens with multiple audiences are being silently accepted when they shouldn't be. The on-call engineer's agent queries the team bank. The JWT audience issue is already there, documented with context and a pointer to the relevant code path. Resolution time: 12 minutes instead of 2 hours. The postmortem is short.

**Three months later**, a new engineer joins. On their first day using Codex, their agent has access to everything the team has learned. Not because anyone wrote it down or gave them a walkthrough, but because it's in the bank. The onboarding conversation shifts from "let me tell you about all the gotchas" to actually building something.

---

## Seeding the Bank on Day One

The shared bank starts empty. Agents fill it organically over time, but there's no reason to wait weeks for useful context to accumulate.

You can seed the bank manually by pointing an agent at your existing documentation. Ask your Claude Code or Codex agent to read through your architecture docs, your runbooks, your Confluence or Notion pages, and retain the key facts to the team bank. One session can bootstrap weeks of organic accumulation.

A practical starting prompt:

> "I'm going to share some internal documentation with you. Read each section and use the Hindsight retain tool to store any facts that would be useful for other engineers working on this codebase, architectural decisions, known issues, conventions, deployment processes. Don't retain process documentation or meeting notes, just the durable technical facts."

Then paste in your most important docs. Within an hour, every agent on the team is working with a pre-populated base of context that would otherwise take months to build up naturally.

You can also check the [Hindsight cookbook](https://github.com/vectorize-io/hindsight-cookbook) for scripts that bulk-seed a bank from files or URLs.

---

## Per-Project vs Global

For teams working on multiple repositories or services, you might want more granularity than a single team bank.

Use `bankIdPrefix` to namespace by team or environment:

```json
{
 "bankId": "backend",
 "bankIdPrefix": "acme-",
 "hindsightApiUrl": "https://api.hindsight.vectorize.io",
 "hindsightApiToken": "hsk_your_team_token"
}
```

This produces bank ID `acme-backend`, isolated from any other team or project using the same server.

For completely separate repositories with different standards, just use different `bankId` values per repository config (checked into the repo via a `.hindsight/` config that takes precedence over the user config).

---

## Hosting Options

Three ways to run this:

| Option | Setup | Data control | Best for |
|--------|-------|-------------|----------|
| **Hindsight Cloud** | Zero setup, share an API token | Hosted by Vectorize | Teams that want to start immediately |
| **Self-hosted** | Deploy on your own infra via Docker | Fully yours | Enterprise, compliance requirements |
| **Local per-machine** | Each developer runs `hindsight-embed` locally | Local only | Sensitive codebases, no external calls |

For most teams, Hindsight Cloud is the right starting point. Share one API key, pick a `bankId`, and you're done. For teams with strict data residency requirements, the [self-hosted deployment](/developer/installation) gives you full control.

---

## Putting It Together

AI coding agents are increasingly how engineering work gets done. The default assumption has been that each agent is personal, scoped to one developer, one machine, one conversation. Shared memory changes that model. A team's collective discoveries, decisions, and hard-won knowledge can flow automatically to every agent, across every session, for every developer.

The config is trivial. The compounding effect over months is not.

---

## Get Started

To set up shared memory for your team:

1. Create a [Hindsight Cloud account](https://ui.hindsight.vectorize.io/signup) and generate an API key
2. Pick a `bankId` for your team (e.g., `"team-brain"` or `"acme-backend"`)
3. Add the config above to `~/.hindsight/claude-code.json` or `~/.hindsight/codex.json` on each machine
4. Have each developer complete one coding session, the bank starts filling immediately

The first few sessions will build up the foundation. After a week, every agent on your team has meaningful shared context. After a month, it's the first thing developers notice when they switch to a new machine or start fresh, the agent already knows the codebase.

Your agents are learning. They might as well learn together.

---

*Set up the integrations: [Claude Code](/sdks/integrations/claude-code) · [Codex](/sdks/integrations/codex) · [Memory banks reference](/developer/api/memory-banks)*
