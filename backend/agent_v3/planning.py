from __future__ import annotations


from backend.agent_v3.state import AgentV3State, StepState
from backend.llm import get_llm_model
from backend.agent_v3.tools import TOOL_REGISTRY
from backend.agent_v3.prompts import load_chat_prompt

from langchain_core.runnables import RunnableConfig
from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field
from typing import Any, cast

SCHEMA_PREFLIGHT_PATH = "artifacts/DB_SCHEMA_REFERENCE.yaml"


tool_descriptions = "\n".join(
    f"- {name}: {structured_tool.description}"
    for name, structured_tool in TOOL_REGISTRY.items()
)


class PlannerStep(BaseModel):
    id: str = ""
    instruction: str
    tool: str
    tool_args: dict[str, Any] | None = None


class Plan(BaseModel):
    steps: list[PlannerStep] = Field(default_factory=list)


def _latest_user_question(messages: list[Any]) -> str:
    for message in reversed(messages):
        msg_type = str(getattr(message, "type", "")).lower()
        if msg_type not in {"human", "user"}:
            continue
        content = getattr(message, "content", "")
        if isinstance(content, list):
            text_parts: list[str] = []
            for part in content:
                if isinstance(part, str):
                    text_parts.append(part)
                elif isinstance(part, dict) and "text" in part:
                    text_parts.append(str(part["text"]))
            text = " ".join(text_parts).strip()
        else:
            text = str(content or "").strip()
        if "[USER QUESTION]" in text:
            parts = text.split("[USER QUESTION]", 1)
            if len(parts) > 1:
                return parts[1].strip()
        return text
    return ""


def _to_runtime_steps(planner_steps: list[PlannerStep]) -> list[StepState]:
    runtime_steps: list[StepState] = []
    for i, step in enumerate(planner_steps, start=1):
        step_id = str(step.id or "").strip() or str(i)
        runtime_steps.append(
            StepState(
                id=step_id,
                instruction=step.instruction,
                tool=step.tool,
                tool_args=step.tool_args,
            )
        )
    return runtime_steps


def _ensure_schema_preflight(steps: list[StepState]) -> list[StepState]:
    has_sql = any(step.tool == "execute_sql" for step in steps)
    if not has_sql:
        return steps

    has_schema_read = any(
        step.tool == "read_file"
        and isinstance(step.tool_args, dict)
        and str(step.tool_args.get("path") or "").strip() == SCHEMA_PREFLIGHT_PATH
        for step in steps
    )
    if has_schema_read:
        return steps

    schema_step = StepState(
        id="schema_preflight",
        instruction=(
            "Read artifacts/DB_SCHEMA_REFERENCE.yaml to ground logical table and "
            "column names before writing SQL."
        ),
        tool="read_file",
        tool_args={"path": SCHEMA_PREFLIGHT_PATH},
    )
    return [schema_step] + steps


def planner(state: AgentV3State, config: RunnableConfig) -> dict[str, Any]:
    model = get_llm_model().with_structured_output(Plan)
    prompt_template = load_chat_prompt("planner")

    existing_messages = state.messages if hasattr(state, "messages") else state.messages
    messages = prompt_template.invoke(
        {"messages": existing_messages, "tool_descriptions": tool_descriptions}
    )

    plan = model.invoke(messages)
    plan = cast(Plan, plan)
    planned_steps = _ensure_schema_preflight(_to_runtime_steps(plan.steps))

    plan_text = "**Plan:**\n" + "\n".join(
        f"{i + 1}. {step.instruction}" for i, step in enumerate(planned_steps)
    )

    return {
        "messages": [AIMessage(content=plan_text)],
        "steps": planned_steps,
        "current_step_index": 0,
        "failed_step_index": None,
        "should_replan": False,
        "replan_attempts": state.replan_attempts,
        "terminal_error": None,
        "last_planned_user_question": _latest_user_question(existing_messages),
    }
