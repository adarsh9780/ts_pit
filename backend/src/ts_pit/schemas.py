"""
Structured Output Schemas for LLM Responses
============================================
This module defines Pydantic models for structured LLM outputs.
Using structured outputs ensures type safety and consistent response formats.

Industry Best Practice:
- Define all LLM response schemas in a central location
- Use Pydantic for validation and type hints
- LangChain's `with_structured_output()` uses these for guaranteed format
"""

from typing import Literal

from pydantic import BaseModel, Field


class ClusterSummaryOutput(BaseModel):
    """Schema for news cluster summarization output."""

    narrative_theme: str = Field(
        description="A short 2-4 word phrase summarizing the main public news driver (e.g., 'Q3 Earnings Beat', 'FDA Approval Announced')"
    )
    narrative_summary: str = Field(
        description="A 2-3 sentence executive summary highlighting publicly available information that could justify the trading activity"
    )
    bullish_events: list[str] = Field(
        description="List of 1-2 short text items describing key positive/bullish factors. DO NOT include bullet characters (-, *, •) at the start of each item."
    )
    bearish_events: list[str] = Field(
        description="List of 1-2 short text items describing key negative/bearish factors. DO NOT include bullet characters (-, *, •) at the start of each item."
    )
    neutral_events: list[str] = Field(
        description="List of 1-2 short text items describing neutral or informational factors. DO NOT include bullet characters (-, *, •) at the start of each item."
    )
    recommendation: Literal["DISMISS", "ESCALATE_L2", "NEEDS_REVIEW"] = Field(
        description="FINAL VERDICT enum only: 'DISMISS', 'ESCALATE_L2', or 'NEEDS_REVIEW'"
    )
    recommendation_reason: str = Field(
        description="A detailed markdown bulleted list of specific facts (article counts, scores) justifying the decision."
    )


# Add future schemas below as needed
# Example:
# class RiskAssessmentOutput(BaseModel):
#     risk_level: str = Field(description="LOW, MEDIUM, or HIGH")
#     rationale: str = Field(description="Brief explanation of risk assessment")


class ArticleAnalysisOutput(BaseModel):
    theme: str = Field(description="The strict category label for the event")
