"""
PostgreSQL connection to Cloud SQL (loop_core database).
Writes to review_responses table (same as backend).

Local dev: Cloud SQL Proxy on localhost:2391
Cloud Run: Direct connection via private IP 10.83.193.4:5432
"""

import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_engine = None
_SessionLocal = None


def _get_pg_config():
    """Read PostgreSQL config from Streamlit secrets."""
    pg = st.secrets.get("postgresql", {})
    return {
        "host": pg.get("host", "localhost"),
        "port": pg.get("port", 2391),
        "user": pg.get("user", "loop"),
        "password": pg.get("password", "password"),
        "database": pg.get("database", "loop_core"),
    }


def get_pg_engine():
    global _engine
    if _engine is None:
        cfg = _get_pg_config()
        host = cfg["host"]
        # Cloud SQL Unix socket (starts with /cloudsql/)
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
