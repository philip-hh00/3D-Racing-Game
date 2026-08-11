"""Base class for in-shell menu pages.

A Page is a lightweight sub-screen hosted by the MenuShell (Lobby, Settings,
Coming-Soon, …). Unlike a full game state it does not own the background or the
tab bar — the shell draws those and hands the page a content *area* to fill.
Pages talk back to the shell through the shell reference passed on enter().
"""
from __future__ import annotations

import pygame


class Page:
    #: Short heading shown by some pages; optional.
    title: str = ""

    #: Wo der Zurück-Knopf sitzt: oben links in der Inhaltsfläche, auf jeder
    #: Seite an derselben Stelle. Eine Seite, die dort etwas anderes braucht,
    #: verschiebt ihn — sie soll ihn aber nicht neu erfinden.
    ZURUECK_VERSATZ = (40, 16)

    #: Unten links statt oben links (gemeldet 05.08.2026).
    #:
    #: „In Workshop und Profil ist die Plazierung passend auch bei der
    #: Fahrzeugauswahl und der Streckenauswahl. In den anderen Untermenüs und
    #: Lobbys würde ich diesen ehr nach ganz unten Links setzen da stört ehr in
    #: allen fällen nicht." Oben links liegt er dort im Weg: die Lobbys füllen
    #: die obere Bildhälfte mit Steppern und Listen, die Werkstatt und das
    #: Profil haben dort ohnehin eine freie Zeile.
    ZURUECK_UNTEN = False

    #: Abstand zur unteren linken Ecke, wenn ``ZURUECK_UNTEN`` gilt. Die
    #: Bedienhinweise stehen mittig — der Knopf links kommt ihnen nicht ins
    #: Gehege.
    ZURUECK_UNTEN_VERSATZ = (80, 40)

    def enter(self, shell, **kwargs) -> None:
        self.shell = shell

    # ------------------------------------------------------------------
    # Der Rückweg als Knopf (gemeldet 04.08.2026)
    # ------------------------------------------------------------------
    # „In den Menüs Lobbys usw. gibt es noch teilweise keine zurück Buttons und
    # der User ist auf ESC angewiesen." Der Knopf gehört hierher und nicht in
    # jede Seite einzeln: gleiche Stelle, gleiche Größe, gleiches Ziel. Wohin er
    # führt, entscheidet ``MenuShellState.zurueck_gehen`` — dieselbe Stelle, die
    # auch ESC bedient, damit Taste und Knopf nie auseinanderlaufen.

    def zurueck_knopf(self):
        """Der Knopf dieser Seite; wird beim ersten Zugriff angelegt."""
        knopf = getattr(self, "_zurueck_knopf", None)
        if knopf is None:
            from src.ui.widgets import ZurueckKnopf
            knopf = ZurueckKnopf(0, 0)
            self._zurueck_knopf = knopf
        return knopf

    def zurueck_zeichnen(self, screen: pygame.Surface, area: pygame.Rect):
        """Den Knopf an seinen Platz setzen und zeichnen. Gibt sein Rechteck
        zurück, damit eine Seite darunter weiterrechnen kann."""
        knopf = self.zurueck_knopf()
        if self.ZURUECK_UNTEN:
            dx, dy = self.ZURUECK_UNTEN_VERSATZ
            knopf.rect.bottomleft = (area.x + dx, area.bottom - dy)
        else:
            dx, dy = self.ZURUECK_VERSATZ
            knopf.rect.topleft = (area.x + dx, area.y + dy)
        knopf.draw(screen)
        return knopf.rect

    def zurueck_geklickt(self, event: pygame.event.Event) -> bool:
        """Ob *event* ein Klick auf den Knopf ist — und wenn ja, ihn gehen.

        Der Rückgabewert ist das, was ``handle_event`` melden muss: verbraucht.

        Der Weg führt durch ``verlassen_erlaubt`` und damit durch dieselbe
        Rückfrage, die auch ein Tabklick auslöst. Ohne sie verschluckte der
        Knopf ungespeicherte Änderungen, während ESC danach fragte — genau das
        Auseinanderlaufen von Taste und Knopf, das dieser Knopf beenden sollte.
        """
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return False
        if not self.zurueck_knopf().hit(event.pos):
            return False
        shell = getattr(self, "shell", None)
        if shell is not None and self.verlassen_erlaubt(shell.zurueck_gehen):
            shell.zurueck_gehen()
        return True

    def hides_tab_bar(self) -> bool:
        """Ob die Shell ihre Tab-Leiste für diese Seite ausblenden soll.

        Standard ist Nein: eine Seite ist Teil des Menüs und die Leiste zeigt,
        wo man steht. Ausnahme sind Ebenen, die keine Menüseite mehr sind,
        sondern ein eigener Abschnitt einer laufenden Sitzung (Grand-Prix-
        Übersicht) — dort führt ein Sprung in einen anderen Tab aus der Sitzung
        heraus, und die Leiste behauptet eine Wahl, die es nicht gibt.
        """
        return False

    def verlassen_erlaubt(self, weiter) -> bool:
        """Darf die Shell diese Seite jetzt verlassen (Klick auf einen Tab)?

        ``True`` heißt ja, sofort. ``False`` heißt: die Seite hat übernommen —
        sie fragt nach und ruft *weiter* selbst auf, wenn der Nutzer zustimmt.
        Standard ist ja; nur wer etwas zu verlieren hat, hält an.
        """
        return True

    def handle_event(self, event: pygame.event.Event) -> None:
        pass

    def update(self, dt: float) -> None:
        pass

    def draw(self, screen: pygame.Surface, area: pygame.Rect) -> None:
        pass
