"""Tests for the Team-Zeitfahren scoring rule.

Runs under pytest *and* standalone (``python tests/test_team_scoring.py``).

The rule (``online_team_tt_plan.md`` §1/A19, mirrored offline and online):
  * A team's result is the average of its drivers' times.
  * A driver that did not finish is scored as the last finisher's time plus a
    30 s penalty — dropping them would make quitting the fastest strategy.
  * A car the online host took over with AI counts normally, no extra malus.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.states.race_state import DNF_PENALTY, DNF_FALLBACK_TIME, score_team_rows


def row(team: str, finish: float | None = None, dnf: bool = False, **extra) -> dict:
    return {"team": team, "finish_time": finish, "dnf": dnf, **extra}


# ---------------------------------------------------------------------------
# Averages
# ---------------------------------------------------------------------------


def test_two_vs_two_average():
    rows = [row("A", 100.0), row("A", 110.0), row("B", 120.0), row("B", 90.0)]
    a, b = score_team_rows(rows)
    assert a == 105.0
    assert b == 105.0


def test_three_vs_three_average():
    rows = [row("A", 60.0), row("A", 62.0), row("A", 64.0),
            row("B", 70.0), row("B", 71.0), row("B", 72.0)]
    a, b = score_team_rows(rows)
    assert a == 62.0
    assert b == 71.0


def test_faster_average_wins_even_with_the_single_fastest_driver_on_the_other_side():
    """The point of the mode: one hero cannot carry a slow team."""
    rows = [row("A", 50.0), row("A", 200.0), row("B", 100.0), row("B", 100.0)]
    a, b = score_team_rows(rows)
    assert a == 125.0
    assert b == 100.0
    assert b < a


def test_draw_is_possible():
    rows = [row("A", 100.0), row("B", 100.0)]
    a, b = score_team_rows(rows)
    assert a == b


# ---------------------------------------------------------------------------
# DNF handling
# ---------------------------------------------------------------------------


def test_dnf_is_scored_as_last_finisher_plus_penalty():
    rows = [row("A", 100.0), row("A", None, dnf=True),
            row("B", 120.0), row("B", 130.0)]
    score_team_rows(rows)
    assert rows[1]["score_time"] == 130.0 + DNF_PENALTY


def test_missing_finish_time_without_the_dnf_flag_is_penalised_too():
    rows = [row("A", 100.0), row("A", None), row("B", 100.0), row("B", 100.0)]
    score_team_rows(rows)
    assert rows[1]["score_time"] == 100.0 + DNF_PENALTY


def test_dnf_hurts_the_average_but_does_not_erase_the_team():
    rows = [row("A", 100.0), row("A", None, dnf=True),
            row("B", 100.0), row("B", 100.0)]
    a, b = score_team_rows(rows)
    assert a == (100.0 + 130.0) / 2
    assert b == 100.0
    assert a > b


def test_all_dnf_falls_back_to_a_finite_number():
    rows = [row("A", None, dnf=True), row("B", None, dnf=True)]
    a, b = score_team_rows(rows)
    expected = DNF_FALLBACK_TIME + DNF_PENALTY
    assert a == expected
    assert b == expected


def test_quitting_costs_more_than_finishing_close_to_the_field():
    """Within a normal spread, giving up is the worse option."""
    finished = [row("A", 112.0), row("B", 100.0)]
    score_team_rows(finished)
    quit_rows = [row("A", None, dnf=True), row("B", 100.0)]
    score_team_rows(quit_rows)
    assert quit_rows[0]["score_time"] > finished[0]["score_time"]


def test_penalty_is_measured_against_the_field_not_the_quitters_own_pace():
    """Known property of the rule, asserted so a future change is deliberate:
    the DNF time is "last finisher + 30 s", so a driver who would have been
    more than 30 s behind the field can improve their team's average by not
    finishing. Online this barely matters because the host's AI takes the car
    over instead of letting it DNF; offline it is an accepted trade-off of
    keeping the penalty relative to the field."""
    finished = [row("A", 999.0), row("B", 100.0)]
    score_team_rows(finished)
    quit_rows = [row("A", None, dnf=True), row("B", 100.0)]
    score_team_rows(quit_rows)
    assert quit_rows[0]["score_time"] == 100.0 + DNF_PENALTY
    assert quit_rows[0]["score_time"] < finished[0]["score_time"]


# ---------------------------------------------------------------------------
# AI takeover
# ---------------------------------------------------------------------------


def test_ai_takeover_counts_fully_without_a_malus():
    """A19: the host's AI finishes the car of a dropped player; the time counts
    exactly like any other finish."""
    normal = [row("A", 105.0), row("B", 100.0)]
    score_team_rows(normal)
    taken = [row("A", 105.0, ai_takeover=True), row("B", 100.0)]
    a, _b = score_team_rows(taken)
    assert taken[0]["score_time"] == normal[0]["score_time"] == 105.0
    assert a == 105.0


def test_takeover_beats_leaving_the_car_behind():
    """The whole reason for the takeover: a dropped car that just vanishes
    would cost the team the full DNF penalty."""
    without = [row("A", None, dnf=True), row("A", 100.0), row("B", 100.0), row("B", 100.0)]
    a_without, _ = score_team_rows(without)
    with_ai = [row("A", 108.0, ai_takeover=True), row("A", 100.0),
               row("B", 100.0), row("B", 100.0)]
    a_with, _ = score_team_rows(with_ai)
    assert a_with < a_without


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_team_scores_zero_rather_than_dividing_by_zero():
    a, b = score_team_rows([row("A", 100.0)])
    assert a == 100.0
    assert b == 0.0


def test_no_rows_at_all():
    assert score_team_rows([]) == (0.0, 0.0)


def test_rows_without_a_team_are_ignored_by_both_averages():
    rows = [row("A", 100.0), {"finish_time": 10.0, "dnf": False}]
    a, b = score_team_rows(rows)
    assert a == 100.0
    assert b == 0.0


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------


def _run_all() -> int:
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in funcs:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {fn.__name__}: {type(exc).__name__}: {exc}")
    total = len(funcs)
    print(f"\n{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
