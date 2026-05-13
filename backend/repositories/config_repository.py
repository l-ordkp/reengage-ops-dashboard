"""Response config data access — `review_response_config` (read-only CDC mirror)."""
from __future__ import annotations

import json

import pandas as pd

from backend.clients.bq_client import bq_read
from backend.config import TABLE_REVIEW_RESPONSE_CFG
from backend.utils.cache import cached


@cached(ttl=120)
def fetch_all_configs() -> pd.DataFrame:
    """All response configs (including paused). Used by Response Config tab."""
    return bq_read(f"""
    SELECT config_id, config_name, chain_name, paused,
           response_type, tonality,
           TO_JSON_STRING(vb_platforms) AS vb_platforms,
           TO_JSON_STRING(ratings) AS ratings,
           TO_JSON_STRING(customer_types) AS customer_types,
           TO_JSON_STRING(review_sentiments) AS review_sentiments,
           TO_JSON_STRING(feedback_presence) AS feedback_presence,
           response_text AS response_template_legacy,
           coupon_type, coupon_fixed_value, coupon_percentage_value,
           dd_coupon_type, dd_coupon_fixed_value, dd_coupon_percentage_value,
           ue_coupon_type, ue_coupon_fixed_value, ue_coupon_percentage_value,
           paraphrase, min_order_value,
           created_by, created_at, updated_by, updated_at
    FROM `{TABLE_REVIEW_RESPONSE_CFG}`
    ORDER BY paused ASC, updated_at DESC
    """)


def fetch_configs_for_matching() -> list[dict]:
    """
    Configs flattened into the shape `find_matching_config()` expects:
    JSON columns parsed, platform_configs nested.
    """
    df = fetch_all_configs()
    if df.empty:
        return []

    def _parse(val):
        if pd.isna(val) or val is None:
            return []
        try:
            return json.loads(val)
        except Exception:
            return []

    configs = []
    for _, row in df.iterrows():
        platform_configs = {}
        for plat, prefix in [("Doordash", "dd"), ("UberEats", "ue")]:
            ct = row.get(f"{prefix}_coupon_type")
            if ct:
                platform_configs[plat] = {
                    "coupon_type": ct,
                    "fixed_value": row.get(f"{prefix}_coupon_fixed_value", 0) or 0,
                    "percentage_value": row.get(f"{prefix}_coupon_percentage_value", 0) or 0,
                    "min_order_value": row.get("min_order_value", 0) or 0,
                }
        configs.append({
            "config_id": row["config_id"],
            "chain_name": row["chain_name"],
            "paused": row["paused"],
            "response_type": row["response_type"],
            "tonality": row.get("tonality", "neutral"),
            "vb_platforms": _parse(row["vb_platforms"]),
            "ratings": _parse(row["ratings"]),
            "customer_types": _parse(row["customer_types"]),
            "feedback_presence": _parse(row.get("feedback_presence")),
            "b_name_ids": [],
            "created_at": str(row.get("created_at", "")),
            "platform_configs": platform_configs,
        })
    return configs
