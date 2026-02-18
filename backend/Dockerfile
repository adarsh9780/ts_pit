FROM python:3.12.10-slim

# Install uv (The fast Python package manager)
COPY --from=docker.io/astral/uv:latest /uv /uvx /bin/

WORKDIR /app

# Configure uv to compile bytecode and ensure we use the virtual env
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Copy dependency definitions and local libraries
COPY pyproject.toml uv.lock ./
COPY libs ./libs
COPY README.md ./

# Install dependencies
RUN uv sync --frozen --no-install-project

COPY src ./src
COPY main.py config.yaml .env* ./

# --- Safe Runner Environment Setup ---
# Create a separate virtual environment for the runner
RUN uv venv /runner-venv

# Install runner dependencies into this isolated environment
# We install standard data science libs here so the runner has them available
RUN uv pip install --python /runner-venv/bin/python RestrictedPython pandas numpy requests beautifulsoup4 yfinance
# -------------------------------------

CMD ["uv", "run", "uvicorn", "ts_pit.main:app", "--host", "0.0.0.0", "--port", "8000"]