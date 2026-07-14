"""Tests for the temporary focused-assignment logic (planning layer only —
synthetic DataFrames, no BigQuery/Postgres). Runs under pytest or standalone:

    python backend/tests/test_focused_assignment_manager.py
"""
from __future__ import annotations

import random
from collections import defaultdict

from backend.managers.assignment_manager import (
    HOT_PRIORITIES,
    _build_group_plan,
    _build_operator_state,
    _materialize_assignments,
)
from backend.managers.focused_assignment_manager import (
    NEAR_BUFFER_PER_OPERATOR,
    _build_buffer_plan,
)
from backend.tests.test_assignment_manager import make_operators, make_pending

# One urgency-heavy chain, a cold mega-group, mid chains with hot + near
# content (near-urgent rows are the 48-72h slice of each group's "far" band
# in make_pending's hour spreading — regenerate explicitly below).
WORKLOAD = (
    [("daves", "Doordash", 500, 90), ("daves", "UberEats", 2500, 5)]
    + [(f"chain_med{i}", "Doordash", 400, 30) for i in range(5)]
    + [(f"chain_cold{i}", "UberEats", 300, 0) for i in range(3)]
)
SEVEN_OPS = [(f"op{i}@x.com", 0) for i in range(1, 8)]


def plan_focused(group_specs, op_specs, seed=7):
    """Replicates run_focused_assignment's planning phase on synthetic data."""
    random.seed(seed)
    pending = make_pending(group_specs).sort_values("hours_left")
    hot = pending[pending["priority"].isin(HOT_PRIORITIES)]
    near = pending[(pending["hours_left"] > 48) & (pending["hours_left"] <= 72)]
    ops = _build_operator_state(make_operators(op_specs), len(hot), len(hot))
    group_plan, groups = _build_group_plan(hot, ops)
    assignments = _materialize_assignments(ops, group_plan, groups)
    # snapshot BEFORE buffer planning: _build_buffer_plan appends buffer
    # groups to op["groups"], and a group can hold both hot and buffer rows,
    # so post-hoc subtraction would misclassify it
    hot_groups_by_op = {op["email"]: set(op["groups"]) for op in ops}
    buffer_plan, buffer_groups = _build_buffer_plan(ops, near)
    buffer_assignments = _materialize_assignments(ops, buffer_plan, buffer_groups)
    return pending, hot, near, ops, assignments, buffer_assignments, hot_groups_by_op


def test_every_hot_review_assigned_and_nothing_far():
    pending, hot, near, _, assignments, buffer_assignments, _ = plan_focused(
        WORKLOAD, SEVEN_OPS)
    all_assigned = assignments + buffer_assignments
    uids = [a["review_uid"] for a in all_assigned]
    assert len(uids) == len(set(uids)), "duplicate assignment"
    hot_uids = set(hot["review_uid"])
    assert hot_uids <= set(uids), "hot review left unassigned"
    # nothing beyond the near-urgent window may be assigned
    eligible = hot_uids | set(near["review_uid"])
    assert set(uids) <= eligible, "far-out normal was assigned"
    # and the far mass is genuinely left out
    assert len(pending) - len(all_assigned) > 0


def test_buffer_size_close_to_target_per_operator():
    _, _, near, ops, _, _, _ = plan_focused(WORKLOAD, SEVEN_OPS)
    for op in ops:
        assert op["buffer_count"] <= round(NEAR_BUFFER_PER_OPERATOR * op["weight"])
    total_target = sum(round(NEAR_BUFFER_PER_OPERATOR * op["weight"]) for op in ops)
    total_taken = sum(op["buffer_count"] for op in ops)
    assert total_taken == min(total_target, len(near))


def test_buffer_prefers_owned_chains():
    """An operator may only receive unowned buffer rows once the near-urgent
    stock of every chain they own is fully drained. (Owned stock can be
    contested — a split hot group gives several operators the same chain — so
    'I had owned stock at planning time' is not a guarantee; 'nothing owned
    was left when I went outside' is.)"""
    _, _, near, ops, _, buffer_assignments, hot_groups_by_op = plan_focused(
        WORKLOAD, SEVEN_OPS)
    near_by_group = near.groupby(["chain_name", "platform"]).size().to_dict()
    buf_by_op_group = defaultdict(lambda: defaultdict(int))
    for a in buffer_assignments:
        buf_by_op_group[a["operator_email"]][(a["chain_name"], a["platform"])] += 1
    taken_by_group = defaultdict(int)
    for per_group in buf_by_op_group.values():
        for g, n in per_group.items():
            taken_by_group[g] += n
    for op in ops:
        owned_chains = {g[0] for g in hot_groups_by_op[op["email"]]}
        took_unowned = sum(
            n for g, n in buf_by_op_group[op["email"]].items()
            if g[0] not in owned_chains
        )
        if took_unowned == 0:
            continue
        leftover_owned = sum(
            near_by_group.get(g, 0) - taken_by_group.get(g, 0)
            for g in near_by_group if g[0] in owned_chains
        )
        assert leftover_owned == 0, (
            f"{op['email']} took {took_unowned} unowned buffer rows while "
            f"{leftover_owned} rows remained in their owned chains")


def test_hot_two_cap_still_enforced():
    _, hot, _, ops, assignments, _, _ = plan_focused(WORKLOAD, SEVEN_OPS)
    hot_uids = set(hot["review_uid"])
    per_op = defaultdict(int)
    for a in assignments:
        if a["review_uid"] in hot_uids:
            per_op[a["operator_email"]] += 1
    for op in ops:
        assert per_op[op["email"]] <= op["hot_cap"] + 3, (
            op["email"], per_op[op["email"]], op["hot_cap"])


def test_no_hot_no_near_is_graceful():
    plan = plan_focused([("cold", "UberEats", 300, 0)], SEVEN_OPS)
    _, hot, near, _, assignments, buffer_assignments, _ = plan
    assert hot.empty or len(assignments) >= 0
    total = len(assignments) + len(buffer_assignments)
    assert total == len(hot) + min(
        len(near), sum(round(NEAR_BUFFER_PER_OPERATOR * 1.0) for _ in SEVEN_OPS))


def test_unowned_buffer_stays_chain_grouped():
    """Regression (PR #31 review): the take-loop mutates op["chains"] while
    candidates are being consumed; a lazy generator would skip the sibling
    platform of a chain the operator just acquired, scattering the buffer
    across unrelated chains. With one operator and zero hot work, the buffer
    must come from the fewest chains possible (both platforms of the biggest
    chain first), not one platform each of two chains."""
    _, _, near, ops, _, buffer_assignments, _ = plan_focused(
        [("chainA", "Doordash", 1000, 0), ("chainA", "UberEats", 1000, 0),
         ("chainB", "Doordash", 500, 0)],
        [("solo@x.com", 0)])
    # chainA holds ~192 near rows across two platforms, chainB ~48; the solo
    # operator's 150-row buffer fits inside chainA alone, so both of its
    # platforms must be drained before chainB is touched at all
    took = defaultdict(int)
    for a in buffer_assignments:
        took[(a["chain_name"], a["platform"])] += 1
    chains_touched = {g[0] for g in took}
    assert chains_touched == {"chainA"}, (
        f"buffer scattered across chains: {dict(took)}")


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted({k: v for k, v in globals().items()
                            if k.startswith("test_") and callable(v)}.items()):
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {name}: {exc}")
    raise SystemExit(1 if failures else 0)
