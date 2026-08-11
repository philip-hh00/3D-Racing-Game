"""Klang im Rennen: Abstand, Panorama, Anlässe (Block C, §C6).

Geprüft wird die Rechnung, nicht die Wiedergabe. Genau dort stecken die Fehler,
die man im Spiel erst spät merkt — ein Fahrzeug, das aus der falschen Richtung
kommt, oder eines, das in fünf Bildschirmbreiten Entfernung noch mitbrummt.
"""
from __future__ import annotations

import os
import sys
import types

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.core import sfx_rennen as sr  # noqa: E402


def _auto(x: float, y: float, upm: float = 0.0, schlupf: float = 0.0,
          vid: int = 1, tempo: float = 0.0):
    koerper = types.SimpleNamespace(position=(x, y), slip_angle_deg=schlupf,
                                    velocity=(tempo, 0.0))
    return types.SimpleNamespace(id=vid, rpm=upm, body=koerper)


# ── Abstandsdämpfung ───────────────────────────────────────────────────────

def test_direkt_daneben_ist_voll_zu_hoeren():
    assert sr.daempfung(0.0) == pytest.approx(1.0)


def test_lautstaerke_faellt_mit_der_entfernung():
    werte = [sr.daempfung(d) for d in (0, 200, 500, 1000, 2000)]
    assert werte == sorted(werte, reverse=True)


def test_beim_halbwert_ist_es_halb_so_laut_in_der_leistung():
    assert sr.daempfung(sr.HALBWERT) == pytest.approx(0.5)


def test_jenseits_der_hoerweite_genau_still():
    """Genau null, nicht fast null: nur so lässt sich ein Kanal abschalten,
    statt unhörbar weiterzulaufen und einen Platz zu belegen."""
    assert sr.daempfung(sr.HOERWEITE) == 0.0
    assert sr.daempfung(sr.HOERWEITE + 5000) == 0.0


# ── Panorama ───────────────────────────────────────────────────────────────

def test_mittig_ist_mittig():
    assert sr.panorama(0.0) == pytest.approx(0.0)


def test_links_und_rechts_haben_das_richtige_vorzeichen():
    assert sr.panorama(-500.0) < 0.0
    assert sr.panorama(+500.0) > 0.0


def test_panorama_laeuft_nicht_ueber():
    assert sr.panorama(-99999.0) == pytest.approx(-1.0)
    assert sr.panorama(+99999.0) == pytest.approx(+1.0)


# ── Zwei Hörpositionen (Splitscreen) ───────────────────────────────────────

def test_ohne_hoerposition_bleibt_es_still():
    assert sr.hoerbar_bei([], (0.0, 0.0)) == (0.0, 0.0)


def test_die_naehere_hoerposition_gewinnt():
    """Die Lautstärken zu addieren würde ein Fahrzeug in der Mitte zwischen
    beiden Spielern lauter machen als eines direkt neben einem."""
    nah, fern = (0.0, 0.0), (2000.0, 0.0)
    laut_mitte, _p = sr.hoerbar_bei([nah, fern], (1000.0, 0.0))
    laut_direkt, _p2 = sr.hoerbar_bei([nah, fern], (50.0, 0.0))
    assert laut_direkt > laut_mitte


def test_panorama_kommt_von_der_naeheren_position():
    """Sonst klingt ein Fahrzeug „von überall", weil zwei Richtungen gemischt
    würden."""
    links_hoerer, rechts_hoerer = (0.0, 0.0), (4000.0, 0.0)
    # Fahrzeug knapp rechts vom linken Hoerer: muss rechts liegen.
    _l, pano = sr.hoerbar_bei([links_hoerer, rechts_hoerer], (300.0, 0.0))
    assert pano > 0.0


def test_ein_hoerer_verhaelt_sich_wie_erwartet():
    laut, pano = sr.hoerbar_bei([(0.0, 0.0)], (sr.HALBWERT, 0.0))
    assert laut == pytest.approx(0.5)
    assert pano > 0.0


# ── Reifenquietschen ───────────────────────────────────────────────────────

def test_normales_kurvenfahren_quietscht_nicht():
    """Sonst quietscht es dauernd und bedeutet nichts mehr."""
    assert sr.schlupf_lautstaerke(0.0) == 0.0
    assert sr.schlupf_lautstaerke(sr.SCHLUPF_AB) == 0.0


def test_quietschen_waechst_mit_dem_schraeglauf():
    leicht = sr.schlupf_lautstaerke(sr.SCHLUPF_AB + 2.0)
    stark = sr.schlupf_lautstaerke(sr.SCHLUPF_AB + 7.0)
    assert 0.0 < leicht < stark <= 1.0


def test_quietschen_laeuft_nicht_ueber():
    assert sr.schlupf_lautstaerke(180.0) == pytest.approx(1.0)


# ── Motorzuordnung ─────────────────────────────────────────────────────────

def test_klassen_bekommen_die_vereinbarte_zylinderzahl():
    assert sr.motor_fuer_klasse("Hatchback") == "4zyl"
    assert sr.motor_fuer_klasse("Limousine") == "6zyl"
    assert sr.motor_fuer_klasse("Drifter") == "6zyl"
    assert sr.motor_fuer_klasse("Rennfahrzeug") == "8zyl"


def test_schluessel_wird_zur_klasse():
    """race_setup.CLASSES steht in der anderen Richtung — hier umgedreht, damit
    der Klang die Klasse nicht raten muss."""
    assert sr.klasse_von_schluessel("rookie_2") == "Hatchback"
    assert sr.klasse_von_schluessel("supercar_3") == "Rennfahrzeug"
    assert sr.klasse_von_schluessel("electric") == "Elektroauto"
    assert sr.klasse_von_schluessel("gibt-es-nicht") == ""


def test_jedes_fahrzeug_im_spiel_hat_eine_klasse():
    """Sonst bekäme es stillschweigend den Standardmotor."""
    from src.core import race_setup
    for klasse, schluessel in race_setup.CLASSES.items():
        if klasse == "Alle":
            continue
        for k in schluessel:
            assert sr.klasse_von_schluessel(k) == klasse, k


def test_unbekannte_klasse_faellt_auf_sechs_zylinder():
    assert sr.motor_fuer_klasse("Gibt es nicht") == "6zyl"


def test_elektro_bekommt_keinen_verbrenner():
    """Ein Sechszylinder unter einem E-Auto wäre kein Ersatz, sondern ein
    hörbarer Fehler — Elektro hat einen eigenen Schichtensatz."""
    from src.core import sfx
    assert sr.motor_fuer_klasse("Elektroauto") == "elektro"
    s = sfx.schichten("elektro")
    if not s:
        pytest.skip("keine Elektroschichten vorhanden")
    assert s.bereich[1] >= 14000, "reicht nicht bis zur Nenndrehzahl"


# ── Klangfärbung je Fahrzeug (§C5) ─────────────────────────────────────────

def test_jedes_fahrzeug_klingt_etwas_anders():
    """Sonst sind drei Fahrzeuge einer Klasse akustisch dasselbe Auto.

    Verglichen wird **innerhalb** einer Klasse. Über Klassen hinweg dürfen sich
    die Werte wiederholen: dort liegt der Unterschied schon in der Aufnahme
    (vier, sechs, acht Zylinder). Vorher stand hier ein Vergleich über alle
    Fahrzeuge — der ging nur durch, solange jedes Fahrzeug seine eigene Tonhöhe
    hatte, und genau die ist am 02.08.2026 als Ursache der Störfrequenzen
    entfallen (siehe tests/test_motorklang_ueberlagerung.py).
    """
    from src.core import race_setup
    from src.entities.vehicle_factory import VehicleFactory
    VehicleFactory.load_all_configs("data/vehicles")
    for klasse, keys in race_setup.CLASSES.items():
        if klasse == "Alle":
            continue
        gesehen = {k: sr.klangfarbe_von_schluessel(k) for k in keys}
        assert len(set(gesehen.values())) == len(gesehen), \
            f"{klasse}: doppelte Färbung: {gesehen}"


def test_versatz_bleibt_im_rahmen():
    """Über etwa 10 % klingt es nach einer anderen Motorbauart statt nach einem
    anderen Fahrzeug derselben Klasse.

    Bei der Färbung wird die **Spanne innerhalb einer Klasse** geprüft, nicht
    der Betrag. Der Grund steht in den Elektro-Fahrzeugen: die ganze Klasse
    liegt seit dem Playtest vom 05.08.2026 gemeinsam dunkler (§C5), weil der
    Elektro sonst fiept. Ein fester Deckel auf den Betrag würde diese
    Verschiebung mit der Streuung zwischen den Fahrzeugen verwechseln.
    """
    from src.core import race_setup
    from src.entities.vehicle_factory import VehicleFactory
    VehicleFactory.load_all_configs("data/vehicles")
    for k in VehicleFactory.get_all_keys():
        ton, farb = sr.klangfarbe_von_schluessel(k)
        assert 0.9 <= ton <= 1.1, f"{k}: Tonhöhe {ton}"
        assert -1.0 <= farb <= 1.0, f"{k}: Färbung {farb} außerhalb des Filters"
    for klasse, keys in race_setup.CLASSES.items():
        if klasse == "Alle":
            continue
        werte = [sr.klangfarbe_von_schluessel(k)[1] for k in keys]
        assert max(werte) - min(werte) <= 1.0, \
            f"{klasse}: Färbung streut um {max(werte) - min(werte):.2f}"


def test_unbekanntes_fahrzeug_klingt_wie_die_aufnahme():
    """Ein geratener Versatz wäre schlimmer als keiner."""
    assert sr.klangfarbe_von_schluessel("gibt-es-nicht") == (1.0, 0.0)


# ── Nachschieben der Blöcke ────────────────────────────────────────────────

class _FalscherKanal:
    """Mixerkanal, der mitzählt statt zu klingen."""

    def __init__(self) -> None:
        self.gespielt = 0
        self.gelegt = 0
        self._queue = None
        self.gestoppt = 0
        #: Seit dem 03.08.2026 wird jenseits der Hoerweite ausgeblendet statt
        #: angehalten — ``stop()`` schneidet die Welle mitten durch.
        self.geblendet = 0

    def fadeout(self, ms):
        self.geblendet += 1
        self._queue = None

    # Der Kanal ist beschäftigt, sobald etwas läuft.
    def get_busy(self):
        return self.gespielt + self.gelegt > 0 and self.gestoppt == 0

    def get_queue(self):
        return self._queue

    def play(self, klang, loops=0):
        self.gespielt += 1
        self._queue = None

    def queue(self, klang):
        self.gelegt += 1
        self._queue = klang

    def set_volume(self, links, rechts=None):
        pass

    def stop(self):
        self.gestoppt += 1

    def blockgrenze(self):
        """Der laufende Block ist zu Ende, der wartende rückt auf."""
        self._queue = None


def _stimme_mit_kanal(monkeypatch):
    kanal = _FalscherKanal()
    stimme = sr._Stimme("6zyl", 0)
    monkeypatch.setattr(stimme, "_kanal", lambda: kanal)
    monkeypatch.setattr(stimme, "_klang", lambda upm: object())
    stimme.stimme = types.SimpleNamespace(__bool__=lambda self: True)
    return stimme, kanal


def test_hohe_bildrate_legt_nicht_mehr_bloecke_nach(monkeypatch):
    """Der eigentliche Fund hinter dem Blubbern: der Neustart über get_busy()
    sah den kurzen Moment zwischen zwei Blöcken als „steht" und schnitt den
    laufenden Block ab. Bei 300 Abfragen je Sekunde waren das 37 Fehlstarts in
    sechs Sekunden, ungebremst 141 — fast jeder zweite Block gekappt."""
    stimme, kanal = _stimme_mit_kanal(monkeypatch)
    for _ in range(200):                      # 200 Bilder, kein Blockwechsel
        stimme.aktualisieren(3000.0, 0.8, 0.8)
    assert kanal.gelegt == 1, f"{kanal.gelegt} Blöcke statt einem nachgelegt"
    assert kanal.gespielt == 0, "play() schneidet den laufenden Block ab"


def test_je_blockgrenze_genau_ein_block(monkeypatch):
    stimme, kanal = _stimme_mit_kanal(monkeypatch)
    for _ in range(5):
        for _bild in range(40):
            stimme.aktualisieren(3000.0, 0.8, 0.8)
        kanal.blockgrenze()
    assert kanal.gelegt == 5


def test_nach_der_pause_laeuft_es_wieder(monkeypatch):
    """queue() startet einen stehenden Kanal von selbst — deshalb braucht es
    play() nicht, auch nicht nach dem Pausenmenü."""
    stimme, kanal = _stimme_mit_kanal(monkeypatch)
    stimme.aktualisieren(3000.0, 0.8, 0.8)
    # Außer Hörweite: der Kanal wird ausgeblendet, nicht abgeschnitten
    # (03.08.2026 — stop() trennt die Welle mitten durch und knackt).
    stimme.aktualisieren(3000.0, 0.0, 0.0)
    assert kanal.geblendet == 1 and kanal.gestoppt == 0
    kanal.geblendet = 0
    kanal._queue = None
    stimme.aktualisieren(3000.0, 0.8, 0.8)
    assert kanal.gelegt == 2, "nach dem Anhalten kam nichts mehr"


# ── Pegelbudget ────────────────────────────────────────────────────────────

def test_wenige_fahrzeuge_werden_nicht_zurueckgenommen(klang_ohne_mixer):
    """Sonst würde ein Rennen mit zwei Autos leiser klingen als eines allein."""
    autos = [_fern(50.0 * i, slot=i + 2) for i in range(4)]
    klang_ohne_mixer.starten(autos, {})
    klang_ohne_mixer.aktualisieren(autos, [(0.0, 0.0)])
    # Drei Kanäle, also drei Stimmen: alle direkt daneben, alle voll auf.
    # Gemessen wird die lautere Seite — die leisere ist nur durch die
    # Panoramalage gedämpft, nicht durch das Budget.
    for stimme in klang_ohne_mixer._stimmen.values():
        assert max(stimme.werte[-1][1], stimme.werte[-1][2]) > 0.6


def test_dichter_pulk_wird_gemeinsam_zurueckgenommen(monkeypatch, klang_ohne_mixer):
    """Der Mixer addiert die Kanäle und schneidet ab, was über die
    Vollaussteuerung geht — das knistert. Zurückgenommen wird gemeinsam, sonst
    würde ausgerechnet das nächste Fahrzeug leiser."""
    monkeypatch.setattr(sr, "PEGELBUDGET", 1.0)
    autos = [_fern(10.0 * i, slot=i + 2) for i in range(3)]
    klang_ohne_mixer.starten(autos, {})
    klang_ohne_mixer.aktualisieren(autos, [(0.0, 0.0)])

    stimmen = list(klang_ohne_mixer._stimmen.values())
    summe = sum(max(s.werte[-1][1], s.werte[-1][2]) for s in stimmen)
    assert summe <= 1.05, f"Summe {summe:.2f} über dem Budget"
    # Gemeinsam, nicht einzeln: das Verhältnis untereinander bleibt.
    laut = [s.werte[-1][1] for s in stimmen]
    assert max(laut) - min(laut) < 0.05


# ── Startsignal ────────────────────────────────────────────────────────────

def test_startsignal_deckt_den_ganzen_countdown_ab():
    """race-start.wav ist nicht das GO, sondern der ganze Countdown: Piep bei
    0,0, 1,0 und 2,0 Sekunden, langer Ton bei 3,0. Am Ende des Countdowns
    abgespielt kam er vier Sekunden zu spät."""
    import numpy as np
    import soundfile as sf
    from src.core import sfx
    pfad = sfx._pfad("race-start.wav")
    if not os.path.isfile(pfad):
        pytest.skip("race-start.wav fehlt")
    x, rate = sf.read(pfad, always_2d=True, dtype="float32")
    x = np.abs(x.mean(axis=1))

    schwelle = x.max() * 0.1
    einsaetze, an = [], False
    for i, v in enumerate(x):
        if v > schwelle and not an:
            einsaetze.append(i / rate)
            an = True
        elif an and not np.any(x[i:i + int(rate * 0.05)] > schwelle * 0.3):
            an = False

    assert len(einsaetze) == 4, f"erwartet drei Piepser und GO, gefunden {einsaetze}"
    assert einsaetze[-1] == pytest.approx(sr.STARTSIGNAL_VORLAUF, abs=0.05), \
        "der lange Ton liegt nicht dort, wo der Vorlauf ihn erwartet"


def test_startsignal_haengt_an_der_restzeit_nicht_am_anfang():
    """Online läuft der Countdown 3,5 Sekunden, lokal 3,0. Am Anfang ausgelöst
    läge der lange Ton online eine halbe Sekunde vor GO."""
    import ast
    pfad = os.path.join(_ROOT, "src", "states", "race_state.py")
    with open(pfad, encoding="utf-8") as fh:
        quelle = fh.read()
    baum = ast.parse(quelle)
    klasse = next(k for k in baum.body
                  if isinstance(k, ast.ClassDef) and k.name == "RaceState")
    fn = next(f for f in klasse.body if isinstance(f, ast.FunctionDef)
              and f.name == "_startsignal_pruefen")
    text = ast.get_source_segment(quelle, fn)
    assert "countdown_timer" in text and "STARTSIGNAL_VORLAUF" in text


# ── Verkabelung im Rennen ──────────────────────────────────────────────────

def test_gehoert_wird_am_eigenen_fahrzeug():
    """Die Hörposition kam aus der Kamera — die rechnet in Pygame-Koordinaten
    mit gespiegelter y-Achse, die Fahrzeuge in Pymunk-Koordinaten. Die
    y-Entfernung war damit Unsinn und weit entfernte Fahrzeuge klangen nah."""
    import ast
    pfad = os.path.join(_ROOT, "src", "states", "race_state.py")
    with open(pfad, encoding="utf-8") as fh:
        quelle = fh.read()
    fn = next(f for f in ast.walk(ast.parse(quelle))
              if isinstance(f, ast.FunctionDef) and f.name == "_hoerpositionen")
    text = ast.get_source_segment(quelle, fn)
    assert "_cameras" not in text, "Hörposition hängt wieder an der Kamera"
    assert "_humans" in text


def test_hoerweite_bleibt_im_sichtbaren_bereich():
    """Bei 1920 px Bildbreite darf ein Fahrzeug nicht noch eine Bildbreite
    hinter dem Rand mitbrummen."""
    from src.core.settings import SCREEN_WIDTH
    assert sr.HOERWEITE <= SCREEN_WIDTH * 0.6
    # Fünf Fahrzeuglängen entfernt noch klar zu hören, zehn deutlich leiser.
    assert sr.daempfung(250.0) > 0.4
    assert sr.daempfung(600.0) < 0.2


# ── Verkabelung im Rennen (Reihenfolge) ────────────────────────────────────

def test_klang_wird_erst_nach_den_fahrzeugen_aufgebaut():
    """Der Aufbau stand einmal vor ``self._humans = ...`` und lief deshalb in
    jedem Rennen auf einen AttributeError — abgefangen, also stumm, und im
    Terminal nur eine Zeile. Genau das prüft dieser Test."""
    import ast
    pfad = os.path.join(_ROOT, "src", "states", "race_state.py")
    with open(pfad, encoding="utf-8") as fh:
        baum = ast.parse(fh.read())

    klasse = next(k for k in baum.body
                  if isinstance(k, ast.ClassDef) and k.name == "RaceState")
    enter = next(f for f in klasse.body
                 if isinstance(f, ast.FunctionDef) and f.name == "enter")

    zuweisung = aufruf = None
    for knoten in ast.walk(enter):
        if (isinstance(knoten, ast.Attribute) and knoten.attr == "_humans"
                and isinstance(knoten.ctx, ast.Store)):
            zuweisung = knoten.lineno
        if (isinstance(knoten, ast.Call) and isinstance(knoten.func, ast.Attribute)
                and knoten.func.attr == "_klang_aufbauen"):
            aufruf = knoten.lineno
    assert zuweisung and aufruf, "Aufbau oder _humans nicht mehr in enter()"
    assert aufruf > zuweisung, "Klang wird vor den Fahrzeugen aufgebaut"


# ── Drehzahl ferner Fahrzeuge ──────────────────────────────────────────────

def test_eigene_drehzahl_wird_genommen():
    assert sr._drehzahl(_auto(0, 0, upm=4200)) == pytest.approx(4200)


def test_fernes_fahrzeug_bekommt_eine_schaetzung():
    """Ferne Fahrzeuge im Online-Rennen sind kinematische Abbilder ohne Motor.
    Ohne Schätzung wären alle Mitspieler stumm."""
    stillstand = sr._drehzahl(_auto(0, 0, upm=0, tempo=0.0))
    schnell = sr._drehzahl(_auto(0, 0, upm=0, tempo=800.0))
    assert 0 < stillstand < schnell


def test_ohne_koerper_kein_absturz():
    leer = types.SimpleNamespace(id=1, rpm=0)
    assert sr._drehzahl(leer) == 0.0
    assert sr._position(leer) == (0.0, 0.0)


# ── Anlässe ────────────────────────────────────────────────────────────────

def test_leichte_beruehrung_bleibt_stumm(monkeypatch):
    """Sonst knackt jede Berührung, und in einem Feld von sechs Autos wird das
    zum Dauergeräusch."""
    gespielt = []
    monkeypatch.setattr("src.core.sfx.spielen",
                        lambda n, l=1.0, p=0.0: gespielt.append(n))
    klang = sr.Rennklang()
    klang.aufprall(sr.IMPULS_AB - 1)
    klang.wandtreffer(sr.IMPULS_AB - 1)
    assert gespielt == []


def test_schwerer_treffer_nimmt_den_grossen_klang(monkeypatch):
    gespielt = []
    monkeypatch.setattr("src.core.sfx.spielen",
                        lambda n, l=1.0, p=0.0: gespielt.append(n))
    klang = sr.Rennklang()
    klang.aufprall(sr.IMPULS_SCHWER + 1000)
    klang.aufprall(sr.IMPULS_AB + 100)
    assert gespielt == ["car-crash-big", "car-crash-small"]


def test_entfernter_treffer_ist_leiser(monkeypatch):
    laut = []
    monkeypatch.setattr("src.core.sfx.spielen",
                        lambda n, l=1.0, p=0.0: laut.append(l))
    klang = sr.Rennklang()
    hoerer = [(0.0, 0.0)]
    klang.aufprall(6000, _auto(0, 0), hoerer)
    klang.aufprall(6000, _auto(1500, 0), hoerer)
    assert laut[0] > laut[1]


# ── Kanalvergabe ───────────────────────────────────────────────────────────

class _FalscheStimme:
    """Stimme ohne Audiogerät — merkt sich nur, was mit ihr geschah."""

    def __init__(self, motor: str, kanal_nr: int, tonhoehe: float = 1.0,
                 faerbung: float = 0.0) -> None:
        self.stimme = True
        self.motor = motor
        self.tonhoehe = tonhoehe
        self.faerbung = faerbung
        self.kanal_nr = kanal_nr
        self.werte: list[tuple[float, float, float]] = []
        self.beendet = False
        self.gestillt = 0

    def aktualisieren(self, upm, links, rechts):
        self.werte.append((upm, links, rechts))
        if links <= 0.001 and rechts <= 0.001:
            self.stille()

    def stille(self):
        self.gestillt += 1

    def beenden(self):
        self.beendet = True


@pytest.fixture
def klang_ohne_mixer(monkeypatch):
    """Rennklang mit vorgetäuschtem Mixer und drei Motorkanälen.

    Nur die zwei Berührungspunkte zum Mixer werden ersetzt. Das ganze
    pygame-Modul auszutauschen ging schief: wird darin zum ersten Mal
    ``pygame.sndarray`` geladen, merkt es sich den falschen Mixer dauerhaft und
    spätere Tests scheitern.
    """
    from src.core import sfx
    monkeypatch.setattr(sr, "_mixer_bereit", lambda: True)
    monkeypatch.setattr(sr, "_kanalzahl", lambda: sfx.EINZEL_KANAELE + 4)
    monkeypatch.setattr(sr, "_Stimme", _FalscheStimme)
    return sr.Rennklang()


def _fern(x: float, slot: int, vid: int = 1, tempo: float = 300.0):
    auto = _auto(x, 0.0, upm=0, vid=vid, tempo=tempo)
    auto.sender_slot = slot
    return auto


def test_eigenes_und_fernes_auto_teilen_keinen_kanal(klang_ohne_mixer):
    """Beide heißen vehicle_id 1. Ohne den Absender im Schlüssel würde der
    Mitspieler den eigenen Motorkanal übernehmen — man hört fremdes Gas."""
    eigen, fremd = _auto(0, 0, upm=3000, vid=1), _fern(100.0, slot=2, vid=1)
    klang_ohne_mixer.starten([eigen], {sr.kennung(eigen): "rookie"})
    klang_ohne_mixer.aktualisieren([eigen, fremd], [(0.0, 0.0)])
    kanaele = {s.kanal_nr for s in klang_ohne_mixer._stimmen.values()}
    assert len(klang_ohne_mixer._stimmen) == 2
    assert len(kanaele) == 2


def test_spaet_erscheinendes_fahrzeug_bekommt_eine_stimme(klang_ohne_mixer):
    """Ferne Fahrzeuge entstehen erst beim ersten Paket, also nach starten()."""
    klang_ohne_mixer.starten([], {})
    assert klang_ohne_mixer._stimmen == {}
    klang_ohne_mixer.aktualisieren([_fern(50.0, slot=3)], [(0.0, 0.0)])
    assert len(klang_ohne_mixer._stimmen) == 1


def test_verschwundenes_fahrzeug_gibt_seinen_kanal_zurueck(klang_ohne_mixer):
    """Sonst hat ein Online-Rennen mit Aus- und Wiedereinstiegen irgendwann
    keinen Kanal frei und die letzten Fahrzeuge bleiben stumm."""
    klang_ohne_mixer.starten([], {})
    hoerer = [(0.0, 0.0)]
    for slot in (2, 3, 4):
        klang_ohne_mixer.aktualisieren([_fern(50.0, slot=slot)], hoerer)
        assert len(klang_ohne_mixer._stimmen) == 1, "alte Stimme nicht abgeräumt"
    assert len(klang_ohne_mixer._freie_kanaele) == 2


def test_ferne_klasse_kommt_vom_konfigurationsschluessel(klang_ohne_mixer):
    auto = _fern(50.0, slot=2)
    auto.config_key = "supercar_3"
    klang_ohne_mixer.starten([], {})
    klang_ohne_mixer.aktualisieren([auto], [(0.0, 0.0)])
    assert next(iter(klang_ohne_mixer._stimmen.values())).motor == "8zyl"


def test_ohne_freien_kanal_bleibt_es_still_statt_zu_stoeren(klang_ohne_mixer):
    autos = [_fern(50.0, slot=s) for s in range(2, 9)]
    klang_ohne_mixer.starten([], {})
    klang_ohne_mixer.aktualisieren(autos, [(0.0, 0.0)])
    # Drei Motorkanäle (vier minus einer fürs Quietschen) für sieben Fahrzeuge.
    assert len(klang_ohne_mixer._stimmen) == 3
    assert klang_ohne_mixer._reifen_kanal is not None


def test_fahrzeug_jenseits_der_hoerweite_haelt_seinen_kanal_an(klang_ohne_mixer):
    """Ein unhörbares Fahrzeug soll keine Blöcke mehr rechnen."""
    nah = _fern(0.0, slot=2)
    klang_ohne_mixer.starten([nah], {})
    klang_ohne_mixer.aktualisieren([nah], [(0.0, 0.0)])
    stimme = next(iter(klang_ohne_mixer._stimmen.values()))
    _upm, links, rechts = stimme.werte[-1]
    assert links > 0.0 and rechts > 0.0

    fern = _fern(sr.HOERWEITE + 1000.0, slot=2)
    klang_ohne_mixer.aktualisieren([fern], [(0.0, 0.0)])
    assert stimme.werte[-1][1:] == (0.0, 0.0)


def test_beenden_gibt_alles_frei(klang_ohne_mixer):
    auto = _fern(0.0, slot=2)
    klang_ohne_mixer.starten([auto], {})
    stimme = next(iter(klang_ohne_mixer._stimmen.values()))
    klang_ohne_mixer.beenden()
    assert stimme.beendet
    assert klang_ohne_mixer._stimmen == {}
    assert not klang_ohne_mixer._aktiv


def test_stimme_faengt_sich_nach_dem_leerlaufen_wieder():
    """Im Pausenmenü wird nicht nachgeschoben, der Kanal läuft leer und hält
    an. Ohne den Neustart blieb das Fahrzeug nach der Pause für immer stumm —
    gemessen mit dem Dummy-Treiber, weil genau das kein Rechenfehler ist."""
    import time
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import pygame
    from src.core import sfx
    if not sfx.mixer_starten():
        pytest.skip("kein Mixer verfügbar")
    if not sfx.schichten("6zyl"):
        pytest.skip("keine Aufnahmen vorhanden")

    stimme = sr._Stimme("6zyl", pygame.mixer.get_num_channels() - 1)
    kanal = pygame.mixer.Channel(stimme.kanal_nr)
    try:
        stimme.aktualisieren(3000.0, 1.0, 1.0)
        assert kanal.get_busy()
        time.sleep(0.5)                      # Pause: nichts nachgeschoben
        assert not kanal.get_busy(), "Kanal lief nicht leer, Test greift nicht"
        stimme.aktualisieren(3000.0, 1.0, 1.0)
        assert kanal.get_busy(), "nach der Pause stumm geblieben"
    finally:
        stimme.beenden()


def test_ohne_mixer_passiert_nichts():
    """Im Test läuft kein Audiogerät — nichts davon darf abstürzen."""
    klang = sr.Rennklang()
    klang.starten([_auto(0, 0)], {1: "rookie"})
    klang.aktualisieren([_auto(0, 0, upm=3000)], [(0.0, 0.0)])
    klang.reifen(_auto(0, 0, schlupf=30.0), [(0.0, 0.0)])
    klang.beenden()


# ---------------------------------------------------------------------------
# Kein Sprung an der Hörgrenze (Playtest 03.08.2026)
# ---------------------------------------------------------------------------
def test_die_daempfung_erreicht_null_ohne_sprung():
    """Die Kennlinie lag an der Hörweite noch bei 0,063, und dort wurde auf null
    geschaltet. Ein Fahrzeug pendelt in einem Rennen dauernd um diese Grenze;
    jedes Überschreiten war ein Sprung im Pegel — und zwar genau dann, wenn ein
    *anderes* Fahrzeug in Hörweite kommt. Das eigene Auto hat Entfernung null
    und kennt den Fall nicht."""
    schritt = 1.0
    werte = [sr.daempfung(d) for d in
             [sr.HOERWEITE - k * schritt for k in range(60, -1, -1)]]
    assert werte[-1] == 0.0
    sprung = max(abs(b - a) for a, b in zip(werte, werte[1:]))
    assert sprung < 0.002, f"Sprung {sprung:.4f} an der Hörgrenze"


def test_die_daempfung_bleibt_monoton_und_im_bereich():
    werte = [sr.daempfung(d) for d in range(0, 1200, 5)]
    assert werte[0] == pytest.approx(1.0)
    assert all(0.0 <= v <= 1.0 for v in werte)
    assert all(b <= a + 1e-9 for a, b in zip(werte, werte[1:])), "nicht monoton"


def test_nahes_bleibt_laut_trotz_ausblende():
    """Die Blende darf nur den Rand betreffen, nicht die Fahrpraxis."""
    assert sr.daempfung(0.0) == pytest.approx(1.0)
    assert sr.daempfung(sr.HALBWERT) == pytest.approx(0.5)
    assert sr.daempfung(sr.HOERWEITE - sr.AUSBLENDE) > 0.06


def test_jenseits_der_hoerweite_wird_ausgeblendet_statt_abgeschnitten(monkeypatch):
    """``stop()`` schneidet den laufenden Block mitten in der Welle ab."""
    stimme, kanal = _stimme_mit_kanal(monkeypatch)
    stimme.aktualisieren(3000.0, 0.8, 0.8)
    assert stimme._gestartet
    stimme.aktualisieren(3000.0, 0.0, 0.0)
    assert kanal.geblendet, "hart angehalten statt ausgeblendet"
    assert not kanal.gestoppt


def test_beim_rennende_wird_ausgeblendet_statt_abgeschnitten(monkeypatch):
    """Wie stille(): beenden() wird beim Verlassen des Rennens gerufen
    (RaceState.exit → Rennklang.beenden) und muss ebenfalls ausblenden.
    ``stop()`` schneidet den laufenden Block mitten in der Welle ab — das ist
    ein Knacks beim Übergang zu den Menüsounds (Playtest 05.08.2026)."""
    stimme, kanal = _stimme_mit_kanal(monkeypatch)
    stimme.aktualisieren(3000.0, 0.8, 0.8)
    assert stimme._gestartet
    stimme.beenden()
    assert kanal.geblendet, "hart angehalten statt ausgeblendet"
    assert not kanal.gestoppt, "sollte nicht hart gestoppt werden"


# ── Aufpralldämpfung (Playtest 05.08.2026) ─────────────────────────────────
# „Kollision ist etwas lauter als nötig — kann um 30% reduziert werden."

def _gespielt(monkeypatch):
    """Sammelt (Name, Lautstärke) statt zu klingen."""
    from src.core import sfx
    protokoll: list[tuple[str, float]] = []
    monkeypatch.setattr(sfx, "spielen",
                        lambda name, laut=1.0, pano=0.0: protokoll.append((name, laut)))
    return protokoll


def test_ein_fahrzeugtreffer_ist_um_dreissig_prozent_leiser(monkeypatch):
    protokoll = _gespielt(monkeypatch)
    sr.Rennklang().aufprall(sr.IMPULS_SCHWER)
    _name, laut = protokoll[-1]
    assert laut == pytest.approx(1.0 * sr.AUFPRALL_DAEMPFUNG)


def test_ein_wandtreffer_ist_um_dreissig_prozent_leiser(monkeypatch):
    protokoll = _gespielt(monkeypatch)
    sr.Rennklang().wandtreffer(8000.0)
    _name, laut = protokoll[-1]
    assert laut == pytest.approx(1.0 * sr.AUFPRALL_DAEMPFUNG)


def test_die_daempfung_dreht_die_treffer_nicht_ganz_ab(monkeypatch):
    """Leiser heißt leiser, nicht weg — und die Abstufung bleibt erhalten."""
    protokoll = _gespielt(monkeypatch)
    klang = sr.Rennklang()
    klang.aufprall(sr.IMPULS_AB + 1.0)
    klang.aufprall(sr.IMPULS_SCHWER)
    leicht, schwer = protokoll[0][1], protokoll[1][1]
    assert 0.0 < leicht < schwer <= 1.0


def test_ein_zu_leichter_treffer_bleibt_weiter_stumm(monkeypatch):
    protokoll = _gespielt(monkeypatch)
    sr.Rennklang().aufprall(sr.IMPULS_AB - 1.0)
    assert protokoll == []


# ── Zwei Reifenklänge im Wechsel (C7) ──────────────────────────────────────

def test_beide_reifenklaenge_sind_verdrahtet():
    """`tire-screeching-2` lag ungenutzt herum, obwohl C1 zwei Klänge führt."""
    assert set(sr.REIFENKLAENGE) == {"tire-screeching-1.wav", "tire-screeching-2.wav"}


def test_die_dateien_gibt_es_auch_wirklich():
    from src.core import sfx
    for name in sr.REIFENKLAENGE:
        assert os.path.exists(sfx._pfad(name)), name


def test_jede_neue_drift_nimmt_den_anderen_klang(monkeypatch, klang_ohne_mixer):
    """Innerhalb einer Drift läuft die Schleife weiter, erst die nächste wechselt."""
    import pygame
    from src.core import resource_manager

    gespielt: list[str] = []

    class _Kanal:
        def __init__(self, _nr): self.laeuft = False
        def get_busy(self): return self.laeuft
        def set_volume(self, *a): pass
        def fadeout(self, _ms): self.laeuft = False
        def play(self, klang, loops=0):
            self.laeuft = True
            gespielt.append(klang)

    kanaele: dict[int, _Kanal] = {}
    monkeypatch.setattr(pygame.mixer, "Channel",
                        lambda nr: kanaele.setdefault(nr, _Kanal(nr)))
    monkeypatch.setattr(resource_manager.ResourceManager, "load_sound",
                        lambda self, pfad: os.path.basename(pfad))

    klang = klang_ohne_mixer
    klang.starten([_auto(0, 0)], {sr.kennung(_auto(0, 0)): "rookie"})
    driftend, ruhig = _auto(0, 0, schlupf=30.0), _auto(0, 0, schlupf=0.0)

    for _ in range(3):
        klang.reifen(driftend, [(0.0, 0.0)])   # Drift beginnt
        klang.reifen(driftend, [(0.0, 0.0)])   # läuft weiter
        klang.reifen(ruhig, [(0.0, 0.0)])      # Drift endet

    assert gespielt == ["tire-screeching-1.wav", "tire-screeching-2.wav",
                        "tire-screeching-1.wav"]
