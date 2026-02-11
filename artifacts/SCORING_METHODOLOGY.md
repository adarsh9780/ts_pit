# Scoring Methodology (Canonical)

## 1. Purpose

This document is the canonical methodology for reconstructing:

1. `impact_score` / `impact_label`
2. materiality triplet `P1P2P3`

It is written so an agent can recompute results on demand using SQL/Python tools.

## 2. Inputs and Source-of-Truth Fields

Use mapped physical columns from `config.yaml` (do not hardcode names).

Required logical fields:

1. Alerts:
   - `id`, `isin`, `start_date`, `end_date`
2. Articles:
   - `id`, `isin`, `created_date`, `theme`, `impact_score`, `impact_label`
3. Article themes:
   - `art_id`, `theme`, `p1_prominence`
4. Hourly prices:
   - `ticker`, `date`, `open`, `close`

Field precedence rules:

1. P1 source is `article_themes.p1_prominence` only (default `L` if missing).
2. Theme source for P3:
   - use `article_themes.theme` when present and not placeholder `"string"`;
   - otherwise fallback to `articles.theme`;
   - if still missing, use `"UNCATEGORIZED"`.

## 3. Impact Score (Z-Score)

Implementation reference: `scripts/calc_impact_scores.py`.

For each article:

1. Parse article timestamp `t_art` from `articles.created_date`.
2. Build baseline window:
   - `t_start = t_art - 10 days`
   - `t_end = t_art`
3. Pull hourly candles in `[t_start, t_end]` for the article ticker.
4. Compute hourly return for each candle:
   - `r_i = (close_i - open_i) / open_i`
5. Baseline volatility:
   - `sigma = std(r_i)`
6. Event candle:
   - first candle where `candle_time >= t_art`
7. Event return:
   - `r_event = (close_event - open_event) / open_event`
8. Impact score:
   - `Z = abs(r_event) / sigma`
9. Label bands:
   - `Z < 2.0` => `Low`
   - `2.0 <= Z < 4.0` => `Medium`
   - `Z >= 4.0` => `High`

Edge handling:

1. If fewer than 10 baseline candles: no score (`None`), reason `Insufficient Data`.
2. If `sigma` is zero or NaN: score `0`, label `Flatline`.
3. If no event candle: no score, reason `No Price Data`.

## 4. Materiality Triplet (`P1P2P3`)

Materiality is a string concatenation:

`materiality = P1 + P2 + P3`

### 4.1 P1 (Prominence)

Value from `article_themes.p1_prominence` (`H`/`M`/`L`).
Default to `L` when null/unavailable.

### 4.2 P2 (Proximity to Alert Window)

Implementation reference: `backend/scoring.py::calculate_p2`.

Inputs:

1. article timestamp: `t_art`
2. alert window start: `t_start`
3. alert window end: `t_end`

Rules:

1. If any date missing/unparseable => `L`
2. If `t_end <= t_start` => `H` (single-point/degenerate window)
3. If `t_art >= t_end` => `H`
4. If `t_art < t_start` => `L`
5. Else compute:
   - `ratio = (t_art - t_start) / (t_end - t_start)`
   - `ratio >= 0.66` => `H`
   - `0.33 <= ratio < 0.66` => `M`
   - `ratio < 0.33` => `L`

Accepted date formats must include:

1. `YYYY-MM-DD`
2. `YYYY-MM-DD HH:MM:SS`
3. timezone-aware forms (e.g., `YYYY-MM-DD HH:MM:SS+00:00`, `...Z`)

Timezone normalization rule:

1. Convert aware datetimes to UTC and compare as naive UTC.

### 4.3 P3 (Theme Importance)

Implementation reference: `backend/scoring.py::calculate_p3`.

`H` themes (substring match, case-insensitive):

1. `EARNINGS_ANNOUNCEMENT`
2. `M_AND_A`
3. `DIVIDEND_CORP_ACTION`
4. `PRODUCT_TECH_LAUNCH`
5. `COMMERCIAL_CONTRACTS`

`M` themes:

1. `LEGAL_REGULATORY`
2. `EXECUTIVE_CHANGE`
3. `OPERATIONAL_CRISIS`
4. `CAPITAL_STRUCTURE`
5. `MACRO_SECTOR`
6. `ANALYST_OPINION`

All others => `L`.

## 5. Worked Example (User-Facing Bug Class)

Given:

1. `start_date = 2025-08-15`
2. `end_date = 2025-08-29`
3. `created_date = 2025-08-28 00:39:05+00:00`
4. `P1 = L`
5. theme maps to `P3 = M`

P2 calculation:

1. ratio is in final third of window => `P2 = H`

Final materiality:

1. `LHM` (not `LLM`)

## 6. Operational Guidance for On-Demand Recompute

For an alert-level recomputation:

1. Load alert (`isin`, `start_date`, `end_date`).
2. Load linked articles by `isin` within desired window.
3. Join `article_themes` on article id for P1/P3 input enrichment.
4. Recompute P2 and P3 deterministically in Python if SQL date parsing is brittle.
5. Recompute impact Z-score from hourly candles only if explicitly requested.
6. Do not persist unless user asks to backfill/update DB.

For consistency checks:

1. Compare recomputed vs stored values.
2. Report mismatches with `article_id`, original value, recomputed value, and reason.

## 7. Versioning

Methodology version: `v1.0`

Any threshold/rule changes must bump version and include:

1. rationale,
2. migration/backfill plan,
3. validation summary.
