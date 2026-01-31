import os
from typing import Dict, Any, Optional
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


def get_llm_model():
    """
    Factory to return the configured LLM model instance.
    """
    config = get_config()
    llm_config = config.get_llm_config()
    provider = llm_config.get("provider", "gemini")

    if provider == "azure":
        # Use user's custom class logic
        azure_conf = llm_config.get("azure", {})

        # Map config to arguments expected by their class (assumption)
        # They showed: client_id, tenant_id, cert_path, scope, refresh_buffer
        return AzureOpenAIModel(
            client_id=azure_conf.get("client_id"),
            tenant_id=azure_conf.get("tenant_id"),
            cert_path=azure_conf.get("cert_path"),
            scope=azure_conf.get("scope"),
            deployment=azure_conf.get("deployment"),
            endpoint=azure_conf.get("endpoint"),
            api_version=azure_conf.get("api_version"),
            api_key=azure_conf.get("api_key"),
        )

    elif provider == "gemini":
        gemini_conf = llm_config.get("gemini", {})
        model_name = gemini_conf.get("model", "gemini-1.5-pro")
        api_key = gemini_conf.get("api_key")

        # Resolve env var if needed
        if api_key and api_key.startswith("${") and api_key.endswith("}"):
            var_name = api_key[2:-1]
            api_key = os.environ.get(var_name)

        if not api_key:
            raise ValueError(
                "Gemini API Key not found in configuration or environment."
            )

        # Use init_chat_model as requested
        return init_chat_model(
            model_name, model_provider="google_genai", google_api_key=api_key
        )

    else:
        raise ValueError(f"Unknown LLM provider: {provider}")


def generate_cluster_summary(articles: list) -> Dict[str, str]:
    """
    Generate a formatted summary and theme from a list of articles.

    Uses LangChain's structured output to guarantee response format.

    Args:
        articles: List of dicts with 'title' and 'summary' keys.

    Returns:
        Dict with keys: 'narrative_theme', 'narrative_summary'
    """
    if not articles:
        return {
            "narrative_theme": "No News",
            "narrative_summary": "No articles available to summarize.",
        }

    llm = get_llm_model()

    # Use structured output for guaranteed format
    structured_llm = llm.with_structured_output(ClusterSummaryOutput)

    # Prepare article text
    article_text = "\n\n".join(
        [
            f"Title: {a.get('title', 'No Title')}\nSummary: {a.get('summary', 'No Summary')}"
            for a in articles[:15]  # Limit to 15 to fit context/cost
        ]
    )

    messages = [
        SystemMessage(content=CLUSTER_SUMMARY_SYSTEM_PROMPT),
        HumanMessage(content=f"Here are the articles:\n\n{article_text}"),
    ]

    try:
        # Invoke with structured output - returns ClusterSummaryOutput instance
        result = structured_llm.invoke(messages)
        return {
            "narrative_theme": result.narrative_theme,
            "narrative_summary": result.narrative_summary,
        }
    except Exception as e:
        print(f"LLM Structured Output Error: {e}")
        return {
            "narrative_theme": "Error",
            "narrative_summary": f"Failed to generate summary: {str(e)}",
        }
