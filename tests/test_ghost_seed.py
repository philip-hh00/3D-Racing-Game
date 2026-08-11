"""Der Seed-Ghost: schnell erzeugt, und nie unbrauchbar abgelegt.

Gemeldet am 07.08.2026: „Nachdem ich eine Strecke erstellt habe, wollte ich
diese im Ghost-Mode fahren; dann hat das Loading ca. 2 min gedauert (sonst ca.
2 sec) und ich bin alleine gefahren ohne Ghost, obwohl im ersten Rennen der
Ghost von der KI übernommen werden soll."

Zwei Beobachtungen, zwei verschiedene Ursachen.

**Die zwei Minuten kommen nicht vom Rechnen.** Gemessen auf einer eigenen
Strecke mit 1026 Mittellinienpunkten: die Erzeugung des Seed-Ghosts dauert
**1,3 s**. Der Fortschrittsbalken wurde dabei **6871-mal** aufgerufen — einmal
je Simulationsschritt. Und ``RaceState._render_loading`` endet auf
``pygame.display.flip()``, das bei eingeschalteter Bildsynchronisierung bis
zum nächsten Bildwechsel wartet: 6871 Bilder bei 60 Hz sind **115 Sekunden**.
Die Ladezeit war also fast vollständig Warten auf den Bildschirm.

Warum es bei den mitgelieferten Strecken nicht auffiel: dort lag längst ein
Ghost, und der zweite Aufruf erzeugt keinen mehr. Ohne Ghost hätte auch das
Oval rund 45 Sekunden gebraucht.

**Der fehlende Ghost ist ein Vergiftungsproblem.** ``generate_seed_ghost``
gibt in zwei Fällen ein **leeres** ``GhostData()`` zurück — keine Startplätze,
kein Fahrzeug gebaut. Das wurde bedenkenlos gespeichert, und ab da meldete
``exists()`` einen Ghost, den es nicht gibt: nie wieder erzeugt, für immer kein
Ghost auf dieser Strecke. Eine einzige misslungene Erzeugung reichte.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.core import ghost  # noqa: E402

def _dichte_strecke(ziel: str) -> str:
    """Eine Strecke bauen, die so dicht abgetastet ist wie eine selbstgezeichnete.

    Gemessen am 07.08.2026: mitgelieferte Strecken haben 330 bis 434
    Mittellinienpunkte, im Editor gezeichnete **1026 bis 1428**. Nur bei dieser
    Dichte wird die Runde lang genug, dass die Erzeugung des Seed-Ghosts viele
    Simulationsschritte braucht — und genau daran hing der Fund.

    Gebaut statt gelesen: eigene Strecken liegen seit dem 08.08.2026 nicht mehr
    im Repo (sie gehoeren dem Spieler). Ein Test, der eine davon braucht, waere
    auf dem Bauknecht stillschweigend uebersprungen — und damit wertlos.
    """
    import json

    with open(os.path.join(_ROOT, "data", "tracks", "oval.json"),
              encoding="utf-8") as fh:
        daten = json.load(fh)

    def verdichten(punkte: list, faktor: int = 3) -> list:
        """Zwischenpunkte einfuegen, ohne den Verlauf zu aendern.

        Die Punkte stehen als ``{"x": …, "y": …}`` in der Datei — sie so
        zurueckzuschreiben ist wichtig, sonst liest ``Track._load`` sie nicht.
        """
        dichter = []
        n = len(punkte)
        for i in range(n):
            p1, p2 = punkte[i], punkte[(i + 1) % n]
            for k in range(faktor):
                anteil = k / faktor
                dichter.append({
                    "x": p1["x"] + (p2["x"] - p1["x"]) * anteil,
                    "y": p1["y"] + (p2["y"] - p1["y"]) * anteil,
                })
        return dichter

    for schluessel in ("centerline", "outer_wall", "inner_wall"):
        if daten.get(schluessel):
            daten[schluessel] = verdichten(daten[schluessel])
    daten["name"] = "Dichte Teststrecke"

    with open(ziel, "w", encoding="utf-8") as fh:
        json.dump(daten, fh)
    return ziel


@pytest.fixture
def dichte_strecke(tmp_path) -> str:
    """Der Pfad enthaelt ``custom`` — der Ghost-Schluessel haengt daran."""
    ordner = tmp_path / "custom"
    ordner.mkdir()
    return _dichte_strecke(str(ordner / "dichte_teststrecke.json"))


@pytest.fixture(autouse=True)
def _eigenes_ghostverzeichnis(monkeypatch, tmp_path):
    from src.core import paths
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)


# ---------------------------------------------------------------------------
# 1. Der Fortschritt darf das Laden nicht dominieren
# ---------------------------------------------------------------------------

def test_der_fortschritt_wird_nicht_je_simulationsschritt_gemeldet(dichte_strecke):
    """Der Kern des Funds.

    Jeder Aufruf kostet im Spiel ein gezeichnetes Bild **und** die Wartezeit
    auf den Bildwechsel. Über hundert Meldungen braucht kein Balken: mehr als
    100 Stufen kann er gar nicht zeigen.
    """
    from src.entities.vehicle_factory import VehicleFactory
    VehicleFactory.load_all_configs()

    aufrufe: list[int] = []
    ghost.generate_seed_ghost(dichte_strecke,
                              progress_callback=aufrufe.append)

    assert aufrufe, "gar keine Rueckmeldung waere auch falsch"
    assert len(aufrufe) <= 120, (
        f"{len(aufrufe)} Fortschrittsmeldungen — bei 60 Hz sind das "
        f"{len(aufrufe) / 60:.0f} s Warten auf den Bildschirm, allein fuer den "
        f"Balken")


def test_der_fortschritt_geht_vorwaerts_und_bis_ans_ende(dichte_strecke):
    """Ein Balken, der bei 40 % stehenbleibt, sieht aus wie ein Absturz."""
    from src.entities.vehicle_factory import VehicleFactory
    VehicleFactory.load_all_configs()

    aufrufe: list[int] = []
    ghost.generate_seed_ghost(dichte_strecke,
                              progress_callback=aufrufe.append)

    assert aufrufe == sorted(aufrufe), f"springt zurueck: {aufrufe[:20]}"
    assert aufrufe[0] <= 5, aufrufe[0]
    assert aufrufe[-1] >= 95, f"bleibt bei {aufrufe[-1]} % stehen"


# ---------------------------------------------------------------------------
# 2. Ein unbrauchbarer Ghost darf nicht liegenbleiben
# ---------------------------------------------------------------------------

def test_ein_leerer_ghost_wird_gar_nicht_erst_gespeichert():
    """Sonst blockiert eine einzige misslungene Erzeugung die Strecke fuer immer.

    ``generate_seed_ghost`` gibt bei fehlenden Startplaetzen ein leeres
    ``GhostData()`` zurueck. Gespeichert hiess das: ``exists()`` meldet einen
    Ghost, ``load()`` liefert einen ohne Punkte, gezeichnet wird nichts — und
    erzeugt wird auch nie wieder.
    """
    ghost.save("teststrecke", ghost.GhostData())

    assert not ghost.exists("teststrecke"), \
        "ein Ghost ohne Punkte liegt jetzt auf der Platte und blockiert"
    assert ghost.load("teststrecke") is None


def test_ein_brauchbarer_ghost_wird_gespeichert_und_gefunden():
    """Die Gegenprobe — sonst waere die einfachste Loesung, nie zu speichern."""
    echt = ghost.GhostData(lap_time=42.0, driver="Seed-Ghost",
                           samples=[[0.0, 1.0, 2.0, 0.0], [0.1, 3.0, 4.0, 0.1]])
    ghost.save("teststrecke", echt)

    assert ghost.exists("teststrecke")
    geladen = ghost.load("teststrecke")
    assert geladen is not None
    assert geladen.lap_time == 42.0
    assert len(geladen.samples) == 2


def test_eine_alte_vergiftete_datei_heilt_von_selbst(tmp_path):
    """Wer schon einen leeren Ghost auf der Platte hat, soll ihn loswerden.

    Die Datei stammt aus einer Fassung, die alles gespeichert hat. Sie jetzt
    nur nicht mehr zu **schreiben**, wuerde diesen Spielern nicht helfen —
    gelesen wird sie ja weiterhin.
    """
    import json

    pfad = ghost._ghost_path("kaputt")
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    with open(pfad, "w", encoding="utf-8") as fh:
        json.dump(ghost.GhostData().to_dict(), fh)

    assert os.path.isfile(pfad), "der Test prueft sonst nichts"
    assert not ghost.exists("kaputt"), \
        "die alte leere Datei gilt weiter als Ghost — sie wird nie ersetzt"
    assert ghost.load("kaputt") is None


# ---------------------------------------------------------------------------
# 3. Eine Quelle fuer die Strecke
# ---------------------------------------------------------------------------

def test_das_erste_zeitfahren_bekommt_seinen_ghost_und_legt_ihn_ab(
        monkeypatch, dichte_strecke):
    """Der gemeldete Fall von vorn bis hinten.

    Eine eigene Strecke, noch kein Ghost: das erste Zeitfahren muss einen
    erzeugen, ihn **in diesem Lauf** schon zeigen (sonst faehrt man das erste
    Mal gegen niemanden) und ihn unter dem Schluessel der gefahrenen Strecke
    ablegen.
    """
    from tests import spielhilfe

    spielhilfe.aufbau_bewahren(monkeypatch)
    spielhilfe.bus_isolieren(monkeypatch)
    spielhilfe.fahrzeuge_laden()

    schluessel = ghost.track_key(dichte_strecke)
    assert not ghost.exists(schluessel), "Vorbedingung: noch kein Ghost"

    rennen, _sm = spielhilfe.rennen_bauen(dichte_strecke, runden=1, feld=1,
                                          modus="Zeitfahren")
    try:
        assert rennen.ghost_player is not None, \
            "erstes Zeitfahren ohne Ghost — man faehrt gegen niemanden"
        daten = rennen.ghost_player.data
        assert daten.samples, "der Ghost hat keine Punkte"
        assert daten.lap_time > 0, daten.lap_time
        assert rennen.ghost_player.get_position(0.0) is not None

        assert ghost.exists(schluessel), \
            "der erzeugte Ghost wurde nicht abgelegt — beim naechsten Mal " \
            "wieder zwei Minuten warten"
    finally:
        spielhilfe.alles_schliessen()


def test_der_ghost_gehoert_zu_der_strecke_die_wirklich_gefahren_wird():
    """Rennen und Ghost lasen aus zwei verschiedenen Quellen.

    Das Rennen faehrt ``kwargs["track_path"]`` (mit ``data/tracks/oval.json``
    als Rueckfall), der Ghost las ``race_setup.current().track_path``. Alle
    Wege im Spiel setzen beides, der Fehler war also nie zu sehen — aber ein
    Weg, der es einmal vergisst, laesst den Spieler die eine Strecke fahren und
    zeigt ihm den Ghost einer anderen. Der faehrt dann durch die Landschaft.

    Geprueft wird an der Quelle: der Ghost-Schluessel muss aus dem Pfad
    kommen, den das Rennen selbst geladen hat.
    """
    import inspect

    from src.states.race_state import RaceState

    for methode in (RaceState.enter, RaceState._build_racing_lines_optimized):
        quelle = inspect.getsource(methode)
        # Nur der Abschnitt, der den Ghost-Schluessel bildet.
        for zeile in quelle.split("\n"):
            if "_ghost_track_key" in zeile or "generate_seed_ghost" in zeile \
                    or ("tk = " in zeile and "basename" in zeile):
                assert "setup.track_path" not in zeile, (
                    f"{methode.__name__}: der Ghost haengt an race_setup statt "
                    f"an der gefahrenen Strecke — {zeile.strip()}")
