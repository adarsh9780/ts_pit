"""
Script to test individual agent tools to identify timeouts or errors.
Run with: uv run scripts/test_tools.py
"""

import os
import sys
import time
import asyncio
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from backend.config import get_config
from backend.agent.tools import (
    execute_sql,
    get_schema,
    consult_expert,
    get_alert_details,
    get_alerts_by_ticker,
    count_material_news,
    get_price_history,
    search_news,
    update_alert_status,
    search_web_news,
    scrape_websites,
)
from backend.llm import get_llm_model

# --- Setup Proxy (Mimic main.py) ---
print("--- Environment Setup ---")
config = get_config()
proxy_config = config.get_proxy_config()

if proxy_config.get("http"):
    os.environ["HTTP_PROXY"] = proxy_config["http"]
    print(f"Set HTTP_PROXY={proxy_config['http']}")
if proxy_config.get("https"):
    os.environ["HTTPS_PROXY"] = proxy_config["https"]
    print(f"Set HTTPS_PROXY={proxy_config['https']}")
if proxy_config.get("no_proxy"):
    os.environ["NO_PROXY"] = proxy_config["no_proxy"]
    print(f"Set NO_PROXY={proxy_config['no_proxy']}")

print("\n--- Initializing LLM ---")
t0 = time.time()
try:
    llm = get_llm_model()
    print(f"LLM Initialized in {time.time() - t0:.2f}s")
except Exception as e:
    print(f"FAILED to initialize LLM: {e}")

# --- Test Functions ---


def run_test(name, tool, input_args):
    """
    Args:
        name: Name of test
        tool: The LangChain tool object
        input_args: Dictionary of arguments to pass to .invoke()
    """
    print(f"\n>>> Testing: {name}")
    t0 = time.time()
    try:
        # LangChain tools: Check if it's an async tool
        is_async = hasattr(tool, "coroutine") and tool.coroutine is not None

        if is_async:
            # Must use ainvoke for async tools
            result = asyncio.run(tool.ainvoke(input_args))
        else:
            # Sync tool
            result = tool.invoke(input_args)

        duration = time.time() - t0
        print(f"✅ PASSED in {duration:.2f}s")
        res_str = str(result)
        print(
            f"Output: {res_str[:200]}..."
            if len(res_str) > 200
            else f"Output: {res_str}"
        )
        return True

    except Exception as e:
        duration = time.time() - t0
        print(f"❌ FAILED in {duration:.2f}s")
        print(f"Error: {e}")
        return False


# --- Main Test Loop ---


def main():
    print("\n=== STARTING TOOL TESTS ===")

    # 1. Database Tools
    run_test("get_schema", get_schema, {"table_name": "alerts"})
    run_test("get_alert_details", get_alert_details, {"alert_id": "1001"})
    run_test("execute_sql", execute_sql, {"query": "SELECT * FROM alerts LIMIT 2"})

    # 2. SQL + Logic
    run_test("get_alerts_by_ticker", get_alerts_by_ticker, {"ticker": "ORX.ST"})
    run_test("search_news (Internal)", search_news, {"ticker": "ORX.ST"})
    run_test("count_material_news", count_material_news, {"ticker": "ORX.ST"})

    # 3. External Network Tools
    print("\n--- Testing External Tools (May take time) ---")

    # yfinance
    print("Testing get_price_history (yfinance)...")
    run_test(
        "get_price_history", get_price_history, {"ticker": "ORX.ST", "period": "1mo"}
    )

    # DuckDuckGo
    print("Testing search_web_news (DuckDuckGo)...")
    run_test(
        "search_web_news",
        search_web_news,
        {"query": "Orexo AB stock news", "max_results": 3},
    )

    # Scraper
    print("Testing scrape_websites (aiohttp)...")
    run_test("scrape_websites", scrape_websites, {"urls": ["https://example.com"]})

    # 4. LLM Tool
    print("\n--- Testing LLM Tool ---")
    run_test("consult_expert", consult_expert, {"question": "What is layering?"})

    print("\n=== TESTS COMPLETED ===")


if __name__ == "__main__":
    main()
