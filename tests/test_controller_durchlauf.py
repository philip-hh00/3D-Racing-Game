"""Das Menue mit dem Controller ablaufen — ohne Controller.

Der Controller ist ein beworbenes Merkmal („Auch die Menues lassen sich
vollstaendig mit dem Controller bedienen"), und ``src/core/gamepad.py`` war am
07.08.2026 zu **20 %** von Tests erreicht — der schlechteste Wert im ganzen
Spiel. Der Grund liegt auf der Hand: auf dem Bauknecht steckt kein Pad, also
schien es unpruefbar.

Es ist pruefbar. ``GamepadManager`` verlangt von einem Joystick vier Methoden,
kein Geraet — :class:`tests.spielhilfe.PadAttrappe` liefert sie, und die
gesamte Uebersetzung von Pad-Ereignissen in Menuebefehle laeuft danach wie mit
echtem Pad.

Zwei Dinge werden geprueft:

1. **Die Uebersetzung.** D-Pad, Analogstick, Knoepfe, Wiederholung beim Halten,
   Totzone, Geraetetrennung. Das ist die Schicht, die im Spiel zwischen Pad
   und allem anderen sitzt.
2. **Der Weg durch die Seiten.** Auf jeder Menueseite mit dem D-Pad durch alle
   Elemente und auf jedem A druecken. Zusage: kein Absturz, der Fokus geht
   nicht verloren, und er bleibt nicht haengen.

Der zweite Punkt haette den Fund vom 31.07.2026 gehalten — „am Controller kam
der Fokus nie zu einem Nachbarn, man sass fest", weil ein Stepper links/rechts
immer selbst beantwortete.
"""
from __future__ import annotations

import os
import sys
import types

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.core import gamepad  # noqa: E402
from src.ui.focus import FocusGroup  # noqa: E402
from tests import spielhilfe  # noqa: E402
from tests.test_layout_regeln import _ShellAttrappe, _seiten, _zeichnen  # noqa: E402


@pytest.fixture(autouse=True)
def _aufbau_bewahren(monkeypatch):
    """Was dieser Test durchklickt, darf der naechste nicht erben.

    Er drueckt auf jeder Seite A auf jedes Element — darunter Streckenkacheln
    und Fahrzeugkacheln, die den prozessweiten Rennaufbau verstellen. Am
    07.08.2026 fiel dadurch ein Grand-Prix-Test zwei Dateien spaeter um.
    """
    spielhilfe.aufbau_bewahren(monkeypatch)


@pytest.fixture
def pad():
    manager, zurueck = spielhilfe.pad_anmelden()
    yield manager
    zurueck()


# ---------------------------------------------------------------------------
# 1. Die Uebersetzung
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("taste,erwartet", [
    (gamepad.BTN_DPAD_UP, pygame.K_UP),
    (gamepad.BTN_DPAD_DOWN, pygame.K_DOWN),
    (gamepad.BTN_DPAD_LEFT, pygame.K_LEFT),
    (gamepad.BTN_DPAD_RIGHT, pygame.K_RIGHT),
    (gamepad.BTN_A, pygame.K_RETURN),
    (gamepad.BTN_B, pygame.K_ESCAPE),
])
def test_jede_taste_wird_in_ihren_menuebefehl_uebersetzt(pad, taste, erwartet):
    assert erwartet in spielhilfe.pad_tasten(pad, taste), \
        f"Taste {taste} ergab {spielhilfe.pad_tasten(pad, taste)}"


def test_uebersetzte_ereignisse_sind_als_solche_erkennbar(pad):
    """``synthetic=True`` ist keine Zierde.

    Daran unterscheidet die Fokusgruppe Controller von Tastatur: am Controller
    ist ein Stepper geschlossen und wird mit A geoeffnet, an der Tastatur nicht.
    Faellt die Kennzeichnung weg, sitzt der Controller wieder fest (31.07.2026).
    """
    for e in spielhilfe.pad_druck(pad, gamepad.BTN_DPAD_DOWN):
        assert getattr(e, "synthetic", False) is True, e


def test_rohe_pad_ereignisse_verlassen_die_uebersetzung_nicht(pad):
    """Ein Druck, eine Fassung.

    Gingen beide durch, machte ein einziges B zwei Schritte zurueck — genau der
    Fund vom 02.08.2026.
    """
    roh = pygame.event.Event(pygame.JOYBUTTONDOWN, joy=0,
                             button=gamepad.BTN_B, instance_id=0)
    raus = gamepad.menue_eingaben([roh])
    assert not any(e.type in gamepad.ROH_TYPEN for e in raus), raus


def test_ohne_pad_kommt_nichts_heraus():
    """Kein angemeldetes Geraet, keine Uebersetzung — auch nicht versehentlich."""
    gamepad.init()
    m = gamepad._gamepad_manager
    vorher = list(m._joysticks)
    m._joysticks = []
    try:
        assert spielhilfe.pad_tasten(m, gamepad.BTN_A) == []
    finally:
        m._joysticks = vorher


def test_die_tastatur_als_geraet_schaltet_das_pad_stumm(pad):
    """Im lokalen Mehrspieler bekommt jeder Spieler sein Geraet.

    Steht der Filter auf „keyboard", darf das Pad des anderen Spielers nicht
    zusaetzlich im Menue mitnavigieren.
    """
    pad.set_device_filter("keyboard")
    assert spielhilfe.pad_tasten(pad, gamepad.BTN_DPAD_DOWN) == []


def test_ein_fremdes_pad_wird_nicht_beachtet():
    """Filter auf pad0 heisst pad0 — nicht „irgendein Pad"."""
    manager, zurueck = spielhilfe.pad_anmelden(anzahl=2)
    try:
        manager.set_device_filter("pad0")
        assert spielhilfe.pad_tasten(manager, gamepad.BTN_DPAD_DOWN, iid=0)
        assert spielhilfe.pad_tasten(manager, gamepad.BTN_DPAD_DOWN, iid=1) == []
    finally:
        zurueck()


def test_der_analogstick_loest_genau_einmal_aus(pad):
    """Sonst huepft das Menue, solange der Stick gehalten wird.

    Ausgeloest wird beim Ueberschreiten der Totzone; der naechste Befehl kommt
    erst, wenn der Stick zurueck in die Ruhezone war.
    """
    def stick(wert: float):
        e = pygame.event.Event(pygame.JOYAXISMOTION, joy=0,
                               axis=gamepad.AXIS_LY, value=wert, instance_id=0)
        return [x.key for x in pad.menu_events([e]) if x.type == pygame.KEYDOWN]

    assert stick(0.9) == [pygame.K_DOWN], "der erste Ausschlag muss ausloesen"
    assert stick(0.9) == [], "gehalten darf er nicht sofort nachlegen"
    stick(0.0)
    assert stick(0.9) == [pygame.K_DOWN], "nach der Rueckkehr wieder"


def test_ein_kleiner_ausschlag_bleibt_folgenlos(pad):
    """Die Totzone. Ein ruhender Stick liegt nie exakt auf null."""
    e = pygame.event.Event(pygame.JOYAXISMOTION, joy=0, axis=gamepad.AXIS_LY,
                           value=0.1, instance_id=0)
    assert [x for x in pad.menu_events([e]) if x.type == pygame.KEYDOWN] == []


def test_das_dpad_hat_vorrang_vor_dem_stick(pad):
    """Beide zugleich wuerden zwei Schritte machen.

    Ein Daumen auf dem Stick und ein Finger auf dem D-Pad ist keine Seltenheit;
    das D-Pad ist digital und gewinnt.
    """
    dpad = pygame.event.Event(pygame.JOYBUTTONDOWN, joy=0,
                              button=gamepad.BTN_DPAD_DOWN, instance_id=0)
    stick = pygame.event.Event(pygame.JOYAXISMOTION, joy=0,
                               axis=gamepad.AXIS_LY, value=0.9, instance_id=0)
    tasten = [x.key for x in pad.menu_events([dpad, stick])
              if x.type == pygame.KEYDOWN]
    assert tasten == [pygame.K_DOWN], tasten


# ---------------------------------------------------------------------------
# 2. Der Weg durch die Seiten
# ---------------------------------------------------------------------------
#
# Gefahren wird durch die **echte** Menueschale und nicht direkt in die Seite.
# Das ist keine Genauigkeitsfrage, sondern die einzige richtige Ebene: ESC und
# Controller-B beantwortet ``MenuShellState._handle_page_event``, nicht die
# Seite — die gibt nur zurueck, ob sie das Ereignis verbraucht hat. Der erste
# Anlauf am 07.08.2026 schickte die Ereignisse an die Seite und meldete
# neunmal „B fuehrt nicht zurueck", wo in Wahrheit der Test an der falschen
# Stelle horchte.


class _ZustandsAttrappe:
    """Eine Zustandsmaschine, die Wechsel merkt statt sie zu gehen.

    Nachgebaut nach ``src/core/state_machine.StateMachine`` und nicht nach dem,
    was gerade gebraucht schien: eine luekenhafte Attrappe meldet Fehler, die
    dem Test gehoeren und nicht dem Spiel. Genau das ist am 07.08.2026 passiert
    — der Affentest brach im Streckeneditor mit „hat kein Attribut zurueck" ab,
    und das fehlte hier, nicht dort.
    """

    def __init__(self) -> None:
        self.wechsel: list = []
        self.zurueck_zaehler = 0
        self.stapel: list[str] = []

    def transition(self, *a, **k) -> None:
        self.wechsel.append((a, k))

    def kann_zurueck(self) -> bool:
        return True

    def zurueck(self, fallback: str | None = "menu") -> bool:
        self.zurueck_zaehler += 1
        self.wechsel.append(((fallback,), {"_zurueck": True}))
        return True

    def push(self, name: str, **kwargs) -> None:
        self.stapel.append(name)
        self.wechsel.append(((name,), kwargs))

    def pop(self) -> None:
        if self.stapel:
            self.stapel.pop()

    def register(self, name: str, state) -> None:
        pass

    def verlauf_leeren(self) -> None:
        pass

    @property
    def current(self):
        return None

    def current_state_name(self) -> str | None:
        return None


def _gruppen(seite) -> list[FocusGroup]:
    """Alle Fokusgruppen einer Seite finden.

    Ueber die Attribute gesucht statt aus einer Liste gelesen: die Seiten
    nennen ihre Gruppen verschieden (``_gruppe``, ``_content_group``,
    ``_host_group``, ``_join_group``, ...), und eine Namensliste zu pflegen
    hiesse, dass eine neue Seite durchs Raster faellt, ohne dass es auffaellt.

    Manche Seiten haben gar keine — das Profil wird gerollt statt fokussiert.
    Das ist kein Mangel, sondern eine andere Art von Seite.
    """
    gefunden: list[FocusGroup] = []
    gesehen: set[int] = set()

    def gehen(o, rest: int) -> None:
        if rest < 0 or id(o) in gesehen:
            return
        gesehen.add(id(o))
        if isinstance(o, FocusGroup):
            gefunden.append(o)
            return
        eigen = getattr(o, "__dict__", None)
        if not isinstance(eigen, dict):
            return
        for wert in eigen.values():
            if isinstance(wert, (list, tuple)):
                for x in wert:
                    gehen(x, rest - 1)
            else:
                gehen(wert, rest - 1)

    gehen(seite, 3)
    return gefunden


def _schale_mit(seite):
    """Eine Menueschale mit *seite* obenauf, fertig gezeichnet."""
    from src.states.menu_shell_state import MenuShellState

    schale = MenuShellState(_ZustandsAttrappe())
    schale.enter()
    schale.push_page(seite)
    _bild(schale)
    return schale


def _bild(schale) -> bytes:
    """Ein Standbild der Schale.

    Der Vergleich zweier Standbilder beantwortet die einzige Frage, die einen
    Spieler interessiert: **hat der Druck etwas bewirkt?** Ueber den Fokus
    allein waere das nicht zu beantworten — das Profil hat gar keine
    Fokusgruppe, dort rollt der Inhalt. Am Bild sieht man beides.
    """
    schirm = pygame.Surface(_SCHIRM)
    schirm.fill((0, 0, 0))
    schale.render(schirm)
    return pygame.image.tobytes(schirm, "RGB")


_SCHIRM = (1920, 1080)

#: Alle Seiten. „Demnaechst" ist eine reine Hinweisseite ohne Bedienung; sie
#: muss auf das D-Pad nicht reagieren, auf B aber sehr wohl.
_ALLE = sorted(_seiten())
_MIT_BEDIENUNG = [n for n in _ALLE if n != "Demnaechst"]


@pytest.mark.parametrize("name", _MIT_BEDIENUNG)
def test_das_dpad_bewirkt_auf_jeder_seite_etwas_sichtbares(pad, name):
    """Ein Druck, der nichts tut, ist fuer den Spieler ein kaputtes Menue.

    Ob sich der Fokus bewegt, der Inhalt rollt oder der Reiter wechselt, ist
    hier gleich — nur dass ueberhaupt etwas passiert.
    """
    schale = _schale_mit(_seiten()[name]())
    vorher = _bild(schale)

    for _ in range(4):
        schale.handle_events(spielhilfe.pad_druck(pad, gamepad.BTN_DPAD_DOWN))
        if _bild(schale) != vorher:
            return

    pytest.fail(f"{name}: vier Druecke auf das D-Pad aendern nichts am Bild")


@pytest.mark.parametrize("name", _MIT_BEDIENUNG)
def test_der_fokus_geht_beim_durchlaufen_nicht_verloren(pad, name):
    """Zweimal durch alle Elemente — und nie ins Leere.

    Der Fokus darf umlaufen, stehenbleiben darf er nicht: ein Fokus auf einem
    gesperrten Element laesst jede weitere Taste ins Leere laufen (dafuer gibt
    es ``FocusGroup.fokus_richten``).
    """
    seite = _seiten()[name]()
    schale = _schale_mit(seite)

    schritte = 2 * max((len(g.widgets) for g in _gruppen(seite)), default=0) + 6
    for _ in range(schritte):
        schale.handle_events(spielhilfe.pad_druck(pad, gamepad.BTN_DPAD_DOWN))
        for gruppe in _gruppen(seite):
            if not any(getattr(w, "focusable", False) for w in gruppe.widgets):
                continue
            assert getattr(gruppe.focused, "focusable", False), \
                f"{name}: Fokus liegt auf {gruppe.focused!r}"


@pytest.mark.parametrize("name", _MIT_BEDIENUNG)
def test_a_auf_jedem_element_stuerzt_nicht_ab(pad, name):
    """Der Weg, den ein Spieler mit dem Pad zwangslaeufig geht.

    Er sieht die Elemente nicht als Liste, er drueckt sich durch. Was dabei
    passiert, ist nicht Gegenstand des Tests — nur, dass es passieren darf,
    ohne dass etwas bricht.
    """
    seite = _seiten()[name]()
    schale = _schale_mit(seite)

    schritte = max((len(g.widgets) for g in _gruppen(seite)), default=0) + 3
    for _ in range(schritte):
        schale.handle_events(spielhilfe.pad_druck(pad, gamepad.BTN_A))
        schale.handle_events(spielhilfe.pad_druck(pad, gamepad.BTN_DPAD_DOWN))
        _bild(schale)          # zeichnen gehoert dazu: ein Fehler steckt oft dort


@pytest.mark.parametrize("name", _ALLE)
def test_b_fuehrt_von_jeder_seite_zurueck(pad, name):
    """Eine Seite, die B verschluckt, sperrt den Controller-Spieler ein.

    Mit der Maus gaebe es noch den Zurueck-Knopf; mit dem Pad ist B der einzige
    Weg heraus, den man ohne Suchen findet. Eine Rueckfrage („ungespeicherte
    Aenderungen") zaehlt als Antwort — sie fuehrt weiter, sie haelt nur an.
    """
    seite = _seiten()[name]()
    schale = _schale_mit(seite)
    tiefe = len(schale.page_stack)

    schale.handle_events(spielhilfe.pad_druck(pad, gamepad.BTN_B))

    raus = len(schale.page_stack) < tiefe
    rueckfrage = getattr(seite, "_dialog", None) or getattr(seite, "_leave_dialog", None)
    assert raus or rueckfrage, f"{name}: B bewirkt nichts"


def test_b_geht_eine_ebene_und_nicht_bis_ins_hauptmenue(pad):
    """Der Fund vom 02.08.2026, hier am Pad statt an der Tastatur.

    Ein Druck darf **einen** Schritt machen. Zwei Auswertungen desselben
    Drucks — roh und uebersetzt — machten zwei, und aus drei Ebenen tief
    landete man im Hauptmenue.
    """
    from src.states.menu.settings_page import SettingsPage
    from src.states.menu.coming_soon_page import ComingSoonPage

    schale = _schale_mit(ComingSoonPage("Test"))
    schale.push_page(SettingsPage())
    _bild(schale)
    assert len(schale.page_stack) == 2

    roh = pygame.event.Event(pygame.JOYBUTTONDOWN, joy=0,
                             button=gamepad.BTN_B, instance_id=0)
    schale.handle_events(gamepad.menue_eingaben([roh]))

    assert len(schale.page_stack) == 1, \
        f"ein Druck ging {2 - len(schale.page_stack)} Ebenen zurueck"


def test_der_controller_kommt_aus_jedem_reiter_der_einstellungen_heraus(pad):
    """Sechs Reiter, sechs mal derselbe Weg hinaus.

    Der Reiter wird mit dem D-Pad gewechselt; B muss aus jedem von ihnen
    dieselbe Ebene zurueckfuehren und nicht nur aus dem ersten.
    """
    from src.states.menu.settings_page import SettingsPage

    seite = SettingsPage()
    for reiter in range(len(seite.categories)):
        seite = SettingsPage()
        schale = _schale_mit(seite)
        seite.cat = reiter
        _bild(schale)

        schale.handle_events(spielhilfe.pad_druck(pad, gamepad.BTN_B))
        assert len(schale.page_stack) == 0, \
            f"Reiter {seite.categories[reiter]}: B fuehrt nicht heraus"
