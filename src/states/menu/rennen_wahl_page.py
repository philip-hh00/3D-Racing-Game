"""Die Auswahlseiten unter dem Reiter RENNEN.

    RENNEN          Lokal | Online
    Lokal           1 Spieler | 2 Spieler (Splitscreen)

Ab hier gelten die bisherigen Wege unveraendert: 1 Spieler fuehrt in die
Einzelspieler-Lobby, 2 Spieler ueber die Namenseingabe in die lokale
Mehrspieler-Lobby, Online in die Online-Seite. ESC und der Zurueck-Knopf gehen
genau eine Ebene hoch (Seitenstapel der Menue-Schale).

Tastatur, Maus und Controller laufen ueber dieselbe ``FocusGroup`` wie auf den
anderen Seiten; die Kacheln sind Widgets mit dem ueblichen Vertrag
(``rect``, ``focusable``, ``hit``, ``activate``, ``draw``).
"""
from __future__ import annotations

import pygame

from src.core.i18n import tr
from src.core.settings import SCREEN_WIDTH, SCREEN_HEIGHT
from src.states.menu.page import Page
from src.ui import theme, zeichnen, hints
from src.ui.focus import FocusGroup
from src.ui.widgets import _Base

#: Obere Kante der Inhaltsflaeche (Hoehe der Menueleiste) — dieselbe Zahl wie
#: ``menu_shell_state.TAB_H``; hier nicht importiert, damit die Schale die
#: Seiten ohne Kreisimport laden kann.
_INHALT_OBEN = 108
_KACHEL_B = 620
_KACHEL_H = 400
_LUECKE = 80


def _umbrechen(text: str, size: int, breite: int) -> list[str]:
    """*text* auf Zeilen von hoechstens *breite* Pixeln brechen."""
    f = theme.font(size)
    zeilen: list[str] = []
    zeile = ""
    for wort in text.split(" "):
        probe = (zeile + " " + wort).strip()
        if f.size(probe)[0] > breite and zeile:
            zeilen.append(zeile)
            zeile = wort
        else:
            zeile = probe
    if zeile:
        zeilen.append(zeile)
    return zeilen


class WahlKachel(_Base):
    """Eine grosse Auswahlkachel: Symbol, Titel und ein kurzer Beschreibungstext."""

    def __init__(self, rect, titel: str, text: str, action: str, symbol: str) -> None:
        super().__init__(rect)
        self.titel = titel
        self.text = text
        self.action = action
        self.symbol = symbol

    def activate(self) -> str | None:
        return self.action

    # -- Symbole: einfache Formen, keine Bilddateien ------------------------
    @staticmethod
    def _bildschirm(screen, farbe, mitte, fuellung: str | None = None) -> None:
        cx, cy = mitte
        rahmen = pygame.Rect(0, 0, 150, 92)
        rahmen.center = (cx, cy - 6)
        zeichnen.rect(screen, farbe, rahmen, 4, border_radius=8)
        zeichnen.line(screen, farbe, (cx, rahmen.bottom), (cx, rahmen.bottom + 14), 4)
        zeichnen.line(screen, farbe, (cx - 30, rahmen.bottom + 14),
                      (cx + 30, rahmen.bottom + 14), 4)
        if fuellung == "eins":
            wagen = pygame.Rect(0, 0, 44, 22)
            wagen.center = rahmen.center
            zeichnen.rect(screen, farbe, wagen, border_radius=8)
        elif fuellung == "zwei":
            zeichnen.line(screen, farbe, (cx, rahmen.top + 6), (cx, rahmen.bottom - 6), 3)
            for dx in (-35, 35):
                wagen = pygame.Rect(0, 0, 30, 18)
                wagen.center = (cx + dx, rahmen.centery)
                zeichnen.rect(screen, farbe, wagen, border_radius=6)

    def _symbol_zeichnen(self, screen, farbe, mitte) -> None:
        cx, cy = mitte
        if self.symbol == "online":
            zeichnen.circle(screen, farbe, (cx, cy), 52, 4)
            zeichnen.ellipse(screen, farbe, pygame.Rect(cx - 22, cy - 52, 44, 104), 3)
            zeichnen.line(screen, farbe, (cx - 52, cy), (cx + 52, cy), 3)
            zeichnen.line(screen, farbe, (cx - 40, cy - 26), (cx + 40, cy - 26), 2)
            zeichnen.line(screen, farbe, (cx - 40, cy + 26), (cx + 40, cy + 26), 2)
        elif self.symbol == "eins":
            self._bildschirm(screen, farbe, mitte, "eins")
        elif self.symbol == "zwei":
            self._bildschirm(screen, farbe, mitte, "zwei")
        else:                              # "lokal"
            self._bildschirm(screen, farbe, mitte)

    def draw(self, screen, focused: bool = False) -> None:
        aktiv = focused or self._hover()
        theme.panel(screen, self.rect, alpha=225,
                    border=theme.ACCENT_HOT if aktiv else theme.BORDER,
                    fill=theme.PANEL_SEL if aktiv else theme.PANEL, radius=12)
        if focused:
            zeichnen.rect(screen, theme.ACCENT_HOT, self.rect.inflate(-8, -8), 1,
                          border_radius=10)
        farbe = theme.ACCENT_HOT if aktiv else theme.ACCENT_DIM
        self._symbol_zeichnen(screen, farbe, (self.rect.centerx, self.rect.y + 120))

        theme.text_fit(screen, tr(self.titel), theme.HEADER,
                       theme.ACCENT_HOT if aktiv else theme.TEXT,
                       pygame.Rect(self.rect.x + 24, self.rect.y + 232, self.rect.w - 48, 60),
                       center=True)
        y = self.rect.y + 312
        for zeile in _umbrechen(tr(self.text), theme.LABEL, self.rect.w - 80)[:4]:
            theme.text(screen, zeile, theme.LABEL, theme.TEXT_DIM if not aktiv else theme.TEXT,
                       (self.rect.centerx, y), center=True)
            y += 36


class _WahlSeite(Page):
    """Gemeinsame Hulle der Auswahlseiten: Kacheln in einer Reihe, Fokus, Zurueck."""

    ZURUECK_UNTEN = True

    #: Schluessel der Kachel, auf der der Fokus beim Betreten steht.
    STANDARD = ""

    def __init__(self, vorwahl: str | None = None) -> None:
        self._vorwahl = vorwahl or self.STANDARD
        self._flaeche: pygame.Rect | None = None
        self.group = FocusGroup([])

    # -- von den Unterklassen --------------------------------------------
    def _eintraege(self) -> list[tuple[str, str, str, str]]:
        """``(Aktion, Titel, Text, Symbol)`` je Kachel, von links nach rechts."""
        raise NotImplementedError

    def _gewaehlt(self, aktion: str) -> None:
        raise NotImplementedError

    UEBERSCHRIFT = ""
    FRAGE = ""

    # -- Seite -------------------------------------------------------------
    def enter(self, shell, **kwargs) -> None:
        self.shell = shell
        self._bauen(pygame.Rect(0, _INHALT_OBEN, SCREEN_WIDTH, SCREEN_HEIGHT - _INHALT_OBEN))

    def _bauen(self, area: pygame.Rect) -> None:
        self._flaeche = pygame.Rect(area)
        eintraege = self._eintraege()
        n = len(eintraege)
        gesamt = n * _KACHEL_B + (n - 1) * _LUECKE
        x0 = area.centerx - gesamt // 2
        y0 = area.y + (area.h - _KACHEL_H) // 2 - 10
        kacheln = [WahlKachel(pygame.Rect(x0 + i * (_KACHEL_B + _LUECKE), y0,
                                          _KACHEL_B, _KACHEL_H), titel, text, aktion, sym)
                   for i, (aktion, titel, text, sym) in enumerate(eintraege)]
        index = self.group.index if self.group.widgets else None
        self.group = FocusGroup(kacheln)
        if index is not None:
            self.group.index = index
        else:
            for i, (aktion, *_rest) in enumerate(eintraege):
                if aktion == self._vorwahl:
                    self.group.index = i

    def handle_event(self, event: pygame.event.Event) -> bool:
        if self.zurueck_geklickt(event):
            return True
        aktion = self.group.handle_event(event)
        if aktion:
            self._gewaehlt(aktion)
            return True
        return False

    def draw(self, screen: pygame.Surface, area: pygame.Rect) -> None:
        if self._flaeche != area:
            self._bauen(area)
        self.zurueck_zeichnen(screen, area)
        theme.text(screen, tr(self.UEBERSCHRIFT), theme.HEADER, theme.ACCENT, (80, 128))
        theme.text(screen, tr(self.FRAGE), theme.BODY, theme.TEXT_DIM, (80, 190))
        self.group.draw(screen)
        theme.text(screen, hints.bar(("nav_h", tr("Wechseln")), ("confirm", tr("Auswählen")),
                                     ("back", tr("Zurück"))),
                   theme.HINT, theme.TEXT_DIM, (area.centerx, area.bottom - 40), center=True)


class RennenWahlPage(_WahlSeite):
    """Oberste Ebene des Reiters RENNEN: lokal oder online."""

    UEBERSCHRIFT = "RENNEN"
    FRAGE = "Wie möchtest du fahren?"
    STANDARD = "lokal"

    def _eintraege(self):
        return [
            ("lokal", "Lokal",
             "An diesem Gerät: allein oder zu zweit im Splitscreen.", "lokal"),
            ("online", "Online",
             "Gegen andere im Netz: Lobby erstellen oder beitreten.", "online"),
        ]

    def _gewaehlt(self, aktion: str) -> None:
        if aktion == "lokal":
            self.shell.push_page(LokalWahlPage())
        elif aktion == "online":
            self.shell.rennen_starten("online")


class LokalWahlPage(_WahlSeite):
    """Lokal: ein Spieler oder zwei im Splitscreen."""

    UEBERSCHRIFT = "RENNEN — LOKAL"
    FRAGE = "Wie viele Spieler fahren?"
    STANDARD = "single"

    def _eintraege(self):
        return [
            ("single", "1 Spieler",
             "Allein am Steuer: gegen Computerfahrer oder auf Bestzeit.", "eins"),
            ("mp", "2 Spieler (Splitscreen)",
             "Zwei Spieler an einem Gerät, mit geteiltem Bildschirm.", "zwei"),
        ]

    def _gewaehlt(self, aktion: str) -> None:
        self.shell.rennen_starten("single" if aktion == "single" else "mp_local")
