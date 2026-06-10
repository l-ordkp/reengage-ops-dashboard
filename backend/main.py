"""
ReEngage Ops Dashboard API — FastAPI application.
Replaces Streamlit UI with a REST API for the Next.js frontend.
"""

import json
from datetime import date, datetime

import numpy as np
import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


class SafeJSONResponse(JSONResponse):
    """JSONResponse that handles numpy/pandas types and NaN values."""
    def render(self, content) -> bytes:
        sanitized = self._sanitize(content)
        return json.dumps(sanitized, default=self._default).encode("utf-8")

    @classmethod
    def _sanitize(cls, obj):
        """Recursively replace NaN/NaT/numpy types with JSON-safe values."""
        if obj is None:
            return None
        if isinstance(obj, dict):
            return {k: cls._sanitize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [cls._sanitize(v) for v in obj]
        if isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
            return None
        if isinstance(obj, (np.floating,)):
            return None if np.isnan(obj) else float(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, (pd.Timestamp, datetime)):
            # NaT is a Timestamp — handle it as None
            if pd.isna(obj):
                return None
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, (np.ndarray,)):
            return obj.tolist()
        try:
            if pd.isna(obj):
                return None
        except (ValueError, TypeError):
            pass
        return obj

    @staticmethod
    def _default(obj):
        return str(obj)

from backend.routers import (
    extension,
    auth_routes,
    reviews,
    assignments,
    users,
    operators,
    chain_health,
    chain_value,
    configs,
    ops_log,
    system,
)

app = FastAPI(title="ReEngage Ops Dashboard API", default_response_class=SafeJSONResponse)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Extension routes (unchanged Chrome extension contract)
app.include_router(extension.router)

# Dashboard API routes (JWT auth)
app.include_router(auth_routes.router)
app.include_router(reviews.router)
app.include_router(assignments.router)
app.include_router(users.router)
app.include_router(operators.router)
app.include_router(chain_health.router)
app.include_router(chain_value.router)
app.include_router(configs.router)
app.include_router(ops_log.router)
app.include_router(system.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
