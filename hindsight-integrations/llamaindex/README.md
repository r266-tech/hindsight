# hindsight-llamaindex

LlamaIndex integration for [Hindsight](https://github.com/vectorize-io/hindsight) — persistent long-term memory for AI agents.

Provides Hindsight memory as a native LlamaIndex `BaseToolSpec`, giving agents retain/recall/reflect capabilities through LlamaIndex's standard tool interface.

## Prerequisites

- A running Hindsight instance ([self-hosted via Docker](https://github.com/vectorize-io/hindsight#quick-start) or [Hindsight Cloud](https://ui.hindsight.vectorize.io/signup))
- Python 3.10+

## Installation

```bash
pip install hindsight-llamaindex
```

## Quick Start: Tool Spec

Use `HindsightToolSpec` directly for full control over tool creation.

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

### Selective Tools

Use `to_tool_list(spec_functions=...)` to include only the tools you need:

```python
# Only recall and reflect — no retain
tools = spec.to_tool_list(spec_functions=["recall_memory", "reflect_on_memory"])
```

## Quick Start: Factory Function

Use `create_hindsight_tools()` for a simpler API with include/exclude flags.

```python
from hindsight_llamaindex import create_hindsight_tools

tools = create_hindsight_tools(
    client=client,
    bank_id="user-123",
    include_reflect=False,  # only retain + recall
)

agent = ReActAgent(tools=tools, llm=llm)
```

## Configuration

### Global config

```python
from hindsight_llamaindex import configure

configure(
    hindsight_api_url="http://localhost:8888",
    api_key="your-api-key",  # or set HINDSIGHT_API_KEY env var
    budget="mid",
    tags=["source:llamaindex"],
)
```

### Per-call overrides

All factory functions accept `client`, `hindsight_api_url`, and `api_key` to override the global config.

| Parameter | Description | Default |
|-----------|-------------|---------|
| `hindsight_api_url` | Hindsight API URL | `https://api.hindsight.vectorize.io` |
| `api_key` | API key (or `HINDSIGHT_API_KEY` env var) | `None` |
| `budget` | Recall budget: `low`, `mid`, `high` | `mid` |
| `max_tokens` | Max tokens for recall results | `4096` |
| `tags` | Tags applied to retain operations | `None` |
| `recall_tags` | Tags to filter recall results | `None` |
| `recall_tags_match` | Tag matching: `any`, `all`, `any_strict`, `all_strict` | `any` |

## Memory Scoping

Use one bank per user/entity and tags to organize memories by context:

```python
spec = HindsightToolSpec(
    client=client,
    bank_id=f"user-{user_id}",           # one bank per user
    tags=["source:chat", "project:X"],     # scope retains by context
    recall_tags=["source:chat"],           # filter recalls to chat memories
)
```

## Requirements

- Python 3.10+
- `llama-index-core >= 0.11.0`
- `hindsight-client >= 0.4.0`

## Documentation

- [Integration docs](https://docs.hindsight.vectorize.io/docs/sdks/integrations/llamaindex)
- [Hindsight API docs](https://docs.hindsight.vectorize.io)
