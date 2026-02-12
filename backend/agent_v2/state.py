from __future__ import annotations

from typing import Annotated
from typing import Any

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class AgentV2State(TypedDict):
    """Planner-router agent state with dynamic tool/context loading."""

    messages: Annotated[list, add_messages]
    summary: str
    route: str
    intent_labels: list[str]
    disallow_execute_code: bool
    planner_reason: str
    needs_db: bool
    needs_kb: bool
    needs_web: bool
    active_tool_names: list[str]
    loaded_context: dict[str, Any]
    needs_schema_preflight: bool
    needs_answer_rewrite: bool
