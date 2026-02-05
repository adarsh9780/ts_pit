# Database Schema Requirements

To ensure the **Financial Alerts Dashboard** and its analysis scripts work correctly, your SQLite database must adhere to the following schema.

> [!IMPORTANT]
> **Use the Validation Script**: Run `uv run scripts/validate_schema.py` to automatically check your database against these requirements.

## 1. ARTICLES Table
The `articles` table is critical for the **Prominence Calculation** (P1 Score). It must contain the following columns to avoid expensive table joins.

| Column Name | Type | Required? | Description |
| :--- | :--- | :--- | :--- |
| `art_id` | TEXT | ✅ Yes | Unique identifier for the article. |
| `isin` | TEXT | ✅ Yes | ISIN code linking the article to a stock/alert. |
| `art_title` | TEXT | ✅ Yes | Headline of the news article. |
| `art_body` | TEXT | ✅ Yes | Full text or content of the article. |
| `ticker` | TEXT | ✅ Yes | **Stock Ticker** (e.g., "META"). Required for regex matching. |
| `instrument_name`| TEXT | ✅ Yes | **Company Name** (e.g., "Meta Platforms"). Required for regex matching. |
| `art_created_date`| TEXT| ✅ Yes | Publication date (YYYY-MM-DD). |

> [!NOTE]
> If your `articles` table is missing `ticker` or `instrument_name`, the `calc_prominence.py` script will fail or require a fallback join which causes data duplication issues. Please populate these columns.

## 3. ARTICLE_THEMES Table
This table stores all backend-calculated analysis, keeping the source `articles` table clean.

| Column Name | Type | Required? | Description |
| :--- | :--- | :--- | :--- |
| `art_id` | TEXT | ✅ Yes | Foreign key to `articles` table. |
| `p1_prominence`| TEXT | ✅ Yes | **calculated** P1 Score (H/M/L). |
| `narrative_theme`| TEXT | ⚠️ Rec. | AI-generated theme. |

## 4. ALERTS Table
The `alerts` table drives the main dashboard view.

| Column Name | Type | Required? | Description |
| :--- | :--- | :--- | :--- |
| `Alert ID` | TEXT | ✅ Yes | Unique ID for the alert. |
| `Ticker` | TEXT | ✅ Yes | Stock Ticker. |
| `ISIN` | TEXT | ⚠️ Rec. | Links to articles. |
| `Instrument Name`| TEXT | ⚠️ Rec. | Display name. |
| `Start date` | TEXT | ⚠️ Rec. | Start of the monitoring window. |
| `End date` | TEXT | ⚠️ Rec. | End of the monitoring window. |

## 3. Configuration
All database column names are configurable in `config.yaml`. If your columns have different names (e.g., `company_name` instead of `instrument_name`), update the mapping in `config.yaml` under the `tables` section.
