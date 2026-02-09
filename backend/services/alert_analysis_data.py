from __future__ import annotations

from ..scoring import calculate_p2, calculate_p3


def get_alert_id_candidates(config, cursor, table_name: str) -> list[str]:
    cursor.execute(f'PRAGMA table_info("{table_name}")')
    available_cols = {row["name"] for row in cursor.fetchall()}
    preferred = [
        config.get_column("alerts", "id"),
        "alert_id",
        "Alert ID",
        "id",
    ]
    return [column for column in dict.fromkeys(preferred) if column in available_cols]


def resolve_alert_row(config, cursor, table_name: str, alert_id: str | int):
    id_cols = get_alert_id_candidates(config, cursor, table_name)
    probe_values = [alert_id]
    if not isinstance(alert_id, str):
        probe_values.append(str(alert_id))
    elif alert_id.isdigit():
        probe_values.append(int(alert_id))

    for value in probe_values:
        for id_col in id_cols:
            cursor.execute(
                f'SELECT * FROM "{table_name}" WHERE "{id_col}" = ? LIMIT 1',
                (value,),
            )
            row = cursor.fetchone()
            if row:
                return row, id_col, value

    return None, None, None


def build_alert_articles(
    config,
    cursor,
    alert,
    start_date: str | None,
    end_date: str | None,
):
    articles_table = config.get_table_name("articles")
    themes_table = config.get_table_name("article_themes")

    art_id_col = config.get_column("articles", "id")
    art_isin_col = config.get_column("articles", "isin")
    date_col = config.get_column("articles", "created_date")
    title_col = config.get_column("articles", "title")
    summary_col = config.get_column("articles", "summary")
    impact_score_col = config.get_column("articles", "impact_score")
    original_theme_col = config.get_column("articles", "theme")

    theme_art_id_col = config.get_column("article_themes", "art_id")
    ai_theme_col = config.get_column("article_themes", "theme")
    ai_summary_col = config.get_column("article_themes", "summary")
    ai_analysis_col = config.get_column("article_themes", "analysis")
    ai_p1_col = config.get_column("article_themes", "p1_prominence")

    isin_col = config.get_column("alerts", "isin")
    isin = alert[isin_col]

    query = f'''
        SELECT
            a."{art_id_col}" as article_id,
            a."{title_col}" as title,
            a."{summary_col}" as original_summary,
            a."{date_col}" as created_date,
            a."{impact_score_col}" as impact_score,
            a."{original_theme_col}" as original_theme,
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
    articles = []
    for row in cursor.fetchall():
        row_data = dict(row)
        theme = row_data.get("ai_theme")
        if not theme or str(theme).lower() == "string":
            theme = row_data.get("original_theme") or "UNCATEGORIZED"
        summary = row_data.get("original_summary")
        if not summary or not str(summary).strip():
            summary = row_data.get("ai_summary")

        p1 = row_data.get("ai_p1") or "L"
        p2 = calculate_p2(row_data.get("created_date"), start_date, end_date)
        p3 = calculate_p3(theme)
        materiality = f"{p1}{p2}{p3}"

        articles.append(
            {
                "article_id": row_data.get("article_id"),
                "title": row_data.get("title"),
                "summary": summary,
                "created_date": row_data.get("created_date"),
                "theme": theme,
                "analysis": row_data.get("ai_analysis"),
                "impact_score": row_data.get("impact_score"),
                "materiality": materiality,
            }
        )
    return articles


def build_price_history(config, cursor, alert):
    price_history = []
    ticker_col = config.get_column("alerts", "ticker")
    start_col = config.get_column("alerts", "start_date")
    end_col = config.get_column("alerts", "end_date")
    ticker = alert[ticker_col] if ticker_col in alert.keys() else None
    start_date = alert[start_col]
    end_date = alert[end_col]
    if not (ticker and start_date and end_date):
        return price_history

    prices_table = config.get_table_name("prices")
    price_ticker_col = config.get_column("prices", "ticker")
    price_date_col = config.get_column("prices", "date")
    price_close_col = config.get_column("prices", "close")
    cursor.execute(
        f'SELECT "{price_date_col}" as date, "{price_close_col}" as close FROM "{prices_table}" WHERE "{price_ticker_col}" = ? AND "{price_date_col}" BETWEEN ? AND ? ORDER BY "{price_date_col}" ASC',
        (ticker, start_date, end_date),
    )
    return [dict(row) for row in cursor.fetchall()]
