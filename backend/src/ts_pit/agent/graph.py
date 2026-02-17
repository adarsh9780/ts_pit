"""
LangGraph Agent Definition
==========================
Defines the agent graph structure, nodes, and edges.

Simplified architecture:
- System prompt is static (role/persona only)
- Alert context is injected into user messages by the API layer
- No more context_loader node needed
"""

from typing import Literal

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode

from ts_pit.llm import get_llm_model
from ts_pit.agent.state import AgentState
from ts_pit.agent.tools import (
    execute_sql,
    get_schema,
    consult_expert,
    get_alert_details,
    get_alerts_by_ticker,
    count_material_news,
    get_article_by_id,
    analyze_current_alert,
    get_current_alert_news,
    generate_current_alert_report,
    search_web_news,
    scrape_websites,
)
from ts_pit.agent.prompts import AGENT_SYSTEM_PROMPT


# --- NODES ---


def ensure_system_prompt(state: AgentState, config: RunnableConfig) -> dict:
    """
    Ensures system prompt is present in messages.
    Only adds it if not already present (first message in session).
    Uses fixed ID so it's never duplicated.
    """
    messages = state.get("messages", [])

    # Check if system prompt already exists
    has_system = any(
        isinstance(m, SystemMessage) and getattr(m, "id", None) == "system-prompt"
        for m in messages
    )

    if not has_system:
        system_msg = SystemMessage(content=AGENT_SYSTEM_PROMPT, id="system-prompt")
        return {"messages": [system_msg]}

    return {}


def agent_node(state: AgentState, config: RunnableConfig):
    """
    Agent Node: Invokes the LLM with tools.
    """
    messages = state["messages"]

    # Initialize LLM with tools
    llm = get_llm_model()

    tools = [
        execute_sql,
        get_schema,
        consult_expert,
        get_alert_details,
        get_alerts_by_ticker,
        count_material_news,
        get_article_by_id,
        analyze_current_alert,
        get_current_alert_news,
        generate_current_alert_report,
        search_web_news,
        scrape_websites,
    ]

    llm_with_tools = llm.bind_tools(tools)

    last_content = str(messages[-1].content).lower() if messages else ""
    analysis_intent = any(
        kw in last_content
        for kw in ("analyze", "analysis", "recommendation", "assess", "investigate")
    ) and ("current alert context" in last_content or "this alert" in last_content)
    if analysis_intent:
        messages = list(messages) + [
            SystemMessage(
                content=(
                    "For current-alert analysis requests, call analyze_current_alert first, "
                    "then answer using that output. Include evidence citations with article_id and created_date. "
                    "Finish with a short Next steps section grounded in current evidence and chat history."
                )
            )
        ]

    # Invoke
    response = llm_with_tools.invoke(messages)

    return {"messages": [response]}


def should_continue(state: AgentState) -> Literal["tools", "__end__"]:
    """Determine if we should go to tools or end."""
    messages = state["messages"]
    last_message = messages[-1]

    if last_message.tool_calls:
        return "tools"
    return "__end__"


# --- GRAPH BUILDER ---


def build_graph():
    """Builds and return the UNCOMPILED LangGraph workflow."""

    # 1. Define Tools
    tools = [
        execute_sql,
        get_schema,
        consult_expert,
        get_alert_details,
        get_alerts_by_ticker,
        count_material_news,
        get_article_by_id,
        analyze_current_alert,
        get_current_alert_news,
        generate_current_alert_report,
        search_web_news,
        scrape_websites,
    ]
    tool_node = ToolNode(tools)

    # 2. Initialize Graph
    workflow = StateGraph(AgentState)

    # 3. Add Nodes
    workflow.add_node("ensure_system_prompt", ensure_system_prompt)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)

    # 4. Define Edges
    # Start -> Ensure System Prompt -> Agent
    workflow.add_edge(START, "ensure_system_prompt")
    workflow.add_edge("ensure_system_prompt", "agent")

    # Agent -> Tools OR End
    workflow.add_conditional_edges(
        "agent",
        should_continue,
    )

    workflow.add_edge("tools", "agent")

    return workflow


# Expose the workflow (not compiled yet)
# This allows the consumer (main.py, test scripts) to decide on Checkpointer (Sync vs Async)
workflow = build_graph()
