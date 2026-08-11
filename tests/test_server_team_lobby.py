"""Unit tests for the relay server's team/mode lobby rules.

Runs under pytest *and* standalone (``python tests/test_server_team_lobby.py``).
Everything here is socket-free: the balance helpers in ``server/server.py`` are
free functions on purpose, so a ``Lobby`` with stand-in ``ClientConn`` objects
is enough to exercise them.

The rules under test come from ``online_team_tt_plan.md`` §5:
  * AI fills the roster and is distributed so both teams end up equal.
  * Humans may sit unevenly — the AI compensates. When it cannot, the start is
    blocked instead of silently starting a lopsided race.
  * ``mode == "Rennen"`` bypasses the whole team machinery.
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "server"))

import server as srv  # noqa: E402  (path shim above must run first)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_lobby(roster: int = 4, mode: str = "Team-Zeitfahren",
               humans: tuple = (), ai: int = 0, ai_team: str = "A") -> "srv.Lobby":
    """Build a lobby with *humans* (a tuple of team letters) and *ai* bots."""
    lobby = srv.Lobby(lobby_id="TEST01")
    lobby.mode = mode
    lobby.roster_size = roster
    for i, team in enumerate(humans):
        conn = srv.ClientConn(slot=i, name=f"P{i}", reader=None, writer=None)
        conn.team = team
        lobby.clients[i] = conn
    lobby.settings["ai_roster"] = [
        {"name": f"KI{i}", "vehicle": "random", "difficulty": "medium", "team": ai_team}
        for i in range(ai)
    ]
    return lobby


def ai_teams(lobby) -> list:
    return [d["team"] for d in lobby.settings["ai_roster"]]


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------


def test_human_counts_ignores_ai():
    lobby = make_lobby(6, humans=("A", "B", "B"), ai=3)
    assert srv.human_counts(lobby) == (1, 2)


def test_ai_slot_count_is_roster_minus_humans():
    assert srv.ai_slot_count(make_lobby(6, humans=("A", "B"), ai=4)) == 4
    assert srv.ai_slot_count(make_lobby(4, humans=("A", "B", "A", "B"))) == 0


def test_team_counts_caps_an_overlong_ai_roster():
    """A host may push more roster entries than there are free slots; the
    surplus must not inflate the field."""
    lobby = make_lobby(4, humans=("A", "B"), ai=5)
    a, b = srv.team_counts(lobby)
    assert a + b == 4


def test_team_counts_treats_invalid_ai_team_as_a():
    lobby = make_lobby(4, humans=("A", "B"), ai=2)
    lobby.settings["ai_roster"][0]["team"] = "Z"
    del lobby.settings["ai_roster"][1]["team"]
    a, b = srv.team_counts(lobby)
    assert (a, b) == (3, 1)


# ---------------------------------------------------------------------------
# AI normalisation
# ---------------------------------------------------------------------------


def test_two_humans_split_evenly_gets_one_ai_each():
    lobby = make_lobby(4, humans=("A", "B"), ai=2)
    srv.normalize_ai_teams(lobby)
    assert ai_teams(lobby) == ["A", "B"]
    assert srv.team_balance_info(lobby) == {"A": 2, "B": 2, "ok": True}


def test_three_humans_all_on_a_pushes_every_bot_to_b():
    lobby = make_lobby(6, humans=("A", "A", "A"), ai=3)
    srv.normalize_ai_teams(lobby)
    assert ai_teams(lobby) == ["B", "B", "B"]
    assert srv.team_balance_info(lobby)["ok"]


def test_uneven_humans_are_compensated_by_ai():
    """2 humans on A, roster 6 → 1 bot joins A, 3 join B."""
    lobby = make_lobby(6, humans=("A", "A"), ai=4)
    srv.normalize_ai_teams(lobby)
    assert ai_teams(lobby) == ["A", "B", "B", "B"]
    assert srv.team_balance_info(lobby)["ok"]


def test_full_roster_with_lopsided_humans_cannot_be_fixed():
    """4 humans 3:1 leave no AI slot — the imbalance has to surface."""
    lobby = make_lobby(4, humans=("A", "A", "A", "B"))
    srv.normalize_ai_teams(lobby)
    assert srv.team_balance_info(lobby) == {"A": 3, "B": 1, "ok": False}


def test_normalisation_is_a_noop_when_it_would_not_add_up():
    """More humans on one side than the target team size: leave the roster
    alone so START_REQUEST reports the real imbalance."""
    lobby = make_lobby(4, humans=("A", "A", "A"), ai=1, ai_team="A")
    srv.normalize_ai_teams(lobby)
    assert ai_teams(lobby) == ["A"]
    assert srv.team_balance_info(lobby)["ok"] is False


def test_short_ai_roster_is_left_untouched():
    """Host has not pushed enough roster entries yet — never invent bots."""
    lobby = make_lobby(6, humans=("A", "B"), ai=1)
    srv.normalize_ai_teams(lobby)
    assert ai_teams(lobby) == ["A"]


def test_normalisation_is_idempotent():
    lobby = make_lobby(6, humans=("A", "A"), ai=4)
    srv.normalize_ai_teams(lobby)
    once = ai_teams(lobby)
    srv.normalize_ai_teams(lobby)
    assert ai_teams(lobby) == once


def test_manual_host_ai_teams_are_preserved_if_balanced():
    """If host manually sets AI teams to ["B", "A"] with 1 human A & 1 human B,
    normalize_ai_teams preserves ["B", "A"] because it is already balanced."""
    lobby = make_lobby(4, humans=("A", "B"), ai=2)
    lobby.settings["ai_roster"][0]["team"] = "B"
    lobby.settings["ai_roster"][1]["team"] = "A"
    srv.normalize_ai_teams(lobby)
    assert ai_teams(lobby) == ["B", "A"]
    assert srv.team_balance_info(lobby) == {"A": 2, "B": 2, "ok": True}



# ---------------------------------------------------------------------------
# Rennen mode bypasses everything
# ---------------------------------------------------------------------------



def test_rennen_mode_never_normalises_or_blocks():
    lobby = make_lobby(4, mode="Rennen", humans=("A", "A", "A"), ai=1)
    srv.normalize_ai_teams(lobby)
    assert ai_teams(lobby) == ["A"]              # untouched
    assert srv.team_balance_info(lobby)["ok"] is True


# ---------------------------------------------------------------------------
# Ready reset
# ---------------------------------------------------------------------------


def test_reset_lobby_ready_clears_everyone():
    lobby = make_lobby(4, humans=("A", "B"), ai=2)
    for conn in lobby.clients.values():
        conn.lobby_ready = True
    srv.reset_lobby_ready(lobby)
    assert not any(c.lobby_ready for c in lobby.clients.values())


# ---------------------------------------------------------------------------
# Roster / join limits
# ---------------------------------------------------------------------------


def test_roster_size_below_player_count_is_the_rejection_condition():
    """Mirrors the ROSTER_TOO_SMALL guard in the SET_SETTINGS handler."""
    lobby = make_lobby(6, humans=("A", "B", "A", "B", "A"))
    assert 4 < len(lobby.clients)      # shrinking to 4 must be refused
    assert not 6 < len(lobby.clients)  # staying at 6 is fine


def test_join_limit_follows_roster_size_not_max_slots():
    lobby = make_lobby(4, humans=("A", "B", "A", "B"))
    assert len(lobby.clients) >= lobby.roster_size
    assert lobby.roster_size < srv.MAX_SLOTS   # roster is the tighter gate


def test_online_results_returns_to_active_lobby_and_tab2():
    """Verify MenuShellState tab selection for online race results and active lobby page resume."""
    from src.states.menu.online_lobby_page import OnlineLobbyPage
    from src.states.menu.results_page import ResultsPage
    from src.states.menu_shell_state import MenuShellState
    from src.net import session, client

    class MockSM:
        pass

    shell = MenuShellState(MockSM())
    # Enter results with an online race config
    shell.enter(results=[{"name": "P1", "position": 1}], race_config={"is_online": True})
    assert shell.tab == 2  # Active tab must be 2 (MEHRSPIELER ONLINE)

    # Set up active mock session and lobby page
    mock_net = client.NetworkClient()
    mock_net._alive = True
    mock_page = OnlineLobbyPage()
    mock_page.enter(shell)
    mock_page._view = "lobby"
    session.set(mock_net)
    session.set_lobby_page(mock_page)

    res_page = shell.page_stack[0]
    assert isinstance(res_page, ResultsPage)
    # Simulate clicking "Zurück zur Lobby"
    res_page.group.handle_event = lambda evt: "lobby"
    res_page.handle_event(type("Event", (), {"type": -1})())


    assert shell.tab == 2
    assert shell.page_stack == [mock_page]
    assert mock_page._view == "lobby"

    # Cleanup mock session
    session.clear()


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
