from __future__ import annotations

from sqlalchemy import Column, MetaData, Table, Text

from ..config import get_config


def _add_columns(table: Table, column_names: list[str]) -> None:
    seen = set()
    for name in column_names:
        if not name or name in seen:
            continue
        table.append_column(Column(name, Text))
        seen.add(name)


def build_metadata(config=None) -> MetaData:
    """
    Build SQLAlchemy Core table metadata from config mappings.
    This is a schema contract used for validation and future query migration.
    """
    cfg = config or get_config()
    md = MetaData()

    alerts = Table(cfg.get_table_name("alerts"), md)
    _add_columns(
        alerts,
        [
            cfg.get_column("alerts", "id"),
            cfg.get_column("alerts", "ticker"),
            cfg.get_column("alerts", "status"),
            cfg.get_column("alerts", "isin"),
            cfg.get_column("alerts", "instrument_name"),
            cfg.get_column("alerts", "buy_quantity"),
            cfg.get_column("alerts", "sell_quantity"),
            cfg.get_column("alerts", "execution_date"),
            cfg.get_column("alerts", "trade_type"),
            cfg.get_column("alerts", "alert_date"),
            cfg.get_column("alerts", "start_date"),
            cfg.get_column("alerts", "end_date"),
        ],
    )

    articles = Table(cfg.get_table_name("articles"), md)
    _add_columns(
        articles,
        [
            cfg.get_column("articles", "id"),
            cfg.get_column("articles", "isin"),
            cfg.get_column("articles", "created_date"),
            cfg.get_column("articles", "title"),
            cfg.get_column("articles", "body"),
            cfg.get_column("articles", "sentiment"),
            cfg.get_column("articles", "theme"),
            cfg.get_column("articles", "summary"),
            cfg.get_column("articles", "ticker"),
            cfg.get_column("articles", "instrument_name"),
            cfg.get_column("articles", "impact_score"),
            cfg.get_column("articles", "impact_label"),
        ],
    )

    article_themes = Table(cfg.get_table_name("article_themes"), md)
    _add_columns(
        article_themes,
        [
            cfg.get_column("article_themes", "art_id"),
            cfg.get_column("article_themes", "theme"),
            cfg.get_column("article_themes", "summary"),
            cfg.get_column("article_themes", "analysis"),
            cfg.get_column("article_themes", "p1_prominence"),
        ],
    )

    prices = Table(cfg.get_table_name("prices"), md)
    _add_columns(
        prices,
        [
            cfg.get_column("prices", "ticker"),
            cfg.get_column("prices", "date"),
            cfg.get_column("prices", "open"),
            cfg.get_column("prices", "high"),
            cfg.get_column("prices", "low"),
            cfg.get_column("prices", "close"),
            cfg.get_column("prices", "volume"),
            cfg.get_column("prices", "industry"),
        ],
    )

    prices_hourly = Table(cfg.get_table_name("prices_hourly"), md)
    _add_columns(
        prices_hourly,
        [
            cfg.get_column("prices_hourly", "ticker"),
            cfg.get_column("prices_hourly", "date"),
            cfg.get_column("prices_hourly", "open"),
            cfg.get_column("prices_hourly", "high"),
            cfg.get_column("prices_hourly", "low"),
            cfg.get_column("prices_hourly", "close"),
            cfg.get_column("prices_hourly", "volume"),
        ],
    )

    alert_analysis = Table("alert_analysis", md)
    _add_columns(
        alert_analysis,
        [
            "id",
            "alert_id",
            "generated_at",
            "source",
            "narrative_theme",
            "narrative_summary",
            "bullish_events",
            "bearish_events",
            "neutral_events",
            "recommendation",
            "recommendation_reason",
        ],
    )

    return md
