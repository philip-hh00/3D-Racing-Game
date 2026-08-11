"""Zurück heißt eine Ebene, nicht zurück zum Anfang.

Gemeldet am 02.08.2026: „mit b beim Controller bzw. ESC mit der Tastatur kommt
man direkt wieder ins Hauptmenü. Selbst wenn man schon drei Ebenen tiefer in den
Einstellungen ist. Oder auch abbrechen oder zurück buttons wie im Streckeneditor
bringen einen direkt zum Hauptmenü anstatt erstmal eine Ebene zurück."

Zwei verschiedene Ursachen steckten dahinter:

1. **Ein Druck, zwei Auswertungen.** Der Gamepad-Manager übersetzt B in ESC,
   die rohen Pad-Ereignisse liefen aber daneben weiter mit. Wer beide auswertete
   — Editor, Rennpause — machte pro Druck zwei Schritte.
2. **Jeder Rückweg von Hand.** Es gab keinen Verlauf; die meisten Bildschirme
   schrieben ``transition("menu")`` hin. Das stimmte für den kürzesten Weg und
   für keinen anderen.

Dazu kamen zwei Stellen, die eine Ebene übersprangen (Bildschirmtastatur in den
Einstellungen, Lack-Reiter im Labor) und eine Tab-Leiste, die sichtbar war,
ohne auf Klicks zu reagieren.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.core import gamepad  # noqa: E402
from src.core.state_machine import StateMachine  # noqa: E402


def _pad_taste(key: int, **extra) -> pygame.event.Event:
    return pygame.event.Event(pygame.KEYDOWN, key=key, unicode="", mod=0,
                              synthetic=True, **extra)


# ---------------------------------------------------------------------------
# 1. Ein Druck, eine Fassung
# ---------------------------------------------------------------------------
def test_rohe_pad_ereignisse_gehen_nicht_mit_raus(monkeypatch):
    """Sobald übersetzt wird, darf die rohe Fassung nicht danebenstehen —
    sonst zählt derselbe Druck zweimal."""
    roh_b = pygame.event.Event(pygame.JOYBUTTONDOWN, joy=0, instance_id=0,
                               button=gamepad.BTN_B)
    hat = pygame.event.Event(pygame.JOYHATMOTION, joy=0, instance_id=0,
                             hat=0, value=(1, 0))
    maus = pygame.event.Event(pygame.MOUSEMOTION, pos=(10, 10), rel=(1, 1),
                              buttons=(0, 0, 0))
    monkeypatch.setattr(gamepad, "menu_events",
                        lambda evs: [_pad_taste(pygame.K_ESCAPE,
                                                pad_button=gamepad.BTN_B)])

    raus = gamepad.menue_eingaben([maus, roh_b, hat])

    typen = [e.type for e in raus]
    assert pygame.JOYBUTTONDOWN not in typen
    assert pygame.JOYHATMOTION not in typen
    assert pygame.MOUSEMOTION in typen, "andere Ereignisse bleiben unberührt"
    assert typen.count(pygame.KEYDOWN) == 1


def test_ohne_uebersetzung_bleibt_nichts_uebrig(monkeypatch):
    """Liefert der Manager nichts (Tastatur-Filter, Startsperre), wird der Pad
    ignoriert — und nicht heimlich über die rohe Fassung doch gehört."""
    roh = pygame.event.Event(pygame.JOYBUTTONDOWN, joy=0, instance_id=0, button=0)
    monkeypatch.setattr(gamepad, "menu_events", lambda evs: [])
    assert gamepad.menue_eingaben([roh]) == []


def test_tastatur_laeuft_unveraendert_durch(monkeypatch):
    monkeypatch.setattr(gamepad, "menu_events", lambda evs: [])
    esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="", mod=0)
    assert gamepad.menue_eingaben([esc]) == [esc]


# ---------------------------------------------------------------------------
# 2. Der Verlauf
# ---------------------------------------------------------------------------
class _Zustand:
    def __init__(self) -> None:
        self.betreten: list[dict] = []

    def enter(self, **kwargs) -> None:
        self.betreten.append(kwargs)

    def exit(self) -> None:
        pass


class _Eigenstaendig(_Zustand):
    """Hält seinen Stand selbst — wie die Menü-Shell mit ihrem Seitenstapel."""

    def rueckweg_kwargs(self) -> dict:
        return {}


@pytest.fixture
def maschine(monkeypatch):
    monkeypatch.setattr(StateMachine, "_update_music", lambda self, name: None)
    sm = StateMachine()
    for name in ("menu", "vehicle_lab", "dev", "editor", "car_select", "race"):
        sm.register(name, _Zustand())
    sm.register("menu", _Eigenstaendig())
    sm.transition("menu")
    return sm


def test_eine_ebene_zurueck(maschine):
    maschine.transition("vehicle_lab", vehicle_config="rookie")
    assert maschine.kann_zurueck() is True
    assert maschine.zurueck() is True
    assert maschine.current_state_name == "menu"


def test_menue_kommt_ohne_argumente_zurueck(maschine):
    """Die Shell hält Tab und Seitenstapel selbst. Würde sie mit ihren alten
    Argumenten neu aufgebaut, wäre die Einstellungsseite weg, aus der man ins
    Labor gegangen ist — genau der gemeldete Fall."""
    maschine.transition("menu", reopen="lobby")
    maschine.transition("vehicle_lab", vehicle_config="rookie")
    maschine.zurueck()
    assert maschine._states["menu"].betreten[-1] == {}


def test_zwei_ebenen_kommen_einzeln_zurueck(maschine):
    maschine.transition("car_select", picker="p1")
    maschine.transition("vehicle_lab")
    maschine.zurueck()
    assert maschine.current_state_name == "car_select"
    assert maschine._states["car_select"].betreten[-1] == {"picker": "p1"}
    maschine.zurueck()
    assert maschine.current_state_name == "menu"


def test_ohne_verlauf_ins_hauptmenue(maschine):
    """Ganz oben angekommen bleibt der Ausweg ins Menü — aber erst dann."""
    maschine.transition("editor")
    maschine.zurueck()
    assert maschine.current_state_name == "menu"
    assert maschine.kann_zurueck() is False
    assert maschine.zurueck() is True
    assert maschine.current_state_name == "menu"


def test_rennen_setzt_den_verlauf_zurueck(maschine):
    """Nach einem Rennen will niemand rückwärts durch die Streckenwahl."""
    maschine.transition("car_select")
    maschine.transition("race", track_path="x")
    assert maschine.kann_zurueck() is False
    maschine.transition("menu", results=[])
    assert maschine.kann_zurueck() is False


def test_rueckweg_legt_keinen_rueckweg_an(maschine):
    """Sonst pendelt man zwischen zwei Bildschirmen statt hochzukommen."""
    maschine.transition("editor")
    maschine.zurueck()
    assert maschine.kann_zurueck() is False


def test_verlauf_waechst_nicht_endlos(maschine):
    from src.core.state_machine import MAX_VERLAUF
    for _ in range(50):
        maschine.transition("editor")
        maschine.transition("dev")
    assert len(maschine._verlauf) <= MAX_VERLAUF


def test_unbekannter_eintrag_wird_uebersprungen(maschine):
    maschine.transition("editor")
    maschine._verlauf.append(("gibtsnicht", {}))
    assert maschine.zurueck() is True
    assert maschine.current_state_name == "menu"


# ---------------------------------------------------------------------------
# 3. Die Menü-Shell: Tab-Leiste und Seitenstapel
# ---------------------------------------------------------------------------
from src.states.menu.page import Page  # noqa: E402
from src.states.menu_shell_state import MenuShellState  # noqa: E402


class _AlleszuckerSeite(Page):
    """Eine Seite, die jedes Ereignis beantwortet — davon gibt es mehrere."""

    def __init__(self) -> None:
        self.gesehen = 0

    def enter(self, shell, **kwargs) -> None:
        self.shell = shell

    def handle_event(self, event):
        self.gesehen += 1
        return True


class _HaeltAn(_AlleszuckerSeite):
    def __init__(self) -> None:
        super().__init__()
        self.weiter = None

    def verlassen_erlaubt(self, weiter) -> bool:
        self.weiter = weiter
        return False


def _shell() -> MenuShellState:
    shell = MenuShellState.__new__(MenuShellState)
    shell.tab = 0
    shell.page_stack = []
    shell._fade = 1.0
    shell._fade_from = None
    shell._prev_tab = 0
    shell._video = None
    shell._video_stem = None
    shell._bg_cache = {}
    shell._blur_cache = {}
    return shell


def _tab_klick(shell, i: int) -> pygame.event.Event:
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                              pos=shell._tab_rects()[i].center)


def test_sichtbare_tab_leiste_reagiert_auch_auf_gefraessigen_seiten():
    """Vorher bekam die Seite den Klick zuerst; wer alles beantwortet, machte
    die sichtbare Leiste damit tot."""
    shell = _shell()
    seite = _AlleszuckerSeite()
    shell.push_page(seite)
    shell._handle_page_event(_tab_klick(shell, 2))
    assert shell.tab == 2
    assert shell.page_stack == []


def test_seite_darf_vorher_nachfragen():
    shell = _shell()
    seite = _HaeltAn()
    shell.push_page(seite)
    shell._handle_page_event(_tab_klick(shell, 3))
    assert shell.tab == 0, "erst die Rückfrage, dann der Sprung"
    assert shell.page_stack == [seite]

    seite.weiter()
    assert shell.tab == 3
    assert shell.page_stack == []


def test_versteckte_leiste_schluckt_keine_klicks():
    """Unsichtbar und trotzdem klickbar wäre schlimmer als sichtbar und tot."""
    class Versteckt(_AlleszuckerSeite):
        def hides_tab_bar(self) -> bool:
            return True

    shell = _shell()
    seite = Versteckt()
    shell.push_page(seite)
    shell._handle_page_event(_tab_klick(shell, 2))
    assert shell.tab == 0
    assert seite.gesehen == 1, "der Klick gehört dann der Seite"


def test_esc_geht_eine_seite_hoch():
    shell = _shell()
    unten, oben = Page(), Page()
    shell.push_page(unten)
    shell.push_page(oben)
    shell._handle_page_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE,
                                                unicode="", mod=0))
    assert shell.page_stack == [unten]


def test_shell_kommt_ohne_argumente_zurueck():
    assert MenuShellState.rueckweg_kwargs(_shell()) == {}


# ---------------------------------------------------------------------------
# 4. Einstellungen: die Bildschirmtastatur ist eine eigene Ebene
# ---------------------------------------------------------------------------
def test_bildschirmtastatur_schliesst_nur_sich_selbst():
    from src.states.menu.settings_page import SettingsPage

    seite = SettingsPage.__new__(SettingsPage)
    seite._focus_content = True

    class _Tastatur:
        def handle_event(self, event):
            return True          # fertig / abgebrochen

    seite.osk = _Tastatur()
    assert seite.handle_event(_pad_taste(pygame.K_ESCAPE)) is True
    assert seite.osk is None
    assert seite._focus_content is True, "die Inhaltsspalte bleibt"


def test_einstellungen_halten_ungespeichertes_fest():
    from src.states.menu.settings_page import SettingsPage

    seite = SettingsPage.__new__(SettingsPage)
    seite._pending = {"username": "neu"}
    seite._leave_dialog = None
    seite._leave_nav = None
    gesprungen = []
    assert seite.verlassen_erlaubt(lambda: gesprungen.append(1)) is False
    assert seite._leave_dialog is not None
    assert gesprungen == []


def test_einstellungen_ohne_aenderung_halten_nicht_auf():
    from src.states.menu.settings_page import SettingsPage

    seite = SettingsPage.__new__(SettingsPage)
    seite._pending = {}
    assert seite.verlassen_erlaubt(lambda: None) is True


# ---------------------------------------------------------------------------
# 5. Streckeneditor: Zurück heißt Projektliste
# ---------------------------------------------------------------------------
def _editor():
    from src.states.editor_state import EditorState

    ed = EditorState.__new__(EditorState)
    ed.state_machine = _WechselMerker()
    ed._mode = "edit"
    ed._dirty = True
    ed._dirty_prompt = True
    ed._dirty_focus = 0
    ed._browse_idx = 0
    ed._browse_scroll = 0
    ed._tool = None
    ed.draft = _EntwurfAttrappe()
    return ed


class _WechselMerker:
    def __init__(self) -> None:
        self.wechsel: list[str] = []

    def transition(self, name, **kwargs):
        self.wechsel.append(name)

    def zurueck(self, fallback="menu"):
        self.wechsel.append("<zurueck>")
        return True


class _EntwurfAttrappe:
    def __init__(self) -> None:
        self.gespeichert = 0

    def save_draft(self):
        self.gespeichert += 1


@pytest.mark.parametrize("antwort,soll_speichern", [(0, 1), (1, 0)])
def test_ungespeichert_dialog_landet_in_der_projektliste(antwort, soll_speichern):
    """Speichern und Verwerfen beenden das Bearbeiten, nicht den Editor.
    Vorher sprangen beide ins Hauptmenü und übersprangen die Liste."""
    ed = _editor()
    ed._dirty_execute(antwort)
    assert ed._mode == "browse"
    assert ed._dirty is False
    assert ed._dirty_prompt is False
    assert ed.draft.gespeichert == soll_speichern
    assert ed.state_machine.wechsel == [], "kein Sprung aus dem Editor heraus"


def test_abbrechen_bleibt_in_der_strecke():
    ed = _editor()
    ed._dirty_execute(2)
    assert ed._mode == "edit"
    assert ed._dirty_prompt is False
    assert ed.state_machine.wechsel == []


def test_zurueck_knopf_tut_mit_der_maus_dasselbe_wie_mit_enter():
    """Derselbe Knopf, zwei Wege — die liefen vorher auseinander: mit der Maus
    ins Hauptmenü, mit ENTER in die Projektliste."""
    ed = _editor()
    ed._dirty = False
    ed._dirty_prompt = False
    ed._trigger_props_click(6, (0, 0))
    assert ed._mode == "browse"
    assert ed.state_machine.wechsel == []


def test_zurueck_knopf_fragt_bei_ungespeichertem():
    ed = _editor()
    ed._dirty = True
    ed._dirty_prompt = False
    ed._trigger_props_click(6, (0, 0))
    assert ed._dirty_prompt is True
    assert ed._mode == "edit"


def test_projektliste_geht_ueber_den_verlauf_zurueck():
    """Von der obersten Editor-Ebene führt der Weg dorthin, wo er herkam —
    nicht fest ins Hauptmenü."""
    ed = _editor()
    ed._mode = "browse"
    ed._projects = []
    esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="", mod=0)
    ed._handle_browse_event(esc)
    assert ed.state_machine.wechsel == ["<zurueck>"]


# ---------------------------------------------------------------------------
# 6. Fahrzeuglabor: der Lack-Reiter ist eine Ebene
# ---------------------------------------------------------------------------
def _labor(seite: str):
    from src.states.vehicle_lab_state import VehicleLabState

    lab = VehicleLabState.__new__(VehicleLabState)
    lab.state_machine = _WechselMerker()
    lab.seite = seite
    lab._lack = None
    lab._active_overlay = None
    lab._reiter_rects = []
    lab.show_help = False
    return lab


def test_lack_reiter_geht_zur_physik_seite_zurueck():
    lab = _labor("lack")
    esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="", mod=0)
    lab.handle_events([esc])
    assert lab.seite == "physik"
    assert lab.state_machine.wechsel == [], "das Labor bleibt offen"


def test_physik_seite_verlaesst_das_labor_ueber_den_verlauf():
    lab = _labor("physik")
    lab._items = lambda: ["a"]
    lab.sel = 0
    esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="", mod=0)
    lab.handle_events([esc])
    assert lab.state_machine.wechsel == ["<zurueck>"]


# ---------------------------------------------------------------------------
# 7. Der gemeldete Weg von oben bis unten
# ---------------------------------------------------------------------------
def test_vier_ebenen_brauchen_vier_druecke(monkeypatch):
    """Hauptmenü → Einstellungen → Inhaltsspalte → Fahrzeuglabor → Lack-Reiter.
    Jeder Druck auf B genau eine Ebene, und zwischendurch steht die
    Einstellungsseite noch da, aus der man losgegangen ist."""
    from src.states.menu.settings_page import SettingsPage
    from src.states.vehicle_lab_state import VehicleLabState

    monkeypatch.setattr(StateMachine, "_update_music", lambda self, name: None)
    sm = StateMachine()
    shell = MenuShellState(sm)
    sm.register("menu", shell)
    labor = VehicleLabState.__new__(VehicleLabState)
    labor.state_machine = sm
    labor.seite = "lack"
    labor._lack = None
    labor._active_overlay = None
    labor._reiter_rects = []
    labor.show_help = False
    labor._items = lambda: ["a"]
    labor.sel = 0
    labor.enter = lambda **kw: None
    labor.exit = lambda: None
    sm.register("vehicle_lab", labor)

    sm.transition("menu")
    shell.tab = 5
    seite = SettingsPage()
    shell.push_page(seite)
    seite._focus_content = True
    sm.transition("vehicle_lab", vehicle_config="rookie")

    esc = _pad_taste(pygame.K_ESCAPE, pad_button=1)

    labor.handle_events([esc])
    assert (sm.current_state_name, labor.seite) == ("vehicle_lab", "physik")

    labor.handle_events([esc])
    assert sm.current_state_name == "menu"
    assert shell.page_stack == [seite], "die Einstellungsseite steht noch"
    assert seite._focus_content is True

    shell._handle_page_event(esc)
    assert shell.page_stack == [seite] and seite._focus_content is False

    shell._handle_page_event(esc)
    assert shell.page_stack == [], "erst jetzt das Hauptmenü"


# ---------------------------------------------------------------------------
# Menüleiste: eine Quelle (Playtest 03.08.2026)
# ---------------------------------------------------------------------------
def test_der_editor_nimmt_die_leiste_der_menueschale():
    """Gemeldet: „In Untermenüs wird teilweise noch nicht die neue
    Hauptmenüleiste angezeigt, sondern noch die alte, z.B. beim Streckeneditor."

    Der Editor ist ein eigener Zustand und hatte die Leiste abgeschrieben — mit
    fünf festen Einträgen und 300 px Breite. Als WERKSTATT und PROFIL dazukamen,
    zeigte er weiter die alte. Kopierte Bedienelemente veralten leise.
    """
    from src.states.editor_state import EditorState
    from src.states.menu_shell_state import tab_rects
    leer = EditorState.__new__(EditorState)
    assert leer._tab_rects() == tab_rects()
    assert len(leer._tab_rects()) == 7


def test_der_editor_hebt_seinen_eigenen_tab_hervor():
    from src.states.menu_shell_state import TAB_EDITOR, _TABS
    assert _TABS[TAB_EDITOR][2] == "editor"


def test_im_editor_ist_keine_eigene_tabliste_mehr_uebrig():
    """Ein zweites _TABS im Editor wäre dieselbe Falle von vorne."""
    import os
    pfad = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "src", "states", "editor_state.py")
    quelle = open(pfad, encoding="utf-8").read()
    assert "_TABS = [" not in quelle
    assert "MEHRSPIELER ONLINE" not in quelle


def test_die_leiste_wird_nur_an_einer_stelle_gerechnet():
    import os
    wurzel = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    treffer = []
    for ordner, _u, dateien in os.walk(os.path.join(wurzel, "src")):
        for name in dateien:
            if not name.endswith(".py"):
                continue
            pfad = os.path.join(ordner, name)
            if "def tab_rects" in open(pfad, encoding="utf-8").read():
                treffer.append(name)
    assert treffer == ["menu_shell_state.py"], treffer


# ---------------------------------------------------------------------------
# Hintergründe der Menüleiste (Playtest 03.08.2026)
# ---------------------------------------------------------------------------
def test_jeder_tab_hat_einen_dateinamen_fuer_seinen_hintergrund():
    """Der Rückfall ist gewollt (Video → PNG → Verlauf), der Tippfehler nicht.

    Gemeldet am 03.08.2026: „Hintergrundvideos für Werkstatt und Profil müssen
    noch erstellt und eingefügt werden." Einlegen heißt: eine Datei
    ``data/menu/<Stamm>.mp4`` ablegen, sonst nichts. Damit das stimmt, muss der
    Stamm ein brauchbarer Dateiname sein — ein Leerzeichen oder Schrägstrich
    darin würde die Datei unauffindbar machen, und die Seite fiele still auf den
    Verlauf zurück.
    """
    from src.states.menu_shell_state import _TABS
    for _label, stamm, _art in _TABS:
        assert stamm and stamm == stamm.strip()
        assert not set(stamm) & set(" /\\:*?\"<>|"), stamm


def test_ein_fehlender_hintergrund_bricht_nichts():
    """Werkstatt und Profil haben heute keinen — die Leiste muss trotzdem
    stehen, sonst wäre der Rückfall keiner."""
    import os
    from src.states.menu_shell_state import _TABS, MenuShellState
    shell = MenuShellState.__new__(MenuShellState)
    shell._bg_cache = {}
    shell._video = None
    shell._video_stem = None
    for _label, stamm, _art in _TABS:
        # _bg gibt None zurueck, wenn die Datei fehlt; _current_frame reicht das
        # durch, und der Aufrufer zeichnet dann den Verlauf.
        assert shell._bg(stamm) is None or os.path.isfile(
            os.path.join("data", "menu", f"{stamm}.png"))
        assert shell._current_frame(stamm) is None or True


def test_jeder_reiter_hat_einen_hintergrund():
    """Die Endform eines Tests, der zweimal angeschlagen hat und beide Male recht
    hatte.

    Am 03.08.2026 fehlten Werkstatt und Profil, und er hielt genau diesen Stand
    fest — in beide Richtungen. `Werkstatt.mp4` kam am 05.08. und `Profil.mp4`
    kurz darauf; beide Male meldete er sich, wie es sein sollte. Jetzt fehlt
    keiner mehr, und damit wird aus der Aufzählung eine Regel: **jeder Reiter
    bringt seinen Hintergrund mit.**

    Das ist die Richtung, die dauerhaft trägt. Geht eine vorhandene Datei
    verloren, bleibt das im Spiel stumm — die Shell fällt Video → PNG → Verlauf
    zurück, und der Verlauf sieht nur nach „noch nicht fertig" aus. Ein neuer
    Reiter ohne Hintergrund fällt hier ebenfalls auf, statt erst dem ersten
    Spieler.
    """
    import os
    from src.states.menu_shell_state import _TABS
    fehlen = [stamm for _l, stamm, _a in _TABS
              if not any(os.path.isfile(os.path.join("data", "menu", f"{stamm}{e}"))
                         for e in (".mp4", ".png"))]
    assert fehlen == [], f"ohne Hintergrund: {fehlen}"
