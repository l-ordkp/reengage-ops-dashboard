"""One-time backfill of the first_seen ledger (action='first_seen' ops_log rows).

Seeds three eras so the ingested chart has no hole and no distorted days:

  1. Pre-focused era (first assignment before 2026-07-15 IST): the old
     algorithm assigned every scoped review on arrival, so
     MIN(assigned_at) per review_uid IS the arrival time. Stamped exactly.
  2. Focused-era gap (2026-07-15 onward): per-day arrival CSVs captured via
     BigQuery time-travel diffs before the 7-day window closed
     (exports/first_seen_backfill/day_YYYY-MM-DD.csv, columns
     arrival_day,platform,chain_name,review_uid). Stamped at 08:00 IST of
     the arrival day. Exact.
  3. Remainder (first assigned during the focused era but absent from the
     CSVs — e.g. arrivals in the few hours between the last old-algorithm
     run and the first snapshot boundary): stamped at MIN(assigned_at) as an
     approximation, labeled in remarks.

Reviews never assigned AND not in any CSV (e.g. arrivals after the last CSV
day) are deliberately left to the cron gate, which records them on its first
run — at most one day of drift for the deploy-day arrivals.

Idempotent: every phase skips review_uids that already have a first_seen row.
Run from repo root:  venv/bin/python scripts/backfill_first_seen.py [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from backend.clients.pg_client import get_pg_session  # noqa: E402

FIRST_SEEN_ACTION = "first_seen"
FOCUSED_CUTOVER_IST_DATE = "2026-07-15"  # first focused-algorithm run: Jul 15 08:02 IST
IST = timezone(timedelta(hours=5, minutes=30))
CSV_DIR = Path(__file__).resolve().parent.parent / "exports" / "first_seen_backfill"
CHUNK = 2000


def fetch_existing_first_seen_uids(session) -> set[str]:
    rows = session.execute(text(f"""
        SELECT review_uid FROM reengage_ops_log WHERE action = '{FIRST_SEEN_ACTION}'
    """)).fetchall()
    return {r[0] for r in rows if r[0]}


def insert_rows(session, rows: list[dict], dry_run: bool) -> None:
    """rows: review_uid, platform, chain_name, first_seen_at (tz-aware), remarks."""
    if dry_run or not rows:
        return
    sql = text("""
        INSERT INTO reengage_ops_log
            (entry_id, review_uid, platform, chain_name, action,
             operator_email, performed_by, remarks, processing_timestamp,
             created_at, updated_at)
        VALUES
            (:entry_id, :review_uid, :platform, :chain_name, :action,
             'system', 'backfill_first_seen', :remarks, :first_seen_at, :now, :now)
    """)
    now = datetime.now(timezone.utc)
    for i in range(0, len(rows), CHUNK):
        session.execute(sql, [{
            "entry_id": str(uuid.uuid4()),
            "review_uid": r["review_uid"],
            "platform": r.get("platform") or "",
            "chain_name": r.get("chain_name") or "",
            "action": FIRST_SEEN_ACTION,
            "remarks": r.get("remarks") or "",
            "first_seen_at": r["first_seen_at"],
            "now": now,
        } for r in rows[i:i + CHUNK]])
        session.commit()


def phase1_pre_focused(session, already: set[str], dry_run: bool) -> int:
    """MIN(assigned_at) before the focused cutover = exact arrival."""
    rows = session.execute(text(f"""
        SELECT review_uid,
               MIN(assigned_at) AS first_assigned_at,
               MIN(platform) AS platform,
               MIN(chain_name) AS chain_name
        FROM reengage_assignments
        GROUP BY review_uid
        HAVING MIN(assigned_at) < TIMESTAMP '{FOCUSED_CUTOVER_IST_DATE} 00:00:00+05:30'
    """)).fetchall()
    to_insert = [{
        "review_uid": r.review_uid,
        "platform": r.platform,
        "chain_name": r.chain_name,
        "first_seen_at": r.first_assigned_at,
        "remarks": "backfill: pre-focused first assignment (exact arrival)",
    } for r in rows if r.review_uid not in already]
    insert_rows(session, to_insert, dry_run)
    already.update(r["review_uid"] for r in to_insert)
    return len(to_insert)


def phase2_snapshot_csvs(session, already: set[str], dry_run: bool) -> int:
    """Time-travel capture CSVs: exact per-day arrivals for the focused era."""
    total = 0
    for csv_path in sorted(CSV_DIR.glob("day_*.csv")):
        with open(csv_path) as f:
            to_insert = []
            for record in csv.DictReader(f):
                uid = record["review_uid"]
                if uid in already:
                    continue
                arrival_ist = datetime.strptime(
                    record["arrival_day"], "%Y-%m-%d"
                ).replace(hour=8, tzinfo=IST)
                to_insert.append({
                    "review_uid": uid,
                    "platform": record["platform"],
                    "chain_name": record["chain_name"],
                    "first_seen_at": arrival_ist,
                    "remarks": "backfill: time-travel snapshot diff (exact arrival)",
                })
                already.add(uid)
        insert_rows(session, to_insert, dry_run)
        print(f"  {csv_path.name}: {len(to_insert)} rows")
        total += len(to_insert)
    return total


def phase3_focused_era_remainder(session, already: set[str], dry_run: bool) -> int:
    """Assigned during the focused era but absent from CSVs — approximate."""
    rows = session.execute(text(f"""
        SELECT review_uid,
               MIN(assigned_at) AS first_assigned_at,
               MIN(platform) AS platform,
               MIN(chain_name) AS chain_name
        FROM reengage_assignments
        GROUP BY review_uid
        HAVING MIN(assigned_at) >= TIMESTAMP '{FOCUSED_CUTOVER_IST_DATE} 00:00:00+05:30'
    """)).fetchall()
    to_insert = [{
        "review_uid": r.review_uid,
        "platform": r.platform,
        "chain_name": r.chain_name,
        "first_seen_at": r.first_assigned_at,
        "remarks": "backfill: focused-era first assignment (approximate arrival)",
    } for r in rows if r.review_uid not in already]
    insert_rows(session, to_insert, dry_run)
    already.update(r["review_uid"] for r in to_insert)
    return len(to_insert)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="report counts without writing")
    args = parser.parse_args()

    session = get_pg_session()
    try:
        already = fetch_existing_first_seen_uids(session)
        print(f"existing first_seen rows: {len(already)}")
        n1 = phase1_pre_focused(session, already, args.dry_run)
        print(f"phase 1 (pre-focused, exact): {n1}")
        n2 = phase2_snapshot_csvs(session, already, args.dry_run)
        print(f"phase 2 (snapshot CSVs, exact): {n2}")
        n3 = phase3_focused_era_remainder(session, already, args.dry_run)
        print(f"phase 3 (focused-era remainder, approximate): {n3}")
        print(f"{'DRY RUN — nothing written' if args.dry_run else 'DONE'}: "
              f"{n1 + n2 + n3} rows total")
    finally:
        session.close()


if __name__ == "__main__":
    main()
