"""
Tools for the Trade Surveillance Agent
======================================
Defines the tools available to the LangGraph agent for interacting with
the database and retrieving alert context.
"""

import json
import sqlite3
import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional
from langchain_core.tools import tool
from backend.database import get_db_connection, remap_row
from backend.config import get_config
from backend.alert_analysis import (
    analyze_alert_non_persisting,
    get_current_alert_news_non_persisting,
)
from backend.reporting import generate_alert_report_html, sanitize_session_id

# Load the database schema for the SQL tool docstring
SCHEMA_PATH = Path(__file__).parent / "db_schema.yaml"
DB_SCHEMA = ""
if SCHEMA_PATH.exists():
    with open(SCHEMA_PATH, "r") as f:
        # Load YAML and dump it back as a string to ensure consistent formatting
        # or just read text. Let's read text to keep comments if possible,
        # but YAML structure is better for LLM.
        schema_data = yaml.safe_load(f)
        DB_SCHEMA = yaml.dump(schema_data, sort_keys=False)


def _normalize_impact_label(label: str) -> str:
    """Normalize legacy impact labels for consistent tool output."""
    return get_config().normalize_impact_label(label)


def _ok(data: Any = None, message: str = "ok", **meta) -> str:
    return json.dumps(
        {"ok": True, "message": message, "data": data, "meta": meta}, default=str
    )


def _error(message: str, code: str = "TOOL_ERROR", **meta) -> str:
    return json.dumps(
        {"ok": False, "error": {"code": code, "message": message}, "meta": meta},
        default=str,
    )


@tool
def execute_sql(query: str) -> str:
    """
    Execute a read-only SQL query against the alerts database.

    Use this tool to answer questions that require aggregation, filtering, or
    finding specific records that cannot be retrieved via other tools.

    The database schema is as follows:

    {db_schema}

    IMPORTANT:
    - Only SELECT statements are allowed.
    - Do not use PRAGMA or other administrative commands.
    - The database is SQLite.
    """
    # Enforce read-only policy
    if not query.strip().upper().startswith("SELECT"):
        return _error(
            "Only SELECT statements are allowed for security reasons.",
            code="READ_ONLY_ENFORCED",
        )

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()

        # Get column names
        column_names = [description[0] for description in cursor.description]

        # Convert to list of dicts
        results = [dict(zip(column_names, row)) for row in rows]
        conn.close()

        return _ok(results, row_count=len(results))
    except Exception as e:
        return _error(f"Database error: {str(e)}", code="DB_ERROR")


# Inject schema into docstring
execute_sql.__doc__ = execute_sql.__doc__.format(db_schema=DB_SCHEMA)


@tool
def get_schema(table_name: Optional[str] = None) -> str:
    """
    Get the database schema with column details and descriptions.

    Use this tool when you need to:
    - Know exact column names for SQL queries
    - Understand what data is available in tables
    - See example values and data types

    Args:
        table_name: Optional. If provided, returns schema for just that table.
                   Options: 'alerts', 'articles', 'prices', 'article_themes', 'prices_hourly'
                   If not provided, returns full schema.

    Returns:
        YAML-formatted schema with table descriptions, column names, types, and examples.
    """
    if not DB_SCHEMA:
        return _error("Schema file not found.", code="SCHEMA_NOT_FOUND")

    if table_name:
        # Load and filter to specific table
        schema_data = yaml.safe_load(DB_SCHEMA)
        if "tables" in schema_data and table_name in schema_data["tables"]:
            filtered = yaml.dump({table_name: schema_data["tables"][table_name]}, sort_keys=False)
            return _ok({"schema_yaml": filtered, "table_name": table_name})
        else:
            return _error(
                f"Table '{table_name}' not found. Available: alerts, articles, prices, article_themes, prices_hourly",
                code="TABLE_NOT_FOUND",
            )

    return _ok({"schema_yaml": DB_SCHEMA})


@tool
def consult_expert(question: str) -> str:
    """
    Consult a Trade Surveillance Domain Expert for definitions and concepts.

    Use this tool when the user asks about:
    - Alert types (e.g. "What is layering?", "Define insider trading")
    - System concepts (e.g. "How does SMARTS work?", "What is a lookback window?")
    - Market abuse terminology

    DO NOT use this for specific alert data (like "What is the price of MSFT?").
    Only use it for general domain knowledge and definitions.

    Args:
        question: The specific concept or question to ask the expert.
    """
    try:
        from backend.llm import get_llm_model

        # Load knowledge base
        kb_path = Path(__file__).parent / "domain_knowledge.md"
        if not kb_path.exists():
            return _error("Knowledge base file not found.", code="KB_NOT_FOUND")

        with open(kb_path, "r") as f:
            knowledge_base = f.read()

        # Create a focused query for the refined context
        llm = get_llm_model()

        system_prompt = (
            "You are a Trade Surveillance Expert. "
            "Answer the user's question using ONLY the provided Knowledge Base below. "
            "If the answer is not in the knowledge base, say 'I don't have that definition in my knowledge base'. "
            "Keep answers concise and relevant."
            "\n\n--- KNOWLEDGE BASE ---\n"
            f"{knowledge_base}"
        )

        messages = [("system", system_prompt), ("human", question)]

        response = llm.invoke(messages)
        return _ok({"answer": response.content})

    except Exception as e:
        return _error(f"Error consulting expert: {str(e)}", code="EXPERT_ERROR")


@tool
def get_alert_details(alert_id: str) -> str:
    """
    Get detailed information for a specific alert by its ID (e.g., 'ALT-1000').
    Returns the full alert record including status, dates, and trade details.

    IMPORTANT: Do NOT use this tool for the alert currently in your 'current focus' / system prompt.
    The details for the active alert are ALREADY provided to you.
    Only use this tool to look up *other* alerts referenced in the conversation.
    """
    config = get_config()
    conn = get_db_connection()
    cursor = conn.cursor()

    table_name = config.get_table_name("alerts")
    alert_id_col = config.get_column("alerts", "id")

    try:
        cursor.execute(
            f'SELECT * FROM "{table_name}" WHERE "{alert_id_col}" = ?', (alert_id,)
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return _error(f"Alert {alert_id} not found.", code="ALERT_NOT_FOUND")

        # Use the same remapping logic as the API for consistency
        result = remap_row(dict(row), "alerts")
        return _ok(result)
    except Exception as e:
        return _error(f"Error fetching alert details: {str(e)}", code="DB_ERROR")


@tool
def get_alerts_by_ticker(ticker: str) -> str:
    """
    Find all alerts associated with a specific stock sticker symbol (e.g., 'NVDA', 'AAPL').
    Useful for checking history of alerts for a company.
    """
    config = get_config()
    conn = get_db_connection()
    cursor = conn.cursor()

    table_name = config.get_table_name("alerts")
    ticker_col = config.get_column("alerts", "ticker")

    try:
        cursor.execute(
            f'SELECT * FROM "{table_name}" WHERE "{ticker_col}" = ?', (ticker,)
        )
        rows = cursor.fetchall()
        conn.close()

        results = [remap_row(dict(row), "alerts") for row in rows]

        if not results:
            return _ok([], message=f"No alerts found for ticker {ticker}.", ticker=ticker)

        return _ok(results, ticker=ticker, row_count=len(results))
    except Exception as e:
        return _error(
            f"Error fetching alerts for ticker: {str(e)}",
            code="DB_ERROR",
            ticker=ticker,
        )


@tool
def count_material_news(ticker: str) -> str:
    """
    Count the number of news articles for a ticker that are flagged as material impact.
    Returns a breakdown of impact labels (High, Medium, Low).
    """
    config = get_config()
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Resolve Ticker -> ISIN using alerts table (reference mapping)
    alerts_table = config.get_table_name("alerts")
    alert_ticker_col = config.get_column("alerts", "ticker")
    alert_isin_col = config.get_column("alerts", "isin")

    try:
        cursor.execute(
            f'SELECT DISTINCT "{alert_isin_col}" FROM "{alerts_table}" WHERE "{alert_ticker_col}" = ?',
            (ticker,),
        )
        row = cursor.fetchone()

        if not row:
            conn.close()
            # If we truly can't find it in alerts, we can't search articles by ISIN.
            # But maybe the user meant a ticker that isn't in alerts?
            # For now, we assume if it's not in alerts, we can't link it.
            return _error(
                f"Ticker {ticker} not found in alerts database, cannot link to news.",
                code="TICKER_NOT_FOUND",
                ticker=ticker,
            )

        isin = row[0]

        # 2. Query Articles by ISIN
        articles_table = config.get_table_name("articles")
        article_isin_col = config.get_column("articles", "isin")
        impact_col = config.get_column("articles", "impact_label")

        if not article_isin_col or not impact_col:
            conn.close()
            return _error(
                "Tool configuration error: missing ISIN or impact_label mapping for articles.",
                code="CONFIG_ERROR",
            )

        cursor.execute(
            f'''
            SELECT "{impact_col}", COUNT(*) as count 
            FROM "{articles_table}" 
            WHERE "{article_isin_col}" = ? 
            GROUP BY "{impact_col}"
            ''',
            (isin,),
        )
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return _ok(
                {"impact_breakdown": {}, "isin": isin},
                message=f"No news found for {ticker}.",
                ticker=ticker,
            )

        results = {}
        for raw_label, count in rows:
            normalized_label = _normalize_impact_label(raw_label)
            results[normalized_label] = results.get(normalized_label, 0) + count
        return _ok({"impact_breakdown": results, "isin": isin}, ticker=ticker)

    except Exception as e:
        conn.close()
        return _error(
            f"Error counting material news: {str(e)}",
            code="DB_ERROR",
            ticker=ticker,
        )


@tool
def get_price_history(ticker: str, period: str = "1mo") -> str:
    """
    Fetch price history for a ticker.
    Args:
        ticker: Stock symbol (e.g., NVDA)
        period: Time period (1mo, 3mo, 6mo, 1y, ytd, max)
    Returns:
        JSON string of price records (Date, Close, volume).
    """
    from backend.prices import fetch_and_cache_prices

    try:
        # Trigger fetch/cache logic
        fetch_and_cache_prices(ticker, period)

        # Query results from DB
        config = get_config()
        conn = get_db_connection()
        cursor = conn.cursor()

        table_name = config.get_table_name("prices")
        ticker_col = config.get_column("prices", "ticker")
        date_col = config.get_column("prices", "date")
        close_col = config.get_column("prices", "close")

        # Get start date based on period (approximate)
        cursor.execute(
            f'SELECT "{date_col}", "{close_col}" FROM "{table_name}" WHERE "{ticker_col}" = ? ORDER BY "{date_col}" DESC LIMIT 30',
            (ticker,),
        )
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return _ok([], message=f"No price data found for {ticker}.", ticker=ticker)

        # Return simplified data to save tokens
        results = [dict(row) for row in rows]
        # Reverse to show chronological order
        results.reverse()
        return _ok(results, ticker=ticker, period=period, row_count=len(results))

    except Exception as e:
        return _error(f"Error fetching prices: {str(e)}", code="PRICE_ERROR", ticker=ticker)


@tool
def search_news(
    ticker: str, limit: int = 5, start_date: str = None, end_date: str = None
) -> str:
    """
    Search for recent news articles for a ticker.
    Args:
        ticker: Stock symbol
        limit: Max number of articles to return (default 5)
        start_date: Optional start date (YYYY-MM-DD) to filter articles
        end_date: Optional end date (YYYY-MM-DD) to filter articles
    """
    config = get_config()
    conn = get_db_connection()
    cursor = conn.cursor()

    # Resolve Ticker -> ISIN
    alerts_table = config.get_table_name("alerts")
    alert_ticker_col = config.get_column("alerts", "ticker")
    alert_isin_col = config.get_column("alerts", "isin")

    try:
        cursor.execute(
            f'SELECT DISTINCT "{alert_isin_col}" FROM "{alerts_table}" WHERE "{alert_ticker_col}" = ?',
            (ticker,),
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            return _error(
                f"Ticker {ticker} not found in alerts, cannot link to news.",
                code="TICKER_NOT_FOUND",
                ticker=ticker,
            )
        isin = row[0]

        # Query Articles
        articles_table = config.get_table_name("articles")
        article_isin_col = config.get_column("articles", "isin")
        title_col = config.get_column("articles", "title")
        summary_col = config.get_column("articles", "summary")
        date_col = config.get_column("articles", "created_date")

        query = f'SELECT "{date_col}", "{title_col}", "{summary_col}" FROM "{articles_table}" WHERE "{article_isin_col}" = ?'
        params = [isin]

        # Add date filtering if provided
        if start_date:
            query += f' AND "{date_col}" >= ?'
            params.append(start_date)

        if end_date:
            query += f' AND "{date_col}" <= ?'
            params.append(end_date)

        query += f' ORDER BY "{date_col}" DESC LIMIT ?'
        params.append(limit)

        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return _ok([], message=f"No news found for {ticker}.", ticker=ticker)

        results = [dict(row) for row in rows]
        return _ok(results, ticker=ticker, row_count=len(results))

    except Exception as e:
        conn.close()
        return _error(f"Error searching news: {str(e)}", code="DB_ERROR", ticker=ticker)


@tool
def update_alert_status(alert_id: str, status: str, reason: str = None) -> str:
    """
    Update the status of an alert.
    Args:
        alert_id: The ID of the alert (e.g., ALT-1000)
        status: New status (configured in config.yaml)
        reason: Optional reason for the status change
    """
    config = get_config()
    normalized_status = config.normalize_status(status)
    valid_statuses = config.get_valid_statuses()
    if config.is_status_enforced() and normalized_status not in valid_statuses:
        return _error(
            f"Invalid status '{status}'. Must be one of: {valid_statuses}",
            code="INVALID_STATUS",
        )

    conn = get_db_connection()
    cursor = conn.cursor()

    table_name = config.get_table_name("alerts")
    alert_id_col = config.get_column("alerts", "id")
    status_col = config.get_column("alerts", "status")

    try:
        cursor.execute(
            f'UPDATE "{table_name}" SET "{status_col}" = ? WHERE "{alert_id_col}" = ?',
            (normalized_status, alert_id),
        )
        conn.commit()

        if cursor.rowcount == 0:
            conn.close()
            return _error(f"Alert {alert_id} not found.", code="ALERT_NOT_FOUND")

        conn.close()
        return _ok(
            {"alert_id": alert_id, "status": normalized_status},
            message="Alert status updated.",
        )

    except Exception as e:
        conn.close()
        return _error(f"Error updating alert status: {str(e)}", code="DB_ERROR")


@tool
def get_current_alert_news(alert_id: str, limit: int = 50) -> str:
    """
    Get in-window news for a specific alert using the exact alert window.
    This avoids ticker-level leakage outside the current investigation period.
    """
    conn = get_db_connection()
    try:
        result = get_current_alert_news_non_persisting(
            conn=conn, config=get_config(), alert_id=alert_id, limit=limit
        )
        if not result.get("ok"):
            return _error(result.get("error", "Failed to fetch alert news"), code="ALERT_NEWS_ERROR")
        return _ok(
            result["articles"],
            alert_id=alert_id,
            articles_total=result["articles_total"],
            start_date=result["start_date"],
            end_date=result["end_date"],
        )
    except Exception as e:
        return _error(f"Error fetching current alert news: {str(e)}", code="ALERT_NEWS_ERROR")
    finally:
        conn.close()


@tool
def get_article_by_id(article_id: str) -> str:
    """
    Fetch a single internal article by article_id, including full body when available.

    Use this tool when the user asks to dissect a specific news item from the UI list.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    config = get_config()
    try:
        table_name = config.get_table_name("articles")
        id_col = config.get_column("articles", "id") or "id"

        cursor.execute(f'PRAGMA table_info("{table_name}")')
        available_cols = [row["name"] for row in cursor.fetchall()]
        available_set = set(available_cols)

        id_candidates = [id_col, "id", "article_id", "art_id"]
        id_candidates = [c for c in dict.fromkeys(id_candidates) if c in available_set]
        if not id_candidates:
            return _error("No article id column found in configured articles table.", code="CONFIG_ERROR")

        probe_values: list[Any] = [article_id]
        if isinstance(article_id, str) and article_id.isdigit():
            probe_values.append(int(article_id))
        elif not isinstance(article_id, str):
            probe_values.append(str(article_id))

        row = None
        matched_col = None
        matched_value = None
        for value in probe_values:
            for candidate_col in id_candidates:
                cursor.execute(
                    f'SELECT * FROM "{table_name}" WHERE "{candidate_col}" = ? LIMIT 1',
                    (value,),
                )
                found = cursor.fetchone()
                if found:
                    row = found
                    matched_col = candidate_col
                    matched_value = value
                    break
            if row:
                break

        if not row:
            return _error(f"Article {article_id} not found.", code="ARTICLE_NOT_FOUND")

        remapped = remap_row(dict(row), "articles")
        body_value = remapped.get("body")
        body_present = isinstance(body_value, str) and body_value.strip() != ""

        data = {
            "id": remapped.get("id") or remapped.get("article_id") or remapped.get("art_id"),
            "title": remapped.get("title"),
            "created_date": remapped.get("created_date"),
            "theme": remapped.get("theme"),
            "sentiment": remapped.get("sentiment"),
            "summary": remapped.get("summary"),
            "url": remapped.get("url") or remapped.get("article_url") or remapped.get("link"),
            "isin": remapped.get("isin"),
            "impact_score": remapped.get("impact_score"),
            "impact_label": remapped.get("impact_label"),
            "body": remapped.get("body"),
            "body_available": body_present,
        }

        return _ok(
            data,
            article_id=article_id,
            matched_id_col=matched_col,
            matched_id_value=matched_value,
        )
    except Exception as e:
        return _error(f"Error fetching article by id: {str(e)}", code="ARTICLE_FETCH_ERROR")
    finally:
        conn.close()


@tool
def analyze_current_alert(alert_id: str) -> str:
    """
    Run deterministic-first analysis for the current alert without persisting anything to DB.
    Uses the same analysis pipeline as /alerts/{id}/summary but read-only.
    """
    conn = get_db_connection()
    try:
        from backend.llm import get_llm_model

        llm = get_llm_model()
        analysis = analyze_alert_non_persisting(
            conn=conn, config=get_config(), alert_id=alert_id, llm=llm
        )
        if not analysis.get("ok"):
            return _error(analysis.get("error", "Analysis failed"), code="ANALYSIS_ERROR")

        return _ok(
            {
                "analysis": analysis["result"],
                "citations": analysis["citations"],
                "articles_considered_count": analysis["articles_considered_count"],
                "source": analysis["source"],
            },
            alert_id=alert_id,
            start_date=analysis["start_date"],
            end_date=analysis["end_date"],
        )
    except Exception as e:
        return _error(f"Error analyzing current alert: {str(e)}", code="ANALYSIS_ERROR")
    finally:
        conn.close()


@tool
def generate_current_alert_report(
    alert_id: str, session_id: str, include_web_news: bool = True
) -> str:
    """
    Generate a downloadable investigation report for the current alert.
    The report includes deterministic + LLM analysis, internal alert-window news,
    materiality-high evidence, optional web news enrichment, and (when available)
    the chart snapshot captured from the UI.

    Args:
        alert_id: Current alert ID from [CURRENT ALERT CONTEXT]
        session_id: Current chat session_id from [CURRENT ALERT CONTEXT]
        include_web_news: Whether to enrich report with external web news

    Returns:
        JSON with report metadata and download_url.
    """
    conn = get_db_connection()
    try:
        from backend.llm import get_llm_model

        safe_session = sanitize_session_id(session_id)
        result = generate_alert_report_html(
            conn=conn,
            config=get_config(),
            llm=get_llm_model(),
            alert_id=alert_id,
            session_id=safe_session,
            include_web_news=include_web_news,
        )
        if not result.get("ok"):
            return _error(result.get("error", "Report generation failed"), code="REPORT_ERROR")
        return _ok(result, message="Report generated")
    except Exception as e:
        return _error(f"Error generating report: {str(e)}", code="REPORT_ERROR")
    finally:
        conn.close()


@tool
async def search_web_news(
    query: str, max_results: int = 5, start_date: str = None, end_date: str = None
) -> str:
    """
    Search the INTERNET for recent news articles using DuckDuckGo, fetch content, and summarize.
    Use this when you need EXTERNAL news from the web (not from the internal database).

    NOTE: For internal database news, use 'search_news' instead. Use this tool only when
    the user explicitly asks for web/internet news or when internal news is insufficient.

    Args:
        query: Search query (e.g., "NVIDIA stock news")
        max_results: Number of articles to fetch and summarize (default 5, max 10)
        start_date: Optional start date (YYYY-MM-DD) for relevance context
        end_date: Optional end date (YYYY-MM-DD) for relevance context

    Returns:
        News articles with title, source, date, URL, and AI-generated summary.
    """
    import asyncio
    import aiohttp
    from bs4 import BeautifulSoup
    from ddgs import DDGS
    from backend.llm import get_llm_model
    from datetime import datetime

    MAX_CONTENT_CHARS = 3000  # Max content to send to LLM per article
    TIMEOUT = 8

    # Enforce limits
    max_results = min(max_results, 10)

    # Enhance query with date context if provided
    search_query = query
    if start_date:
        try:
            # Add Month Year to query for better relevance (e.g. "Active news Jan 2024")
            dt = datetime.strptime(start_date, "%Y-%m-%d")
            month_year = dt.strftime("%B %Y")
            if month_year not in query:
                search_query = f"{query} {month_year}"
        except:
            pass

    def _search():
        """Sync DDGS search."""
        # Get proxy from config
        config = get_config()
        proxy_config = config.get_proxy_config()
        # Use HTTPS proxy if available, else HTTP
        proxy_url = proxy_config.get("https") or proxy_config.get("http")

        # Pass proxy to DDGS if set
        kwargs = {}
        if proxy_url:
            kwargs["proxy"] = proxy_url

        # Respect config.yaml proxy.ssl_verify (defaults to True).
        kwargs["verify"] = proxy_config.get("ssl_verify", True)

        with DDGS(**kwargs) as ddgs:
            # Fetch more than needed to allow for date filtering
            results = list(ddgs.news(search_query, max_results=max_results * 2))

            # Simple client-side date filtering if possible
            filtered_results = []
            for r in results:
                # DDGS returns relative dates (e.g. "1 hour ago") or absolute dates
                # Parsing is hard, so we just rely on query relevance mostly.
                # But we can try basic filtering if 'date' field is parsable.
                filtered_results.append(r)

            return filtered_results[:max_results]

    async def _fetch_content(session: aiohttp.ClientSession, url: str) -> str:
        """Fetch and extract article content (internal only, not returned)."""
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=TIMEOUT), headers=headers
            ) as response:
                if response.status != 200:
                    return ""
                html = await response.text()
                soup = BeautifulSoup(html, "html.parser")

                for elem in soup(
                    ["script", "style", "nav", "header", "footer", "aside", "form"]
                ):
                    elem.extract()

                text = soup.get_text()
                lines = (line.strip() for line in text.splitlines())
                clean_text = " ".join(line for line in lines if line)

                # Truncate for LLM context (internal use only)
                return (
                    clean_text[:MAX_CONTENT_CHARS]
                    if len(clean_text) > MAX_CONTENT_CHARS
                    else clean_text
                )
        except:
            return ""

    def _batch_summarize(articles: list[dict], contents: list[str]) -> list[str]:
        """Use LLM to summarize all articles in a single batch call."""
        llm = get_llm_model()

        # Build batch prompt
        prompt_parts = [
            "Summarize each of the following news articles in 2-3 sentences. Return ONLY the summaries, numbered 1, 2, 3, etc.\n"
        ]

        for i, (article, content) in enumerate(zip(articles, contents), 1):
            title = article.get("title", "Unknown")
            text = content if content else article.get("body", "No content available")
            prompt_parts.append(
                f"\n---\nArticle {i}: {title}\n{text[:1500]}\n"
            )  # Limit per article

        prompt = "".join(prompt_parts)

        try:
            response = llm.invoke(prompt)
            # Parse numbered summaries
            raw_summaries = response.content.strip()

            # Split by numbered pattern and clean up
            summaries = []
            current = ""
            for line in raw_summaries.split("\n"):
                line = line.strip()
                if line and line[0].isdigit() and "." in line[:3]:
                    if current:
                        summaries.append(current.strip())
                    current = line.split(".", 1)[1].strip() if "." in line else line
                elif current:
                    current += " " + line
            if current:
                summaries.append(current.strip())

            # Pad if we got fewer summaries than expected
            while len(summaries) < len(articles):
                summaries.append("Summary not available.")

            return summaries[: len(articles)]
        except Exception as e:
            return ["Summary generation failed." for _ in articles]

    try:
        # 1. Search for news
        results = await asyncio.to_thread(_search)

        if not results:
            return _ok([], message=f"No web news found for: {query}", query=query)

        # 2. Fetch article content concurrently (kept internal)
        # Enable trust_env=True to respect HTTP_PROXY/HTTPS_PROXY/NO_PROXY
        async with aiohttp.ClientSession(trust_env=True) as session:
            urls = [r.get("url", "") for r in results]
            tasks = [_fetch_content(session, url) for url in urls]
            contents = await asyncio.gather(*tasks)  # Internal only, not returned

        # 3. Batch summarize using LLM
        summaries = await asyncio.to_thread(_batch_summarize, results, contents)

        # contents variable is discarded here - never enters return value

        # 4. Format results as JSON
        final_results = []
        for r, summary in zip(results, summaries):
            final_results.append(
                {
                    "title": r.get("title", "No Title"),
                    "source": r.get("source", "Unknown"),
                    "date": r.get("date", "Unknown"),
                    "url": r.get("url", ""),
                    "summary": summary,
                }
            )

        return _ok(final_results, query=query, row_count=len(final_results))

    except Exception as e:
        return _error(
            f"Error searching web news: {str(e)}",
            code="WEB_NEWS_ERROR",
            query=query,
        )


@tool
async def scrape_websites(urls: list[str]) -> str:
    """
    Fetches and extracts text content from multiple URLs concurrently.
    Use this to read full article content from URLs returned by search_web_news.

    Args:
        urls: List of URLs to scrape (e.g., ["https://a.com/1", "https://b.com/2"])

    Returns:
        Combined text content from all URLs, each truncated to ~2000 characters.
    """
    import asyncio
    import aiohttp
    from bs4 import BeautifulSoup

    MAX_CHARS_PER_URL = 2000
    TIMEOUT = 10

    # Validate input
    if not urls:
        return _error("No URLs provided.", code="INVALID_INPUT")

    # Limit to 10 URLs max
    url_list = urls[:10]

    async def fetch_one(session: aiohttp.ClientSession, url: str) -> tuple[str, str]:
        """Fetch and parse a single URL."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            }
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=TIMEOUT), headers=headers
            ) as response:
                if response.status != 200:
                    return url, f"[Error: HTTP {response.status}]"

                html = await response.text()
                soup = BeautifulSoup(html, "html.parser")

                # Remove non-content elements
                for element in soup(
                    ["script", "style", "nav", "header", "footer", "aside"]
                ):
                    element.extract()

                # Clean text
                text = soup.get_text()
                lines = (line.strip() for line in text.splitlines())
                chunks = (
                    phrase.strip() for line in lines for phrase in line.split("  ")
                )
                clean_text = "\n".join(chunk for chunk in chunks if chunk)

                # Truncate
                if len(clean_text) > MAX_CHARS_PER_URL:
                    clean_text = clean_text[:MAX_CHARS_PER_URL] + "... (truncated)"

                return url, clean_text

        except asyncio.TimeoutError:
            return url, "[Error: Request timed out]"
        except Exception as e:
            return url, f"[Error: {str(e)}]"

    # Run all fetches concurrently
    # Enable trust_env=True to respect HTTP_PROXY/HTTPS_PROXY
    # Configure SSL verification based on config (set ssl_verify: false in config.yaml for VDI)
    config = get_config()
    ssl_verify = config.get_proxy_config().get("ssl_verify", True)

    connector = aiohttp.TCPConnector(ssl=ssl_verify)
    async with aiohttp.ClientSession(trust_env=True, connector=connector) as session:
        tasks = [fetch_one(session, url) for url in url_list]
        results = await asyncio.gather(*tasks)

    # Format output
    formatted = []
    for i, (url, content) in enumerate(results, 1):
        formatted.append({"index": i, "url": url, "content": content})

    return _ok(formatted, url_count=len(results))
