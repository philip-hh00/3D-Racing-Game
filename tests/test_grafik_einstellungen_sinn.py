"""Grafikeinstellungen ergeben Sinn (Produktinhaber, 1.1.0).

* Die Auflösungsliste bietet nur Fenster an, die auf den Bildschirm passen —
  keine doppelten, keine größeren als der Schirm — und das Fenster bekommt
  genau eine dieser Größen (nicht eine stufenlos verkleinerte, die nirgends
  steht).
* Im Vollbild gilt die Bildschirmgröße; der Regler zeigt sie (Nativ) und ist
  gesperrt, statt etwas zu verstellen, das nichts tut.
* Jedes Feld der Grafik hat einen Regler, jeder Regler ein Feld, und jede Stufe
  (Niedrig … Ultra) ist mit ihren Werten im Regler wählbar. Ein verstellter
  Einzelwert heißt danach „Eigen".
* „Texturqualität" wirkt auf die 3D-Texturen.
"""
from __future__ import annotations

import os
import sys
from dataclasses import fields

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.core import display, i18n, profile, sfx  # noqa: E402
from src.render3d import grafik, mesh  # noqa: E402
from src.states.menu import settings_page  # noqa: E402
from src.states.menu.settings_page import SettingsPage, _grafik_regler  # noqa: E402

SCHIRME = [(1366, 768), (1440, 900), (1920, 1080), (1920, 1200), (2560, 1440),
           (2560, 1600), (3440, 1440), (3840, 2160), (5120, 2880)]


def _groesse(label: str) -> tuple[int, int]:
    return display._aufloesung_lesen(label)


@pytest.fixture
def seite(monkeypatch):
    p = profile.Profile(username="Testfahrer")
    p.save = lambda: None
    monkeypatch.setattr(profile, "_current", p, raising=False)
    monkeypatch.setattr(profile, "current", lambda: p)
    monkeypatch.setattr(sfx, "spielen", lambda *a, **k: None)
    s = SettingsPage()
    s.enter(type("Schale", (), {"state_machine": None})())
    return s


# ---------------------------------------------------------------------------
# Auflösung
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("schirm", SCHIRME)
def test_die_auswahl_ist_sauber_und_passt_auf_den_schirm(schirm):
    liste = display.verfuegbare_aufloesungen(schirm)
    assert liste, schirm
    assert len(liste) == len(set(liste)), "doppelte Einträge"
    groessen = [_groesse(label) for label in liste]
    assert groessen == sorted(groessen, key=lambda g: g[0] * g[1]), "nicht aufsteigend"
    assert all(g[0] >= 1280 and g[1] >= 720 for g in groessen), "winzige Modi"
    if schirm[0] >= 1920:
        assert all(g[0] <= schirm[0] and g[1] <= schirm[1] for g in groessen)
    for g in groessen:
        # jede angebotene Größe wird auch genau so angelegt
        assert display.fenstergroesse_fuer(*g, schirm) == g, (schirm, g)


def test_ein_fenster_in_voller_hd_gibt_es_auf_einem_hd_schirm_nicht():
    assert display.verfuegbare_aufloesungen((1920, 1080)) == ["1280×720", "1600×900"]
    # gespeichert war 1920x1080: das Fenster wird die größte angebotene Größe
    assert display.fenstergroesse_fuer(1920, 1080, (1920, 1080)) == (1600, 900)


def test_das_fenster_wird_in_der_liste_gewaehlt_nicht_stufenlos():
    assert display.fenstergroesse_fuer(1920, 1080, (1440, 900)) == (1280, 720)
    assert display.fenstergroesse_fuer(1920, 1080, (3840, 2160)) == (1920, 1080)
    assert display.fenstergroesse_fuer(3840, 2160, (2560, 1440)) == (1920, 1080)


def test_der_gespeicherte_wert_zeigt_die_tatsaechliche_fenstergroesse():
    liste = ["1280×720", "1600×900"]
    assert display.aufloesung_waehlen("1920x1080", liste) == 1
    assert display.aufloesung_waehlen("1600x900", liste) == 1
    assert display.aufloesung_waehlen("1280x720", liste) == 0
    assert display.aufloesung_waehlen("800x600", liste) == 0


def test_native_aufloesung(monkeypatch):
    monkeypatch.setattr(display, "_desktop_groesse", lambda: (2560, 1440))
    assert display.native_aufloesung() == "2560×1440"
    monkeypatch.setattr(display, "_desktop_groesse", lambda: None)
    assert display.native_aufloesung() is None


def test_vsync_ohne_opengl_fenster_meldet_misserfolg(monkeypatch):
    monkeypatch.setattr(display, "_opengl_fenster", False)
    assert display.vsync_setzen(True) is False


def _video(seite, vollbild: bool):
    seite._pending = {"fullscreen": vollbild}
    seite.cat = seite.categories.index("Video")
    seite._build_content()
    return seite._stepper("change_resolution"), seite._stepper("toggle_fullscreen")


def test_im_vollbild_zeigt_der_regler_die_bildschirmgroesse_und_ist_gesperrt(
        seite, monkeypatch):
    monkeypatch.setattr(display, "_desktop_groesse", lambda: (2560, 1440))
    res, fs = _video(seite, True)
    assert not res.enabled and not res.focusable
    assert res.options == ["2560×1440 (Nativ)"]
    assert seite._content_group.focused is not res

    # zurück ins Fenster: wieder die Liste, an der alten Stelle
    fs.index = 0
    seite._dispatch("toggle_fullscreen")
    assert res.enabled and res.focusable
    assert res.options == display.verfuegbare_aufloesungen()
    assert seite._pending["fullscreen"] is False

    fs.index = 1
    seite._dispatch("toggle_fullscreen")
    assert not res.enabled and res.options == ["2560×1440 (Nativ)"]


def test_im_fenster_ist_der_regler_frei(seite, monkeypatch):
    monkeypatch.setattr(display, "_desktop_groesse", lambda: (2560, 1440))
    res, _fs = _video(seite, False)
    assert res.enabled and res.focusable
    assert len(res.options) >= 2


def test_nativ_ist_uebersetzt():
    i18n.set_language("en")
    try:
        assert i18n.tr("Nativ") != "Nativ"
    finally:
        i18n.set_language("de")


# ---------------------------------------------------------------------------
# Grafikregler und Stufen
# ---------------------------------------------------------------------------
def test_jedes_grafikfeld_hat_einen_regler_und_umgekehrt():
    regler = {feld for feld, _b, _o in _grafik_regler()}
    felder = {f.name for f in fields(grafik.Grafik)} - {"stufe"}
    assert regler == felder, (regler ^ felder)


def test_die_reglerwerte_sind_geordnet_und_eindeutig_beschriftet():
    for feld, beschriftung, optionen in _grafik_regler():
        werte = [w for w, _a in optionen]
        anzeigen = [a for _w, a in optionen]
        assert len(set(anzeigen)) == len(anzeigen), (feld, "gleiche Anzeige")
        assert len(set(werte)) == len(werte), (feld, "gleicher Wert")
        zahlen = [w for w in werte if isinstance(w, (int, float)) and not isinstance(w, bool)]
        if len(zahlen) == len(werte):
            assert zahlen == sorted(zahlen), (feld, "nicht aufsteigend")
        assert beschriftung


@pytest.mark.parametrize("name", grafik.STUFEN_NAMEN)
def test_jede_stufe_ist_mit_ihren_werten_im_regler_waehlbar(name):
    optionen = {feld: [w for w, _a in o] for feld, _b, o in _grafik_regler()}
    for feld, wert in grafik.als_dict(grafik.STUFEN[name]).items():
        if feld == "stufe":
            continue
        assert wert in optionen[feld], (name, feld, wert)
    assert settings_page._grafik_stufe_erkennen(grafik.als_dict(grafik.STUFEN[name])) == name


def test_die_stufen_steigen_in_den_kosten():
    """Niedrig <= Mittel <= Hoch <= Ultra in jedem Feld, in dem mehr mehr kostet."""
    felder = ("aufloesung_skala", "schatten_px", "ssao", "deko_dichte", "sichtweite_m",
              "gras", "gelaende_detail", "strecken_details", "fahrzeug_lod_m",
              "gelaende_schatten", "lichter_max", "spiegel", "regen_tropfen",
              "gischt_teilchen")
    folge = [grafik.STUFEN[n] for n in grafik.STUFEN_NAMEN]
    for feld in felder:
        werte = [getattr(g, feld) for g in folge]
        assert werte == sorted(werte), (feld, werte)


def test_ein_verstellter_einzelwert_heisst_eigen(seite, monkeypatch):
    seite.cat = seite.categories.index("Video")
    seite._build_content()
    seite._dispatch("grafik_advanced")
    stufe = seite._stepper("grafik_stufe")
    assert stufe.value == "Hoch"
    schatten = seite._stepper("grafik_schatten_px")
    schatten.index = (schatten.index + 1) % len(schatten.options)
    seite._dispatch("grafik_schatten_px")
    assert stufe.value == "Eigen"
    # zurück auf den Wert der Stufe: wieder „Hoch"
    schatten.index = (schatten.index - 1) % len(schatten.options)
    seite._dispatch("grafik_schatten_px")
    assert stufe.value == "Hoch"


def test_eine_stufe_stellt_alle_regler_im_overlay(seite):
    seite.cat = seite.categories.index("Video")
    seite._build_content()
    seite._dispatch("grafik_advanced")
    stufe = seite._stepper("grafik_stufe")
    stufe.index = 0                                      # Niedrig
    seite._dispatch("grafik_stufe")
    for feld, wert in grafik.als_dict(grafik.STUFEN["niedrig"]).items():
        if feld == "stufe":
            continue
        w = seite._stepper("grafik_" + feld)
        assert seite._werte["grafik_" + feld][w.index] == wert, feld


# ---------------------------------------------------------------------------
# Texturqualität wirkt auf die 3D-Texturen
# ---------------------------------------------------------------------------
def test_die_texturqualitaet_stellt_die_anisotrope_filterung(monkeypatch):
    p = profile.Profile(username="T")
    monkeypatch.setattr(profile, "current", lambda: p)
    p.texture_quality = "Hoch"
    assert mesh.textur_anisotropie() == 8.0
    p.texture_quality = "Niedrig"
    assert mesh.textur_anisotropie() == 1.0
