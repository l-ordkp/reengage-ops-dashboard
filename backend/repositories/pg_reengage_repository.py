"""Postgres (loop_core) repository for the ReEngage OLTP tables — the
AUTHORITATIVE write path for `reengage_assignments` and `reengage_ops_log`.

These are the primary writers (no longer a best-effort BigQuery mirror): a
failure RAISES so the caller (and ultimately the extension / cron) sees the
error and can retry, rather than silently losing a reply. `_write` owns the
session lifecycle (open inside the try, commit, guarded rollback/close) and
re-raises on failure.

`canonical_review_key` is a generated column
(COALESCE(NULLIF(review_uid,''), NULLIF(order_id,''))); the terminal partial
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


def _write(op_name: str, work: Callable[[Session], None]) -> None:
    """Run `work(session)` and commit. On failure: roll back, close, and
    RE-RAISE — these are authoritative writes, so the caller must know a write
    failed (unlike the old best-effort dual-write, which swallowed errors)."""
    session = None
    try:
        session = get_pg_session()
        work(session)
        session.commit()
    except Exception:
        if session is not None:
            try:
                session.rollback()
            except Exception:
                pass
        logger.exception("%s failed", op_name)
        raise
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


# ── Assignment writes ─────────────────────────────────────────────────────────

def mark_completed(
    *, review_uid: str | None, order_id: str | None, operator_email: str,
    platform: str, chain_name: str = "",
    platform_reply_id: str = "", platform_coupon_id: str = "",
) -> None:
    """Flip an existing pending row to completed; if none exists, insert a
    completed row — and if a terminal row already exists: an auto_resolved
    sibling is promoted to the submitter's completed row, while a row that is
    already completed is left ENTIRELY untouched (idempotent — retries must not
    move completed_at or clear observed_out_of_window). The terminal partial
    unique index guarantees at most one terminal row per review."""
    ck = _canonical(review_uid, order_id)
    if not ck:
        return
    now = datetime.now(timezone.utc)

    def work(session: Session) -> None:
        # 1) Flip an existing pending row.
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
        #    terminal one (insert + promote_auto_resolved cases).
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
                        operator_email = EXCLUDED.operator_email,
                        platform_reply_id  = COALESCE(EXCLUDED.platform_reply_id,  reengage_assignments.platform_reply_id),
                        platform_coupon_id = COALESCE(EXCLUDED.platform_coupon_id, reengage_assignments.platform_coupon_id)
                    -- Promotion only: an auto_resolved row becomes this submit's
                    -- completed row, stamped with the submitter. A row that is
                    -- ALREADY completed is left untouched (no-op), so an
                    -- extension outbox retry of a mark whose 200 was lost can't
                    -- bump completed_at (shifting the reply's counted IST day)
                    -- or clear a legitimate observed_out_of_window=TRUE.
                    -- Matches the old BQ promote_auto_resolved_to_completed's
                    -- NOT-EXISTS guard.
                    WHERE reengage_assignments.status = 'auto_resolved'
                """),
                {"aid": str(uuid.uuid4()), "review_uid": review_uid or "",
                 "order_id": order_id, "operator_email": operator_email,
                 "chain_name": chain_name or "", "platform": platform, "now": now,
                 "reply_id": platform_reply_id, "coupon_id": platform_coupon_id},
            )

    _write("mark_completed", work)


def mark_completed_by_assignment_id(assignment_id: str) -> None:
    """Flip one assignment row to completed by its assignment_id (the dashboard
    queue's manual "mark complete" — POST /api/assignments/{id}/complete).

    The BQ version updated unconditionally; here two guards keep the terminal
    invariant and make retries no-ops:
      * skip if the row is already terminal (idempotent — a retry must not bump
        completed_at or the OOW flag);
      * skip if a SIBLING row for the same review already holds the terminal
        slot (flipping would violate uq_reengage_assignment_terminal) — the
        review is already recorded as replied, so there's nothing to do.
    Like the BQ version, non-pending rows (expired/reassigned) may still be
    flipped: an operator completing a stale queue entry is real work.
    """
    now = datetime.now(timezone.utc)

    def work(session: Session) -> None:
        session.execute(
            text("""
                UPDATE reengage_assignments r
                SET status = 'completed', completed_at = :now, updated_at = :now
                WHERE r.assignment_id = :aid
                  AND r.status NOT IN ('completed', 'auto_resolved')
                  AND NOT EXISTS (
                    SELECT 1 FROM reengage_assignments x
                    WHERE x.canonical_review_key = r.canonical_review_key
                      AND x.status IN ('completed', 'auto_resolved')
                  )
            """),
            {"aid": assignment_id, "now": now},
        )

    _write("mark_completed_by_assignment_id", work)


def write_observed(items: list[dict]) -> None:
    """observed_responded's assignment writes.

    Each item: review_uid, order_id, platform, status ('completed' for
    missed_but_ours, 'auto_resolved' for external), operator_email (matched Loop
    username, or '' for external), observed_out_of_window.

    Batched: one UPDATE per (status, operator, OOW) group flips matching pending
    rows (matched on review_uid OR order_id, both indexed; a NOT EXISTS guard
    skips rows with a terminal sibling so no second terminal row is created),
    then one bulk INSERT with ON CONFLICT DO NOTHING so an observation never
    overwrites a real submit's completed row.
    """
    if not items:
        return
    now = datetime.now(timezone.utc)

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

    _write("write_observed", work)


def expire_pending() -> None:
    """pending -> expired once past the stamped response_deadline (`<=` matches
    BQ's `CURRENT_TIMESTAMP() >= deadline`). Only rows with a deadline set."""
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

    _write("expire_pending", work)


def void_pending() -> None:
    """All pending -> reassigned (the full-reassign tombstone step)."""
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

    _write("void_pending", work)


def insert_pending(rows: list[dict]) -> None:
    """Bulk-insert freshly-assigned pending rows. Each row: assignment_id,
    review_uid, order_id, operator_email, chain_name, platform, days_left,
    response_deadline (may be None).

    Commits PER CHUNK so a 40-80k-row cron insert doesn't hold locks / a pooled
    connection for the whole batch. ON CONFLICT (assignment_id) DO NOTHING makes
    a re-run idempotent. On failure: rollback, close, and RAISE (authoritative)
    — partial progress from earlier chunks stays committed, which is fine given
    the idempotent conflict clause.
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
    except Exception:
        if session is not None:
            try:
                session.rollback()
            except Exception:
                pass
        logger.exception("insert_pending failed (partial, %d rows)", len(rows))
        raise
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass


# ── ops_log writes ────────────────────────────────────────────────────────────

def log_action(
    review_uid: str, platform: str, chain_name: str, action: str,
    operator_email: str, performed_by: str, remarks: str = "",
) -> None:
    """Insert one audit row into reengage_ops_log. Same signature as the old
    BigQuery log_action so call sites are unchanged."""
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

    _write("log_action", work)


def log_actions_bulk(entries: list[dict]) -> None:
    """Bulk variant of log_action. Each entry: review_uid, platform, chain_name,
    action, operator_email, performed_by, remarks."""
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

    _write("log_actions_bulk", work)


# ── Assignment reads (write-coupled) ──────────────────────────────────────────

def fetch_already_assigned_uids() -> set[str]:
    """UIDs the cron should skip re-ingesting: reviews with a pending / completed
    / auto_resolved row in the last 14 days. PG-native replacement for the BQ
    version (reads must be fresh, so this hits Postgres directly, not the CDC
    mirror).

    NOTE: window is a rolling `now() - 14 days` vs the BQ version's midnight-
    aligned `CURRENT_DATE - 14`; slightly more inclusive (skips marginally more
    UIDs), which is the safe direction for a dedup gate.

    SCOPE: this is called ONLY on `full_reassign=False` runs
    (assignment_manager.py:93 / focused_assignment_manager.py:70). The scheduled
    8 AM cron POSTs `{"full_reassign": true}`, which voids all pending and
    rebuilds the queue from `fetch_reviews_14d()` (BigQuery) WITHOUT calling this
    — so the scheduled cron does not depend on PG assignment history at all.

    REQUIRES (only for a manual `full_reassign=False` trigger): PG must hold
    >=14 days of assignment history, else reviews present only in BQ are
    re-ingested and re-assigned (duplicate pending rows, since insert_pending's
    ON CONFLICT is on the fresh-uuid assignment_id, not review_uid). Backfill
    BQ->PG before relying on this path or before flipping the cron default."""
    def work(session: Session):
        return session.execute(
            text("""
                SELECT DISTINCT review_uid FROM reengage_assignments
                WHERE status IN ('pending', 'completed', 'auto_resolved')
                  AND assigned_at >= now() - interval '14 days'
            """)
        ).fetchall()
    session = None
    try:
        session = get_pg_session()
        rows = work(session)
        return {r[0] for r in rows if r[0]}
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
