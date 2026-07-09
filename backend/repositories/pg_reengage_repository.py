"""Dual-write of extension writes to Postgres (loop_core) during the BQ->PG
migration.

Every function here is BEST-EFFORT: it runs through `_safe`, which opens the
session INSIDE the try, swallows and logs any error (including session/engine
construction, rollback, and close), and never raises — so a Postgres failure
can never break the authoritative BigQuery write path. Gated by
config.DUAL_WRITE_PG (off by default).

Targets the tables from loop_core migration 4a4ee4129539 (reengage_assignments,
reengage_ops_log). `canonical_review_key` is a generated column
(COALESCE(NULLIF(review_uid,''), NULLIF(order_id,''))) and the terminal partial
unique index (status IN ('completed','auto_resolved')) is the dedup guard, so
the mark/observed race can't create two terminal rows.
"""
from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.clients.pg_client import get_pg_session

logger = logging.getLogger(__name__)


def _safe(op_name: str, work: Callable[[Session], None]) -> None:
    """Run `work(session)` and commit, guaranteeing nothing escapes.

    The session is created INSIDE the try, so engine/config construction errors
    are caught too; rollback() and close() are individually guarded so a broken
    connection can't re-raise past us. This is what makes the dual-write
    genuinely best-effort — the caller (mark_responded / run_assignment) never
    sees an exception, even though the authoritative BigQuery write already ran.
    """
    session = None
    try:
        session = get_pg_session()
        work(session)
        session.commit()
    except Exception as e:
        if session is not None:
            try:
                session.rollback()
            except Exception:
                pass
        logger.warning("%s failed: %s", op_name, e)
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass


def _canonical(review_uid: str | None, order_id: str | None) -> str | None:
    """Mirror the DB's canonical_review_key EXACTLY:
    COALESCE(NULLIF(review_uid, ''), NULLIF(order_id, '')). No trim — a
    whitespace-only value is non-empty to NULLIF, so we must not strip it or
    the Python key would disagree with the generated column."""
    return (review_uid or None) or (order_id or None)


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

    def work(session: Session) -> None:
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

    _safe("dual_write_mark_completed", work)


def dual_write_ops_log(
    *, review_uid: str | None, platform: str, chain_name: str, action: str,
    operator_email: str, performed_by: str, remarks: str = "",
) -> None:
    """Append one audit row to reengage_ops_log (best-effort)."""
    now = datetime.now(timezone.utc)

    def work(session: Session) -> None:
        session.execute(
            text("""
                INSERT INTO reengage_ops_log
                    (entry_id, review_uid, platform, chain_name, action,
                     operator_email, performed_by, remarks, processing_timestamp,
                     created_at, updated_at)
                VALUES
                    (:entry_id, :review_uid, :platform, :chain_name, :action,
                     :operator_email, :performed_by, :remarks, :now, :now, :now)
            """),
            {"entry_id": str(uuid.uuid4()), "review_uid": review_uid or "",
             "platform": platform or "", "chain_name": chain_name or "",
             "action": action, "operator_email": operator_email or "",
             "performed_by": performed_by or "", "remarks": remarks or "", "now": now},
        )

    _safe("dual_write_ops_log", work)


def dual_write_ops_log_bulk(entries: list[dict]) -> None:
    """Bulk variant of dual_write_ops_log for the observed-responded batch.
    Each entry: review_uid, platform, chain_name, action, operator_email,
    performed_by, remarks."""
    if not entries:
        return
    now = datetime.now(timezone.utc)

    def work(session: Session) -> None:
        session.execute(
            text("""
                INSERT INTO reengage_ops_log
                    (entry_id, review_uid, platform, chain_name, action,
                     operator_email, performed_by, remarks, processing_timestamp,
                     created_at, updated_at)
                VALUES
                    (:entry_id, :review_uid, :platform, :chain_name, :action,
                     :operator_email, :performed_by, :remarks, :now, :now, :now)
            """),
            [{"entry_id": str(uuid.uuid4()), "review_uid": e.get("review_uid") or "",
              "platform": e.get("platform") or "", "chain_name": e.get("chain_name") or "",
              "action": e.get("action") or "", "operator_email": e.get("operator_email") or "",
              "performed_by": e.get("performed_by") or "", "remarks": e.get("remarks") or "",
              "now": now} for e in entries],
        )

    _safe("dual_write_ops_log_bulk", work)


def dual_write_observed(items: list[dict]) -> None:
    """Mirror observed_responded's assignment writes into Postgres.

    Each item: review_uid, order_id, platform, status ('completed' for
    missed_but_ours, 'auto_resolved' for external), operator_email (matched Loop
    username, or '' for external), observed_out_of_window.

    Batched (not per-item) to keep this synchronous handler's PG cost to a few
    statements regardless of batch size:
      1. One UPDATE per (status, operator, OOW) group flips matching pending
         rows. Matched on review_uid OR order_id (both indexed —
         ix_reengage_assignment_review / _order — and matching BQ's
         bulk_flip_pending_to, which keys on review_uid OR order_id). A
         NOT EXISTS guard skips any row that already has a terminal sibling, so
         the flip can never create a second terminal row (no unique violation).
      2. One bulk INSERT of all items with ON CONFLICT DO NOTHING. Rows that
         were just flipped, or that already had a terminal row, conflict and are
         skipped — so an observation never overwrites a real submit's completed
         row (matching the manager's "already-terminal rows are skipped").
    """
    if not items:
        return
    now = datetime.now(timezone.utc)

    # Group flips by their target (status, operator, OOW) so each group is one
    # UPDATE. Collect the review_uids/order_ids to match pending rows on.
    groups: dict[tuple, dict[str, list]] = defaultdict(lambda: {"ruids": [], "oids": []})
    for it in items:
        if not _canonical(it.get("review_uid"), it.get("order_id")):
            continue
        key = (it["status"], it.get("operator_email") or "",
               bool(it.get("observed_out_of_window")))
        if it.get("review_uid"):
            groups[key]["ruids"].append(it["review_uid"])
        if it.get("order_id"):
            groups[key]["oids"].append(it["order_id"])

    def work(session: Session) -> None:
        for (status, op, oow), g in groups.items():
            session.execute(
                text("""
                    UPDATE reengage_assignments AS a
                    SET status = :status, operator_email = :op,
                        observed_out_of_window = :oow,
                        completed_at = :now, updated_at = :now
                    WHERE a.status = 'pending'
                      AND (a.review_uid = ANY(:ruids) OR a.order_id = ANY(:oids))
                      AND NOT EXISTS (
                          SELECT 1 FROM reengage_assignments t
                          WHERE t.canonical_review_key = a.canonical_review_key
                            AND t.status IN ('completed', 'auto_resolved'))
                """),
                {"status": status, "op": op, "oow": oow, "now": now,
                 "ruids": g["ruids"], "oids": g["oids"]},
            )
        session.execute(
            text("""
                INSERT INTO reengage_assignments
                    (assignment_id, review_uid, order_id, operator_email, chain_name,
                     platform, days_left, status, assigned_at, completed_at,
                     observed_out_of_window, created_at, updated_at)
                VALUES
                    (:aid, :review_uid, :order_id, :op, '', :platform, 0,
                     :status, :now, :now, :oow, :now, :now)
                ON CONFLICT (canonical_review_key)
                    WHERE status IN ('completed', 'auto_resolved')
                          AND canonical_review_key IS NOT NULL
                DO NOTHING
            """),
            [{"aid": str(uuid.uuid4()), "review_uid": it.get("review_uid") or "",
              "order_id": it.get("order_id"), "op": it.get("operator_email") or "",
              "platform": it.get("platform") or "", "status": it["status"],
              "oow": bool(it.get("observed_out_of_window")), "now": now}
             for it in items if _canonical(it.get("review_uid"), it.get("order_id"))],
        )

    _safe("dual_write_observed", work)


# ── Assignment-cron dual-writes (run_assignment) ──────────────────────────────

def dual_write_expire_pending() -> None:
    """Mirror expire_stale_assignments: pending -> expired once past the stamped
    response_deadline. `<=` matches BQ's `CURRENT_TIMESTAMP() >= deadline`
    boundary. Only rows with a deadline set are touched (see the insert path,
    which stamps the precise review_timestamp + 7/14d)."""
    now = datetime.now(timezone.utc)

    def work(session: Session) -> None:
        session.execute(
            text("""
                UPDATE reengage_assignments
                SET status = 'expired', updated_at = :now
                WHERE status = 'pending'
                  AND response_deadline IS NOT NULL
                  AND response_deadline <= :now
            """),
            {"now": now},
        )

    _safe("dual_write_expire_pending", work)


def dual_write_void_pending() -> None:
    """Mirror void_pending_assignments: all pending -> reassigned (the
    full-reassign tombstone step)."""
    now = datetime.now(timezone.utc)

    def work(session: Session) -> None:
        session.execute(
            text("""
                UPDATE reengage_assignments
                SET status = 'reassigned', updated_at = :now
                WHERE status = 'pending'
            """),
            {"now": now},
        )

    _safe("dual_write_void_pending", work)


def dual_write_insert_pending(rows: list[dict]) -> None:
    """Mirror insert_assignments: bulk-insert freshly-assigned pending rows.
    Each row: assignment_id, review_uid, order_id, operator_email, chain_name,
    platform, days_left, response_deadline (may be None).

    Commits PER CHUNK so a 40-80k-row cron insert doesn't hold row locks / a
    pooled connection on shared prod loop_core for the whole batch (a long
    single transaction risks statement/idle-in-transaction timeouts). Partial
    progress on failure is fine — ON CONFLICT (assignment_id) DO NOTHING makes a
    re-run idempotent. Session lifecycle is guarded so nothing escapes.
    """
    if not rows:
        return
    now = datetime.now(timezone.utc)
    sql = text("""
        INSERT INTO reengage_assignments
            (assignment_id, review_uid, order_id, operator_email, chain_name,
             platform, days_left, status, assigned_at, response_deadline,
             created_at, updated_at)
        VALUES
            (:assignment_id, :review_uid, :order_id, :operator_email, :chain_name,
             :platform, :days_left, 'pending', :now, :response_deadline, :now, :now)
        ON CONFLICT (assignment_id) DO NOTHING
    """)
    CHUNK = 2000
    session = None
    try:
        session = get_pg_session()
        for i in range(0, len(rows), CHUNK):
            params = [{
                "assignment_id": r["assignment_id"],
                "review_uid": r["review_uid"],
                "order_id": (r.get("order_id") or None),
                "operator_email": r["operator_email"],
                "chain_name": r.get("chain_name") or "",
                "platform": r.get("platform") or "",
                "days_left": r.get("days_left"),
                "response_deadline": r.get("response_deadline"),
                "now": now,
            } for r in rows[i:i + CHUNK]]
            session.execute(sql, params)
            session.commit()  # per-chunk: bound lock/connection hold time
    except Exception as e:
        if session is not None:
            try:
                session.rollback()
            except Exception:
                pass
        logger.warning("dual_write_insert_pending failed (partial, %d rows): %s", len(rows), e)
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
