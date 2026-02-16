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
from backend.llm import get_llm_model

MAX_REPLAN_ATTEMPTS = 1


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
                "tool": step.selected_tool,
                "attempts": step.attempts,
                "result": step.result_payload
                or _safe_json_loads(step.result_summary),
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
                "tool": step.selected_tool,
                "attempts": step.attempts,
                "error_code": step.last_error_code,
                "error": step.error,
            }
        )
    return payloads


def _first_pending_index(state: AgentV3State) -> int:
    for idx, step in enumerate(state.steps):
        if step.status in {"pending", "running"}:
            return idx
    return len(state.steps)


def _first_failed_index(state: AgentV3State) -> int | None:
    for idx, step in enumerate(state.steps):
        if step.status == "failed":
            return idx
    return None


def ensure_system_prompt(state: AgentV3State, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    existing = state.messages

    system_prompt = load_chat_prompt("agent").invoke({"messages": []}).to_messages()[0]

    if _has_system_message(existing, expected=_content_to_text(system_prompt.content)):
        return {}

    return {"messages": [system_prompt]}


def master(state: AgentV3State, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    latest_question = _latest_user_question(state.messages)

    if state.terminal_error:
        return {"next_step": "respond"}

    if latest_question and latest_question != (state.last_user_question or ""):
        return {
            "next_step": "plan",
            "failed_step_index": None,
            "terminal_error": None,
        }

    failed_idx = _first_failed_index(state)
    if failed_idx is not None:
        if state.replan_attempts < MAX_REPLAN_ATTEMPTS:
            return {
                "next_step": "plan",
                "failed_step_index": failed_idx,
                "replan_attempts": state.replan_attempts + 1,
            }
        failed_step = state.steps[failed_idx]
        return {
            "next_step": "respond",
            "terminal_error": failed_step.error or "Task failed after retries.",
            "failed_step_index": failed_idx,
        }

    if not state.plan_requires_execution:
        return {"next_step": "respond"}

    if not state.steps:
        if latest_question and latest_question == (state.last_user_question or ""):
            return {
                "next_step": "respond",
                "terminal_error": (
                    "Planner returned no actionable steps for the current request."
                ),
            }
        return {"next_step": "plan"}

    pending_idx = _first_pending_index(state)
    if pending_idx >= len(state.steps):
        return {"next_step": "respond", "current_step_index": pending_idx}

    return {
        "next_step": "execute",
        "current_step_index": pending_idx,
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
                    "Do not include internal reasoning or debug traces. "
                    "If there are rows/data results, present them clearly. "
                    "If partial failure occurred, include one concise limitation note."
                )
            ),
            HumanMessage(
                content=(
                    "User request:\n"
                    f"{user_question or '(missing user request)'}\n\n"
                    "Completed step outputs (JSON):\n"
                    f"{json.dumps(completed, default=str)}\n\n"
                    "Failed steps (JSON):\n"
                    f"{json.dumps(failed, default=str)}\n\n"
                    "Current alert context (JSON):\n"
                    f"{state.current_alert.model_dump_json()}\n\n"
                    "Terminal error (if any):\n"
                    f"{state.terminal_error or ''}"
                )
            ),
        ]
    )
    return {"messages": [ai_msg]}


def router(state: AgentV3State) -> str:
    mapping = {
        "plan": "planner",
        "respond": "respond",
        "execute": "executioner",
    }
    return mapping[state.next_step]


def build_graph():
    workflow = StateGraph(state_schema=AgentV3State, input_schema=AgentInputSchema)
    workflow.add_node("ensure_system_prompt", ensure_system_prompt)
    workflow.add_node("master", master)
    workflow.add_node("planner", planner)
    workflow.add_node("respond", respond)
    workflow.add_node("executioner", executioner)

    workflow.add_edge(START, "ensure_system_prompt")
    workflow.add_edge("ensure_system_prompt", "master")
    workflow.add_conditional_edges(
        "master",
        router,
        {
            "planner": "planner",
            "respond": "respond",
            "executioner": "executioner",
        },
    )
    workflow.add_edge("planner", "master")
    workflow.add_edge("executioner", "master")
    workflow.add_edge("respond", END)

    return workflow


workflow = build_graph()
