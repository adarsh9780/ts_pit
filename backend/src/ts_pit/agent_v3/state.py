from __future__ import annotations

from typing import Annotated, Literal, Any
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


def _should_persist_message(message: AnyMessage) -> bool:
    msg_type = str(getattr(message, "type", "")).lower()
    if msg_type == "tool":
        return False
    additional = getattr(message, "additional_kwargs", None)
    if isinstance(additional, dict) and additional.get("ephemeral_node_output"):
        return False
    return True


def add_persistent_messages(
    left: list[AnyMessage], right: list[AnyMessage] | AnyMessage
) -> list[AnyMessage]:
    merged = add_messages(left, right)
    return [message for message in merged if _should_persist_message(message)]


class CorrectionAttempt(BaseModel):
    attempt: int = Field(ge=1)
    error_code: str | None = None
    error_message: str | None = None
    old_args: dict[str, Any] = Field(default_factory=dict)
    new_args: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None


class AnswerFeedback(BaseModel):
    decision: Literal["accept", "rewrite", "escalate"] = "accept"
    reason: str = ""
    issues: list[str] = Field(default_factory=list)
    rewrite_instructions: str | None = None
    confidence: float | None = None


class CurrentAlertContext(BaseModel):
    alert_id: int | None = Field(
        default=None,
        description="Id of the currently selected alert by the user, should be provided by the frontend",
    )
    ticker: str | None = Field(default=None, description="ticker of the current alert")
    start_date: str | None = Field(
        default=None, description="Start of the investigation window"
    )
    end_date: str | None = Field(
        default=None, description="End of the investigation window"
    )
    buy_qt: int = Field(default=0, description="Sum of buy quantity")
    sell_qt: int = Field(default=0, description="Sum of sell quantity")


class StepState(BaseModel):
    id: str
    instruction: str
    goal: str | None = None
    success_criteria: str | None = None
    constraints: list[str] = Field(default_factory=list)
    selected_tool: str | None = None
    tool_args: dict[str, Any] | None = None
    status: Literal["pending", "running", "done", "failed", "skipped"] = "pending"
    attempts: int = Field(default=0, ge=0)
    started_at: str | None = None
    finished_at: str | None = None
    result_summary: str | None = None
    result_payload: dict[str, Any] | None = None
    error: str | None = None
    last_error_code: str | None = None
    last_attempt_signature: str | None = None
    retry_history: list[CorrectionAttempt] = Field(default_factory=list)


class AgentV3State(BaseModel):
    messages: Annotated[list[AnyMessage], add_persistent_messages] = Field(default_factory=list)
    current_alert: CurrentAlertContext = Field(default_factory=CurrentAlertContext)
    steps: list[StepState] = Field(default_factory=list)
    archived_steps: list[StepState] = Field(default_factory=list)
    current_step_index: int = Field(default=0, ge=0)
    max_steps: int = Field(default=10, ge=1)
    next_step: Literal["respond", "execute", "plan"] = Field(default="execute")
    failed_step_index: int | None = Field(default=None, ge=0)
    should_replan: bool = False
    replan_attempts: int = Field(default=0, ge=0)
    terminal_error: str | None = None
    last_user_question: str | None = None
    plan_action: Literal["reuse", "append", "replace", "none"] = "none"
    plan_requires_execution: bool = True
    plan_requires_execution_reason: str | None = None
    plan_id: str | None = None
    plan_version: int = Field(default=0, ge=0)
    conversation_summary: str | None = None
    summary_version: int = Field(default=0, ge=0)
    last_summarized_message_index: int = Field(default=0, ge=0)
    token_estimate: int = Field(default=0, ge=0)
    intent_class: Literal[
        "task",
        "meta_help",
        "blocked_user_code",
        "blocked_safety",
        "analyze_current_alert",
        "analyze_other_alert",
        "needs_clarification",
    ] = "task"
    intent_confidence: float | None = None
    intent_reason: str | None = None
    intent_target_alert_id: int | None = None
    guardrail_response: str | None = None
    needs_clarification: bool = False
    clarification_reason: str | None = None
    clarification_question: str | None = None
    clarification_questions: list[str] = Field(default_factory=list)
    clarification_signature: str | None = None
    clarification_asked_turns: int = Field(default=0, ge=0)
    max_clarification_turns: int = Field(default=1, ge=0)
    clarification_resolved: bool = False
    assumption_risk: Literal["low", "medium", "high"] = "low"
    assumption_candidate: str | None = None
    clarify_decision_reason: str | None = None
    draft_answer: str | None = None
    last_answer_feedback: AnswerFeedback | None = None
    answer_revision_attempts: int = Field(default=0, ge=0)
    master_escalations_from_validation: int = Field(default=0, ge=0)
    max_answer_revision_attempts: int = Field(default=1, ge=0)
    max_master_escalations_from_validation: int = Field(default=1, ge=0)


class AgentInputSchema(BaseModel):
    messages: Annotated[list[AnyMessage], add_persistent_messages] = Field(default_factory=list)
    current_alert: CurrentAlertContext = Field(default_factory=CurrentAlertContext)
