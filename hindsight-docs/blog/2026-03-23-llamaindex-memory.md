---
title: "Your LlamaIndex Agents Forget Everything Between Sessions. Here's the Fix."
authors: [benfrank241]
date: 2026-03-23
tags: [llamaindex, agents, python, memory, tutorial]
image: /img/blog/llamaindex-memory.png
---

LlamaIndex agents lose all context when a session ends. `hindsight-llamaindex` implements LlamaIndex's native `BaseToolSpec` to give agents persistent retain/recall/reflect tools -- one pip install, and your agents remember everything across conversations.

<!-- truncate -->

**TL;DR:**
- LlamaIndex agents have no built-in long-term memory -- context resets every session
- `hindsight-llamaindex` implements LlamaIndex's `BaseToolSpec` so memory tools work natively with any agent (ReAct, FunctionCalling, etc.)
- Three tools: `retain_memory` (store), `recall_memory` (search), `reflect_on_memory` (synthesize)
- Works with [Hindsight Cloud](https://ui.hindsight.vectorize.io/signup) (zero infra) or self-hosted

## The problem: stateless agents

LlamaIndex gives you excellent tools for building agents. ReAct agents, function-calling agents, multi-step query engines -- they're all powerful within a single session.

Then the session ends.

Next time the user shows up, the agent starts from zero. Preferences forgotten. Decisions lost. Context gone.

This matters when you build agents that serve repeat users:

- A coding assistant that remembers your stack and coding preferences
- A customer support agent that knows your order history and prior issues
- A research assistant that builds on findings from previous sessions

LlamaIndex has a `ChatMemoryBuffer` for in-session context, but it doesn't persist across sessions. For cross-session memory that actually compounds, you need something else.

That's what `hindsight-llamaindex` does. It implements LlamaIndex's `BaseToolSpec` using Hindsight's memory engine, so your agents remember everything -- across sessions, across days, across weeks.

---

## Architecture

```
LlamaIndex Agent (ReAct, FunctionCalling, etc.)
  └─ HindsightToolSpec (extends BaseToolSpec)
       ├─ retain_memory()     → Hindsight retain (extract facts, entities, relationships)
       ├─ recall_memory()     → Hindsight recall (semantic + graph + temporal retrieval)
       └─ reflect_on_memory() → Hindsight reflect (synthesize a reasoned answer)
```

`HindsightToolSpec` extends LlamaIndex's `BaseToolSpec`. Call `to_tool_list()` and you get standard `FunctionTool` instances that any LlamaIndex agent consumes natively. No monkey-patching, no custom tool wrappers.

Under the hood, Hindsight does more than store text. It extracts structured facts, identifies entities, builds a knowledge graph, and runs multi-strategy retrieval (semantic search, BM25, graph traversal, temporal ranking) with cross-encoder reranking.

Your agent gets a real memory system, not a vector dump.

---

## Step 1 -- Start Hindsight

Install and start the memory server:

```bash
pip install hindsight-all
```

```bash
export HINDSIGHT_API_LLM_API_KEY=YOUR_OPENAI_KEY
hindsight-api
```

This runs locally at `http://localhost:8888` with embedded Postgres, embeddings, and reranking. No external infra needed.

> **Note:** You can also use [Hindsight Cloud](https://ui.hindsight.vectorize.io/signup) and skip the self-hosted setup entirely.

---

## Step 2 -- Install the Integration

```bash
pip install hindsight-llamaindex
```

This pulls in `llama-index-core` and `hindsight-client` as dependencies.

---

## Step 3 -- Create the Memory Bank and Agent

Banks must exist before use. Since LlamaIndex agents are async, wrap everything in `asyncio.run()` for scripts (or use top-level `await` in notebooks):

```python
import asyncio
from hindsight_client import Hindsight
from hindsight_llamaindex import HindsightToolSpec
from llama_index.llms.openai import OpenAI
from llama_index.core.agent import ReActAgent

async def main():
    client = Hindsight(base_url="http://localhost:8888")

    # Create the memory bank (one-time setup)
    await client.acreate_bank("user-123", name="User 123 Memory")

    spec = HindsightToolSpec(
        client=client,
        bank_id="user-123",
        tags=["source:chat"],
        budget="mid",
    )
    tools = spec.to_tool_list()

    agent = ReActAgent(
        tools=tools,
        llm=OpenAI(model="gpt-4o-mini"),
        system_prompt=(
            "You are a helpful assistant with long-term memory. "
            "Use retain_memory to store important facts. "
            "Use recall_memory to search your memory before answering."
        ),
    )

    # Session 1: store preferences
    await agent.run(
        "I'm a data scientist. I use Python, SQL, and VS Code with dark mode."
    )

    # Session 2 (new agent instance, same bank_id): recall works
    agent = ReActAgent(tools=tools, llm=OpenAI(model="gpt-4o-mini"))
    response = await agent.run("What IDE do I use?")
    # → "You use VS Code with dark mode."
    print(response)

asyncio.run(main())
```

That's it. Three tools, one bank, persistent memory.

---

## Convenience Factory

If you don't need full `BaseToolSpec` control, use the factory function:

```python
from hindsight_llamaindex import create_hindsight_tools

tools = create_hindsight_tools(
    client=client,
    bank_id="user-123",
    include_reflect=False,  # only retain + recall
)

agent = ReActAgent(tools=tools, llm=llm)
```

The factory wraps `HindsightToolSpec` and returns a filtered list of `FunctionTool` instances. Use `include_retain`, `include_recall`, and `include_reflect` flags to control which tools are exposed.

---

## Selective Tools via `to_tool_list()`

LlamaIndex's `BaseToolSpec` natively supports selective tool export:

```python
spec = HindsightToolSpec(client=client, bank_id="user-123")

# Only expose recall and reflect — read-only memory access
tools = spec.to_tool_list(spec_functions=["recall_memory", "reflect_on_memory"])
```

This is useful when you want different agents to have different memory capabilities. A research agent might get all three tools, while a reporting agent only gets read-only access.

---

## Per-User Memory Banks

Use parameterized `bank_id` to give each user their own memory:

```python
def create_agent_for_user(user_id: str) -> ReActAgent:
    spec = HindsightToolSpec(
        client=client,
        bank_id=f"user-{user_id}",
    )
    return ReActAgent(
        tools=spec.to_tool_list(),
        llm=OpenAI(model="gpt-4o-mini"),
    )
```

Each bank is fully isolated -- no cross-user data leakage.

---

## Production Patterns

### Memory Scoping with Tags

Use tags to organize memories by source, conversation, or topic. For multi-tenant applications, use one bank per user and tags per context:

```python
spec = HindsightToolSpec(
    client=client,
    bank_id=f"user-{user_id}",
    tags=["source:chat", f"session:{session_id}"],
    recall_tags=["source:chat"],
)
```

### Error Handling

All tool methods raise `HindsightError` on failure. In production, wrap agent execution to handle memory unavailability gracefully — agents can still function without memory.

---

## Pitfalls and Edge Cases

**1. Bank must exist before use.** Call `client.create_bank(bank_id, name=...)` before your agent starts. If the bank doesn't exist, retain/recall will fail.

**2. Async processing delay.** After `retain_memory`, Hindsight processes the content asynchronously (extracting facts, entities, embeddings). If you retain and immediately recall, the new memories may not be searchable yet. In practice, this takes 1-3 seconds.

**3. Budget tuning.** The default `budget="mid"` balances speed and thoroughness. For latency-sensitive agents, use `"low"`. For deep analysis, use `"high"`. Budget affects how many retrieval strategies run and how much reranking happens.

**4. Reflect vs Recall.** Use `recall_memory` when you need raw facts ("What IDE do I use?"). Use `reflect_on_memory` when you need synthesis ("Based on everything you know, what should I prioritize?"). Reflect is more expensive but produces reasoned answers.

---

## When NOT to use this

- **In-session context only** — If your agent only needs to remember things within a single conversation, LlamaIndex's `ChatMemoryBuffer` is simpler and has zero latency overhead.
- **Document search** — If you need vector search over documents (RAG), use LlamaIndex's built-in `VectorStoreIndex`. Hindsight is a memory system for facts learned over time, not a document store.
- **Ephemeral agents** — If each agent invocation is stateless by design (batch processing, one-shot tasks), persistent memory adds complexity without benefit.

---

## Recap

- `hindsight-llamaindex` gives LlamaIndex agents persistent, compounding memory
- It implements `BaseToolSpec`, so tools work natively with any LlamaIndex agent
- Three tools: retain (store), recall (search), reflect (synthesize)
- Per-user banks for memory isolation
- Selective tool export via `spec_functions` or `include_*` flags

---

## Next Steps

- **Try it locally**: `pip install hindsight-all hindsight-llamaindex` and run the example above
- **Use Hindsight Cloud**: Skip self-hosting with a [free account](https://ui.hindsight.vectorize.io/signup)
- **Run the cookbook notebook**: [LlamaIndex ReAct Agent](https://github.com/vectorize-io/hindsight-cookbook/blob/main/notebooks/08-llamaindex-react-agent.ipynb)
- **Read the docs**: [LlamaIndex integration guide](https://docs.hindsight.vectorize.io/docs/sdks/integrations/llamaindex)
- **Explore other integrations**: [LangGraph](/blog/langgraph-memory), [Pydantic AI](/docs/sdks/integrations/pydantic-ai), [CrewAI](/blog/crewai), [Agno](/docs/sdks/integrations/agno)
