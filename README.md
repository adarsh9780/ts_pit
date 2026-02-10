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

## Frontend Build Artifacts

The frontend production build is emitted to `backend/static` and should be generated during build/release, not tracked in Git.

Create backend-served frontend assets:

```bash
cd frontend && npm run build:backend-static
```

Prepare backend release artifacts (API client + static assets):

```bash
cd frontend && npm run prepare:backend
```

## Export OpenAPI Contract

Generate the current FastAPI contract as JSON:

```bash
uv run scripts/export_openapi.py --output openapi.json
```

Generate YAML instead:

```bash
uv run scripts/export_openapi.py --output openapi.yaml
```

Generate frontend API client from the OpenAPI contract:

```bash
cd frontend && npm run generate:api
```

This creates a generated JavaScript client under `frontend/src/api/generated`.

## Backend Tests

Run backend non-LLM unit tests:

```bash
uv run python -m unittest discover -s tests -p 'test_*.py'
```

## Agent V2 Python Runtime (Isolated DS Env)

`execute_python` in `agent_v2` uses a separate interpreter so data-science packages stay out of the main app environment.

1. Configure packages in `config.yaml`:

```yaml
agent_v2:
  python_exec:
    enabled: true
    venv_path: "~/.ts_pit/safe_py_runner/.venv"
    auto_create_venv: false
    packages:
      - numpy
      - pandas
      - polars
      - duckdb
      - scikit-learn
      - statsmodels
      - plotly
```

2. One-liner setup:

```bash
uv run python scripts/setup_safe_py_runner_env.py
```

This creates/updates the isolated runner venv and installs the configured `packages` there.

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
