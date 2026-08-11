"""Statistik und Erfolge (Releaseplan E1 / E1a).

Der Nachweis, den E5 verlangt: **jede Zählregel einzeln.** Die Regeln sind der
eigentliche Inhalt von E1 — steht eine davon falsch, bekommt jemand eine
Freischaltung geschenkt oder eine verdiente nicht, und beides merkt man erst
spät.

Getestet wird gegen ein Wegwerfprofil. Das echte ``data/settings/profile.json``
wird hier **nie** angefasst: ein Test, der die eigene Statistik hochzählt, wäre
selbst der Fehler, den er sucht.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.core import profile, statistik  # noqa: E402


@pytest.fixture(autouse=True)
def wegwerfprofil(monkeypatch):
    """Ein frisches Profil je Test, das nichts auf die Platte schreibt."""
    p = profile.Profile(username="Testfahrer")
    p.save = lambda: None
    monkeypatch.setattr(profile, "_current", p, raising=False)
    monkeypatch.setattr(profile, "current", lambda: p)
    return p


def _zeile(position=1, dnf=False, vehicle="rookie", best_lap=60.0):
    return {"position": position, "dnf": dnf, "vehicle": vehicle,
            "best_lap": best_lap, "is_player": True, "name": "Testfahrer"}


# ---------------------------------------------------------------------------
# Die Zählregeln aus E1 — einzeln
# ---------------------------------------------------------------------------
def test_ein_zielankunft_zaehlt():
    assert statistik.rennen_gewertet(_zeile(position=4), modus="Rennen") is True
    assert statistik.werte()["rennen"] == 1


def test_abgebrochenes_rennen_zaehlt_nicht():
    """Sonst treibt Starten-und-Abbrechen jeden Zähler hoch, und die
    Freischaltung ist keine Leistung mehr."""
    assert statistik.rennen_gewertet(_zeile(), modus="Rennen", beendet=False) is False
    assert statistik.werte()["rennen"] == 0
    assert statistik.werte()["siege"] == 0


def test_dnf_zaehlt_nicht():
    """Wer ausrollt, war da, aber nicht im Ziel — weder als Rennen noch als
    Niederlage."""
    assert statistik.rennen_gewertet(_zeile(position=5, dnf=True), modus="Rennen") is False
    assert statistik.werte()["rennen"] == 0


@pytest.mark.parametrize("modus", ["Zeitfahren", "zeitfahren", "time_trial"])
def test_zeitfahren_ist_kein_rennen(modus):
    """Runden drehen ist etwas anderes als fahren. Bestzeiten und geschlagene
    Ghosts werden trotzdem getrennt geführt."""
    assert statistik.rennen_gewertet(_zeile(), modus=modus) is False
    assert statistik.werte()["rennen"] == 0
    statistik.ghost_geschlagen("oval.json")
    assert statistik.werte()["ghosts_geschlagen"] == ["oval.json"]


def test_online_zaehlt_mit():
    """Ein Rennen gegen echte Leute ist mehr Rennen, nicht weniger."""
    statistik.rennen_gewertet(_zeile(position=1), modus="Rennen", online=True)
    w = statistik.werte()
    assert (w["rennen"], w["siege"], w["online_rennen"], w["online_siege"]) == (1, 1, 1, 1)


def test_offline_erhoeht_keinen_onlinezaehler():
    statistik.rennen_gewertet(_zeile(position=1), modus="Rennen", online=False)
    w = statistik.werte()
    assert (w["online_rennen"], w["online_siege"]) == (0, 0)


def test_jeder_gp_lauf_ist_ein_rennen_die_serie_zaehlt_getrennt():
    for _ in range(3):
        statistik.rennen_gewertet(_zeile(position=2), modus="Grand Prix")
    statistik.gp_gewonnen()
    w = statistik.werte()
    assert w["rennen"] == 3
    assert w["podeste"] == 3
    assert w["gp_siege"] == 1


# ---------------------------------------------------------------------------
# Was ein Ergebnis auslöst
# ---------------------------------------------------------------------------
def test_sieg_podest_und_klasse():
    statistik.rennen_gewertet(_zeile(position=1, vehicle="supercar"), modus="Rennen")
    w = statistik.werte()
    assert w["siege"] == 1 and w["podeste"] == 1
    assert "Rennfahrzeug" in w["klassen_gewonnen"]


def test_vierter_platz_ist_kein_podest():
    statistik.rennen_gewertet(_zeile(position=4), modus="Rennen")
    w = statistik.werte()
    assert w["podeste"] == 0 and w["siege"] == 0


def test_start_ziel_sieg_nur_von_ganz_vorn():
    statistik.rennen_gewertet(_zeile(position=1), modus="Rennen", startplatz=0)
    assert statistik.werte()["start_ziel_siege"] == 1
    statistik.rennen_gewertet(_zeile(position=1), modus="Rennen", startplatz=3)
    assert statistik.werte()["start_ziel_siege"] == 1, "von Platz 4 ist kein Start-Ziel-Sieg"


def test_aufholjagd_braucht_ein_feld():
    """Vom letzten Platz eines Zweierfeldes aufs Podest ist keine Leistung —
    da ist jeder auf dem Podest."""
    statistik.rennen_gewertet(_zeile(position=2), modus="Rennen",
                              startplatz=1, teilnehmer=2)
    assert statistik.werte()["aufholjagden"] == 0
    statistik.rennen_gewertet(_zeile(position=3), modus="Rennen",
                              startplatz=5, teilnehmer=6)
    assert statistik.werte()["aufholjagden"] == 1


def test_listen_zaehlen_vielfalt_nicht_wiederholung():
    """Dreimal dieselbe Strecke ist nicht dasselbe wie drei Strecken."""
    for _ in range(3):
        statistik.rennen_gewertet(_zeile(), modus="Rennen", strecke="oval.json")
    assert statistik.werte()["strecken_gefahren"] == ["oval.json"]
    statistik.rennen_gewertet(_zeile(), modus="Rennen", strecke="acht.json")
    assert len(statistik.werte()["strecken_gefahren"]) == 2


def test_eigene_strecke_wird_getrennt_gefuehrt():
    statistik.rennen_gewertet(_zeile(position=1), modus="Rennen", eigene_strecke=True)
    w = statistik.werte()
    assert w["eigene_strecke_gefahren"] == 1
    assert w["eigene_strecke_gewonnen"] == 1


def test_meter_und_zeit_laufen_auch_im_zeitfahren_mit():
    """Gefahren ist gefahren — nur als *Rennen* zählt es dort nicht."""
    statistik.fahrt_gezaehlt(1500.0, 92.0)
    w = statistik.werte()
    assert w["meter"] == pytest.approx(1500.0)
    assert w["spielzeit_s"] == pytest.approx(92.0)


# ---------------------------------------------------------------------------
# Erfolge sind eine Funktion der Statistik
# ---------------------------------------------------------------------------
def test_frisches_profil_hat_keinen_erfolg():
    assert statistik.erreicht() == set()


def test_jeder_erfolg_hat_einen_eindeutigen_schluessel_und_text():
    schluessel = [e[0] for e in statistik.ERFOLGE]
    assert len(set(schluessel)) == len(schluessel)
    for key, gruppe, name, text, _q, _z in statistik.ERFOLGE:
        assert key and gruppe and name and text, key


def test_erfolge_gehen_an_ihrer_grenze_auf():
    w = statistik.werte()
    w["rennen"] = 4
    assert "rennen_5" not in statistik.erreicht()
    w["rennen"] = 5
    assert "rennen_5" in statistik.erreicht()
    assert "rennen_20" not in statistik.erreicht()


def test_stand_liefert_die_zahl_fuer_die_anzeige():
    """„7 / 20" statt nur „offen" — ohne Zahl weiß niemand, ob er kurz davor
    ist oder weit weg."""
    statistik.werte()["rennen"] = 7
    assert statistik.stand("rennen_20") == (7, 20)


def test_vollstaendigkeit_zaehlt_gegen_den_bestand():
    """Kommt eine Strecke dazu, wandert das Ziel mit — niemand muss daran
    denken."""
    _wert, ziel = statistik.stand("alle_strecken")
    assert ziel >= 1
    statistik.werte()["strecken_gefahren"] = ["x.json"] * (ziel + 3)
    assert "alle_strecken" in statistik.erreicht()


def test_erfolge_sind_eine_reine_funktion():
    """Nichts wird gespeichert — dieselbe Statistik ergibt immer dieselben
    Erfolge, und ein Erfolg kann nicht gesetzt sein, ohne dass der Zähler ihn
    hergibt."""
    block = dict(statistik.VORGABE)
    block["siege"] = 5
    einmal = statistik.erreicht(block)
    assert statistik.erreicht(block) == einmal
    assert "sieg_5" in einmal and "sieg_20" not in einmal


def test_online_und_editor_erfolge_schalten_nichts_frei():
    """Der Grund, warum es sie überhaupt geben darf: als Bedingung vor einem
    Lack wären sie unfair — Online braucht Mitspieler, der Editor ist optional.
    Die Lacke hängen allein an Rennen, Siegen und Ghosts (E2)."""
    from src.core import lack
    block = dict(statistik.VORGABE)
    block.update(online_rennen=99, online_siege=99, lobbys_gehostet=9,
                 strecken_veroeffentlicht=9, strecken_geteilt=9)
    offen = statistik.erreicht(block)
    assert {"online_1", "gastgeber", "veroeffentlicht"} <= offen
    # Die Lackfreischaltung kennt diese Zähler gar nicht.
    for finish in ("metallic", "neon", "zweifarbig"):
        assert lack.finish(finish) is not None


def test_dev_modus_haengt_am_paket():
    """Aus dem Quelltext gestartet ist alles frei; im ausgelieferten Bündel nie."""
    import src.core.version as version
    assert statistik.alles_frei() is not version.IS_RELEASE


# ---------------------------------------------------------------------------
# Robustheit
# ---------------------------------------------------------------------------
def test_fehlende_felder_sind_nullen(wegwerfprofil):
    """Ein Profil von vor E1 hat den Block gar nicht — das ist kein Fehler."""
    wegwerfprofil.statistik = {"rennen": 3}
    w = statistik.werte()
    assert w["rennen"] == 3
    assert w["siege"] == 0
    assert w["ghosts_geschlagen"] == []


def test_kaputter_block_wird_ersetzt(wegwerfprofil):
    wegwerfprofil.statistik = "kein dict"
    assert statistik.werte()["rennen"] == 0


def test_statistik_wird_mitgespeichert(tmp_path, monkeypatch):
    import json
    pfad = tmp_path / "profile.json"
    monkeypatch.setattr(profile, "_profile_path", lambda: str(pfad))
    p = profile.Profile(username="Testfahrer")
    p.statistik = {"rennen": 12, "siege": 3}
    p.save()
    # Seit E4 liegt das Profil verschlüsselt — geprüft wird hier trotzdem die
    # abgelegte Datei und nicht nur der Speicher, sonst hinge der Nachweis an
    # demselben Objekt, das gerade geschrieben hat.
    from src.core import tresor
    gelesen = json.loads(tresor.lesen(str(pfad)))
    assert gelesen["statistik"]["rennen"] == 12
    wieder = profile.Profile.load()
    assert wieder.statistik["siege"] == 3
