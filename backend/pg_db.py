"""
PostgreSQL connection — no Streamlit dependency.
Uses env vars for connection config.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_engine = None
_SessionLocal = None


def _get_pg_config():
    return {
        "host": os.environ.get("DB_HOST", "localhost"),
        "port": int(os.environ.get("DB_PORT", "2391")),
        "user": os.environ.get("DB_USER", "loop"),
        "password": os.environ.get("DB_PASSWORD", "password"),
        "database": os.environ.get("DB_NAME", "loop_core"),
    }


def get_pg_engine():
    global _engine
    if _engine is None:
        cfg = _get_pg_config()
        host = cfg["host"]
        if host.startswith("/"):
            url = (f"postgresql+psycopg2://{cfg['user']}:{cfg['password']}"
                   f"@/{cfg['database']}?host={host}")
        else:
            url = (f"postgresql+psycopg2://{cfg['user']}:{cfg['password']}"
                   f"@{host}:{cfg['port']}/{cfg['database']}")
        _engine = create_engine(url, pool_size=3, max_overflow=5, pool_pre_ping=True)
    return _engine


def get_pg_session():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_pg_engine())
    return _SessionLocal()
