from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine

from ..config import get_config


_ENGINE = None


def get_database_url() -> str:
    """Resolve SQLAlchemy database URL from env/config."""
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url

    db_path = get_config().get_database_path()
    p = Path(db_path)
    if not p.is_absolute():
        p = (Path(__file__).parent.parent.parent / p).resolve()
    return f"sqlite:///{p}"


def get_engine():
    """Return singleton SQLAlchemy Engine."""
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_engine(get_database_url(), future=True)
    return _ENGINE

