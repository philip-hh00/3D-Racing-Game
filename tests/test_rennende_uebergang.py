"""Kurzer Uebergang vor dem Ergebnisschirm.

Fund 08.08.2026: der Ergebnisschirm kam uebergangslos, sobald der Letzte ueber
die Linie fuhr oder DNF war — "als wuerde er einem ins Gesicht geschmissen".
Jetzt laeuft eine kurze Nachlaufzeit mit Ausblenden (RESULTS_OUTRO_SECONDS),
erst danach der Wechsel.

Die Tests halten die Regel — es gibt einen sichtbaren Ausblendvorgang, und der
Wechsel kommt erst danach — nicht die eine Dauer. Ein headless gefahrenes
Rennen belegt den ganzen Weg; zwei Einheitstests halten den Verlauf des
Schleiers fest.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.states.race_state import RaceState, RESULTS_OUTRO_SECONDS  # noqa: E402
from tests import spielhilfe  # noqa: E402


@pytest.fixture(autouse=True)
def _sauber(monkeypatch):
    spielhilfe.bus_isolieren(monkeypatch)
    spielhilfe.aufbau_bewahren(monkeypatch)
    yield
    spielhilfe.alles_schliessen()


# ---------------------------------------------------------------------------
# Der Schleier selbst (ohne Rennen)
# ---------------------------------------------------------------------------

def test_schleier_faengt_durchsichtig_an_und_endet_schwarz():
    r = RaceState.__new__(RaceState)
    r._outro_active = False
    r._outro_timer = 0.0
    assert r._outro_alpha() == 0                      # ohne Ausblenden nichts

    r._outro_active = True
    r._outro_timer = RESULTS_OUTRO_SECONDS
    assert r._outro_alpha() == 0                      # zu Beginn durchsichtig
    r._outro_timer = RESULTS_OUTRO_SECONDS / 2.0
    assert 110 < r._outro_alpha() < 145               # in der Mitte halb
    r._outro_timer = 0.0
    assert r._outro_alpha() == 255                    # am Ende voll schwarz


def test_ausblenden_starten_ist_idempotent():
    r = RaceState.__new__(RaceState)
    r._outro_active = False
    r._outro_timer = 0.0
    r._outro_rows = None
    r._starte_ausblenden(None)
    assert r._outro_active and r._outro_timer == RESULTS_OUTRO_SECONDS
    r._outro_timer = 0.3                              # laeuft schon
    r._starte_ausblenden(None)                        # zweiter Aufruf
    assert r._outro_timer == 0.3, "ein zweiter Aufruf darf nicht neu aufziehen"


# ---------------------------------------------------------------------------
# Der ganze Weg: Rennen fahren und den Uebergang beobachten
# ---------------------------------------------------------------------------

def test_ergebnisse_kommen_erst_nach_dem_ausblenden():
    """Regel: kein harter Schnitt. Vor dem Zustandswechsel gibt es einen
    Ausblendvorgang, der schwarz wird; der Wechsel kommt erst danach."""
    rennen, sm = spielhilfe.rennen_bauen("oval", runden=1, feld=3)

    verlauf: list[tuple[bool, int, int]] = []

    def aufzeichnen(r, _i):
        verlauf.append((r._outro_active, r._outro_alpha(), len(sm.wechsel)))

    spielhilfe.rennen_fahren(rennen, sekunden=240.0 + 30.0,
                             halt_am_ziel=False, je_bild=aufzeichnen)

    # Es gab ueberhaupt einen Wechsel.
    wechsel_bei = next((i for i, (_, _, n) in enumerate(verlauf) if n > 0), None)
    assert wechsel_bei is not None, "das Rennen hat nie gewechselt"

    # Vor dem Wechsel lief der Schleier — und zwar eine echte Weile, kein Bild.
    davor = verlauf[:wechsel_bei]
    aktive = [a for (aktiv, a, _) in davor if aktiv]
    assert aktive, "es gab keinen Ausblendvorgang vor dem Wechsel (harter Schnitt)"

    erwartet = RESULTS_OUTRO_SECONDS / (1.0 / 60.0)
    assert 0.8 * erwartet <= len(aktive) <= 1.2 * erwartet, (
        f"Ausblenddauer {len(aktive)} Bilder passt nicht zu ~{erwartet:.0f}")

    # Der Schleier zieht von durchsichtig nach schwarz und ist am Ende voll.
    assert min(aktive) <= 10
    assert max(aktive) >= 240, "der Schleier wurde nie richtig schwarz"
    # Unmittelbar vor dem Wechsel war das Bild (fast) schwarz.
    assert verlauf[wechsel_bei - 1][1] >= 240
