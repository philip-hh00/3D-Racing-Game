"""Bausteine, die mehrere Testdateien brauchen — einmal, nicht viermal.

Drei Dinge liegen hier:

* :func:`rennen_bauen` und :func:`rennen_fahren` — ein Rennen ohne Fenster
  aufbauen und in Bildschritten fahren.
* :class:`PadAttrappe` und :func:`pad_anmelden` — ein Controller ohne
  Controller.
* :func:`gezeichnete_texte` — mitschreiben, was eine Seite wirklich auf den
  Bildschirm malt.

**Warum gemeinsam.** Am 06.08.2026 stellte sich heraus, dass die Relay-Hilfe
der Netztests wortgleich in drei Testdateien stand — und damit derselbe Fehler
dreimal. Diese Datei ist die Lehre daraus, gezogen bevor es wieder passiert.

Ein Modul ohne ``test_``-Vorsilbe: pytest sammelt hier nichts ein.
"""
from __future__ import annotations

import math
import os
import sys
from typing import Any, Callable

import pygame

_WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _WURZEL not in sys.path:
    sys.path.insert(0, _WURZEL)


# ---------------------------------------------------------------------------
# Ein Rennen ohne Fenster
# ---------------------------------------------------------------------------

#: Die mitgelieferten Strecken. Nicht fest verdrahtet, sondern gelesen — kommt
#: eine dazu, faehrt die Simulation sie ohne Zutun mit.
def mitgelieferte_strecken() -> list[str]:
    ordner = os.path.join(_WURZEL, "data", "tracks")
    return sorted(n[:-5] for n in os.listdir(ordner) if n.endswith(".json"))


class StateMachineAttrappe:
    """Nimmt Zustandswechsel entgegen und merkt sie sich, statt sie zu gehen.

    Ein Rennen ruft am Ende ``transition("results")``. Wuerde das wirklich
    laufen, zoege der Test die halbe Menuewelt mit hoch; gemerkt reicht, um zu
    pruefen, *dass* es passiert ist.
    """

    def __init__(self) -> None:
        self.wechsel: list[tuple[tuple, dict]] = []

    def transition(self, *args: Any, **kwargs: Any) -> None:
        self.wechsel.append((args, kwargs))

    # Manche Wege im Rennen greifen auf diese beiden zu.
    def push(self, *args: Any, **kwargs: Any) -> None:
        pass

    def pop(self, *args: Any, **kwargs: Any) -> None:
        pass


def spielstand_zuruecksetzen() -> None:
    """Den prozessweiten Rennaufbau auf Werkszustand.

    ``race_setup`` haelt **eine** Konfiguration fuer den ganzen Prozess. Ohne
    das hier erbt jeder Test die Wahl des vorigen — und ein Rennen, das nur
    deshalb durchlaeuft, weil vorher jemand die Rundenzahl gesenkt hat, ist
    kein bestandener Test.
    """
    from src.core import race_setup
    race_setup._current = race_setup.RaceSetup()


def fahrzeuge_laden() -> None:
    """Die Fahrzeugdaten einlesen, falls das noch niemand getan hat.

    Ohne diesen Aufruf liefert ``VehicleFactory.create_ai_vehicle`` stillschweigend
    ``None`` — das Rennen startet dann **ohne Gegner** und jede Zusage darueber
    ist wertlos. Genau so ist am 06.08.2026 eine Farbpruefung ins Leere gelaufen
    und hat fuer jedes Fahrzeug +0,00 gemeldet.
    """
    from src.entities.vehicle_factory import VehicleFactory
    if not getattr(VehicleFactory, "_configs", None):
        VehicleFactory.load_all_configs()


#: Rennen, die gebaut, aber noch nicht geschlossen wurden. Siehe
#: :func:`alles_schliessen`.
_offen: list = []


def alles_schliessen() -> None:
    """Jedes offene Rennen ordentlich beenden.

    **Warum das noetig ist.** ``EventBus`` ist prozessweit, und ein Rennen
    meldet sich beim Betreten fuer fuenf Ereignisse an. Abgemeldet wird es erst
    in ``exit()`` — im Spiel ruft die Zustandsmaschine das, im Test niemand. Ein
    Test, der einfach aufhoert, laesst seine Handler stehen: das naechste
    Rennen loest sie mit aus, und die Rennen davor rechnen unsichtbar weiter
    mit. Aufgefallen ist es an der Meldung „Race completed!", die nach dem
    24. Rennen 24-mal auf einmal erschien.
    """
    while _offen:
        rennen = _offen.pop()
        try:
            rennen.exit()
        except Exception:
            # Ein Rennen, das beim Aufraeumen stolpert, darf den naechsten Test
            # nicht mitreissen — der Fehler gehoert dem Test, der es gebaut hat.
            pass


def rennen_bauen(strecke: str = "oval", *, runden: int = 1, feld: int = 6,
                 modus: str = "Rennen", klasse: str = "Alle",
                 schwierigkeit: str = "medium", ki_fahrzeug: str | None = None,
                 **kwargs: Any):
    """Ein fahrbereites Rennen. Gibt ``(RaceState, StateMachineAttrappe)``.

    *feld* ist die Feldgroesse einschliesslich des Menschen; die KI fuellt auf.
    Das Rennen wird vorgemerkt und von :func:`alles_schliessen` beendet.

    *ki_fahrzeug* legt die KI-Autos auf Fahrzeugschluessel fest — ein Schluessel
    fuer alle, oder eine Liste, die reihum vergeben wird. Ohne das steht im
    Kader ``"random"``, und ``_spawn_ai_vehicles`` zieht mit ``random.choice``:
    ein Test, der zwei Laeufe vergleicht, misst dann den Zufall mit, und ein
    Test ueber eine Fahrzeugklasse sieht drei zufaellige statt aller drei
    Modelle. Genau diese Sorte Flatterhaftigkeit hat am 06.08.2026 einen halben
    Tag gekostet.
    """
    from src.core import race_setup
    from src.states.race_state import RaceState

    fahrzeuge_laden()
    spielstand_zuruecksetzen()

    aufbau = race_setup.current()
    aufbau.mode = modus
    aufbau.laps = runden
    aufbau.vehicle_count = feld
    aufbau.vehicle_class = klasse
    aufbau.ai_difficulty = schwierigkeit
    # Auch in den Aufbau, nicht nur als Argument an enter(): das Rennen faehrt
    # ``kwargs["track_path"]``, der Ghost im Zeitfahren liest dagegen
    # ``race_setup.current().track_path``. Wer nur eines setzt, faehrt die eine
    # Strecke und bekommt den Ghost der anderen — beim Nachstellen des Funds
    # vom 07.08.2026 lief genau das und kostete eine halbe Stunde Suche an der
    # falschen Stelle. Im Spiel setzen alle Wege beides.
    aufbau.track_path = strecke if strecke.endswith(".json") else \
        os.path.join(_WURZEL, "data", "tracks", f"{strecke}.json")
    aufbau.sync_ai_roster()
    if ki_fahrzeug is not None:
        schluessel = ([ki_fahrzeug] if isinstance(ki_fahrzeug, str)
                      else list(ki_fahrzeug))
        for i, fahrer in enumerate(aufbau.ai_roster):
            fahrer.vehicle = schluessel[i % len(schluessel)]

    sm = StateMachineAttrappe()
    rennen = RaceState(sm)
    # ``track_path`` und nicht ``track``: ``RaceState.enter`` liest genau
    # diesen Namen und faellt sonst still auf ``data/tracks/oval.json`` zurueck.
    # Bis zum 07.08.2026 stand hier ``track=`` — jeder Renntest fuhr damit das
    # Oval, auch die fuenf, die je Strecke parametrisiert sind. Sie waren gruen
    # und haben weniger geprueft, als sie behaupteten.
    rennen.enter(track_path=aufbau.track_path, **kwargs)
    _offen.append(rennen)
    return rennen, sm


def schliessen(rennen) -> None:
    """Ein Rennen jetzt beenden und aus der Merkliste nehmen."""
    if rennen in _offen:
        _offen.remove(rennen)
    rennen.exit()


def horcher_zahl() -> int:
    """Wie viele Rueckrufe insgesamt am prozessweiten Ereignisbus haengen."""
    from src.core.event_bus import EventBus
    return sum(len(v) for v in EventBus()._subscribers.values())


def bus_isolieren(monkeypatch) -> None:
    """Dem Test einen leeren Ereignisbus geben und den alten danach zurueck.

    **Warum das noetig ist.** ``EventBus`` ist ein Singleton fuer den ganzen
    Prozess, und ein Rennen meldet sich darin fuer fuenf Ereignisse an. Im
    Spiel meldet ``exit()`` es wieder ab; in einem Testlauf tut das nicht jeder
    Test, der nebenbei ein Rennen oder einen Rundenzaehler baut. Gemessen am
    07.08.2026: nach rund 1480 Tests haengen **88** fremde Rueckrufe am Bus.

    Die stoeren nicht theoretisch. Fahrzeugnummern fangen in jedem Rennen
    wieder bei 1 an — ein abgeraeumter Rennverwalter von vorhin haelt also
    Rundenzaehler zu genau den Nummern, die das laufende Rennen gerade
    benutzt, und bekommt jedes ``checkpoint_crossed`` und ``lap_completed``
    mit. Sichtbar wurde es daran, dass dieselben Renntests einzeln grün waren
    und im vollen Lauf rot: ein Auto stand in Runde 5 von 3, weil das Rennen
    nie in ``finished`` kam.

    Aufgeraeumt wird nur fuer die Dauer des Tests. Was vorher am Bus hing,
    haengt danach wieder dort — dieser Test ist nicht der Ort, fremde
    Rueckstaende zu entsorgen.
    """
    from collections import defaultdict
    from src.core.event_bus import EventBus

    monkeypatch.setattr(EventBus(), "_subscribers", defaultdict(list))


def datenordner_spiegeln(monkeypatch, ziel) -> None:
    """In ein Ausweichverzeichnis wechseln, in dem ``data/`` schreibbar ist.

    **Warum.** Zwei Werkzeuge schreiben ueber **relative** Pfade zurueck in den
    Datenordner: das Fahrzeuglabor nach ``data/vehicles/<schluessel>.json``
    (``vehicle_lab_state.py``) und das Klanglabor nach
    ``data/audio/motor_klang.json`` (``motorklang.py``). Relativ heisst: relativ
    zum Arbeitsverzeichnis — und das ist im Testlauf der Arbeitsbaum. Der
    Affentest hat am 07.08.2026 genau so drei versionierte Dateien veraendert;
    aufgefallen ist es erst an ``git status``.

    ``conftest.py`` faengt das nicht ab: es lenkt das Verzeichnis fuer
    **Nutzerdaten** um (Profil, Ghosts, eigene Strecken), und diese beiden
    Pfade gehoeren nicht dazu — sie zeigen auf mitgelieferte Daten, die zur
    Laufzeit eigentlich unveraenderlich sind.

    Kopiert werden nur die 72 KB JSON, die wirklich beschrieben werden; alles
    uebrige (239 MB Videos, Klaenge, Bilder) wird verlinkt. Ein Kopieren des
    ganzen Ordners je Test waere die Laufzeit nicht wert.
    """
    import shutil
    from pathlib import Path

    ziel = Path(ziel)
    quelle = Path(_WURZEL) / "data"
    (ziel / "data").mkdir(parents=True, exist_ok=True)

    beschreibbar = {"vehicles", "audio"}
    for eintrag in quelle.iterdir():
        neu = ziel / "data" / eintrag.name
        if eintrag.name not in beschreibbar:
            neu.symlink_to(eintrag, target_is_directory=eintrag.is_dir())
            continue
        # Hier hinein wird geschrieben: JSON kopieren, den Rest verlinken.
        neu.mkdir(exist_ok=True)
        for datei in eintrag.iterdir():
            if datei.suffix == ".json":
                shutil.copy2(datei, neu / datei.name)
            else:
                neu.joinpath(datei.name).symlink_to(
                    datei, target_is_directory=datei.is_dir())

    monkeypatch.chdir(ziel)


def aufbau_bewahren(monkeypatch) -> None:
    """Den prozessweiten Rennaufbau nach dem Test wiederherstellen.

    ``race_setup`` haelt **eine** Konfiguration fuer den ganzen Prozess: Modus,
    Feldgroesse, gewaehlte Strecke, gewaehltes Fahrzeug. Ein Test, der sich
    durch Menues klickt, verstellt sie unterwegs — und der naechste Test
    beginnt dann mit einer Strecke, die er nicht gewaehlt hat.

    Gefunden am 07.08.2026: ``test_gast_darf_blaettern_ohne_auszuwaehlen``
    erwartete den Cursor der Grand-Prix-Uebersicht auf 1 und fand ihn auf 4.
    Die Uebersicht setzt ihn beim Eintreten auf die **gewaehlte** Strecke, und
    die hatte der Controller-Durchlauf davor mit lauter A-Druecken verstellt.

    Der Test bekommt eine **Kopie** zum Verstellen; das Original wird
    beiseitegelegt und danach zurueckgesetzt. Ein blosses Merken der Referenz
    reichte nicht — verstellt wird das Objekt an Ort und Stelle.
    """
    import copy

    from src.core import race_setup

    monkeypatch.setattr(race_setup, "_current",
                        copy.deepcopy(race_setup._current))


def fahrzeuge(rennen) -> list:
    """Alle Autos im Rennen — Menschen und KI, in Startreihenfolge."""
    menschen = list(getattr(rennen, "_humans", None) or
                    ([rennen.player] if rennen.player else []))
    return menschen + list(rennen.ai_vehicles)


def rennen_fahren(rennen, sekunden: float = 120.0, dt: float = 1 / 60,
                  je_bild: Callable[[Any, int], None] | None = None,
                  halt_am_ziel: bool = True) -> float:
    """Das Rennen fahren, bis es zu Ende ist oder *sekunden* um sind.

    Gibt die gefahrene Rennzeit zurueck. *je_bild* wird nach jedem Bild mit
    ``(rennen, bildnummer)`` gerufen — dort haengen die Tests ihre Zusagen ein,
    damit ein Fehler beim **ersten** falschen Bild auffaellt und nicht erst am
    Ende, wenn nicht mehr zu sehen ist, wo er herkam.

    *halt_am_ziel* aus, wenn geprueft werden soll, was **nach** dem Ziel
    passiert: der Weg in die Ergebnisse laeuft ueber weitere Bilder, und ein
    ausrollendes DNF-Auto haelt ihn ein paar Sekunden auf.
    """
    bilder = int(sekunden / dt)
    for i in range(bilder):
        rennen.handle_events([])
        rennen.update(dt)
        if je_bild is not None:
            je_bild(rennen, i)
        verwalter = rennen.race_manager
        if halt_am_ziel and verwalter is not None \
                and verwalter.state == "finished":
            return (i + 1) * dt
    return bilder * dt


def streckenfeld(rennen, rand: float = 400.0) -> pygame.Rect:
    """Der Bereich, in dem sich ein Auto aufhalten darf.

    Die Huelle um die aeussere Streckenbegrenzung plus *rand*. Grosszuegig mit
    Absicht: geprueft wird nicht, ob ein Auto sauber faehrt, sondern ob es die
    Welt verlaesst — ein Auto, das durch eine Wand faellt, ist nach wenigen
    Sekunden Tausende Einheiten weit weg, ein ausgangs der Kurve rutschendes
    bleibt in Streckennaehe.
    """
    punkte = list(rennen.track.outer_wall) or list(rennen.track.centerline)
    xs = [p[0] for p in punkte]
    ys = [p[1] for p in punkte]
    return pygame.Rect(
        int(min(xs) - rand), int(min(ys) - rand),
        int(max(xs) - min(xs) + 2 * rand), int(max(ys) - min(ys) + 2 * rand))


def ist_endlich(*werte: float) -> bool:
    """Ob jeder Wert eine echte Zahl ist — kein ``nan``, kein ``inf``.

    Eine Physik, die einmal ``nan`` erzeugt, kommt nie wieder zurueck: jede
    Rechnung damit ergibt wieder ``nan``, das Auto verschwindet und der
    Bildschirm bleibt heil. Sichtbar wird es erst daran, dass nichts mehr
    passiert.
    """
    return all(isinstance(w, (int, float)) and math.isfinite(w) for w in werte)


# ---------------------------------------------------------------------------
# Ein Controller ohne Controller
# ---------------------------------------------------------------------------

class PadAttrappe:
    """Das Wenige, das ``GamepadManager`` von einem Joystick braucht.

    Der Manager verlangt kein pygame-Joystick-Objekt, sondern vier Methoden.
    Damit laesst sich die gesamte Uebersetzung von Pad-Ereignissen in
    Menuebefehle pruefen, ohne dass ein Geraet angesteckt ist — und damit auch
    auf dem Bauknecht, wo nie eines stecken wird.
    """

    def __init__(self, iid: int = 0, name: str = "Xbox Series Controller") -> None:
        self._iid = iid
        self._name = name

    def get_instance_id(self) -> int:
        return self._iid

    def get_id(self) -> int:
        return self._iid

    def get_name(self) -> str:
        return self._name

    def get_numbuttons(self) -> int:
        return 16

    def get_numaxes(self) -> int:
        return 6

    def get_numhats(self) -> int:
        return 1

    def get_axis(self, nr: int) -> float:
        return 0.0

    def get_button(self, nr: int) -> int:
        return 0

    def init(self) -> None:
        pass


def pad_anmelden(anzahl: int = 1):
    """Ein (oder mehrere) vorgetaeuschte Pads beim Manager anmelden.

    Gibt eine Funktion zurueck, die den vorherigen Zustand wiederherstellt —
    der Manager ist prozessweit, ein Test darf ihn dem naechsten nicht
    veraendert hinterlassen.
    """
    from src.core import gamepad

    gamepad.init()
    m = gamepad._gamepad_manager
    vorher = (list(m._joysticks), m._ready_at, m._active_device_filter)

    m._joysticks = [PadAttrappe(i) for i in range(anzahl)]
    # Der Anlaufschutz schluckt sonst jede Eingabe der ersten Sekunde. Im Spiel
    # ist er richtig (ein frisch erkanntes Pad feuert beim Anstecken), im Test
    # wuerde er alles verschlucken.
    m._ready_at = 0
    m.set_menu_translation(True)
    m.set_device_filter(None)

    def zurueck() -> None:
        m._joysticks, m._ready_at, m._active_device_filter = vorher

    return m, zurueck


def pad_druck(manager, taste: int, iid: int = 0) -> list[pygame.event.Event]:
    """Einen Knopfdruck schicken und die uebersetzten Menuebefehle einsammeln."""
    roh = pygame.event.Event(pygame.JOYBUTTONDOWN, joy=iid, button=taste,
                             instance_id=iid)
    return list(manager.menu_events([roh]))


def pad_tasten(manager, taste: int, iid: int = 0) -> list[int]:
    """Dasselbe, aber nur die Tastencodes — das, was ein Menue davon sieht."""
    return [e.key for e in pad_druck(manager, taste, iid)
            if e.type == pygame.KEYDOWN]


# ---------------------------------------------------------------------------
# Mitschreiben, was gezeichnet wird
# ---------------------------------------------------------------------------

class Textzug:
    """Ein gemalter Text, sein Schriftkasten und seine sichtbaren Zeichen.

    Der Unterschied ist der Punkt. ``rect`` ist die Flaeche, die pygame fuer
    die Zeile belegt — sie enthaelt oben und unten die Reserve fuer Ober- und
    Unterlaengen, auch wenn im Text gar keine vorkommen. ``tinte`` ist, was man
    wirklich sieht.

    Am 07.08.2026 gemessen: die Ueberschrift „WERTUNG & FAHRER" in der
    Grand-Prix-Uebersicht belegt y=165..195, die Spaltenkoepfe darunter
    y=186..208 — die Kaesten ueberschneiden sich um 9 px. Die Zeichen aber
    stehen bei y=173..189 und y=193..208: **4 px Luft dazwischen**. Wer die
    Kaesten vergleicht, meldet hier einen Fehler, den niemand sehen kann.
    """

    __slots__ = ("text", "rect", "tinte", "groesse")

    def __init__(self, text: str, rect: pygame.Rect, tinte: pygame.Rect,
                 groesse: int) -> None:
        self.text = text
        self.rect = pygame.Rect(rect)
        self.tinte = pygame.Rect(tinte)
        self.groesse = groesse

    def __repr__(self) -> str:            # nur fuer die Fehlermeldung
        return f"{self.text!r}@{tuple(self.tinte)}"


class Mitschrift:
    """Sammelt die Textzuege eines Zeichenvorgangs."""

    def __init__(self) -> None:
        self.zuege: list[Textzug] = []

    def ausserhalb(self, flaeche: pygame.Rect) -> list[Textzug]:
        return [z for z in self.zuege if not flaeche.contains(z.tinte)]

    def ueberlagerungen(self) -> list[tuple[Textzug, Textzug]]:
        """Paare, deren **sichtbare Zeichen** sich schneiden.

        Zwei Faelle bleiben bewusst draussen:

        * Leere Tinte — ein Leerzeichen malt nichts und kann nichts verdecken.
        * Zweimal derselbe Text an derselben Stelle. Das ist kein Uebereinander,
          sondern dasselbe Bild zweimal: die Werkstatt setzt ihren
          Zurueck-Knopf mit ``zurueck_zeichnen`` an seinen Platz und zeichnet
          ihn danach noch einmal mit Fokus. Sichtbar ist davon genau eine
          Fassung, und die obere ist die richtige.

        Quadratisch in der Anzahl der Texte — bei den Groessenordnungen hier
        (Dutzende je Seite) ist das billiger als jede Beschleunigung, die man
        erst wieder pruefen muesste.
        """
        raus = []
        for i, a in enumerate(self.zuege):
            if not a.tinte.width or not a.tinte.height:
                continue
            for b in self.zuege[i + 1:]:
                if not b.tinte.width or not b.tinte.height:
                    continue
                if a.text == b.text and a.tinte == b.tinte:
                    continue
                if a.tinte.colliderect(b.tinte):
                    raus.append((a, b))
        return raus


class _SchriftSpion:
    """Eine Schrift, die sich merkt, was sie zuletzt gemalt hat.

    Der Umweg ueber die Schrift ist noetig, weil ``theme.text`` den Text
    unterwegs veraendern kann: passt er nicht in ``max_w``, wird erst die
    Groesse verkleinert und dann gekuerzt. Von aussen ist weder die
    tatsaechliche Groesse noch der tatsaechliche Text zu sehen — die gerenderte
    Flaeche kennt beides, und aus ihr kommt die Tinte.
    """

    __slots__ = ("_schrift", "_ablage")

    def __init__(self, schrift, ablage: list) -> None:
        self._schrift = schrift
        self._ablage = ablage

    def render(self, *args, **kwargs):
        flaeche = self._schrift.render(*args, **kwargs)
        self._ablage.append(flaeche)
        return flaeche

    def __getattr__(self, name):
        return getattr(self._schrift, name)


def gezeichnete_texte(monkeypatch) -> Mitschrift:
    """``theme.text`` und ``theme.text_fit`` beim Zeichnen belauschen.

    Beide geben das Rechteck zurueck, in dem sie gemalt haben — die Mitschrift
    ist damit kein Nachbau des Layouts, sondern das, was wirklich auf dem
    Bildschirm steht. Ein nachgerechnetes Layout kann sich irren; dieses hier
    ist per Bauart richtig.

    Festgehalten wird beides: der Schriftkasten und die **Tinte**, also die
    Flaeche, in der wirklich Zeichen stehen. Siehe :class:`Textzug`, warum der
    Unterschied ueber richtig und falsch entscheidet.

    Nicht erfasst: was mit ``screen.blit`` direkt gemalt wird — das HUD tut
    das. Fuer die Menueseiten, um die es hier geht, laeuft alles ueber diese
    beiden Funktionen.
    """
    from src.ui import theme

    mit = Mitschrift()
    echt_text = theme.text
    echt_fit = theme.text_fit
    echt_font = theme.font
    gemalt: list = []

    def spion_font(groesse, *a, **k):
        return _SchriftSpion(echt_font(groesse, *a, **k), gemalt)

    def merken(screen, s: str, r: pygame.Rect, size: int) -> None:
        # Die letzte gerenderte Flaeche gehoert zu diesem Aufruf; ihre
        # bemalte Teilflaeche, verschoben an die Blitstelle, ist die Tinte.
        if gemalt:
            innen = gemalt[-1].get_bounding_rect()
            tinte = innen.move(r.topleft)
        else:
            tinte = pygame.Rect(r)

        # **Und dann durch den Beschnitt.** Wer in einen rollenden Kasten malt,
        # setzt vorher ``screen.set_clip``; was ausserhalb liegt, landet nie auf
        # dem Bildschirm. Ohne diesen Schritt meldete die Regel Text, den
        # niemand sehen kann: die Info-Seite zeichnet ihre Ankuendigungen in
        # einen Kasten mit Unterkante y=900, und die Eintraege darunter
        # „ueberlagerten" die Zeilen bei y=916 und y=971. Auf der Bauknecht-
        # Maschine fiel es nicht auf, weil dort ohne Netz gar keine
        # Ankuendigungen ankamen (07.08.2026).
        #
        # ``get_clip`` liefert ohne gesetzten Beschnitt die ganze Flaeche, der
        # Schritt ist also immer richtig.
        sichtbar = tinte.clip(screen.get_clip())
        if not sichtbar.width or not sichtbar.height:
            return                      # vollstaendig abgeschnitten
        mit.zuege.append(Textzug(s, r, sichtbar, size))

    def spion_text(screen, s, size, color, pos, **kw):
        gemalt.clear()
        r = echt_text(screen, s, size, color, pos, **kw)
        if s:
            merken(screen, s, r, size)
        return r

    def spion_fit(screen, s, size, color, rect, **kw):
        gemalt.clear()
        r = echt_fit(screen, s, size, color, rect, **kw)
        if s:
            merken(screen, s, r, size)
        return r

    monkeypatch.setattr(theme, "font", spion_font)
    monkeypatch.setattr(theme, "text", spion_text)
    monkeypatch.setattr(theme, "text_fit", spion_fit)
    return mit


def sprache_setzen(monkeypatch, kuerzel: str) -> None:
    """Die Oberflaeche auf eine Sprache stellen, fuer die Dauer eines Tests.

    Die Reihenfolge ist nicht beliebig: erst die Wiederherstellung anmelden,
    **dann** umschalten. Andersherum merkt sich monkeypatch den bereits
    umgeschalteten Wert und der Test laesst die Sprache umgestellt zurueck —
    der naechste liefe dann in einer Sprache, die er nicht gewaehlt hat.
    """
    from src.core import i18n
    monkeypatch.setattr(i18n, "_lang", i18n._lang)
    i18n.set_language(kuerzel)


def widget_rechtecke(objekt: Any, tiefe: int = 4) -> list[tuple[str, pygame.Rect]]:
    """Alles mit einem ``rect`` unterhalb von *objekt* einsammeln.

    Ueber die Attribute gelaufen statt ueber eine Liste, die eine Seite fuehren
    muesste: es gibt keine solche Liste, und eine einzufuehren hiesse, den
    Spielcode fuer den Test umzubauen. Der Weg hier findet, was da ist, und
    nichts muss gepflegt werden.
    """
    gesehen: set[int] = set()
    raus: list[tuple[str, pygame.Rect]] = []

    def gehen(o: Any, rest: int) -> None:
        if rest < 0 or id(o) in gesehen:
            return
        gesehen.add(id(o))
        r = getattr(o, "rect", None)
        if isinstance(r, pygame.Rect):
            raus.append((type(o).__name__, pygame.Rect(r)))
        eigen = getattr(o, "__dict__", None)
        if not isinstance(eigen, dict):
            return
        for wert in eigen.values():
            if isinstance(wert, (list, tuple)):
                for x in wert:
                    gehen(x, rest - 1)
            elif isinstance(wert, dict):
                for x in wert.values():
                    gehen(x, rest - 1)
            else:
                gehen(wert, rest - 1)

    gehen(objekt, tiefe)
    return raus
