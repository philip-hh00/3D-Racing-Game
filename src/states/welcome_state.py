"""First-start screen: pick a driver name, then a short "So spielst du".

Shown only when no profile exists yet. Validates the name (length, characters,
blacklist) and, on success, saves the profile. The same widget is reused by
Settings → Allgemein for later name changes.

**Zwei Schritte, ein Zustand** (Block F2). Bis zum 05.08.2026 landete man nach
dem Namen ohne ein Wort im Hauptmenü — Steuerung, Werkstatt und Zeitfahren
musste jeder selbst finden. Jetzt kommt eine Karte mit Zeilen dazwischen.
Sie steht bewusst hier und nicht in einem eigenen Zustand: sie gehört zum
ersten Start und soll auch nur dann erscheinen. Die Tastenzeilen kommen aus
``keybindings``, nicht aus dem Text — wer seine Belegung geändert hat, liest
seine eigene.

Seit dem 05.08.2026 kommt eine siebte Zeile dazu, die nur sagt, WO man
Ankündigungen findet (Einstellungen → Info) — nicht, WAS gerade angekündigt
ist. Ein frisches Profil bekommt die zu diesem Zeitpunkt bestehenden
Ankündigungen ohnehin als gesehen markiert (siehe ``Profile.seed_seen_announcements``
in ``src/core/profile.py``); ein Erstnutzer soll nur wissen, wo künftige
landen, nicht mit der Sammlung der Vergangenheit begrüßt werden.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from src.states.base_state import BaseState
from src.core.settings import SCREEN_WIDTH, SCREEN_HEIGHT
from src.core import profile, gamepad
from src.ui import theme
from src.ui.widgets import TextInput, Button, OnScreenKeyboard
from src.core.i18n import tr

if TYPE_CHECKING:
    from src.core.state_machine import StateMachine


#: Erster Schritt: Fahrername. Zweiter: die Kurzanleitung.
SCHRITT_NAME = "name"
SCHRITT_HILFE = "hilfe"


def spielhinweise() -> list[tuple[str, str]]:
    """Die Zeilen der Kurzanleitung — (Überschrift, Erklärung).

    Als Funktion und nicht als Konstante, weil beides erst zur Laufzeit
    feststeht: die Übersetzung hängt an der gewählten Sprache, die Tastennamen
    an der eigenen Belegung.
    """
    from src.core import keybindings as kb
    lenken = f"{kb.key_name(kb.get('left'))} / {kb.key_name(kb.get('right'))}"
    gas = kb.key_name(kb.get("throttle"))
    bremse = kb.key_name(kb.get("brake"))
    hand = kb.key_name(kb.get("handbrake"))
    return [
        (tr("Fahren"), tr("{gas} Gas, {bremse} Bremse, {lenken} lenken, "
                          "{hand} Handbremse").format(
                              gas=gas, bremse=bremse, lenken=lenken, hand=hand)),
        (tr("Ziel"), tr("Alle Runden fahren und vor der KI über die Ziellinie.")),
        (tr("Zeitfahren"), tr("Eine Runde gegen deinen eigenen Ghost — der "
                              "graue Wagen ist deine Bestzeit.")),
        (tr("Werkstatt"), tr("Lackierung wählen. Neue Finishes schaltest du "
                             "durch Rennen, Siege und geschlagene Ghosts frei.")),
        (tr("Profil"), tr("Bestzeiten, Erfolge und wie weit du noch bist.")),
        (tr("Pause und zurück"), tr("ESC pausiert das Rennen und führt im Menü "
                                    "eine Ebene zurück.")),
        # Playtest-Fund 05.08.2026: nicht die Ankuendigungen selbst hierher
        # holen (das waere fuer den allerersten Start genau das Zuspammen, das
        # vermieden werden soll), sondern nur sagen, wo man sie spaeter findet.
        (tr("Ankündigungen"), tr("Neuigkeiten vom Server findest du unter "
                                 "Einstellungen → Info.")),
    ]


class WelcomeState(BaseState):
    def __init__(self, state_machine: StateMachine) -> None:
        super().__init__(state_machine)
        self.input: TextInput | None = None
        self.ok: Button | None = None
        self.osk: OnScreenKeyboard | None = None
        self.error = ""
        self._t = 0.0
        self.schritt = SCHRITT_NAME
        self.weiter: Button | None = None

    def enter(self, **kwargs) -> None:
        w = 640
        col = theme.Column(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 60, gap=20, align="center")
        self.input = TextInput(
            pygame.Rect(0, 0, w, 60),
            profile.current().username, max_len=profile.NAME_MAX,
            allowed=profile.NAME_ALLOWED,
        )
        self.ok = Button(
            pygame.Rect(0, 0, 260, 60),
            tr("Los geht's"), "ok",
        )
        col.add(self.input)
        col.add(self.ok)
        
        self.weiter = Button(
            pygame.Rect(SCREEN_WIDTH // 2 - 150, SCREEN_HEIGHT - 190, 300, 60),
            tr("Ab ins Menü"), "weiter",
        )

        gamepad.set_menu_translation(True)
        self.osk = None            # only opened when a controller user edits
        self.error = ""
        self.schritt = SCHRITT_NAME

    def handle_events(self, events: list[pygame.event.Event]) -> None:
        # Gamepad→key translation is injected globally by the game loop.
        if self.schritt == SCHRITT_HILFE:
            self._hilfe_ereignisse(events)
            return
        for e in events:
            if self.osk:
                if self.osk.handle_event(e):
                    self.osk = None
                continue
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_RETURN:
                    # Controller: A opens the on-screen keyboard; keyboard: submit.
                    if gamepad.using_pad():
                        self.osk = OnScreenKeyboard(self.input, on_done=self._confirm)
                    else:
                        self._confirm()
                elif e.key == pygame.K_ESCAPE:
                    pass
                else:
                    self.input.handle_key(e.key, e.unicode)
                    self.error = ""
            elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                if self.ok.rect.collidepoint(e.pos):
                    from src.core import sfx as _sfx
                    vorher = _sfx.klang_zaehler()
                    self._confirm()
                    # Auch ein abgelehnter Name ist eine Antwort: _confirm setzt
                    # dann self.error und klingt selbst nicht.
                    _sfx.klick_quittieren(event=e, zaehler_vorher=vorher,
                                          anlass="gesperrt" if self.error else "ausgeloest")

    def _hilfe_ereignisse(self, events: list[pygame.event.Event]) -> None:
        """Auf der Kurzanleitung führt jede Bestätigung weiter — auch ESC.

        Sie ist kein Dialog mit einer Wahl: es gibt nur einen Weg von hier, und
        wer sie nicht lesen will, soll nicht suchen müssen, wie er sie loswird.
        """
        for e in events:
            if e.type == pygame.KEYDOWN and e.key in (pygame.K_RETURN,
                                                      pygame.K_ESCAPE,
                                                      pygame.K_SPACE):
                self._ins_menue()
                return
            if (e.type == pygame.MOUSEBUTTONDOWN and e.button == 1
                    and self.weiter and self.weiter.rect.collidepoint(e.pos)):
                from src.core import sfx as _sfx
                vorher = _sfx.klang_zaehler()
                self._ins_menue()
                _sfx.klick_quittieren(event=e, zaehler_vorher=vorher)
                return

    def _ins_menue(self) -> None:
        self.state_machine.transition("menu")

    def _confirm(self) -> None:
        name = self.input.text.strip()
        ok, msg = profile.validate_username(name)
        if not ok:
            self.error = msg
            return
        # War vor dem Namen noch kein Profil da? Nur dann ist es die
        # Erstanlage, fuer die die bisherigen Ankuendigungen als gesehen
        # gelten sollen (Playtest 05.08.2026) — dieser Zustand wird nie fuer
        # eine spaetere Namensaenderung durchlaufen, aber die Pruefung
        # schuetzt trotzdem davor, dass ein bestehendes Profil beruehrt wird.
        neuanlage = not profile.current().exists()
        profile.set_username(name)
        if neuanlage:
            profile.current().seed_seen_announcements()
        # Der Name ist gespeichert — ab hier ist der Start abgeschlossen, auch
        # wenn jemand das Fenster auf der Kurzanleitung schliesst.
        self.schritt = SCHRITT_HILFE

    def update(self, dt: float) -> None:
        self._t += dt
        if self.input:
            self.input.update(dt)
        if self.osk:
            self.osk.update(dt)

    def render(self, screen: pygame.Surface) -> None:
        theme.draw_background(screen)
        screen.blit(theme.vignette((SCREEN_WIDTH, SCREEN_HEIGHT), 100), (0, 0))
        theme.draw_input_badge(screen, (SCREEN_WIDTH - 20, 20))
        from src.core.version import version_string
        theme.text(screen, version_string(), theme.HINT, theme.TEXT_FAINT,
                   (SCREEN_WIDTH - 20, SCREEN_HEIGHT - 20), midright=True)
        if self.schritt == SCHRITT_HILFE:
            self._hilfe_zeichnen(screen)
            return
        from src.ui import hints
        theme.text(screen, hints.bar(("confirm", tr("Bestätigen"))),
                   theme.HINT, theme.TEXT_DIM, (SCREEN_WIDTH // 2, SCREEN_HEIGHT - 60), center=True)

        theme.text(screen, tr("WILLKOMMEN"), theme.TITLE, theme.ACCENT,
                   (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 240), center=True)
        theme.text(screen, tr("Wähle deinen Fahrernamen"), theme.HEADER, theme.TEXT,
                   (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 140), center=True)

        self.input.draw(screen, focused=True)

        if self.osk:
            self.osk.draw(screen)
        else:
            self.ok.draw(screen, focused=True)

        if self.error:
            # Shift error position slightly depending on keyboard presence
            err_y = SCREEN_HEIGHT // 2 + 100 if self.osk else SCREEN_HEIGHT // 2 + 110
            theme.text(screen, tr(self.error), theme.BODY, theme.DANGER,
                       (SCREEN_WIDTH // 2, err_y), center=True)
        elif not self.osk:
            theme.text(screen, tr("{lo}–{hi} Zeichen · Buchstaben, Zahlen, _").format(lo=profile.NAME_MIN, hi=profile.NAME_MAX),
                       theme.HINT, theme.TEXT_DIM,
                       (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 110), center=True)

    # ------------------------------------------------------------------
    # Schritt 2: Kurzanleitung
    # ------------------------------------------------------------------
    def _hilfe_zeichnen(self, screen: pygame.Surface) -> None:
        from src.ui import hints
        mitte = SCREEN_WIDTH // 2
        theme.text(screen, tr("SO SPIELST DU"), theme.TITLE, theme.ACCENT,
                   (mitte, 150), center=True)
        theme.text(screen, tr("Hallo {name}! Das Wichtigste in sieben Zeilen.").format(
            name=profile.current().username), theme.HEADER, theme.TEXT,
            (mitte, 232), center=True)

        zeilen = spielhinweise()
        karte = pygame.Rect(mitte - 520, 300, 1040, 60 + len(zeilen) * 62)
        theme.panel(screen, karte, alpha=210)
        y = karte.y + 34
        for titel, text in zeilen:
            theme.text(screen, titel, theme.BODY, theme.ACCENT_DIM, (karte.x + 40, y))
            theme.text_fit(screen, text, theme.BODY, theme.TEXT,
                           pygame.Rect(karte.x + 300, y, karte.width - 340, 30))
            y += 62

        if self.weiter:
            self.weiter.draw(screen, focused=True)
        theme.text(screen, hints.bar(("confirm", tr("Weiter"))),
                   theme.HINT, theme.TEXT_DIM, (mitte, SCREEN_HEIGHT - 60), center=True)
        theme.text(screen, tr("Die Tastenbelegung steht später unter Einstellungen → Steuerung."),
                   theme.HINT, theme.TEXT_FAINT, (mitte, SCREEN_HEIGHT - 100), center=True)
