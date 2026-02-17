# Technical Implementation Guide

## 1. Scope

This document is the implementation source of truth for junior and mid-level developers working
on this repository.

It explains:

1. Runtime architecture.
2. Database contracts and mapping rules.
3. Alert summary pipeline (`Analyze with AI`).
4. Scoring and materiality implementation.
5. Migration/operational scripts.
6. Common failure modes and runbook steps.

## 2. Runtime Architecture

## 2.1 Components

1. Backend:
   - FastAPI app in `backend/main.py`.
   - Configuration and mapping in `backend/config.py`.
   - LLM normalization and validation in `backend/llm.py`.
   - Scoring helpers in `backend/scoring.py`.
2. Frontend:
   - Vue app in `frontend/src`.
   - Primary detail workflow in `frontend/src/views/AlertDetail.vue`.
3. Database:
   - SQLite DB configured by `config.yaml`.
   - Table and column names are mapped (not hardcoded) through config.

## 2.2 Request flow (high level)

1. Frontend loads `/config`.
2. Frontend loads `/alerts`.
3. On alert click:
   - `/alerts/{id}` for detail,
   - prices/news calls for visual context.
4. On `Analyze with AI`:
   - `POST /alerts/{id}/summary`.

## 3. Data Contracts

## 3.1 Canonical recommendation enum

Accepted recommendation values:

1. `DISMISS`
2. `ESCALATE_L2`
3. `NEEDS_REVIEW`

Legacy aliases may appear from old data or prompts, but runtime normalization must map them to
this enum before persistence.

## 3.2 Status values

Configured valid status values are read from `config.yaml` and validated by backend config logic.

Default canonical set:

1. `NEEDS_REVIEW`
2. `ESCALATE_L2`
3. `DISMISS`

## 3.3 Core DB fields used by summary generation

Minimum fields required by summary generation path:

1. Alert:
   - id,
   - trade type,
   - start_date,
   - end_date,
   - execution timestamp (preferred) or fallback end_date.
2. Article:
   - article id,
   - title/summary/body context,
   - `created_date` (required for deterministic causality gate),
   - impact score and thematic fields as available.

## 4. Analyze-with-AI Pipeline

Primary endpoint: `POST /alerts/{alert_id}/summary` in `backend/main.py`.

## 4.1 Pipeline stages

1. Read alert row and alert window context.
2. Query linked articles (mapped columns).
3. Build article payload list for policy and LLM.
4. Run deterministic gates first.
5. If no deterministic override, run LLM summary.
6. Persist summary fields and recommendation.

## 4.2 Deterministic gate policy

Gate function:

`_run_deterministic_summary_gates(...)`

Deterministic checks:

1. Data readiness:
   - Missing core fields -> `NEEDS_REVIEW`.
2. Article timestamp validity:
   - Any invalid/missing article timestamp -> `NEEDS_REVIEW`.
3. Causality:
   - Keep only `article.created_date <= trade_timestamp` as justifying evidence.
4. No pre-trade evidence:
   - If high-impact exists without valid pre-trade news -> `ESCALATE_L2`.
   - Otherwise -> `NEEDS_REVIEW`.

## 4.3 Important regression guard

When building article payload, always include:

1. `created_date`
2. `impact_score`
3. `materiality`
4. text fields used by LLM output generation

If `created_date` is omitted from payload, deterministic gates will force timestamp failure and
degrade recommendation quality.

## 5. Scoring and Materiality

Canonical reconstruction spec:

- `artifacts/SCORING_METHODOLOGY.md` (formulas, thresholds, edge-case handling, and worked examples)

## 5.1 Impact score model

Implementation source:

`scripts/calc_impact_scores.py`

Method:

1. Build 10-day hourly baseline before article publication timestamp.
2. Compute hourly returns:
   - `r_i = (close_i - open_i) / open_i`
3. Compute baseline volatility:
   - `sigma = std(r_i)`
4. Event return:
   - first hourly candle at or after publication timestamp.
5. Impact score:
   - `Z = abs(r_event) / sigma`
6. Label thresholds:
   - `Z < 2.0` -> `Low`
   - `2.0 <= Z < 4.0` -> `Medium`
   - `Z >= 4.0` -> `High`

## 5.2 Materiality triplet

Triplet format:

`P1P2P3`

1. P1:
   - entity prominence (`article_themes.p1_prominence`).
2. P2:
   - temporal proximity to alert window (`calculate_p2`).
3. P3:
   - thematic tier (`calculate_p3` in `backend/scoring.py`).

Theme tier mapping is enforced in `backend/scoring.py`.

## 5.3 Column ownership rule

Canonical ownership:

1. `p1_prominence` lives in `article_themes`.
2. `articles.p1_prominence` is not authoritative and should not be used.

Startup/schema logic must ensure `article_themes.p1_prominence` exists.

## 6. Config Behavior and Feature Flags

## 6.1 Materiality availability

`has_materiality` in `/config` must be derived dynamically from:

1. config mapping presence, and
2. actual DB column availability.

Do not hardcode this flag.

## 6.2 Mapping safety

All SQL paths should use mapped table/column names from config helpers, not literal hardcoded names.

## 7. Migration and Utility Scripts

Common scripts:

1. `scripts/validate_schema.py`
   - checks configured DB compatibility.
2. `scripts/calc_impact_scores.py`
   - computes impact score and labels.
3. `scripts/calc_prominence.py`
   - computes/stores P1 prominence.
4. `scripts/remove_articles_p1_prominence.py`
   - optional cleanup: drops `articles.p1_prominence` if present.
5. `scripts/migrate_statuses.py`
   - status normalization.
6. `scripts/migrate_impact_labels.py`
   - historical label normalization (legacy -> `Low/Medium/High`).
7. `scripts/verify_impact_labels.py`
   - post-migration verification.
8. `scripts/test_p3_mapping.py`
   - policy test for P3 tier mapping.

## 8. Safe Rollout Guidance (Large DBs)

For larger DBs (e.g., 20k+ article rows):

1. Always run migration scripts in dry-run mode first (if supported).
2. Capture before/after label/status distributions.
3. Execute migrations in single-purpose steps (status, labels, schema, scoring).
4. Recompute expensive scores only when formula/inputs changed.
5. Keep DB backup until verification checks pass.

## 9. Troubleshooting Runbook

## 9.1 Symptom: Alert click loads list but no detail chart/news

Check:

1. Browser network tab for `/alerts/{id}` request.
2. Backend logs for 404 on that alert id.
3. ID-shape mapping from alert list row to detail route.

## 9.2 Symptom: Summary always returns `NEEDS_REVIEW`

Check deterministic gate inputs:

1. alert timestamps present and parseable,
2. trade_type/start_date/end_date present,
3. each article payload includes valid `created_date`.

## 9.3 Symptom: SQLite migration errors like duplicate column

Cause:

Migration attempted to add an already-existing column.

Action:

1. verify column existence via pragma,
2. make migration idempotent,
3. rerun.

## 10. Developer Change Checklist

For any change to recommendation/scoring policy:

1. Update runtime code:
   - prompts, schemas, normalization, deterministic gates.
2. Update frontend expectation/rendering.
3. Update this doc and business methodology doc.
4. Add or update verification script/test.
5. Validate on local dummy DB and VDI-like schema.
