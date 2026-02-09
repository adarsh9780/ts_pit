from __future__ import annotations

import aiosqlite
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from .agent.graph import workflow
from .api.routers import (
    agent_router,
    alerts_router,
    market_router,
    reports_router,
    settings_router,
)
from .config import get_config
from .database import get_db_connection
from .llm import get_llm_model
from .logger import init_logger, logprint


config = get_config()
init_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    proxy_config = config.get_proxy_config()
    if proxy_config.get("http"):
        os.environ["HTTP_PROXY"] = proxy_config["http"]
        logprint("Proxy configured: HTTP_PROXY set", proxy=proxy_config["http"])
    if proxy_config.get("https"):
        os.environ["HTTPS_PROXY"] = proxy_config["https"]
        logprint("Proxy configured: HTTPS_PROXY set", proxy=proxy_config["https"])
    if proxy_config.get("no_proxy"):
        os.environ["NO_PROXY"] = proxy_config["no_proxy"]
        logprint("Proxy bypass configured", no_proxy=proxy_config["no_proxy"])

    logprint("Initializing LLM model...")
    app.state.llm = get_llm_model()

    db_path = Path.home() / ".ts_pit" / "agent_memory.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    logprint("Initializing agent memory", db_path=str(db_path))

    async with aiosqlite.connect(db_path) as conn:
        app.state.agent_params = {"conn": conn}
        checkpointer = AsyncSqliteSaver(conn)
        app.state.agent = workflow.compile(checkpointer=checkpointer)
        yield

    logprint("Application shutdown complete")


app = FastAPI(lifespan=lifespan)


def run_migrations():
    conn = get_db_connection()
    cursor = conn.cursor()

    table_name = config.get_table_name("alerts")
    cursor.execute(f'PRAGMA table_info("{table_name}")')
    columns = [row["name"] for row in cursor.fetchall()]

    new_cols = {
        "narrative_theme": "TEXT",
        "narrative_summary": "TEXT",
        "summary_generated_at": "TEXT",
        "bullish_events": "TEXT",
        "bearish_events": "TEXT",
        "neutral_events": "TEXT",
        "recommendation": "TEXT",
        "recommendation_reason": "TEXT",
    }

    for col, dtype in new_cols.items():
        if col not in columns:
            logprint("Migration adding column", table=table_name, column=col, dtype=dtype)
            cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{col}" {dtype}')

    status_col = config.get_column("alerts", "status")
    default_status = config.get_valid_statuses()[0]
    if status_col not in columns:
        logprint(
            "Migration adding status column",
            table=table_name,
            column=status_col,
            default_status=default_status,
        )
        default_status_sql = default_status.replace("'", "''")
        cursor.execute(
            f'ALTER TABLE "{table_name}" ADD COLUMN "{status_col}" TEXT DEFAULT \'{default_status_sql}\''
        )
    cursor.execute(
        f'UPDATE "{table_name}" SET "{status_col}" = ? WHERE "{status_col}" IS NULL OR TRIM("{status_col}") = ""',
        (default_status,),
    )

    articles_table = config.get_table_name("articles")
    cursor.execute(f'PRAGMA table_info("{articles_table}")')
    art_columns = [row["name"] for row in cursor.fetchall()]

    new_art_cols = {
        config.get_column("articles", "impact_score"): "REAL",
        config.get_column("articles", "impact_label"): "TEXT",
        config.get_column("articles", "ticker"): "TEXT",
        config.get_column("articles", "instrument_name"): "TEXT",
    }

    for col, dtype in new_art_cols.items():
        if col and col not in art_columns:
            logprint("Migration adding article column", table=articles_table, column=col, dtype=dtype)
            cursor.execute(f'ALTER TABLE "{articles_table}" ADD COLUMN "{col}" {dtype}')

    themes_table = config.get_table_name("article_themes")
    articles_id_col = config.get_column("articles", "id")
    art_id_col = config.get_column("article_themes", "art_id")
    theme_col = config.get_column("article_themes", "theme")
    summary_col = config.get_column("article_themes", "summary")
    analysis_col = config.get_column("article_themes", "analysis")

    cursor.execute(
        f'''
        CREATE TABLE IF NOT EXISTS "{themes_table}" (
            "{art_id_col}" TEXT PRIMARY KEY,
            "{theme_col}" TEXT,
            "{summary_col}" TEXT,
            "{analysis_col}" TEXT,
            FOREIGN KEY("{art_id_col}") REFERENCES "{articles_table}"("{articles_id_col}")
        )
    '''
    )

    p1_col = config.get_column("article_themes", "p1_prominence")
    cursor.execute(f'PRAGMA table_info("{themes_table}")')
    theme_columns = [row["name"] for row in cursor.fetchall()]
    if p1_col not in theme_columns:
        logprint("Migration adding p1 prominence column", table=themes_table, column=p1_col)
        cursor.execute(f'ALTER TABLE "{themes_table}" ADD COLUMN "{p1_col}" TEXT')

    conn.commit()
    conn.close()


run_migrations()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = request.headers.get("x-request-id", "-")
    logprint(
        "Request validation error",
        level="ERROR",
        request_id=request_id,
        path=str(request.url),
        errors=exc.errors(),
        body=exc.body,
    )
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": str(exc.body)},
    )


app.include_router(settings_router)
app.include_router(alerts_router)
app.include_router(market_router)
app.include_router(agent_router)
app.include_router(reports_router)


STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists() and (STATIC_DIR / "index.html").exists():
    app.mount("/ui/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/ui")
    @app.get("/ui/{path:path}")
    async def serve_frontend(path: str = ""):
        file_path = STATIC_DIR / path
        if path and file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(STATIC_DIR / "index.html")

