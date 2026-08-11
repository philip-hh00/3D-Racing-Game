"""Die Startaufstellung muss auf der Strecke stehen — auch hinter einer Kurve.

Gemeldet am 08.08.2026: „Das erste Bauteil (Start- und Ziellinie) ist etwas
kurz nach hinten. Das bedeutet, wenn man direkt vor der Ziellinie, wo ja die
Startblöcke sind, eine scharfe Kurve setzt, dann starten die letzten beiden
Fahrzeuge in der Kurve."

**Nachgerechnet.** ``build_start_positions`` setzt die Autos in Abständen von
``60 + i * 100`` px hinter die Linie; bei sechs Startplätzen steht das letzte
also **560 px** dahinter. Eine Zelle im Editor ist ``CELL = 400`` px lang, und
``new_with_start`` legte genau **eine** Gerade hinter die Linie. Die Plätze 5
und 6 lagen damit jenseits dieses Bauteils — „die letzten beiden Fahrzeuge",
wie gemeldet.

Zwei Dinge waren daran falsch, und nur eines davon ist die Bauteillänge:

1. **Die Plätze folgten der Strecke nicht.** Gerechnet wurde entlang der
   Tangente am ersten Mittellinienpunkt — also geradeaus, egal wie die Strecke
   hinter der Linie wirklich verläuft. Ein Auto 560 px hinter einer Kurve stand
   damit zwangsläufig neben der Fahrbahn. Jetzt wird die Mittellinie
   rückwärts abgeschritten.
2. **Die Vorgabe war zu kurz.** Eine Gerade reicht für 400 px, gebraucht werden
   560. Eine neue Strecke bekommt jetzt zwei.

Der erste Punkt ist der wichtigere: er gilt auch für jemanden, der die Kurve
dort **absichtlich** hinsetzt.
"""
from __future__ import annotations

import math
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.track.track_builder import START_COUNT, build_start_positions  # noqa: E402


def _abstand_zur_mittellinie(punkt, mittellinie) -> float:
    """Kürzester Abstand von *punkt* zur Mittellinie (Strecke für Strecke)."""
    px, py = punkt
    bester = float("inf")
    n = len(mittellinie)
    for i in range(n):
        ax, ay = mittellinie[i]
        bx, by = mittellinie[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        laenge = dx * dx + dy * dy
        if laenge == 0:
            t = 0.0
        else:
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / laenge))
        qx, qy = ax + dx * t, ay + dy * t
        bester = min(bester, math.hypot(px - qx, py - qy))
    return bester


def _oval() -> list[tuple[float, float]]:
    """Die Mittellinie des mitgelieferten Ovals.

    Eine echte, **geschlossene** Runde. Ein erster Anlauf benutzte hier eine
    offene Punktreihe — rueckwaerts von Punkt 0 landet man dann beim letzten
    Punkt am anderen Ende der Strecke, und der Test scheiterte an seiner
    eigenen Vorlage statt am Code.
    """
    import json

    with open(os.path.join(_ROOT, "data", "tracks", "oval.json"),
              encoding="utf-8") as fh:
        daten = json.load(fh)
    return [(p["x"], p["y"]) for p in daten["centerline"]]


def _mit_kurve_hinter_der_linie() -> list[tuple[float, float]]:
    """Eine Strecke, die **direkt hinter** der Ziellinie scharf abknickt.

    Die Ziellinie liegt auf ``centerline[0]``; die Autos stehen dahinter, also
    am **Ende** der Liste. Genau dort steht hier die Kurve — der gemeldete Fall.
    """
    punkte: list[tuple[float, float]] = []
    # Vorwärts von der Linie weg: eine lange Gerade nach Osten.
    for i in range(30):
        punkte.append((i * 60.0, 0.0))
    # Dann zurück, aber über einen Bogen nach Norden — der Bogen endet
    # unmittelbar vor der Linie und ist damit das, was die Autos befahren.
    mitte_x, mitte_y, r = 30 * 60.0, 600.0, 600.0
    for k in range(24):
        w = -math.pi / 2 + k * (math.pi / 24)
        punkte.append((mitte_x + r * math.cos(w), mitte_y + r * math.sin(w)))
    for i in range(30):
        punkte.append((mitte_x - i * 60.0, 1200.0))
    mitte2_x, r2 = 0.0, 600.0
    for k in range(24):
        w = math.pi / 2 + k * (math.pi / 24)
        punkte.append((mitte2_x + r2 * math.cos(w), 600.0 + r2 * math.sin(w)))
    return punkte


# ---------------------------------------------------------------------------
# Die Rechnung
# ---------------------------------------------------------------------------

def test_der_letzte_startplatz_liegt_weiter_hinten_als_eine_zelle():
    """Die Zahl, um die es geht — festgehalten, damit sie nicht auseinanderläuft.

    Wer den Abstand der Startplätze ändert, muss die Vorgabe im Editor
    mitziehen; wer die Zellgröße ändert, ebenso.
    """
    from src.track.tile_track import CELL

    tiefste = 60.0 + (START_COUNT - 1) * 100.0
    assert tiefste == 560.0, tiefste
    assert tiefste > CELL, (
        "der Grid passt in eine Zelle — dann ist die Vorgabe im Editor "
        "grosszuegiger als noetig, und dieser Test darf weg")


@pytest.mark.parametrize("breite", [250.0, 300.0])
def test_auf_einer_normalen_strecke_stehen_alle_autos_auf_der_bahn(breite):
    """Der einfache Fall, damit der schwere nicht allein dasteht."""
    mittellinie = _oval()
    plaetze = build_start_positions(mittellinie, breite)

    assert len(plaetze) == START_COUNT
    for i, p in enumerate(plaetze):
        abstand = _abstand_zur_mittellinie((p["x"], p["y"]), mittellinie)
        assert abstand <= breite / 2, (i, abstand, breite / 2)


def test_hinter_einer_scharfen_kurve_steht_niemand_neben_der_strecke():
    """Der gemeldete Fall.

    Vorher wurde geradeaus zurückgerechnet: die hinteren Autos landeten dort,
    wo die Strecke längst abgebogen war.
    """
    mittellinie = _mit_kurve_hinter_der_linie()
    breite = 250.0
    plaetze = build_start_positions(mittellinie, breite)

    daneben = []
    for i, p in enumerate(plaetze):
        abstand = _abstand_zur_mittellinie((p["x"], p["y"]), mittellinie)
        if abstand > breite / 2:
            daneben.append(f"Platz {i + 1}: {abstand:.0f} px von der Mitte "
                           f"(erlaubt {breite / 2:.0f})")
    assert daneben == [], "\n".join(daneben)


def test_die_autos_schauen_in_fahrtrichtung():
    """Ein Auto, das quer steht, fährt beim Start gegen die Wand.

    Auf einer Kurve ist die Richtung nicht mehr die der Ziellinie — sie muss
    dort gelten, wo das Auto wirklich steht.
    """
    mittellinie = _mit_kurve_hinter_der_linie()
    plaetze = build_start_positions(mittellinie, 250.0)

    n = len(mittellinie)
    for i, p in enumerate(plaetze):
        w = math.radians(p["angle"])
        blick = (math.cos(w), math.sin(w))

        # Die Fahrtrichtung der Strecke **an der Stelle, wo das Auto steht**.
        j = min(range(n),
                key=lambda k: math.dist(mittellinie[k], (p["x"], p["y"])))
        hier, weiter = mittellinie[j], mittellinie[(j + 1) % n]
        dx, dy = weiter[0] - hier[0], weiter[1] - hier[1]
        laenge = math.hypot(dx, dy) or 1.0
        bahn = (dx / laenge, dy / laenge)

        # Skalarprodukt: 1 heisst gleiche Richtung, 0 quer, -1 entgegen.
        gleich = blick[0] * bahn[0] + blick[1] * bahn[1]
        assert gleich > 0.9, (
            f"Platz {i + 1} steht schief zur Fahrbahn (Skalarprodukt "
            f"{gleich:.2f}) — beim Start faehrt er gegen die Wand")


def test_die_autos_stehen_hintereinander_und_versetzt():
    """Zwei Reihen, abwechselnd links und rechts — das war schon richtig und
    soll es bleiben."""
    mittellinie = _oval()
    plaetze = build_start_positions(mittellinie, 250.0)

    ziel = mittellinie[0]
    abstaende = [math.dist((p["x"], p["y"]), ziel) for p in plaetze]
    assert abstaende == sorted(abstaende), abstaende

    # Die Seite ergibt sich aus dem Kreuzprodukt mit der Fahrtrichtung, nicht
    # aus dem Vorzeichen von y — die Ziellinie liegt selten waagerecht.
    def seite(p) -> int:
        w = math.radians(p["angle"])
        tx, ty = math.cos(w), math.sin(w)
        nah = min(mittellinie,
                  key=lambda m: math.dist(m, (p["x"], p["y"])))
        dx, dy = p["x"] - nah[0], p["y"] - nah[1]
        return 1 if tx * dy - ty * dx >= 0 else -1

    seiten = [seite(p) for p in plaetze]
    assert seiten[:4] == [seiten[0], -seiten[0], seiten[0], -seiten[0]], seiten


# ---------------------------------------------------------------------------
# Die Vorgabe im Editor
# ---------------------------------------------------------------------------

def test_eine_neue_strecke_hat_genug_gerade_hinter_der_linie():
    """Damit der Normalfall gar nicht erst in die Lage kommt.

    Die Rechnung oben rettet auch eine Kurve direkt hinter der Linie — aber
    eine **neue** Strecke soll ihre Autos auf gerader Fahrbahn aufstellen, ohne
    dass jemand daran denken muss.
    """
    from src.track.tile_track import CELL, TileTrackDraft

    entwurf = TileTrackDraft.new_with_start()
    start = entwurf.pieces[entwurf.start_piece_idx]

    # Die Bauteile hinter der Linie: dieselbe Zeile, kleinere Spalte.
    dahinter = [p for p in entwurf.pieces
                if p.row == start.row and p.col < start.col]
    assert all(p.kind == "straight" for p in dahinter), \
        [p.kind for p in dahinter]

    tiefste = 60.0 + (START_COUNT - 1) * 100.0
    assert len(dahinter) * CELL >= tiefste, (
        f"{len(dahinter)} Gerade(n) = {len(dahinter) * CELL:.0f} px hinter der "
        f"Linie, der hinterste Startplatz liegt aber {tiefste:.0f} px dahinter")


def test_der_name_einer_neuen_strecke_ist_uebersetzbar():
    """Gemeldet am 08.08.2026: der Vorgabename war fest deutsch.

    Er steht als Vorgabe im Namensfeld und wandert von dort in die Datei — auf
    Englisch stand dort trotzdem „Neue Strecke".
    """
    import json

    from src.track.tile_track import TileTrackDraft

    entwurf = TileTrackDraft.new_with_start()
    with open(os.path.join(_ROOT, "data", "i18n", "en.json"),
              encoding="utf-8") as fh:
        englisch = json.load(fh)

    assert entwurf.name in englisch, (
        f"der Vorgabename {entwurf.name!r} hat keine englische Fassung")
