---
sidebar_position: 6
---

# Embedded Node.js (hindsight-embed)

Node.js lifecycle manager for the Python `hindsight-embed` daemon. Use this when you want to embed a local Hindsight daemon in a Node application without hand-rolling subprocess management.

This package **does not ship an HTTP client** — it only owns the daemon process. Once the daemon is running, talk to it with [`@vectorize-io/hindsight-client`](./nodejs.md) against `manager.getBaseUrl()`. The two packages compose: one owns the process, the other owns the API surface.

## How it works

1. `manager.start()` resolves the `hindsight-embed` command (via `uvx` from PyPI, or `uv run --directory <path>` for a local checkout).
2. Runs `profile create <name> --merge --port <port> [--env KEY=VALUE ...]` with every entry from `options.env` forwarded as `--env`.
3. Runs `daemon --profile <name> start`.
4. Polls `http://host:port/health` until it returns `200` or the `readyTimeoutMs` budget is exhausted.
5. `manager.stop()` runs `daemon --profile <name> stop`.

The manager is intentionally transparent: new Python env vars or CLI flags never require a wrapper release — pass them through `env`, `extraProfileCreateArgs`, or `extraDaemonStartArgs`.

## Requirements

- **Node.js ≥ 22** — uses global `fetch` and `AbortSignal.timeout`.
- **`uv` / `uvx`** on `PATH` — used to download and run the Python `hindsight-embed` package. Install via [docs.astral.sh/uv](https://docs.astral.sh/uv/).

## Install

```bash
npm install @vectorize-io/hindsight-embed @vectorize-io/hindsight-client
```

## Example

```ts
import { HindsightEmbedManager, consoleLogger } from '@vectorize-io/hindsight-embed';
import { HindsightClient } from '@vectorize-io/hindsight-client';

const manager = new HindsightEmbedManager({
  profile: 'my-app',
  port: 9077,
  env: {
    HINDSIGHT_API_LLM_PROVIDER: 'anthropic',
    HINDSIGHT_API_LLM_API_KEY: process.env.ANTHROPIC_API_KEY,
    HINDSIGHT_API_LLM_MODEL: 'claude-sonnet-4-20250514',
    HINDSIGHT_EMBED_DAEMON_IDLE_TIMEOUT: '0',
  },
  logger: consoleLogger,
});

await manager.start();

const client = new HindsightClient({ baseUrl: manager.getBaseUrl() });
await client.retain('user-123', 'User prefers dark mode.');
const recall = await client.recall('user-123', 'what are the user preferences?');

await manager.stop();
```

For a remote Hindsight API, skip the manager entirely and point `HindsightClient` directly at the remote URL.

## `HindsightEmbedManagerOptions`

| Option | Type | Default | Description |
|---|---|---|---|
| `profile` | `string` | `"default"` | Profile name passed to `--profile` on every sub-command. |
| `port` | `number` | `8888` | TCP port the daemon listens on. |
| `host` | `string` | `"127.0.0.1"` | Hostname the daemon binds to (used for health checks). |
| `embedVersion` | `string` | `"latest"` | Version of `hindsight-embed` to run via `uvx`. |
| `embedPackagePath` | `string` | — | Local checkout path — takes precedence over `embedVersion`. Uses `uv run --directory` instead of `uvx`. |
| `env` | `Record<string, string \| undefined>` | `{}` | Environment variables passed to the daemon process **and** written into the profile config via `--env KEY=VALUE`. The preferred way to surface any `HINDSIGHT_API_*` / `HINDSIGHT_EMBED_*` setting. |
| `extraProfileCreateArgs` | `string[]` | `[]` | Extra args appended verbatim to `profile create`. |
| `extraDaemonStartArgs` | `string[]` | `[]` | Extra args appended verbatim to `daemon start`. |
| `platformCpuWorkaround` | `boolean` | `true` on macOS | Auto-set `HINDSIGHT_API_EMBEDDINGS_LOCAL_FORCE_CPU=1` and `HINDSIGHT_API_RERANKER_LOCAL_FORCE_CPU=1` to avoid Metal/MPS crashes. Caller-supplied `env` values win over the auto-applied ones. |
| `readyTimeoutMs` | `number` | `30000` | Max time to wait for `/health` to return 200. |
| `readyPollIntervalMs` | `number` | `1000` | Polling interval while waiting for `/health`. |
| `logger` | `Logger` | silent | Pluggable logger (`debug`/`info`/`warn`/`error`). `consoleLogger` and `silentLogger` helpers are exported. |

## Manager methods

| Method | Returns | Description |
|---|---|---|
| `start()` | `Promise<void>` | Configure profile, spawn the daemon, wait for `/health`. Idempotent — safe to re-run. |
| `stop()` | `Promise<void>` | Stop the daemon. Never throws; logs and resolves even on failure. |
| `checkHealth()` | `Promise<boolean>` | One-shot `/health` probe with a 2 s timeout. |
| `getBaseUrl()` | `string` | `http://host:port` — pass this straight to `HindsightClient`. |
| `getProfile()` | `string` | The profile name this manager operates on. |

For memory operations (retain, recall, reflect, bank management) use [`@vectorize-io/hindsight-client`](./nodejs.md).
