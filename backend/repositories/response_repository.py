"""
AI response writes — PostgreSQL `review_responses` table (Cloud SQL).
This is the only place we touch PostgreSQL.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import pandas as pd

from backend.clients.pg_client import get_pg_session
from backend.models import ReviewResponse

logger = logging.getLogger(__name__)


def _safe_int(val) -> Optional[int]:
    if val is None:
        return None
    try:
        v = int(float(val))
        return v if v > 0 else None
    except (ValueError, TypeError):
        return None


def fetch_responded_order_ids(order_ids: list) -> set:
    """
    Return the subset of `order_ids` that already have a non-empty AI response.

    Used by the generate-batch endpoint to skip already-generated reviews
    across chunks of the same run. Reading PostgreSQL directly is authoritative
    and lag-free, so we no longer bust the fetch_reviews_14d() cache and re-scan
    BigQuery (~4 GiB) just to refresh the joined response_text.
    """
    ids = [str(o) for o in order_ids if o is not None and not pd.isna(o)]
    if not ids:
        return set()
    session = get_pg_session()
    try:
        rows = (
            session.query(ReviewResponse.order_id)
            .filter(ReviewResponse.order_id.in_(ids))
            .filter(ReviewResponse.response_text.isnot(None))
            .filter(ReviewResponse.response_text != "")
            .all()
        )
        return {r[0] for r in rows}
    finally:
        session.close()


def upsert_response(
    review: dict,
    response_text: str,
    errors: Optional[str],
    config_id: Optional[int],
    coupon_value: Optional[float],
    min_order_value: Optional[float],
    response_type: str,
) -> Optional[ReviewResponse]:
    """
    Insert or update the AI response row for a given order_id.
    Returns the persisted ReviewResponse, or None on error.
    """
    session = get_pg_session()
    try:
        existing = session.query(ReviewResponse).filter(
            ReviewResponse.order_id == review.get("order_id")
        ).first()

        if existing:
            existing.response_text = response_text
            existing.response_type = response_type
            existing.config_id = config_id
            existing.coupon_value = coupon_value
            existing.min_order_value = min_order_value
            existing.generated_at = datetime.utcnow()
            existing.response_sent = None
            existing.errors = errors
            session.commit()
            session.refresh(existing)
            return existing

        ts = review.get("event_timestamp")
        rr = ReviewResponse(
            platform=review.get("platform"),
            slug=review.get("slug"),
            b_name_id=review.get("b_name_id"),
            store_id=review.get("store_id"),
            order_id=review.get("order_id"),
            order_timestamp=ts if not pd.isna(ts) else None,
            review_timestamp=ts if not pd.isna(ts) else None,
            review_id=review.get("review_id"),
            customer_name=review.get("customer_name"),
            rating=_safe_int(review.get("star_rating")),
            review_text=review.get("review_text"),
            response_text=response_text,
            response_type=response_type,
            generated_at=datetime.utcnow(),
            config_id=config_id,
            coupon_value=coupon_value,
            min_order_value=min_order_value,
            errors=errors,
            items=review.get("items"),
            item_reviews=review.get("item_reviews"),
        )
        session.add(rr)
        session.commit()
        session.refresh(rr)
        return rr
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to save response for order {review.get('order_id')}: {e}")
        return None
    finally:
        session.close()
