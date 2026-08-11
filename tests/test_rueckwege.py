"""Der Rückweg: ein Knopf auf jedem Bildschirm, und immer eine Ebene (04.08.2026).

Gemeldet: „In den Menüs Lobbys usw. gibt es noch teilweise keine zurück Buttons
und der User ist auf ESC angewiesen (das führt aber manchmal auch direkt zum
Hauptmenü) schöner sind zurück Buttons die immer zur letzten geöffneten Seite
führen."

Zwei Aussagen, zwei Prüfungen.

**Ein Knopf, überall.** Er steht als ``ZurueckKnopf`` an einer Stelle im Code und
auf jedem Bildschirm links. Wer ihn selbst hinstellt, stellt ihn anders hin.

Seit dem 05.08.2026 gibt es dabei **zwei** feste Plätze statt einem: oben links,
wo die Seite die Zeile frei hat (Werkstatt, Profil, die Auswahlbildschirme), und
unten links in den Lobbys und Untermenüs — dort füllen Stepper und Listen die
obere Hälfte. Gemeldet als „In den anderen Untermenüs und Lobbys würde ich
diesen ehr nach ganz unten Links setzen da stört ehr in allen fällen nicht."
Zwei Plätze nach einer Regel sind noch keine Wanderung; geprüft wird deshalb,
dass es bei zweien bleibt.

**Immer eine Ebene.** Der Knopf führt genau dorthin, wohin auch ESC führt. Das
ist keine Bequemlichkeit: die Werkstatt hatte schon einmal zwei Wege für dieselbe
Absicht, und sie führten verschieden weit (gemeldet 03.08.2026). Geprüft wird
deshalb paarweise — Taste und Knopf müssen dasselbe tun.

Der eine Fall, in dem ESC wirklich ins Hauptmenü sprang: ein abgebrochener Grand
Prix in der Streckenauswahl. ``transition("menu")`` statt einer Ebene hoch.
"""
from __future__ import annotations

import ast
import os
import sys
import types

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.core import profile, race_setup  # noqa: E402
from src.core.settings import SCREEN_HEIGHT, SCREEN_WIDTH  # noqa: E402
from src.states.menu_shell_state import TAB_H  # noqa: E402
from src.ui.widgets import ZurueckKnopf  # noqa: E402

INHALT = pygame.Rect(0, TAB_H, SCREEN_WIDTH, SCREEN_HEIGHT - TAB_H)

#: Seiten mit einem **eigenen**, benannten Ausgang. Dort wäre „‹ Zurück" nicht
#: nur doppelt, sondern unehrlich: eine Serie zu beenden ist keine Ebene hoch,
#: und aus der Ergebnisliste führen drei verschiedene Wege weiter.
EIGENER_AUSGANG = {
    "results_page": ("Zurück zur Lobby", "Hauptmenü"),
    "gp_overview_page": ("Grand Prix beenden",),
}


@pytest.fixture(autouse=True)
def spielstand(monkeypatch):
    p = profile.Profile(username="Philip")
    p.save = lambda: None
    p.statistik = {}
    monkeypatch.setattr(profile, "_current", p, raising=False)
    monkeypatch.setattr(profile, "current", lambda: p)
    return p


class _Schale:
    """Die Menüschale, soweit eine Seite sie anfasst."""

    def __init__(self) -> None:
        self.gegangen = 0
        self.gepoppt = 0
        self.state_machine = types.SimpleNamespace(
            transition=lambda *a, **k: None, zurueck=lambda *a, **k: None)
        self.page_stack: list = []

    def zurueck_gehen(self) -> None:
        self.gegangen += 1
        seite = self.page_stack[-1] if self.page_stack else None
        eigen = getattr(seite, "zurueck", None)
        if callable(eigen):
            eigen()
            return
        self.pop_page()

    def pop_page(self) -> None:
        self.gepoppt += 1

    def push_page(self, page) -> None:
        self.page_stack.append(page)


def _klick(pos):
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos)


def _esc():
    return pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="", mod=0)


def _seiten():
    """Die Menüseiten, die eine Ebene für sich sind — jede frisch aufgebaut."""
    from src.states.menu.coming_soon_page import ComingSoonPage
    from src.states.menu.lobby_page import LobbyPage
    from src.states.menu.mp_lobby_page import MPLobbyPage
    from src.states.menu.mp_name_page import MPNamePage
    from src.states.menu.profil_page import ProfilPage
    from src.states.menu.settings_page import SettingsPage
    from src.states.menu.werkstatt_page import WerkstattPage
    return {
        "ComingSoon": ComingSoonPage("TEST"),
        "Lobby": LobbyPage(),
        "MP-Name": MPNamePage(),
        "MP-Lobby": MPLobbyPage(),
        "Profil": ProfilPage(),
        "Einstellungen": SettingsPage(),
        "Werkstatt": WerkstattPage(),
    }


def _aufgebaut(seite):
    schale = _Schale()
    seite.enter(schale)
    schale.push_page(seite)
    schirm = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    seite.draw(schirm, INHALT)
    return seite, schale, schirm


# ---------------------------------------------------------------------------
# Ein Knopf, überall
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(_seiten()))
def test_jede_menueseite_hat_einen_zurueck_knopf(name):
    seite, _schale, _schirm = _aufgebaut(_seiten()[name])
    knopf = seite.zurueck_knopf()
    assert knopf.rect.width > 0 and knopf.rect.height > 0
    assert INHALT.contains(knopf.rect), f"{name}: der Knopf liegt außerhalb"


#: Seiten, die ihren Knopf seit dem 05.08.2026 unten links tragen. Gemeldet:
#: „In Workshop und Profil ist die Plazierung passend … In den anderen
#: Untermenüs und Lobbys würde ich diesen ehr nach ganz unten Links setzen."
#: Oben ist dort kein Platz — Stepper und Listen füllen die obere Bildhälfte.
UNTEN_LINKS = {"Einstellungen", "Lobby", "MP-Lobby", "MP-Name"}


@pytest.mark.parametrize("name", sorted(_seiten()))
def test_der_knopf_steht_immer_links_und_hat_immer_dieselbe_groesse(name):
    """Links bleibt links. Was sich unterscheidet, ist nur oben gegen unten —
    und das folgt einer Regel, nicht dem Zufall."""
    seite, _schale, _schirm = _aufgebaut(_seiten()[name])
    r = seite.zurueck_knopf().rect
    assert r.x - INHALT.x <= 80, f"{name}: {r.x - INHALT.x} px von links"
    assert (r.width, r.height) == (ZurueckKnopf.BREITE, ZurueckKnopf.HOEHE)


@pytest.mark.parametrize("name", sorted(_seiten()))
def test_der_knopf_sitzt_da_wo_seine_seite_ihn_hingehoert(name):
    """Zwei Familien, je eine feste Stelle — keine dritte.

    Ein Knopf, der von Seite zu Seite wandert, ist auf jeder neu zu suchen.
    Zwei klar getrennte Plätze sind das nicht: oben, wo die Seite die Zeile frei
    hat (Werkstatt, Profil), sonst unten aus dem Weg.
    """
    seite, _schale, _schirm = _aufgebaut(_seiten()[name])
    r = seite.zurueck_knopf().rect
    if name in UNTEN_LINKS:
        assert INHALT.bottom - r.bottom <= 48, \
            f"{name}: {INHALT.bottom - r.bottom} px von unten"
    else:
        assert r.y - INHALT.y <= 24, f"{name}: {r.y - INHALT.y} px von oben"


@pytest.mark.parametrize("name", sorted(UNTEN_LINKS))
def test_unten_links_kommt_den_bedienhinweisen_nicht_ins_gehege(name):
    """Die Hinweiszeile steht mittig; der Knopf links darf sie nicht berühren."""
    from src.core.settings import SCREEN_WIDTH as _B
    seite, _schale, _schirm = _aufgebaut(_seiten()[name])
    assert seite.zurueck_knopf().rect.right < _B // 2 - 200


@pytest.mark.parametrize("name", sorted(_seiten()))
def test_ein_klick_auf_den_knopf_geht_eine_ebene_hoch(name):
    seite, schale, _schirm = _aufgebaut(_seiten()[name])
    verbraucht = seite.handle_event(_klick(seite.zurueck_knopf().rect.center))
    assert verbraucht, f"{name}: der Klick wurde nicht verarbeitet"
    # Entweder über die Schale (``zurueck_gehen``) oder von der Seite selbst —
    # die Werkstatt kennt ihren Kurzweg zurück in die Fahrzeugauswahl. Beide
    # Wege enden eine Ebene höher, und genau das ist die Aussage.
    assert schale.gegangen + schale.gepoppt >= 1, f"{name}: kein Rückweg gegangen"


@pytest.mark.parametrize("name", sorted(_seiten()))
def test_ein_klick_daneben_geht_nirgendwohin(name):
    """Sonst wäre der Knopf eine Falle statt einer Hilfe."""
    seite, schale, _schirm = _aufgebaut(_seiten()[name])
    r = seite.zurueck_knopf().rect
    seite.handle_event(_klick((r.right + 60, r.centery)))
    assert schale.gegangen + schale.gepoppt == 0


@pytest.mark.parametrize("name", sorted(_seiten()))
def test_der_knopf_ist_auch_zu_sehen(name):
    """Ein Knopf, der nicht gezeichnet wird, ist keiner — auch wenn er trifft."""
    seite, _schale, schirm = _aufgebaut(_seiten()[name])
    r = seite.zurueck_knopf().rect
    # Eine Vergleichsstelle neben dem Knopf, die sicher noch im Bild liegt —
    # seit er auch unten sitzen kann, ist „200 px darunter" nicht mehr sicher.
    hintergrund = schirm.get_at((min(r.right + 40, schirm.get_width() - 1),
                                 r.centery))
    anders = sum(1 for x in range(r.x, r.right, 4) for y in range(r.y, r.bottom, 4)
                 if schirm.get_at((x, y)) != hintergrund)
    gesamt = len(range(r.x, r.right, 4)) * len(range(r.y, r.bottom, 4))
    assert anders > gesamt // 3, f"{name}: da ist nichts gezeichnet"


def test_der_knopf_wird_nicht_von_jeder_seite_neu_erfunden():
    """Keine **Menüseite** baut sich ihr eigenes „‹ Zurück".

    Geprüft wird genau der Rückweg eines Bildschirms — der, der überall an
    derselben Stelle stehen soll. Nicht gemeint sind Knöpfe, die in einer Reihe
    mit anderen stehen und deren Breite tragen: die Serverauswahl und die
    Beitrittsmaske haben „‹ Zurück" als Feld ihres Formulars, das Klanglabor als
    vierten in einer Knopfreihe, die Rennpause als Fuß einer Unteransicht. Die
    sind Teil ihrer Reihe, nicht Rückweg des Bildschirms — und eine feste Größe
    würde sie aus ihr herausbrechen.
    """
    ordner = os.path.join(_ROOT, "src", "states", "menu")
    verdaechtig = []
    for name in sorted(os.listdir(ordner)):
        if not name.endswith(".py") or name == "online_lobby_page.py":
            continue
        text = open(os.path.join(ordner, name), encoding="utf-8").read()
        for k in ast.walk(ast.parse(text)):
            if (isinstance(k, ast.Constant) and isinstance(k.value, str)
                    and k.value.strip() in ("‹ Zurück", "‹  Zurück")):
                verdaechtig.append(f"{name}:{k.lineno}")
    assert not verdaechtig, ("eigene Zurück-Beschriftung statt ZurueckKnopf: "
                            + ", ".join(verdaechtig))


def test_die_auswahlbildschirme_benutzen_denselben_knopf():
    """Fahrzeug- und Streckenwahl sind eigene Zustände, keine Menüseiten — der
    Knopf muss trotzdem derselbe sein."""
    from src.states.car_select_state import CarSelectState
    from src.states.track_select_state import TrackSelectState
    from src.states.editor_state import EditorState
    for klasse in (CarSelectState, TrackSelectState, EditorState):
        sm = types.SimpleNamespace(transition=lambda *a, **k: None,
                                   zurueck=lambda *a, **k: None)
        knopf = klasse(sm)._zurueck_knopf
        assert isinstance(knopf, ZurueckKnopf), klasse.__name__


def test_keine_menueseite_bleibt_ohne_ausgang():
    """Die Regel für jede neue Seite: entweder der Standardknopf oder ein
    eigener, benannter Ausgang — aber nicht nur ESC."""
    ordner = os.path.join(_ROOT, "src", "states", "menu")
    ohne = []
    for name in sorted(os.listdir(ordner)):
        if not name.endswith(".py") or name in ("__init__.py", "page.py"):
            continue
        text = open(os.path.join(ordner, name), encoding="utf-8").read()
        # Nur Module, die wirklich eine Seite enthalten. ``gp_overview.py`` ist
        # die gemeinsame Streckenübersicht, die zwei Seiten benutzen — sie ist
        # keine Ebene und hat deshalb auch keinen Ausgang.
        if not any(isinstance(k, ast.ClassDef)
                   and any(getattr(b, "id", "") == "Page" for b in k.bases)
                   for k in ast.walk(ast.parse(text))):
            continue
        if "zurueck_zeichnen" in text:
            continue
        stamm = name[:-3]
        eigene = EIGENER_AUSGANG.get(stamm)
        if eigene and all(w in text for w in eigene):
            continue
        ohne.append(name)
    assert not ohne, f"Seiten ohne sichtbaren Ausgang: {ohne}"


# ---------------------------------------------------------------------------
# Immer eine Ebene — und Knopf wie Taste
# ---------------------------------------------------------------------------
def test_esc_geht_durch_dieselbe_stelle_wie_der_knopf():
    """Die Schale beantwortet beides mit ``zurueck_gehen``. Stünde in ihrem
    ESC-Zweig weiter ``pop_page``, liefen Taste und Knopf auseinander, sobald eine
    Seite ihren eigenen Rückweg meldet — genau der Fehler der Werkstatt."""
    quelle = open(os.path.join(_ROOT, "src", "states", "menu_shell_state.py"),
                  encoding="utf-8").read()
    block = quelle.split("def _handle_page_event")[1].split("\n    def ")[0]
    esc = block.split("K_ESCAPE")[1]
    assert "zurueck_gehen()" in esc
    assert "pop_page()" not in esc.split("return")[0]


def test_eine_seite_mit_eigenem_rueckweg_wird_gefragt():
    """Die Werkstatt hat einen Kurzweg zurück in die Fahrzeugauswahl und fragt
    vor dem Verwerfen. Die Schale darf ihr nicht dazwischenfahren."""
    from src.states.menu.werkstatt_page import WerkstattPage
    seite = WerkstattPage()
    schale = _Schale()
    seite.enter(schale)
    schale.push_page(seite)
    gerufen = []
    seite.zurueck = lambda: gerufen.append(1)
    schale.zurueck_gehen()
    assert gerufen == [1]
    assert schale.gepoppt == 0


def test_die_schale_faellt_ohne_eigenen_rueckweg_auf_den_stapel_zurueck():
    from src.states.menu_shell_state import MenuShellState
    schale = MenuShellState.__new__(MenuShellState)
    gepoppt = []
    schale.page_stack = [object()]
    schale.pop_page = lambda: gepoppt.append(1)
    schale.zurueck_gehen()
    assert gepoppt == [1]


@pytest.mark.parametrize("modus", ["einzeln", "online", "mp_p1"])
def test_fahrzeugwahl_knopf_und_taste_gehen_denselben_weg(modus):
    from src.states.car_select_state import CarSelectState

    def lauf(wie: str):
        wege = []
        sm = types.SimpleNamespace(
            transition=lambda ziel, **kw: wege.append((ziel, kw)),
            zurueck=lambda *a, **k: wege.append(("zurueck", {})))
        z = CarSelectState(sm)
        z.enter()
        s = race_setup.current()
        s.is_multiplayer = modus.startswith("mp")
        z._online_mode = (modus == "online")
        z.picker = "p2" if modus == "mp_p2" else "p1"
        if wie == "taste":
            z.handle_events([_esc()])
        else:
            z.handle_events([_klick(z._zurueck_knopf.rect.center)])
        return wege

    assert lauf("taste") == lauf("knopf") != []
    race_setup.current().is_multiplayer = False


def test_ein_pad_gefuehrter_spieler_zwei_hoert_bewusst_nicht_auf_die_maus():
    """Spieler 2 wählt am Controller, und dort schluckt der Bildschirm jeden
    Mausklick — sonst griffe ein Zuschauer mit der Maus in seine Wahl. Sein
    Rückweg ist B, das als ESC ankommt; der Knopf ist für die Maus."""
    from src.states.car_select_state import CarSelectState
    wege = []
    sm = types.SimpleNamespace(
        transition=lambda ziel, **kw: wege.append((ziel, kw)),
        zurueck=lambda *a, **k: wege.append(("zurueck", {})))
    z = CarSelectState(sm)
    z.enter()
    s = race_setup.current()
    s.is_multiplayer = True
    s.p2_input = "pad0"
    z.picker = "p2"
    try:
        z.handle_events([_klick(z._zurueck_knopf.rect.center)])
        assert wege == [], "der Klick darf nicht durchgehen"
        z.handle_events([_esc()])
        assert wege == [("car_select", {"picker": "p1"})]
    finally:
        s.is_multiplayer = False


def test_streckenwahl_knopf_und_taste_gehen_denselben_weg():
    from src.states.track_select_state import TrackSelectState

    def lauf(wie: str):
        wege = []
        sm = types.SimpleNamespace(
            transition=lambda ziel, **kw: wege.append((ziel, kw)),
            zurueck=lambda *a, **k: wege.append(("zurueck", {})))
        z = TrackSelectState(sm)
        z.enter()
        if wie == "taste":
            z.handle_events([_esc()])
        else:
            z.handle_events([_klick(z._zurueck_knopf.rect.center)])
        return wege

    assert lauf("taste") == lauf("knopf") != []


def test_ein_abgebrochener_grand_prix_landet_nicht_im_hauptmenue():
    """Der eine Fall, den die Meldung wörtlich beschreibt: „das führt aber
    manchmal auch direkt zum Hauptmenü"."""
    from src.core import grand_prix
    from src.states.track_select_state import TrackSelectState
    wege = []
    sm = types.SimpleNamespace(
        transition=lambda ziel, **kw: wege.append((ziel, kw)),
        zurueck=lambda *a, **k: wege.append(("zurueck", {})))
    z = TrackSelectState(sm)
    z.enter()
    grand_prix.start_series(3, 3)
    try:
        z.handle_events([_esc()])
        assert z._dialog is not None, "erst fragen — der Zwischenstand geht verloren"
        schirm = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        z._dialog.draw(schirm)
        ja = next(r for r, a in z._dialog._rects if a == "ok")
        z.handle_events([_klick(ja.center)])
    finally:
        grand_prix.cancel()
    assert wege == [("zurueck", {})], wege


def test_der_streckeneditor_hat_einen_knopf_in_der_projektliste():
    """Die Projektliste ist eine Menüebene; die Zeichenfläche daneben nicht."""
    from src.states.editor_state import EditorState
    wege = []
    sm = types.SimpleNamespace(transition=lambda ziel, **kw: None,
                              zurueck=lambda *a, **k: wege.append("zurueck"))
    z = EditorState(sm)
    assert z._zurueck_knopf.rect.y >= TAB_H, "unter die Reiterleiste, nicht darüber"
    z._mode = "browse"
    z._handle_browse_event(_klick(z._zurueck_knopf.rect.center))
    assert wege == ["zurueck"]
    z._handle_browse_event(_esc())
    assert wege == ["zurueck", "zurueck"], "Taste und Knopf, derselbe Weg"


def test_die_auswahlbildschirme_zeichnen_ihren_knopf_sichtbar():
    from src.states.car_select_state import CarSelectState
    from src.states.track_select_state import TrackSelectState
    for klasse in (CarSelectState, TrackSelectState):
        sm = types.SimpleNamespace(transition=lambda *a, **k: None,
                                   zurueck=lambda *a, **k: None)
        z = klasse(sm)
        z.enter()
        z.update(0.016)
        schirm = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        z.render(schirm)
        r = z._zurueck_knopf.rect
        rand = schirm.get_at((r.x - 20, r.centery))
        anders = sum(1 for x in range(r.x, r.right, 4)
                       for y in range(r.y, r.bottom, 4)
                     if schirm.get_at((x, y)) != rand)
        assert anders > 60, klasse.__name__


def test_die_onlinelobby_bietet_in_jeder_ebene_einen_ausweg():
    """Aus der Lobby heraus gab es nur ESC — und beim Gastgeber löst das die
    ganze Lobby auf, also wird gefragt."""
    from src.states.menu import online_lobby_page as olp
    for ansicht in (olp._ROLE, olp._LOBBY, olp._GP_OVERVIEW):
        seite = olp.OnlineLobbyPage.__new__(olp.OnlineLobbyPage)
        seite._view = ansicht
        seite.shell = _Schale()
        gefragt = []
        seite._ask_leave_lobby = lambda: gefragt.append("lobby")
        seite._ask_leave_gp = lambda: gefragt.append("gp")
        seite.zurueck()
        if ansicht == olp._LOBBY:
            assert gefragt == ["lobby"]
        elif ansicht == olp._GP_OVERVIEW:
            assert gefragt == ["gp"]
        else:
            assert seite.shell.gepoppt == 1


# ---------------------------------------------------------------------------
# Die Grand-Prix-Übersicht braucht kein zweites „Zurück" (05.08.2026)
# ---------------------------------------------------------------------------

def test_die_gp_uebersicht_traegt_keinen_zurueck_knopf():
    """Gemeldet: „In der Grand Prix Übersicht ist der Back Button unnötig da es
    Leave Grand Prix gibt - kann entfernt werden."

    Beide führten ohnehin auf dieselbe Rückfrage. Der benannte Knopf sagt, was
    passiert — eine Serie zu beenden ist keine Ebene hoch, und „‹ Zurück"
    behauptet genau das.
    """
    from src.states.menu import online_lobby_page as olp
    assert olp._GP_OVERVIEW in olp.OnlineLobbyPage._HAT_EIGENEN_RUECKWEG


def test_die_uebrigen_ebenen_behalten_ihren_knopf():
    """Die Gegenrichtung: nur die Übersicht verliert ihn, nicht die Lobby."""
    from src.states.menu import online_lobby_page as olp
    assert olp._LOBBY not in olp.OnlineLobbyPage._HAT_EIGENEN_RUECKWEG
    assert olp._ROLE not in olp.OnlineLobbyPage._HAT_EIGENEN_RUECKWEG


def test_die_uebersicht_hat_trotzdem_einen_ausweg():
    """Ohne den Knopf muss der benannte Ausgang tatsächlich da sein — sonst
    wäre die Ebene eine Sackgasse."""
    from src.states.menu import online_lobby_page as olp
    seite = olp.OnlineLobbyPage.__new__(olp.OnlineLobbyPage)
    seite._view = olp._GP_OVERVIEW
    seite.shell = _Schale()
    gefragt = []
    seite._ask_leave_gp = lambda: gefragt.append("gp")
    seite.zurueck()
    assert gefragt == ["gp"]
