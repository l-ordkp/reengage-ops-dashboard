"""DataFrame → JSON-safe list of dicts."""
from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd


def df_to_dicts(df: pd.DataFrame) -> list[dict]:
    """
    Convert a DataFrame into a list of JSON-serializable dicts.
    Handles NaN, NaT, numpy ints/floats/bools, pandas Timestamps, and date objects.
    """
    records = df.to_dict("records")
    for row in records:
        for k, v in row.items():
            # NaN/NaT first (NaT is also a Timestamp instance)
            try:
                if v is None or pd.isna(v):
                    row[k] = None
                    continue
            except (ValueError, TypeError):
                pass

            if isinstance(v, (pd.Timestamp, datetime)):
                row[k] = v.isoformat()
            elif isinstance(v, date):
                row[k] = v.isoformat()
            elif isinstance(v, (np.integer,)):
                row[k] = int(v)
            elif isinstance(v, (np.floating,)):
                row[k] = float(v)
            elif isinstance(v, np.bool_):
                row[k] = bool(v)
    return records
