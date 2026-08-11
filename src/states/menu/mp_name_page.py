"""Local multiplayer player 2 name page.

Shown before entering the local multiplayer lobby.
Allows player 2 to input their name, which is validated and stored.
"""
from __future__ import annotations

import pygame

from src.states.menu.page import Page
from src.core import race_setup, profile, gamepad
from src.ui import theme
from src.ui.widgets import Button, TextInput, OnScreenKeyboard
from src.ui.focus import FocusGroup
from src.states.menu.mp_lobby_page import MPLobbyPage
from src.core.i18n import tr


class MPNamePage(Page):
    #: Der Zurück-Knopf steht mit dem Inhalt auf einer Kante (x + 80); der Titel
    #: rückt dafür nach rechts und liest sich als Fortsetzung: „‹ Zurück  TITEL".
    ZURUECK_VERSATZ = (80, 16)
    #: Unten links: oben ist hier kein Platz (gemeldet 05.08.2026).
    ZURUECK_UNTEN = True

    def enter(self, shell, **kwargs) -> None:
        self.shell = shell
        self.msg = ""
        self.osk: OnScreenKeyboard | None = None
        s = race_setup.current()
        s.is_multiplayer = True

        # Ensure default is "Spieler_2" if empty or default "Spieler 2"/"Player-2"
        if not s.player2_name or s.player2_name in ("Spieler 2", "Player-2", "Spieler_2", "Player_2"):
            s.player2_name = tr("Spieler_2")

        x, w, h = 560, 800, 56
        y = 320  # Center it vertically

        self.p2name = TextInput(pygame.Rect(x, y, w, h), s.player2_name, max_len=profile.NAME_MAX,
                                allowed=profile.NAME_ALLOWED)
        self.next = Button(pygame.Rect(x + w - 300, y + 100, 300, 62), tr("WEITER  ›"), "next")
        self.group = FocusGroup([self.p2name, self.next])

    def update(self, dt: float) -> None:
        self.p2name.update(dt)
        if self.osk:
            self.osk.update(dt)

    def handle_event(self, event: pygame.event.Event) -> None:
        if self.zurueck_geklickt(event):
            return True
        if self.osk:
            if self.osk.handle_event(event):
                self.osk = None
            return

        # Controller: A on the name field opens the on-screen keyboard.
        if (event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN
                and self.group.focused is self.p2name and gamepad.using_pad()):
            self.osk = OnScreenKeyboard(self.p2name, on_done=lambda: setattr(self.group, "index", 1))
            return

        action = self.group.handle_event(event)
        if action == "next" or (event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN and self.group.focused is not self.p2name):
            self._advance()

    def _advance(self) -> None:
        name_val = self.p2name.text.strip()
        ok, m = profile.validate_username(name_val)
        if not ok:
            self.msg = tr("Spieler 2: ") + m
            return

        s = race_setup.current()
        s.player2_name = name_val
        self.shell.push_page(MPLobbyPage())

    def draw(self, screen: pygame.Surface, area: pygame.Rect) -> None:
        self.zurueck_zeichnen(screen, area)
        # Titel zurück nach links gerückt — der Zurück-Knopf sitzt jetzt unten links,
        # nicht oben links. Der alte x=290-Versatz war nur nötig, um Platz zu schaffen.
        theme.text(screen, tr("MEHRSPIELER LOKAL — ANMELDUNG"), theme.HEADER, theme.ACCENT, (80, 120))
        theme.text(screen, tr("Wer spielt mit?"), theme.TITLE, theme.TEXT, (80, 180))
        theme.text(screen, tr("Gib den Namen für Spieler 2 ein:"), theme.BODY, theme.TEXT_DIM, (80, 260))

        theme.text(screen, tr("Spieler 2 (Name)"), theme.HINT, theme.TEXT_DIM,
                   (self.p2name.rect.x, self.p2name.rect.y - 30))
        self.group.draw(screen)
        if self.osk:
            self.osk.draw(screen)
        if self.msg:
            theme.text(screen, tr(self.msg), theme.BODY, theme.DANGER, (area.centerx, area.bottom - 84), center=True)

        from src.ui import hints
        theme.text(screen, hints.bar(("confirm", tr("Weiter")), ("back", tr("Zurück"))),
                   theme.HINT, theme.TEXT_DIM, (area.centerx, area.bottom - 40), center=True)
