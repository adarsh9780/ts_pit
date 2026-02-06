import os
from typing import Dict
from langchain_core.messages import SystemMessage, HumanMessage
from dotenv import load_dotenv
from .config import get_config
from .prompts import CLUSTER_SUMMARY_SYSTEM_PROMPT
from .schemas import ClusterSummaryOutput

# Load environment variables from .env file
load_dotenv()

# Import user's Azure logic (Placeholder for now)
# User provided: "I have a file called, llm.py which has a class called, AzureOpenAIModel"
# We expect the user to integrate or provide this class.
# For now, we define a dummy or imported class.
try:
    from .azure_llm import AzureOpenAIModel
except ImportError:

    class AzureOpenAIModel:
        def __init__(self, **kwargs):
            print("AzureOpenAIModel initialized with:", kwargs)

        def invoke(self, messages):
            raise NotImplementedError(
                "AzureOpenAIModel logic not provided by user yet."
            )


# Import LangChain's init_chat_model for Gemini
try:
    from langchain.chat_models import init_chat_model
except ImportError:
    # Fallback/Mock for environment without latest langchain
    def init_chat_model(model, model_provider, **kwargs):
        raise ImportError(
            "langchain.chat_models.init_chat_model not found. Please upgrade langchain."
        )


def _resolve_env_var(value: str) -> str:
    """Resolve ${VAR_NAME} syntax to actual environment variable value."""
    if (
        value
        and isinstance(value, str)
        and value.startswith("${")
        and value.endswith("}")
    ):
        var_name = value[2:-1]
        return os.environ.get(var_name, "")
    return value or ""


# Global cache for the LLM instance
_cached_llm = None


def get_llm_model():
    """
    Singleton Factory to return the configured LLM model instance.
    Initializes once and returns cached instance thereafter.
    """
    global _cached_llm
    if _cached_llm:
        return _cached_llm

    config = get_config()
    llm_config = config.get_llm_config()
    provider = llm_config.get("provider", "gemini")

    model_instance = None

    if provider == "azure":
        # Use user's custom class logic
        azure_conf = llm_config.get("azure", {})

        # Resolve all environment variables from config
        model_instance = AzureOpenAIModel(
            client_id=_resolve_env_var(azure_conf.get("client_id")),
            tenant_id=_resolve_env_var(azure_conf.get("tenant_id")),
            cert_path=azure_conf.get("cert_path"),  # Not sensitive, no env var
            scope=azure_conf.get("scope"),  # Not sensitive
            deployment=azure_conf.get("deployment"),
            endpoint=azure_conf.get("endpoint"),
            api_version=azure_conf.get("api_version"),
            api_key=_resolve_env_var(azure_conf.get("api_key")),
        )

    elif provider == "gemini":
        gemini_conf = llm_config.get("gemini", {})
        model_name = gemini_conf.get("model", "gemini-1.5-pro")
        api_key = _resolve_env_var(gemini_conf.get("api_key"))

        if not api_key:
            raise ValueError(
                "Gemini API Key not found in configuration or environment."
            )

        # Use init_chat_model as requested
        model_instance = init_chat_model(
            model_name, model_provider="google_genai", google_api_key=api_key
        )

    else:
        raise ValueError(f"Unknown LLM provider: {provider}")

    # Cache and return
    _cached_llm = model_instance
    return _cached_llm


def generate_cluster_summary(
    articles: list,
    price_history: list | None = None,
    trade_type: str | None = None,
    llm=None,
) -> Dict[str, str | list[str]]:
    """
    Generate a formatted summary and theme from a list of articles.

    Uses LangChain's structured output to guarantee response format.

    Args:
        articles: List of dicts with 'title' and 'summary' keys.
        price_history: Optional list of daily price records.
        llm: Optional pre-initialized LLM instance.

    Returns:
        Dict with keys: 'narrative_theme', 'narrative_summary'
    """
    if not articles:
        return {
            "narrative_theme": "No News",
            "narrative_summary": "No articles available to summarize.",
        }

    if llm is None:
        llm = get_llm_model()

    # Use structured output for guaranteed format
    structured_llm = llm.with_structured_output(ClusterSummaryOutput)

    # Prepare article text
    # Filter articles based on User Request: "At least one H in materiality OR Significant Impact"
    filtered_articles = []
    for a in articles:
        mat = a.get("materiality", "")
        impact = a.get("impact_score") or 0.0

        # Logic: High Materiality Component OR High Z-Score (> 2.0)
        if "H" in mat or abs(impact) >= 2.0:
            filtered_articles.append(a)

    # Fallback: If filter is too aggressive (empty/low), use top 15 by default sort
    if len(filtered_articles) < 3:
        filtered_articles = articles[:15]
    else:
        # Cap to avoid context overflow (though 1.5 Pro is huge, cleaner is better)
        filtered_articles = filtered_articles[:30]

    article_lines = []
    for a in filtered_articles:
        title = a.get("title", "No Title")
        summary = a.get("summary", "No Summary")
        theme = a.get("theme")
        analysis = a.get("analysis")
        impact = a.get("impact_score")
        materiality = a.get("materiality")  # informative to add to context

        entry = f"Title: {title}\nSummary: {summary}"
        if theme:
            entry += f"\nCONFIRMED THEME: {theme}"
        if analysis:
            entry += f"\nAI ANALYSIS: {analysis}"
        if impact:
            entry += f"\nIMPACT SCORE (Z-Score): {impact}"
        if materiality:
            entry += f"\nMATERIALITY SCORE: {materiality}"

        article_lines.append(entry)

    article_text = "\n\n".join(article_lines)

    # Prepare Price History Context
    price_context = ""
    if price_history:
        price_lines = ["\n\n**Daily Price History (Correlate with News):**"]
        for p in price_history:
            # Format: Date: Close
            date = p.get("date", "N/A")
            close = p.get("close", 0)
            price_lines.append(f"{date}: {close}")
        price_context = "\n".join(price_lines)

    # Add Alert Type context if available
    alert_context = ""
    if trade_type:
        alert_context = f"\n\n**Alert Type: {trade_type.upper()}**\n(Verify if news sentiment aligns with this trade direction)"

    messages = [
        SystemMessage(content=CLUSTER_SUMMARY_SYSTEM_PROMPT),
        HumanMessage(
            content=f"Here are the articles:\n\n{article_text}{price_context}{alert_context}"
        ),
    ]

    try:
        # Invoke with structured output - returns ClusterSummaryOutput instance
        result = structured_llm.invoke(messages)
        return {
            "narrative_theme": result.narrative_theme,
            "narrative_summary": result.narrative_summary,
            "bullish_events": result.bullish_events or [],
            "bearish_events": result.bearish_events or [],
            "neutral_events": result.neutral_events or [],
            "recommendation": result.recommendation
            or "Approve the alert",  # Default to safety
            "recommendation_reason": result.recommendation_reason
            or "No recommendation generated.",
        }
    except Exception as e:
        print(f"LLM Structured Output Error: {e}")
        return {
            "narrative_theme": "Error",
            "narrative_summary": f"Failed to generate summary: {str(e)}",
            "bullish_events": [],
            "bearish_events": [],
            "neutral_events": [],
            "recommendation": "Approve the alert",
            "recommendation_reason": "Error during analysis.",
        }


def generate_article_analysis(
    article_title: str,
    article_summary: str,
    z_score: float,
    price_change: float,
    llm=None,
) -> Dict[str, str | None]:
    """
    Analyze an article with price context to generate theme and reasoning.
    """
    from .prompts import ANALYSIS_SYSTEM_PROMPT
    from .schemas import ArticleAnalysisOutput

    if llm is None:
        llm = get_llm_model()
    structured_llm = llm.with_structured_output(ArticleAnalysisOutput)

    content = f"""
    Title: {article_title}
    Summary: {article_summary}
    
    Price Change: {price_change}%
    Impact Score (Z-Score): {z_score:.2f}
    """

    messages = [
        SystemMessage(content=ANALYSIS_SYSTEM_PROMPT),
        HumanMessage(content=content),
    ]

    try:
        result = structured_llm.invoke(messages)

        # Validation: Filter out placeholder "string" values
        theme = (
            result.theme
            if result.theme and result.theme.lower() != "string"
            else "UNCATEGORIZED"
        )

        return {
            "theme": theme,
            "analysis": None,  # User explicitly removed individual AI reasoning
            "summary": None,
        }
    except Exception as e:
        print(f"LLM Analysis Error: {e}")
        return {"theme": "Error", "summary": None, "analysis": str(e)}
