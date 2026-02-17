from __future__ import annotations

from uuid import uuid4

from ts_pit.agent_v3.state import AgentV3State, StepState
from ts_pit.agent_v3.prompts import load_chat_prompt
from ts_pit.agent_v3.tools import TOOL_REGISTRY
from ts_pit.agent_v3.utils import build_prompt_messages
from ts_pit.llm import get_llm_model

from langchain_core.runnables import RunnableConfig
from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field, ValidationError
from typing import Any, Literal, cast


class PlannerStep(BaseModel):
    instruction: str
    goal: str | None = None
    success_criteria: str | None = None
    constraints: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    plan_action: Literal["reuse", "append", "replace"] = "append"
    requires_execution: bool = True
    requires_execution_reason: str = ""
    steps: list[PlannerStep] = Field(default_factory=list)


PLAN_RESPONSE_SCHEMA: dict[str, Any] = {
    "title": "PlannerResponse",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "plan_action": {
            "type": "string",
            "enum": ["reuse", "append", "replace"],
        },
        "requires_execution": {"type": "boolean"},
        "requires_execution_reason": {"type": "string"},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "instruction": {"type": "string"},
                    "goal": {"type": "string"},
                    "success_criteria": {"type": "string"},
                    "constraints": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["instruction"],
            },
        },
    },
    "required": [
        "plan_action",
        "requires_execution",
        "requires_execution_reason",
        "steps",
    ],
}


SCHEMA_PRECHECK_HINT = "artifacts/DB_SCHEMA_REFERENCE.yaml"
ARTIFACT_KNOWLEDGE = (
    "artifacts/* contains reference material the agent can read for planning and execution:\n"
    "- Business methodology\n"
    "- Technical implementation\n"
    "- Database schema mappings (especially DB_SCHEMA_REFERENCE.yaml)"
)
TOOL_DESCRIPTIONS = "\n".join(
    f"- {name}: {tool.description}" for name, tool in TOOL_REGISTRY.items()
)
PLANNER_RECENT_WINDOW = 16

SQL_INTENT_KEYWORDS = {
    "sql",
    "database",
    "table",
    "column",
    "select",
    "join",
    "from ",
    "group by",
    "where",
}

DIRECT_STATE_QUESTION_KEYWORDS = {
    "which alert is currently selected",
    "current selected alert",
    "selected alert",
    "current alert",
}


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


def _step_snapshot(step: StepState) -> dict[str, Any]:
    return {
        "id": step.id,
        "instruction": step.instruction,
        "goal": step.goal,
        "success_criteria": step.success_criteria,
        "constraints": step.constraints,
        "status": step.status,
        "attempts": step.attempts,
        "selected_tool": step.selected_tool,
        "result": step.result_payload,
        "error_code": step.last_error_code,
        "error": step.error,
    }


def _make_step_id(plan_version: int, index: int) -> str:
    return f"v{plan_version}_s{index}"


def _planner_steps_to_runtime(
    planner_steps: list[PlannerStep],
    *,
    start_index: int,
    plan_version: int,
) -> list[StepState]:
    runtime_steps: list[StepState] = []
    for offset, step in enumerate(planner_steps, start=1):
        runtime_steps.append(
            StepState(
                id=_make_step_id(plan_version, start_index + offset),
                instruction=step.instruction,
                goal=step.goal,
                success_criteria=step.success_criteria,
                constraints=step.constraints,
            )
        )
    return runtime_steps


def _first_pending_index(steps: list[StepState]) -> int:
    for idx, step in enumerate(steps):
        if step.status in {"pending", "running"}:
            return idx
    return len(steps)


def _has_pending_steps(steps: list[StepState]) -> bool:
    return any(step.status in {"pending", "running"} for step in steps)


def _text_has_sql_intent(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(keyword in lowered for keyword in SQL_INTENT_KEYWORDS)


def _is_direct_state_question(query: str) -> bool:
    lowered = str(query or "").lower()
    return any(kw in lowered for kw in DIRECT_STATE_QUESTION_KEYWORDS)


def _step_is_schema_grounding_text(text: str) -> bool:
    lowered = str(text or "").lower()
    return (
        "schema" in lowered
        or "db_schema_reference.yaml" in lowered
        or "logical" in lowered
        and "column" in lowered
    )


def _step_has_schema_grounding(step: StepState) -> bool:
    combined = " ".join(
        [
            step.instruction or "",
            step.goal or "",
            step.success_criteria or "",
            " ".join(step.constraints or []),
        ]
    )
    return _step_is_schema_grounding_text(combined)


def _planner_step_has_schema_grounding(step: PlannerStep) -> bool:
    combined = " ".join(
        [
            step.instruction or "",
            step.goal or "",
            step.success_criteria or "",
            " ".join(step.constraints or []),
        ]
    )
    return _step_is_schema_grounding_text(combined)


def _planner_steps_need_schema_grounding(steps: list[PlannerStep]) -> bool:
    for step in steps:
        combined = " ".join(
            [
                step.instruction or "",
                step.goal or "",
                step.success_criteria or "",
                " ".join(step.constraints or []),
            ]
        )
        if _text_has_sql_intent(combined):
            return True
    return False


def _ensure_schema_grounding_step(
    existing_steps: list[StepState], planner_steps: list[PlannerStep]
) -> list[PlannerStep]:
    if not planner_steps:
        return planner_steps
    if not _planner_steps_need_schema_grounding(planner_steps):
        return planner_steps

    existing_has_schema = any(
        _step_has_schema_grounding(step) for step in existing_steps
    )
    incoming_has_schema = any(
        _planner_step_has_schema_grounding(step) for step in planner_steps
    )
    if existing_has_schema or incoming_has_schema:
        return planner_steps

    schema_step = PlannerStep(
        instruction="Read artifacts/DB_SCHEMA_REFERENCE.yaml before any SQL/data query.",
        goal="Ground logical tables/columns and date fields before querying.",
        success_criteria="Mapped logical schema names needed for the next SQL/data step are identified.",
        constraints=[
            "Use artifacts/DB_SCHEMA_REFERENCE.yaml as source of truth.",
            "Do not guess physical DB column names before schema grounding.",
        ],
    )
    return [schema_step] + planner_steps


def _merge_plan(
    state: AgentV3State, plan: Plan
) -> tuple[list[StepState], list[StepState]]:
    existing = list(state.steps)
    archived = list(state.archived_steps)

    if plan.plan_action == "reuse":
        return existing, archived

    next_plan_version = max(state.plan_version + 1, 1)

    if plan.plan_action == "replace":
        ensured_steps = _ensure_schema_grounding_step(existing, plan.steps)
        for idx, step in enumerate(existing):
            if step.status in {"pending", "running", "failed"}:
                existing[idx] = step.model_copy(update={"status": "skipped"})
                archived.append(step)
        new_steps = _planner_steps_to_runtime(
            ensured_steps,
            start_index=len(existing),
            plan_version=next_plan_version,
        )
        return existing + new_steps, archived

    # append
    ensured_steps = _ensure_schema_grounding_step(existing, plan.steps)
    new_steps = _planner_steps_to_runtime(
        ensured_steps,
        start_index=len(existing),
        plan_version=next_plan_version,
    )
    return existing + new_steps, archived


def planner(state: AgentV3State, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    model = get_llm_model().with_structured_output(PLAN_RESPONSE_SCHEMA)
    prompt_template = load_chat_prompt("planner")

    user_query = _latest_user_question(state.messages)
    completed = [_step_snapshot(s) for s in state.steps if s.status == "done"]
    pending = [
        _step_snapshot(s) for s in state.steps if s.status in {"pending", "running"}
    ]
    failed = [_step_snapshot(s) for s in state.steps if s.status == "failed"]

    messages = prompt_template.invoke(
        {
            "query": user_query,
            "messages": build_prompt_messages(
                state.messages,
                conversation_summary=state.conversation_summary,
                recent_window=PLANNER_RECENT_WINDOW,
            ),
            "current_alert": state.current_alert.model_dump_json(),
            "completed_steps": completed,
            "pending_steps": pending,
            "failed_steps": failed,
            "tool_descriptions": TOOL_DESCRIPTIONS,
            "artifact_knowledge": ARTIFACT_KNOWLEDGE,
            "conversation_summary": state.conversation_summary or "(none)",
        }
    )

    raw_plan = model.invoke(messages)
    if not isinstance(raw_plan, dict):
        raw_plan = {}
    try:
        plan = Plan.model_validate(raw_plan)
    except ValidationError:
        plan = Plan()

    # Deterministic direct-answer fallback for state-only questions.
    if _is_direct_state_question(user_query):
        plan = plan.model_copy(
            update={
                "requires_execution": False,
                "requires_execution_reason": (
                    "The request can be answered directly from current alert context "
                    "and prior completed outputs."
                ),
                "plan_action": "replace",
                "steps": [],
            }
        )

    # Safety: `reuse` is only valid when existing plan has actionable pending work.
    if plan.plan_action == "reuse" and not _has_pending_steps(state.steps):
        plan = plan.model_copy(update={"plan_action": "append"})

    # Safety: avoid no-op loops on empty planner output.
    if (
        plan.requires_execution
        and plan.plan_action in {"append", "replace"}
        and not plan.steps
    ):
        plan = plan.model_copy(
            update={
                "steps": [
                    PlannerStep(
                        instruction=user_query or "Complete the user's latest request.",
                        goal="Produce the requested result for the current user question.",
                        success_criteria="At least one actionable execution step is available.",
                        constraints=[],
                    )
                ]
            }
        )
    if plan.requires_execution:
        merged_steps, archived_steps = _merge_plan(state, plan)
    else:
        # For direct-answer requests, archive unresolved execution work to avoid
        # accidentally running stale pending steps from previous questions.
        merged_steps = list(state.steps)
        archived_steps = list(state.archived_steps)
        for idx, step in enumerate(merged_steps):
            if step.status in {"pending", "running", "failed"}:
                merged_steps[idx] = step.model_copy(update={"status": "skipped"})
                archived_steps.append(step)

    plan_lines = [
        f"Plan action: {plan.plan_action}",
        f"Requires execution: {str(plan.requires_execution).lower()}",
        f"Execution reason: {plan.requires_execution_reason or 'not provided'}",
        "",
        "**Plan:**",
    ]
    display_steps = [s for s in merged_steps if s.status in {"pending", "running"}]
    if not display_steps:
        plan_lines.append("No tool execution required for this request.")
    for i, step in enumerate(display_steps, start=1):
        plan_lines.append(f"{i}. {step.instruction}")

    updated_plan_version = state.plan_version
    updated_plan_id = state.plan_id
    if plan.plan_action in {"append", "replace"}:
        updated_plan_version = max(state.plan_version + 1, 1)
        updated_plan_id = state.plan_id or str(uuid4())

    return {
        "messages": [
            AIMessage(
                content="\n".join(plan_lines),
                additional_kwargs={"ephemeral_node_output": "planner"},
            )
        ],
        "steps": merged_steps,
        "archived_steps": archived_steps,
        "current_step_index": _first_pending_index(merged_steps),
        "failed_step_index": None,
        "should_replan": False,
        "replan_attempts": state.replan_attempts,
        "terminal_error": None,
        "last_user_question": user_query,
        "plan_action": plan.plan_action,
        "plan_requires_execution": plan.requires_execution,
        "plan_requires_execution_reason": plan.requires_execution_reason or None,
        "plan_id": updated_plan_id,
        "plan_version": updated_plan_version,
    }
