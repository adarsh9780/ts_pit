# Database Schema & Data Requirements

This document outlines the required database schema, data types, and formatting standards for the Financial Alerts Dashboard. The application uses a SQLite database.

## General Requirements

-   **Database Type**: SQLite 3
-   **File Name**: `alerts.db` (default, configurable)
-   **Date Format**: All dates **MUST** be stored as text strings in ISO 8601 format (`YYYY-MM-DD`).
    -   ✅ Correct: `2023-12-25`
    -   ❌ Incorrect: `25-12-2023`, `2023/12/25`, `Dec 25, 2023`
-   **Text Encoding**: UTF-8
-   **Column Names**: The application configuration matches column names **case-sensitively**. Please ensure column names match exactly as specified below.

---

## 1. Table: `alerts`

Contains the core financial alerts that drive the dashboard.

| Column Name | Data Type | Required | Description | Sample Data |
| :--- | :--- | :--- | :--- | :--- |
| `Alert ID` | TEXT | **Yes** | Unique identifier for the alert. Used in URLs. | `ALT-2024-001` |
| `Ticker` | TEXT | **Yes** | Stock ticker symbol. | `NVDA` |
| `ISIN` | TEXT | **Yes** | International Securities Identification Number. **CRITICAL**: Used to link to articles. Must match exactly. | `US67066G1040` |
| `status` | TEXT | **Yes** | Workflow status. Default canonical values: `NEEDS_REVIEW`, `ESCALATE_L2`, `DISMISS` (aliases can be configured). | `NEEDS_REVIEW` |
| `Alert date` | TEXT | Yes | Date the alert was generated (`YYYY-MM-DD`). Used for filtering. | `2024-01-15` |
| `Start date` | TEXT | Yes | Start of the relevant analysis period (`YYYY-MM-DD`). | `2023-12-15` |
| `End date` | TEXT | Yes | End of the relevant analysis period (`YYYY-MM-DD`). | `2024-01-15` |
| `Instrument Name` | TEXT | No | Full name of the company or instrument. | `NVIDIA Corporation` |
| `trade type` | TEXT | No | Type of trade (e.g., Buy, Sell). | `Buy` |
| `Sum of buy quantity`| INTEGER | No | Total quantity bought. | `5000` |
| `Sum of sell quantity`| INTEGER | No | Total quantity sold. | `0` |

### Critical Constraints
1.  **ISIN Linking**: The `ISIN` field corresponds to the `isin` field in the `articles` table. Truncated or whitespace-padded ISINs will break news fetching.
2.  **Date Logic**: `End date` must be greater than or equal to `Start date`.

---

## 2. Table: `articles`

Contains news articles related to the alerts.

| Column Name | Data Type | Required | Description | Sample Data |
| :--- | :--- | :--- | :--- | :--- |
| `art_id` | TEXT | **Yes** | Unique identifier for the article. | `news-abc-123` |
| `isin` | TEXT | **Yes** | **Foreign Key**: Matches `ISIN` in `alerts` table. | `US67066G1040` |
| `art_created_date`| TEXT | **Yes** | Publication date (`YYYY-MM-DD`). Used to filter news relevant to the alert window. | `2024-01-10` |
| `art_title` | TEXT | No | Headline of the article. | `Nvidia announces new AI chip` |
| `art_summary` | TEXT | No | Short summary or body text. | `The company revealed...` |
| `sentiment` | TEXT | No | Sentiment analysis string. Recommended format: `Label: Explanation`. | `Bullish: Strong growth.` |
| `theme` | TEXT | No | Topic/Theme of the article. | `M_AND_A` |
| `Materiality` | TEXT | No | Materiality score code (e.g., HHH, HML). Used for coloring. | `HHH` |

### Critical Constraints
1.  **Date Filtering**: The dashboard only displays articles where `art_created_date` is between the Alert's `Start date` and `End date`. **Articles outside this range will be hidden.**
2.  **Case Sensitivity**: Ensure the column is named `isin` (lowercase) as per default config, or update the config to match DB. Ideally, standardize on lowercase `isin` for this table.

---

## 3. Table: `prices`

Contains historical price data. This table is often populated automatically by the application (via yFinance), but can be pre-filled.

| Column Name | Data Type | Required | Description | Sample Data |
| :--- | :--- | :--- | :--- | :--- |
| `ticker` | TEXT | **Yes** | Stock ticker symbol. | `NVDA` |
| `date` | TEXT | **Yes** | Date of the price point (`YYYY-MM-DD`). | `2024-01-15` |
| `opening price` | REAL | Yes | Opening price. | `540.20` |
| `closing price` | REAL | Yes | Closing price. | `545.50` |
| `volume` | INTEGER | Yes | Trading volume. | `1500000` |
| `industry` | TEXT | No | Industry name (used for sector comparison line). | `Semiconductors` |

### Critical Constraints
1.  **Composite Key**: The combination of `ticker` and `date` must be unique.
