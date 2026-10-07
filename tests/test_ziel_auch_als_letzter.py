"""Online: jeder sieht seine eigene Zieldurchfahrt — nicht nur der Erste.

Playtest 06.10.2026: „Ist ein anderer Spieler schon im Ziel, bekomme ich keine
Zielanzeige, wenn ich selbst über die Linie fahre. Nur wer zuerst ankommt,
sieht sie."

Ursache: der Hinweis im HUD hing allein am **Warten** („ZIEL! Warte auf
weitere Fahrzeuge..."). Wer zuerst ankommt, wartet — er sieht ihn, solange die
anderen fahren. Wer als Letzter ankommt, meldet sein Ergebnis, der Server hat
damit alle beisammen und schickt die Gesamtwertung sofort zurück. Ein Bild
später war das Warten vorbei, das Ausblenden lief, und von der eigenen
Zieldurchfahrt war nichts zu sehen.

Jetzt steht nach jeder echten Zieldurchfahrt erst „ZIEL!" (ZIEL_ANZEIGE_SECONDS),
und das Ausblenden beginnt danach. Ein DNF bekommt diesen Moment nicht.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.states.race_state import (  # noqa: E402
    RaceState, RESULTS_OUTRO_SECONDS, ZIEL_ANZEIGE_SECONDS,
)
from tests import spielhilfe  # noqa: E402


@pytest.fixture(autouse=True)
def _sauber(monkeypatch):
    spielhilfe.bus_isolieren(monkeypatch)
    spielhilfe.aufbau_bewahren(monkeypatch)
    yield
    spielhilfe.alles_schliessen()


# ---------------------------------------------------------------------------
# Die Regel ohne Rennen
# ---------------------------------------------------------------------------

def _zustand() -> RaceState:
    r = RaceState.__new__(RaceState)
    r._outro_active = False
    r._outro_timer = 0.0
    r._outro_rows = None
    r._zielanzeige_rest = 0.0
    r._ausblenden_vorgemerkt = False
    return r


def test_ausblenden_wartet_auf_das_ende_von_ziel():
    r = _zustand()
    r._zielanzeige_rest = ZIEL_ANZEIGE_SECONDS
    zeilen = [{"name": "Philip", "position": 2}]

    r._starte_ausblenden(zeilen)
    assert not r._outro_active, "Ausblenden lief, waehrend ZIEL! noch stand"

    r._zielanzeige_fortschreiben(ZIEL_ANZEIGE_SECONDS / 2)
    assert not r._outro_active

    r._zielanzeige_fortschreiben(ZIEL_ANZEIGE_SECONDS)
    assert r._outro_active and r._outro_timer == RESULTS_OUTRO_SECONDS
    assert r._outro_rows is zeilen, "die Gesamtwertung ging unterwegs verloren"


def test_ohne_zieldurchfahrt_beginnt_das_ausblenden_sofort():
    """DNF oder Zuschauer: nichts aufzuhalten — wie vorher."""
    r = _zustand()
    r._starte_ausblenden(None)
    assert r._outro_active


# ---------------------------------------------------------------------------
# Der Fund selbst: Letzter im Online-Rennen
# ---------------------------------------------------------------------------

class _Relay:
    """Netzsitzung eines Gastes, dessen Mitspieler schon im Ziel ist.

    Auf RACE_RESULT antwortet sie wie der echte Server, wenn damit alle
    gemeldet haben: sofort mit der Gesamtwertung.
    """

    slot = 1
    ping_ms = 30.0

    def __init__(self) -> None:
        self._eingang: list[dict] = []
        self.gesendet: list[dict] = []

    def send_tcp(self, msg: dict) -> None:
        self.gesendet.append(msg)
        if msg.get("type") == "RACE_RESULT":
            zeilen = [{"position": 1, "name": "Host", "slot": 0, "finish_time": 50.0}]
            zeilen += [dict(z, position=2) for z in msg.get("rows", [])]
            self._eingang.append({"source": "tcp", "data": {
                "type": "RACE_RESULTS", "rows": zeilen}})

    def send_state(self, vehicles) -> None:
        pass

    def poll(self):
        while self._eingang:
            yield self._eingang.pop(0)

    def update(self, dt: float) -> None:
        pass

    def disconnect(self) -> None:
        pass


def test_wer_als_letzter_ankommt_sieht_seine_zieldurchfahrt(monkeypatch):
    from src.net import session

    relay = _Relay()
    monkeypatch.setattr(session, "get", lambda: relay)

    rennen, sm = spielhilfe.rennen_bauen("oval", runden=1, feld=1)
    rennen._online = True
    dt = 1.0 / 60.0
    # Bis zum Start: Ampel und Countdown laufen ab.
    for _ in range(int(6.0 / dt)):
        rennen.update(dt)
        if rennen.race_manager.state == "racing":
            break
    assert rennen.race_manager.state == "racing"

    # Der Mitspieler ist laengst durch; jetzt faehrt der Gast ueber die Linie.
    rennen.race_manager._record_finish(rennen.player)

    verlauf = []
    # Seit 1.1.0 zeigt der Movie-Modus noch NACHLAUF_S nach der Gesamtwertung.
    from src.render3d.tv_regie import NACHLAUF_S
    for _ in range(int((ZIEL_ANZEIGE_SECONDS + NACHLAUF_S + RESULTS_OUTRO_SECONDS + 2.0) / dt)):
        rennen.update(dt)
        hud = rennen.hud
        zeigt_ziel = hud._dnf_seconds is None and (
            getattr(hud, "_zielanzeige", False) or hud._waiting_for_field)
        verlauf.append((zeigt_ziel, rennen._outro_active, len(sm.wechsel)))
        if sm.wechsel:
            break

    assert any(m.get("type") == "RACE_RESULT" for m in relay.gesendet)
    assert rennen._online_results_rows is not None, "Gesamtwertung kam nicht an"

    ausblenden_bei = next(i for i, (_, aktiv, _) in enumerate(verlauf) if aktiv)
    gezeigt = sum(1 for z, _, _ in verlauf[:ausblenden_bei] if z)
    assert gezeigt * dt >= ZIEL_ANZEIGE_SECONDS - 0.1, (
        f"ZIEL! stand nur {gezeigt * dt:.2f} s, bevor das Ausblenden begann — "
        f"der Letzte sieht seine Zieldurchfahrt nicht")
    assert sm.wechsel, "danach ging es nicht in die Ergebnisse"


def test_der_hud_zeichnet_ziel_ohne_zu_warten():
    """Das HUD selbst: „ZIEL!" auch dann, wenn auf niemanden gewartet wird."""
    import pygame
    from src.hud.hud import HUD

    hud = HUD()
    gesehen: list[str] = []

    class _Schrift:
        def __init__(self, echt):
            self._echt = echt

        def render(self, text, *a, **k):
            gesehen.append(text)
            return self._echt.render(text, *a, **k)

    hud._overlay_body_font = _Schrift(hud._overlay_body_font)
    hud._zielanzeige = True
    hud._waiting_for_field = False
    hud._dnf_seconds = None
    hud._render_race_finish(pygame.Surface((1920, 1080), pygame.SRCALPHA), 1920, 1080, 1.0)
    assert "ZIEL!" in gesehen
