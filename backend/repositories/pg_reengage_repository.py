"""Dual-write of extension writes to Postgres (loop_core) during the BQ->PG
migration.

Every function here is BEST-EFFORT: it opens its own session, swallows and logs
any error, and never raises — so a Postgres failure can never break the
authoritative BigQuery write path. Gated by config.DUAL_WRITE_PG (off by
default).

Targets the tables from loop_core migration 4a4ee4129539 (reengage_assignments,
reengage_ops_log). `canonical_review_key` is a generated column
(COALESCE(NULLIF(review_uid,''), NULLIF(order_id,''))) and the terminal partial
unique index (status IN ('completed','auto_resolved')) is the dedup guard, so
the mark/observed race can't create two terminal rows.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from backend.clients.pg_client import get_pg_session

logger = logging.getLogger(__name__)


def _canonical(review_uid: str | None, order_id: str | None) -> str | None:
    """Mirror the DB's canonical_review_key: review_uid, else order_id."""
    return (review_uid or "").strip() or (order_id or "").strip() or None


def dual_write_mark_completed(
    *, review_uid: str | None, order_id: str | None, operator_email: str,
    platform: str, chain_name: str = "",
    platform_reply_id: str = "", platform_coupon_id: str = "",
) -> None:
    """Mirror mark_responded's assignment write into Postgres.

    Matches the BQ semantics: flip an existing pending row to completed; if none
    exists, insert a completed row — and if a terminal row already exists,
    promote/keep it (an auto_resolved sibling, operator_email='', is promoted to
    the submitter; a real completed row's operator is left intact). The terminal
    partial unique index guarantees at most one terminal row per review.
    """
    ck = _canonical(review_uid, order_id)
    if not ck:
        return
    now = datetime.now(timezone.utc)
    session = get_pg_session()
    try:
        # 1) Flip an existing pending row (== update_assignment_by_order_id).
        flipped = session.execute(
            text("""
                UPDATE reengage_assignments
                SET status = 'completed', completed_at = :now, updated_at = :now,
                    platform_reply_id  = COALESCE(NULLIF(:reply_id, ''), platform_reply_id),
                    platform_coupon_id = COALESCE(NULLIF(:coupon_id, ''), platform_coupon_id)
                WHERE canonical_review_key = :ck AND status = 'pending'
            """),
            {"now": now, "reply_id": platform_reply_id,
             "coupon_id": platform_coupon_id, "ck": ck},
        ).rowcount

        # 2) No pending row -> insert a completed row, or promote an existing
        #    terminal one (handles the insert + promote_auto_resolved cases).
        if flipped == 0:
            session.execute(
                text("""
                    INSERT INTO reengage_assignments
                        (assignment_id, review_uid, order_id, operator_email, chain_name,
                         platform, status, assigned_at, completed_at,
                         platform_reply_id, platform_coupon_id,
                         observed_out_of_window, created_at, updated_at)
                    VALUES
                        (:aid, :review_uid, :order_id, :operator_email, :chain_name,
                         :platform, 'completed', :now, :now,
                         NULLIF(:reply_id, ''), NULLIF(:coupon_id, ''),
                         FALSE, :now, :now)
                    ON CONFLICT (canonical_review_key)
                        WHERE status IN ('completed', 'auto_resolved')
                              AND canonical_review_key IS NOT NULL
                    DO UPDATE SET
                        status = 'completed',
                        completed_at = :now,
                        updated_at = :now,
                        observed_out_of_window = FALSE,
                        -- promote auto_resolved (operator '') to the submitter;
                        -- keep a real completed row's operator untouched.
                        operator_email = CASE
                            WHEN reengage_assignments.operator_email = ''
                            THEN EXCLUDED.operator_email
                            ELSE reengage_assignments.operator_email END,
                        platform_reply_id  = COALESCE(EXCLUDED.platform_reply_id,  reengage_assignments.platform_reply_id),
                        platform_coupon_id = COALESCE(EXCLUDED.platform_coupon_id, reengage_assignments.platform_coupon_id)
                """),
                {"aid": str(uuid.uuid4()), "review_uid": review_uid or "",
                 "order_id": order_id, "operator_email": operator_email,
                 "chain_name": chain_name or "", "platform": platform, "now": now,
                 "reply_id": platform_reply_id, "coupon_id": platform_coupon_id},
            )
        session.commit()
    except Exception as e:  # best-effort: never break the BQ path
        session.rollback()
        logger.warning("dual_write_mark_completed failed for ck=%s: %s", ck, e)
    finally:
        session.close()


def dual_write_ops_log(
    *, review_uid: str | None, platform: str, chain_name: str, action: str,
    operator_email: str, performed_by: str, remarks: str = "",
) -> None:
    """Append one audit row to reengage_ops_log (best-effort)."""
    now = datetime.now(timezone.utc)
    session = get_pg_session()
    try:
        session.execute(
            text("""
                INSERT INTO reengage_ops_log
                    (entry_id, review_uid, platform, chain_name, action,
                     operator_email, performed_by, remarks, processing_timestamp,
                     created_at, updated_at)
                VALUES
                    (:entry_id, :review_uid, :platform, :chain_name, :action,
                     :operator_email, :performed_by, :remarks, :now, :now, :now)
                ON CONFLICT (entry_id) DO NOTHING
            """),
            {"entry_id": str(uuid.uuid4()), "review_uid": review_uid or "",
             "platform": platform or "", "chain_name": chain_name or "",
             "action": action, "operator_email": operator_email or "",
             "performed_by": performed_by or "", "remarks": remarks or "", "now": now},
        )
        session.commit()
    except Exception as e:
        session.rollback()
        logger.warning("dual_write_ops_log failed (action=%s): %s", action, e)
    finally:
        session.close()
