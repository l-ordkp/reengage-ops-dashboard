"""
Extension API — Chrome extension endpoints.
Moved from extension_api.py into a router. ZERO behavioral changes.
Auth uses X-Operator-Email header (not JWT).
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from backend.config import PROJECT, TABLE_OPS_LOG, TABLE_ASSIGNMENTS, TABLE_USERS, TABLE_AUTOMATION_REVIEWS
from backend.db import bq_read_dicts, bq_exec

router = APIRouter(prefix="/api/extension", tags=["extension"])

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def validate_operator(email: str) -> str:
    if not email or "@" not in email:
        raise HTTPException(status_code=401, detail="Missing operator email")
    safe = email.lower().replace("'", "''")
    rows = bq_read_dicts(f"""
        SELECT email FROM `{PROJECT}.{TABLE_USERS}`
        WHERE LOWER(email) = '{safe}' AND approved = TRUE
        LIMIT 1
    """)
    if not rows:
        raise HTTPException(status_code=403, detail="Operator not approved")
    return email


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/lookup")
def lookup(order_id: str, x_operator_email: str = Header(None)):
    operator_email = validate_operator(x_operator_email or "")
    if not UUID_RE.match(order_id):
        raise HTTPException(status_code=400, detail="Invalid order_id")

    safe_id = order_id.replace("'", "")
    rows = bq_read_dicts(f"""
        SELECT
            rr.response_text,
            rr.coupon_value,
            rr.response_type,
            rr.response_sent,
            ar.customer_name,
            ar.review_text,
            ar.star_rating,
            ar.slug,
            ar.is_replied
        FROM `{PROJECT}.pg_cdc_public.review_responses` rr
        LEFT JOIN `{PROJECT}.elt_data.automation_reviews` ar
            ON rr.order_id = ar.order_id
        WHERE rr.order_id = '{safe_id}'
        LIMIT 1
    """)

    if not rows:
        return {"found": False, "order_id": order_id}

    r = rows[0]
    return {
        "found": True,
        "order_id": order_id,
        "response_text": r.get("response_text"),
        "coupon_value": float(r["coupon_value"]) if r.get("coupon_value") else 0,
        "response_type": r.get("response_type"),
        "response_sent": str(r["response_sent"]) if r.get("response_sent") else None,
        "customer_name": r.get("customer_name"),
        "review_text": r.get("review_text"),
        "star_rating": str(r["star_rating"]) if r.get("star_rating") else None,
        "slug": r.get("slug"),
        "is_replied": bool(r.get("is_replied")),
        "operator_email": operator_email,
    }


class MarkRespondedBody(BaseModel):
    order_id: str
    platform: str
    chain_name: str = ""


@router.post("/mark-responded")
def mark_responded(body: MarkRespondedBody, x_operator_email: str = Header(None)):
    operator_email = validate_operator(x_operator_email or "")
    if not UUID_RE.match(body.order_id):
        raise HTTPException(status_code=400, detail="Invalid order_id")

    safe_order_id = body.order_id.replace("'", "")

    uid_rows = bq_read_dicts(f"""
        SELECT COALESCE(review_id, order_id) AS review_uid
        FROM `{PROJECT}.{TABLE_AUTOMATION_REVIEWS}`
        WHERE order_id = '{safe_order_id}'
        LIMIT 1
    """)
    review_uid = uid_rows[0]["review_uid"] if uid_rows else body.order_id

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    safe_uid = review_uid.replace("'", "''")
    safe_platform = body.platform.replace("'", "''")
    safe_chain = body.chain_name.replace("'", "''")
    safe_operator = operator_email.replace("'", "''")
    platform_short = "extension_ue" if "uber" in body.platform.lower() else "extension_dd"
    log_id = str(uuid.uuid4())

    bq_exec(f"""
        INSERT INTO `{PROJECT}.{TABLE_OPS_LOG}`
            (id, review_uid, platform, chain_name, action,
             operator_email, performed_by, remarks, processing_timestamp)
        VALUES
            ('{log_id}', '{safe_uid}', '{safe_platform}', '{safe_chain}',
             'mark_responded', '{safe_operator}', '{safe_operator}',
             '{platform_short}', TIMESTAMP('{now}'))
    """)

    existing = bq_read_dicts(f"""
        SELECT assignment_id FROM `{PROJECT}.{TABLE_ASSIGNMENTS}`
        WHERE order_id = '{safe_order_id}'
        LIMIT 1
    """)
    if existing:
        bq_exec(f"""
            UPDATE `{PROJECT}.{TABLE_ASSIGNMENTS}`
            SET status = 'completed', completed_at = TIMESTAMP('{now}')
            WHERE order_id = '{safe_order_id}' AND status = 'pending'
        """)
    else:
        assignment_id = str(uuid.uuid4())
        bq_exec(f"""
            INSERT INTO `{PROJECT}.{TABLE_ASSIGNMENTS}`
                (assignment_id, review_uid, order_id, operator_email,
                 chain_name, platform, days_left, status, assigned_at, completed_at)
            VALUES
                ('{assignment_id}', '{safe_uid}', '{safe_order_id}', '{safe_operator}',
                 '{safe_chain}', '{safe_platform}', 0, 'completed',
                 TIMESTAMP('{now}'), TIMESTAMP('{now}'))
        """)

    bq_exec(f"""
        UPDATE `{PROJECT}.{TABLE_AUTOMATION_REVIEWS}`
        SET is_loop_replied = TRUE
        WHERE order_id = '{safe_order_id}'
    """)

    return {"success": True, "operator_email": operator_email, "review_uid": review_uid}
