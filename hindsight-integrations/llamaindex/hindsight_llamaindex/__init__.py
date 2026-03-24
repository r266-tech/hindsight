"""Hindsight-LlamaIndex: Persistent memory tools for LlamaIndex agents.

Provides a ``BaseToolSpec`` subclass and a convenience factory that give
LlamaIndex agents long-term memory via Hindsight's retain/recall/reflect APIs.

Basic usage with the tool spec::

    from hindsight_client import Hindsight
    from hindsight_llamaindex import HindsightToolSpec

    client = Hindsight(base_url="http://localhost:8888")
    spec = HindsightToolSpec(client=client, bank_id="user-123")
    tools = spec.to_tool_list()

    # Use with a LlamaIndex agent
    agent = ReActAgent.from_tools(tools, llm=llm)

Convenience factory::

    from hindsight_llamaindex import create_hindsight_tools

    tools = create_hindsight_tools(
        client=client,
        bank_id="user-123",
        include_reflect=False,  # only retain + recall
    )
"""

from .config import (
    HindsightLlamaIndexConfig,
    configure,
    get_config,
    reset_config,
)
from .errors import HindsightError
from .tools import HindsightToolSpec, create_hindsight_tools

__version__ = "0.1.0"

__all__ = [
    "configure",
    "get_config",
    "reset_config",
    "HindsightLlamaIndexConfig",
    "HindsightError",
    "HindsightToolSpec",
    "create_hindsight_tools",
]
