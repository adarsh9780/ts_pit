from __future__ import annotations

from typing import Annotated, Literal, Any
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class CorrectionAttempt(BaseModel):
    attempt: int = Field(ge=1)
    error_code: str | None = None
    error_message: str | None = None
    old_args: dict[str, Any] = Field(default_factory=dict)
    new_args: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None


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
    messages: Annotated[list[AnyMessage], add_messages] = Field(default_factory=list)
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
    plan_id: str | None = None
    plan_version: int = Field(default=0, ge=0)


class AgentInputSchema(BaseModel):
    messages: Annotated[list[AnyMessage], add_messages] = Field(default_factory=list)
    current_alert: CurrentAlertContext = Field(default_factory=CurrentAlertContext)
