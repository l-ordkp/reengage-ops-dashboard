"""
TEMPORARY focused assignment: assign only what must be worked today.

Assigns every CRITICAL + URGENT review (two-cap balanced, whole-chain bundles
— same machinery as assignment_manager) plus a small near-urgent buffer per
operator (~150 normals at 48-72h to deadline, drawn from chains the operator
already owns so it costs no extra portal logins). Far-out normals are NOT
assigned at all — they stay visible in All Reviews and age into the pool on
later runs. Goal: an operator's queue contains only reviews that matter today,
so daily capacity is never spent on far-future work while urgent reviews
expire.

This intentionally lives in its own file and changes nothing in
assignment_manager.py: it is an experiment toggled by FOCUSED_ASSIGNMENT_MODE
(env, default on). Rollback = set FOCUSED_ASSIGNMENT_MODE=false, redeploy.
All shared mechanics (operator caps, chain bundling, forced splits with
urgency-interleaved dealing, PG dual-write choreography) are imported from
the existing modules, not reimplemented.
"""
from __future__ import annotations

import os
from collections import defaultdict

from backend.config import DUAL_WRITE_PG
from backend.managers.assignment_manager import (
    HOT_PRIORITIES,
    _build_group_plan,
    _build_operator_state,
    _materialize_assignments,
)
from backend.repositories.assignment_repository import (
    expire_stale_assignments,
    fetch_already_assigned_uids,
    insert_assignments,
    void_pending_assignments,
)
from backend.repositories.ops_log_repository import log_action
from backend.repositories.pg_reengage_repository import (
    dual_write_expire_pending,
    dual_write_insert_pending,
    dual_write_void_pending,
)
from backend.repositories.review_repository import fetch_reviews_14d
from backend.repositories.user_repository import fetch_approved_operators

# Near-urgent buffer: normals within this many hours of their deadline are
# eligible; each operator gets ~NEAR_BUFFER_PER_OPERATOR of them (weight-scaled
# for new operators) on top of their hot share.
NEAR_URGENT_MAX_HOURS = 72
NEAR_BUFFER_PER_OPERATOR = int(os.getenv("NEAR_BUFFER_PER_OPERATOR", "150"))


def run_focused_assignment(full_reassign: bool = True) -> dict:
    """Entry point — same contract and write choreography as run_assignment."""
    if DUAL_WRITE_PG:
        dual_write_expire_pending()
    expire_stale_assignments()
    if full_reassign:
        if DUAL_WRITE_PG:
            dual_write_void_pending()
        void_pending_assignments()

    reviews = fetch_reviews_14d()
    operators = fetch_approved_operators()

    if operators.empty:
        return {"error": "No approved operators found", "assigned": 0}
    if reviews.empty:
        return {"info": "No reviews to assign", "assigned": 0}

    pending = reviews[reviews["status"] == "PENDING"].copy()
    if pending.empty:
        return {"info": "No pending reviews", "assigned": 0}

    if not full_reassign:
        already = fetch_already_assigned_uids()
        pending = pending[~pending["review_uid"].isin(already)]
        if pending.empty:
            return {"info": "All pending reviews already assigned", "assigned": 0}

    pending = pending.sort_values("hours_left", ascending=True)
    hot = pending[pending["priority"].isin(HOT_PRIORITIES)]
    near = pending[
        (pending["hours_left"] > 48)
        & (pending["hours_left"] <= NEAR_URGENT_MAX_HOURS)
    ]

    if hot.empty and near.empty:
        return {"info": "No hot or near-urgent reviews to assign", "assigned": 0}

    # Pool caps computed over the hot pool only: total cap == hot cap since
    # the pool is all-hot; the buffer is bookkept separately below.
    ops = _build_operator_state(operators, len(hot), len(hot))
    if hot.empty:
        group_plan, groups = defaultdict(list), {}
    else:
        group_plan, groups = _build_group_plan(hot, ops)
    assignments = _materialize_assignments(ops, group_plan, groups)

    buffer_plan, buffer_groups = _build_buffer_plan(ops, near)
    buffer_assignments = _materialize_assignments(ops, buffer_plan, buffer_groups)
    assignments += buffer_assignments

    # Invariant: every hot review must be in the insert set. This is the
    # guarantee that makes "focused" safe — nothing urgent is ever left
    # unassigned. Refuse to write a plan that violates it.
    hot_uids = set(hot["review_uid"])
    planned_uids = {a["review_uid"] for a in assignments}
    missing = hot_uids - planned_uids
    if missing:
        return {
            "error": f"invariant violated: {len(missing)} hot reviews unassigned",
            "assigned": 0,
        }

    if assignments:
        if DUAL_WRITE_PG:
            dual_write_insert_pending(assignments)
        insert_assignments(assignments)

    unassigned_normals = len(pending) - len(assignments)
    summary = {
        "assigned": len(assignments),
        "hot_assigned": len(hot),
        "buffer_assigned": len(buffer_assignments),
        "unassigned_normals": unassigned_normals,
        "operators": len(ops),
        "groups": len(group_plan) + len(buffer_plan),
        "per_operator": {
            op["email"]: {
                "count": op["assigned_count"],
                "hot": op["hot_count"],
                "buffer": op.get("buffer_count", 0),
                "chain_platforms": len(set(op["groups"])),
                "chains": len(op["chains"]),
            }
            for op in ops
        },
    }
    log_action(
        review_uid="batch", platform="all", chain_name="all",
        action="assign_batch", operator_email="system", performed_by="system",
        remarks=(
            f"Assigned {len(assignments)} reviews to {len(ops)} operators "
            f"({len(hot)} hot + {len(buffer_assignments)} near-urgent buffer, "
            f"{unassigned_normals} normals left unassigned, focused algo)"
        ),
    )
    return summary


def _build_buffer_plan(ops: list[dict], near) -> tuple[dict, dict]:
    """Assign each operator ~NEAR_BUFFER_PER_OPERATOR near-urgent normals.

    Login-first selection order per operator:
      1. groups (chain x platform) the operator already holds hot work in —
         same portal session, zero extra logins;
      2. other platforms of chains they already own — same chain, one login;
      3. unowned groups, largest remaining first, so a shortfall is covered
         with the fewest new logins.
    Rows within a group go nearest-deadline first (groups dict is sorted by
    hours_left, and _materialize_assignments deals in that order).
    """
    if near.empty:
        return defaultdict(list), {}

    groups = {
        (chain, plat): grp.sort_values("hours_left").to_dict("records")
        for (chain, plat), grp in near.groupby(["chain_name", "platform"])
    }
    remaining = {g: len(rows) for g, rows in groups.items()}
    plan: dict = defaultdict(list)

    for idx, op in enumerate(ops):
        room = max(round(NEAR_BUFFER_PER_OPERATOR * op["weight"]), 0)
        op["buffer_count"] = 0
        owned_groups = set(op["groups"])
        owned_chains = op["chains"]

        def candidates():
            yield from (g for g in groups if g in owned_groups)
            yield from (g for g in groups
                        if g[0] in owned_chains and g not in owned_groups)
            for g in sorted(groups, key=lambda g: -remaining[g]):
                if g[0] not in owned_chains:
                    yield g

        for g in candidates():
            if room <= 0:
                break
            take = min(room, remaining[g])
            if take <= 0:
                continue
            plan[g].append((idx, take))
            remaining[g] -= take
            room -= take
            op["assigned_count"] += take
            op["buffer_count"] += take
            op["groups"].append(g)
            op["chains"].add(g[0])

    # Trim groups to just the dealt prefix count so _materialize_assignments
    # (which deals plan counts over the group's row list) sees consistent data.
    dealt_groups = {
        g: groups[g][: sum(count for _, count in plan[g])] for g in plan
    }
    return plan, dealt_groups
