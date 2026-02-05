"""
LangGraph Agent Definition
==========================
Defines the agent graph structure, nodes, and edges.
"""

import sys
import sqlite3
import yaml
from pathlib import Path
from typing import Annotated, Literal

from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode

from backend.llm import get_llm_model
from backend.agent.state import AgentState
from backend.agent.tools import (
    execute_sql,
    get_alert_details,
    get_alerts_by_ticker,
    count_material_news,
    get_price_history,
    search_news,
    update_alert_status,
    DB_SCHEMA,
)
from backend.agent.prompts import AGENT_SYSTEM_PROMPT


# --- NODES ---


def context_loader(state: AgentState, config: RunnableConfig) -> dict:
    """
    Context Loader Node:
    1. Checks if current_alert_id is set.
    2. If set, fetches alert details and injects them into the system prompt.
    3. Always injects the database schema.
    """
    alert_id = state.get("current_alert_id")
    alert_context_str = "No specific alert selected."

    if alert_id:
        try:
            # Fast lookup directly via tool function (it returns string)
            details = get_alert_details.invoke(alert_id)
            alert_context_str = (
                f"User is viewing Alert ID: {alert_id}\nDetails:\n{details}"
            )
        except Exception as e:
            alert_context_str = f"Error loading context for alert {alert_id}: {e}"

    final_prompt = AGENT_SYSTEM_PROMPT.format(
        schema_context=DB_SCHEMA, alert_context=alert_context_str
    )

    return {"messages": [SystemMessage(content=final_prompt)]}


def agent_node(state: AgentState, config: RunnableConfig):
    """
    Agent Node: Invokes the LLM with tools.
    """
    messages = state["messages"]

    # Initialize LLM with tools
    # We cache this typically, but get_llm_model factory is lightweight
    llm = get_llm_model()

    tools = [
        execute_sql,
        get_alert_details,
        get_alerts_by_ticker,
        count_material_news,
        get_price_history,
        search_news,
        update_alert_status,
    ]

    llm_with_tools = llm.bind_tools(tools)

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
        get_alert_details,
        get_alerts_by_ticker,
        count_material_news,
        get_price_history,
        search_news,
        update_alert_status,
    ]
    tool_node = ToolNode(tools)

    # 2. Initialize Graph
    workflow = StateGraph(AgentState)

    # 3. Add Nodes
    workflow.add_node("context_loader", context_loader)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)

    # 4. Define Edges
    # Start -> Context Loader (to refresh context) -> Agent
    workflow.add_edge(START, "context_loader")
    workflow.add_edge("context_loader", "agent")

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
