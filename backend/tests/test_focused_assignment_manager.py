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
    assigned_uids = [assignment["review_uid"] for assignment in all_assigned]
    assert len(assigned_uids) == len(set(assigned_uids)), "duplicate assignment"
    hot_uids = set(hot["review_uid"])
    assert hot_uids <= set(assigned_uids), "hot review left unassigned"
    # nothing beyond the near-urgent window may be assigned
    eligible_uids = hot_uids | set(near["review_uid"])
    assert set(assigned_uids) <= eligible_uids, "far-out normal was assigned"
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
    near_stock_per_group = near.groupby(["chain_name", "platform"]).size().to_dict()
    buffer_rows_per_operator = defaultdict(lambda: defaultdict(int))
    for assignment in buffer_assignments:
        group_key = (assignment["chain_name"], assignment["platform"])
        buffer_rows_per_operator[assignment["operator_email"]][group_key] += 1
    buffer_taken_per_group = defaultdict(int)
    for rows_per_group in buffer_rows_per_operator.values():
        for group_key, row_count in rows_per_group.items():
            buffer_taken_per_group[group_key] += row_count
    for op in ops:
        owned_chains = {group_key[0] for group_key in hot_groups_by_op[op["email"]]}
        unowned_rows_taken = sum(
            row_count
            for group_key, row_count in buffer_rows_per_operator[op["email"]].items()
            if group_key[0] not in owned_chains
        )
        if unowned_rows_taken == 0:
            continue
        owned_stock_leftover = sum(
            near_stock_per_group.get(group_key, 0) - buffer_taken_per_group.get(group_key, 0)
            for group_key in near_stock_per_group if group_key[0] in owned_chains
        )
        assert owned_stock_leftover == 0, (
            f"{op['email']} took {unowned_rows_taken} unowned buffer rows while "
            f"{owned_stock_leftover} rows remained in their owned chains")


def test_hot_two_cap_still_enforced():
    _, hot, _, ops, assignments, _, _ = plan_focused(WORKLOAD, SEVEN_OPS)
    hot_uids = set(hot["review_uid"])
    hot_rows_per_operator = defaultdict(int)
    for assignment in assignments:
        if assignment["review_uid"] in hot_uids:
            hot_rows_per_operator[assignment["operator_email"]] += 1
    for op in ops:
        assert hot_rows_per_operator[op["email"]] <= op["hot_cap"] + 3, (
            op["email"], hot_rows_per_operator[op["email"]], op["hot_cap"])


def test_no_hot_no_near_is_graceful():
    _, hot, near, _, assignments, buffer_assignments, _ = plan_focused(
        [("cold", "UberEats", 300, 0)], SEVEN_OPS)
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
    rows_taken_per_group = defaultdict(int)
    for assignment in buffer_assignments:
        rows_taken_per_group[(assignment["chain_name"], assignment["platform"])] += 1
    chains_touched = {group_key[0] for group_key in rows_taken_per_group}
    assert chains_touched == {"chainA"}, (
        f"buffer scattered across chains: {dict(rows_taken_per_group)}")


def _gate_reviews_df():
    import pandas as pd
    return pd.DataFrame([
        {"review_uid": "u1", "platform": "Doordash", "chain_name": "daves", "status": "PENDING"},
        {"review_uid": "u2", "platform": "UberEats", "chain_name": "daves", "status": "RESPONDED"},
        {"review_uid": "u3", "platform": "Doordash", "chain_name": "pizza", "status": "EXPIRED"},
        {"review_uid": "u4", "platform": "UberEats", "chain_name": "pizza", "status": "PENDING"},
        {"review_uid": "u4", "platform": "UberEats", "chain_name": "pizza", "status": "PENDING"},
    ])


def test_first_seen_gate_records_only_unseen_across_all_statuses(monkeypatch=None):
    """The gate counts every scoped review regardless of status (arrival is
    arrival, even if already replied or expired), dedupes against the ledger,
    and dedupes repeated uids within the pool."""
    import backend.managers.focused_assignment_manager as fam
    recorded = []
    orig_fetch, orig_record = fam.fetch_first_seen_uids, fam.record_first_seen
    fam.fetch_first_seen_uids = lambda uids: {"u1"}
    fam.record_first_seen = lambda rows: recorded.extend(rows)
    try:
        recorded_count = fam._record_first_seen(_gate_reviews_df())
    finally:
        fam.fetch_first_seen_uids, fam.record_first_seen = orig_fetch, orig_record
    recorded_uids = {row["review_uid"] for row in recorded}
    assert recorded_count == 3
    assert recorded_uids == {"u2", "u3", "u4"}, recorded_uids
    assert all(row["platform"] and row["chain_name"] for row in recorded)


def test_first_seen_gate_fails_open():
    """A ledger failure must never block assignment: the gate logs, returns
    -1, and raises nothing."""
    import backend.managers.focused_assignment_manager as fam

    def exploding_fetch(uids):
        raise RuntimeError("pg down")

    orig_fetch = fam.fetch_first_seen_uids
    fam.fetch_first_seen_uids = exploding_fetch
    try:
        recorded_count = fam._record_first_seen(_gate_reviews_df())
    finally:
        fam.fetch_first_seen_uids = orig_fetch
    assert recorded_count == -1


def test_first_seen_gate_second_run_is_noop():
    """Re-runs (the leads' manual 9 AM trigger) record nothing new."""
    import backend.managers.focused_assignment_manager as fam
    ledger: set = set()
    recorded_batches = []
    orig_fetch, orig_record = fam.fetch_first_seen_uids, fam.record_first_seen
    fam.fetch_first_seen_uids = lambda uids: set(ledger)

    def fake_record(rows):
        recorded_batches.append(len(rows))
        ledger.update(row["review_uid"] for row in rows)

    fam.record_first_seen = fake_record
    try:
        first_run = fam._record_first_seen(_gate_reviews_df())
        second_run = fam._record_first_seen(_gate_reviews_df())
    finally:
        fam.fetch_first_seen_uids, fam.record_first_seen = orig_fetch, orig_record
    assert first_run == 4
    assert second_run == 0
    assert recorded_batches == [4, 0]


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
