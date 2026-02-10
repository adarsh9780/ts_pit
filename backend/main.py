from __future__ import annotations

import aiosqlite
import os
from contextlib import asynccontextmanager
from importlib import import_module
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from .api.routers import (
    agent_router,
    alerts_router,
    market_router,
    reports_router,
    settings_router,
)
from .config import get_config
from .db import validate_required_schema
from .llm import get_llm_model
from .logger import init_logger, logprint
from .agent_v2.python_env import ensure_python_runtime


config = get_config()
init_logger()


def _load_agent_workflow():
    mode = config.get_agent_mode()
    module_name = ".agent.graph" if mode == "v1" else ".agent_v2.graph"
    try:
        module = import_module(module_name, package=__package__)
    except Exception as e:
        raise RuntimeError(
            f"Failed to load configured agent mode '{mode}' from {module_name}: {e}"
        ) from e

    workflow = getattr(module, "workflow", None)
    if workflow is None:
        raise RuntimeError(
            f"Configured agent mode '{mode}' does not expose 'workflow' in {module_name}"
        )
    return workflow, mode


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

    missing_schema = validate_required_schema(config=config)
    if missing_schema:
        joined = ", ".join(missing_schema)
        raise RuntimeError(
            "Database schema validation failed. Missing required tables/columns: "
            f"{joined}. Apply migrations/schema setup before starting the app."
        )

    logprint("Initializing LLM model...")
    app.state.llm = get_llm_model()

    if config.get_agent_mode() == "v2":
        py_exec_cfg = config.get_agent_v2_python_exec_config()
        if py_exec_cfg.get("enabled", False):
            py_exec_path = ensure_python_runtime(py_exec_cfg)
            logprint(
                "Validated agent_v2 python runtime",
                python_executable=str(py_exec_path),
            )

    db_path = Path.home() / ".ts_pit" / "agent_memory.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    logprint("Initializing agent memory", db_path=str(db_path))

    workflow, agent_mode = _load_agent_workflow()
    logprint("Selected agent runtime", mode=agent_mode)

    async with aiosqlite.connect(db_path) as conn:
        app.state.agent_params = {"conn": conn}
        checkpointer = AsyncSqliteSaver(conn)
        app.state.agent = workflow.compile(checkpointer=checkpointer)
        app.state.agent_mode = agent_mode
        yield

    logprint("Application shutdown complete")


app = FastAPI(lifespan=lifespan)


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
