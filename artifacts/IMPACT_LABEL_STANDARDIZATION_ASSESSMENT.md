# Impact Label Standardization Assessment

Goal:
- Standardize impact labels to `Low | Medium | High`
- Preserve existing numeric thresholds:
  - `Z < 2.0`
  - `2.0 <= Z < 4.0`
  - `Z >= 4.0`

Current legacy labels:
- `Noise | Significant | Extreme`

Proposed mapping:
- `Noise -> Low`
- `Significant -> Medium`
- `Extreme -> High`

---

## 1. Where Changes Are Required

### A) Scoring producer (writes impact_label)
- File: `scripts/calc_impact_scores.py`
- Current behavior: writes `Noise/Significant/Extreme`
- Required change: write `Low/Medium/High`
- Consequence: all newly calculated rows use new vocabulary.

### B) Frontend badge styling (depends on label text)
- File: `frontend/src/components/alert/AlertNews.vue`
- Current behavior: CSS classes for `.noise`, `.significant`, `.extreme`
- Required change:
  - Add/replace classes for `.low`, `.medium`, `.high`
  - Optionally keep legacy classes as aliases during transition
- Consequence: without this, badges may lose expected color styling.

### C) Config and schema docs
- File: `config.yaml`
- Current comment: "High/Medium/Low/Noise" (mixed vocabulary)
- Required change: update comment to canonical `Low/Medium/High` and mention legacy mapping.
- Consequence: reduces confusion for operators and future integrations.

- File: `backend/agent/db_schema.yaml`
- Current description/example still references `Noise` in examples.
- Required change: align description/examples to `Low/Medium/High`.
- Consequence: agent context remains consistent with live data semantics.

### D) Agent and prompt text references
- File: `backend/agent/tools.py`
- Current docstring says High/Medium/Low already.
- Required change: verify wording matches final canonical order and examples.
- Consequence: low risk (documentation-level consistency).

- File: `backend/agent/prompts.py`
- Current wording references "significant" threshold.
- Required change: keep threshold wording as-is or explicitly map to Medium/High language.
- Consequence: moderate wording drift risk if not aligned with UI labels.

### E) Historical data in database
- Data affected: `articles.impact_label`
- Required change options:
  1. Backfill existing values with SQL update.
  2. Runtime alias mapping (read-time normalization).
  3. Both (recommended: alias first, backfill later).
- Consequence:
  - Without migration/aliasing, mixed labels will appear in UI and analytics.

---

## 2. Runtime and Production Consequences

### If only scorer is changed (no alias/backfill)
- New rows: `Low/Medium/High`
- Old rows: `Noise/Significant/Extreme`
- Result: mixed labels across screens and grouped counts.

### If frontend CSS is not updated
- Badges may render without intended color coding for new labels.

### If analytics/grouping logic expects old labels
- Aggregations or filters may fragment into six categories.
- Monitoring dashboards may appear inconsistent.

### If backfill is done directly on large DB
- Write-heavy operation on `articles` table.
- Needs backup and controlled execution window.

---

## 3. Safe Rollout Recommendation

1. Introduce read-time alias mapping first (backward-compatible).
2. Update scorer to emit canonical labels for new computations.
3. Update frontend to support both old and new labels during transition.
4. Backfill historical labels in controlled batches.
5. Remove legacy aliases only after data and UI are fully normalized.

---

## 4. Suggested Validation Checklist

1. Run scorer on sample set; verify only `Low/Medium/High` are newly written.
2. Open alert details and confirm badge colors are correct for all three labels.
3. Run grouped count query and confirm no unexpected label variants.
4. Confirm agent tool outputs remain coherent (no mixed vocabulary confusion).

