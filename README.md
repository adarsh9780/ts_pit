# Financial Alerts Dashboard

An alert-triage platform for compliance analysts to investigate suspicious trading activity using
alert metadata, market data, linked public news, and AI-assisted reasoning.

## Canonical Documentation

Use only these two docs as source of truth:

1. Business methodology:
   - `artifacts/BUSINESS_METHODOLOGY.md`
2. Technical implementation:
   - `artifacts/TECHNICAL_IMPLEMENTATION.md`

## Quick Start

1. Install backend and frontend dependencies:
   ```bash
   uv sync
   cd frontend && npm install
   ```
2. Validate schema and mappings for the configured DB:
   ```bash
   uv run scripts/validate_schema.py
   ```
3. Start backend:
   ```bash
   uv run main.py
   ```
4. Start frontend:
   ```bash
   cd frontend && npm run dev
   ```

## Configuration

Edit `config.yaml` to map your database tables/columns.

Minimal alert mapping example:

```yaml
database:
  path: "./alerts.db"

tables:
  alerts:
    name: "alerts"
    columns:
      id: "Alert ID"
      ticker: "Ticker"
      status: "status"
      isin: "ISIN"
```
