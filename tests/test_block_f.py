"""Block F2 — was ein neuer Spieler beim ersten Start und im Fehlerfall sieht.

Drei Punkte aus der Auslieferungsliste, alle mit derselben Frage dahinter: was
weiß jemand, der das Spiel zum ersten Mal öffnet, und was weiß jemand, dem es
gerade abgestürzt ist?

* **Kurzanleitung beim ersten Start.** Bis zum 05.08.2026 kam nach dem
  Fahrernamen sofort das Hauptmenü. Steuerung, Zeitfahren, Werkstatt — alles
  musste man selbst finden.
* **``crash.log`` verlinken.** Nach einem Absturz steht der Pfad sechs Sekunden
  lang auf einem roten Bildschirm. Das reicht zum Lesen, nicht zum Abschreiben,
  und im gepackten macOS-Bündel liegt die Datei ohnehin woanders als im
  Arbeitsverzeichnis.
* **Unverschlüsselter Online-Verkehr.** Aus Block H1: niemand soll mehr
  Vertraulichkeit annehmen, als da ist. Ausdrücklich nicht als Kleingedrucktes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pygame
import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from src.core import absturz, i18n, keybindings as kb, profile, sfx  # noqa: E402
from src.states import welcome_state as ws  # noqa: E402
from src.states.menu.settings_page import SettingsPage  # noqa: E402


@pytest.fixture(autouse=True)
def deutsch_danach():
    yield
    i18n.set_language("de")


@pytest.fixture
def eigenes_profil(monkeypatch):
    p = profile.Profile(username="Testfahrer")
    p.save = lambda: None
    monkeypatch.setattr(profile, "_current", p, raising=False)
    monkeypatch.setattr(profile, "current", lambda: p)
    monkeypatch.setattr(sfx, "spielen", lambda *a, **k: None)
    return p


class _Maschine:
    """Nur das, was WelcomeState anfasst."""

    def __init__(self) -> None:
        self.gewechselt: list[str] = []

    def transition(self, name: str, **kwargs) -> None:
        self.gewechselt.append(name)


def _taste(key: int) -> pygame.event.Event:
    return pygame.event.Event(pygame.KEYDOWN, key=key, unicode="", mod=0)


def _klick(pos) -> pygame.event.Event:
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos)


@pytest.fixture
def start(eigenes_profil):
    m = _Maschine()
    z = ws.WelcomeState(m)
    z.enter()
    return z, m


# ===========================================================================
# Kurzanleitung beim ersten Start
# ===========================================================================
def test_nach_dem_namen_kommt_die_kurzanleitung_und_nicht_das_menue(start):
    """Der gemeldete Punkt: „heute landet man ohne Erklärung im Menü"."""
    z, m = start
    z.input.text = "Neuling"
    z._confirm()
    assert z.schritt == ws.SCHRITT_HILFE
    assert m.gewechselt == [], "das Menü kam vor der Anleitung"


def test_der_name_ist_vor_der_anleitung_schon_gespeichert(start, eigenes_profil):
    """Wer das Fenster auf der Anleitung schließt, hat trotzdem ein Profil —
    sonst stünde er beim nächsten Start wieder bei der Namenseingabe."""
    z, _m = start
    z.input.text = "Neuling"
    z._confirm()
    assert profile.current().username == "Neuling"


def test_ein_abgelehnter_name_bleibt_auf_der_namensseite(start):
    z, _m = start
    z.input.text = "x"                      # zu kurz
    z._confirm()
    assert z.schritt == ws.SCHRITT_NAME
    assert z.error


@pytest.mark.parametrize("key", [pygame.K_RETURN, pygame.K_ESCAPE, pygame.K_SPACE])
def test_jede_bestaetigung_fuehrt_von_der_anleitung_ins_menue(start, key):
    """Die Anleitung ist kein Dialog mit einer Wahl. Auch ESC geht vorwärts —
    wer sie nicht lesen will, soll nicht suchen müssen, wie er sie loswird."""
    z, m = start
    z.input.text = "Neuling"
    z._confirm()
    z.handle_events([_taste(key)])
    assert m.gewechselt == ["menu"]


def test_der_knopf_fuehrt_ins_menue(start):
    z, m = start
    z.input.text = "Neuling"
    z._confirm()
    z.handle_events([_klick(z.weiter.rect.center)])
    assert m.gewechselt == ["menu"]


def test_auf_der_anleitung_tippt_niemand_mehr_am_namen(start):
    """Derselbe Zustand, zwei Schritte: die Namenseingabe darf hier keine
    Tasten mehr sehen, sonst hieße der Fahrer am Ende „NeulingX"."""
    z, _m = start
    z.input.text = "Neuling"
    z._confirm()
    z.handle_events([_taste(pygame.K_x)])
    assert z.input.text == "Neuling"


def test_die_anleitung_nennt_die_eigene_tastenbelegung(monkeypatch):
    """Die Zeilen kommen aus ``keybindings``, nicht aus dem Text. Wer Gas auf
    W gelegt hat, soll nicht „Pfeil hoch" lesen."""
    echt = kb.get
    monkeypatch.setattr(kb, "get",
                        lambda a: pygame.K_w if a == "throttle" else echt(a))
    fahren = dict(ws.spielhinweise())[i18n.tr("Fahren")]
    assert kb.key_name(pygame.K_w) in fahren


def test_die_anleitung_bleibt_kurz():
    """„Kurzes ‚So spielst du'" — kurze Zeilen, keine Bedienungsanleitung.

    Seit dem 05.08.2026 (Playtest-Fund) sind es sieben statt sechs: die siebte
    sagt nur, wo Ankündigungen stehen, nicht, was gerade angekündigt ist —
    darum bleibt die Zeile genauso kurz wie die anderen.
    """
    zeilen = ws.spielhinweise()
    assert len(zeilen) == 7
    for titel, text in zeilen:
        assert titel.strip() and text.strip()
        assert len(text) < 120, text


def test_die_anleitung_zeichnet_ohne_absturz(start):
    z, _m = start
    z.input.text = "Neuling"
    z._confirm()
    schirm = pygame.Surface((1920, 1080), pygame.SRCALPHA)
    z.render(schirm)                        # keine Ausnahme = bestanden


def test_die_anleitung_gibt_es_auch_auf_englisch(start):
    i18n.set_language("en")
    zeilen = dict(ws.spielhinweise())
    assert "Driving" in zeilen
    assert "throttle" in zeilen["Driving"]


# ===========================================================================
# crash.log
# ===========================================================================
def test_der_pfad_des_absturzberichts_liegt_an_einer_stelle():
    """``main.py`` schreibt und die Einstellungen verlinken — beide über
    ``absturz.pfad()``. Zwei eigene Pfade wären zwei Gelegenheiten,
    auseinanderzulaufen."""
    quelle = (_ROOT / "main.py").read_text(encoding="utf-8")
    assert "absturz.schreiben(" in quelle
    assert "crash.log" not in quelle, "main.py baut den Pfad wieder selbst"


def test_der_bericht_wird_dorthin_geschrieben_wo_er_gesucht_wird(tmp_path, monkeypatch):
    monkeypatch.setattr("src.core.paths.user_data_dir", lambda: tmp_path)
    assert not absturz.vorhanden()
    ziel = absturz.schreiben("Traceback (most recent call last): ...")
    assert ziel == absturz.pfad()
    assert absturz.vorhanden()
    assert "Traceback" in ziel.read_text(encoding="utf-8")


def test_ohne_bericht_wird_nichts_geoeffnet(tmp_path, monkeypatch):
    monkeypatch.setattr("src.core.paths.user_data_dir", lambda: tmp_path)
    assert absturz.oeffnen() is False


def test_ein_fehlschlag_beim_oeffnen_stuerzt_nicht_ab(tmp_path, monkeypatch):
    """Der Weg zur Fehlermeldung darf nicht die nächste Fehlermeldung sein."""
    monkeypatch.setattr("src.core.paths.user_data_dir", lambda: tmp_path)
    absturz.schreiben("egal")
    monkeypatch.setattr(absturz.subprocess, "Popen",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("kein xdg-open")))
    monkeypatch.setattr(absturz.sys, "platform", "linux")
    assert absturz.oeffnen() is False


def test_der_pfad_steht_auch_ohne_datei_fest(tmp_path, monkeypatch):
    """Ohne Bericht nennen die Einstellungen den Pfad statt eines toten Links —
    dafür muss er auch dann beantwortbar sein."""
    monkeypatch.setattr("src.core.paths.user_data_dir", lambda: tmp_path)
    assert absturz.pfad().name == "crash.log"
    assert not absturz.vorhanden()


# ===========================================================================
# Einstellungen → Info
# ===========================================================================
@pytest.fixture
def info_seite(eigenes_profil):
    s = SettingsPage()
    s.enter(type("Schale", (), {"state_machine": None})())
    s.cat = s.categories.index("Info")
    s._build_content()
    return s


def _info_zeichnen(s: SettingsPage) -> pygame.Surface:
    schirm = pygame.Surface((1920, 1080), pygame.SRCALPHA)
    s._draw_info(schirm)
    return schirm


def test_info_verlinkt_den_absturzbericht(info_seite, tmp_path, monkeypatch):
    monkeypatch.setattr("src.core.paths.user_data_dir", lambda: tmp_path)
    absturz.schreiben("Traceback ...")
    _info_zeichnen(info_seite)
    assert info_seite._crash_rect is not None


def test_ohne_bericht_gibt_es_keinen_toten_link(info_seite, tmp_path, monkeypatch):
    monkeypatch.setattr("src.core.paths.user_data_dir", lambda: tmp_path)
    _info_zeichnen(info_seite)
    assert info_seite._crash_rect is None


def test_ein_klick_auf_den_link_oeffnet_den_bericht(info_seite, tmp_path, monkeypatch):
    monkeypatch.setattr("src.core.paths.user_data_dir", lambda: tmp_path)
    absturz.schreiben("Traceback ...")
    _info_zeichnen(info_seite)
    geoeffnet = []
    monkeypatch.setattr(absturz, "oeffnen", lambda: geoeffnet.append(True) or True)
    assert info_seite.handle_event(_klick(info_seite._crash_rect.center)) is True
    assert geoeffnet == [True]


def test_der_link_zu_github_funktioniert_weiter(info_seite, monkeypatch):
    """Der neue Link sitzt unter dem alten — der darf dabei nicht verrutschen."""
    _info_zeichnen(info_seite)
    import webbrowser
    gerufen = []
    monkeypatch.setattr(webbrowser, "open", lambda url: gerufen.append(url))
    assert info_seite.handle_event(_klick(info_seite._issues_rect.center)) is True
    assert gerufen and "issues" in gerufen[0]


def test_der_hinweis_auf_klartext_steht_nicht_mehr_in_der_info():
    """Am 05.08.2026 entschieden: der Satz kommt wieder heraus und auch nicht
    in die itch.io-Beschreibung.

    Er stand einen Tag lang dort (Block H1). Der Test bleibt in die andere
    Richtung stehen, damit der Satz nicht bei der nächsten Durchsicht von Block
    H „wieder eingebaut" wird — das ist eine Entscheidung, keine Lücke. Am
    Verkehr selbst ändert sich nichts: er ist unverändert unverschlüsselt.
    """
    quelle = (_ROOT / "src" / "states" / "menu" / "settings_page.py").read_text(
        encoding="utf-8")
    gezeichnet = [z for z in quelle.splitlines()
                  if "unverschlüsselt" in z and not z.lstrip().startswith("#")]
    assert gezeichnet == [], gezeichnet

    sprachdatei = json.loads(
        (_ROOT / "data" / "i18n" / "en.json").read_text(encoding="utf-8"))
    assert not any("unencrypted" in v for v in sprachdatei.values())


def test_die_info_seite_zeichnet_mit_und_ohne_bericht(info_seite, tmp_path, monkeypatch):
    monkeypatch.setattr("src.core.paths.user_data_dir", lambda: tmp_path)
    _info_zeichnen(info_seite)
    absturz.schreiben("Traceback ...")
    _info_zeichnen(info_seite)
