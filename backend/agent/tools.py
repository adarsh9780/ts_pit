"""
Tools for the Trade Surveillance Agent
======================================
Defines the tools available to the LangGraph agent for interacting with
the database and retrieving alert context.
"""

import sqlite3
import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional
from langchain_core.tools import tool
from backend.database import get_db_connection, remap_row
from backend.config import get_config

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
        return "Error: Only SELECT statements are allowed for security reasons."

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

        return str(results)
    except Exception as e:
        return f"Database error: {str(e)}"


# Inject schema into docstring
execute_sql.__doc__ = execute_sql.__doc__.format(db_schema=DB_SCHEMA)


@tool
def get_alert_details(alert_id: str) -> str:
    """
    Get detailed information for a specific alert by its ID (e.g., 'ALT-1000').
    Returns the full alert record including status, dates, and trade details.
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
            return f"Alert {alert_id} not found."

        # Use the same remapping logic as the API for consistency
        result = remap_row(dict(row), "alerts")
        return str(result)
    except Exception as e:
        return f"Error fetching alert details: {str(e)}"


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
            return f"No alerts found for ticker {ticker}."

        return str(results)
    except Exception as e:
        return f"Error fetching alerts for ticker: {str(e)}"


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
            return f"Ticker {ticker} not found in alerts database, cannot link to news."

        isin = row[0]

        # 2. Query Articles by ISIN
        articles_table = config.get_table_name("articles")
        article_isin_col = config.get_column("articles", "isin")
        impact_col = config.get_column("articles", "impact_label")

        if not article_isin_col or not impact_col:
            conn.close()
            return "Tool configuration error: missing ISIN or impact_label mapping for articles."

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
            return f"No news found for {ticker} (ISIN: {isin})."

        results = {row[0]: row[1] for row in rows}
        return f"News Impact Breakdown for {ticker}: {results}"

    except Exception as e:
        conn.close()
        return f"Error counting material news: {str(e)}"


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
            return f"No price data found for {ticker}."

        # Return simplified data to save tokens
        results = [dict(row) for row in rows]
        # Reverse to show chronological order
        results.reverse()
        return f"Recent Price History for {ticker} (Last 30 records):\n" + str(results)

    except Exception as e:
        return f"Error fetching prices: {str(e)}"


@tool
def search_news(ticker: str, limit: int = 5) -> str:
    """
    Search for recent news articles for a ticker.
    Args:
        ticker: Stock symbol
        limit: Max number of articles to return (default 5)
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
            return f"Ticker {ticker} not found in alerts, cannot link to news."
        isin = row[0]

        # Query Articles
        articles_table = config.get_table_name("articles")
        article_isin_col = config.get_column("articles", "isin")
        title_col = config.get_column("articles", "title")
        summary_col = config.get_column("articles", "summary")
        date_col = config.get_column("articles", "created_date")

        cursor.execute(
            f'SELECT "{date_col}", "{title_col}", "{summary_col}" FROM "{articles_table}" WHERE "{article_isin_col}" = ? ORDER BY "{date_col}" DESC LIMIT ?',
            (isin, limit),
        )
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return f"No news found for {ticker}."

        results = [dict(row) for row in rows]
        return str(results)

    except Exception as e:
        conn.close()
        return f"Error searching news: {str(e)}"


@tool
def update_alert_status(alert_id: str, status: str, reason: str = None) -> str:
    """
    Update the status of an alert.
    Args:
        alert_id: The ID of the alert (e.g., ALT-1000)
        status: New status ('Pending', 'Approved', 'Rejected')
        reason: Optional reason for the status change
    """
    valid_statuses = ["Pending", "Approved", "Rejected"]
    if status not in valid_statuses:
        return f"Invalid status '{status}'. Must be one of: {valid_statuses}"

    config = get_config()
    conn = get_db_connection()
    cursor = conn.cursor()

    table_name = config.get_table_name("alerts")
    alert_id_col = config.get_column("alerts", "id")
    status_col = config.get_column("alerts", "status")

    try:
        cursor.execute(
            f'UPDATE "{table_name}" SET "{status_col}" = ? WHERE "{alert_id_col}" = ?',
            (status, alert_id),
        )
        conn.commit()

        if cursor.rowcount == 0:
            conn.close()
            return f"Alert {alert_id} not found."

        conn.close()
        return f"Successfully updated alert {alert_id} status to '{status}'."

    except Exception as e:
        conn.close()
        return f"Error updating alert status: {str(e)}"
