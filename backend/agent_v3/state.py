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


class StepState(BaseModel):
    id: str
    instruction: str
    tool: str
    tool_args: dict[str, Any] | None = None
    status: Literal["pending", "running", "done", "failed", "skipped"] = "pending"
    attempts: int = Field(default=0, ge=0)
    correction_attempts: int = Field(default=0, ge=0)
    started_at: str | None = None
    finished_at: str | None = None
    result_summary: str | None = None
    error: str | None = None
    last_error_code: str | None = None
    last_attempt_signature: str | None = None
    correction_history: list[CorrectionAttempt] = Field(default_factory=list)


class AgentV3State(BaseModel):
    messages: Annotated[list[AnyMessage], add_messages] = Field(default_factory=list)
    steps: list[StepState] = Field(default_factory=list)
    current_step_index: int = Field(default=0, ge=0)
    max_steps: int = Field(default=10, ge=1)
    next_step: Literal["respond", "execute", "plan", "correct"] = Field(
        default="execute"
    )
    failed_step_index: int | None = Field(default=None, ge=0)
    should_replan: bool = False
    replan_attempts: int = Field(default=0, ge=0)
    terminal_error: str | None = None
    last_planned_user_question: str | None = None


class AgentInputSchema(BaseModel):
    messages: Annotated[list[AnyMessage], add_messages] = Field(default_factory=list)
