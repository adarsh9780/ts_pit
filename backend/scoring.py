from datetime import datetime, timezone

# ==============================================================================
# SCORING LOGIC (P1, P2, P3)
# ==============================================================================


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    """Parse common DB/API datetime representations into naive UTC datetimes."""
    if value is None:
        return None

    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if not raw:
            return None
        normalized = raw.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(normalized, fmt)
                    break
                except ValueError:
                    continue
            else:
                return None

    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def calculate_p2(art_date_str: str, start_date_str: str, end_date_str: str) -> str:
    """
    Calculate P2 (Time Proximity) Score.
    H = In the last 33% of the window (closest to impact).
    M = In the middle 33%.
    L = In the first 33% or outside.
    """
    if not start_date_str or not end_date_str or not art_date_str:
        return "L"

    try:
        dt_start = _parse_datetime(start_date_str)
        dt_end = _parse_datetime(end_date_str)
        dt_art = _parse_datetime(art_date_str)
    except Exception:
        return "L"

    if not dt_start or not dt_end or not dt_art:
        return "L"

    duration = (dt_end - dt_start).total_seconds()
    if duration <= 0:
        return "H"  # Single day point

    if dt_art >= dt_end:
        # Article is after the end date?
        # Usually end_date is the Alert Date. Articles should be <= Alert Date.
        # But if it's very close, it's High Proximity.
        return "H"

    if dt_art < dt_start:
        return "L"

    elapsed = (dt_art - dt_start).total_seconds()
    ratio = elapsed / duration

    if ratio >= 0.66:
        return "H"
    if ratio >= 0.33:
        return "M"
    return "L"


def calculate_p3(theme_str: str) -> str:
    """
    Calculate P3 (Theme Importance) Score.
    Based on predefined lists of market-moving themes.
    """
    if not theme_str:
        return "L"

    theme = theme_str.upper()

    # High Priority Themes (Direct Financial/Strategic Impact)
    high_themes = [
        "EARNINGS_ANNOUNCEMENT",
        "M_AND_A",
        "DIVIDEND_CORP_ACTION",
        "PRODUCT_TECH_LAUNCH",
        "COMMERCIAL_CONTRACTS",
    ]

    # Medium Priority Themes (Operational/Governance)
    med_themes = [
        "LEGAL_REGULATORY",
        "EXECUTIVE_CHANGE",
        "OPERATIONAL_CRISIS",
        "CAPITAL_STRUCTURE",
        "MACRO_SECTOR",
        "ANALYST_OPINION",
    ]

    for t in high_themes:
        if t in theme:
            return "H"
    for t in med_themes:
        if t in theme:
            return "M"

    return "L"
