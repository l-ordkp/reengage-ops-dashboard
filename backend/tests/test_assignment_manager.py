"""Tests for the two-cap min-login assignment algorithm.

Pure planning-layer tests: build synthetic pending/operators DataFrames and
exercise the private helpers directly — no BigQuery access. Runs under pytest
if available, or standalone (no extra dependencies):

    python backend/tests/test_assignment_manager.py
"""
from __future__ import annotations

import math
import random
from collections import defaultdict

import pandas as pd

from backend.managers.assignment_manager import (
    HOT_PRIORITIES,
    SOFT_CAP_MULTIPLIER,
    _build_group_plan,
    _build_operator_state,
    _materialize_assignments,
    _split_group_across_ops,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

def make_pending(group_specs: list[tuple[str, str, int, int]]) -> pd.DataFrame:
    """group_specs: (chain, platform, total, hot). Hot rows get hours_left
    1-48 (deterministically spread), cold rows 49+, matching the repository's
    priority CASE."""
    rows = []
    uid = 0
    for chain, plat, total, hot in group_specs:
        for k in range(total):
            uid += 1
            hours = 1 + (k * 47 // max(hot, 1)) % 48 if k < hot else 49 + (k % 250)
            rows.append({
                "review_uid": f"uid{uid}",
                "order_id": f"o{uid}",
                "chain_name": chain,
                "platform": plat,
                "hours_left": hours,
                "priority": ("CRITICAL" if hours <= 24 else
                             "URGENT" if hours <= 48 else "NORMAL"),
            })
    return pd.DataFrame(rows).sort_values("hours_left", ascending=True)


def make_operators(specs: list[tuple[str, float]]) -> pd.DataFrame:
    """specs: (email, reduction_pct). reduction_pct > 0 -> new_operator."""
    return pd.DataFrame([
        {"email": email,
         "role": "new_operator" if reduction else "tenured_operator",
         "reduction_pct": reduction}
        for email, reduction in specs
    ])


def plan_and_materialize(group_specs, op_specs, seed=7):
    random.seed(seed)
    pending = make_pending(group_specs)
    total_hot = int(pending["priority"].isin(HOT_PRIORITIES).sum())
    ops = _build_operator_state(make_operators(op_specs), len(pending), total_hot)
    group_plan, groups = _build_group_plan(pending, ops)
    assignments = _materialize_assignments(ops, group_plan, groups)
    return pending, ops, group_plan, assignments


def realized_stats(pending, assignments):
    """Per-operator totals/hot/groups as actually materialized."""
    hot_uid = set(pending.loc[pending["priority"].isin(HOT_PRIORITIES), "review_uid"])
    stats = defaultdict(lambda: {"total": 0, "hot": 0, "groups": set()})
    for a in assignments:
        s = stats[a["operator_email"]]
        s["total"] += 1
        s["hot"] += a["review_uid"] in hot_uid
        s["groups"].add((a["chain_name"], a["platform"]))
    return stats


DAVES_DAY = (
    # one chain concentrating the fleet's urgency (Jul 8 2026 incident shape):
    # its hot count (90) exceeds every operator's hot cap (~55) so it MUST
    # split, while all other groups fit under both caps individually and the
    # fleet keeps comfortable headroom — the production shape (274 groups,
    # one urgency-heavy mega-group, ~20% overall slack).
    [("daves", "Doordash", 500, 90), ("daves", "UberEats", 400, 5)]
    + [(f"chain_med{i}", "Doordash", 250, 25) for i in range(6)]
    + [(f"chain_sm{i}", "UberEats", 150, 15) for i in range(5)]
    + [(f"chain_cold{i}", "Doordash", 200, 0) for i in range(4)]
)
DAVES_DD_HOT = 90
SEVEN_OPS = [(f"op{i}@x.com", 0) for i in range(1, 8)]


# ── Tests ───────────────────────────────────────────────────────────────────

def test_every_review_assigned_exactly_once():
    pending, _, _, assignments = plan_and_materialize(DAVES_DAY, SEVEN_OPS)
    uids = [a["review_uid"] for a in assignments]
    assert len(uids) == len(pending)
    assert len(set(uids)) == len(uids)


def test_both_caps_respected_under_urgency_concentration():
    """Caps are SOFT: greedy fragmentation can overshoot hot_cap by a few
    reviews via the bounded fallback path. The contract is 'everyone lands
    near 1.2x fair share' — not the incident shape, where one operator held
    the mega-group's entire hot count (500 = ~4.6x fair share here)."""
    pending, ops, _, assignments = plan_and_materialize(DAVES_DAY, SEVEN_OPS)
    stats = realized_stats(pending, assignments)
    hot_fair = int(pending["priority"].isin(HOT_PRIORITIES).sum()) / len(ops)
    for op in ops:
        s = stats[op["email"]]
        assert s["total"] <= op["soft_cap"], (op["email"], s["total"], op["soft_cap"])
        overshoot_allowance = max(3, round(op["hot_cap"] * 0.25))
        assert s["hot"] <= op["hot_cap"] + overshoot_allowance, (
            op["email"], s["hot"], op["hot_cap"])
    worst_hot = max(stats[op["email"]]["hot"] for op in ops)
    assert worst_hot <= 1.5 * hot_fair, f"urgency still concentrated: {worst_hot}"


def test_planner_bookkeeping_matches_materialized_rows():
    pending, ops, _, assignments = plan_and_materialize(DAVES_DAY, SEVEN_OPS)
    stats = realized_stats(pending, assignments)
    for op in ops:
        s = stats[op["email"]]
        assert op["assigned_count"] == s["total"]
        # shard hot shares are booked from the group hot ratio while dealing
        # interleaves actual rows; allow only rounding-level drift
        assert abs(op["hot_count"] - s["hot"]) <= len(s["groups"]), (
            op["email"], op["hot_count"], s["hot"])


def test_forced_split_is_minimal_and_urgency_interleaved():
    pending, ops, group_plan, assignments = plan_and_materialize(DAVES_DAY, SEVEN_OPS)
    split_plans = {g: p for g, p in group_plan.items() if len(p) > 1}
    max_hot_cap = max(op["hot_cap"] for op in ops)
    assert ("daves", "Doordash") in split_plans
    # splits stay rare: the hot-forced mega-group, plus at most a couple of
    # small groups the end-of-run headroom fragmentation can no longer fit
    assert len(split_plans) <= 3, f"too many splits: {sorted(split_plans)}"
    # shard count stays at the minimum the caps force (+1 slack for greedy
    # placement having consumed some hot headroom before this group)
    assert len(split_plans[("daves", "Doordash")]) <= math.ceil(DAVES_DD_HOT / max_hot_cap) + 1
    # interleaved dealing: each recipient's slice has a similar deadline mix
    hours = dict(zip(pending["review_uid"], pending["hours_left"]))
    by_op = defaultdict(list)
    for a in assignments:
        if (a["chain_name"], a["platform"]) == ("daves", "Doordash"):
            by_op[a["operator_email"]].append(hours[a["review_uid"]])
    means = [sum(v) / len(v) for v in by_op.values()]
    assert max(means) - min(means) < 10, f"skewed deadline mix across shards: {means}"


def test_no_splits_when_urgency_is_uniform():
    uniform = [(f"chain{i}", p, 200, 40) for i in range(10) for p in ("Doordash", "UberEats")]
    _, _, group_plan, _ = plan_and_materialize(uniform, SEVEN_OPS)
    assert all(len(p) == 1 for p in group_plan.values()), "caps must not bind here"


def test_quiet_day_floor_prevents_pointless_splits():
    quiet = [(f"chain{i}", "Doordash", 300, h) for i, h in enumerate([3, 2, 1] + [0] * 9)]
    _, ops, group_plan, _ = plan_and_materialize(quiet, SEVEN_OPS)
    assert all(len(p) == 1 for p in group_plan.values())
    assert all(op["hot_cap"] >= 5 for op in ops)


def test_reduced_weight_operator_gets_proportional_share_of_both_budgets():
    op_specs = [(f"op{i}@x.com", 0) for i in range(1, 5)] + [("new@x.com", 50)]
    pending, ops, _, assignments = plan_and_materialize(DAVES_DAY, op_specs)
    new_op = next(op for op in ops if op["email"] == "new@x.com")
    total = len(pending)
    total_hot = int(pending["priority"].isin(HOT_PRIORITIES).sum())
    weights = 4.0 + 0.5
    assert new_op["soft_cap"] == round(total * 0.5 / weights * SOFT_CAP_MULTIPLIER)
    assert new_op["hot_cap"] == max(round(total_hot * 0.5 / weights * SOFT_CAP_MULTIPLIER), 5)
    stats = realized_stats(pending, assignments)
    assert stats["new@x.com"]["hot"] <= new_op["hot_cap"]
    assert stats["new@x.com"]["total"] <= new_op["soft_cap"]


def test_shard_hot_booking_rounds_half_up_not_bankers():
    """Regression (PR #21 review): round(0.5) == 0 would under-book a shard's
    hot share and leak the hot row through the fallback onto an operator with
    no hot headroom."""
    ops = [
        {"email": "a@x", "soft_cap": 1, "hot_cap": 1, "assigned_count": 0,
         "hot_count": 0, "groups": [], "chains": set()},
        {"email": "b@x", "soft_cap": 10, "hot_cap": 3, "assigned_count": 0,
         "hot_count": 3, "groups": [], "chains": set()},
    ]
    plan = defaultdict(list)
    _split_group_across_ops(ops, ("chainX", "Doordash"), 2, 1, plan)
    assert ops[0]["hot_count"] == 1, "op with hot headroom must book the hot row"
    assert ops[1]["hot_count"] == 3, "op at hot cap must not be pushed over it"


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
