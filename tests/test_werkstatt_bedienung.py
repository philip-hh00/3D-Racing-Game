"""Werkstatt: Speichern, Neon-Sperre, Meldung, Ansicht, Scrollen (Playtest 04.08.2026).

Fünf Meldungen aus einem Playtest, alle über dieselbe Seite. Sie sehen wie fünf
Kleinigkeiten aus, aber zwei davon sind Datenverlust:

* **Speichern fehlte.** Jede Änderung ging sofort ins Profil — ein Blick auf
  eine Lackierung hieß, sie zu tragen. Umgekehrt gab es kein Zurück: wer
  ausprobierte, hatte schon geändert. Jetzt schreibt nur ``_speichern``, und
  wer mit Ungespeichertem geht, wird gefragt (Verwerfen · Speichern · Abbrechen).
* **Der Fahrzeugwechsel** wirft die Anprobe genauso weg wie das Verlassen, also
  fragt er auch.
* **Neon auf Anthrazit oder Perlweiß** ergibt nichts: Neon zieht die Sättigung
  ans Maximum, und an einer unbunten Farbe hat das nichts zu greifen. Die Felder
  verschwinden (so entschieden: „Feld ganz ausblenden").
* **Die Meldung „noch gesperrt"** lag quer über dem Auto und war halb verdeckt.
* **„Ansicht zurück"** war immer anklickbar, auch am Standardwinkel.
* **Der Streifen sprang** seitenweise und hart.

Geprüft wird an der Seite selbst, nicht an einer Attrappe: die Meldungen kamen
alle aus dem Spiel und nicht aus einem Modell davon.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.core import lack, profile, statistik, version  # noqa: E402
from src.core.settings import SCREEN_WIDTH  # noqa: E402
from src.states.menu import werkstatt_page as wp  # noqa: E402
from src.states.menu.werkstatt_page import KACHELN, WerkstattPage  # noqa: E402


@pytest.fixture
def spielstand(monkeypatch):
    p = profile.Profile(username="Testfahrer")
    p.geschrieben = 0

    def speichern() -> None:
        p.geschrieben += 1

    p.save = speichern
    p.statistik = {}
    monkeypatch.setattr(profile, "_current", p, raising=False)
    monkeypatch.setattr(profile, "current", lambda: p)
    return p


class _Schale:
    """Die Menüschale, soweit die Seite sie anfasst."""

    def __init__(self) -> None:
        self.abgeraeumt = 0

    def pop_page(self) -> None:
        self.abgeraeumt += 1


@pytest.fixture
def seite(spielstand):
    s = WerkstattPage()
    s.enter(_Schale())
    return s


def _zeichnen(s: WerkstattPage) -> pygame.Surface:
    schirm = pygame.Surface((SCREEN_WIDTH, 1080))
    s.draw(schirm, pygame.Rect(0, 108, SCREEN_WIDTH, 1080 - 108))
    return schirm


def _finish(s: WerkstattPage, key: str) -> None:
    """Über den Stepper, wie im Spiel — nicht am Feld vorbei."""
    s._finish_stepper.index = [f["key"] for f in lack.finishes()].index(key) + 1
    s.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F15))
    s.finish_index = s._finish_stepper.index
    s._farb_index_richten()
    s._uebernehmen()


def _farbe(s: WerkstattPage, key: str) -> None:
    s.farb_index = [f["key"] for f in lack.farben()].index(key)
    s._uebernehmen()


def _klick(s: WerkstattPage, pos) -> bool:
    return s.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                             pos=pos))


def _antworten(s: WerkstattPage, aktion: str) -> None:
    """Im Dialog auf den Knopf mit dieser Aktion klicken."""
    schirm = pygame.Surface((SCREEN_WIDTH, 1080))
    s._dialog.draw(schirm)
    rect = next(r for r, a in s._dialog._rects if a == aktion)
    _klick(s, rect.center)


# ---------------------------------------------------------------------------
# Speichern: vorher ist nichts übernommen
# ---------------------------------------------------------------------------
def test_eine_anprobe_landet_noch_nicht_im_profil(seite, spielstand):
    """Der Kern des Fundes: „vor dem Speichern sollen die Änderungen auch nicht
    übernommen werden."""
    _finish(seite, "metallic")
    _farbe(seite, "rubinrot")
    assert profile.current().paint(seite._key()) == lack.WERK
    assert spielstand.geschrieben == 0, "gar nicht geschrieben, nicht nur nichts geändert"


def test_erst_der_knopf_uebernimmt(seite):
    _finish(seite, "metallic")
    _farbe(seite, "rubinrot")
    _zeichnen(seite)
    _klick(seite, seite._knopf_speichern.rect.center)
    assert profile.current().paint(seite._key()) == "metallic:rubinrot"


def test_der_speichernknopf_ist_ohne_aenderung_gesperrt(seite):
    _zeichnen(seite)
    assert seite._knopf_speichern.enabled is False
    _finish(seite, "metallic")
    assert seite._knopf_speichern.enabled is True
    seite._speichern()
    assert seite._knopf_speichern.enabled is False, \
        "nach dem Speichern gibt es wieder nichts zu speichern"


def test_die_kachel_zeigt_den_bestand_und_nicht_die_anprobe(seite):
    """Der Unterschied zwischen Bühne und Streifen ist die ungespeicherte
    Änderung — zeigte die Kachel sie mit, wäre er unsichtbar."""
    _finish(seite, "metallic")
    _farbe(seite, "rubinrot")
    quelle = open(os.path.join(_ROOT, "src", "states", "menu",
                               "werkstatt_page.py"), encoding="utf-8").read()
    kachel = quelle.split("def _kachel_zeichnen")[1].split("\n    def ")[0]
    assert "self._kennung()" not in kachel


# ---------------------------------------------------------------------------
# Rückfrage vor dem Verwerfen
# ---------------------------------------------------------------------------
def test_ohne_aenderung_wird_nicht_gefragt(seite):
    seite._verlassen()
    assert seite._dialog is None
    assert seite.shell.abgeraeumt == 1


def test_mit_aenderung_wird_gefragt_und_nicht_gegangen(seite):
    _finish(seite, "metallic")
    seite._verlassen()
    assert seite._dialog is not None
    assert seite.shell.abgeraeumt == 0, "die Seite darf noch nicht weg sein"


def test_speichern_aus_der_rueckfrage_geht_dann_weiter(seite):
    _finish(seite, "metallic")
    _farbe(seite, "rubinrot")
    seite._verlassen()
    _antworten(seite, "speichern")
    assert profile.current().paint(seite._key()) == "metallic:rubinrot"
    assert seite.shell.abgeraeumt == 1


def test_verwerfen_stellt_den_gespeicherten_stand_wieder_her(seite):
    profile.current().set_paint(seite._key(), "metallic:rubinrot")
    seite._aus_profil_lesen()
    _finish(seite, "zweifarbig")
    _farbe(seite, "kobaltblau")
    seite._verlassen()
    _antworten(seite, "verwerfen")
    assert profile.current().paint(seite._key()) == "metallic:rubinrot"
    assert seite._kennung() == "metallic:rubinrot", \
        "verworfen heißt auch: die Seite zeigt wieder den Bestand"
    assert seite.shell.abgeraeumt == 1


def test_abbrechen_bleibt_und_behaelt_die_anprobe(seite):
    _finish(seite, "metallic")
    _farbe(seite, "rubinrot")
    seite._verlassen()
    _antworten(seite, "abbrechen")
    assert seite.shell.abgeraeumt == 0
    assert seite._kennung() == "metallic:rubinrot"
    assert seite._dialog is None


def test_esc_im_dialog_bricht_ab(seite):
    """B am Controller nimmt denselben Weg — und der darf nichts wegwerfen."""
    _finish(seite, "metallic")
    seite._verlassen()
    seite.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    assert seite.shell.abgeraeumt == 0
    assert seite._geaendert() is True


def test_hinter_der_rueckfrage_wird_nicht_weiterlackiert(seite):
    """Sonst fragt sie am Ende nach einem Stand, den es nicht mehr gibt."""
    _finish(seite, "metallic")
    _farbe(seite, "rubinrot")
    _zeichnen(seite)
    seite._verlassen()
    vorher = seite._kennung()
    for _i, kasten in seite._farb_rects:
        _klick(seite, kasten.center)
    assert seite._kennung() == vorher


def test_die_schale_darf_vor_dem_tabwechsel_fragen(seite):
    """Ein Klick auf einen Tab räumt die Seite ab — die Shell fragt dafür
    ``verlassen_erlaubt``, und ohne Antwort wäre die Anprobe still weg."""
    assert seite.verlassen_erlaubt(lambda: None) is True
    _finish(seite, "metallic")
    gegangen = []
    assert seite.verlassen_erlaubt(lambda: gegangen.append(1)) is False
    assert gegangen == []
    _antworten(seite, "verwerfen")
    assert gegangen == [1]


def test_ein_fahrzeugwechsel_fragt_genauso(seite):
    """Er wirft dieselbe Anprobe weg wie das Verlassen."""
    _finish(seite, "metallic")
    _zeichnen(seite)
    ziel = next(i for i, _r in seite._kachel_rects if i != seite.index)
    _klick(seite, dict(seite._kachel_rects)[ziel].center)
    assert seite._dialog is not None
    assert seite.index != ziel, "noch nicht gewechselt"
    _antworten(seite, "verwerfen")
    assert seite.index == ziel


def test_dasselbe_fahrzeug_nochmal_anklicken_fragt_nicht(seite):
    _finish(seite, "metallic")
    _zeichnen(seite)
    _klick(seite, dict(seite._kachel_rects)[seite.index].center)
    assert seite._dialog is None


def test_eine_gesperrte_lackierung_laesst_sich_nicht_wegspeichern(seite,
                                                                 spielstand,
                                                                 monkeypatch):
    """„Speichern" auf etwas Gesperrtes darf nicht heimlich weitergehen."""
    monkeypatch.setattr(version, "IS_RELEASE", True)
    assert not statistik.alles_frei()
    _finish(seite, "metallic")
    _farbe(seite, "tuerkis")
    seite._verlassen()
    _antworten(seite, "speichern")
    assert seite.shell.abgeraeumt == 0, "der Weg bleibt zu"
    assert profile.current().paint(seite._key()) == lack.WERK
    assert seite._grund, "und die Seite sagt, warum"


# ---------------------------------------------------------------------------
# Neon: unbunte Felder verschwinden
# ---------------------------------------------------------------------------
def test_neon_zeigt_anthrazit_und_perlweiss_nicht_mehr(seite):
    _finish(seite, "neon")
    _zeichnen(seite)
    keys = [f["key"] for f in lack.farben()]
    gezeigt = {keys[i] for i, _r in seite._farb_rects}
    assert "anthrazit" not in gezeigt
    assert "perlweiss" not in gezeigt
    assert "rubinrot" in gezeigt and "eisblau" in gezeigt


@pytest.mark.parametrize("finish_key", ["standard", "metallic", "zweifarbig"])
def test_die_anderen_finishes_zeigen_alle_zwoelf(seite, finish_key):
    """Anthrazit und Perlweiß sind vollwertige Lackfarben — nur Neon kann mit
    ihnen nichts anfangen."""
    _finish(seite, finish_key)
    _zeichnen(seite)
    assert len(seite._farb_rects) == len(lack.farben())


def test_bei_werkslack_bleibt_die_ganze_palette_stehen(seite):
    seite.finish_index = 0
    _zeichnen(seite)
    assert len(seite._farb_rects) == len(lack.farben())


def test_wer_auf_neon_wechselt_landet_auf_einer_bunten_farbe(seite):
    _finish(seite, "metallic")
    _farbe(seite, "anthrazit")
    _finish(seite, "neon")
    fin, far = lack.zerlege(seite._kennung())
    assert fin == "neon"
    assert lack.buntheit(lack.farbe(far)["rgb"]) >= lack.BUNT_AB


def test_der_ersatz_liegt_in_der_naehe(seite):
    """Vom anderen Ende der Palette zurückzukommen wäre ein Verlust an
    Orientierung — die Nachbarfarbe ist die kleinste Überraschung."""
    keys = [f["key"] for f in lack.farben()]
    _finish(seite, "metallic")
    _farbe(seite, "perlweiss")           # letztes Feld
    _finish(seite, "neon")
    assert keys[seite.farb_index] == "magenta"   # das letzte bunte davor


def test_ein_gespeichertes_neon_grau_geht_nicht_verloren(seite):
    """Ein Profil aus der Zeit davor (oder von Hand geschrieben) darf beim
    Öffnen der Werkstatt nicht stillschweigend umgefärbt werden — gezeigt wird
    die Nachbarfarbe, geschrieben wird erst auf Knopfdruck."""
    profile.current().set_paint(seite._key(), "neon:anthrazit")
    seite._aus_profil_lesen()
    assert profile.current().paint(seite._key()) == "neon:anthrazit"


def test_die_auswahl_kommt_aus_der_palettendatei():
    """Stünde die Liste der unbunten Farben in der Seite, liefe sie gegen
    ``lacke.json``, sobald eine Farbe dazukommt.

    Geprüft werden die **Zeichenketten im Code**, nicht der Text der Datei: in
    Kommentaren und Beschreibungen dürfen die Namen selbstverständlich stehen,
    dort erklären sie ja gerade die Entscheidung.
    """
    import ast
    baum = ast.parse(open(os.path.join(_ROOT, "src", "states", "menu",
                                       "werkstatt_page.py"),
                          encoding="utf-8").read())
    beschreibungen = {id(ast.get_docstring(k, clean=False))
                      for k in ast.walk(baum)
                      if isinstance(k, (ast.Module, ast.ClassDef,
                                        ast.FunctionDef))}
    texte = [k.value.lower() for k in ast.walk(baum)
             if isinstance(k, ast.Constant) and isinstance(k.value, str)
             and id(k.value) not in beschreibungen]
    for name in ("anthrazit", "perlweiss", "neon"):
        assert name not in texte, name


def test_buntheit_trennt_die_palette_deutlich():
    """Die Schwelle muss weit von allem weg liegen, was sie trennt — sonst
    entscheidet sie irgendwann eine Farbe falsch, die niemand geprüft hat."""
    werte = {f["key"]: lack.buntheit(f["rgb"]) for f in lack.farben()}
    unbunt = [w for k, w in werte.items() if k in ("anthrazit", "perlweiss")]
    bunt = [w for k, w in werte.items() if k not in ("anthrazit", "perlweiss")]
    assert max(unbunt) < lack.BUNT_AB < min(bunt)
    assert min(bunt) - max(unbunt) > 0.3, "kein knappes Rennen"


# ---------------------------------------------------------------------------
# Die Meldung liegt nicht mehr auf dem Auto
# ---------------------------------------------------------------------------
def test_die_meldung_steht_in_der_schiene_nicht_auf_der_buehne(seite, spielstand,
                                                               monkeypatch):
    """Gemeldet: „der wird aber über das Fahrzeug gelegt und ist dadurch nur
    teilweise sichtbar"."""
    monkeypatch.setattr(version, "IS_RELEASE", True)
    _finish(seite, "metallic")
    _zeichnen(seite)
    keys = [f["key"] for f in lack.farben()]
    _klick(seite, dict(seite._farb_rects)[keys.index("tuerkis")].center)
    assert seite._grund, "die Meldung selbst muss kommen"

    # Die Bühne ist die linke, große Fläche; die Schiene die 440 px rechts
    # daneben. Gezeichnet wird die Meldung in der Schiene — also rechts von der
    # Bühnenmitte und unterhalb der Farbfelder.
    schiene_x = min(r.x for _i, r in seite._farb_rects)
    quelle = open(os.path.join(_ROOT, "src", "states", "menu",
                               "werkstatt_page.py"), encoding="utf-8").read()
    buehne = quelle.split("def _buehne_zeichnen")[1].split("\n    def ")[0]
    assert "self._grund" not in buehne and "self._meldung" not in buehne
    schiene = quelle.split("def _schiene_zeichnen")[1].split("\n    def ")[0]
    assert "self._grund" in schiene and "self._stand" in schiene
    assert schiene_x > 0


def test_die_meldung_liest_sich_als_ein_satz(seite, spielstand, monkeypatch):
    """Zweizeilig gezeichnet, einzeilig gelesen — Berichte und Tests brauchen
    den ganzen Text."""
    monkeypatch.setattr(version, "IS_RELEASE", True)
    spielstand.statistik["rennen"] = 7
    _finish(seite, "metallic")
    _farbe(seite, "tuerkis")
    assert seite._meldung == "Diese Lackierung ist noch gesperrt.  7 / 20 Rennen"


def test_eine_freie_wahl_meldet_nichts(seite):
    _finish(seite, "metallic")
    _farbe(seite, "rubinrot")
    assert seite._meldung == ""


# ---------------------------------------------------------------------------
# „Ansicht zurück" am Standardwinkel
# ---------------------------------------------------------------------------
def test_am_standardwinkel_ist_ansicht_zurueck_gesperrt(seite):
    assert seite.winkel == 0.0
    assert seite._knopf_ansicht.enabled is False


def test_gedreht_wird_er_frei_und_danach_wieder_gesperrt(seite):
    _zeichnen(seite)
    _klick(seite, seite._dreh_rects[1].center)
    assert seite.winkel != 0.0
    assert seite._knopf_ansicht.enabled is True
    _zeichnen(seite)
    _klick(seite, seite._knopf_ansicht.rect.center)
    assert seite.winkel == 0.0
    assert seite._knopf_ansicht.enabled is False


def test_eine_ganze_umdrehung_zaehlt_wieder_als_standardansicht(seite):
    """Ohne Rest bei 360 wäre der Knopf ab dem 24. Klick auf ewig frei, obwohl
    das Auto genau so steht wie am Anfang."""
    _zeichnen(seite)
    for _ in range(24):
        _klick(seite, seite._dreh_rects[1].center)
    assert seite.winkel == 0.0
    assert seite._knopf_ansicht.enabled is False


def test_ein_fahrzeugwechsel_stellt_die_ansicht_zurueck(seite):
    _zeichnen(seite)
    _klick(seite, seite._dreh_rects[0].center)
    ziel = next(i for i, _r in seite._kachel_rects if i != seite.index)
    _klick(seite, dict(seite._kachel_rects)[ziel].center)
    assert seite.winkel == 0.0
    assert seite._knopf_ansicht.enabled is False


def test_der_gesperrte_knopf_sagt_warum(seite):
    """Ein grauer Knopf ohne Grund sieht nach Fehler aus."""
    assert seite._knopf_ansicht.hint


def test_der_fokus_bleibt_nicht_auf_einem_gesperrten_knopf(seite):
    """Sonst läuft jede Taste ins Leere."""
    _zeichnen(seite)
    _klick(seite, seite._dreh_rects[1].center)
    seite._gruppe.index = seite._gruppe.widgets.index(seite._knopf_ansicht)
    _zeichnen(seite)
    _klick(seite, seite._knopf_ansicht.rect.center)     # Winkel wieder 0
    assert seite._gruppe.focused is not seite._knopf_ansicht
    assert getattr(seite._gruppe.focused, "focusable", False)


# ---------------------------------------------------------------------------
# Flottenstreifen: gleiten statt springen
# ---------------------------------------------------------------------------
def test_das_mausrad_blaettert_keine_ganze_seite(seite):
    """Gemeldet: „Scrollen der Fahrzeuge wirkt unnatürlich". Eine Raste = eine
    Seite ist genau das Springen."""
    assert len(seite.fahrzeuge) > KACHELN, "sonst prüft der Test nichts"
    seite.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, y=-1, x=0))
    assert 0 < seite._ziel_scroll < KACHELN


def test_der_streifen_gleitet_zum_ziel_statt_zu_springen(seite):
    seite.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, y=-1, x=0))
    assert seite.scroll == 0.0, "sofort umgesprungen wäre kein Gleiten"
    seite.update(1.0 / 60)
    zwischen = seite.scroll
    assert 0.0 < zwischen < seite._ziel_scroll
    for _ in range(120):
        seite.update(1.0 / 60)
    assert seite.scroll == seite._ziel_scroll


def test_das_gleiten_haengt_nicht_an_der_bildrate(seite):
    """Sonst scrollt es auf einer schnellen Maschine langsamer."""
    wege = []
    for schritt in (1.0 / 30, 1.0 / 144):
        s = WerkstattPage()
        s.enter(_Schale())
        s._ziel_scroll = 4.0
        gelaufen = 0.0
        while gelaufen < 0.2 - 1e-9:
            s.update(schritt)
            gelaufen += schritt
        wege.append(s.scroll)
    assert abs(wege[0] - wege[1]) < 0.15, wege


def test_die_pfeilknoepfe_blaettern_weiter_seitenweise(seite):
    """Sie heißen „blättern" — dort ist der Sprung gewollt."""
    _zeichnen(seite)
    _klick(seite, seite._blatt_rects[1].center)
    assert seite._ziel_scroll == min(float(KACHELN),
                                     float(len(seite.fahrzeuge) - KACHELN))


def test_der_streifen_laeuft_nicht_ueber_die_enden_hinaus(seite):
    for _ in range(50):
        seite.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, y=-1, x=0))
    assert seite._ziel_scroll == float(len(seite.fahrzeuge) - KACHELN)
    for _ in range(50):
        seite.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, y=1, x=0))
    assert seite._ziel_scroll == 0.0


def test_die_bildlaufleiste_ist_da_und_zieht(seite):
    _zeichnen(seite)
    assert seite._leiste_rect is not None
    r = seite._leiste_rect
    _klick(seite, (r.right - 2, r.centery))
    assert seite._ziel_scroll == float(len(seite.fahrzeuge) - KACHELN)
    seite.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=(r.x, r.centery),
                                          rel=(0, 0), buttons=(1, 0, 0)))
    assert seite._ziel_scroll == 0.0
    seite.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1,
                                          pos=(r.x, r.centery)))
    assert seite._zieht_leiste is False


def test_ziehen_folgt_dem_zeiger_ohne_nachlauf(seite):
    """Beim Ziehen ist der Zeiger der Führende; Nachlauf fühlt sich nach
    Gummiband an."""
    _zeichnen(seite)
    r = seite._leiste_rect
    _klick(seite, (r.centerx, r.centery))
    assert seite.scroll == seite._ziel_scroll


def test_halb_sichtbare_kacheln_sammeln_keine_klicks_daneben(seite):
    """Der Streifen ist beschnitten gezeichnet — die Klickfläche muss mit."""
    seite._ziel_scroll = seite.scroll = 2.5
    schirm = _zeichnen(seite)
    innen_links = min(r.x for _i, r in seite._kachel_rects)
    for _i, r in seite._kachel_rects:
        assert r.x >= innen_links
        assert r.right <= schirm.get_width()


def test_ohne_ueberlauf_gibt_es_keine_leiste(seite, monkeypatch):
    """Eine Leiste, die nichts zu zeigen hat, ist nur Zierde."""
    seite.fahrzeuge = seite.fahrzeuge[:3]
    seite.index = 0
    _zeichnen(seite)
    assert seite._leiste_rect is None
    assert seite._blatt_rects is None


def test_das_gewaehlte_fahrzeug_wird_in_den_streifen_geholt(seite):
    seite.index = len(seite.fahrzeuge) - 1
    seite._sichtbar_machen(sofort=True)
    assert seite.scroll == float(len(seite.fahrzeuge) - KACHELN)
    assert seite.scroll == seite._ziel_scroll, "beim Öffnen ohne Anlauf"


def test_zeichnen_stuerzt_in_jeder_stellung_nicht_ab(seite):
    for stand in (0.0, 0.5, 2.3, float(len(seite.fahrzeuge) - KACHELN), 99.0):
        seite.scroll = seite._ziel_scroll = stand
        _zeichnen(seite)


def test_der_puffer_von_gleiten_bleibt_positiv():
    """Ein Wert <= 0 stünde für „nie ankommen" bzw. „sofort springen"."""
    assert wp.GLEITEN > 0 and 0 < wp.RAD_WEITE < KACHELN


# ---------------------------------------------------------------------------
# Controller-Navigation (Playtest 05.08.2026)
# ---------------------------------------------------------------------------
# „Mit Controllersteuerung nicht möglich die Farben zu erreichen … Auch die
#  Fahrzeuge können mit dem Controller nicht erreicht werden. Die Steuerung muss
#  logischer sein wenn ich nach unten gehe möchte ich auch nach unten zu den
#  Fahrzeugen kommen und nicht nach rechts zum Lack."
#
# Ursache: Farbfelder und Fahrzeugkacheln entstehen erst beim Zeichnen und lagen
# gar nicht in der Fokusgruppe — sie waren nur per Mausklick zu treffen. Jetzt
# liegen sie drin, und damit erledigt die vorhandene Raumnavigation die Richtung
# von selbst.

def _pad(key: int) -> pygame.event.Event:
    """Ein Steuerkreuz-Druck, so wie der Gamepad-Manager ihn liefert."""
    return pygame.event.Event(pygame.KEYDOWN, key=key, unicode="", mod=0,
                              synthetic=True)


def _fokus(s: WerkstattPage):
    return s._gruppe.focused


def _fokus_auf(s: WerkstattPage, feld) -> None:
    s._gruppe.index = s._gruppe.widgets.index(feld)


def test_die_farbfelder_liegen_in_der_fokusgruppe(seite):
    _zeichnen(seite)
    erreichbar = [w for w in seite._farb_felder if w.focusable]
    assert erreichbar, "kein einziges Farbfeld ist mit dem Controller erreichbar"


def test_die_fahrzeugkacheln_liegen_in_der_fokusgruppe(seite):
    _zeichnen(seite)
    erreichbar = [w for w in seite._kachel_felder if w.focusable]
    assert erreichbar, "keine einzige Kachel ist mit dem Controller erreichbar"


def test_nur_sichtbare_kacheln_sind_erreichbar(seite):
    """Sonst stünde der Fokus auf einer Kachel, die niemand sieht."""
    _zeichnen(seite)
    erreichbar = sum(1 for w in seite._kachel_felder if w.focusable)
    assert erreichbar == len(seite._kachel_rects)
    assert erreichbar <= KACHELN


def test_runter_fuehrt_zu_den_fahrzeugen(seite):
    """Der Kern der Meldung: runter geht runter, nicht seitwärts zum Lack."""
    _zeichnen(seite)
    _fokus_auf(seite, seite._knopf_zurueck)
    for _ in range(12):
        seite.handle_event(_pad(pygame.K_DOWN))
        _zeichnen(seite)
        if _fokus(seite) in seite._kachel_felder:
            return
    pytest.fail(f"runter endete bei {getattr(_fokus(seite), 'action', None)}")


def test_die_kacheln_liegen_unter_den_farbfeldern(seite):
    """Die Voraussetzung dafür, dass „runter" überhaupt dorthin führen kann.

    Geprüft an der Geometrie und nicht am Ergebnis — läge der Streifen woanders,
    wäre der Test darüber grün, ohne dass die Bedienung stimmt.
    """
    _zeichnen(seite)
    farben = [w.rect for w in seite._farb_felder if w.focusable]
    kacheln = [w.rect for w in seite._kachel_felder if w.focusable]
    assert min(k.centery for k in kacheln) > max(f.centery for f in farben)


def test_eine_farbe_laesst_sich_per_controller_auftragen(seite):
    _zeichnen(seite)
    frei = [w for w in seite._farb_felder if w.focusable]
    ziel = frei[-1]
    _fokus_auf(seite, ziel)
    vorher = seite.farb_index
    seite.handle_event(_pad(pygame.K_RETURN))
    assert seite.farb_index != vorher or seite.finish_index > 0


def test_ein_fahrzeugwechsel_per_controller_fragt_nach(seite):
    """Am Controller darf nichts verlorengehen, was die Maus schützt."""
    _zeichnen(seite)
    _finish(seite, lack.finishes()[0]["key"])      # etwas Ungespeichertes
    assert seite._geaendert()
    _zeichnen(seite)
    andere = [w for w in seite._kachel_felder
              if w.focusable and w is not seite._kachel_felder[seite.index]]
    _fokus_auf(seite, andere[-1])
    seite.handle_event(_pad(pygame.K_RETURN))
    assert seite._dialog is not None, "der Wechsel ging ohne Rückfrage durch"


def test_die_stepper_regel_bleibt_unangetastet(seite):
    """Entschieden am 05.08.2026: nur die Navigation wird repariert.

    Ein Stepper bleibt am Controller ein geschlossenes Bedienelement — erst A,
    dann links/rechts. Die neuen Felder sind keine Stepper und lösen direkt aus.
    """
    assert seite._finish_stepper.bearbeitbar is True
    assert all(w.bearbeitbar is False for w in seite._farb_felder)
    assert all(w.bearbeitbar is False for w in seite._kachel_felder)
