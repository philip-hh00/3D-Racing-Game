"""Werkzeug fuer die Controller-Pruefung (kein Test, wird nicht gesammelt).

Die Vorgabe des Besitzers: **jeder** Knopf, Reiter, Stepper, jede Listenzeile,
jedes Textfeld, jeder Dialog muss mit dem Controller allein erreichbar und
bedienbar sein. Das laesst sich nicht pro Seite von Hand behaupten, sondern nur
als Regel pruefen. Zwei Sichten, die sich ergaenzen:

1. **Gezeichnet, aber nicht im Fokus.** Beim Zeichnen einer Ansicht wird
   mitgeschrieben, welche Bedienelemente (``widgets._Base``) tatsaechlich
   gemalt werden. Ist eines davon bedienbar (``enabled``), aber in keiner
   Fokusgruppe der Ansicht, erreicht es nur die Maus. Das ist der haeufigste
   Fehler: ein Element wird gebaut und gezeichnet, aber nicht in die Gruppe
   gelegt (so war es beim Sprachwechsel und dem Beenden-Knopf unter
   Einstellungen > Allgemein).
2. **Im Fokus, aber nicht erreichbar.** In jeder Gruppe wird von jedem Element
   aus jede Richtung des Steuerkreuzes gedrueckt (ueber den Weg des Spiels:
   Pad-Knopf -> ``GamepadManager`` -> synthetische Taste -> Seite) und der
   Fokus abgelesen. Daraus entsteht ein Graph; ein bedienbares Element, das von
   keinem anderen aus erreichbar ist, ist eine Sackgasse.
"""
from __future__ import annotations

import pygame

from src.core import gamepad
from src.ui import widgets
from src.ui.focus import FocusGroup
from tests import spielhilfe

RICHTUNGEN = (gamepad.BTN_DPAD_UP, gamepad.BTN_DPAD_DOWN,
              gamepad.BTN_DPAD_LEFT, gamepad.BTN_DPAD_RIGHT)


def alle_unterklassen(klasse, acc=None) -> set:
    acc = acc if acc is not None else set()
    for u in klasse.__subclasses__():
        if u not in acc:
            acc.add(u)
            alle_unterklassen(u, acc)
    return acc


class Zeichenmitschrift:
    """Belauscht ``draw`` aller Bedienelemente, solange der Test laeuft."""

    def __init__(self, monkeypatch) -> None:
        self.gezeichnet: list = []
        for klasse in alle_unterklassen(widgets._Base) | {widgets._Base}:
            if "draw" not in klasse.__dict__:
                continue
            monkeypatch.setattr(klasse, "draw", self._huelle(klasse.__dict__["draw"]))

    def _huelle(self, echt):
        liste = self.gezeichnet

        def draw(selbst, *a, **k):
            liste.append(selbst)
            return echt(selbst, *a, **k)
        return draw

    def leeren(self) -> None:
        self.gezeichnet.clear()

    def bedienbar(self) -> list:
        """Gezeichnete Elemente, die der Spieler bedienen koennen soll."""
        gesehen, aus = set(), []
        for w in self.gezeichnet:
            if id(w) in gesehen or isinstance(w, widgets.Label):
                continue
            gesehen.add(id(w))
            if getattr(w, "enabled", True) and hasattr(w, "activate"):
                aus.append(w)
        return aus


def beschreibe(w) -> str:
    name = type(w).__name__
    text = getattr(w, "label", None) or getattr(w, "action", None) or getattr(w, "text", "")
    return f"{name}({text!r})"


def nicht_im_fokus(mitschrift: Zeichenmitschrift, gruppen: list[FocusGroup],
                   erlaubt=()) -> list[str]:
    """Gezeichnete, bedienbare Elemente, die in keiner der *gruppen* stehen.

    *erlaubt*: Elemente, die bewusst nur mit der Maus gehen, weil es eine
    Taste gibt, die dasselbe tut (der Zurueck-Knopf: B).
    """
    ids = {id(w) for g in gruppen for w in g.widgets}
    aus = []
    for w in mitschrift.bedienbar():
        if id(w) in ids or isinstance(w, widgets.ZurueckKnopf):
            continue
        if any(w is e for e in erlaubt):
            continue
        if not getattr(w, "focusable", True):
            continue
        aus.append(beschreibe(w))
    return aus


def druecke(manager, ziel, taste: int) -> list[pygame.event.Event]:
    """Einen Pad-Knopf auf dem Weg des Spiels an *ziel* schicken.

    Derselbe Weg wie in ``Game.run``: ``observe`` (das Spiel merkt sich, dass
    gerade der Controller benutzt wird), dann ``menue_eingaben`` (rohe Ereignisse
    raus, uebersetzte rein) — es sei denn, der Zustand liest das Pad selbst
    (``raw_gamepad``, der Editor). *ziel* hat ``handle_event`` (Seite) oder
    ``handle_events`` (Zustand). Gibt die zugestellten Ereignisse zurueck.
    """
    roh = pygame.event.Event(pygame.JOYBUTTONDOWN, joy=0, button=taste,
                             instance_id=0)
    gamepad.observe([roh])
    if getattr(ziel, "raw_gamepad", False):
        events = [roh]
    else:
        events = gamepad.menue_eingaben([roh])
    # Loslassen: ohne das haelt der Manager das Steuerkreuz fuer gedrueckt und
    # schluckt jeden weiteren Druck derselben Richtung (Wiederholungsschutz).
    if taste in RICHTUNGEN:
        gamepad.menue_eingaben([pygame.event.Event(
            pygame.JOYBUTTONUP, joy=0, button=taste, instance_id=0)])
    for e in events:
        if hasattr(ziel, "handle_events"):
            ziel.handle_events([e])
        else:
            ziel.handle_event(e)
    return events


def mehrmals(manager, ziel, *tasten: int) -> None:
    """Nacheinander mehrere Knoepfe druecken."""
    for t in tasten:
        druecke(manager, ziel, t)


def erreichbarkeit(manager, ziel, gruppe: FocusGroup, vorbereiten=None
                   ) -> list[str]:
    """Bedienbare Elemente von *gruppe*, die per Steuerkreuz nicht erreichbar sind.

    *vorbereiten* wird vor jedem Druck gerufen (Zustand zuruecksetzen, etwa
    eine Ansicht, die ein Druck verlassen haette).
    """
    n = len(gruppe.widgets)
    bedienbar = [i for i, w in enumerate(gruppe.widgets)
                 if getattr(w, "focusable", False)]
    if not bedienbar:
        return []
    start = gruppe.index if gruppe.index in bedienbar else bedienbar[0]
    kanten: dict[int, set[int]] = {i: set() for i in bedienbar}
    for i in bedienbar:
        for richtung in RICHTUNGEN:
            gruppe.index = i
            gruppe.bearbeiten = False
            if vorbereiten is not None:
                vorbereiten()
            druecke(manager, ziel, richtung)
            j = gruppe.index
            if 0 <= j < n and j != i:
                kanten[i].add(j)
    erreicht, offen = {start}, [start]
    while offen:
        for j in kanten.get(offen.pop(), ()):
            if j not in erreicht and j in kanten:
                erreicht.add(j)
                offen.append(j)
    gruppe.index = start
    return [beschreibe(gruppe.widgets[i]) for i in bedienbar if i not in erreicht]
