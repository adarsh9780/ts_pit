import os
import yfinance as yf
import pandas as pd
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Optional
from pydantic import BaseModel
from .database import get_db_connection
from .database import get_db_connection
from .config import get_config
from .llm import generate_cluster_summary

app = FastAPI()

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
    }

    for col, dtype in new_cols.items():
        if col not in columns:
            print(f"Migrating: Adding {col} to {table_name}")
            cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{col}" {dtype}')

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


def remap_row(row, table_key: str):
    """
    Remaps a database row (dict-like) to UI keys based on config.

    Args:
        row: Database row as dict-like object
        table_key: Table key (alerts, articles, prices)

    Returns:
        Dict with UI-friendly keys
    """
    columns = config.get_columns(table_key)
    result = {}

    # Map DB columns to UI keys
    for ui_key, db_col in columns.items():
        if db_col and db_col in row.keys():
            result[ui_key] = row[db_col]

    # Keep extra fields that aren't in the mapping
    mapped_db_cols = set(col for col in columns.values() if col)
    for k in row.keys():
        if k not in mapped_db_cols:
            result[k] = row[k]

    return result


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
def generate_summary(alert_id: str):
    """Generate AI summary for the alert."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Get Alert Details
    alerts_table = config.get_table_name("alerts")
    alert_id_col = config.get_column("alerts", "id")
    isin_col = config.get_column("alerts", "isin")
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

    # 2. Fetch news
    articles_table = config.get_table_name("articles")
    art_isin_col = config.get_column("articles", "isin")
    date_col = config.get_column("articles", "created_date")
    title_col = config.get_column("articles", "title")
    summary_col = config.get_column("articles", "summary")

    query = f'SELECT "{title_col}" as title, "{summary_col}" as summary FROM "{articles_table}" WHERE "{art_isin_col}" = ?'
    params = [isin]

    if start_date:
        query += f' AND "{date_col}" >= ?'
        params.append(start_date)
    if end_date:
        query += f' AND "{date_col}" <= ?'
        params.append(end_date)

    query += f' ORDER BY "{date_col}" DESC'

    cursor.execute(query, params)
    articles = [dict(row) for row in cursor.fetchall()]

    # 3. Generate Summary via LLM
    try:
        result = generate_cluster_summary(articles)
    except Exception as e:
        conn.close()
        print(f"LLM Error: {e}")
        raise HTTPException(status_code=500, detail=f"LLM Generation Failed: {str(e)}")

    # 4. Save to DB
    now_str = datetime.now().isoformat()

    cursor.execute(
        f'UPDATE "{alerts_table}" SET "narrative_theme" = ?, "narrative_summary" = ?, "summary_generated_at" = ? WHERE "{alert_id_col}" = ?',
        (result["narrative_theme"], result["narrative_summary"], now_str, alert_id),
    )
    conn.commit()
    conn.close()

    return {
        "narrative_theme": result["narrative_theme"],
        "narrative_summary": result["narrative_summary"],
        "summary_generated_at": now_str,
    }


def fetch_and_cache_prices(ticker: str, period: str, is_etf: bool = False):
    """Fetches missing price data from yfinance and caches it in the database."""
    # Convert period to start date
    end_date = datetime.now()
    start_date = None

    if period == "1mo":
        start_date = end_date - pd.DateOffset(months=1)
    elif period == "3mo":
        start_date = end_date - pd.DateOffset(months=3)
    elif period == "6mo":
        start_date = end_date - pd.DateOffset(months=6)
    elif period == "1y":
        start_date = end_date - pd.DateOffset(years=1)
    elif period == "ytd":
        start_date = datetime(end_date.year, 1, 1)
    elif period == "max":
        start_date = datetime(1900, 1, 1)  # Effectively max
    else:
        start_date = end_date - pd.DateOffset(months=1)  # Default

    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get table and column names from config
    table_name = config.get_table_name("prices")
    ticker_col = config.get_column("prices", "ticker")
    date_col = config.get_column("prices", "date")
    open_col = config.get_column("prices", "open")
    close_col = config.get_column("prices", "close")
    volume_col = config.get_column("prices", "volume")
    industry_col = config.get_column("prices", "industry")

    # Ensure table exists
    # We create it dynamically to support any user-provided database
    create_table_query = f'''
        CREATE TABLE IF NOT EXISTS "{table_name}" (
            "{ticker_col}" TEXT,
            "{date_col}" TEXT,
            "{open_col}" REAL,
            "{close_col}" REAL,
            "{volume_col}" INTEGER,
            "{industry_col}" TEXT,
            PRIMARY KEY ("{ticker_col}", "{date_col}")
        )
    '''
    cursor.execute(create_table_query)
    conn.commit()

    # Check if we have data for this range
    cursor.execute(
        f'SELECT MIN("{date_col}") as min_date, MAX("{date_col}") as max_date '
        f'FROM "{table_name}" WHERE "{ticker_col}" = ?',
        (ticker,),
    )
    row = cursor.fetchone()

    need_fetch = False
    if row["min_date"] is None:
        need_fetch = True
    else:
        db_min = row["min_date"]
        # If DB start is significantly after requested start, fetch more.
        if db_min > start_str:
            need_fetch = True

    if need_fetch:
        print(f"Fetching {ticker} from yfinance...")
        try:
            # Fetch data from yfinance
            if period == "max":
                hist = yf.Ticker(ticker).history(period="max")
            else:
                hist = yf.Ticker(ticker).history(start=start_str, end=end_str)

            if not hist.empty:
                hist = hist.reset_index()
                # Ensure Date is string
                hist["Date"] = hist["Date"].dt.strftime("%Y-%m-%d")

                # Get industry info if not ETF
                industry = "Unknown"
                if not is_etf:
                    try:
                        info = yf.Ticker(ticker).info
                        industry = info.get("industry", "Unknown")
                    except:
                        pass
                else:
                    industry = "ETF"

                # Insert into DB
                data_to_insert = []
                for _, r in hist.iterrows():
                    data_to_insert.append(
                        (
                            ticker,
                            r["Date"],
                            r["Open"],
                            r["Close"],
                            r["Volume"],
                            industry,
                        )
                    )

                # UPSERT logic
                cursor.executemany(
                    f'''
                    INSERT OR IGNORE INTO "{table_name}" 
                    ("{ticker_col}", "{date_col}", "{open_col}", "{close_col}", "{volume_col}", "{industry_col}")
                    VALUES (?, ?, ?, ?, ?, ?)
                ''',
                    data_to_insert,
                )
                conn.commit()
        except Exception as e:
            print(f"Error fetching data for {ticker}: {e}")

    conn.close()
    return start_str


@app.get("/prices/{ticker}")
def get_prices(
    ticker: str, period: str = Query("1y", pattern="^(1mo|3mo|6mo|1y|ytd|max)$")
):
    """Get price data for a ticker with industry comparison."""
    # 1. Ensure data exists for ticker
    start_date_str = fetch_and_cache_prices(ticker, period)

    conn = get_db_connection()
    cursor = conn.cursor()

    table_name = config.get_table_name("prices")
    ticker_col = config.get_column("prices", "ticker")
    date_col = config.get_column("prices", "date")

    # 2. Get Ticker Data
    cursor.execute(
        f'SELECT * FROM "{table_name}" WHERE "{ticker_col}" = ? AND "{date_col}" >= ? '
        f'ORDER BY "{date_col}" ASC',
        (ticker, start_date_str),
    )
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
            info = yf.Ticker(ticker).info
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
            fetch_and_cache_prices(etf_ticker, period, is_etf=True)

            # Query ETF data
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                f'SELECT * FROM "{table_name}" WHERE "{ticker_col}" = ? AND "{date_col}" >= ? '
                f'ORDER BY "{date_col}" ASC',
                (etf_ticker, start_date_str),
            )
            etf_rows = cursor.fetchall()
            conn.close()

            industry_data = [remap_row(dict(row), "prices") for row in etf_rows]

    return {
        "ticker": ticker_data,
        "industry": industry_data,
        "industry_name": industry_name,
    }


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

    query = f'SELECT * FROM "{table_name}" WHERE "{isin_col}" = ?'
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
    conn.close()

    return [remap_row(dict(row), "articles") for row in rows]
