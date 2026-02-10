from __future__ import annotations

from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from .tools import (
    TOOL_REGISTRY,
)
from ..llm import get_llm_model
from .prompts import AGENT_V2_SYSTEM_PROMPT
from .state import AgentV2State

ALL_TOOLS = list(TOOL_REGISTRY.values())


def ensure_system_prompt(state: AgentV2State, config: RunnableConfig) -> dict:
    _ = config
    messages = state.get("messages", [])
    has_system = any(
        isinstance(m, SystemMessage) and getattr(m, "id", None) == "agent-v2-system-prompt"
        for m in messages
    )
    if has_system:
        return {}
    return {
        "messages": [
            SystemMessage(content=AGENT_V2_SYSTEM_PROMPT, id="agent-v2-system-prompt")
        ]
    }


def _latest_user_text(messages: list) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage) or getattr(message, "type", "") == "human":
            return str(getattr(message, "content", "") or "").strip()
    if messages:
        return str(getattr(messages[-1], "content", "") or "").strip()
    return ""


def _contains_any(text_value: str, tokens: tuple[str, ...]) -> bool:
    lowered = text_value.lower()
    return any(token in lowered for token in tokens)


def plan_request(state: AgentV2State, config: RunnableConfig) -> dict:
    _ = config
    text_value = _latest_user_text(state.get("messages", []))

    needs_web = _contains_any(
        text_value,
        ("web", "internet", "online", "external", "latest news", "search"),
    )
    needs_kb = _contains_any(
        text_value,
        ("methodology", "method", "framework", "definition", "explain score", "why"),
    )
    needs_db = _contains_any(
        text_value,
        ("alert", "article", "sql", "database", "table", "ticker", "isin", "status", "count"),
    )
    needs_report = _contains_any(
        text_value,
        ("report", "download", "export", "pdf", "artifact"),
    )
    needs_compute = _contains_any(
        text_value,
        ("calculate", "compute", "correlation", "regression", "python", "simulate"),
    )

    direct_smalltalk = _contains_any(
        text_value,
        ("hello", "hi", "thanks", "thank you", "who are you"),
    ) and not (needs_db or needs_kb or needs_web or needs_report or needs_compute)

    # Temporary simplification: for non-smalltalk requests, expose full toolset.
    # This disables dynamic tool gating and makes planner failures less likely.
    active_tool_names: list[str] = [] if direct_smalltalk else list(TOOL_REGISTRY.keys())

    active_tool_names = [
        name for name in dict.fromkeys(active_tool_names) if name in TOOL_REGISTRY
    ]

    route = "direct" if direct_smalltalk else "agent"
    reason = (
        f"needs_db={needs_db}, needs_kb={needs_kb}, needs_web={needs_web}, "
        f"needs_compute={needs_compute}, needs_report={needs_report}, "
        f"route={route}, tool_mode={'all_tools' if not direct_smalltalk else 'direct'}"
    )
    return {
        "route": route,
        "planner_reason": reason,
        "needs_db": needs_db,
        "needs_kb": needs_kb,
        "needs_web": needs_web,
        "active_tool_names": active_tool_names,
    }


def load_context(state: AgentV2State, config: RunnableConfig) -> dict:
    _ = config
    loaded_context: dict[str, str] = {}
    context_lines: list[str] = []

    if state.get("needs_db"):
        loaded_context["db"] = "Use `get_schema` first if column/table names are uncertain."
        context_lines.append("- DB context is available via `get_schema` and `execute_sql`.")

    if state.get("needs_kb"):
        loaded_context["kb"] = "Use file tools to discover and load only required documents."
        context_lines.append("- Document context is available via `list_files` and `read_file`.")

    if state.get("needs_web"):
        loaded_context["web"] = "Use web search tools only when internal data is insufficient."
        context_lines.append("- Web context is available via `search_web`/`search_web_news` and optional `scrape_websites`.")

    if not context_lines:
        context_lines.append("- No extra context preloaded for this request.")

    runtime_context = (
        "Planner summary:\n"
        f"{state.get('planner_reason', '')}\n"
        "Runtime context:\n"
        + "\n".join(context_lines)
    )

    return {
        "loaded_context": loaded_context,
        "messages": [SystemMessage(content=runtime_context, id="agent-v2-runtime-context")],
    }


def route_after_plan(state: AgentV2State) -> Literal["direct_answer", "agent"]:
    return "direct_answer" if state.get("route") == "direct" else "agent"


def direct_answer_node(state: AgentV2State, config: RunnableConfig):
    _ = config
    llm = get_llm_model()
    response = llm.invoke(state["messages"])
    return {"messages": [response]}


def agent_node(state: AgentV2State, config: RunnableConfig):
    _ = config
    llm = get_llm_model()
    active_names = state.get("active_tool_names") or []
    selected_tools = [TOOL_REGISTRY[name] for name in active_names if name in TOOL_REGISTRY]
    if selected_tools:
        response = llm.bind_tools(selected_tools).invoke(state["messages"])
    else:
        response = llm.invoke(state["messages"])
    return {"messages": [response]}


def should_continue(state: AgentV2State) -> Literal["tools", "__end__"]:
    messages = state["messages"]
    if not messages:
        return "__end__"
    last_message = messages[-1]
    if getattr(last_message, "tool_calls", None):
        return "tools"
    return "__end__"


def build_graph():
    tool_node = ToolNode(ALL_TOOLS)

    workflow = StateGraph(AgentV2State)
    workflow.add_node("ensure_system_prompt", ensure_system_prompt)
    workflow.add_node("plan_request", plan_request)
    workflow.add_node("load_context", load_context)
    workflow.add_node("direct_answer", direct_answer_node)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)

    workflow.add_edge(START, "ensure_system_prompt")
    workflow.add_edge("ensure_system_prompt", "plan_request")
    workflow.add_edge("plan_request", "load_context")
    workflow.add_conditional_edges("load_context", route_after_plan)
    workflow.add_edge("direct_answer", END)
    workflow.add_conditional_edges("agent", should_continue)
    workflow.add_edge("tools", "agent")

    return workflow


workflow = build_graph()
