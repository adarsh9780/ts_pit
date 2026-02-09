from __future__ import annotations

import yfinance as yf
from fastapi import APIRouter, Query

from ...config import get_config
from ...database import get_db_connection, remap_row
from ...logger import logprint
from ...prices import fetch_and_cache_prices
from ...scoring import calculate_p2, calculate_p3
from ...services.alert_normalizer import normalize_impact_label


router = APIRouter(tags=["market"])
config = get_config()


@router.get("/prices/{ticker}")
def get_prices(
    ticker: str,
    period: str = Query(None, pattern="^(1mo|3mo|6mo|1y|ytd|max)$"),
    start_date: str = Query(None),
    end_date: str = Query(None),
):
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
                etf_ticker = "SPY"
                industry_name = "Market (SPY)"
        except Exception as e:
            logprint("Failed to fetch sector info", level="ERROR", ticker=actual_ticker, error=str(e))
            etf_ticker = "SPY"
            industry_name = "Market (SPY)"

        if etf_ticker:
            if start_date and end_date:
                fetch_and_cache_prices(
                    etf_ticker, "1y", start_date, end_date, is_etf=True
                )
            else:
                fetch_and_cache_prices(etf_ticker, period, is_etf=True)

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


@router.get("/news/{isin}")
def get_news(
    isin: str,
    start_date: str | None = None,
    end_date: str | None = None,
):
    conn = get_db_connection()
    cursor = conn.cursor()

    table_name = config.get_table_name("articles")
    isin_col = config.get_column("articles", "isin")
    date_col = config.get_column("articles", "created_date")

    themes_table = config.get_table_name("article_themes")
    art_id_col = config.get_column("articles", "id")
    theme_art_id_col = config.get_column("article_themes", "art_id")
    ai_theme_col = config.get_column("article_themes", "theme")
    ai_summary_col = config.get_column("article_themes", "summary")
    ai_analysis_col = config.get_column("article_themes", "analysis")
    ai_p1_col = config.get_column("article_themes", "p1_prominence")

    original_theme_col = config.get_column("articles", "theme")
    original_summary_col = config.get_column("articles", "summary")
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

    mat_score_map = {"H": 3, "M": 2, "L": 1}
    results = []
    for row in rows:
        r = dict(row)
        remapped = remap_row(r, "articles")
        if "impact_label" in remapped:
            remapped["impact_label"] = normalize_impact_label(remapped["impact_label"])

        ai_theme = r.get("ai_theme")
        if ai_theme and ai_theme.lower() != "string":
            remapped["theme"] = ai_theme

        if remapped.get("theme") is None:
            remapped["theme"] = r.get("original_theme") or "UNCATEGORIZED"

        p1 = r.get("ai_p1") or "L"
        p2 = calculate_p2(remapped.get("created_date"), start_date, end_date)
        p3 = calculate_p3(remapped.get("theme"))

        final_score = f"{p1}{p2}{p3}"
        remapped["materiality"] = final_score
        remapped["materiality_details"] = {
            "p1": {"score": p1, "reason": "Entity Mention (Title/Lead/Body)"},
            "p2": {"score": p2, "reason": f"Proximity to Window ({start_date} to {end_date})"},
            "p3": {"score": p3, "reason": f"Theme Priority ({remapped['theme']})"},
        }

        sort_score = (
            mat_score_map.get(p1, 1)
            + mat_score_map.get(p2, 1)
            + mat_score_map.get(p3, 1)
        )
        remapped["_sort_score"] = sort_score
        results.append(remapped)

    conn.close()

    results.sort(key=lambda x: (x["_sort_score"], x["created_date"]), reverse=True)
    for res in results:
        del res["_sort_score"]

    return results

