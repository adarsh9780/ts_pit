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
        description="List of 1-2 bullet points describing key positive/bullish factors found in the news"
    )
    bearish_events: list[str] = Field(
        description="List of 1-2 bullet points describing key negative/bearish factors found in the news"
    )
    neutral_events: list[str] = Field(
        description="List of 1-2 bullet points describing neutral or informational factors"
    )


# Add future schemas below as needed
# Example:
# class RiskAssessmentOutput(BaseModel):
#     risk_level: str = Field(description="LOW, MEDIUM, or HIGH")
#     rationale: str = Field(description="Brief explanation of risk assessment")


class ArticleAnalysisOutput(BaseModel):
    theme: str = Field(description="The strict category label for the event")
