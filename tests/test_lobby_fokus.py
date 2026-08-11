"""Der Fokus bleibt, wo er ist — auch in der Online-Lobby.

Gemeldet am 07.08.2026: „Wenn der User eine Änderung an den
Einstellungsbuttons macht, springt die Hervorhebung **immer noch** ganz oben
zum Game mode."

Das „immer noch" trifft es genau. Für die Einzelspieler- und die lokale
Mehrspieler-Lobby war das schon behoben: beide rufen
``FocusGroup.set_widgets(..., keep_focus=True)``. Die Online-Lobby baut ihre
Liste in ``_refresh_focus_group`` und wurde dabei übersehen — sie rief
``set_widgets`` ohne die Angabe, und der Vorgabewert ist ``False``, also
„Fokus auf das erste bedienbare Element". Das erste ist der Spielmodus.

Ausgelöst wird der Neubau bei jeder Änderung, die die Liste betreffen **könnte**
— Feldgröße, Fahrzeugklasse, jede Servernachricht mit geändertem Kader. Wer mit
Tastatur oder Controller die Rundenzahl verstellte, stand danach wieder oben und
musste sich zurückarbeiten. Mit der Maus fällt es kaum auf, mit dem Controller
ist es die halbe Bedienung.

Der Test prüft beides: dass der Fokus bleibt, wenn das Element noch da ist, und
dass er sinnvoll umzieht, wenn es verschwindet.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from tests.test_layout_regeln import _ShellAttrappe  # noqa: E402


@pytest.fixture
def host(monkeypatch):
    """Ein Gastgeber in der Lobby — er hat die meisten Einstellknöpfe."""
    from src.core import grand_prix
    from src.entities.vehicle_factory import VehicleFactory
    from src.net import server_probe
    from src.states.menu import online_lobby_page as olp
    from tests import spielhilfe

    spielhilfe.aufbau_bewahren(monkeypatch)
    VehicleFactory.load_all_configs()
    monkeypatch.setattr(server_probe, "start", lambda: None)
    monkeypatch.setattr(server_probe, "statuses", lambda: [])
    grand_prix.cancel()

    seite = olp.OnlineLobbyPage()
    seite.enter(_ShellAttrappe())
    seite._is_host = True
    seite._view = olp._LOBBY
    seite._players = [
        {"slot": 0, "name": "Host", "lobby_ready": False, "vehicle": "rookie"},
        {"slot": 1, "name": "Gast", "lobby_ready": False, "vehicle": "drifter"},
    ]
    seite._refresh_focus_group()
    yield seite
    grand_prix.cancel()


def test_der_fokus_bleibt_auf_dem_verstellten_element(host):
    """Der gemeldete Fall. Rundenzahl verstellen, Fokus soll dort bleiben."""
    gruppe = host._lobby_group
    gruppe.widgets.index(host._laps_stepper)     # muss überhaupt drin sein
    gruppe.index = gruppe.widgets.index(host._laps_stepper)

    host._refresh_focus_group()

    assert gruppe.focused is host._laps_stepper, (
        f"Fokus sprang von der Rundenzahl auf {gruppe.focused!r} — bei einer "
        f"Liste, in der die Rundenzahl unverändert steht")


def test_der_fokus_bleibt_auch_auf_der_fahrzeugklasse(host):
    """Zweites Element, damit der Test nicht an einem Einzelfall hängt."""
    gruppe = host._lobby_group
    gruppe.index = gruppe.widgets.index(host._class_stepper)

    host._refresh_focus_group()

    assert gruppe.focused is host._class_stepper


def test_ein_verschwundenes_element_gibt_den_fokus_ordentlich_ab(host):
    """Die Gegenprobe: was nicht mehr da ist, darf den Fokus nicht festhalten.

    Sonst zeigte die Gruppe auf ein Element, das niemand mehr sieht, und jede
    Taste liefe ins Leere.
    """
    gruppe = host._lobby_group
    fremd = object()
    gruppe.widgets = list(gruppe.widgets) + [fremd]
    gruppe.index = len(gruppe.widgets) - 1

    host._refresh_focus_group()

    assert gruppe.focused is not fremd
    assert getattr(gruppe.focused, "focusable", False), \
        "nach dem Umbau muss der Fokus auf einem bedienbaren Element sitzen"


def test_der_gast_behaelt_seinen_fokus_genauso(host):
    """Ein Gast hat weniger Knöpfe, aber dieselbe Erwartung."""
    host._is_host = False
    host._refresh_focus_group()
    gruppe = host._lobby_group

    bedienbar = [w for w in gruppe.widgets if getattr(w, "focusable", False)]
    assert len(bedienbar) > 1, "sonst prüft der Test nichts"
    ziel = bedienbar[-1]
    gruppe.index = gruppe.widgets.index(ziel)

    host._refresh_focus_group()

    assert gruppe.focused is ziel


def test_alle_drei_lobbys_halten_den_fokus_auf_dieselbe_weise():
    """Die Regel, nicht die drei Stellen.

    Einzelspieler und lokaler Mehrspieler waren schon richtig, die Online-Lobby
    nicht — genau so entstehen Meldungen mit „immer noch". Der Test hält fest,
    dass keine der drei ohne ``keep_focus`` neu aufbaut.
    """
    import ast

    ohne = []
    for name in ("lobby_page", "mp_lobby_page", "online_lobby_page"):
        pfad = os.path.join(_ROOT, "src", "states", "menu", f"{name}.py")
        with open(pfad, encoding="utf-8") as fh:
            baum = ast.parse(fh.read())
        for knoten in ast.walk(baum):
            if not isinstance(knoten, ast.Call):
                continue
            if not (isinstance(knoten.func, ast.Attribute)
                    and knoten.func.attr == "set_widgets"):
                continue
            # Über den Aufruf selbst geprüft, nicht über den Dateitext: eine
            # Datei kann ein ``keep_focus=True`` an einer Stelle haben und es
            # an der nächsten vergessen — und genau so ist der Fund entstanden.
            gesetzt = any(s.arg == "keep_focus" for s in knoten.keywords)
            if not gesetzt:
                ohne.append(f"{name}.py Zeile {knoten.lineno}")

    assert ohne == [], (
        "Diese Aufrufe bauen die Fokusliste neu auf, ohne über keep_focus zu "
        "entscheiden — der Fokus springt dort bei jeder Änderung nach oben:\n"
        + "\n".join(ohne))
