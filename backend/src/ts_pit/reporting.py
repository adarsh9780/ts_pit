from __future__ import annotations

import html
import json
import base64
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ddgs import DDGS
from sqlalchemy import Text, cast, inspect, select

from .alert_analysis import (
    analyze_alert_non_persisting,
    build_price_history,
    get_current_alert_news_non_persisting,
    resolve_alert_row,
)
from .db import get_engine
from .services.db_helpers import get_table


REPORTS_ROOT = Path(__file__).parent / "data" / "reports"
CHART_SNAPSHOTS_DIR = "chart_snapshots"
SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9._-]{1,128}$")
DATA_URL_PATTERN = re.compile(r"^data:image/(png|jpeg);base64,", re.IGNORECASE)


def sanitize_session_id(session_id: str) -> str:
    if not session_id or not SESSION_ID_PATTERN.match(session_id):
        raise ValueError("Invalid session_id format")
    return session_id


def _format_num(value: Any, decimals: int = 2) -> str:
    try:
        return f"{float(value):,.{decimals}f}"
    except Exception:
        return "-"


def _parse_report_date(value: Any) -> datetime | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _safe_filename_component(value: Any, fallback: str) -> str:
    raw = str(value or fallback).strip()
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", raw)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or fallback


def _select_report_articles(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Keep all if <= 10. If more than 10, keep top 10 ranked by:
    1) number of H characters in materiality (desc),
    2) impact score absolute value (desc),
    3) created_date (desc, lexical ISO).
    """
    if len(articles) <= 10:
        return articles

    def _rank_key(a: dict[str, Any]):
        materiality = str(a.get("materiality") or "").upper()
        h_count = materiality.count("H")
        try:
            impact = abs(float(a.get("impact_score") or 0.0))
        except (TypeError, ValueError):
            impact = 0.0
        created_date = str(a.get("created_date") or "")
        return (h_count, impact, created_date)

    ranked = sorted(articles, key=_rank_key, reverse=True)
    return ranked[:10]


def _build_price_svg(price_history: list[dict], width: int = 900, height: int = 240) -> str:
    if not price_history:
        return '<svg width="900" height="240" xmlns="http://www.w3.org/2000/svg"><text x="20" y="30" font-size="14">No price data for alert window</text></svg>'

    points = []
    closes = []
    for row in price_history:
        close = row.get("close")
        try:
            closes.append(float(close))
        except Exception:
            continue

    if not closes:
        return '<svg width="900" height="240" xmlns="http://www.w3.org/2000/svg"><text x="20" y="30" font-size="14">No valid close prices in alert window</text></svg>'

    min_p = min(closes)
    max_p = max(closes)
    y_range = (max_p - min_p) or 1.0
    x_pad = 45
    y_pad = 25
    w = width - (x_pad * 2)
    h = height - (y_pad * 2)

    valid_rows = []
    for row in price_history:
        try:
            valid_rows.append((row.get("date", ""), float(row.get("close"))))
        except Exception:
            continue

    for idx, (_, close) in enumerate(valid_rows):
        x = x_pad + (idx / max(1, len(valid_rows) - 1)) * w
        y = y_pad + (1 - ((close - min_p) / y_range)) * h
        points.append(f"{x:.2f},{y:.2f}")

    polyline = " ".join(points)
    start_label = html.escape(str(valid_rows[0][0])) if valid_rows else "-"
    end_label = html.escape(str(valid_rows[-1][0])) if valid_rows else "-"

    return f"""
<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Alert window price chart">
  <rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff" stroke="#e2e8f0"/>
  <line x1="{x_pad}" y1="{y_pad}" x2="{x_pad}" y2="{height-y_pad}" stroke="#94a3b8"/>
  <line x1="{x_pad}" y1="{height-y_pad}" x2="{width-x_pad}" y2="{height-y_pad}" stroke="#94a3b8"/>
  <polyline fill="none" stroke="#2563eb" stroke-width="2.5" points="{polyline}"/>
  <text x="{x_pad}" y="16" font-size="12" fill="#334155">Close ({len(valid_rows)} points)</text>
  <text x="{x_pad}" y="{height-6}" font-size="11" fill="#64748b">{start_label}</text>
  <text x="{width-x_pad-120}" y="{height-6}" font-size="11" fill="#64748b">{end_label}</text>
  <text x="{width-x_pad+4}" y="{y_pad+4}" font-size="11" fill="#475569">{_format_num(max_p)}</text>
  <text x="{width-x_pad+4}" y="{height-y_pad}" font-size="11" fill="#475569">{_format_num(min_p)}</text>
</svg>
""".strip()


def save_chart_snapshot(
    session_id: str,
    alert_id: str | int,
    image_data_url: str,
) -> dict[str, Any]:
    """
    Persist a UI-captured chart snapshot for later embedding in reports.
    """
    session_id = sanitize_session_id(session_id)
    if not image_data_url or not DATA_URL_PATTERN.match(image_data_url):
        raise ValueError("Invalid image_data_url; expected data:image/png;base64,...")

    header, b64_data = image_data_url.split(",", 1)
    image_ext = "png" if "png" in header.lower() else "jpg"
    try:
        image_bytes = base64.b64decode(b64_data, validate=True)
    except Exception as e:
        raise ValueError(f"Invalid base64 image payload: {e}") from e

    safe_alert_id = str(alert_id).replace("/", "_")
    session_dir = REPORTS_ROOT / session_id / CHART_SNAPSHOTS_DIR
    session_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = session_dir / f"{safe_alert_id}_latest.{image_ext}"
    snapshot_path.write_bytes(image_bytes)

    return {
        "ok": True,
        "session_id": session_id,
        "alert_id": safe_alert_id,
        "snapshot_abs_path": str(snapshot_path),
        "snapshot_rel_path": f"{session_id}/{CHART_SNAPSHOTS_DIR}/{snapshot_path.name}",
    }


def _get_chart_snapshot_data_url(session_id: str, alert_id: str | int) -> str | None:
    session_id = sanitize_session_id(session_id)
    safe_alert_id = str(alert_id).replace("/", "_")
    snapshot_dir = REPORTS_ROOT / session_id / CHART_SNAPSHOTS_DIR
    if not snapshot_dir.exists():
        return None

    for ext, mime in (("png", "image/png"), ("jpg", "image/jpeg"), ("jpeg", "image/jpeg")):
        path = snapshot_dir / f"{safe_alert_id}_latest.{ext}"
        if path.exists():
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            return f"data:{mime};base64,{encoded}"
    return None


def _article_urls_by_id(conn, config, article_ids: list[Any]) -> dict[Any, str]:
    _ = conn
    if not article_ids:
        return {}
    engine = get_engine()
    table_name = config.get_table_name("articles")
    id_col = config.get_column("articles", "id")
    articles = get_table(table_name)

    cols = {col["name"] for col in inspect(engine).get_columns(table_name)}
    url_col = next(
        (c for c in ("url", "article_url", "art_url", "link", "news_url") if c in cols),
        None,
    )
    if not url_col:
        return {}

    normalized_ids = [str(i) for i in article_ids]
    stmt = (
        select(
            cast(articles.c[id_col], Text).label("article_id"),
            cast(articles.c[url_col], Text).label("article_url"),
        )
        .where(cast(articles.c[id_col], Text).in_(normalized_ids))
    )
    with engine.connect() as db_conn:
        rows = db_conn.execute(stmt).mappings().all()
    return {row["article_id"]: row["article_url"] for row in rows}


def _fetch_web_news(query: str, config, max_results: int = 5) -> list[dict[str, str]]:
    proxy_config = config.get_proxy_config()
    proxy_url = proxy_config.get("https") or proxy_config.get("http")
    kwargs: dict[str, Any] = {"verify": proxy_config.get("ssl_verify", True)}
    if proxy_url:
        kwargs["proxy"] = proxy_url

    try:
        with DDGS(**kwargs) as ddgs:
            rows = list(ddgs.news(query, max_results=max_results))
    except Exception:
        return []

    results = []
    for r in rows[:max_results]:
        results.append(
            {
                "title": str(r.get("title") or "No title"),
                "source": str(r.get("source") or "Unknown"),
                "date": str(r.get("date") or "Unknown"),
                "url": str(r.get("url") or ""),
                "summary": str(r.get("body") or "").strip(),
            }
        )
    return results


def _render_reasoning_html(reason: str) -> str:
    lines = [ln.strip() for ln in str(reason or "").splitlines() if ln.strip()]
    if not lines:
        return "<p class='muted'>No reasoning provided.</p>"

    intro_items: list[str] = []
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for ln in lines:
        is_bullet = ln.startswith("- ")
        content = ln[2:].strip() if is_bullet else ln
        is_header = (not is_bullet) and content.endswith(":")

        if is_header:
            current = {"title": content[:-1].strip(), "items": []}
            sections.append(current)
            continue

        if current is None:
            intro_items.append(content)
        else:
            current["items"].append(content)

    parts: list[str] = []
    if intro_items:
        parts.append("<ul>" + "".join(f"<li>{html.escape(item)}</li>" for item in intro_items) + "</ul>")

    for section in sections:
        title = html.escape(str(section.get("title") or ""))
        items = section.get("items") or []
        parts.append(f"<h4 class='reason-subtitle'>{title}</h4>")
        if items:
            parts.append("<ul>" + "".join(f"<li>{html.escape(item)}</li>" for item in items) + "</ul>")
        else:
            parts.append("<p class='muted'>No details provided.</p>")

    return "".join(parts)


def _render_report_html(payload: dict[str, Any]) -> str:
    alert = payload["alert"]
    analysis = payload["analysis"]
    h_articles = payload["high_materiality_articles"]
    related_alert_ids = [
        str(x) for x in (payload.get("related_alert_ids") or []) if str(x).strip()
    ]
    related_alert_count = int(payload.get("related_alert_count") or 0)
    linked_alerts_notice = str(payload.get("linked_alerts_notice") or "").strip()
    if not linked_alerts_notice:
        if related_alert_count > 1:
            linked_alerts_notice = (
                "Multiple alerts share the same ticker and investigation window. "
                "Use this conclusion consistently unless case-specific evidence differs."
            )
        else:
            linked_alerts_notice = (
                "No linked alerts found for the same ticker and investigation window."
            )
    price_svg = payload["price_svg"]
    chart_snapshot = payload.get("chart_snapshot_data_url")
    web_news = payload.get("web_news", [])
    generated_at = payload["generated_at"]

    def _e(v: Any) -> str:
        return html.escape(str(v if v is not None else "-"))

    evidence_cards = []
    for idx, a in enumerate(h_articles, start=1):
        title = _e(a.get("title"))
        url = a.get("url")
        title_html = f'<a href="{html.escape(url)}" target="_blank" rel="noopener noreferrer">{title}</a>' if url else title
        evidence_cards.append(
            f"""
<article class="news-item">
  <div class="news-kicker">Evidence {idx}</div>
  <h3 class="news-title">{title_html}</h3>
  <p class="news-meta">{_e(a.get('created_date'))} | {_e(a.get('theme'))} | Materiality {_e(a.get('materiality'))} | Impact {_format_num(a.get('impact_score'), 2)}</p>
  <p class="news-summary">{_e(a.get('summary'))}</p>
</article>
""".strip()
        )
    evidence_html = "\n".join(evidence_cards) if evidence_cards else "<p class='muted'>No internal alert-window articles with materiality containing H were found.</p>"

    web_items = []
    for w in web_news:
        title_html = _e(w.get("title"))
        if w.get("url"):
            title_html = f'<a href="{html.escape(w.get("url"))}" target="_blank" rel="noopener noreferrer">{title_html}</a>'
        web_items.append(
            f"""
<article class="news-item web-item">
  <h3 class="news-title">{title_html}</h3>
  <p class="news-meta">{_e(w.get('source'))} | {_e(w.get('date'))}</p>
  <p class="news-summary">{_e(w.get('summary'))}</p>
</article>
""".strip()
        )
    web_html = "\n".join(web_items) if web_items else "<p class='muted'>Web news enrichment not included.</p>"

    rec = analysis["analysis"].get("recommendation", "NEEDS_REVIEW")
    rec_norm = str(rec or "NEEDS_REVIEW").upper()
    rec_class = {
        "ESCALATE_L2": "badge-escalate",
        "DISMISS": "badge-close",
        "NEEDS_REVIEW": "badge-review",
    }.get(rec_norm, "badge-review")
    rec_reason_raw = str(analysis["analysis"].get("recommendation_reason") or "").strip()
    reason_html = _render_reasoning_html(rec_reason_raw)
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Investigation Report { _e(alert.get('id')) }</title>
  <style>
    :root {{
      --text: #0f172a;
      --muted: #64748b;
      --line: #e2e8f0;
      --surface: #ffffff;
      --surface-soft: #f8fafc;
      --title: #111827;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: linear-gradient(180deg, #f8fafc 0%, #eef2f7 100%);
      color: var(--text);
      font-family: "Inter", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
      font-size: 14px;
      line-height: 1.6;
      padding: 28px 20px;
    }}
    .report {{
      max-width: 1040px;
      margin: 0 auto;
      background: var(--surface);
      border: 1px solid #dbe3ef;
      border-radius: 14px;
      padding: 26px 30px 34px 30px;
      box-shadow: 0 10px 28px rgba(15, 23, 42, 0.08);
    }}
    .report-head {{
      border-bottom: 1px solid var(--line);
      padding-bottom: 10px;
      margin-bottom: 14px;
    }}
    h1, h2, h3 {{ margin: 0 0 10px 0; color: var(--title); font-family: "Inter", "Segoe UI", "Helvetica Neue", Arial, sans-serif; }}
    h1 {{ font-size: 38px; letter-spacing: -0.02em; margin-bottom: 6px; }}
    h2 {{ font-size: 22px; margin-bottom: 12px; letter-spacing: -0.01em; }}
    h3 {{ font-size: 16px; margin-top: 6px; }}
    .subtitle {{ color: var(--muted); font-family: "Inter", "Segoe UI", Arial, sans-serif; font-size: 13px; }}
    .muted {{ color: var(--muted); }}
    .card {{
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 16px 18px 14px 18px;
      margin: 16px 0;
      background: var(--surface);
    }}
    .meta-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 6px 18px;
      margin-top: 8px;
    }}
    .meta-item b {{ font-family: "Helvetica Neue", Arial, sans-serif; }}
    .recommendation-row {{
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
      margin: 8px 0 10px 0;
    }}
    .rec-badge {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
      font-weight: 700;
      font-family: "Helvetica Neue", Arial, sans-serif;
      border: 1px solid transparent;
      letter-spacing: 0.02em;
    }}
    .badge-escalate {{ color: #991b1b; background: #fee2e2; border-color: #fecaca; }}
    .badge-close {{ color: #065f46; background: #d1fae5; border-color: #a7f3d0; }}
    .badge-review {{ color: #92400e; background: #fef3c7; border-color: #fde68a; }}
    .reason-box {{
      background: #fafcff;
      border: 1px solid #e6edf7;
      border-radius: 10px;
      padding: 10px 12px;
      margin: 8px 0 10px 0;
    }}
    .reason-box p {{
      margin: 0 0 6px 0;
    }}
    .reason-box ul {{
      margin: 0 0 0 18px;
      padding: 0;
    }}
    .reason-box li {{
      margin-bottom: 5px;
    }}
    .reason-subtitle {{
      margin: 10px 0 6px 0;
      font-size: 14px;
      font-weight: 700;
      color: #1e293b;
    }}
    .chart-frame {{
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      background: var(--surface-soft);
      padding: 8px;
    }}
    .news-feed {{
      display: flex;
      flex-direction: column;
      gap: 12px;
    }}
    .news-item {{
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 12px 14px;
      background: #fff;
    }}
    .news-kicker {{
      font-family: "Helvetica Neue", Arial, sans-serif;
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      margin-bottom: 4px;
    }}
    .news-title {{
      margin: 0 0 4px 0;
      font-size: 18px;
      line-height: 1.35;
    }}
    .news-title a {{
      color: #1d4ed8;
      text-decoration: none;
    }}
    .news-title a:hover {{
      text-decoration: underline;
    }}
    .news-meta {{
      margin: 0 0 6px 0;
      font-family: "Helvetica Neue", Arial, sans-serif;
      color: var(--muted);
      font-size: 12px;
    }}
    .news-summary {{
      margin: 0;
    }}
    .web-item .news-title {{
      font-size: 16px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      table-layout: fixed;
    }}
    th, td {{
      border: 1px solid var(--line);
      padding: 8px 9px;
      text-align: left;
      vertical-align: top;
      word-wrap: break-word;
    }}
    th {{
      background: var(--surface-soft);
      font-family: "Helvetica Neue", Arial, sans-serif;
      font-size: 12px;
      letter-spacing: 0.01em;
    }}
    tr:nth-child(even) td {{ background: #fcfdff; }}
    ul {{ margin: 8px 0 0 20px; }}
    li {{ margin-bottom: 8px; }}
    .small {{ font-size: 12px; }}
    .pre {{ white-space: pre-wrap; }}
    .section-index {{
      font-family: "Inter", "Segoe UI", Arial, sans-serif;
      font-size: 11px;
      color: var(--muted);
      margin-bottom: 4px;
      text-transform: uppercase;
      letter-spacing: 0.1em;
    }}
    @media print {{
      body {{ background: #fff; padding: 0; }}
      .report {{ border: none; box-shadow: none; max-width: none; border-radius: 0; padding: 16px 20px; }}
      a {{ color: inherit; text-decoration: none; }}
    }}
  </style>
</head>
<body>
  <div class="report">
    <div class="report-head">
      <h1>Investigation Report</h1>
      <p class="subtitle">Generated: {_e(generated_at)} | Session: {_e(payload.get('session_id'))} | Alert: {_e(alert.get('id'))}</p>
    </div>

    <div class="card">
      <div class="section-index">Section 1</div>
      <h2>Alert Context</h2>
      <div class="meta-grid">
        <div class="meta-item"><b>Ticker:</b> {_e(alert.get('ticker'))} ({_e(alert.get('instrument_name'))})</div>
        <div class="meta-item"><b>ISIN:</b> {_e(alert.get('isin'))}</div>
        <div class="meta-item"><b>Window:</b> {_e(alert.get('start_date'))} to {_e(alert.get('end_date'))}</div>
        <div class="meta-item"><b>Trade Type:</b> {_e(alert.get('trade_type'))}</div>
        <div class="meta-item"><b>Status:</b> {_e(alert.get('status'))}</div>
        <div class="meta-item"><b>Analysis Source:</b> {_e(analysis.get('source'))}</div>
      </div>
    </div>

    <div class="card">
      <div class="section-index">Section 2</div>
      <h2>Linked Alerts Detected</h2>
      <p>{_e(linked_alerts_notice)}</p>
      <p><b>Related Alert IDs:</b> {_e(", ".join(related_alert_ids) if related_alert_ids else "None")}</p>
    </div>

    <div class="card">
      <div class="section-index">Section 3</div>
      <h2>Executive Summary</h2>
      <div class="recommendation-row">
        <b>Recommendation:</b>
        <span class="rec-badge {rec_class}">{_e(rec_norm)}</span>
      </div>
      <div class="reason-box">
        <b>Reasoning:</b>
        {reason_html}
      </div>
      <p><b>Narrative Theme:</b> {_e(analysis['analysis'].get('narrative_theme'))}</p>
      <p class="pre"><b>Narrative Summary:</b> {_e(analysis['analysis'].get('narrative_summary'))}</p>
    </div>

    <div class="card">
      <div class="section-index">Section 4</div>
      <h2>Price Chart (Alert Window)</h2>
      <div class="chart-frame">
        {"<img src='" + html.escape(chart_snapshot) + "' alt='Alert chart snapshot' style='max-width:100%;display:block;border-radius:4px;'/>" if chart_snapshot else price_svg}
      </div>
    </div>

    <div class="card">
      <div class="section-index">Section 5</div>
      <h2>Internal Evidence Articles (Materiality contains H)</h2>
      <div class="news-feed">{evidence_html}</div>
    </div>

    <div class="card">
      <div class="section-index">Section 6</div>
      <h2>External News (Optional Enrichment)</h2>
      <div class="news-feed">{web_html}</div>
    </div>
  </div>
</body>
</html>
"""


def generate_alert_report_html(
    conn,
    config,
    llm,
    alert_id: str | int,
    session_id: str,
    include_web_news: bool = False,
) -> dict[str, Any]:
    session_id = sanitize_session_id(session_id)

    alerts_table = config.get_table_name("alerts")
    alert_row, _, _ = resolve_alert_row(config, None, alerts_table, alert_id)
    if not alert_row:
        return {"ok": False, "error": "Alert not found"}
    alert = dict(alert_row)

    analysis = analyze_alert_non_persisting(conn=conn, config=config, alert_id=alert_id, llm=llm)
    if not analysis.get("ok"):
        return {"ok": False, "error": analysis.get("error", "Analysis failed")}

    # Internal alert-window news and materiality filter
    news_data = get_current_alert_news_non_persisting(conn=conn, config=config, alert_id=alert_id, limit=500)
    articles = news_data.get("articles", []) if news_data.get("ok") else []
    high_materiality_articles = [
        a for a in articles if "H" in str(a.get("materiality") or "").upper()
    ]
    high_materiality_articles = _select_report_articles(high_materiality_articles)

    # Optional URL enrichment
    article_ids = [a.get("article_id") for a in high_materiality_articles if a.get("article_id") is not None]
    url_map = _article_urls_by_id(conn, config, article_ids)
    for a in high_materiality_articles:
        if a.get("article_id") in url_map:
            a["url"] = url_map[a["article_id"]]

    price_history = build_price_history(config, None, alert_row)
    price_svg = _build_price_svg(price_history)
    chart_snapshot_data_url = _get_chart_snapshot_data_url(session_id=session_id, alert_id=alert_id)

    web_news = []
    if include_web_news:
        query = f"{alert.get(config.get_column('alerts', 'ticker'), '')} stock news"
        web_news = _fetch_web_news(query=query, config=config, max_results=5)

    now = datetime.now()
    report_payload = {
        "session_id": session_id,
        "alert": {
            "id": alert.get(config.get_column("alerts", "id")),
            "ticker": alert.get(config.get_column("alerts", "ticker")),
            "instrument_name": alert.get(config.get_column("alerts", "instrument_name")),
            "isin": alert.get(config.get_column("alerts", "isin")),
            "start_date": alert.get(config.get_column("alerts", "start_date")),
            "end_date": alert.get(config.get_column("alerts", "end_date")),
            "trade_type": alert.get(config.get_column("alerts", "trade_type")),
            "status": alert.get(config.get_column("alerts", "status")),
            "alert_date": alert.get(config.get_column("alerts", "alert_date")),
        },
        "analysis": {
            "source": analysis.get("source"),
            "analysis": analysis.get("result", {}),
            "citations": analysis.get("citations", []),
        },
        "related_alert_ids": analysis.get("related_alert_ids", []),
        "related_alert_count": analysis.get("related_alert_count", 0),
        "linked_alerts_notice": analysis.get("linked_alerts_notice"),
        "high_materiality_articles": high_materiality_articles,
        "price_svg": price_svg,
        "chart_snapshot_data_url": chart_snapshot_data_url,
        "web_news": web_news,
        "generated_at": now.isoformat(),
    }

    report_html = _render_report_html(report_payload)
    ticker_str = _safe_filename_component(report_payload["alert"].get("ticker"), "ticker")
    alert_id_str = _safe_filename_component(report_payload["alert"].get("id") or alert_id, "alert")
    alert_date_raw = (
        report_payload["alert"].get("alert_date")
        or report_payload["alert"].get("end_date")
        or report_payload["alert"].get("start_date")
    )
    parsed_alert_date = _parse_report_date(alert_date_raw) or now
    human_date = parsed_alert_date.strftime("%b_%d_%Y")
    session_dir = REPORTS_ROOT / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    base_filename = f"{ticker_str}_{alert_id_str}_{human_date}"
    report_filename = f"{base_filename}.html"
    report_path = session_dir / report_filename
    suffix = 2
    while report_path.exists():
        report_filename = f"{base_filename}_{suffix}.html"
        report_path = session_dir / report_filename
        suffix += 1
    report_path.write_text(report_html, encoding="utf-8")

    expires_at = (now + timedelta(hours=24)).isoformat()
    return {
        "ok": True,
        "session_id": session_id,
        "alert_id": alert_id_str,
        "report_filename": report_filename,
        "report_rel_path": f"{session_id}/{report_filename}",
        "report_abs_path": str(report_path),
        "download_url": f"/reports/{session_id}/{report_filename}",
        "expires_at": expires_at,
        "generated_at": now.isoformat(),
    }
