"""Einstellungen: Anzeigetext ist keine Logik (Playtest 04.08.2026).

Gemeldeter Absturz beim Verstellen der Musik:

    File "src\\states\\menu\\settings_page.py", line 613, in _dispatch
    ValueError: invalid literal for int() with base 10: 'Muted'

Die Ursache ist ein Muster, nicht eine Zeile: ``_dispatch`` hat den **angezeigten**
Text eines Steppers zurückgerechnet. Der ist übersetzt — „Stumm" heißt auf
Englisch „Muted", „Vollbild" heißt „Fullscreen". Damit gab es **sechs** Fehler,
die alle nur auf Englisch auftreten, und nur einer davon war laut:

===========================  ==================================================
Regler                        Auf Englisch
===========================  ==================================================
Musik (Menü) / (Rennen)       ``int("Muted")`` → **Absturz**
Fenstermodus                  ``"Fullscreen" == "Vollbild"`` → nie Vollbild
FPS-Limit                     Beschriftung nicht in der Tabelle → immer 60
Texturqualität                „High" landet im Profil statt „Hoch"
V-Sync                        ``"On" == "An"`` → nie einschaltbar
===========================  ==================================================

Geprüft wird deshalb nicht der eine Absturz, sondern die Regel: **in jeder
Sprache muss dasselbe herauskommen.**
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.core import i18n, profile, sfx  # noqa: E402
from src.states.menu.settings_page import SettingsPage  # noqa: E402

AUDIO = ["change_menu_volume", "change_race_volume",
         "change_sfx_menu_volume", "change_sfx_race_volume"]
VIDEO = ["change_resolution", "toggle_fullscreen", "change_fps",
         "change_texquality", "toggle_vsync"]


@pytest.fixture(autouse=True)
def deutsch_danach():
    yield
    i18n.set_language("de")


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


def _stellen(s: SettingsPage, kategorie: str, index: int) -> None:
    s.cat = s.categories.index(kategorie)
    s._build_content()
    for w in s._content_group.widgets:
        if hasattr(w, "index") and getattr(w, "options", None):
            w.index = min(index, len(w.options) - 1)


def _auswerten(s: SettingsPage, kategorie: str, aktionen: list[str],
               index: int) -> dict:
    _stellen(s, kategorie, index)
    for a in aktionen:
        s._dispatch(a)
    return dict(s._pending)


# ---------------------------------------------------------------------------
# Der gemeldete Absturz
# ---------------------------------------------------------------------------
def test_der_musikregler_stuerzt_auf_englisch_nicht_ab(seite):
    """Genau der gemeldete Weg: Sprache Englisch, Regler auf Stumm."""
    i18n.set_language("en")
    _stellen(seite, "Audio", 0)          # Stellung 0 = „Muted"
    seite._dispatch("change_menu_volume")
    assert seite._pending["menu_volume"] == 0.0


@pytest.mark.parametrize("sprache", ["de", "en"])
@pytest.mark.parametrize("stellung", [0, 1, 5, 10])
def test_die_lautstaerkeregler_liefern_in_jeder_sprache_dasselbe(seite, sprache,
                                                                stellung):
    i18n.set_language(sprache)
    werte = _auswerten(seite, "Audio", AUDIO, stellung)
    erwartet = stellung / 10.0
    for feld in ("menu_volume", "race_volume", "sfx_menu_volume", "sfx_race_volume"):
        assert werte[feld] == pytest.approx(erwartet), (sprache, stellung, feld)


# ---------------------------------------------------------------------------
# Die fünf stillen Geschwister
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("stellung", [0, 1, 2, 4])
def test_die_videoregler_liefern_in_jeder_sprache_dasselbe(seite, stellung):
    """Der eigentliche Fund: nicht ein Absturz, sondern fünf Einstellungen, die
    auf Englisch stillschweigend nicht funktionierten."""
    deutsch = _auswerten(seite, "Video", VIDEO, stellung)
    seite._pending = {}
    i18n.set_language("en")
    englisch = _auswerten(seite, "Video", VIDEO, stellung)
    assert deutsch == englisch, stellung


def test_vollbild_laesst_sich_auch_auf_englisch_einschalten(seite):
    i18n.set_language("en")
    assert _auswerten(seite, "Video", ["toggle_fullscreen"], 1)["fullscreen"] is True
    seite._pending = {}
    assert _auswerten(seite, "Video", ["toggle_fullscreen"], 0)["fullscreen"] is False


def test_vsync_laesst_sich_auch_auf_englisch_einschalten(seite):
    i18n.set_language("en")
    assert _auswerten(seite, "Video", ["toggle_vsync"], 1)["vsync"] is True


def test_das_fps_limit_kennt_alle_stufen_auch_auf_englisch(seite):
    i18n.set_language("en")
    gesehen = []
    for stellung in range(6):
        seite._pending = {}
        gesehen.append(_auswerten(seite, "Video", ["change_fps"], stellung)["fps_limit"])
    assert gesehen == [30, 60, 120, 144, 240, 0], gesehen


def test_die_texturqualitaet_landet_deutsch_im_profil(seite):
    """Im Profil steht der **Schlüssel**, nicht die Anzeige — sonst findet
    ``tr()`` beim nächsten Start nichts zu übersetzen."""
    i18n.set_language("en")
    assert _auswerten(seite, "Video", ["change_texquality"], 1)["texture_quality"] == "Hoch"
    seite._pending = {}
    assert _auswerten(seite, "Video", ["change_texquality"], 0)["texture_quality"] == "Niedrig"


# ---------------------------------------------------------------------------
# Dass niemand zurückfällt
# ---------------------------------------------------------------------------
def test_kein_regler_rechnet_noch_anzeigetext_zurueck():
    """Die Regel selbst. Wer wieder ``stepper.value`` auswertet, holt den Fehler
    zurück — in einer Sprache, die er beim Testen nicht eingestellt hat."""
    quelle = open(os.path.join(_ROOT, "src", "states", "menu", "settings_page.py"),
                  encoding="utf-8").read()
    dispatch = quelle.split("def _dispatch")[1].split("\n    def ")[0]
    assert "stepper.value" not in dispatch
    assert ".value ==" not in dispatch


def test_ein_falscher_index_stuerzt_nicht_ab(seite):
    """Eine Einstellungsseite darf am falschen Index nicht sterben."""
    _stellen(seite, "Video", 0)
    assert seite._rohwert("gibtsnicht", 0) is None
    assert seite._rohwert("change_fps", 99) == 30
    seite._content_group.widgets[2].index = 99
    assert seite._rohwert("change_fps", 2) == 30


# ---------------------------------------------------------------------------
# Der Vorhör-Klang
# ---------------------------------------------------------------------------
def test_der_effektregler_spielt_keinen_aufprall_mehr(seite, monkeypatch):
    """Gemeldet: „spielt den crash sound ab bei jedem 10% Änderung, nicht
    userfreundlich da sehr laut"."""
    gespielt = []
    monkeypatch.setattr(sfx, "spielen",
                        lambda name, *a, **k: gespielt.append(name))
    _stellen(seite, "Audio", 5)
    seite._dispatch("change_sfx_race_volume")
    assert gespielt and "crash" not in gespielt[-1]
    assert gespielt[-1] != "car-wall"


def test_beide_effektregler_hoeren_ihren_eigenen_bereich_vor(seite, monkeypatch):
    """Sonst beurteilt man den Rennregler an einem Menüklick."""
    gespielt = []
    monkeypatch.setattr(sfx, "spielen",
                        lambda name, *a, **k: gespielt.append(name))
    _stellen(seite, "Audio", 5)
    seite._dispatch("change_sfx_menu_volume")
    seite._dispatch("change_sfx_race_volume")
    assert gespielt[0] != gespielt[1]


def test_die_vorhoerdatei_gibt_es_wirklich(seite):
    """Ein Vorhören, das ins Leere greift, ist ein stiller Regler."""
    for name in ("click", "tire-screeching-1"):
        assert os.path.isfile(sfx._pfad(f"{name}.wav")), name


# ---------------------------------------------------------------------------
# CPU-Last: die Bildrate-Obergrenze (Playtest 04.08.2026)
# ---------------------------------------------------------------------------
class _Zustand:
    pass


def _spiel(fps_limit, im_menue: bool, mit_menue: bool = True):
    """Ein Game-Gerüst ohne pygame-Fenster — nur die Grenzenrechnung."""
    from src.core.game import GameManager
    g = GameManager.__new__(GameManager)
    g.menu_state = _Zustand() if mit_menue else None
    g.state_machine = _Zustand()
    g.state_machine.current = g.menu_state if im_menue else _Zustand()
    p = profile.Profile(username="x")
    p.fps_limit = fps_limit
    p.save = lambda: None
    import pytest as _pt
    with _pt.MonkeyPatch.context() as mp:
        mp.setattr(profile, "_current", p, raising=False)
        mp.setattr(profile, "current", lambda: p)
        return g._bildgrenze()


def test_im_menue_wird_unbegrenzt_gedeckelt():
    """Gemeldet: 40–50 % CPU in der Lobby, 30 % im Rennen. Die Lobby war teurer
    als das Rennen — das geht nur, wenn dort viel mehr Durchläufe hineinpassen.
    Eine höhere Bildrate bringt im Menü nichts."""
    from src.core.game import GameManager
    assert _spiel(0, im_menue=True) == GameManager.MENUE_GRENZE


def test_im_rennen_bleibt_unbegrenzt_unbegrenzt():
    """Dort ist es ein echter Vorteil, und die Physik rechnet mit dem
    gemessenen Zeitschritt."""
    assert _spiel(0, im_menue=False) == 0


@pytest.mark.parametrize("grenze", [30, 60, 120, 144, 240])
def test_im_rennen_gilt_die_eingestellte_zahl_unveraendert(grenze):
    """Die Einstellung ist eine Aussage über das Rennen — dort bleibt sie."""
    assert _spiel(grenze, im_menue=False) == grenze


@pytest.mark.parametrize("grenze", [120, 144, 240])
def test_im_menue_deckelt_die_menuegrenze_nach_oben(grenze):
    """Geändert am 05.08.2026 auf Wunsch: im Menü ist bei 60 Schluss.

    Vorher wurde nur „Unbegrenzt" umgedeutet. Gemeldet wurden aber 40–50 % CPU
    **auch bei eingestellten 30 Bildern** — das kann eine Grenze, die nur
    „Unbegrenzt" abfängt, nicht erklären, und eine höhere Bildrate bringt im
    Menü ohnehin nichts.
    """
    from src.core.game import GameManager
    assert _spiel(grenze, im_menue=True) == GameManager.MENUE_GRENZE


@pytest.mark.parametrize("grenze", [30, 60])
def test_eine_kleinere_zahl_bleibt_im_menue_kleiner(grenze):
    """Gedeckelt heißt nach oben. Wer 30 wählt, bekommt 30 und nicht 60 —
    sonst machte der Deckel aus einer Sparsamkeit eine Verdopplung."""
    assert _spiel(grenze, im_menue=True) == grenze


def test_vor_dem_aufbau_der_zustaende_gilt_die_zielrate():
    from src.core.settings import TARGET_FPS
    assert _spiel(0, im_menue=False, mit_menue=False) == TARGET_FPS


def test_die_vignette_unterscheidet_ihre_staerken():
    """Der Schlüssel ignorierte die Stärke — der zweite Aufrufer bekam die
    Fläche des ersten, und eine der beiden Seiten war falsch abgedunkelt."""
    from src.ui import theme
    a = theme.vignette((320, 200), 90)
    b = theme.vignette((320, 200), 120)
    assert a is not b
    assert theme.vignette((320, 200), 90) is a, "nicht mehr zwischengespeichert"
