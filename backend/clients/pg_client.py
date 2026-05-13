"""
PostgreSQL connection (Cloud SQL / local).
Singleton engine + session factory.
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _get_pg_config() -> dict:
    return {
        "host": os.environ.get("DB_HOST", "localhost"),
        "port": int(os.environ.get("DB_PORT", "5432")),
        "user": os.environ.get("DB_USER", "loop"),
        "password": os.environ.get("DB_PASSWORD", ""),
        "database": os.environ.get("DB_NAME", "loop_core"),
    }


def get_pg_engine() -> Engine:
    global _engine
    if _engine is None:
        cfg = _get_pg_config()
        host = cfg["host"]
        if host.startswith("/"):  # Cloud SQL Unix socket
            url = (f"postgresql+psycopg2://{cfg['user']}:{cfg['password']}"
                   f"@/{cfg['database']}?host={host}")
        else:
            url = (f"postgresql+psycopg2://{cfg['user']}:{cfg['password']}"
                   f"@{host}:{cfg['port']}/{cfg['database']}")
        _engine = create_engine(url, pool_size=3, max_overflow=5, pool_pre_ping=True)
    return _engine


def get_pg_session() -> Session:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_pg_engine())
    return _SessionLocal()
