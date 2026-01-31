"""
Prompt Templates for LLM Operations
====================================
This module stores all prompt templates used across the application.
Edit these prompts to customize LLM behavior without touching code logic.

Industry Best Practice:
- Centralize prompts in one location for easy iteration
- Use clear variable names indicating purpose
- Document the expected input/output format
"""

# ==============================================================================
# CLUSTER SUMMARIZATION PROMPT
# ==============================================================================
# Perspective: Trade Surveillance Investigator looking for MNPI justification
#
# Input: List of news articles with title and summary
# Output: Structured JSON via ClusterSummaryOutput schema
# ==============================================================================

CLUSTER_SUMMARY_SYSTEM_PROMPT = """You are a Trade Surveillance Analyst reviewing this alert for potential Material Non-Public Information (MNPI).

Your task is to analyze the provided news articles and help the investigator determine whether the trade can be justified by publicly available information. Focus on:

1. **Key Market Events**: Identify significant public announcements (earnings, M&A, regulatory filings, guidance changes) that could explain trading activity.
2. **Timeline Correlation**: Note when major news broke relative to the alert period.
3. **Materiality Assessment**: Evaluate whether the news was material enough to drive the observed price movement.

Provide a concise theme and summary that helps justify or explain the trading activity based on public information."""


# ==============================================================================
# ADD FUTURE PROMPTS BELOW
# ==============================================================================
# Example:
# RISK_ASSESSMENT_PROMPT = """..."""
# SENTIMENT_ANALYSIS_PROMPT = """..."""
