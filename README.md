# Financial Alerts Dashboard

A tool for monitoring and investigating trade alerts with news correlation and price chart analysis.

## Key Features

- **Interactive Dashboard**: View alerts with rich metadata and status tracking.
- **Advanced Charting**: ECharts-based price performance with:
  - **Look Back Window**: Automatically highlights the alert period, smartly handling trading holidays.
  - **Volume Analysis**: Integrated volume bar chart.
  - **News Correlation**: Visual bubbles indicating news events on the timeline.
  - **Table View**: Toggle between Chart and Table views for detailed daily data analysis.
- **News Integration**: Filterable news feed with sentiment analysis and materiality scoring.
- **Detailed Insights**: Tooltips showing precise Open/Close price differences for news events.

## Quick Start

1. **Install dependencies:**
   ```bash
   uv sync
   cd frontend && npm install
   ```
   ```bash
   uv sync
   cd frontend && npm install
   ```

2. **Validate your database schema:**
   Run the schema check to ensure your database has all required tables and columns:
   ```bash
   uv run scripts/validate_schema.py
   ```
   *See [SCHEMA_REQUIREMENTS.md](SCHEMA_REQUIREMENTS.md) for details.*

3. **Understanding the Scores:**
   Detailed guide on Materiality (P1/P2/P3), Impact Z-Scores, and how to use them for decision making:
   *📖 Read [SCORING_METHODOLOGY.md](SCORING_METHODOLOGY.md)*

4. **Configure your database** (see Configuration section below)

3. **Start the backend:**
   ```bash
   uv run main.py
   ```

4. **Start the frontend (development):**
   ```bash
   cd frontend && npm run dev
   ```

## Configuration

The application uses a YAML configuration file (`config.yaml`) in the project root to connect to any SQLite database. This makes it easy to use the tool with different database schemas.

### Database Path

```yaml
database:
  path: "./alerts.db"  # Relative or absolute path to your SQLite database
```

### Table and Column Mappings

Map your database's table names and column names to the expected UI fields:

```yaml
tables:
  alerts:
    name: "your_alerts_table_name"  # Actual table name in your database
    columns:
      id: "Alert ID"               # Column for unique alert ID (required)
      ticker: "Ticker"             # Column for stock ticker (required)
      status: "status"             # Column for alert status (required)
      isin: "ISIN"                 # Column for ISIN (links to news)
      # ... add other column mappings
```

### Required Columns

The following columns are **required** for each table:

**Alerts table:**
- `id` - Unique identifier for each alert
- `ticker` - Stock ticker symbol
- `status` - Current status (default canonical values: NEEDS_REVIEW/ESCALATE_L2/DISMISS)

**Articles table:**
- `id` - Unique identifier
- `isin` - Links articles to alerts
- `created_date` - Date for filtering and sorting
- `title` - Article title

**Prices table:** (auto-created if it doesn't exist)
- `ticker`, `date`, `open`, `close`, `volume`, `industry`

### Display Configuration

Control which columns appear in the alerts table and their labels:

```yaml
display:
  table_columns:
    - id
    - ticker
    - instrument_name
    - trade_type
    - alert_date
    - status

  column_labels:
    id: "Alert ID"
    ticker: "Ticker"
    # ... etc
```

### Optional Features

**Materiality Column:** If your articles table has a `materiality` column, the chart will display color-coded news event bubbles. If not present, simply leave the materiality column empty:

```yaml
tables:
  articles:
    columns:
      materiality: ""  # Leave empty to disable materiality display
```

## Example: Adapting to a New Database

1. Copy your SQLite database to the project folder (or reference it by path)

2. Edit `config.yaml`:
   ```yaml
   database:
     path: "./my_database.db"
   
   tables:
     alerts:
       name: "my_trade_alerts"
       columns:
         id: "alert_pk"
         ticker: "symbol"
         status: "alert_status"
         # ... map all your columns
   ```

3. Restart the backend server

4. The application will automatically use your database and column names

## Architecture

```
├── config.yaml          # Central configuration
├── main.py              # Entry point
├── backend/
│   ├── config.py        # Configuration loader
│   ├── database.py      # Database connection
│   └── main.py          # FastAPI endpoints
└── frontend/
    └── src/views/       # Vue components
```

## API Endpoints

- `GET /config` - Returns current configuration
- `GET /alerts` - List all alerts
- `GET /alerts/{id}` - Get alert details
- `PATCH /alerts/{id}/status` - Update alert status
- `GET /prices/{ticker}` - Get price data with sector comparison
- `GET /news/{isin}` - Get news articles for an ISIN
