"""Die Funde vom 05.08.2026, jeder mit dem Fehler festgehalten, den er erzeugt hat.

Fünf Meldungen, drei Ursachen — und zwei davon sind dieselbe Verwechslung.

**Zwei Abstürze**, beide Rückstände aus der Woche davor: eine querschnittliche
Änderung hat eine Stelle nicht erreicht, und genau dort knallt es. Im Editor war
es ``theme`` (die Zeichen ``theme.HAKEN``/``theme.WARNUNG`` vom 04.08. kamen in
eine Datei, die ``theme`` nie importiert hat), im Pausenmenü ``zurueck_gehen``
(der Knopf vom 04.08. ruft es auf jeder Seite, aber die Schale im Rennen ist
keine ``MenuShellState``). Beides fällt nur auf, wenn man den Weg wirklich geht —
ein Importtest hätte keinen davon gefunden.

**Zwei Einheitenverwechslungen**, unabhängig voneinander entstanden, aber mit
derselben Wurzel: ``max_speed`` und ``current_speed`` stehen in px/s, gerechnet
wurde mit km/h. Einmal wurde der Rückwärtsgang dadurch auf ein Viertel gedeckelt,
einmal stand jeder Balken auf Anschlag. Deshalb prüfen die Tests unten nicht die
Konstante, sondern das Ergebnis in km/h — eine Zahl, die niemand nachrechnen
muss, um sie zu beurteilen.

**Eine geschenkte Strecke**, die eine eigene verdeckt: die Umbenennung sah nur
im Nutzerverzeichnis nach, gelesen wird aber über alle Wurzeln.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.core import profile  # noqa: E402
from src.core.settings import KMH_PER_PXS  # noqa: E402


@pytest.fixture(autouse=True)
def spielstand(monkeypatch):
    p = profile.Profile(username="Philip")
    p.save = lambda: None
    p.statistik = {}
    monkeypatch.setattr(profile, "_current", p, raising=False)
    monkeypatch.setattr(profile, "current", lambda: p)
    return p


class _StateMachineAttrappe:
    def __init__(self) -> None:
        self.wechsel: list[tuple[str, dict]] = []

    def transition(self, name: str, **kwargs) -> None:
        self.wechsel.append((name, kwargs))


def _klick(pos):
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos)


# ---------------------------------------------------------------------------
# Absturz 1 — Streckeneditor: theme war nie importiert
# ---------------------------------------------------------------------------
# „Beim öffnen einer Strecke im Streckeneditor.
#  NameError: name 'theme' is not defined"  (editor_state.py:234, _refresh_status)

def test_der_editor_kann_den_status_einer_strecke_berechnen():
    """``_refresh_status`` läuft bei **jedem** Öffnen und bei jeder Änderung.

    Gerufen wird es aus ``update``, nicht aus dem Zeichenpfad — ein Test, der nur
    zeichnet, ginge daran vorbei.
    """
    from src.states.editor_state import EditorState
    from src.track.tile_track import TileTrackDraft

    zustand = EditorState(_StateMachineAttrappe())
    zustand.draft = TileTrackDraft()
    zustand._refresh_status()

    assert zustand._status_text, "ohne Text weiß der Editor nichts zu melden"
    assert zustand._geo_dirty is False


def test_auch_die_geschlossene_strecke_bekommt_ihren_haken():
    """Der Zweig mit ``theme.HAKEN`` ist der, der gemeldet wurde.

    Eine offene Strecke läuft am Zeichen vorbei; nur die geschlossene erreicht
    die Zeile, die abgestürzt ist.
    """
    from src.states.editor_state import EditorState
    from src.track.tile_track import TileTrackDraft
    from src.ui import theme

    zustand = EditorState(_StateMachineAttrappe())
    zustand.draft = TileTrackDraft()
    zustand.draft.is_closed_loop = lambda: True
    zustand.draft.open_ports = lambda: []
    zustand.draft.validate_game = lambda: []
    zustand._refresh_status()

    assert theme.HAKEN in zustand._status_text


def test_editor_holt_theme_nicht_mehr_in_einzelnen_methoden():
    """Eine Datei, die ``theme`` an drei Stellen benutzt, importiert es einmal.

    Der Absturz entstand, weil zwei Methoden ihren eigenen lokalen Import hatten
    und die dritte darauf vertraute, dass er im Modul steht.
    """
    import src.states.editor_state as modul
    quelle = open(modul.__file__, encoding="utf-8").read()

    assert "theme" in vars(modul), "theme gehört in die Modul-Globals"
    assert quelle.count("from src.ui import theme") == 0, \
        "kein zweiter, lokaler Import — sonst ist wieder unklar, was gilt"
    assert "from src.ui import hints, theme" in quelle


# ---------------------------------------------------------------------------
# Absturz 2 — Pausenmenü: die Schale im Rennen kannte zurueck_gehen nicht
# ---------------------------------------------------------------------------
# „Pausemenü im Rennen, Button Back führt zu Absturz:
#  AttributeError: 'SettingsShellAdapter' object has no attribute 'zurueck_gehen'"

def _rennen_mit_pauseneinstellungen():
    from src.states.race_state import RaceState
    rennen = RaceState(_StateMachineAttrappe())
    rennen._open_pause_settings()
    return rennen


def test_zurueck_im_pausenmenue_stuerzt_nicht_ab():
    rennen = _rennen_mit_pauseneinstellungen()
    seite = rennen._pause_settings
    knopf = seite.zurueck_knopf()
    knopf.rect.topleft = (40, 40)

    assert seite.handle_event(_klick(knopf.rect.center)) is True
    assert rennen._pause_view != "settings", \
        "der Knopf muss die Einstellungen auch wirklich verlassen"


def test_die_schale_im_rennen_kann_alles_was_eine_seite_ruft():
    """Nicht nur der eine Aufruf, der abgestürzt ist.

    Der Absturz war ein fehlendes Stück einer Schnittstelle, und ein Test auf
    genau diesen einen Namen hätte den nächsten Rückstand wieder durchgelassen.
    """
    rennen = _rennen_mit_pauseneinstellungen()
    schale = rennen._pause_settings.shell

    for name in ("pop_page", "zurueck_gehen", "state_machine", "page_stack"):
        assert hasattr(schale, name), f"die Schale im Rennen braucht {name}"


def test_knopf_und_taste_verlassen_die_pauseneinstellungen_gleich():
    """Dieselbe Regel wie im Menü: zwei Wege für eine Absicht führen gleich weit."""
    ueber_knopf = _rennen_mit_pauseneinstellungen()
    seite = ueber_knopf._pause_settings
    seite.zurueck_knopf().rect.topleft = (40, 40)
    seite.handle_event(_klick(seite.zurueck_knopf().rect.center))

    ueber_taste = _rennen_mit_pauseneinstellungen()
    ueber_taste._pause_settings.shell.pop_page()

    assert ueber_knopf._pause_view == ueber_taste._pause_view


def test_ungespeicherte_einstellungen_gehen_am_knopf_nicht_verloren():
    """Der Knopf fragt genauso nach wie ESC und der Tabklick.

    Vorher lief er an ``verlassen_erlaubt`` vorbei: ESC zeigte den Dialog, der
    Knopf daneben warf die Änderungen weg. Genau das Auseinanderlaufen von Taste
    und Knopf, gegen das der Knopf gebaut wurde.
    """
    rennen = _rennen_mit_pauseneinstellungen()
    seite = rennen._pause_settings
    seite._pending["music_volume"] = 30   # eine echte, ungespeicherte Änderung
    assert seite._dirty
    seite.zurueck_knopf().rect.topleft = (40, 40)

    seite.handle_event(_klick(seite.zurueck_knopf().rect.center))

    assert seite._leave_dialog is not None, "es muss gefragt werden"
    assert rennen._pause_view == "settings", "und vorher wird nichts verlassen"


# ---------------------------------------------------------------------------
# Einheiten 1 — Rückwärtsgang stand in px/s, gemeint war km/h
# ---------------------------------------------------------------------------
# „Rückwärtsfahren ist auf 5 km/h begrenzt — Erhöhen auf 30 km/h"

def _motor(schluessel="rookie"):
    """Der Motor genau so gebaut, wie ``Vehicle`` ihn baut."""
    from src.entities.components.engine import Engine
    from src.entities.vehicle import VehicleConfig
    config = VehicleConfig.from_json(f"data/vehicles/{schluessel}.json")
    return Engine(
        max_power=config.engine_power,
        max_speed=config.max_speed,
        gear_ratios=config.gear_ratios,
        gears_max_speeds_ratios=None,
        idle_rpm=config.idle_rpm,
        redline_rpm=config.redline_rpm,
        shift_up_rpm=config.redline_rpm * 0.95,
        torque_curve=getattr(config, "torque_curve", None),
        wheel_diameter=getattr(config, "wheel_diameter", 0.65),
    )


def test_rueckwaerts_zieht_bis_etwa_dreissig_kmh():
    """Gemessen in km/h, nicht an der Konstanten.

    Die Konstante hieß 30 und stand für 8,6 km/h — ein Test auf ``== 30`` wäre
    grün gewesen und hätte den Fehler zementiert.
    """
    motor = _motor()
    grenze_kmh = motor.max_reverse_speed_pxs * KMH_PER_PXS

    assert 28.0 <= grenze_kmh <= 32.0, f"{grenze_kmh:.1f} km/h"


def test_rueckwaerts_schiebt_noch_bei_zwanzig_kmh():
    """Die Kraft fällt zur Grenze hin auf null — bei 5 km/h fühlte sich das
    Auto deshalb schon weit vor 8,6 km/h fest an."""
    motor = _motor()
    zwanzig_pxs = 20.0 / KMH_PER_PXS

    kraft = motor.compute_force(-1.0, zwanzig_pxs, 1 / 60.0)

    assert kraft < 0.0, "rückwärts muss die Kraft nach hinten zeigen"


def test_rueckwaerts_hoert_an_der_grenze_auf():
    motor = _motor()
    darueber = motor.max_reverse_speed_pxs * 1.1

    assert motor.compute_force(-1.0, darueber, 1 / 60.0) == 0.0


# ---------------------------------------------------------------------------
# Einheiten 2 — Top-Speed-Balken stand bei jedem Fahrzeug auf Anschlag
# ---------------------------------------------------------------------------
# „Blaue Statusbar bei Top Speed ist bei jedem Fahrzeug voll —
#  Anpassen auf die max und min Werte bezogen auf alle Fahrzeuge"

def _alle_fahrzeuge():
    from src.core.race_setup import CLASSES
    from src.entities.vehicle import VehicleConfig
    return [VehicleConfig.from_json(f"data/vehicles/{k}.json") for k in CLASSES["Alle"]]


def test_der_top_speed_balken_unterscheidet_die_fahrzeuge():
    from src.states.car_select_state import top_speed_anteil

    anteile = {round(top_speed_anteil(c), 3) for c in _alle_fahrzeuge()}

    assert len(anteile) > 1, "ein Balken, der überall gleich steht, sagt nichts"
    assert max(anteile) > min(anteile) + 0.5, \
        "die Spanne muss den Balken auch sichtbar ausnutzen"


def test_das_schnellste_fahrzeug_fuellt_den_balken_und_das_langsamste_nicht():
    from src.states.car_select_state import top_speed_anteil

    fahrzeuge = sorted(_alle_fahrzeuge(), key=lambda c: c.max_speed)

    assert top_speed_anteil(fahrzeuge[-1]) == pytest.approx(1.0, abs=0.01)
    assert top_speed_anteil(fahrzeuge[0]) < 0.3


def test_der_balken_bleibt_in_seinen_ufern():
    from src.states.car_select_state import top_speed_anteil

    for config in _alle_fahrzeuge():
        anteil = top_speed_anteil(config)
        assert 0.0 <= anteil <= 1.0, f"{config.name}: {anteil}"


# ---------------------------------------------------------------------------
# Die geschenkte Strecke, die eine eigene verdeckt
# ---------------------------------------------------------------------------
# „Wenn ich eine hochgeladene Strecke von einem User herunterlade … der Name wird
#  nicht angepasst wenn ich eine Strecke mit dem selben Namen schon habe."

def _wurzeln_setzen(monkeypatch, nutzer, bundle):
    from src.core import paths
    monkeypatch.setattr(paths, "user_data_dir", lambda: nutzer)
    monkeypatch.setattr(paths, "bundle_dir", lambda: bundle)
    monkeypatch.setattr(paths, "track_roots", lambda: [nutzer, bundle])


def _strecke_anlegen(wurzel, name):
    ordner = wurzel / "data" / "tracks" / "custom"
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / name).write_text(json.dumps({"centerline": []}), encoding="utf-8")


def test_eine_geschenkte_strecke_ueberschreibt_keine_eigene(monkeypatch, tmp_path):
    from src.core import paths
    nutzer, bundle = tmp_path / "nutzer", tmp_path / "bundle"
    _wurzeln_setzen(monkeypatch, nutzer, bundle)
    _strecke_anlegen(nutzer, "Rundkurs.json")

    ziel = paths.freier_streckenpfad("data/tracks/custom", "Rundkurs.json")

    assert os.path.basename(ziel) == "Rundkurs (2).json"


def test_auch_eine_mitgelieferte_strecke_wird_nicht_verdeckt(monkeypatch, tmp_path):
    """Der eigentliche Fund. Aus dem Quelltext gestartet fallen Nutzer- und
    Bundleverzeichnis zusammen, im gepackten Build nicht — und dort lag die
    eigene Strecke im Bundle, wurde beim Prüfen nicht gesehen, und die
    geschenkte gewann anschließend die Namensgleichheit in ``track_files``.
    """
    from src.core import paths
    nutzer, bundle = tmp_path / "nutzer", tmp_path / "bundle"
    _wurzeln_setzen(monkeypatch, nutzer, bundle)
    _strecke_anlegen(bundle, "Rundkurs.json")

    ziel = paths.freier_streckenpfad("data/tracks/custom", "Rundkurs.json")

    assert os.path.basename(ziel) != "Rundkurs.json", \
        "sonst verschwindet die eigene Strecke aus der Liste"


def test_beide_strecken_bleiben_danach_sichtbar(monkeypatch, tmp_path):
    """Die Probe aufs Exempel: nach dem Speichern müssen es zwei sein."""
    from src.core import paths
    nutzer, bundle = tmp_path / "nutzer", tmp_path / "bundle"
    _wurzeln_setzen(monkeypatch, nutzer, bundle)
    _strecke_anlegen(bundle, "Rundkurs.json")

    ziel = paths.freier_streckenpfad("data/tracks/custom", "Rundkurs.json")
    os.makedirs(os.path.dirname(ziel), exist_ok=True)
    open(ziel, "w", encoding="utf-8").write("{}")

    namen = {p.name for p in paths.track_files("custom")}
    assert namen == {"Rundkurs.json", "Rundkurs (2).json"}


def test_ein_freier_name_bleibt_unveraendert(monkeypatch, tmp_path):
    from src.core import paths
    nutzer, bundle = tmp_path / "nutzer", tmp_path / "bundle"
    _wurzeln_setzen(monkeypatch, nutzer, bundle)

    ziel = paths.freier_streckenpfad("data/tracks/custom", "Rundkurs.json")

    assert os.path.basename(ziel) == "Rundkurs.json"


# ---------------------------------------------------------------------------
# Die Fahrzeugwahl überlebt den Weg durch die Werkstatt
# ---------------------------------------------------------------------------
# „Wenn ich ein Fahrzeug in der Werkstatt bearbeite und aus der Fahrzeugauswahl
#  und wieder dahin zurück gehe soll das Fahrzeug ausgewählt bleiben."

class _SchaleMitZustand:
    """Menüschale, die sich den Zustandswechsel merkt."""

    def __init__(self) -> None:
        self.gewechselt: list[tuple[str, dict]] = []
        self.abgeraeumt = 0
        self.state_machine = self

    def transition(self, ziel: str, **argumente) -> None:
        self.gewechselt.append((ziel, argumente))

    def pop_page(self) -> None:
        self.abgeraeumt += 1


def _werkstatt_mit_kurzweg(hingegangen_mit: str):
    from src.states.menu.werkstatt_page import WerkstattPage
    seite = WerkstattPage()
    schale = _SchaleMitZustand()
    seite.enter(schale, vehicle_config=hingegangen_mit,
                rueckweg=("car_select", {"picker": "p1", "online_mode": False,
                                         "vehicle_config": hingegangen_mit}))
    return seite, schale


def test_die_werkstatt_kommt_mit_dem_fahrzeug_zurueck_das_sie_zeigt():
    """Der Streifen ist eine Auswahl, keine blosse Vorschau."""
    seite, schale = _werkstatt_mit_kurzweg("rookie")
    seite._fahrzeug_wechseln(seite.fahrzeuge.index("supercar"))
    seite._weggehen()

    ziel, argumente = schale.gewechselt[-1]
    assert ziel == "car_select"
    assert argumente["vehicle_config"] == "supercar"


def test_der_uebrige_rueckweg_bleibt_unangetastet():
    """Die Fahrzeugauswahl kennt drei Rückwege — geändert wird nur das Fahrzeug."""
    seite, schale = _werkstatt_mit_kurzweg("rookie")
    seite._fahrzeug_wechseln(seite.fahrzeuge.index("drifter"))
    seite._weggehen()

    _ziel, argumente = schale.gewechselt[-1]
    assert argumente["picker"] == "p1"
    assert argumente["online_mode"] is False


def test_ohne_wechsel_kommt_dasselbe_fahrzeug_zurueck():
    seite, schale = _werkstatt_mit_kurzweg("limousine")
    seite._weggehen()

    _ziel, argumente = schale.gewechselt[-1]
    assert argumente["vehicle_config"] == "limousine"


def test_die_fahrzeugauswahl_nimmt_die_anweisung_auch_im_mehrspieler(monkeypatch):
    """Vorher galt ``vehicle_config`` nur im Einzelspieler — im Mehrspieler fiel
    die Auswahl auf die Lobbywahl zurück, und der Weg durch die Werkstatt war
    dort umsonst."""
    from src.core import race_setup
    from src.states.car_select_state import CarSelectState

    s = race_setup.current()
    monkeypatch.setattr(type(s), "is_multiplayer", property(lambda self: True))
    s.player_vehicle = "rookie"

    zustand = CarSelectState(_StateMachineAttrappe())
    zustand.enter(picker="p1", vehicle_config="supercar")

    assert zustand.car_keys[zustand.selected_index] == "supercar"


# ---------------------------------------------------------------------------
# Das Leistungsdiagramm überlagert sich nicht mehr
# ---------------------------------------------------------------------------
# „Das Diagramm für das Drehmoment und die Motorleistung hat bei den dem Titel
#  und den Achsen überlagerungen von der Beschriftung"

class _MitschreibendeFlaeche(pygame.Surface):
    """Eine Zeichenfläche, die sich merkt, wohin geschrieben wurde.

    Gezeichneter Text ist nicht auslesbar; wo er landet, schon. ``pygame.draw``
    geht daran vorbei — Rahmen und Gitterlinien sollen auch nicht mitzählen.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.kaesten: list[tuple[str, pygame.Rect]] = []

    def blit(self, *args, **kwargs):
        rect = super().blit(*args, **kwargs)
        self.kaesten.append(("", pygame.Rect(rect)))
        return rect


def _diagramm_kaesten(schluessel="supercar"):
    """Zeichnet das Diagramm und gibt zurück, wo welcher Text gelandet ist.

    Gemessen wird am gezeichneten Bild, nicht an nachgerechneten Konstanten —
    genau die Nachrechnung war ja falsch.
    """
    from src.entities.vehicle_factory import VehicleFactory
    from src.states.car_select_state import CarSelectState

    VehicleFactory.load_all_configs()
    zustand = CarSelectState(_StateMachineAttrappe())
    zustand.enter(picker="p1")
    config = VehicleFactory.get_config(schluessel)

    schirm = _MitschreibendeFlaeche((1920, 1080))
    zustand._draw_power_curve(schirm, config)
    return schirm.kaesten


def test_im_leistungsdiagramm_ueberlagert_sich_kein_text():
    kaesten = [r for _n, r in _diagramm_kaesten()]
    assert kaesten, "es wurde gar nichts beschriftet"
    for i, a in enumerate(kaesten):
        for b in kaesten[i + 1:]:
            assert not a.colliderect(b), f"{a} überlagert {b}"


@pytest.mark.parametrize("schluessel", ["rookie", "supercar", "electric",
                                        "limousine", "drifter"])
def test_das_gilt_fuer_jede_fahrzeugklasse(schluessel):
    """Die Spitzenzeile ist je Fahrzeug verschieden lang, und die Achsenzahlen
    haben je nach Drehzahlband drei oder vier Stellen."""
    kaesten = [r for _n, r in _diagramm_kaesten(schluessel)]
    for i, a in enumerate(kaesten):
        for b in kaesten[i + 1:]:
            assert not a.colliderect(b), f"{schluessel}: {a} überlagert {b}"


def test_alles_bleibt_in_der_tafel():
    """Ein Text, der aus der Tafel läuft, liegt auf dem Fahrzeug daneben."""
    tafel = pygame.Rect(1215, 570, 540, 300)
    for _n, r in _diagramm_kaesten():
        assert tafel.contains(r), f"{r} ragt aus {tafel}"


# ---------------------------------------------------------------------------
# Fahrzeug- und Streckenauswahl: erster Klick markiert, zweiter geht weiter
# ---------------------------------------------------------------------------
# „Wenn ich ein Fahrzeug oder eine Strecke auswähle soll mit dem ersten
#  Mausklick diese hervorgehoben werden (Ausgewählt bleiben auch wenn ich dann
#  über die anderen auswhlmöglichkeiten drüber hovere) mit dem nächsten klick
#  gehts dann weiter. Ich denke es ergibt auch sinn wenn es in er
#  Fahrzeugauswahl einen weiter button gibt und bei der Streckenauswahl den
#  Button Rennen start."

def _bewegung(pos):
    return pygame.event.Event(pygame.MOUSEMOTION, pos=pos, rel=(1, 1), buttons=(0, 0, 0))


def _fahrzeugauswahl(online=False):
    from src.entities.vehicle_factory import VehicleFactory
    from src.states.car_select_state import CarSelectState
    VehicleFactory.load_all_configs()
    zustand = CarSelectState(_StateMachineAttrappe())
    zustand.enter(picker="p1", online_mode=online)
    return zustand


def _streckenauswahl():
    from src.states.track_select_state import TrackSelectState
    zustand = TrackSelectState(_StateMachineAttrappe())
    zustand.enter()
    return zustand


def test_der_zeiger_zieht_die_fahrzeugwahl_nicht_mehr_mit():
    """Der Kern der Meldung. Vorher wählte jede Mausbewegung mit — wer sein
    Fahrzeug gewählt hatte und den Zeiger nur wegbewegte, hatte ein anderes."""
    zustand = _fahrzeugauswahl()
    karten = zustand._car_card_rects()
    zustand.handle_events([_klick(karten[1][1].center)])
    gewaehlt = zustand.selected_index

    zustand.handle_events([_bewegung(karten[0][1].center)])

    assert zustand.selected_index == gewaehlt, "der Zeiger hat die Wahl mitgenommen"


def test_der_zeiger_zieht_die_streckenwahl_nicht_mehr_mit():
    zustand = _streckenauswahl()
    karten = zustand._track_card_rects()
    zustand.handle_events([_klick(karten[1][1].center)])
    gewaehlt = zustand.selected_index

    zustand.handle_events([_bewegung(karten[0][1].center)])

    assert zustand.selected_index == gewaehlt


def test_der_erste_klick_waehlt_nur_aus():
    zustand = _fahrzeugauswahl()
    karten = zustand._car_card_rects()

    zustand.handle_events([_klick(karten[2][1].center)])

    assert zustand.selected_index == 2
    assert zustand.state_machine.wechsel == [], "der erste Klick ist noch kein Weiter"


def test_der_zweite_klick_auf_dieselbe_kachel_geht_weiter():
    zustand = _fahrzeugauswahl()
    karten = zustand._car_card_rects()

    zustand.handle_events([_klick(karten[2][1].center)])
    zustand.handle_events([_klick(karten[2][1].center)])

    assert zustand.state_machine.wechsel, "der zweite Klick muss weiterführen"


def test_ein_klick_auf_eine_andere_kachel_waehlt_nur_um():
    """Sonst wäre jeder Vergleich zweier Fahrzeuge ein versehentliches Weiter."""
    zustand = _fahrzeugauswahl()
    karten = zustand._car_card_rects()

    zustand.handle_events([_klick(karten[1][1].center)])
    zustand.handle_events([_klick(karten[3][1].center)])

    assert zustand.selected_index == 3
    assert zustand.state_machine.wechsel == []


def test_das_vorausgewaehlte_fahrzeug_braucht_trotzdem_zwei_klicks():
    """Man kommt schon ausgewählt an — aus der Lobby, aus der Werkstatt.

    Ohne diese Unterscheidung wäre der erste Klick dort gleich der zweite, und
    „mit dem ersten Mausklick hervorgehoben" ginge ins Leere.
    """
    zustand = _fahrzeugauswahl()
    karten = zustand._car_card_rects()
    zustand.selected_index = karten[1][0]

    zustand.handle_events([_klick(karten[1][1].center)])

    assert zustand.state_machine.wechsel == []


def test_der_weiter_knopf_fuehrt_weiter():
    zustand = _fahrzeugauswahl()
    zustand.handle_events([_klick(zustand._weiter_rect().center)])
    assert zustand.state_machine.wechsel


def test_der_startknopf_der_streckenwahl_startet():
    zustand = _streckenauswahl()
    zustand.handle_events([_klick(zustand._start_rect().center)])
    assert zustand.state_machine.wechsel


def test_die_knoepfe_heissen_offline_nach_ihrem_ziel():
    assert _fahrzeugauswahl()._weiter_beschriftung() == "Weiter"
    assert _streckenauswahl()._start_beschriftung() == "Rennen starten"


def test_online_wird_nur_gewaehlt_und_nicht_gestartet():
    """„Muss online natürlich anders gelöst werden hier wird ja nur gewählt da
    das Rennen über den Button in der Lobby gestartet wird."""
    zustand = _fahrzeugauswahl(online=True)
    assert zustand._weiter_beschriftung() == "Übernehmen"

    zustand.handle_events([_klick(zustand._weiter_rect().center)])
    ziel, argumente = zustand.state_machine.wechsel[-1]
    assert (ziel, argumente.get("reopen")) == ("menu", "online_lobby")


def test_die_knoepfe_liegen_nicht_uebereinander():
    zustand = _fahrzeugauswahl()
    assert not zustand._weiter_rect().colliderect(zustand._werkstatt_rect())


def test_die_knoepfe_liegen_im_bild():
    from src.core.settings import SCREEN_HEIGHT, SCREEN_WIDTH
    bild = pygame.Rect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT)
    assert bild.contains(_fahrzeugauswahl()._weiter_rect())
    assert bild.contains(_streckenauswahl()._start_rect())


def test_der_startknopf_deckt_keine_streckenkachel_zu():
    zustand = _streckenauswahl()
    knopf = zustand._start_rect()
    for _i, rect in zustand._track_card_rects():
        assert not knopf.colliderect(rect)
