"""Nacharbeit an Block G (29.07.2026).

1. In der Vorschlagsliste stand der Dateiname statt des Streckennamens.
2. Angeboten werden dürfen nur eigene Strecken — nicht das, was aus einem
   Rennstart in ``data/tracks/online`` gelandet ist.
3. Die 1-MB-Grenze wurde erst im Arbeitsfaden geprüft: die Seite meldete
   „Lade hoch …" und brach Sekunden später ab.
4. „Grand Prix verlassen" war bei einem Gast Kosmetik — er landete in der
   Lobby, wurde vom nächsten START wieder ins Rennen geholt und weiter
   gewertet. Die Warnung „Deine Wertung geht verloren" stimmte doppelt nicht.
5. Beendet der Gastgeber die Serie, während ein Gast in der Lobby steht,
   bekam der das nicht mit.
6. Die Auswahlliste ließ sich nur mit den Pfeiltasten bedienen.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.core import grand_prix, race_setup  # noqa: E402
from tests.test_gp_online_start import (  # noqa: E402
    SPIELER, _NetzAttrappe, _seite_in_der_uebersicht,
)


@pytest.fixture
def serie():
    grand_prix.cancel()
    race_setup.current().mode = "Grand Prix"
    yield grand_prix.start_series(3, 3)
    grand_prix.cancel()


@pytest.fixture
def netz(monkeypatch):
    from src.net import session
    n = _NetzAttrappe()
    monkeypatch.setattr(session, "get", lambda: n)
    return n


@pytest.fixture
def strecken(tmp_path, monkeypatch):
    """Eigene Strecken in einem leeren Nutzerverzeichnis."""
    import json
    from src.core import paths
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "bundle_dir", lambda: tmp_path)

    def anlegen(ordner: str, datei: str, name: str, fuellung: int = 0) -> str:
        ziel = tmp_path / "data" / "tracks" / ordner
        ziel.mkdir(parents=True, exist_ok=True)
        pfad = ziel / datei
        daten = {"name": name, "centerline": [{"x": 1.0 * i, "y": 2.0 * i}
                                              for i in range(5)]}
        if fuellung:
            daten["polster"] = "x" * fuellung
        pfad.write_text(json.dumps(daten), encoding="utf-8")
        return str(pfad)

    return anlegen


# ── 1. Streckenname statt Dateiname ────────────────────────────────────────

def test_liste_zeigt_den_streckennamen(serie, netz):
    from src.states.menu.gp_overview import GPOverview
    ui = GPOverview()
    schirm = pygame.Surface((1920, 1080))
    ui.draw(schirm, gewaehlt_key="oval", ist_host=True,
            gp_view={"gp_race": 1, "gp_total": 3, "gp_standings": []},
            players=SPIELER, eigener_slot=0, offers_aktiv=True,
            offers=[{"slot": 1, "name": "haus_v2.json", "title": "Hausstrecke",
                     "size": 4096, "from": "philip2"}])


def test_titel_reist_mit(serie, netz, strecken):
    """Der Empfänger kann den Namen nicht aus der Datei lesen — die hat er
    noch gar nicht."""
    pfad = strecken("custom", "haus_v2.json", "Hausstrecke")
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    seite._offer_upload(pfad)

    import time
    frist = time.time() + 3.0
    while not netz.hochgeladen and time.time() < frist:
        time.sleep(0.01)
    assert netz.hochgeladen == [(pfad, "Hausstrecke")]


def test_server_reicht_den_titel_durch():
    import inspect
    import sys as _s
    _s.path.insert(0, os.path.join(_ROOT, "server"))
    import server as srv
    quelle = inspect.getsource(srv.offer_list)
    assert '"title"' in quelle


# ── 2. Nur eigene Strecken ─────────────────────────────────────────────────

def test_nur_eigene_strecken_stehen_zur_wahl(serie, netz, strecken):
    strecken("custom", "Meine.json", "Meine Strecke")
    strecken("online", "Vom_Host.json", "Fremde aus dem Rennen")
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)

    namen = [t for t, _p, _g in seite._eigene_strecken()]
    assert namen == ["Meine Strecke"]


# ── 3. Größe vor dem Hochladen prüfen ──────────────────────────────────────

def test_zu_grosse_strecke_wird_gar_nicht_erst_gesendet(serie, netz, strecken):
    pfad = strecken("custom", "Riesig.json", "Riesig", fuellung=1024 * 1100)
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)

    seite._offer_upload(pfad)

    assert netz.hochgeladen == []
    assert "zu groß" in seite._msg


def test_zu_grosse_strecke_ist_in_der_liste_gesperrt(serie, netz, strecken):
    strecken("custom", "Riesig.json", "Riesig", fuellung=1024 * 1100)
    strecken("custom", "Klein.json", "Klein")
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    seite._open_offer_picker()

    knoepfe = {w.label.split("   ")[0]: w for w in seite._offer_pick_group.widgets
               if w.action.startswith("pick_") and w.action != "pick_cancel"}
    assert knoepfe["Riesig"].enabled is False
    assert knoepfe["Riesig"].hint, "gesperrt ohne Begründung"
    assert knoepfe["Klein"].enabled is True


# ── 4. Serie verlassen heißt Lobby verlassen ───────────────────────────────

def test_gast_verlaesst_beim_aussteigen_die_lobby(serie, netz, monkeypatch):
    from src.net import session
    from src.states.menu import online_lobby_page as olp
    getrennt = []
    monkeypatch.setattr(session, "clear", lambda: getrennt.append(True))

    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    seite._confirm_leave_gp()

    assert getrennt, "Gast bleibt verbunden und würde weiter gewertet"
    assert seite._view == olp._ROLE


def test_host_beendet_nur_die_serie(serie, netz, monkeypatch):
    """Beim Gastgeber bleibt die Lobby stehen — dort kann die Gruppe etwas
    Neues starten."""
    from src.net import session
    from src.states.menu import online_lobby_page as olp
    getrennt = []
    monkeypatch.setattr(session, "clear", lambda: getrennt.append(True))

    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    seite._confirm_leave_gp()

    assert getrennt == []
    assert seite._view == olp._LOBBY
    assert not grand_prix.is_active()


def test_warnung_behauptet_keinen_punktverlust_mehr(serie, netz):
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    seite._ask_leave_gp()
    text = str(seite._dialog.__dict__)
    assert "Wertung geht verloren" not in text


# ── 5. Gast erfährt vom Ende der Serie ─────────────────────────────────────

def _lobby_state(settings: dict) -> dict:
    return {"source": "tcp", "data": {
        "type": "LOBBY_STATE", "players": SPIELER, "mode": "Grand Prix",
        "settings": settings}}


def test_gast_in_der_lobby_erfaehrt_vom_serienende(serie, netz):
    from src.states.menu import online_lobby_page as olp
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    seite._view = olp._LOBBY
    seite._gp_view = {"gp_active": True}

    seite._on_net(_lobby_state({"gp_active": False}))

    assert "beendet" in seite._msg


def test_laufende_serie_holt_den_gast_in_die_uebersicht(serie, netz):
    """Auch ohne Phase im verteilten Stand — etwa nach einem Wiedereinstieg,
    bei dem der Gastgeber gerade nichts Neues verteilt."""
    from src.states.menu import online_lobby_page as olp
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    seite._view = olp._LOBBY
    seite._gp_ui = None

    seite._on_net(_lobby_state({"gp_active": True, "gp_standings": []}))

    assert seite._view == olp._GP_OVERVIEW


# ── 6. Auswahlliste mit Maus und Controller ────────────────────────────────

def _klick(knopf):
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                              pos=knopf.rect.center)


def _warte_auf_upload(netz, sekunden: float = 3.0):
    import time
    frist = time.time() + sekunden
    while not netz.hochgeladen and time.time() < frist:
        time.sleep(0.01)
    return netz.hochgeladen


def test_maus_waehlt_aus_und_der_knopf_laedt_hoch(serie, netz, strecken):
    """Ein Klick in eine Liste soll nicht sofort eine Datei verschicken."""
    pfad = strecken("custom", "Klein.json", "Klein")
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    seite._open_offer_picker()

    seite._offer_pick_event(_klick(seite._offer_rows[0]))
    assert seite._offer_pick is not None, "Liste schloss sich beim Auswählen"
    assert netz.hochgeladen == [], "Klick allein hat schon hochgeladen"
    assert seite._offer_pick_cursor == 0

    seite._offer_pick_event(_klick(seite._btn_offer_ok))
    assert seite._offer_pick is None
    assert _warte_auf_upload(netz)[0][0] == pfad


def test_abbrechen_knopf_laedt_nichts_hoch(serie, netz, strecken):
    strecken("custom", "Klein.json", "Klein")
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    seite._open_offer_picker()

    seite._offer_pick_event(_klick(seite._btn_offer_cancel))

    assert seite._offer_pick is None
    assert netz.hochgeladen == []


def test_controller_bedient_dieselbe_liste(serie, netz, strecken):
    """Der Gamepad-Übersetzer macht aus Steuerkreuz und A ganz normale
    Tastenereignisse — eine FocusGroup versteht die ohnehin."""
    strecken("custom", "Eins.json", "Eins")
    strecken("custom", "Zwei.json", "Zwei")
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    seite._open_offer_picker()

    runter = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN, unicode="",
                                mod=0, synthetic=True)
    seite._offer_pick_event(runter)
    assert seite._offer_pick_group.index == 1

    a_knopf = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="",
                                 mod=0, synthetic=True, pad_button=0)
    seite._offer_pick_event(a_knopf)
    # Auswählen rückt den Fokus auf "Hochladen" — zweimal A lädt hoch, ohne
    # sich durch die ganze Liste nach unten arbeiten zu müssen.
    assert seite._offer_pick_cursor == 1
    assert seite._offer_pick_group.focused is seite._btn_offer_ok

    seite._offer_pick_event(a_knopf)
    assert seite._offer_pick is None
    assert _warte_auf_upload(netz)[0][1] == "Zwei"


def test_zu_grosse_wahl_sperrt_den_hochladen_knopf(serie, netz, strecken):
    strecken("custom", "Riesig.json", "Riesig", fuellung=1024 * 1100)
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    seite._open_offer_picker()

    assert seite._btn_offer_ok.enabled is False
    assert seite._btn_offer_ok.hint


def test_abbrechen_laedt_nichts_hoch(serie, netz, strecken):
    strecken("custom", "Klein.json", "Klein")
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    seite._open_offer_picker()

    seite._offer_pick_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE,
                                               unicode="", mod=0))

    assert seite._offer_pick is None
    assert seite._offer_pick_group is None
    assert netz.hochgeladen == []


def test_lange_liste_scrollt_mit_dem_fokus(serie, netz, strecken):
    for i in range(12):
        strecken("custom", f"S{i}.json", f"Strecke {i}")
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    seite._open_offer_picker()

    sichtbar = [w for w in seite._offer_rows if w.rect.width > 0]
    assert len(sichtbar) == 8, "Fenster zeigt mehr als geplant"

    seite._offer_pick_group.index = 11
    seite._layout_offer_picker()
    assert seite._offer_rows[11].rect.width > 0, "gewählte Zeile liegt außerhalb"


def test_rad_blaettert_ohne_die_auswahl_mitzunehmen(serie, netz, strecken):
    """Wie in der Streckenliste daneben: Blättern und Auswählen sind zwei
    Dinge."""
    for i in range(12):
        strecken("custom", f"S{i}.json", f"Strecke {i}")
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    seite._open_offer_picker()

    seite._offer_pick_event(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-3))

    assert seite._offer_pick_offset == 3
    assert seite._offer_pick_cursor == 0, "Rad hat die Auswahl mitgenommen"
    assert seite._offer_pick_group.index == 0


def test_rad_laeuft_nicht_ueber_die_liste_hinaus(serie, netz, strecken):
    for i in range(10):
        strecken("custom", f"S{i}.json", f"Strecke {i}")
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    seite._open_offer_picker()

    seite._offer_pick_event(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=5))
    assert seite._offer_pick_offset == 0

    seite._offer_pick_event(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-99))
    assert seite._offer_pick_offset == 2, "unter der letzten Zeile bleibt Leerraum"


# ── Meldungen verschwinden wieder ──────────────────────────────────────────

def test_kurze_meldungen_laufen_ab(serie, netz, strecken):
    """„Gespeichert als …" und „Lade hoch …" beschreiben einen Zwischenstand.
    Ohne Ablauf standen sie den Rest der Sitzung in der Übersicht."""
    pfad = strecken("custom", "Klein.json", "Klein")
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)

    seite._offer_upload(pfad)
    assert "Klein" in seite._msg

    for _ in range(40):
        seite.update(1.0)
    assert seite._msg == "", "Meldung bleibt stehen"


def test_dauermeldungen_bleiben(serie, netz):
    """Nur was ausdrücklich kurz gemeint ist, verfällt — ein Fehlerzustand
    muss stehen bleiben, bis er behoben ist."""
    from src.states.menu import online_lobby_page as olp
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    seite._view = olp._LOBBY
    seite._players = []

    for _ in range(10):
        seite.update(1.0)
    assert "Mindestens 2 Spieler" in seite._msg


def test_neue_lobby_startet_ohne_alte_vorschlaege(serie, netz, strecken):
    """Die Seite überlebt einen Lobbywechsel. Ohne Zurücksetzen stand die
    Liste der vorigen Lobby weiter da — sichtbar nur für einen selbst, denn
    der Server hatte sie nie geschickt."""
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    seite._offers = [{"slot": 1, "name": "alt.json", "title": "Aus der alten Lobby",
                      "size": 4096, "from": "wer auch immer"}]
    seite._offer_busy = "alt"

    seite._on_net({"source": "tcp", "data": {
        "type": "JOIN_OK", "lobby_id": "NEU123", "slot": 2, "is_host": False}})

    assert seite._offers == []
    assert seite._offer_busy == ""


def test_offene_auswahlliste_ueberlebt_den_lobbywechsel_nicht(serie, netz, strecken):
    strecken("custom", "Klein.json", "Klein")
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    seite._open_offer_picker()
    assert seite._offer_pick is not None

    seite._on_net({"source": "tcp", "data": {
        "type": "JOIN_OK", "lobby_id": "NEU123", "slot": 2, "is_host": False}})

    assert seite._offer_pick is None


def test_bestaetigung_ersetzt_das_lade_hoch(serie, netz, strecken):
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    seite._offer_busy = "Hausstrecke"

    seite._on_net({"source": "tcp", "data": {
        "type": "OFFER_LIST",
        "offers": [{"slot": 1, "name": "haus.json", "title": "Hausstrecke",
                    "size": 4096, "from": "philip2"}]}})

    assert "liegt jetzt in der Lobby" in seite._msg
    assert seite._msg_until > 0, "auch die Bestätigung muss wieder verschwinden"
