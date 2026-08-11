"""Optische Schaeden als **Regel** pruefen, nicht einzeln nachtragen.

Bis zum 07.08.2026 gab es zu jeder gemeldeten Ueberlagerung genau einen Test:
Ping ueber Lobbyzahl in der Serverliste (28.07.), Ankuendigungstitel unter dem
Kasten (05.08.), Beschriftungen im Leistungsdiagramm (05.08.). Jeder davon
haelt seine eine Stelle fest. Die **Regel** dahinter — kein Text liegt auf
einem anderen, nichts laeuft aus dem Bild — war nie gepruefte Zusage, sondern
Gewohnheit. Deshalb kam der naechste Fall immer aus einer Ecke, an die niemand
gedacht hatte.

**Wie gemessen wird.** ``theme.text`` und ``theme.text_fit`` geben das Rechteck
zurueck, in das sie wirklich gemalt haben. Der Test belauscht beide und
vergleicht die Rechtecke. Das ist kein Nachbau des Layouts — ein nachgerechnetes
Layout kann sich irren — sondern das, was auf dem Bildschirm steht.

**Tinte statt Schriftkasten.** Verglichen werden nicht die Flaechen, die
pygame fuer eine Zeile belegt, sondern die Pixel, in denen wirklich Zeichen
stehen. Der Unterschied ist nicht klein: die Ueberschrift „WERTUNG & FAHRER"
in der Grand-Prix-Uebersicht belegt y=165..195, die Spaltenkoepfe darunter
y=186..208 — die Kaesten ueberschneiden sich um 9 px, die Zeichen stehen aber
bei y=173..189 und y=193..208 und lassen **4 px Luft**. Der erste Anlauf am
07.08.2026 verglich die Kaesten und meldete vier Fehler, von denen keiner zu
sehen war. Wer die Reserve fuer Ober- und Unterlaengen mitmisst, misst die
Schrift und nicht das Layout.

**Warum beide Sprachen.** Deutscher Text ist laenger als englischer
("Einstellungen" gegen "Settings"), und ein Layout, das auf Englisch passt,
laeuft auf Deutsch ueber. Sechs Fehler dieser Art gab es schon einmal an einem
Tag (04.08.2026, Stepper-Beschriftungen).
"""
from __future__ import annotations

import os
import sys
import types

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.core import display  # noqa: E402
from src.states import menu_shell_state  # noqa: E402
from tests import spielhilfe  # noqa: E402

#: Das Spiel zeichnet **immer** in eine feste Flaeche von 1920x1080 und
#: skaliert die erst aufs Fenster (``src/core/display.py``). Eine kleinere
#: Fenstergroesse aendert am Layout also nichts — sie in den Test aufzunehmen
#: haette geprueft, was das Spiel gar nicht tut. Am 07.08.2026 zuerst
#: andersherum gebaut und beim ersten Lauf korrigiert.
_BILD = (display.SCREEN_WIDTH, display.SCREEN_HEIGHT)

#: Die Flaeche, die die Schale einer Seite gibt: alles unter der Reiterleiste.
#: Aus ``MenuShellState._content_area`` uebernommen und nicht erfunden — eine
#: erfundene Flaeche prueft ein Layout, das es nicht gibt.
_INHALT = pygame.Rect(0, menu_shell_state.TAB_H,
                      display.SCREEN_WIDTH,
                      display.SCREEN_HEIGHT - menu_shell_state.TAB_H)


@pytest.fixture(autouse=True)
def _aufbau_bewahren(monkeypatch):
    """Das Zeichnen einer Seite darf den Rennaufbau nicht veraendern —
    und wo es das doch tut, soll es der naechste Test nicht merken."""
    spielhilfe.aufbau_bewahren(monkeypatch)


class _ShellAttrappe:
    """Was eine Seite von ihrer Schale erwartet — mehr nicht."""

    def __init__(self) -> None:
        self.state_machine = types.SimpleNamespace(
            transition=lambda *a, **k: None)
        self.zurueck_zaehler = 0

    def zurueck_gehen(self) -> None:
        self.zurueck_zaehler += 1

    def pop_page(self) -> None:
        self.zurueck_zaehler += 1

    def push_page(self, seite) -> None:
        pass


def _seiten():
    """Jede Menueseite mit einem Weg, sie zu bauen.

    Als Funktionen und nicht als fertige Objekte: eine Seite haelt nach dem
    Zeichnen Zustand, und der naechste Durchlauf soll bei null anfangen.
    """
    from src.states.menu import (coming_soon_page, gp_overview_page, lobby_page,
                                 mp_lobby_page, mp_name_page, online_lobby_page,
                                 profil_page, results_page, settings_page,
                                 werkstatt_page)

    return {
        "Einstellungen": settings_page.SettingsPage,
        "Profil": profil_page.ProfilPage,
        "Lobby": lobby_page.LobbyPage,
        "Mehrspieler-Lobby": mp_lobby_page.MPLobbyPage,
        "Mehrspieler-Name": mp_name_page.MPNamePage,
        "Werkstatt": werkstatt_page.WerkstattPage,
        "Grand-Prix-Uebersicht": gp_overview_page.GPOverviewPage,
        "Online": online_lobby_page.OnlineLobbyPage,
        "Demnaechst": lambda: coming_soon_page.ComingSoonPage("Test"),
        "Ergebnisse": lambda: results_page.ResultsPage(_ERGEBNISZEILEN),
    }


#: Ein Ergebnis, wie es aus einem Rennen kommt. Sechs Zeilen, damit die Tabelle
#: voll ist — eine leere Tabelle kann sich nicht ueberlagern.
_ERGEBNISZEILEN = [
    {"vehicle_id": i, "name": f"Fahrer {i}", "position": i,
     "finish_time": 60.0 + i, "best_lap": 30.0 + i,
     "lap_times": [30.0 + i, 30.5 + i], "dnf": False}
    for i in range(1, 7)
]


def _zeichnen(seite) -> pygame.Surface:
    """Die Seite so zeichnen, wie die Schale es tut."""
    schirm = pygame.Surface(_BILD)
    schirm.fill((0, 0, 0))
    seite.enter(_ShellAttrappe())
    seite.draw(schirm, _INHALT)
    return schirm


def _echte_ueberlagerungen(mitschrift) -> list[str]:
    """Jedes Paar, dessen Zeichen sich beruehren — als Klartext.

    Keine Schwelle mehr: seit die Tinte verglichen wird, ist jede Beruehrung
    eine. Ein Pixel Ueberschneidung zwischen zwei Buchstaben ist genau das,
    was gemeldet werden soll.
    """
    return [f"{a.text!r}{tuple(a.tinte)} liegt auf {b.text!r}{tuple(b.tinte)}"
            for a, b in mitschrift.ueberlagerungen()]


# ---------------------------------------------------------------------------
# Die Regel
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sprache", ["de", "en"])
@pytest.mark.parametrize("name", sorted(_seiten()))
def test_auf_keiner_seite_liegt_text_auf_text(name, sprache, monkeypatch):
    spielhilfe.sprache_setzen(monkeypatch, sprache)
    mit = spielhilfe.gezeichnete_texte(monkeypatch)

    _zeichnen(_seiten()[name]())

    assert mit.zuege, f"{name}: die Seite hat gar keinen Text gezeichnet"
    schlimm = _echte_ueberlagerungen(mit)
    assert schlimm == [], f"{name} ({sprache}):\n" + "\n".join(schlimm)


@pytest.mark.parametrize("sprache", ["de", "en"])
@pytest.mark.parametrize("name", sorted(_seiten()))
def test_kein_text_laeuft_seitlich_aus_dem_bild(name, sprache, monkeypatch):
    """Links und rechts, nicht oben und unten.

    Senkrecht darf Inhalt ueber den Rand hinausgehen: die rollenden Seiten
    (Profil, Ergebnisse) zeichnen bewusst mehr, als zu sehen ist, und
    beschneiden es mit ``set_clip``. Waagerecht gibt es dafuer keinen Grund —
    ein Text, der rechts hinauslaeuft, ist abgeschnitten und nicht lesbar.
    Genau das war der zweite Fund vom 28.07.2026 in der Serverliste.
    """
    spielhilfe.sprache_setzen(monkeypatch, sprache)
    mit = spielhilfe.gezeichnete_texte(monkeypatch)

    _zeichnen(_seiten()[name]())

    raus = [f"{z.text!r} von x={z.tinte.left} bis x={z.tinte.right}"
            for z in mit.zuege
            if z.tinte.left < 0 or z.tinte.right > _BILD[0]]
    assert raus == [], f"{name} ({sprache}):\n" + "\n".join(raus)


#: Ankuendigungen, wie der Server sie schickt. Absichtlich lang und mehrere —
#: der Kasten auf der Info-Seite rollt, und nur mit genug Inhalt gibt es
#: ueberhaupt etwas zu rollen.
_ANKUENDIGUNGEN = {
    "announcements": [
        {"id": f"a{i}", "date": f"2026-07-{29 - i:02d}",
         "title": {"de": f"Neue Version 0.6.{i}-beta",
                   "en": f"New version 0.6.{i}-beta"},
         "text": {"de": "Neuer Modus Grand Prix verfügbar in: " + "Zeile " * 40,
                  "en": "New Grand Prix mode available in: " + "line " * 40}}
        for i in range(4)
    ],
    "version_ok": True,
}


@pytest.mark.parametrize("mit_ankuendigungen", [False, True],
                         ids=["ohne-Ankuendigungen", "mit-Ankuendigungen"])
@pytest.mark.parametrize("sprache", ["de", "en"])
def test_die_info_seite_bleibt_auch_mit_ankuendigungen_sauber(
        sprache, mit_ankuendigungen, monkeypatch):
    """Der Reiter, der am 07.08.2026 auf dem Bauknecht rot war.

    Er ist der einzige mit Inhalt aus dem Netz, und genau daran hing es: ohne
    Netz war der Kasten leer und alles gruen, mit Netz standen Ankuendigungen
    darin. Der Fall gehoert nicht dem Zufall ueberlassen, sondern beide Male
    geprueft — deshalb hier gesetzt statt geholt.

    Dass die Meldung damals ein Fehlalarm war (die Eintraege stehen in einem
    beschnittenen Kasten und sind unterhalb von y=900 unsichtbar), aendert
    nichts daran, dass der Reiter geprueft gehoert.
    """
    from src.net import server_info
    from src.states.menu.settings_page import SettingsPage

    spielhilfe.sprache_setzen(monkeypatch, sprache)
    inhalt = _ANKUENDIGUNGEN if mit_ankuendigungen else None
    monkeypatch.setattr(server_info, "get_cached", lambda: inhalt)
    monkeypatch.setattr(server_info, "version_ok", lambda: True)

    seite = SettingsPage()
    if "Info" not in seite.categories:
        pytest.skip("kein Info-Reiter in dieser Fassung")

    mit = spielhilfe.gezeichnete_texte(monkeypatch)
    schirm = pygame.Surface(_BILD)
    schirm.fill((0, 0, 0))
    seite.enter(_ShellAttrappe())
    seite.cat = seite.categories.index("Info")
    seite.draw(schirm, _INHALT)

    schlimm = _echte_ueberlagerungen(mit)
    assert schlimm == [], f"Info ({sprache}, {mit_ankuendigungen}):\n" + \
        "\n".join(schlimm)


@pytest.mark.parametrize("kategorie", range(6))
@pytest.mark.parametrize("sprache", ["de", "en"])
def test_jeder_reiter_der_einstellungen_bleibt_sauber(kategorie, sprache,
                                                      monkeypatch):
    """Die Einstellungen sind sechs Seiten in einer.

    Der Fund vom 05.08.2026 — „Ankuendigungen Ueberschrift wird von den
    Ankuendigungen selbst ueberlagert" — steckte in genau einem dieser Reiter.
    Die anderen fuenf hat damals niemand angesehen.
    """
    from src.states.menu.settings_page import SettingsPage

    spielhilfe.sprache_setzen(monkeypatch, sprache)
    seite = SettingsPage()
    if kategorie >= len(seite.categories):
        pytest.skip(f"nur {len(seite.categories)} Reiter in dieser Fassung")

    mit = spielhilfe.gezeichnete_texte(monkeypatch)
    schirm = pygame.Surface(_BILD)
    schirm.fill((0, 0, 0))
    seite.enter(_ShellAttrappe())
    seite.cat = kategorie
    seite.draw(schirm, _INHALT)

    reiter = seite.categories[kategorie]
    schlimm = _echte_ueberlagerungen(mit)
    assert schlimm == [], \
        f"Einstellungen/{reiter} ({sprache}):\n" + "\n".join(schlimm)
    raus = [z.text for z in mit.zuege
            if z.tinte.left < 0 or z.tinte.right > _BILD[0]]
    assert raus == [], f"Einstellungen/{reiter} ({sprache}): {raus}"


# ---------------------------------------------------------------------------
# Was die Regel nicht sieht, aber genauso stoert
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(_seiten()))
def test_jede_seite_zeichnet_in_beiden_sprachen_ohne_absturz(name, monkeypatch):
    """Der billigste Test von allen, und er haette zwei Abstuerze gefunden.

    Am 05.08.2026 stuerzten Streckeneditor und Rennpause ab, weil eine
    querschnittliche Aenderung je eine Stelle nicht erreicht hatte. Ein
    Importtest findet so etwas nicht — nur das Zeichnen selbst.
    """
    for sprache in ("de", "en"):
        spielhilfe.sprache_setzen(monkeypatch, sprache)
        seite = _seiten()[name]()
        _zeichnen(seite)
        seite.update(1 / 60)


@pytest.mark.parametrize("name", sorted(_seiten()))
def test_die_bedienelemente_jeder_seite_liegen_im_bild(name):
    """Ein Knopf ausserhalb des Bildes ist nicht anklickbar.

    Anders als beim Text zaehlt hier auch senkrecht: ein Widget wird nicht
    beschnitten, es wird gezeichnet oder nicht — und liegt es teilweise
    draussen, ist der Teil unerreichbar.
    """
    seite = _seiten()[name]()
    _zeichnen(seite)

    bild = pygame.Rect((0, 0), _BILD)
    draussen = [(art, tuple(r)) for art, r in spielhilfe.widget_rechtecke(seite)
                if r.width and r.height and not bild.contains(r)]
    assert draussen == [], f"{name}: {draussen}"
