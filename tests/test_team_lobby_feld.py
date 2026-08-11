"""Online-Lobby: Fahrzeugzahl und KI-Feld im Team-Zeitfahren (Playtest 04.08.2026).

Gemeldet: „Team Time Trail Einstellungen leicht verbuggt. Wenn auf diesen Modus
gewechselt wird, werden 4 Fahrer angezeigt … eine KI (hier kann ich auch Fahrzeug
und Schwierigkeit einstellen), die zwei weiteren Fahrer heißen einfach KI und
keine Einstellungen sind möglich. Wenn ich die vehicle anpasse zb. auf 4, dann
zeigt mir die Lobby nur noch mich selber als Fahrer und eine KI an."

Nachgestellt und **drei** Ursachen gefunden, alle dieselbe: über die
Fahrzeugzahl gab es drei Aussagen, und sie liefen auseinander.

1. ``_SIZE_OPTIONS[self._size_stepper.index]`` — im Team-Zeitfahren trägt der
   Stepper aber ``[4, 6]``. „4" stand auf Stellung 0 und ergab damit
   ``_SIZE_OPTIONS[0]`` = **2 Plätze**, „6" ergab 3. Genau der zweite Satz der
   Meldung. Dasselbe Muster wie der Absturz am Musikregler: Anzeige als Logik.
2. Der Moduswechsel konnte die Zahl mitziehen (3 und 5 gehen im Team-Zeitfahren
   nicht), ohne das KI-Feld neu zu besetzen. Übrig blieben Zeilen, die nur
   „KI 3", „KI 4" hießen und sich nicht einstellen ließen — der erste Satz.
3. Eine vom Server gemeldete Fahrzeugzahl bewegte den Stepper nie: die Liste
   wurde nur beim Wechsel getauscht, der Zeiger nur dabei gesetzt. Die
   Einstellung zeigte „4", während die Lobby mit zwei Plätzen lief.

Geprüft wird am echten Seitenobjekt mit echten Steppern — die Fehler entstanden
alle daraus, dass Widget und Zustand verschiedene Dinge sagten, und genau das
kann ein Testdoppel nicht zeigen.
"""
from __future__ import annotations

import os
import sys
import types

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.core import profile, race_setup  # noqa: E402


class _Schale:
    def __init__(self) -> None:
        self.state_machine = types.SimpleNamespace(transition=lambda *a, **k: None)

    def pop_page(self) -> None:
        pass

    def push_page(self, page) -> None:
        pass


@pytest.fixture
def seite(monkeypatch):
    p = profile.Profile(username="Host")
    p.save = lambda: None
    p.statistik = {}
    monkeypatch.setattr(profile, "_current", p, raising=False)
    monkeypatch.setattr(profile, "current", lambda: p)

    from src.net import server_probe, session
    monkeypatch.setattr(server_probe, "start", lambda: None)
    monkeypatch.setattr(server_probe, "statuses", lambda: [])
    monkeypatch.setattr(session, "get", lambda: types.SimpleNamespace(
        slot=0, ping_ms=24.0, send_tcp=lambda *a, **k: None,
        set_lobby=lambda *a, **k: None))

    race_setup.current().ai_roster.clear()

    from src.states.menu import online_lobby_page as olp
    s = olp.OnlineLobbyPage()
    s.enter(_Schale())
    s._view = olp._LOBBY
    s._is_host = True
    return s


def _lobby_state(s, *, modus="Rennen", groesse=4, spieler=1) -> None:
    """Was der Server schickt — Modus und Plätze sind serverseitig maßgeblich."""
    namen = ["Host", "Gast", "Dritter", "Vierter", "Fünfter", "Sechster"]
    s._on_net({"source": "tcp", "data": {
        "type": "LOBBY_STATE",
        "players": [{"slot": i, "name": namen[i], "is_host": i == 0,
                     "vehicle": "rookie", "team": "A" if i % 2 == 0 else "B",
                     "lobby_ready": False}
                    for i in range(spieler)],
        "roster_size": groesse, "mode": modus, "settings": {}}})


def _verstellen(s, stepper, richtung=pygame.K_RIGHT) -> None:
    """Wie im Spiel: Fokus auf den Stepper, dann eine Pfeiltaste.

    Bewusst nicht ``stepper.index = …`` von außen: ``_lobby_event`` merkt sich den
    alten Stand **vor** dem Ereignis, ein von Hand gesetzter Index sieht damit
    wie „nichts geändert" aus — und die ganze Auswertung liefe nicht.
    """
    s._lobby_group.index = s._lobby_group.widgets.index(stepper)
    s._lobby_event(pygame.event.Event(pygame.KEYDOWN, key=richtung, unicode="",
                                      mod=0))


def _auf_team(s) -> None:
    from src.states.menu import online_lobby_page as olp
    while s._selected_mode != "Team-Zeitfahren":
        vorher = s._selected_mode
        _verstellen(s, s._mode_stepper)
        assert s._selected_mode != vorher, "Modus lässt sich nicht wechseln"
    assert s._selected_mode in olp._MODE_KEYS


def _feld(s) -> list[tuple[str, bool]]:
    """Was in der Fahrerliste steht: (Name, einstellbar) je Zeile.

    Nachgebildet aus denselben Angaben, aus denen ``_draw_lobby`` zeichnet.
    """
    ai_roster = race_setup.current().ai_roster
    spieler = {p["slot"]: p for p in s._players}
    mit_widget = {slot for j, slot in enumerate(s._roster_free_slots)
                  if j < len(s._roster_ai_widgets)}
    zeilen = []
    for slot in range(s._roster_size):
        if slot in spieler:
            zeilen.append((spieler[slot]["name"], False))
            continue
        j = s._roster_free_slots.index(slot) if slot in s._roster_free_slots else -1
        name = ai_roster[j].name if 0 <= j < len(ai_roster) else f"KI {slot + 1}"
        zeilen.append((name, slot in mit_widget))
    return zeilen


# ---------------------------------------------------------------------------
# Der zweite Satz der Meldung: „4" ergab 2 Plätze
# ---------------------------------------------------------------------------
def test_vier_fahrzeuge_heisst_vier_plaetze(seite):
    _lobby_state(seite)
    _auf_team(seite)
    _verstellen(seite, seite._size_stepper)             # auf 6
    _verstellen(seite, seite._size_stepper, pygame.K_LEFT)   # zurück auf 4
    assert seite._size_stepper.value == "4"
    assert seite._roster_size == 4
    assert len(_feld(seite)) == 4


def test_sechs_fahrzeuge_heisst_sechs_plaetze(seite):
    _lobby_state(seite)
    _auf_team(seite)
    _verstellen(seite, seite._size_stepper)
    assert seite._size_stepper.value == "6"
    assert seite._roster_size == 6
    assert len(_feld(seite)) == 6


@pytest.mark.parametrize("schritte", [0, 1, 2, 3, 4])
def test_die_zahl_im_stepper_gilt_in_jedem_modus(seite, schritte):
    """Die Regel hinter allen drei Fehlern: was dasteht, muss gelten."""
    _lobby_state(seite)
    for modus_schritte in (0, 1, 2):
        for _ in range(modus_schritte):
            _verstellen(seite, seite._mode_stepper)
        for _ in range(schritte):
            _verstellen(seite, seite._size_stepper)
        assert int(seite._size_stepper.value) == seite._roster_size, \
            (seite._selected_mode, seite._size_stepper.options)


def test_kein_regler_rechnet_mit_der_falschen_liste():
    """Wer wieder ``_SIZE_OPTIONS[index]`` schreibt, holt den Fehler zurück — im
    Team-Zeitfahren trägt der Stepper eine andere Liste."""
    quelle = open(os.path.join(_ROOT, "src", "states", "menu",
                               "online_lobby_page.py"), encoding="utf-8").read()
    ereignis = quelle.split("def _lobby_event")[1].split("\n    def ")[0]
    assert "_SIZE_OPTIONS[" not in ereignis
    assert "_SIZE_OPTIONS_TEAM[" not in ereignis


# ---------------------------------------------------------------------------
# Der erste Satz: Zeilen, die nur „KI n" heißen
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("vorher", [2, 3, 4, 5, 6])
def test_nach_dem_moduswechsel_ist_jede_ki_einstellbar(seite, vorher):
    """Der Kern: aus 3 oder 5 Fahrzeugen wird im Team-Zeitfahren 4 — und dann
    braucht das Feld eine neue Besetzung."""
    _lobby_state(seite, groesse=vorher)
    _auf_team(seite)
    zeilen = _feld(seite)
    assert zeilen[0][0] == "Host"
    for name, einstellbar in zeilen[1:]:
        assert einstellbar, f"{name!r} lässt sich nicht einstellen"
        assert not name.startswith("KI "), f"Platzhaltername {name!r}"


@pytest.mark.parametrize("vorher", [3, 5])
def test_eine_ungerade_zahl_wird_auf_eine_gerade_gezogen(seite, vorher):
    """Sonst ließen sich die Teams nicht gleich groß besetzen."""
    _lobby_state(seite, groesse=vorher)
    _auf_team(seite)
    assert seite._roster_size in (4, 6)
    assert seite._roster_size % 2 == 0
    assert int(seite._size_stepper.value) == seite._roster_size


def test_eine_gerade_zahl_bleibt_beim_wechsel_stehen(seite):
    """6 geht im Team-Zeitfahren — sie darf nicht auf 4 zurückfallen."""
    _lobby_state(seite, groesse=6)
    _auf_team(seite)
    assert seite._roster_size == 6


def test_das_ki_feld_faellt_nach_dem_wechsel_nicht_auseinander(seite):
    """Feldgröße, freie Plätze, KI-Fahrer und Widgets müssen sich nach jedem
    Wechsel dieselbe Zahl merken."""
    _lobby_state(seite, groesse=3)
    _auf_team(seite)
    frei = seite._roster_size - len(seite._players)
    assert len(seite._roster_free_slots) == frei
    assert len(race_setup.current().ai_roster) == frei
    assert len(seite._roster_ai_widgets) == frei


def test_mit_einem_gast_bleibt_ein_platz_fuer_ihn(seite):
    """Ein echter Mitspieler bekommt keine KI-Regler über seine Zeile gelegt."""
    _lobby_state(seite, groesse=4, spieler=2)
    _auf_team(seite)
    zeilen = _feld(seite)
    assert [z[0] for z in zeilen[:2]] == ["Host", "Gast"]
    assert all(einstellbar for _n, einstellbar in zeilen[2:])
    assert len(race_setup.current().ai_roster) == 2


def test_zurueck_auf_rennen_gibt_die_ungeraden_zahlen_wieder_frei(seite):
    _lobby_state(seite)
    _auf_team(seite)
    assert seite._size_stepper.options == ["4", "6"]
    while seite._selected_mode != "Rennen":
        _verstellen(seite, seite._mode_stepper)
    assert seite._size_stepper.options == ["2", "3", "4", "5", "6"]
    assert int(seite._size_stepper.value) == seite._roster_size


# ---------------------------------------------------------------------------
# Der dritte Fund: der Server sagt eine Zahl, die Anzeige eine andere
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("groesse", [2, 3, 4, 5, 6])
def test_die_anzeige_folgt_der_zahl_vom_server(seite, groesse):
    """Sie stand auf dem Wert von vorher — beim Betreten also auf „4", ganz
    gleich wie viele Plätze die Lobby wirklich hatte."""
    _lobby_state(seite, groesse=groesse)
    assert seite._roster_size == groesse
    assert int(seite._size_stepper.value) == groesse


def test_ein_gast_sieht_dieselbe_zahl_wie_der_host(seite):
    seite._is_host = False
    _lobby_state(seite, groesse=6, spieler=2)
    assert int(seite._size_stepper.value) == 6
    assert seite._size_stepper.enabled is False, "einstellen darf nur der Host"


def test_eine_unmoegliche_zahl_vom_server_bringt_die_anzeige_nicht_um(seite):
    """Ein fremder oder älterer Server könnte im Team-Zeitfahren 5 schicken. Die
    Anzeige muss trotzdem etwas zeigen und darf nicht abstürzen."""
    _lobby_state(seite)
    _auf_team(seite)
    _lobby_state(seite, modus="Team-Zeitfahren", groesse=5)
    assert seite._size_stepper.value in ("4", "6")


# ---------------------------------------------------------------------------
# Zeichnen
# ---------------------------------------------------------------------------
def test_die_lobby_zeichnet_in_jedem_zustand(seite):
    from src.core.settings import SCREEN_HEIGHT, SCREEN_WIDTH
    schirm = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    for groesse in (2, 3, 4, 5, 6):
        _lobby_state(seite, groesse=groesse)
        seite.draw(schirm, pygame.Rect(0, 108, SCREEN_WIDTH, SCREEN_HEIGHT - 108))
        _auf_team(seite)
        seite.draw(schirm, pygame.Rect(0, 108, SCREEN_WIDTH, SCREEN_HEIGHT - 108))
        while seite._selected_mode != "Rennen":
            _verstellen(seite, seite._mode_stepper)
