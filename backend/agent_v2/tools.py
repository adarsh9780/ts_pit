from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml
from langchain_core.tools import tool
from sqlalchemy import Text, cast, inspect, select, text

from ..alert_analysis import analyze_alert_non_persisting
from ..config import get_config
from ..database import get_db_connection, remap_row
from ..db import get_engine
from ..reporting import generate_alert_report_html, sanitize_session_id
from ..services.db_helpers import get_table
from .python_env import ensure_python_runtime
from safe_py_runner import RunnerPolicy, run_code


engine = get_engine()


def _ok(data: Any = None, message: str = "ok", **meta) -> str:
    return json.dumps(
        {"ok": True, "message": message, "data": data, "meta": meta}, default=str
    )


def _error(message: str, code: str = "TOOL_ERROR", **meta) -> str:
    return json.dumps(
        {"ok": False, "error": {"code": code, "message": message}, "meta": meta},
        default=str,
    )


def _quote_identifier(identifier: str) -> str:
    escaped = str(identifier).replace('"', '""')
    return f'"{escaped}"'


def _table_logical_to_physical_column_map(table_key: str) -> dict[str, str]:
    cfg = get_config()
    mappings: dict[str, str] = {}
    try:
        cols = cfg.get_columns(table_key)
    except Exception:
        return mappings
    for logical_name, physical_name in cols.items():
        logical = str(logical_name or "").strip()
        physical = str(physical_name or "").strip()
        if not logical or not physical:
            continue
        mappings[logical.lower()] = physical
    return mappings


def _configured_table_keys() -> list[str]:
    return ["alerts", "articles", "prices", "prices_hourly", "article_themes"]


def _table_aliases_to_keys() -> dict[str, str]:
    cfg = get_config()
    aliases: dict[str, str] = {}
    for table_key in _configured_table_keys():
        aliases[table_key.lower()] = table_key
        try:
            table_name = str(cfg.get_table_name(table_key) or "").strip()
        except Exception:
            table_name = ""
        if table_name:
            aliases[table_name.lower()] = table_key
    return aliases


def _extract_referenced_table_keys(query: str) -> list[str]:
    aliases = _table_aliases_to_keys()
    pattern = re.compile(
        r"\b(?:from|join)\s+(?:\"([^\"]+)\"|`([^`]+)`|\[([^\]]+)\]|([A-Za-z_][\w$.]*))",
        flags=re.IGNORECASE,
    )
    keys: list[str] = []
    for match in pattern.finditer(query):
        raw_token = next((g for g in match.groups() if g), "") or ""
        token = raw_token.strip().split(".")[-1].strip().lower()
        table_key = aliases.get(token)
        if table_key:
            keys.append(table_key)
    return list(dict.fromkeys(keys))


def _logical_to_physical_column_map_for_query(query: str) -> dict[str, str]:
    """
    Build a query-scoped logical->physical map.
    Only rewrite columns that resolve unambiguously across referenced tables.
    """
    table_keys = _extract_referenced_table_keys(query) or _configured_table_keys()

    candidates: dict[str, set[str]] = {}
    for table_key in table_keys:
        for logical, physical in _table_logical_to_physical_column_map(table_key).items():
            candidates.setdefault(logical, set()).add(physical)

    resolved: dict[str, str] = {}
    for logical, physical_names in candidates.items():
        if len(physical_names) == 1:
            resolved[logical] = next(iter(physical_names))
    return resolved


def _rewrite_logical_sql(query: str) -> tuple[str, bool]:
    """
    Best-effort rewrite from logical column names to physical mapped names.
    This reduces common LLM SQL errors like `WHERE id = ...`.
    """
    rewritten = query
    changed = False
    mappings = _logical_to_physical_column_map_for_query(query)

    # Replace only in unquoted segments so we don't corrupt
    # existing quoted identifiers like "Alert date".
    parts = re.split(r'(".*?(?<!\\)"|\'.*?(?<!\\)\')', query)
    for idx, part in enumerate(parts):
        if idx % 2 == 1:
            # Inside quotes -> do not rewrite.
            continue

        segment = part
        logical_names = sorted(mappings.keys(), key=len, reverse=True)
        for logical in logical_names:
            physical = mappings[logical]
            replacement = _quote_identifier(physical)
            pattern = re.compile(rf"\b{re.escape(logical)}\b", flags=re.IGNORECASE)
            segment = pattern.sub(replacement, segment)
        if segment != part:
            changed = True
            parts[idx] = segment

    rewritten = "".join(parts)
    return rewritten, changed


def _load_schema_text() -> str:
    schema_candidates = [
        Path(__file__).parent / "db_schema.yaml",
        Path(__file__).parent.parent / "agent" / "db_schema.yaml",
    ]
    for path in schema_candidates:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                schema_data = yaml.safe_load(f)
                return yaml.dump(schema_data, sort_keys=False)
    return ""


DB_SCHEMA = _load_schema_text()
PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEXT_FALLBACK_EXTENSIONS = {".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".log", ".sql", ".py"}


def list_schema_tables() -> list[dict[str, Any]]:
    """
    Non-tool helper: list configured schema tables and high-level descriptions.
    """
    if not DB_SCHEMA:
        return []
    try:
        parsed = yaml.safe_load(DB_SCHEMA) or {}
    except Exception:
        return []
    table_docs = parsed.get("tables") if isinstance(parsed, dict) else {}
    if not isinstance(table_docs, dict):
        return []

    cfg = get_config()
    rows: list[dict[str, Any]] = []
    for table_key, table_value in table_docs.items():
        if not isinstance(table_value, dict):
            continue
        try:
            physical_name = cfg.get_table_name(table_key)
        except Exception:
            physical_name = table_key
        rows.append(
            {
                "table_key": table_key,
                "table_name": physical_name,
                "description": table_value.get("description"),
            }
        )
    return rows


def list_schema_columns(table_name: str | None = None) -> list[dict[str, Any]]:
    """
    Non-tool helper: list schema columns with db names and descriptions.
    """
    if not DB_SCHEMA:
        return []
    try:
        parsed = yaml.safe_load(DB_SCHEMA) or {}
    except Exception:
        return []
    table_docs = parsed.get("tables") if isinstance(parsed, dict) else {}
    if not isinstance(table_docs, dict):
        return []

    cfg = get_config()
    alias_to_key: dict[str, str] = {}
    for key in table_docs.keys():
        alias_to_key[str(key).lower()] = str(key)
        try:
            alias_to_key[str(cfg.get_table_name(key)).lower()] = str(key)
        except Exception:
            pass

    selected_key = None
    if table_name:
        selected_key = alias_to_key.get(str(table_name).strip().lower())
        if not selected_key:
            return []

    target_keys = [selected_key] if selected_key else list(table_docs.keys())
    rows: list[dict[str, Any]] = []
    for key in target_keys:
        table_value = table_docs.get(key)
        if not isinstance(table_value, dict):
            continue
        try:
            physical_name = cfg.get_table_name(key)
        except Exception:
            physical_name = key
        columns = table_value.get("columns", {})
        if not isinstance(columns, dict):
            continue
        for logical_name, col_info in columns.items():
            if not isinstance(col_info, dict):
                continue
            rows.append(
                {
                    "table_key": key,
                    "table_name": physical_name,
                    "logical_column": logical_name,
                    "db_column": col_info.get("db_column"),
                    "type": col_info.get("type"),
                    "description": col_info.get("description"),
                }
            )
    return rows


@tool
def execute_sql(query: str) -> str:
    """
    Execute a read-only SQL query against the alerts database.

    The database schema is as follows:

    {db_schema}

    IMPORTANT:
    - Only SELECT statements are allowed.
    - Do not use PRAGMA or administrative commands.
    """
    if not query.strip().upper().startswith("SELECT"):
        return _error(
            "Only SELECT statements are allowed for security reasons.",
            code="READ_ONLY_ENFORCED",
        )

    try:
        rewritten_query, auto_rewritten = _rewrite_logical_sql(query)
        stmt = text(rewritten_query)
        with engine.connect() as conn:
            result = conn.execute(stmt)
            rows = result.fetchall()
            columns = list(result.keys())
        results = [dict(zip(columns, row)) for row in rows]
        return _ok(
            results,
            row_count=len(results),
            query_rewritten=auto_rewritten,
            executed_query=rewritten_query if auto_rewritten else query,
        )
    except Exception as e:
        msg = str(e)
        hint = ""
        if "no such column" in msg.lower():
            try:
                cfg = get_config()
                hint = (
                    " Hint: this DB uses mapped physical column names from config.yaml. "
                    f"For alerts table logical 'id', use '{cfg.get_column('alerts', 'id')}'. "
                    "Read artifacts/DB_SCHEMA_REFERENCE.yaml for table and column mappings."
                )
            except Exception:
                hint = " Hint: read artifacts/DB_SCHEMA_REFERENCE.yaml and query physical column names."
        return _error(f"Database error: {msg}{hint}", code="DB_ERROR")


execute_sql.__doc__ = execute_sql.__doc__.format(db_schema=DB_SCHEMA)


def _fs_cfg() -> dict[str, Any]:
    return get_config().get_agent_v2_filesystem_config()


def _allowed_roots() -> list[Path]:
    roots: list[Path] = []
    for item in _fs_cfg().get("allowed_dirs", []):
        raw = str(item or "").strip()
        if not raw:
            continue
        p = Path(os.path.expanduser(os.path.expandvars(raw)))
        if not p.is_absolute():
            p = (PROJECT_ROOT / p).resolve()
        else:
            p = p.resolve()
        roots.append(p)
    return roots


def _path_depth_from_root(path: Path, root: Path) -> int:
    rel = path.relative_to(root)
    return len(rel.parts) - 1


def _resolve_allowed_path(path_value: str, *, must_exist: bool) -> Path | None:
    value = str(path_value or "").strip()
    if not value:
        return None

    candidate = Path(os.path.expanduser(os.path.expandvars(value)))
    if not candidate.is_absolute():
        candidate = (PROJECT_ROOT / candidate).resolve()
    else:
        candidate = candidate.resolve()

    max_depth = int(_fs_cfg().get("max_depth", 1))
    for root in _allowed_roots():
        if not root.exists():
            continue
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if _path_depth_from_root(candidate, root) > max_depth:
            return None
        if must_exist and not candidate.exists():
            return None
        return candidate
    return None


def _allowed_read_extensions() -> set[str]:
    configured = _fs_cfg().get("read_extensions", [])
    values = {str(ext).lower() for ext in configured if str(ext).strip()}
    return values or set(TEXT_FALLBACK_EXTENSIONS)


def _allowed_write_extensions() -> set[str]:
    configured = _fs_cfg().get("write_extensions", [".md"])
    return {str(ext).lower() for ext in configured if str(ext).strip()} or {".md"}


@tool
def list_files(path: str = "artifacts") -> str:
    """
    List files available under configured allowed directories.

    `path` must be inside allowed dirs and within configured depth.
    """
    base = _resolve_allowed_path(path, must_exist=True)
    if base is None or not base.exists():
        return _error(f"Path not found or not allowed: {path}", code="FS_PATH_NOT_ALLOWED")
    if not base.is_dir():
        return _error(f"Path is not a directory: {path}", code="FS_NOT_DIRECTORY")

    max_depth = int(_fs_cfg().get("max_depth", 1))
    rows: list[dict[str, Any]] = []
    try:
        for item in sorted(base.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            depth = None
            root_label = None
            for root in _allowed_roots():
                try:
                    depth = _path_depth_from_root(item.resolve(), root)
                    root_label = str(root.relative_to(PROJECT_ROOT)) if str(root).startswith(str(PROJECT_ROOT)) else str(root)
                    break
                except Exception:
                    continue
            if depth is None or depth > max_depth:
                continue
            rows.append(
                {
                    "name": item.name,
                    "path": str(item.resolve().relative_to(PROJECT_ROOT)),
                    "type": "dir" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None,
                    "root": root_label,
                }
            )
    except Exception as e:
        return _error(f"Failed to list files: {e}", code="FS_LIST_ERROR")

    return _ok({"items": rows}, item_count=len(rows))


@tool
def read_file(path: str) -> str:
    """
    Read a text file from allowed directories.
    """
    target = _resolve_allowed_path(path, must_exist=True)
    if target is None or not target.is_file():
        return _error(f"File not found or not allowed: {path}", code="FS_READ_NOT_ALLOWED")

    ext = target.suffix.lower()
    if ext not in _allowed_read_extensions():
        return _error(f"File extension not allowed for read: {ext}", code="FS_READ_EXTENSION_BLOCKED")

    max_bytes = int(_fs_cfg().get("max_read_bytes", 1024 * 1024))
    try:
        raw = target.read_bytes()
        if len(raw) > max_bytes:
            raw = raw[:max_bytes]
        content = raw.decode("utf-8", errors="replace")
        return _ok(
            {
                "path": str(target.relative_to(PROJECT_ROOT)),
                "content": content,
                "truncated": target.stat().st_size > max_bytes,
                "size_bytes": target.stat().st_size,
            }
        )
    except Exception as e:
        return _error(f"Failed to read file: {e}", code="FS_READ_ERROR")


@tool
def write_file(path: str, content: str) -> str:
    """
    Write markdown content to an allowed file path.
    """
    target = _resolve_allowed_path(path, must_exist=False)
    if target is None:
        return _error(f"Path not allowed: {path}", code="FS_WRITE_NOT_ALLOWED")

    ext = target.suffix.lower()
    if ext not in _allowed_write_extensions():
        return _error(f"File extension not allowed for write: {ext}", code="FS_WRITE_EXTENSION_BLOCKED")

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content), encoding="utf-8")
        return _ok({"path": str(target.relative_to(PROJECT_ROOT)), "bytes_written": len(str(content).encode("utf-8"))})
    except Exception as e:
        return _error(f"Failed to write file: {e}", code="FS_WRITE_ERROR")


@tool
def get_article_by_id(article_id: str) -> str:
    """
    Fetch a single internal article by article_id, including body when available.
    """
    config = get_config()
    try:
        table_name = config.get_table_name("articles")
        articles = get_table(table_name)
        id_col = config.get_column("articles", "id") or "id"
        available_set = {col["name"] for col in inspect(engine).get_columns(table_name)}

        id_candidates = [id_col, "id", "article_id", "art_id"]
        id_candidates = [c for c in dict.fromkeys(id_candidates) if c in available_set]
        if not id_candidates:
            return _error(
                "No article id column found in configured articles table.",
                code="CONFIG_ERROR",
            )

        probe_values: list[Any] = [article_id]
        if isinstance(article_id, str) and article_id.isdigit():
            probe_values.append(int(article_id))
        elif not isinstance(article_id, str):
            probe_values.append(str(article_id))

        row = None
        matched_col = None
        matched_value = None
        for value in probe_values:
            for candidate_col in id_candidates:
                stmt = select(*[cast(c, Text).label(c.name) for c in articles.columns]).where(
                    cast(articles.c[candidate_col], Text) == str(value)
                ).limit(1)
                with engine.connect() as conn:
                    found = conn.execute(stmt).mappings().first()
                if found:
                    row = dict(found)
                    matched_col = candidate_col
                    matched_value = value
                    break
            if row:
                break

        if not row:
            return _error(f"Article {article_id} not found.", code="ARTICLE_NOT_FOUND")

        remapped = remap_row(row, "articles")
        body_value = remapped.get("body")
        body_present = isinstance(body_value, str) and body_value.strip() != ""

        data = {
            "id": remapped.get("id") or remapped.get("article_id") or remapped.get("art_id"),
            "title": remapped.get("title"),
            "created_date": remapped.get("created_date"),
            "theme": remapped.get("theme"),
            "sentiment": remapped.get("sentiment"),
            "summary": remapped.get("summary"),
            "url": remapped.get("url") or remapped.get("article_url") or remapped.get("link"),
            "isin": remapped.get("isin"),
            "impact_score": remapped.get("impact_score"),
            "impact_label": remapped.get("impact_label"),
            "body": remapped.get("body"),
            "body_available": body_present,
        }

        return _ok(
            data,
            article_id=article_id,
            matched_id_col=matched_col,
            matched_id_value=matched_value,
        )
    except Exception as e:
        return _error(f"Error fetching article by id: {str(e)}", code="ARTICLE_FETCH_ERROR")


@tool
def analyze_current_alert(alert_id: str) -> str:
    """
    Run deterministic-first analysis for the current alert without persisting.
    """
    conn = get_db_connection()
    try:
        from ..llm import get_llm_model

        llm = get_llm_model()
        analysis = analyze_alert_non_persisting(
            conn=conn, config=get_config(), alert_id=alert_id, llm=llm
        )
        if not analysis.get("ok"):
            return _error(analysis.get("error", "Analysis failed"), code="ANALYSIS_ERROR")

        return _ok(
            {
                "analysis": analysis["result"],
                "citations": analysis["citations"],
                "articles_considered_count": analysis["articles_considered_count"],
                "source": analysis["source"],
            },
            alert_id=alert_id,
            start_date=analysis["start_date"],
            end_date=analysis["end_date"],
        )
    except Exception as e:
        return _error(f"Error analyzing current alert: {str(e)}", code="ANALYSIS_ERROR")
    finally:
        conn.close()


@tool
def generate_current_alert_report(
    alert_id: str, session_id: str, include_web_news: bool = True
) -> str:
    """
    Generate a downloadable investigation report for the current alert.
    """
    conn = get_db_connection()
    try:
        from ..llm import get_llm_model

        safe_session = sanitize_session_id(session_id)
        result = generate_alert_report_html(
            conn=conn,
            config=get_config(),
            llm=get_llm_model(),
            alert_id=alert_id,
            session_id=safe_session,
            include_web_news=include_web_news,
        )
        if not result.get("ok"):
            return _error(result.get("error", "Report generation failed"), code="REPORT_ERROR")
        return _ok(result, message="Report generated")
    except Exception as e:
        return _error(f"Error generating report: {str(e)}", code="REPORT_ERROR")
    finally:
        conn.close()


@tool
def execute_python(code: str, input_data_json: str = "{}") -> str:
    """
    Execute restricted Python code in an isolated subprocess.

    Contract:
    - Read inputs from `input_data` (dict).
    - Assign final output to variable `result`.
    - Optional prints are captured in stdout.
    """
    cfg = get_config().get_agent_v2_safe_py_runner_config()
    if not cfg.get("enabled", False):
        return _error(
            "execute_python is disabled. Enable agent_v2.safe_py_runner.enabled in config.yaml.",
            code="PYTHON_EXEC_DISABLED",
        )

    normalized_from = "dict"
    try:
        max_input_json_kb = int(cfg.get("max_input_json_kb", 256))
        if len((input_data_json or "").encode("utf-8")) > (max_input_json_kb * 1024):
            return _error(
                f"input_data_json exceeds {max_input_json_kb} KB limit.",
                code="INPUT_TOO_LARGE",
            )
        decoded_input = json.loads(input_data_json or "{}")
        if isinstance(decoded_input, dict):
            input_data = decoded_input
        elif isinstance(decoded_input, list):
            # Be tolerant of model-produced top-level arrays.
            input_data = {"rows": decoded_input}
            normalized_from = "list"
        else:
            return _error(
                "input_data_json must decode to an object/dict or a list.",
                code="INVALID_INPUT",
            )
    except Exception as e:
        return _error(f"Invalid input_data_json: {e}", code="INVALID_INPUT")

    policy = RunnerPolicy(
        timeout_seconds=int(cfg.get("timeout_seconds", 5)),
        memory_limit_mb=int(cfg.get("memory_limit_mb", 256)),
        max_output_kb=int(cfg.get("max_output_kb", 128)),
        blocked_imports=list(cfg.get("blocked_imports", [])),
        blocked_builtins=list(cfg.get("blocked_builtins", [])),
        # Backward-compatible aliases for model-generated snippets that still
        # reference `input_data_json` or `input_data_dict`.
        extra_globals={
            "input_data_json": json.dumps(input_data),
            "input_data_dict": input_data,
            "input_rows": input_data.get("rows", []) if isinstance(input_data, dict) else [],
        },
    )
    try:
        python_executable = str(ensure_python_runtime(cfg))
    except Exception as e:
        return _error(str(e), code="PYTHON_RUNTIME_ERROR")

    result = run_code(
        code=code,
        input_data=input_data,
        policy=policy,
        python_executable=python_executable,
    )

    if not result.ok:
        error_text = result.error or "Python execution failed"
        if ("is not allowed" in error_text or "blocked by policy" in error_text) and "Import '" in error_text:
            error_text = (
                f"{error_text}. Add this module to "
                "agent_v2.safe_py_runner.blocked_imports (or remove it there) in config.yaml."
            )
        return _error(
            error_text,
            code="PYTHON_EXEC_ERROR",
            timed_out=result.timed_out,
            resource_exceeded=result.resource_exceeded,
            stderr=result.stderr,
            exit_code=result.exit_code,
        )

    return _ok(
        {
            "result": result.result,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "timed_out": result.timed_out,
            "resource_exceeded": result.resource_exceeded,
            "exit_code": result.exit_code,
        },
        message="Python executed successfully",
        normalized_input_from=normalized_from,
    )


@tool
def get_python_capabilities() -> str:
    """
    Return current execute_python runtime capabilities from config.

    Use this before complex Python tasks to discover:
    - whether runtime is enabled
    - available/allowed imports
    - execution limits
    """
    cfg = get_config().get_agent_v2_safe_py_runner_config()
    enabled = bool(cfg.get("enabled", False))
    required_imports = [str(x).strip() for x in cfg.get("required_imports", []) if str(x).strip()]
    blocked_imports = [str(x).strip() for x in cfg.get("blocked_imports", []) if str(x).strip()]
    blocked_builtins = [str(x).strip() for x in cfg.get("blocked_builtins", []) if str(x).strip()]

    data = {
        "enabled": enabled,
        "venv_path": str(cfg.get("venv_path", "")),
        "required_imports": required_imports,
        "blocked_imports": blocked_imports,
        "blocked_builtins": blocked_builtins,
        "limits": {
            "timeout_seconds": int(cfg.get("timeout_seconds", 5)),
            "memory_limit_mb": int(cfg.get("memory_limit_mb", 256)),
            "max_output_kb": int(cfg.get("max_output_kb", 128)),
            "max_input_json_kb": int(cfg.get("max_input_json_kb", 256)),
        },
    }
    return _ok(data)


@tool
async def search_web_news(
    query: str, max_results: int = 5, start_date: str = None, end_date: str = None
) -> str:
    """
    Search the internet for recent news and summarize top results.
    """
    import asyncio
    from datetime import datetime

    import aiohttp
    from bs4 import BeautifulSoup
    from ddgs import DDGS

    from ..llm import get_llm_model

    max_results = min(max_results, 10)
    max_content_chars = 3000
    timeout_seconds = 8

    search_query = query
    if start_date:
        try:
            dt = datetime.strptime(start_date, "%Y-%m-%d")
            month_year = dt.strftime("%B %Y")
            if month_year not in query:
                search_query = f"{query} {month_year}"
        except Exception:
            pass

    def _search():
        proxy_config = get_config().get_proxy_config()
        kwargs: dict[str, Any] = {"verify": proxy_config.get("ssl_verify", True)}
        proxy_url = proxy_config.get("https") or proxy_config.get("http")
        if proxy_url:
            kwargs["proxy"] = proxy_url
        with DDGS(**kwargs) as ddgs:
            results = list(ddgs.news(search_query, max_results=max_results * 2))
            return results[:max_results]

    async def _fetch_content(session: aiohttp.ClientSession, url: str) -> str:
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=timeout_seconds),
                headers=headers,
            ) as response:
                if response.status != 200:
                    return ""
                html = await response.text()
                soup = BeautifulSoup(html, "html.parser")
                for elem in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
                    elem.extract()
                text_blob = " ".join(line.strip() for line in soup.get_text().splitlines() if line.strip())
                return text_blob[:max_content_chars]
        except Exception:
            return ""

    def _batch_summarize(articles: list[dict], contents: list[str]) -> list[str]:
        llm = get_llm_model()
        parts = [
            "Summarize each article in 2-3 sentences. Return numbered summaries only.\n"
        ]
        for i, (article, content) in enumerate(zip(articles, contents), 1):
            title = article.get("title", "Unknown")
            body = content or article.get("body", "No content available")
            parts.append(f"\n---\nArticle {i}: {title}\n{body[:1500]}\n")
        try:
            response = llm.invoke("".join(parts))
            raw = response.content.strip()
            summaries: list[str] = []
            current = ""
            for line in raw.split("\n"):
                clean = line.strip()
                if clean and clean[0].isdigit() and "." in clean[:3]:
                    if current:
                        summaries.append(current.strip())
                    current = clean.split(".", 1)[1].strip()
                elif current:
                    current += " " + clean
            if current:
                summaries.append(current.strip())
            while len(summaries) < len(articles):
                summaries.append("Summary not available.")
            return summaries[: len(articles)]
        except Exception:
            return ["Summary generation failed." for _ in articles]

    try:
        results = await asyncio.to_thread(_search)
        if not results:
            return _ok([], message=f"No web news found for: {query}", query=query)

        async with aiohttp.ClientSession(trust_env=True) as session:
            urls = [r.get("url", "") for r in results]
            tasks = [_fetch_content(session, url) for url in urls]
            contents = await asyncio.gather(*tasks)

        summaries = await asyncio.to_thread(_batch_summarize, results, contents)
        final_results = []
        for r, summary in zip(results, summaries):
            final_results.append(
                {
                    "title": r.get("title", "No Title"),
                    "source": r.get("source", "Unknown"),
                    "date": r.get("date", "Unknown"),
                    "url": r.get("url", ""),
                    "summary": summary,
                }
            )
        return _ok(final_results, query=query, row_count=len(final_results))
    except Exception as e:
        return _error(f"Error searching web news: {str(e)}", code="WEB_NEWS_ERROR", query=query)


@tool
async def search_web(query: str, max_results: int = 5) -> str:
    """
    Unified web search: returns both general web and news results.

    Returns:
    - combined: deduplicated merged results
    - web: general web results
    - news: news results
    """
    import asyncio

    from ddgs import DDGS

    max_results = min(max_results, 10)

    def _search():
        proxy_config = get_config().get_proxy_config()
        kwargs: dict[str, Any] = {"verify": proxy_config.get("ssl_verify", True)}
        proxy_url = proxy_config.get("https") or proxy_config.get("http")
        if proxy_url:
            kwargs["proxy"] = proxy_url
        with DDGS(**kwargs) as ddgs:
            web_hits = list(ddgs.text(query, max_results=max_results))
            news_hits = list(ddgs.news(query, max_results=max_results))
            return web_hits, news_hits

    try:
        web_hits, news_hits = await asyncio.to_thread(_search)
        if not web_hits and not news_hits:
            return _ok([], message=f"No web results found for: {query}", query=query)

        web_results = []
        for item in web_hits:
            web_results.append(
                {
                    "title": item.get("title", "No title"),
                    "url": item.get("href", ""),
                    "snippet": item.get("body", ""),
                    "source": item.get("source", "web"),
                    "kind": "web",
                }
            )

        news_results = []
        for item in news_hits:
            news_results.append(
                {
                    "title": item.get("title", "No title"),
                    "url": item.get("url", ""),
                    "snippet": item.get("body", ""),
                    "source": item.get("source", "news"),
                    "date": item.get("date", ""),
                    "kind": "news",
                }
            )

        seen_urls: set[str] = set()
        combined_results = []
        for item in web_results + news_results:
            url = str(item.get("url") or "").strip()
            key = url.lower()
            if not key:
                continue
            if key in seen_urls:
                continue
            seen_urls.add(key)
            combined_results.append(item)

        return _ok(
            {
                "combined": combined_results,
                "web": web_results,
                "news": news_results,
            },
            query=query,
            combined_count=len(combined_results),
            web_count=len(web_results),
            news_count=len(news_results),
        )
    except Exception as e:
        return _error(f"Error searching web: {str(e)}", code="WEB_SEARCH_ERROR", query=query)


@tool
async def scrape_websites(urls: list[str]) -> str:
    """
    Fetch and extract readable text from multiple URLs concurrently.
    """
    import asyncio

    import aiohttp
    from bs4 import BeautifulSoup

    if not urls:
        return _error("No URLs provided.", code="INVALID_INPUT")

    max_chars_per_url = 2000
    timeout_seconds = 10
    url_list = urls[:10]

    async def fetch_one(session: aiohttp.ClientSession, url: str) -> tuple[str, str]:
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=timeout_seconds),
                headers=headers,
            ) as response:
                if response.status != 200:
                    return url, f"[Error: HTTP {response.status}]"
                html = await response.text()
                soup = BeautifulSoup(html, "html.parser")
                for element in soup(["script", "style", "nav", "header", "footer", "aside"]):
                    element.extract()
                text_blob = "\n".join(
                    chunk.strip()
                    for line in soup.get_text().splitlines()
                    for chunk in line.split("  ")
                    if chunk.strip()
                )
                if len(text_blob) > max_chars_per_url:
                    text_blob = text_blob[:max_chars_per_url] + "... (truncated)"
                return url, text_blob
        except asyncio.TimeoutError:
            return url, "[Error: Request timed out]"
        except Exception as e:
            return url, f"[Error: {str(e)}]"

    ssl_verify = get_config().get_proxy_config().get("ssl_verify", True)
    connector = aiohttp.TCPConnector(ssl=ssl_verify)
    async with aiohttp.ClientSession(trust_env=True, connector=connector) as session:
        tasks = [fetch_one(session, url) for url in url_list]
        results = await asyncio.gather(*tasks)

    formatted = []
    for i, (url, content) in enumerate(results, 1):
        formatted.append({"index": i, "url": url, "content": content})
    return _ok(formatted, url_count=len(results))


TOOL_REGISTRY = {
    "execute_sql": execute_sql,
    "execute_python": execute_python,
    "get_python_capabilities": get_python_capabilities,
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "get_article_by_id": get_article_by_id,
    "analyze_current_alert": analyze_current_alert,
    "search_web": search_web,
    "generate_current_alert_report": generate_current_alert_report,
    "scrape_websites": scrape_websites,
}
