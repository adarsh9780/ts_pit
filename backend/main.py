import os
import json
import yfinance as yf
import requests
import asyncio
import aiosqlite
import pandas as pd
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional, AsyncGenerator
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from .database import get_db_connection, remap_row
from .config import get_config
from .llm import get_llm_model, generate_cluster_summary, generate_article_analysis
from .prices import fetch_and_cache_prices, get_ticker_from_isin
from .agent.graph import workflow  # Import the workflow blueprint

# Load configuration
config = get_config()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize LLM & Agent
    print("Initializing LLM Model...")
    app.state.llm = get_llm_model()

    # Initialize Persistent Memory for Agent
    db_path = Path.home() / ".ts_pit" / "agent_memory.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Initializing Agent Memory at {db_path}...")
    # Open async connection for the application lifespan
    async with aiosqlite.connect(db_path) as conn:
        app.state.agent_params = {"conn": conn}
        checkpointer = AsyncSqliteSaver(conn)

        # Compile the graph ONCE with the checkpointer
        app.state.agent = workflow.compile(checkpointer=checkpointer)

        yield

    # Shutdown
    print("Shutting down...")


app = FastAPI(lifespan=lifespan)

# Load configuration
# Load configuration
config = get_config()


# Ensure DB schema is up to date (Migration)
def run_migrations():
    conn = get_db_connection()
    cursor = conn.cursor()
    table_name = config.get_table_name("alerts")

    # Check for new columns
    cursor.execute(f'PRAGMA table_info("{table_name}")')
    columns = [row["name"] for row in cursor.fetchall()]

    new_cols = {
        "narrative_theme": "TEXT",
        "narrative_summary": "TEXT",
        "summary_generated_at": "TEXT",
        "bullish_events": "TEXT",
        "bearish_events": "TEXT",
        "neutral_events": "TEXT",
        "recommendation": "TEXT",
        "recommendation_reason": "TEXT",
    }

    for col, dtype in new_cols.items():
        if col not in columns:
            print(f"Migrating: Adding {col} to {table_name}")
            cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{col}" {dtype}')

    # Ensure 'article_themes' table exists
    themes_table = config.get_table_name("article_themes")
    art_id_col = config.get_column("article_themes", "art_id")
    theme_col = config.get_column("article_themes", "theme")
    summary_col = config.get_column("article_themes", "summary")
    analysis_col = config.get_column("article_themes", "analysis")

    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS "{themes_table}" (
            "{art_id_col}" TEXT PRIMARY KEY,
            "{theme_col}" TEXT,
            "{summary_col}" TEXT,
            "{analysis_col}" TEXT,
            FOREIGN KEY("{art_id_col}") REFERENCES "articles"(id)
        )
    ''')

    conn.commit()
    conn.close()


run_migrations()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve built frontend from /ui if it exists
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists() and (STATIC_DIR / "index.html").exists():
    # Mount static files for assets (js, css, etc.)
    app.mount("/ui/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/ui")
    @app.get("/ui/{path:path}")
    async def serve_frontend(path: str = ""):
        """Serve the frontend SPA. All routes fall back to index.html for client-side routing."""
        # Check if the path is a file that exists
        file_path = STATIC_DIR / path
        if path and file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        # Otherwise serve index.html for SPA routing
        return FileResponse(STATIC_DIR / "index.html")


@app.post("/articles/{id}/analyze")
def analyze_article(id: str, request: Request):
    """
    Generate AI analysis for a specific article using its price impact context.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get table info
    articles_table = config.get_table_name("articles")
    article_id_col = config.get_column("articles", "id")

    # Fetch article and its calculated impact score
    cursor.execute(
        f'SELECT * FROM "{articles_table}" WHERE "{article_id_col}" = ?', (id,)
    )
    row = cursor.fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Article not found")

    article = dict(row)

    # Extract context
    title = article.get("title", "")
    summary = article.get("summary", "")
    z_score = article.get("impact_score") or 0.0
    # Price change isn't directly in articles table usually, but we can imply intensity from z-score
    # Or we could fetch it from prices if we had the timestamp logic here.
    # For now, let's use z_score as the primary proxy for "Price Movement".
    # We can pass a dummy price_change or 0 if not available, relying on Z-score for magnitude.
    price_change = 0.0  # Placeholder, LLM will rely on Z-Score

    # 2. Generate Analysis using Singleton LLM
    llm = request.app.state.llm
    analysis_result = generate_article_analysis(
        title, summary, z_score, price_change, llm=llm
    )

    if analysis_result.get("theme") == "Error":
        conn.close()
        raise HTTPException(status_code=500, detail=analysis_result.get("analysis"))

    # 3. Save to article_themes
    themes_table = config.get_table_name("article_themes")
    art_id_col = config.get_column("article_themes", "art_id")
    theme_col = config.get_column("article_themes", "theme")
    summary_col = config.get_column("article_themes", "summary")
    analysis_col = config.get_column("article_themes", "analysis")

    try:
        cursor.execute(
            f'''
            INSERT OR REPLACE INTO "{themes_table}" 
            ("{art_id_col}", "{theme_col}", "{summary_col}", "{analysis_col}")
            VALUES (?, ?, ?, ?)
        ''',
            (
                id,
                analysis_result["theme"],
                analysis_result["summary"] or "",  # Handle None
                analysis_result["analysis"],
            ),
        )
        conn.commit()
    except Exception as e:
        print(f"Error saving analysis: {e}")
        # Return result even if save fails

    conn.close()

    return analysis_result


class StatusUpdate(BaseModel):
    status: str


@app.get("/config")
def get_config_endpoint():
    """Return configuration for the frontend."""
    return config.get_mappings_for_api()


# For backwards compatibility, also serve at /mappings
@app.get("/mappings")
def get_mappings():
    """Legacy endpoint - returns same as /config."""
    return config.get_mappings_for_api()


@app.get("/alerts")
def get_alerts(date: Optional[str] = None):
    """Get all alerts, optionally filtered by date."""
    conn = get_db_connection()
    cursor = conn.cursor()

    table_name = config.get_table_name("alerts")
    alert_date_col = config.get_column("alerts", "alert_date")

    if date:
        cursor.execute(
            f'SELECT * FROM "{table_name}" WHERE "{alert_date_col}" = ?', (date,)
        )
    else:
        cursor.execute(f'SELECT * FROM "{table_name}"')

    rows = cursor.fetchall()
    conn.close()
    return [remap_row(dict(row), "alerts") for row in rows]


@app.patch("/alerts/{alert_id}/status")
def update_alert_status(alert_id: str, update: StatusUpdate):
    """Update the status of an alert."""
    valid_statuses = config.get_valid_statuses()
    if update.status not in valid_statuses:
        raise HTTPException(
            status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}"
        )

    conn = get_db_connection()
    cursor = conn.cursor()

    table_name = config.get_table_name("alerts")
    alert_id_col = config.get_column("alerts", "id")
    status_col = config.get_column("alerts", "status")

    cursor.execute(
        f'UPDATE "{table_name}" SET "{status_col}" = ? WHERE "{alert_id_col}" = ?',
        (update.status, alert_id),
    )
    conn.commit()

    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Alert not found")

    conn.close()
    return {"message": "Status updated", "alert_id": alert_id, "status": update.status}


@app.get("/alerts/{alert_id}")
def get_alert_detail(alert_id: str):
    """Get details for a specific alert."""
    conn = get_db_connection()
    cursor = conn.cursor()

    table_name = config.get_table_name("alerts")
    alert_id_col = config.get_column("alerts", "id")

    cursor.execute(
        f'SELECT * FROM "{table_name}" WHERE "{alert_id_col}" = ?', (alert_id,)
    )
    row = cursor.fetchone()
    conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    return remap_row(dict(row), "alerts")


@app.post("/alerts/{alert_id}/summary")
def generate_summary(alert_id: str, request: Request):
    """Generate AI summary for the alert."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Get Alert Details
    alerts_table = config.get_table_name("alerts")
    alert_id_col = config.get_column("alerts", "id")
    isin_col = config.get_column("alerts", "isin")
    ticker_col = config.get_column("alerts", "ticker")  # Add ticker col
    start_col = config.get_column("alerts", "start_date")
    end_col = config.get_column("alerts", "end_date")

    cursor.execute(
        f'SELECT * FROM "{alerts_table}" WHERE "{alert_id_col}" = ?', (alert_id,)
    )
    alert = cursor.fetchone()

    if not alert:
        conn.close()
        raise HTTPException(status_code=404, detail="Alert not found")

    start_date = alert[start_col]
    end_date = alert[end_col]
    isin = alert[isin_col]
    ticker = alert[ticker_col] if ticker_col in alert.keys() else None

    # Extract trade_type for AI alignment check
    trade_type_col = config.get_column("alerts", "trade_type")
    trade_type = alert[trade_type_col] if trade_type_col in alert.keys() else None

    # 1.5 Fetch Price History for context
    price_history = []
    if ticker and start_date and end_date:
        prices_table = config.get_table_name("prices")
        price_ticker_col = config.get_column("prices", "ticker")
        price_date_col = config.get_column("prices", "date")
        price_close_col = config.get_column("prices", "close")

        try:
            cursor.execute(
                f'SELECT "{price_date_col}" as date, "{price_close_col}" as close FROM "{prices_table}" WHERE "{price_ticker_col}" = ? AND "{price_date_col}" BETWEEN ? AND ? ORDER BY "{price_date_col}" ASC',
                (ticker, start_date, end_date),
            )
            price_history = [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"Error fetching price history for summary: {e}")

    # 2. Fetch news with AI Analysis fallback
    articles_table = config.get_table_name("articles")
    themes_table = config.get_table_name("article_themes")

    art_id_col = config.get_column("articles", "id")
    art_isin_col = config.get_column("articles", "isin")
    date_col = config.get_column("articles", "created_date")
    title_col = config.get_column("articles", "title")
    summary_col = config.get_column("articles", "summary")
    impact_score_col = config.get_column("articles", "impact_score")

    # Theme columns
    theme_art_id_col = config.get_column("article_themes", "art_id")
    ai_theme_col = config.get_column("article_themes", "theme")
    ai_summary_col = config.get_column("article_themes", "summary")
    ai_analysis_col = config.get_column("article_themes", "analysis")
    ai_p1_col = config.get_column("article_themes", "p1_prominence")

    # Join query to prefer AI analysis if available
    query = f'''
        SELECT 
            a."{title_col}" as title, 
            a."{summary_col}" as original_summary,
            a."{date_col}" as created_date, 
            a."{impact_score_col}" as impact_score,
            t."{ai_theme_col}" as ai_theme,
            t."{ai_summary_col}" as ai_summary,
            t."{ai_analysis_col}" as ai_analysis,
            t."{ai_p1_col}" as ai_p1
        FROM "{articles_table}" a
        LEFT JOIN "{themes_table}" t ON a."{art_id_col}" = t."{theme_art_id_col}"
        WHERE a."{art_isin_col}" = ?
    '''
    params = [isin]

    if start_date:
        query += f' AND a."{date_col}" >= ?'
        params.append(start_date)
    if end_date:
        query += f' AND a."{date_col}" <= ?'
        params.append(end_date)

    query += f' ORDER BY a."{date_col}" DESC'

    cursor.execute(query, params)

    # Construct list for LLM, preferring AI versions
    articles = []
    for row in cursor.fetchall():
        r = dict(row)

        # Use AI theme if valid, else fallback to original
        theme = r.get("ai_theme")
        if not theme or theme.lower() == "string":
            # Determine which col holds original theme for articles
            orig_theme_col = config.get_column("articles", "theme")
            theme = r.get(orig_theme_col) or "UNCATEGORIZED"

        # Use Original Summary as requested
        summary = r.get("original_summary")
        if not summary or not summary.strip():
            summary = r.get("ai_summary")  # Last resort fallback

        # Calculate Materiality
        p1 = r.get("ai_p1") or "L"
        p2 = calculate_p2(r.get("created_date"), start_date, end_date)
        p3 = calculate_p3(theme)
        materiality = f"{p1}{p2}{p3}"

        articles.append(
            {
                "title": r["title"],
                "summary": summary,
                "theme": theme,
                "analysis": r["ai_analysis"],
                "impact_score": r["impact_score"],
                "materiality": materiality,
            }
        )

    # 3. Generate Summary via Singleton LLM
    try:
        llm = request.app.state.llm
        result = generate_cluster_summary(
            articles, price_history=price_history, trade_type=trade_type, llm=llm
        )
    except Exception as e:
        conn.close()
        print(f"LLM Error: {e}")
        raise HTTPException(status_code=500, detail=f"LLM Generation Failed: {str(e)}")

    # 4. Save to DB
    # 4. Save to DB
    now_str = datetime.now().isoformat()

    # Serialize lists to JSON
    bullish_json = json.dumps(result.get("bullish_events", []))
    bearish_json = json.dumps(result.get("bearish_events", []))
    neutral_json = json.dumps(result.get("neutral_events", []))

    # Extract Recommendation
    recommendation = result.get(
        "recommendation", "APPROVE L2"
    )  # Default to Approve L2 if missing
    recommendation_reason = result.get(
        "recommendation_reason", "AI analysis completed."
    )

    cursor.execute(
        f'UPDATE "{alerts_table}" SET "narrative_theme" = ?, "narrative_summary" = ?, "bullish_events" = ?, "bearish_events" = ?, "neutral_events" = ?, "summary_generated_at" = ?, "recommendation" = ?, "recommendation_reason" = ? WHERE "{alert_id_col}" = ?',
        (
            result["narrative_theme"],
            result["narrative_summary"],
            bullish_json,
            bearish_json,
            neutral_json,
            now_str,
            recommendation,
            recommendation_reason,
            alert_id,
        ),
    )
    conn.commit()
    conn.close()

    return {
        "narrative_theme": result["narrative_theme"],
        "narrative_summary": result["narrative_summary"],
        "bullish_events": result.get("bullish_events", []),
        "bearish_events": result.get("bearish_events", []),
        "neutral_events": result.get("neutral_events", []),
        "recommendation": recommendation,
        "recommendation_reason": recommendation_reason,
        "summary_generated_at": now_str,
    }


# fetch_and_cache_prices and get_ticker_from_isin moved to backend/prices.py


@app.get("/prices/{ticker}")
def get_prices(
    ticker: str,
    period: str = Query(None, pattern="^(1mo|3mo|6mo|1y|ytd|max)$"),
    start_date: str = Query(None),
    end_date: str = Query(None),
):
    """Get price data for a ticker with industry comparison."""
    # Use custom date range if provided, otherwise use period
    if start_date and end_date:
        start_date_str, actual_ticker = fetch_and_cache_prices(
            ticker, "1y", start_date, end_date
        )
    else:
        start_date_str, actual_ticker = fetch_and_cache_prices(ticker, period or "1y")

    conn = get_db_connection()
    cursor = conn.cursor()

    table_name = config.get_table_name("prices")
    ticker_col = config.get_column("prices", "ticker")
    date_col = config.get_column("prices", "date")

    # 2. Get Ticker Data
    query = (
        f'SELECT * FROM "{table_name}" WHERE "{ticker_col}" = ? AND "{date_col}" >= ? '
    )
    params = [actual_ticker, start_date_str]

    if end_date:
        query += f'AND "{date_col}" <= ? '
        params.append(end_date)

    query += f'ORDER BY "{date_col}" ASC'

    cursor.execute(query, tuple(params))
    rows = cursor.fetchall()
    conn.close()

    ticker_data = [remap_row(dict(row), "prices") for row in rows]

    # 3. Determine Sector and fetch ETF for comparison
    industry_data = []
    industry_name = "Industry Error"

    if ticker_data:
        etf_ticker = None
        sector_etf_mapping = config.get_sector_etf_mapping()

        try:
            info = yf.Ticker(actual_ticker).info
            sector = info.get("sector")
            industry_name = sector

            if sector in sector_etf_mapping:
                etf_ticker = sector_etf_mapping[sector]
            else:
                # Fallback to SPY
                etf_ticker = "SPY"
                industry_name = "Market (SPY)"
        except Exception as e:
            print(f"Error fetching sector: {e}")
            etf_ticker = "SPY"
            industry_name = "Market (SPY)"

        if etf_ticker:
            # Fetch ETF data
            if start_date and end_date:
                fetch_and_cache_prices(
                    etf_ticker, "1y", start_date, end_date, is_etf=True
                )
            else:
                fetch_and_cache_prices(etf_ticker, period, is_etf=True)

            # Query ETF data
            conn = get_db_connection()
            cursor = conn.cursor()

            query_etf = f'SELECT * FROM "{table_name}" WHERE "{ticker_col}" = ? AND "{date_col}" >= ? '
            params_etf = [etf_ticker, start_date_str]

            if end_date:
                query_etf += f'AND "{date_col}" <= ? '
                params_etf.append(end_date)

            query_etf += f'ORDER BY "{date_col}" ASC'

            cursor.execute(query_etf, tuple(params_etf))
            etf_rows = cursor.fetchall()
            conn.close()

            industry_data = [remap_row(dict(row), "prices") for row in etf_rows]

    return {
        "ticker": ticker_data,
        "industry": industry_data,
        "industry_name": industry_name,
    }


from .scoring import calculate_p2, calculate_p3


@app.get("/news/{isin}")
def get_news(
    isin: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    """Get news articles for an ISIN."""
    conn = get_db_connection()
    cursor = conn.cursor()

    table_name = config.get_table_name("articles")
    isin_col = config.get_column("articles", "isin")
    date_col = config.get_column("articles", "created_date")

    # Join query to prefer AI analysis if available
    themes_table = config.get_table_name("article_themes")
    art_id_col = config.get_column("articles", "id")
    theme_art_id_col = config.get_column("article_themes", "art_id")
    ai_theme_col = config.get_column("article_themes", "theme")
    ai_summary_col = config.get_column("article_themes", "summary")
    ai_analysis_col = config.get_column("article_themes", "analysis")
    ai_p1_col = config.get_column("article_themes", "p1_prominence")

    impact_score_col = config.get_column("articles", "impact_score")
    original_theme_col = config.get_column("articles", "theme")
    original_summary_col = config.get_column("articles", "summary")
    # Legacy P1 support (if exists in articles)
    legacy_p1_col = (
        "p1_prominence"  # We don't get this from config anymore as we removed it
    )

    query = f'''
        SELECT 
            a.*,
            a."{original_theme_col}" as original_theme,
            a."{original_summary_col}" as original_summary,
            t."{ai_theme_col}" as ai_theme,
            t."{ai_summary_col}" as ai_summary,
            t."{ai_analysis_col}" as ai_analysis,
            t."{ai_p1_col}" as ai_p1
        FROM "{table_name}" a
        LEFT JOIN "{themes_table}" t ON a."{art_id_col}" = t."{theme_art_id_col}"
        WHERE a."{isin_col}" = ?
    '''
    params = [isin]

    if start_date:
        query += f' AND "{date_col}" >= ?'
        params.append(start_date)

    if end_date:
        query += f' AND "{date_col}" <= ?'
        params.append(end_date)

    query += f' ORDER BY "{date_col}" DESC'

    cursor.execute(query, params)
    rows = cursor.fetchall()

    # Materiality Scoring Weights for Sorting
    mat_score_map = {"H": 3, "M": 2, "L": 1}

    results = []
    for row in rows:
        r = dict(row)
        remapped = remap_row(r, "articles")

        # Fallback logic for theme and summary
        ai_theme = r.get("ai_theme")
        if ai_theme and ai_theme.lower() != "string":
            remapped["theme"] = ai_theme

        # Ensure theme is never None (fallback to original or uncategorized)
        if remapped.get("theme") is None:
            remapped["theme"] = r.get("original_theme") or "UNCATEGORIZED"

        # ------------------------------------------------------------------
        # Dynamic Materiality Calculation (P1 + P2 + P3)
        # ------------------------------------------------------------------
        # Prefer P1 from article_themes (ai_p1), fallback to articles (p1_prominence)
        p1 = r.get("ai_p1") or r.get("p1_prominence") or "L"
        # p3 is now calculated dynamically from the theme
        p2 = calculate_p2(remapped.get("created_date"), start_date, end_date)
        p3 = calculate_p3(remapped.get("theme"))

        final_score = f"{p1}{p2}{p3}"
        remapped["materiality"] = final_score

        # Detailed Breakdown for Tooltip
        remapped["materiality_details"] = {
            "p1": {"score": p1, "reason": "Entity Mention (Title/Lead/Body)"},
            "p2": {
                "score": p2,
                "reason": f"Proximity to Window ({start_date} to {end_date})",
            },
            "p3": {"score": p3, "reason": f"Theme Priority ({remapped['theme']})"},
        }

        # Calculate numeric sort score (e.g., HHH=9, LLL=3)
        sort_score = (
            mat_score_map.get(p1, 1)
            + mat_score_map.get(p2, 1)
            + mat_score_map.get(p3, 1)
        )
        remapped["_sort_score"] = sort_score

        results.append(remapped)

    conn.close()

    # Sort by Materiality Score (descending), then by date
    results.sort(key=lambda x: (x["_sort_score"], x["created_date"]), reverse=True)

    # Remove temporary sort key
    for res in results:
        del res["_sort_score"]

    return results


# ==============================================================================
# AI AGENT ENDPOINTS
# ==============================================================================


class AlertContext(BaseModel):
    """Full alert context passed from frontend to avoid re-fetching."""

    id: str
    ticker: str
    isin: str
    start_date: str
    end_date: str
    instrument_name: Optional[str] = None
    trade_type: Optional[str] = None
    status: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    session_id: str
    alert_context: Optional[AlertContext] = None  # Full context from frontend


@app.get("/agent/history/{session_id}")
async def get_chat_history(session_id: str, request: Request):
    """
    Retrieve chat history for a given session from the LangGraph checkpointer.
    Returns messages in a format suitable for the frontend.
    """
    agent = request.app.state.agent
    config = {"configurable": {"thread_id": session_id}}

    try:
        # Get the current state from the checkpointer
        state = await agent.aget_state(config)

        # Debug logging
        print(f"[DEBUG] get_chat_history for session: {session_id}")
        print(f"[DEBUG] state exists: {state is not None}")
        print(f"[DEBUG] state.values: {state.values if state else 'None'}")

        if not state or not state.values:
            return {"messages": []}

        messages = state.values.get("messages", [])

        # Convert LangChain messages to frontend format
        frontend_messages = []
        for msg in messages:
            # Skip system messages and tool outputs
            if hasattr(msg, "type"):
                if msg.type == "system":
                    continue
                if msg.type == "tool":
                    continue

            role = "user" if (hasattr(msg, "type") and msg.type == "human") else "agent"
            content = msg.content if hasattr(msg, "content") else str(msg)

            # Handle case where content is a list (e.g., Gemini/Anthropic response structure)
            if isinstance(content, list):
                text_parts = []
                for part in content:
                    if isinstance(part, str):
                        text_parts.append(part)
                    elif isinstance(part, dict) and "text" in part:
                        text_parts.append(part["text"])
                content = " ".join(text_parts)

            # Skip empty messages
            if not content or (isinstance(content, str) and not content.strip()):
                continue

            # For user messages, strip the [CURRENT ALERT CONTEXT] prefix if present
            if role == "user" and "[USER QUESTION]" in content:
                # Extract just the user's question from the enriched message
                parts = content.split("[USER QUESTION]")
                if len(parts) > 1:
                    content = parts[1].strip()

            frontend_messages.append(
                {
                    "role": role,
                    "content": content,
                    "tools": [],  # Historical messages don't need tool indicators
                }
            )

        return {"messages": frontend_messages}

    except Exception as e:
        print(f"Error fetching chat history: {e}")
        return {"messages": []}


@app.delete("/agent/history/{session_id}")
async def delete_chat_history(session_id: str, request: Request):
    """
    Delete chat history for a given session from the LangGraph checkpointer.
    """
    import aiosqlite

    db_path = Path.home() / ".ts_pit" / "agent_memory.db"

    if not db_path.exists():
        return {
            "status": "deleted",
            "session_id": session_id,
            "message": "No history database found",
        }

    try:
        async with aiosqlite.connect(str(db_path)) as conn:
            deleted_count = 0

            # Try to delete from each table (some may not exist)
            for table in ["checkpoints", "checkpoint_writes", "checkpoint_blobs"]:
                try:
                    cursor = await conn.execute(
                        f"DELETE FROM {table} WHERE thread_id = ?", (session_id,)
                    )
                    deleted_count += cursor.rowcount
                except Exception:
                    pass  # Table doesn't exist, skip

            await conn.commit()

        return {
            "status": "deleted",
            "session_id": session_id,
            "deleted_rows": deleted_count,
        }

    except Exception as e:
        print(f"Error deleting chat history: {e}")
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=500, content={"status": "error", "message": str(e)}
        )


@app.post("/agent/chat")
async def chat_agent(request: Request, body: ChatRequest):
    """
    Chat with the Trade Surveillance Agent.
    Streams the response using Server-Sent Events (SSE).
    """
    agent = request.app.state.agent

    # Configure session
    config = {"configurable": {"thread_id": body.session_id}}

    # Build enriched user message with alert context
    if body.alert_context:
        ctx = body.alert_context
        enriched_message = f"""[CURRENT ALERT CONTEXT]
Alert ID: {ctx.id}
Ticker: {ctx.ticker} ({ctx.instrument_name or "N/A"})
ISIN: {ctx.isin}
Investigation Window: {ctx.start_date} to {ctx.end_date}
Trade Type: {ctx.trade_type or "N/A"}
Status: {ctx.status or "N/A"}

[USER QUESTION]
{body.message}"""
    else:
        enriched_message = body.message

    # Input State - no more current_alert_id, context is in message
    input_state = {
        "messages": [("user", enriched_message)],
    }

    async def event_generator():
        """Generates SSE events from the agent graph."""
        try:
            async for event in agent.astream_events(input_state, config, version="v1"):
                kind = event["event"]

                # Filter interesting events to stream to frontend
                if kind == "on_chat_model_stream":
                    # Only stream tokens from the AGENT node, not internal tool LLM calls
                    if event.get("metadata", {}).get("langgraph_node") != "agent":
                        continue

                    chunk = event["data"]["chunk"]
                    content = chunk.content

                    # Handle case where content is a list (e.g., Anthropic/Gemini structure)
                    if isinstance(content, list):
                        text_content = ""
                        for block in content:
                            if isinstance(block, str):
                                text_content += block
                            elif isinstance(block, dict) and "text" in block:
                                text_content += block["text"]
                        content = text_content

                    if content:
                        yield f"data: {json.dumps({'type': 'token', 'content': content})}\n\n"

                elif kind == "on_tool_start":
                    tool_name = event["name"]
                    yield f"data: {json.dumps({'type': 'tool_start', 'tool': tool_name})}\n\n"

                elif kind == "on_tool_end":
                    tool_name = event["name"]
                    # output = str(event["data"].get("output")) # Don't send full output
                    yield f"data: {json.dumps({'type': 'tool_end', 'tool': tool_name, 'output': 'Hidden'})}\n\n"

            # End of stream
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            print(f"Agent Error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
