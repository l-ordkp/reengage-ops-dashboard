"""First-seen ledger gate — the 'ingested' metric's write path.

Records every scoped review the system has never seen before as an
action='first_seen' ops_log row. Lives in its own module so BOTH assignment
entrypoints (run_assignment and run_focused_assignment) call it: the metric
must not depend on which algorithm is active (FOCUSED_ASSIGNMENT_MODE) or
which entrypoint fires the cron (HTTP endpoint vs cron_assignment.py) —
otherwise a rollback or an entrypoint change silently zeroes the ingested
chart and both Slack alerts (PR #36 review)."""
from __future__ import annotations

import logging

from backend.repositories.pg_reengage_repository import (
    fetch_first_seen_uids,
    record_first_seen,
)

logger = logging.getLogger(__name__)


def record_first_seen_reviews(reviews) -> int:
    """Record never-before-seen scoped reviews in the first_seen ledger.

    Counts ALL scoped reviews regardless of status: a review that arrives
    already replied or expired still 'came into the system'.

    FAIL-OPEN: a ledger failure must never block assignment. Errors are logged
    and swallowed (returns -1); unrecorded reviews are still in tomorrow's
    pool, so they get counted a day late rather than lost. Idempotent per run
    (dedup lookup + unique-index backstop), so manual re-runs write ~0 rows.
    """
    try:
        candidates = (
            reviews[["review_uid", "platform", "chain_name"]]
            .dropna(subset=["review_uid"])  # a NaN uid must never reach the ledger
            .drop_duplicates("review_uid")
        )
        candidate_uids = candidates["review_uid"].tolist()
        seen_uids = fetch_first_seen_uids(candidate_uids)
        new_rows = candidates[~candidates["review_uid"].isin(seen_uids)]
        record_first_seen(new_rows.to_dict("records"))
        return len(new_rows)
    except Exception:
        logger.exception("first_seen ledger gate failed; continuing with assignment")
        return -1
