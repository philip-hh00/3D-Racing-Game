"""Der Schalter für Streckenvorschläge muss bei den Gästen ankommen.

Gemeldet am 07.08.2026: „Wenn der Host die Streckenfreigabe mit dem Button
aktiviert, dann passiert bei den anderen Usern nur die Beschreibung im Feld,
aber es wird ihnen kein Button angezeigt, um ihre Strecken hochzuladen — erst
nachdem der Host eine Strecke hochgeladen hat."

**Was passierte.** Der Host verteilt ``offers_enabled`` in seinen Einstellungen;
die kommen beim Gast als ``LOBBY_STATE`` an und landen in ``_gp_view``. Der
**gezeichnete Text** liest direkt daraus — deshalb änderte sich die
Beschreibung sofort. Die **Knöpfe** dagegen entstehen in ``_build_gp_group``,
und die wurde auf diesem Weg nie gerufen: gebaut wurde beim Betreten der
Übersicht, beim Serienende und bei ``OFFER_LIST``. Letzteres kommt erst, wenn
jemand wirklich eine Strecke hochlädt — genau das hat der Fund beschrieben.

Ein Gast sah damit „Vorschläge: An" und keinen Weg, etwas anzubieten. Wer
zuerst hochlädt, muss der Host sein, obwohl der Schalter das Gegenteil
verspricht.

**Warum nicht einfach bei jedem Zustand neu bauen.** Weil ein Neubau die
Fokusgruppe zurücksetzt — und der Host schickt seine Einstellungen bei jeder
Kleinigkeit. Der Fokus spränge dann laufend nach oben. Gebaut wird deshalb
genau dann, wenn sich die Sichtbarkeit wirklich ändert.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from tests.test_layout_regeln import _ShellAttrappe  # noqa: E402


@pytest.fixture
def gast(monkeypatch):
    """Ein Gast, der in der Grand-Prix-Übersicht steht."""
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
    seite._is_host = False
    seite._players = [
        {"slot": 0, "name": "Host", "lobby_ready": True, "vehicle": "rookie"},
        {"slot": 1, "name": "Gast", "lobby_ready": False, "vehicle": "drifter"},
    ]
    seite._enter_gp_overview()
    yield seite, olp
    grand_prix.cancel()


def _zustand(seite, **einstellungen) -> None:
    """Einen ``LOBBY_STATE`` des Hosts zustellen."""
    grund = {"gp_active": True, "gp_phase": "overview",
             "gp_race": 1, "gp_total": 3, "gp_standings": []}
    grund.update(einstellungen)
    seite._on_net({"source": "tcp", "data": {
        "type": "LOBBY_STATE", "players": seite._players,
        "mode": "Grand Prix", "settings": grund}})


def _aktionen(seite) -> set[str]:
    """Die Aktionsnamen aller Knöpfe, die der Gast gerade bedienen kann."""
    gruppe = getattr(seite, "_gp_group", None)
    if gruppe is None:
        return set()
    return {getattr(w, "action", "") for w in gruppe.widgets}


def test_der_gast_bekommt_den_anbieten_knopf_sobald_der_host_freigibt(gast):
    """Der gemeldete Fall — ohne dass vorher jemand etwas hochgeladen hat."""
    seite, _olp = gast

    _zustand(seite, offers_enabled=False)
    assert "offer_add" not in _aktionen(seite), \
        "solange der Host nicht freigegeben hat, gibt es nichts anzubieten"

    _zustand(seite, offers_enabled=True)

    assert seite._offers_aktiv(), "der Schalter ist beim Gast angekommen"
    assert "offer_add" in _aktionen(seite), (
        "der Gast sieht die Freigabe, aber keinen Knopf zum Anbieten — genau "
        "der Fund vom 07.08.2026")


def test_der_knopf_verschwindet_wieder_wenn_der_host_abschaltet(gast):
    """Die Gegenrichtung. Ein Knopf, der nach dem Abschalten stehen bleibt,
    schickt den Gast in eine Zurückweisung durch den Server."""
    seite, _olp = gast

    _zustand(seite, offers_enabled=True)
    assert "offer_add" in _aktionen(seite)

    _zustand(seite, offers_enabled=False)
    assert "offer_add" not in _aktionen(seite)


def test_ein_unveraenderter_zustand_baut_die_leiste_nicht_neu(gast):
    """Sonst springt der Fokus bei jeder Servernachricht nach oben.

    Der Host verteilt seine Einstellungen bei jeder Kleinigkeit. Würde jede
    davon die Leiste neu bauen, wäre die Bedienung mit Tastatur und Controller
    in der Übersicht unbrauchbar — dieselbe Sorte Fehler wie der zweite Fund
    vom 07.08.2026 in der Lobby.
    """
    seite, _olp = gast

    _zustand(seite, offers_enabled=True)
    gruppe_vorher = seite._gp_group
    seite._gp_group.index = len(seite._gp_group.widgets) - 1
    gewaehlt = seite._gp_group.index

    _zustand(seite, offers_enabled=True)          # nichts hat sich geändert

    assert seite._gp_group is gruppe_vorher, "die Leiste wurde neu gebaut"
    assert seite._gp_group.index == gewaehlt, "die Auswahl ist verrutscht"


def test_der_host_sieht_den_knopf_sofort_nach_dem_umlegen(gast):
    """Beim Host lief es schon richtig — festgehalten, damit es so bleibt."""
    seite, _olp = gast
    seite._is_host = True
    seite._offers_enabled = False
    seite._build_gp_group()
    assert "offer_add" not in _aktionen(seite)

    seite._offers_umschalten()

    assert seite._offers_enabled
    assert "offer_add" in _aktionen(seite)
