"""Rennen wirklich fahren, statt nur ueber sie zu reden.

Bis zum 07.08.2026 hat **kein einziger** Test ein Rennen gefahren. Geprueft
waren einzelne Bausteine — die KI-Geometrie, die Rundenzaehlung, die Wertung —
und jeder Fund, den ein Playtest gemeldet hat. Das Zusammenspiel aus Physik,
KI, Rundenzaehlung, Wertung und Zustandswechsel lief nur, wenn ein Mensch es
startete. ``coverage`` hat es in Zahlen gefasst: ``src/states/race_state.py``,
mit 1617 Zeilen die groesste Datei im Spiel, war zu **38 %** erreicht.

Was hier geprueft wird, sind keine Feinheiten, sondern die Zusagen, ohne die
ein Rennspiel keines ist:

* Das Rennen **endet**. Ein Rennen, das nie in ``finished`` kommt, sperrt den
  Spieler in einer Runde ein, die nicht aufhoert.
* Kein Auto verlaesst die Welt. Faellt eines durch eine Wand, ist es nach
  Sekunden Tausende Einheiten weit weg und nie wieder zu sehen.
* Keine Zahl wird ``nan``. Eine Physik, die einmal ``nan`` rechnet, kommt nicht
  zurueck — jede weitere Rechnung ergibt wieder ``nan``, und auf dem Schirm
  passiert einfach nichts mehr.
* Runden zaehlen nur vorwaerts, und nie ueber das Ziel hinaus.
* Kein Startplatz doppelt. pymunk drueckt zwei ineinander stehende Koerper mit
  voller Wucht auseinander — das Rennen beginnt dann mit einem Abflug.

Gefahren wird ueber **alle** mitgelieferten Strecken und **alle** Klassen; die
Liste wird gelesen, nicht geschrieben, damit eine neue Strecke von selbst
mitfaehrt.

Laufzeit: ein volles Rennen mit sechs Autos ueber eine Runde kostet rund drei
Sekunden — 20-mal schneller als in Echtzeit, weil nichts gezeichnet wird.
"""
from __future__ import annotations

import math
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.core import race_setup  # noqa: E402
from tests import spielhilfe  # noqa: E402

_STRECKEN = spielhilfe.mitgelieferte_strecken()
_KLASSEN = [k for k in race_setup.CLASSES if k != "Alle"]

#: Obergrenze fuer ein Rennen ueber eine Runde. Die langsamste Strecke braucht
#: mit der langsamsten Klasse deutlich weniger; wer hier anschlaegt, faehrt
#: nicht langsam, sondern gar nicht.
_FRIST = 240.0


@pytest.fixture(autouse=True)
def _sauber(monkeypatch):
    """Ein Rennen fuer sich allein — davor und danach.

    Zwei Vorkehrungen, beide durch einen Fehlschlag verdient:

    * **Ein leerer Ereignisbus.** ``EventBus`` ist prozessweit; nach rund 1480
      Tests haengen dort 88 fremde Rueckrufe, darunter Rennverwalter laengst
      abgeraeumter Rennen mit Rundenzaehlern zu denselben Fahrzeugnummern.
      Diese Datei war einzeln gruen und im vollen Lauf rot, mit einem Auto in
      Runde 5 von 3. Siehe ``spielhilfe.bus_isolieren``.
    * **Jedes Rennen schliessen.** Sonst laesst dieser Test genau die
      Rueckstaende zurueck, ueber die er selbst gestolpert ist.
    """
    spielhilfe.bus_isolieren(monkeypatch)
    spielhilfe.aufbau_bewahren(monkeypatch)
    yield
    spielhilfe.alles_schliessen()


def _pruefe_bild(rennen, nr: int) -> None:
    """Die Zusagen, die in **jedem** Bild gelten muessen.

    Als Rueckruf und nicht als Pruefung am Ende: ein Auto, das in Bild 400
    durch die Wand faellt, steht am Ende irgendwo im Nichts, und aus der
    Endlage laesst sich nicht mehr ablesen, wann es passiert ist. So schlaegt
    der Test beim ersten falschen Bild an und nennt dessen Nummer.
    """
    feld = _pruefe_bild.feld
    for fahrzeug in spielhilfe.fahrzeuge(rennen):
        koerper = fahrzeug.body
        x, y = koerper.position
        vx, vy = koerper.velocity
        assert spielhilfe.ist_endlich(x, y, vx, vy, koerper.angle), (
            f"Bild {nr}: Fahrzeug {fahrzeug.id} hat eine Zahl verloren "
            f"(pos={x},{y} v={vx},{vy} winkel={koerper.angle})")
        assert feld.collidepoint(int(x), int(y)), (
            f"Bild {nr}: Fahrzeug {fahrzeug.id} steht bei ({int(x)}, {int(y)}) "
            f"und damit ausserhalb von {tuple(feld)}")


# ---------------------------------------------------------------------------
# Ein Rennen je Strecke
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("strecke", _STRECKEN)
def test_ein_rennen_auf_jeder_strecke_kommt_zu_ende(strecke):
    rennen, sm = spielhilfe.rennen_bauen(strecke, runden=1, feld=6)
    _pruefe_bild.feld = spielhilfe.streckenfeld(rennen)

    dauer = spielhilfe.rennen_fahren(rennen, sekunden=_FRIST,
                                     je_bild=_pruefe_bild)

    assert rennen.race_manager.state == "finished", (
        f"{strecke}: nach {dauer:.0f} s Rennzeit immer noch "
        f"{rennen.race_manager.state}")
    assert rennen.race_manager.results, f"{strecke}: keine Ergebnisse"


@pytest.mark.parametrize("strecke", _STRECKEN)
def test_jede_strecke_hat_genug_startplaetze_fuer_das_volle_feld(strecke):
    """Sechs Spieler sind beworben — jede Strecke muss sie aufstellen koennen."""
    rennen, _ = spielhilfe.rennen_bauen(strecke, runden=1, feld=6)
    assert len(rennen.track.start_positions) >= 6, (
        f"{strecke} hat nur {len(rennen.track.start_positions)} Startplaetze")
    assert len(spielhilfe.fahrzeuge(rennen)) == 6, (
        f"{strecke}: {len(spielhilfe.fahrzeuge(rennen))} Autos statt 6")


@pytest.mark.parametrize("strecke", _STRECKEN)
def test_kein_startplatz_ist_doppelt_belegt(strecke):
    """Zwei Autos auf einem Platz heisst: pymunk sprengt sie auseinander.

    Genau das ist im lokalen Mehrspieler-Grand-Prix passiert (Playtest-Runde 4)
    — Spieler 1 stand nach dem ersten Lauf auf Wertungsplatz 1 und bekam damit
    denselben Gitterplatz wie Spieler 2, der fest auf 1 stand.
    """
    rennen, _ = spielhilfe.rennen_bauen(strecke, runden=1, feld=6)
    gitter = list(rennen._gitter)
    assert len(gitter) == len(set(gitter)), f"{strecke}: Gitter {gitter}"

    # Und die Autos stehen auch tatsaechlich auseinander.
    stellen = [tuple(round(k) for k in f.body.position)
               for f in spielhilfe.fahrzeuge(rennen)]
    assert len(stellen) == len(set(stellen)), f"{strecke}: {stellen}"


# ---------------------------------------------------------------------------
# Jede Fahrzeugklasse faehrt
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("klasse", _KLASSEN)
def test_jede_klasse_bringt_ihr_feld_ins_ziel(klasse):
    """Eine Klasse, die sich nicht bewegt, faellt sonst niemandem auf.

    Die KI bekommt ihre Fahrzeuge aus ``class_keys()``. Ein Fahrzeug mit
    kaputten Werten — kein Drehmoment, kein Grip — steht am Start und blockiert
    die Startaufstellung, waehrend das Rennen auf es wartet.
    """
    modelle = race_setup.CLASSES[klasse]
    # Ein KI-Auto je Modell, nicht drei zufaellige: so faehrt ueber die fuenf
    # Klassen hinweg jedes der 15 Fahrzeuge wirklich einmal.
    rennen, _ = spielhilfe.rennen_bauen("oval", runden=1,
                                        feld=1 + len(modelle), klasse=klasse,
                                        ki_fahrzeug=modelle)
    gefahren = {f.config_key for f in rennen.ai_vehicles}
    assert gefahren == set(modelle), (klasse, gefahren)

    _pruefe_bild.feld = spielhilfe.streckenfeld(rennen)
    spielhilfe.rennen_fahren(rennen, sekunden=_FRIST, je_bild=_pruefe_bild)

    verwalter = rennen.race_manager
    assert verwalter.state == "finished", f"{klasse}: {verwalter.state}"
    # Die KI muss ankommen. Der Mensch steht still, er darf es nicht.
    ki_ids = {f.id for f in rennen.ai_vehicles}
    angekommen = ki_ids & verwalter.finished_ids
    assert angekommen == ki_ids, (
        f"{klasse}: nicht im Ziel {sorted(ki_ids - angekommen)}")


@pytest.mark.parametrize("schwierigkeit", ["easy", "medium", "hard"])
def test_jede_schwierigkeit_faehrt_die_runde(schwierigkeit):
    rennen, _ = spielhilfe.rennen_bauen("oval", runden=1, feld=3,
                                        schwierigkeit=schwierigkeit)
    spielhilfe.rennen_fahren(rennen, sekunden=_FRIST)
    assert rennen.race_manager.state == "finished", schwierigkeit


def test_schwerer_faehrt_nicht_langsamer_als_leichter():
    """Die Stufen sollen etwas bedeuten.

    Kein Test auf einen genauen Abstand — die KI-Linie und die Startaufstellung
    streuen. Geprueft wird die Richtung: „schwer" darf nicht laenger brauchen
    als „einfach", sonst ist die Beschriftung im Menue eine Falschaussage.
    """
    zeiten = {}
    for stufe in ("easy", "hard"):
        # Dasselbe Auto in beiden Laeufen — sonst vergleicht der Test die
        # Fahrzeuge und nicht die Stufen.
        rennen, _ = spielhilfe.rennen_bauen("oval", runden=1, feld=2,
                                            schwierigkeit=stufe,
                                            ki_fahrzeug="rookie")
        spielhilfe.rennen_fahren(rennen, sekunden=_FRIST)
        verwalter = rennen.race_manager
        ki = rennen.ai_vehicles[0]
        eintrag = next((r for r in verwalter.results
                        if r["vehicle_id"] == ki.id), None)
        assert eintrag is not None, f"{stufe}: die KI ist nicht angekommen"
        assert not eintrag["dnf"], f"{stufe}: die KI kam nur als DNF an"
        zeiten[stufe] = eintrag["finish_time"]
        spielhilfe.schliessen(rennen)

    assert zeiten["hard"] <= zeiten["easy"] * 1.05, zeiten


# ---------------------------------------------------------------------------
# Runden und Wertung
# ---------------------------------------------------------------------------

def test_runden_zaehlen_nur_vorwaerts_und_nie_ueber_das_ziel_hinaus():
    """Ein Rundenzaehler, der zurueckspringt, verschenkt eine gefahrene Runde.

    Rueckwaerts ueber die Linie zu rollen ist der Weg dorthin — deshalb prueft
    ``LapTracker`` die Fahrtrichtung. Hier wird gehalten, dass die Zahl unter
    normaler Fahrt monoton bleibt.
    """
    rennen, _ = spielhilfe.rennen_bauen("oval", runden=3, feld=4)
    hoechststand: dict[int, int] = {}

    def wache(r, nr):
        for fid, zaehler in r.race_manager.lap_trackers.items():
            vorher = hoechststand.get(fid, 0)
            assert zaehler.current_lap >= vorher, (
                f"Bild {nr}: Fahrzeug {fid} faellt von Runde {vorher} "
                f"auf {zaehler.current_lap} zurueck")
            assert zaehler.current_lap <= r.race_manager.total_laps + 1, (
                f"Bild {nr}: Fahrzeug {fid} steht in Runde "
                f"{zaehler.current_lap} von {r.race_manager.total_laps}")
            hoechststand[fid] = zaehler.current_lap

    spielhilfe.rennen_fahren(rennen, sekunden=_FRIST * 2, je_bild=wache)
    assert rennen.race_manager.state == "finished"


def test_jede_gefahrene_rundenzeit_ist_eine_echte_zahl():
    """``inf`` als Bestzeit ist der Startwert und darf nie im Ergebnis landen."""
    rennen, _ = spielhilfe.rennen_bauen("oval", runden=2, feld=4)
    spielhilfe.rennen_fahren(rennen, sekunden=_FRIST * 2)

    for fid, zaehler in rennen.race_manager.lap_trackers.items():
        for zeit in zaehler.lap_times:
            assert math.isfinite(zeit) and zeit > 0, (fid, zaehler.lap_times)


def test_die_wertung_enthaelt_jedes_auto_genau_einmal():
    rennen, _ = spielhilfe.rennen_bauen("oval", runden=1, feld=6)
    spielhilfe.rennen_fahren(rennen, sekunden=_FRIST)

    ids = [f.id for f in spielhilfe.fahrzeuge(rennen)]
    # ``_standings`` mit Unterstrich: eine oeffentliche Fassung gibt es nicht,
    # und die Reihenfolge ist genau das, was hier geprueft werden soll.
    wertung = [f.id for f in rennen.race_manager._standings]
    assert sorted(wertung) == sorted(ids), (wertung, ids)


def test_das_rennen_wechselt_am_ende_in_die_ergebnisse():
    """Ohne diesen Wechsel bleibt der Spieler auf der leeren Strecke stehen.

    Der Wechsel kommt nicht im Zielbild, sondern ein paar Bilder spaeter: ein
    Auto ohne Zielankunft rollt erst noch aus (``DNF_COAST_SECONDS``), und der
    Spieler in diesem Test steht still, ist also genau so eines. Deshalb wird
    hier ueber das Ziel hinaus weitergefahren.
    """
    rennen, sm = spielhilfe.rennen_bauen("oval", runden=1, feld=3)
    spielhilfe.rennen_fahren(rennen, sekunden=_FRIST + 30.0,
                             halt_am_ziel=False)

    ziele = [a[0] for a, _ in sm.wechsel if a]
    assert ziele, "das Rennen hat nie einen Zustandswechsel angefordert"
    assert ziele[0] == "menu", ziele


# ---------------------------------------------------------------------------
# Zeitfahren
# ---------------------------------------------------------------------------

def test_zeitfahren_faehrt_allein_und_kommt_an():
    """Im Zeitfahren gibt es keine Gegner — und trotzdem ein Ende."""
    rennen, _ = spielhilfe.rennen_bauen("oval", runden=1, feld=1,
                                        modus="Zeitfahren")
    assert rennen.ai_vehicles == [], "im Zeitfahren faehrt niemand mit"
    _pruefe_bild.feld = spielhilfe.streckenfeld(rennen)
    # Kurz gehalten: das Zeitfahren endet nicht von selbst (ein Auto, das steht,
    # faehrt keine Runde zu Ende), und geprueft wird hier, dass Aufnahme und
    # Ghost-Wiedergabe ueberhaupt laufen — nicht wie lange.
    spielhilfe.rennen_fahren(rennen, sekunden=10.0, je_bild=_pruefe_bild)


# ---------------------------------------------------------------------------
# Der Zustand nach dem Rennen
# ---------------------------------------------------------------------------

def test_ein_rennen_raeumt_hinter_sich_auf():
    """``exit`` muss den Physikraum leeren.

    Bleiben Koerper stehen, sammelt jedes Rennen die Autos des vorigen ein —
    die Physik wird von Rennen zu Rennen langsamer, und irgendwann steht das
    naechste Feld in einem Haufen unsichtbarer Wracks.
    """
    rennen, _ = spielhilfe.rennen_bauen("oval", runden=1, feld=6)
    raum = rennen.physics_world.space
    vorher = len(raum.bodies)
    assert vorher > 0

    spielhilfe.rennen_fahren(rennen, sekunden=10.0)
    spielhilfe.schliessen(rennen)

    assert rennen.ai_vehicles == []
    # Der Raum selbst wird in exit() weggeraeumt (``physics_world`` ist danach
    # ``None``) — deshalb die vorher gemerkte Referenz.
    uebrig = len(raum.bodies)
    assert uebrig < vorher, f"nach exit() stehen noch {uebrig} Koerper im Raum"


def test_ein_rennen_meldet_sich_vom_ereignisbus_wieder_ab():
    """Sonst rechnet jedes gefahrene Rennen fuer immer mit.

    ``EventBus`` ist ein Singleton fuer den ganzen Prozess. Ein Rennen meldet
    sich beim Betreten fuer fuenf Ereignisse an; meldet es sich beim Verlassen
    nicht wieder ab, haengt es fuer den Rest der Sitzung darin — es kann nicht
    freigegeben werden, und bei jedem Zielereignis des **naechsten** Rennens
    laeuft auch sein Rueckruf.

    Aufgefallen beim Bau dieser Datei am 07.08.2026: die Meldung
    „Race completed!" erschien nach zwei Dutzend Testrennen zwei Dutzend Mal
    fuer ein einziges Ziel. Im Spiel greift ``exit()``, der Weg ist also
    richtig verdrahtet — aber nichts hat das bisher festgehalten.
    """
    vorher = spielhilfe.horcher_zahl()

    rennen, _ = spielhilfe.rennen_bauen("oval", runden=1, feld=3)
    waehrend = spielhilfe.horcher_zahl()
    assert waehrend > vorher, "das Rennen hat sich nirgends angemeldet"

    spielhilfe.rennen_fahren(rennen, sekunden=10.0)
    spielhilfe.schliessen(rennen)

    assert spielhilfe.horcher_zahl() == vorher, (
        f"nach exit() haengen {spielhilfe.horcher_zahl() - vorher} Rueckrufe "
        f"mehr am Bus als vorher")


def test_zwei_rennen_hintereinander_stoeren_sich_nicht():
    """Der haeufigste Weg im Spiel: fahren, Ergebnis, nochmal fahren."""
    erstes, _ = spielhilfe.rennen_bauen("oval", runden=1, feld=4)
    spielhilfe.rennen_fahren(erstes, sekunden=20.0)
    spielhilfe.schliessen(erstes)

    zweites, _ = spielhilfe.rennen_bauen("city", runden=1, feld=4)
    _pruefe_bild.feld = spielhilfe.streckenfeld(zweites)
    spielhilfe.rennen_fahren(zweites, sekunden=_FRIST, je_bild=_pruefe_bild)
    assert zweites.race_manager.state == "finished"
