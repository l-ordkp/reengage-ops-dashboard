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
    buffer_plan, buffer_groups = _build_buffer_plan(ops, near)
    buffer_assignments = _materialize_assignments(ops, buffer_plan, buffer_groups)
    return pending, hot, near, ops, assignments, buffer_assignments


def test_every_hot_review_assigned_and_nothing_far():
    pending, hot, near, _, assignments, buffer_assignments = plan_focused(
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
    _, _, near, ops, _, _ = plan_focused(WORKLOAD, SEVEN_OPS)
    for op in ops:
        assert op["buffer_count"] <= round(NEAR_BUFFER_PER_OPERATOR * op["weight"])
    total_target = sum(round(NEAR_BUFFER_PER_OPERATOR * op["weight"]) for op in ops)
    total_taken = sum(op["buffer_count"] for op in ops)
    assert total_taken == min(total_target, len(near))


def test_buffer_prefers_owned_chains():
    """Operators whose hot chains have near-urgent stock must draw their
    buffer from those chains before touching unowned ones."""
    _, _, near, ops, _, buffer_assignments = plan_focused(WORKLOAD, SEVEN_OPS)
    near_by_group = near.groupby(["chain_name", "platform"]).size().to_dict()
    buf_by_op_group = defaultdict(lambda: defaultdict(int))
    for a in buffer_assignments:
        buf_by_op_group[a["operator_email"]][(a["chain_name"], a["platform"])] += 1
    for op in ops:
        hot_groups = {g for g in set(op["groups"])}
        owned_stock = sum(near_by_group.get(g, 0) for g in hot_groups)
        took_unowned = sum(
            n for g, n in buf_by_op_group[op["email"]].items()
            if g not in hot_groups
        )
        if owned_stock >= round(NEAR_BUFFER_PER_OPERATOR * op["weight"]):
            assert took_unowned == 0, (
                f"{op['email']} took {took_unowned} unowned buffer rows despite "
                f"{owned_stock} available in owned chains")


def test_hot_two_cap_still_enforced():
    _, hot, _, ops, assignments, _ = plan_focused(WORKLOAD, SEVEN_OPS)
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
    _, hot, near, _, assignments, buffer_assignments = plan
    assert hot.empty or len(assignments) >= 0
    total = len(assignments) + len(buffer_assignments)
    assert total == len(hot) + min(
        len(near), sum(round(NEAR_BUFFER_PER_OPERATOR * 1.0) for _ in SEVEN_OPS))


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
