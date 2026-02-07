# AI Recommendation Logic (Operational Contract)

This document defines the current recommendation contract for the dashboard.
It is the canonical reference for recommendation labels and decision intent.

---

## 1. Canonical Recommendation Labels

Use only these values for system recommendations:

- `DISMISS`: Market move appears justified by public information, or impact is noise.
- `ESCALATE_L2`: Suspicious or unexplained behavior requiring deeper review.
- `NEEDS_REVIEW`: Insufficient/conflicting evidence or technical/data-quality blockers.

> Note: Historical labels (`REJECT`, `APPROVE L2`, `Approve the alert`, `Dismiss the alert`) are legacy vocabulary and should be treated as transitional aliases only.

---

## 2. Core Methodology

The recommendation is based on a justification test:

1. **Market Impact**: Was the move statistically abnormal?
2. **News Materiality**: Is there high-quality public evidence that explains direction and magnitude?

### Decision Matrix

| Scenario | Impact | Evidence Quality | System Recommendation |
| :--- | :--- | :--- | :--- |
| Move explained by material public news | High | High | `DISMISS` |
| High impact with weak/no explanatory news | High | Low/None | `ESCALATE_L2` |
| No significant market abnormality | Low | Any | `DISMISS` |
| Missing/conflicting key evidence | Unknown | Unknown | `NEEDS_REVIEW` |

---

## 3. Data Flow (Current Implementation)

1. Backend loads alert context + linked articles in the alert window.
2. Impact score and materiality context are assembled for selected articles.
3. LLM returns structured narrative + recommendation.
4. Recommendation and reason are stored on the alert record.

---

## 4. Prompt Contract (Required)

The recommendation output must map to exactly one of:

- `DISMISS`
- `ESCALATE_L2`
- `NEEDS_REVIEW`

Recommendation reason should include explicit evidence (scores, dates, and article-level linkage), not generic prose.

---

## 5. UI Semantics

- Green: `DISMISS`
- Red: `ESCALATE_L2`
- Amber/Neutral: `NEEDS_REVIEW`

Analyst workflow status is separate from system recommendation.

---

## 6. Change Control

Any change to recommendation labels, thresholds, or mapping logic must be reflected in:

- `backend/prompts.py`
- `backend/schemas.py`
- `backend/llm.py`
- `frontend/src/components/alert/AlertSummary.vue`
- this document
