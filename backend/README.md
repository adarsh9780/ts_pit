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
   Or use grouped runner:
   ```bash
   uv run scripts/schema_ops.py validate-schema
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

## Script Categories

Utilities under `scripts/` are grouped by task type. Use one of:

- `uv run scripts/db_ops.py <operation>`
- `uv run scripts/scoring_ops.py <operation>`
- `uv run scripts/schema_ops.py <operation>`
- `uv run scripts/dev_checks.py <operation>`
- `uv run scripts/data_ops.py <operation>`

Or use the unified CLI:

```bash
uv run scripts/cli.py <category> <operation> [args...]
```

Examples:

```bash
uv run scripts/cli.py db migrate-statuses --dry-run
uv run scripts/cli.py schema export-openapi --output openapi.yaml
uv run scripts/cli.py scoring calc-impact-scores --calc-all
```

## Backend Tests

Run backend non-LLM unit tests:

```bash
uv run python -m unittest discover -s tests -p 'test_*.py'
```

## Agent V2 Python Runtime (Isolated DS Env)

`execute_python` in `agent_v2` uses a separate interpreter so data-science packages stay out of the main app environment.

1. Configure runner executable path in `config.yaml`:

```yaml
agent_v2:
  safe_py_runner:
    enabled: true
    # Windows/VDI example:
    # venv_path: "C:/Users/<you>/ds/.virtualenvs/safe_py_runner/.venv/Scripts/python.exe"
    # Linux/macOS example:
    # venv_path: "~/.ts_pit/safe_py_runner/.venv/bin/python"
    venv_path: "~/.ts_pit/safe_py_runner/.venv/bin/python"
    required_imports:
      - RestrictedPython
```

2. Health check:

```bash
uv run python scripts/check_safe_py_runner_env.py
```

This prints runtime diagnostics (runner path + import validation)
and exits non-zero if the runner environment is not ready.

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

## Langfuse Observability

Langfuse tracing is now wired into model calls and is opt-in.

1. Install backend deps:
   ```bash
   uv sync
   ```
2. Enable Langfuse in environment:
   ```bash
   LANGFUSE_ENABLED=true
   LANGFUSE_HOST=http://localhost:3000
   LANGFUSE_PUBLIC_KEY=pk_...
   LANGFUSE_SECRET_KEY=sk_...
   ```
3. Optional local unauth mode (self-hosted only):
   ```bash
   LANGFUSE_ALLOW_UNAUTH=true
   ```

If Langfuse is not configured or unavailable, the app continues normally without tracing.
