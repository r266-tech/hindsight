---
sidebar_position: 8
---

# LlamaIndex

Persistent long-term memory for [LlamaIndex](https://docs.llamaindex.ai/) agents via Hindsight. Uses LlamaIndex's native `BaseToolSpec` pattern to expose retain, recall, and reflect as tools that any LlamaIndex agent can use.

## Features

- **Native BaseToolSpec** — Implements `BaseToolSpec` so tools work with any LlamaIndex agent (ReAct, FunctionCalling, etc.)
- **Three Memory Operations** — retain (store), recall (search), and reflect (synthesize) as individual tools
- **Selective Tools** — Use `to_tool_list(spec_functions=...)` or `include_retain/recall/reflect` flags to expose only the tools you need
- **Global + Per-Call Config** — Set defaults via `configure()`, override per-call
- **Full Hindsight Feature Set** — Tags, metadata, document grouping, fact type filtering, entity extraction, reflect schemas

## Installation

```bash
pip install hindsight-llamaindex
```

## Quick Start: Tool Spec

Use `HindsightToolSpec` directly for full control.

```python
import asyncio
from hindsight_client import Hindsight
from hindsight_llamaindex import HindsightToolSpec
from llama_index.llms.openai import OpenAI
from llama_index.core.agent import ReActAgent

async def main():
    client = Hindsight(base_url="http://localhost:8888")

    # Create the memory bank first (one-time setup)
    await client.acreate_bank("user-123", name="User 123 Memory")

    spec = HindsightToolSpec(client=client, bank_id="user-123")
    tools = spec.to_tool_list()

    agent = ReActAgent(tools=tools, llm=OpenAI(model="gpt-4o"))
    response = await agent.run("Remember that I prefer dark mode")
    print(response)

asyncio.run(main())
```

:::tip Jupyter Notebooks
In notebooks, use top-level `await` directly — no `asyncio.run()` needed:
```python
await client.acreate_bank("user-123", name="User 123 Memory")
response = await agent.run("Remember that I prefer dark mode")
```
:::

## Quick Start: Factory Function

Use `create_hindsight_tools()` for a simpler API.

```python
import asyncio
from hindsight_client import Hindsight
from hindsight_llamaindex import create_hindsight_tools
from llama_index.llms.openai import OpenAI
from llama_index.core.agent import ReActAgent

async def main():
    client = Hindsight(base_url="http://localhost:8888")
    tools = create_hindsight_tools(client=client, bank_id="user-123")

    agent = ReActAgent(tools=tools, llm=OpenAI(model="gpt-4o"))
    response = await agent.run("What do you remember about me?")
    print(response)

asyncio.run(main())
```

## Selecting Tools

### Via `to_tool_list()`

```python
spec = HindsightToolSpec(client=client, bank_id="user-123")

# Only recall and reflect — no retain
tools = spec.to_tool_list(spec_functions=["recall_memory", "reflect_on_memory"])
```

### Via factory flags

```python
tools = create_hindsight_tools(
    client=client,
    bank_id="user-123",
    include_retain=True,
    include_recall=True,
    include_reflect=False,  # exclude reflect
)
```

## Configuration

### Global config

Set connection and default parameters once. All subsequent tool creation will use these unless overridden.

```python
from hindsight_llamaindex import configure

configure(
    hindsight_api_url="http://localhost:8888",
    api_key="your-api-key",  # or set HINDSIGHT_API_KEY env var
    budget="mid",
    tags=["source:llamaindex"],
)

# Now you can create tools without passing client/url
tools = create_hindsight_tools(bank_id="user-123")
```

### Per-call overrides

Pass parameters directly to `HindsightToolSpec()` or `create_hindsight_tools()` to override global config.

## API Reference

### `HindsightToolSpec()`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `bank_id` | `str` | *required* | Hindsight memory bank to operate on |
| `client` | `Hindsight` | `None` | Pre-configured Hindsight client |
| `hindsight_api_url` | `str` | `None` | API URL (used if no client provided) |
| `api_key` | `str` | `None` | API key (used if no client provided) |
| `budget` | `str` | `None` → `"mid"` | Recall/reflect budget: `low`, `mid`, `high` |
| `max_tokens` | `int` | `None` → `4096` | Max tokens for recall results |
| `tags` | `list[str]` | `None` | Tags applied when storing memories |
| `recall_tags` | `list[str]` | `None` | Tags to filter recall results |
| `recall_tags_match` | `str` | `None` → `"any"` | Tag matching: `any`, `all`, `any_strict`, `all_strict` |
| `retain_metadata` | `dict[str, str]` | `None` | Default metadata for retain operations |
| `retain_document_id` | `str` | `None` | Document ID for retain (groups/upserts memories) |
| `recall_types` | `list[str]` | `None` | Fact types: `world`, `experience`, `opinion`, `observation` |
| `recall_include_entities` | `bool` | `False` | Include entity info in recall results |
| `reflect_context` | `str` | `None` | Additional context for reflect |
| `reflect_max_tokens` | `int` | `None` | Max tokens for reflect (defaults to `max_tokens`) |
| `reflect_response_schema` | `dict` | `None` | JSON schema to constrain reflect output |
| `reflect_tags` | `list[str]` | `None` | Tags for reflect (defaults to `recall_tags`) |
| `reflect_tags_match` | `str` | `None` | Tag matching for reflect (defaults to `recall_tags_match`) |

### `create_hindsight_tools()`

Accepts all `HindsightToolSpec` parameters plus:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `include_retain` | `bool` | `True` | Include the retain (store) tool |
| `include_recall` | `bool` | `True` | Include the recall (search) tool |
| `include_reflect` | `bool` | `True` | Include the reflect (synthesize) tool |

### `configure()`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `hindsight_api_url` | `str` | Production URL | Hindsight API URL |
| `api_key` | `str` | `None` | API key (falls back to `HINDSIGHT_API_KEY` env var) |
| `budget` | `str` | `"mid"` | Default recall budget |
| `max_tokens` | `int` | `4096` | Default max tokens |
| `tags` | `list[str]` | `None` | Default retain tags |
| `recall_tags` | `list[str]` | `None` | Default recall filter tags |
| `recall_tags_match` | `str` | `"any"` | Default tag matching mode |
| `verbose` | `bool` | `False` | Enable verbose logging |

## Production Patterns

### Memory Scoping with Tags

Use tags to organize memories by source, conversation, or topic:

```python
spec = HindsightToolSpec(
    client=client,
    bank_id="user-123",
    tags=["source:chat", "session:abc"],        # applied to all retains
    recall_tags=["source:chat"],                 # filter recalls to chat memories
    recall_tags_match="any",                     # match any tag (default)
)
```

For multi-tenant applications, use one bank per user and tags per context (e.g., `project:X`, `channel:support`).

### Error Handling

All tool methods raise `HindsightError` on failure. Wrap agent execution to handle memory errors gracefully:

```python
from hindsight_llamaindex import HindsightError

try:
    response = await agent.run("What do you know about me?")
except HindsightError as e:
    # Memory unavailable — agent can still function without memory
    logger.warning(f"Memory error: {e}")
```

### Bank Lifecycle

Banks must be created before use and should be created once per user/entity:

```python
# One-time setup (e.g., during user onboarding)
await client.acreate_bank(f"user-{user_id}", name=f"{user_name}'s Memory")

# Subsequent agent creation — bank already exists
spec = HindsightToolSpec(client=client, bank_id=f"user-{user_id}")
```

## Requirements

- Python 3.10+
- `llama-index-core >= 0.11.0`
- `hindsight-client >= 0.4.0`
