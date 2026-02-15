"""
Agent V3 Graph — bare-minimum scaffold.

Three nodes, no conditional routing:
  START → ensure_system_prompt → agent ↔ tools → ... → END

The agent node binds ALL tools from TOOL_REGISTRY and lets the LLM decide.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langchain_core.messages import AnyMessage, SystemMessage, HumanMessage

from backend.agent_v3.state import AgentV3State, AgentInputSchema
from backend.agent_v3.planning import planner
from backend.agent_v3.prompts import load_chat_prompt
from backend.agent_v3.execution import executioner
from backend.agent_v3.correction import code_correction
from backend.llm import get_llm_model

FIXABLE_ERROR_CODES = {
    "READ_ONLY_ENFORCED",
    "INVALID_INPUT",
    "TABLE_NOT_FOUND",
    "DB_ERROR",
    "PYTHON_EXEC_ERROR",
    "TOOL_ERROR",
}
MAX_REPLAN_ATTEMPTS = 1
MAX_CORRECTION_ATTEMPTS = 2


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


def _has_system_message(
    messages: list[AnyMessage], expected: str | None = None
) -> bool:
    expected_norm = expected.strip() if isinstance(expected, str) else None

    for m in messages:
        if isinstance(m, SystemMessage):
            current = _content_to_text(m.content).strip()
            if expected_norm is None or current == expected_norm:
                return True
    return False


def _latest_user_question(messages: list[AnyMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage) or getattr(message, "type", "") in {
            "human",
            "user",
        }:
            content = _content_to_text(getattr(message, "content", ""))
            if "[USER QUESTION]" in content:
                parts = content.split("[USER QUESTION]", 1)
                if len(parts) > 1:
                    return parts[1].strip()
            return content.strip()
    return ""


def _safe_json_loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {"raw": str(raw)}


def _completed_step_payloads(state: AgentV3State) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for step in state.steps:
        if step.status != "done":
            continue
        payloads.append(
            {
                "id": step.id,
                "instruction": step.instruction,
                "tool": step.tool,
                "attempts": step.attempts,
                "result": _safe_json_loads(step.result_summary),
            }
        )
    return payloads


def _failed_step_payloads(state: AgentV3State) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for step in state.steps:
        if step.status != "failed":
            continue
        payloads.append(
            {
                "id": step.id,
                "instruction": step.instruction,
                "tool": step.tool,
                "attempts": step.attempts,
                "error_code": step.last_error_code,
                "error": step.error,
            }
        )
    return payloads


# ---------------------------------------------------------------------------
#  Nodes
# ---------------------------------------------------------------------------


def ensure_system_prompt(state: AgentV3State, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    existing = state.messages

    system_prompt = load_chat_prompt("agent").invoke({"messages": []}).to_messages()[0]

    if _has_system_message(existing, expected=_content_to_text(system_prompt.content)):
        return {}  # no-op, already present

    return {"messages": [system_prompt]}


def master(state: AgentV3State, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    latest_question = _latest_user_question(state.messages)
    if latest_question and latest_question != (state.last_planned_user_question or ""):
        return {
            "steps": [],
            "current_step_index": 0,
            "failed_step_index": None,
            "should_replan": False,
            "replan_attempts": 0,
            "terminal_error": None,
            "next_step": "plan",
        }

    if state.terminal_error:
        return {"next_step": "respond"}

    if state.should_replan:
        if state.replan_attempts >= MAX_REPLAN_ATTEMPTS:
            return {
                "next_step": "respond",
                "terminal_error": (
                    state.terminal_error
                    or "Unable to produce a valid execution plan after retries."
                ),
            }
        return {
            "next_step": "plan",
            "should_replan": False,
            "replan_attempts": state.replan_attempts + 1,
        }

    if not state.steps:
        return {"next_step": "plan"}

    if state.current_step_index >= len(state.steps):
        return {"next_step": "respond", "current_step_index": len(state.steps)}

    step_idx = state.current_step_index
    if state.failed_step_index is not None and state.failed_step_index < len(state.steps):
        step_idx = state.failed_step_index
    step = state.steps[step_idx]

    if step.status == "failed":
        if (
            (step.last_error_code or "").upper() in FIXABLE_ERROR_CODES
            and step.correction_attempts < MAX_CORRECTION_ATTEMPTS
        ):
            return {"next_step": "correct", "current_step_index": step_idx}
        if (
            (step.last_error_code or "").upper() in FIXABLE_ERROR_CODES
            and step.correction_attempts >= MAX_CORRECTION_ATTEMPTS
        ):
            return {
                "next_step": "respond",
                "terminal_error": (
                    step.error
                    or f"Step {step.id} exceeded correction attempts ({MAX_CORRECTION_ATTEMPTS})."
                ),
            }
        if state.replan_attempts >= MAX_REPLAN_ATTEMPTS:
            return {
                "next_step": "respond",
                "terminal_error": (
                    step.error
                    or f"Step {step.id} failed with non-fixable error {step.last_error_code}."
                ),
            }
        return {
            "next_step": "plan",
            "failed_step_index": step_idx,
            "replan_attempts": state.replan_attempts + 1,
        }
    elif step.status in {"done", "skipped"}:
        next_index = state.current_step_index + 1
        if next_index >= len(state.steps):
            return {"next_step": "respond", "current_step_index": next_index}
        else:
            return {
                "next_step": "execute",
                "current_step_index": next_index,
            }
    else:
        # step.status in {"pending", "running"}:
        return {
            "next_step": "execute",
            "current_step_index": state.current_step_index,
        }


def respond(state: AgentV3State, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    llm = get_llm_model()
    user_question = _latest_user_question(state.messages)
    completed = _completed_step_payloads(state)
    failed = _failed_step_payloads(state)

    ai_msg = llm.invoke(
        [
            SystemMessage(
                content=(
                    "You are generating the final user-facing answer. "
                    "Answer the user's request directly using completed tool outputs. "
                    "Do not include internal reasoning, planning narration, or tool-debug details. "
                    "If SQL/tool outputs contain rows, present the requested results clearly (prefer table format). "
                    "If partial failure occurred, provide the best available answer and a short limitation note."
                )
            ),
            HumanMessage(
                content=(
                    "User request:\n"
                    f"{user_question or '(missing user request)'}\n\n"
                    "Completed step outputs (JSON):\n"
                    f"{json.dumps(completed, default=str)}\n\n"
                    "Failed steps (JSON):\n"
                    f"{json.dumps(failed, default=str)}"
                )
            ),
        ]
    )
    return {"messages": [ai_msg]}


# def executioner(state: AgentV3State, config: RunnableConfig) -> dict[str, Any]:
#     _ = config
#     step = state.steps[state.current_step_index]
#     step.status = "done"
#     return {"steps": state.steps}


def router(state: AgentV3State) -> str:
    mapping = {
        "plan": "planner",
        "respond": "respond",
        "execute": "executioner",
        "correct": "code_correction",
    }

    return mapping[state.next_step]


# ---------------------------------------------------------------------------
#  Graph builder
# ---------------------------------------------------------------------------


def build_graph():

    workflow = StateGraph(state_schema=AgentV3State, input_schema=AgentInputSchema)
    workflow.add_node("ensure_system_prompt", ensure_system_prompt)
    workflow.add_node("master", master)
    workflow.add_node("planner", planner)
    workflow.add_node("respond", respond)
    workflow.add_node("executioner", executioner)
    workflow.add_node("code_correction", code_correction)

    workflow.add_edge(START, "ensure_system_prompt")
    workflow.add_edge("ensure_system_prompt", "master")
    workflow.add_conditional_edges(
        "master",
        router,
        {
            "planner": "planner",
            "respond": "respond",
            "executioner": "executioner",
            "code_correction": "code_correction",
        },
    )
    workflow.add_edge("planner", "master")
    workflow.add_edge("executioner", "master")
    workflow.add_edge("code_correction", "master")
    workflow.add_edge("respond", END)

    return workflow


# Expose uncompiled workflow — main.py will compile with a checkpointer.
workflow = build_graph()
