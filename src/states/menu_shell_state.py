"""MenuShell — the top-level menu with the tab bar and per-tab backgrounds.

Structure:
    top level        the five tabs; ←/→ switches (background crossfades), ENTER
                     opens a tab, ESC asks to quit.
    inside a tab     the tab bar stays visible but dimmed; a Page fills the
                     content area; ESC goes one level up. Some tabs hand off to a
                     full game state instead (race, editor, labs).

Backgrounds live in data/menu/<name>.png; a gradient fallback is drawn when a
file is missing so the game never breaks on absent art.
"""
from __future__ import annotations

import math
import os
from typing import TYPE_CHECKING

import pygame

from src.states.base_state import BaseState
from src.core.settings import SCREEN_WIDTH, SCREEN_HEIGHT
from src.core import display
from src.ui import theme
from src.ui.widgets import Dialog
from src.core.i18n import tr
from src.net import server_info
from src.states.menu.coming_soon_page import ComingSoonPage

if TYPE_CHECKING:
    from src.core.state_machine import StateMachine

TAB_H = 108

# (display label, background image stem, kind)
_TABS = [
    ("EINZELSPIELER",      "Einzelspieler",       "single"),
    ("MEHRSPIELER LOKAL",  "Mehrspieler_Lokal",   "mp_local"),
    ("MEHRSPIELER ONLINE", "Mehrspieler_Online",  "online"),
    ("STRECKENEDITOR",     "Streckeneditor",      "editor"),
    ("WERKSTATT",          "Werkstatt",           "werkstatt"),
    ("PROFIL",             "Profil",              "profil"),
    ("EINSTELLUNGEN",      "Einstellungen",       "settings"),
]

#: Index des Werkstatt-Tabs — gebraucht vom Kurzweg aus der Fahrzeugauswahl.
TAB_WERKSTATT = 4
#: Index des Editor-Tabs. Der Streckeneditor ist ein eigener Zustand, keine
#: Seite in dieser Schale, und muss seinen eigenen Tab hervorheben können.
TAB_EDITOR = 3


def tab_rects() -> list[pygame.Rect]:
    """Die Kästen der Menüleiste. **Die** Stelle, an der sie gerechnet werden.

    Die Breite kommt aus der Anzahl, nicht aus einer Konstante. Vorher standen
    hier feste 288 px; mit dem siebten Tab (PROFIL) wäre die Leiste 2064 px breit
    geworden und über den Bildrand gelaufen. ``theme.text_fit`` kürzt, was in der
    jeweiligen Sprache nicht passt.
    """
    n = len(_TABS)
    th, gap = 60, 8
    rand = 40
    tw = min(288, (SCREEN_WIDTH - 2 * rand - (n - 1) * gap) // n)
    total = n * tw + (n - 1) * gap
    x0 = SCREEN_WIDTH // 2 - total // 2
    y = 28
    return [pygame.Rect(x0 + i * (tw + gap), y, tw, th) for i in range(n)]


def tab_leiste_zeichnen(screen: pygame.Surface, aktiv: int, *,
                        gedimmt: bool = False) -> None:
    """Die Menüleiste zeichnen, mit *aktiv* hervorgehoben.

    Als Funktion und nicht als Methode, weil der Streckeneditor ein eigener
    Zustand ist und dieselbe Leiste braucht. Er hatte sie bis zum 03.08.2026
    **abgeschrieben** — mit fünf festen Einträgen und 300 px Breite. Als Block D
    und E WERKSTATT und PROFIL ergänzten, zeigte er weiter die alte Leiste
    (gemeldet 03.08.2026). Kopierte Bedienelemente veralten leise; deshalb steht
    sie jetzt einmal hier.
    """
    for i, rect in enumerate(tab_rects()):
        active = (i == aktiv)
        if gedimmt:
            fill = (28, 30, 40, 180) if not active else (44, 40, 24, 200)
            border = theme.ACCENT_DIM if active else theme.BORDER
            txt = theme.TEXT_DIM if active else theme.TEXT_FAINT
        else:
            hover = rect.collidepoint(display.mouse_pos())
            fill = (58, 48, 20, 235) if active else (
                (40, 44, 56, 220) if hover else (26, 29, 38, 210))
            border = theme.ACCENT if active else theme.BORDER
            txt = theme.TEXT if (active or hover) else theme.TEXT_DIM
        surf = pygame.Surface(rect.size, pygame.SRCALPHA)
        surf.fill(fill)
        screen.blit(surf, rect.topleft)
        pygame.draw.rect(screen, border, rect, 2, border_radius=6)
        theme.text(screen, tr(_TABS[i][0]), theme.LABEL, txt, rect.center, center=True)


def _announcement_sort_key(entry: tuple[int, dict]) -> tuple:
    """Sortierschlüssel: neuestes Datum zuerst, bei Gleichstand Dateireihenfolge.

    Ein unlesbares oder fehlendes Datum darf eine Ankündigung nicht nach vorn
    schieben — sie landet hinten und wird nur gezeigt, wenn nichts Datiertes
    mehr offen ist.
    """
    idx, ann = entry
    roh = str(ann.get("date", "")).strip()
    try:
        jahr, monat, tag = (int(x) for x in roh.split("-"))
        datiert = (jahr, monat, tag)
    except (ValueError, TypeError):
        return (0, (0, 0, 0), -idx)
    return (1, datiert, -idx)


def newest_unseen_announcement(announcements, seen) -> dict | None:
    """Neueste noch nicht gesehene Ankündigung, oder None.

    Vorher wurde schlicht die erste ungesehene in Dateireihenfolge genommen —
    dadurch hing die Anzeige davon ab, in welcher Reihenfolge sie in
    live_config.json standen, nicht davon, welche die aktuellste ist.
    """
    kandidaten = [
        (i, a) for i, a in enumerate(announcements)
        if isinstance(a, dict) and a.get("id") and a["id"] not in seen
    ]
    if not kandidaten:
        return None
    kandidaten.sort(key=_announcement_sort_key, reverse=True)
    # Gesäubert, nicht roh: der Text kommt vom Relay und wird im Menü angezeigt
    # (Block H, H2.12). Bleibt nichts Anzeigbares übrig, wird die nächste
    # genommen — sonst öffnete sich ein leeres Fenster, das man wegklicken muss.
    from src.net import servertext
    for _i, eintrag in kandidaten:
        sauber = servertext.saeubere_ankuendigung(eintrag)
        if sauber is not None:
            return sauber
    return None


class MenuShellState(BaseState):
    def __init__(self, state_machine: StateMachine) -> None:
        super().__init__(state_machine)
        self.tab = 0
        self.page_stack: list = []
        self._quit_requested = False
        self._quit_dialog: Dialog | None = None
        # Hinweisfenster ohne Rueckfrage (z.B. unlesbare Strecke). Getrennt vom
        # Beenden-Dialog, damit sich beide nicht gegenseitig ueberschreiben.
        self._notice_dialog: Dialog | None = None

        self._time = 0.0
        self._fade = 1.0           # background crossfade progress (1 = settled)
        self._prev_tab = 0

        self._bg_cache: dict[str, pygame.Surface | None] = {}
        self._blur_cache: dict[str, pygame.Surface] = {}

        # Looping video background for the active tab (opened lazily, only one at
        # a time). Falls back to PNG, then gradient.
        self._video = None
        self._video_stem: str | None = None
        self._fade_from: pygame.Surface | None = None

        self._announcement: dict | None = None
        self._ann_ok_rect: pygame.Rect | None = None

    @property
    def quit_requested(self) -> bool:
        return self._quit_requested

    def rueckweg_kwargs(self) -> dict:
        """Ohne Argumente zurueckkommen: Tab und Seitenstapel stehen noch hier.

        Wer aus einem Vollbildzustand (Labor, Editor) zurueckkehrt, landet damit
        genau auf der Seite, von der er losgegangen ist — auch drei Ebenen tief.
        """
        return {}

    # ------------------------------------------------------------------
    def enter(self, **kwargs) -> None:
        self._quit_requested = False
        server_info.fetch_info_async()

        # Das Rennen hat abgebrochen, weil die Streckendatei unlesbar war.
        # Ohne Hinweis landet der Spieler kommentarlos wieder im Menue und
        # haelt das Spiel fuer kaputt.
        if kwargs.get("track_error"):
            self._notice_dialog = Dialog(
                tr("Strecke nicht ladbar"),
                tr("Die Streckendatei ist beschädigt oder unvollständig."),
                [(tr("OK"), "ok")],
            )

        tab_idx = kwargs.get("tab_idx")
        if tab_idx is not None:
            self.tab = tab_idx
            self.page_stack = []
            self._open_tab()
            return
        # Returning from a race with results → show the results page.
        results = kwargs.get("results")
        if results is not None:
            race_cfg = kwargs.get("race_config") or {}
            self.tab = 2 if race_cfg.get("is_online") else 0
            from src.states.menu.results_page import ResultsPage
            self.page_stack = [ResultsPage(results, race_cfg)]
            self.page_stack[-1].enter(self)
            return

        # Re-open a specific lobby (e.g. after leaving a selection screen).
        reopen = kwargs.get("reopen")
        if reopen == "mp_lobby":
            self.tab = 1
            from src.states.menu.mp_name_page import MPNamePage
            from src.states.menu.mp_lobby_page import MPLobbyPage
            p1 = MPNamePage()
            p2 = MPLobbyPage()
            self.page_stack = [p1, p2]
            p1.enter(self)
            p2.enter(self)
        elif reopen == "lobby":
            self.tab = 0
            from src.states.menu.lobby_page import LobbyPage
            self.page_stack = [LobbyPage()]
            self.page_stack[-1].enter(self)
        elif reopen == "online_lobby":
            self.tab = 2
            from src.net import session as _sess
            page = _sess.get_lobby_page()
            if page is not None:
                page.shell = self
                self.page_stack = [page]
                page.on_return_from_select()
            else:
                from src.states.menu.online_lobby_page import OnlineLobbyPage
                self.page_stack = [OnlineLobbyPage()]
                self.page_stack[-1].enter(self)

        elif reopen == "werkstatt":
            from src.states.menu.werkstatt_page import WerkstattPage
            self.tab = TAB_WERKSTATT
            seite = WerkstattPage()
            self.page_stack = [seite]
            seite.enter(self, vehicle_config=kwargs.get("vehicle_config"),
                        rueckweg=kwargs.get("rueckweg"))
            # rueckweg ist (Zustandsname, kwargs) — siehe WerkstattPage.

        elif reopen == "gp_overview":
            # Grand Prix ohne Netz: die Uebersicht fuehrt die Serie, genau wie
            # online. Der Tab richtet sich danach, wo die Serie herkommt.
            from src.states.menu.gp_overview_page import GPOverviewPage
            from src.core import race_setup as _rs
            self.tab = 1 if _rs.current().is_multiplayer else 0
            self.page_stack = [GPOverviewPage()]
            self.page_stack[-1].enter(self)

        elif reopen == "online_lobby_resume":
            self.tab = 2
            from src.net import session as _sess
            page = _sess.get_lobby_page()
            if page is not None and _sess.get() is not None:
                page.shell = self
                page.resume_after_race()
                # Grund der Rueckkehr anzeigen, sonst steht der Spieler ohne
                # Erklaerung wieder in der Lobby.
                hinweis = kwargs.get("lobby_msg")
                if hinweis:
                    page._msg = tr(hinweis)
                self.page_stack = [page]
            else:
                from src.states.menu.online_lobby_page import OnlineLobbyPage
                self.page_stack = [OnlineLobbyPage()]
                self.page_stack[-1].enter(self)

    # ------------------------------------------------------------------
    # Background handling
    # ------------------------------------------------------------------
    def _ensure_video(self, stem: str) -> None:
        """Open the video for *stem* (closing the previous one)."""
        if stem == self._video_stem:
            return
        if self._video is not None:
            self._video.close()
            self._video = None
        self._video_stem = stem
        path = os.path.join("data", "menu", f"{stem}.mp4")
        if os.path.isfile(path):
            # cv2 (opencv) may be unavailable (e.g. missing VC++ runtime on a
            # clean system). A failure here must never break the menu: fall back
            # to the PNG/gradient background so the tab bar still renders.
            try:
                from src.ui.video_player import VideoPlayer
                self._video = VideoPlayer(path, (SCREEN_WIDTH, SCREEN_HEIGHT))
                if not self._video.ok:
                    self._video = None
            except Exception:
                self._video = None

    def _current_frame(self, stem: str) -> pygame.Surface | None:
        """Live video frame if available, else the still image."""
        if stem == self._video_stem and self._video is not None:
            try:
                surf = self._video.get_surface()
            except Exception:
                surf = None
                self._video = None
            if surf is not None:
                return surf
        return self._bg(stem)

    def _goto_tab(self, i: int) -> None:
        """Switch to tab *i* with a crossfade from the current frame."""
        cur_stem = _TABS[self.tab][1]
        frame = self._current_frame(cur_stem)
        self._fade_from = frame.copy() if frame is not None else None
        self._prev_tab = self.tab
        self.tab = i
        self._fade = 0.0

    def _bg(self, stem: str) -> pygame.Surface | None:
        if stem not in self._bg_cache:
            path = os.path.join("data", "menu", f"{stem}.png")
            surf = None
            if os.path.isfile(path):
                try:
                    img = pygame.image.load(path).convert()
                    surf = pygame.transform.smoothscale(img, (SCREEN_WIDTH, SCREEN_HEIGHT))
                except Exception:
                    surf = None
            self._bg_cache[stem] = surf
        return self._bg_cache[stem]

    def _blurred(self, stem: str) -> pygame.Surface | None:
        """Darkened + cheaply blurred background for use behind a page."""
        if stem in self._blur_cache:
            return self._blur_cache[stem]
        base = self._bg(stem)
        if base is None:
            return None
        small = pygame.transform.smoothscale(base, (SCREEN_WIDTH // 12, SCREEN_HEIGHT // 12))
        blur = pygame.transform.smoothscale(small, (SCREEN_WIDTH, SCREEN_HEIGHT))
        dark = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        dark.fill((0, 0, 0, 150))
        blur.blit(dark, (0, 0))
        self._blur_cache[stem] = blur
        return blur

    def _draw_tab_background(self, screen: pygame.Surface) -> None:
        stem = _TABS[self.tab][1]
        self._ensure_video(stem)
        frame = self._current_frame(stem)
        in_page = bool(self.page_stack)

        if frame is None:
            # Gradient fallback (no video, no PNG).
            theme.draw_background(screen)
            if in_page:
                screen.blit(theme.vignette((SCREEN_WIDTH, SCREEN_HEIGHT), 90), (0, 0))
            else:
                theme.text(screen, tr(_TABS[self.tab][0]), theme.TITLE, theme.ACCENT_DIM,
                           (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2), center=True)
            return

        if in_page:
            screen.blit(frame, (0, 0))
            dark = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
            dark.fill((0, 0, 0, 150))
            screen.blit(dark, (0, 0))
            return

        # Top level: full frame with a crossfade from the snapshot.
        if self._fade < 1.0 and self._fade_from is not None:
            screen.blit(self._fade_from, (0, 0))
            fc = frame.copy()
            fc.set_alpha(int(255 * self._fade))
            screen.blit(fc, (0, 0))
        else:
            screen.blit(frame, (0, 0))
        screen.blit(theme.vignette((SCREEN_WIDTH, SCREEN_HEIGHT), 120), (0, 0))

    # ------------------------------------------------------------------
    # Tab bar
    # ------------------------------------------------------------------
    def _tab_rects(self) -> list[pygame.Rect]:
        return tab_rects()

    def _tabs_hidden(self) -> bool:
        """Ob die oberste Seite die Leiste für sich beansprucht (Page.hides_tab_bar).
        Gilt für Zeichnen UND Klicks — eine unsichtbare Leiste, die weiter Klicks
        schluckt, wäre schlimmer als eine sichtbare."""
        if not self.page_stack:
            return False
        return bool(getattr(self.page_stack[-1], "hides_tab_bar", lambda: False)())

    def _draw_tab_bar(self, screen: pygame.Surface) -> None:
        if self._tabs_hidden():
            return
        tab_leiste_zeichnen(screen, self.tab, gedimmt=bool(self.page_stack))

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def _content_area(self) -> pygame.Rect:
        return pygame.Rect(0, TAB_H, SCREEN_WIDTH, SCREEN_HEIGHT - TAB_H)

    def push_page(self, page) -> None:
        page.enter(self)
        self.page_stack.append(page)

    def pop_page(self) -> None:
        if self.page_stack:
            self.page_stack.pop()
            from src.core import sfx
            sfx.menue("zurueck")

    def zurueck_gehen(self) -> None:
        """Eine Ebene hoch. **Der** Rueckweg aus einer Seite heraus.

        Gemeldet am 04.08.2026: „In den Menues Lobbys usw. gibt es noch teilweise
        keine zurueck Buttons und der User ist auf ESC angewiesen (das fuehrt aber
        manchmal auch direkt zum Hauptmenue)." Jede Seite hat jetzt einen Knopf,
        und damit Knopf und Taste nie auseinanderlaufen, gehen beide hier durch.

        Eine Seite, die ihren Ausgang selbst kennt, meldet ``zurueck()``: die
        Werkstatt hat einen Kurzweg zurueck in die Fahrzeugauswahl, die
        Onlinelobby fragt vor dem Verlassen. Alle anderen nehmen den Stapel.
        """
        seite = self.page_stack[-1] if self.page_stack else None
        eigen = getattr(seite, "zurueck", None)
        if callable(eigen):
            eigen()
            return
        self.pop_page()

    def _switch_tab(self, d: int) -> None:
        self._goto_tab((self.tab + d) % len(_TABS))

    def _open_tab(self) -> None:
        kind = _TABS[self.tab][2]
        from src.core import race_setup
        s = race_setup.current()
        if kind == "single":
            s.is_multiplayer = False
            s.ai_roster.clear()
            s.sync_ai_roster()
            from src.states.menu.lobby_page import LobbyPage
            self.push_page(LobbyPage())
        elif kind == "mp_local":
            s.is_multiplayer = True
            s.ai_roster.clear()
            s.sync_ai_roster()
            from src.states.menu.mp_name_page import MPNamePage
            self.push_page(MPNamePage())
        elif kind == "online":
            from src.states.menu.online_lobby_page import OnlineLobbyPage
            self.push_page(OnlineLobbyPage())
        elif kind == "soon":
            self.push_page(ComingSoonPage(_TABS[self.tab][0].title()))
        elif kind == "editor":
            self.state_machine.transition("editor")
        elif kind == "werkstatt":
            from src.states.menu.werkstatt_page import WerkstattPage
            self.push_page(WerkstattPage())
        elif kind == "profil":
            from src.states.menu.profil_page import ProfilPage
            self.push_page(ProfilPage())
        elif kind == "settings":
            from src.states.menu.settings_page import SettingsPage
            self.push_page(SettingsPage())

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------
    def beenden_bestaetigen(self) -> None:
        """Rueckfrage vor dem Beenden des Spiels.

        Eine Stelle fuer beide Ausloeser (08.08.2026): ESC im Hauptmenue und der
        Beenden-Knopf unter Einstellungen > Allgemein. Zwei getrennt gebaute
        Dialoge wuerden frueher oder spaeter auseinanderlaufen.
        """
        self._quit_dialog = Dialog(tr("Beenden?"), tr("Spiel wirklich beenden?"),
                                   [(tr("Ja"), "yes"), (tr("Nein"), "no")])

    def handle_events(self, events: list[pygame.event.Event]) -> None:
        for event in events:
            if self._announcement is not None:
                ann = self._announcement
                if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                    from src.core import profile
                    profile.current().mark_announcement_seen(ann["id"])
                    self._announcement = None
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 \
                        and self._ann_ok_rect and self._ann_ok_rect.collidepoint(event.pos):
                    from src.core import profile
                    profile.current().mark_announcement_seen(ann["id"])
                    self._announcement = None
                continue

            if self._notice_dialog is not None:
                if self._notice_dialog.handle_event(event) is not None:
                    self._notice_dialog = None
                continue

            if self._quit_dialog is not None:
                res = self._quit_dialog.handle_event(event)
                if res == "yes":
                    self._quit_requested = True
                elif res is not None:
                    self._quit_dialog = None
                continue

            if self.page_stack:
                self._handle_page_event(event)
                continue

            # Top level
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_LEFT, pygame.K_a, pygame.K_PAGEUP):
                    self._switch_tab(-1)
                elif event.key in (pygame.K_RIGHT, pygame.K_d, pygame.K_PAGEDOWN):
                    self._switch_tab(+1)
                elif event.key == pygame.K_RETURN:
                    self._open_tab()
                elif event.key == pygame.K_ESCAPE:
                    self.beenden_bestaetigen()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                from src.core import sfx
                for i, rect in enumerate(self._tab_rects()):
                    if rect.collidepoint(event.pos):
                        vorher = sfx.klang_zaehler()
                        if i == self.tab:
                            self._open_tab()
                        else:
                            self._goto_tab(i)
                        sfx.klick_quittieren(event, vorher)
                        break

    def _tab_anspringen(self, i: int) -> None:
        """Aus einer Seite heraus in Tab *i* — der Kurzweg nach oben.

        Die Seite darf dazwischengehen (ungespeicherte Änderungen, offene
        Lobby): ``verlassen_erlaubt`` bekommt den Weg als Rückruf und entscheidet,
        ob er sofort gegangen wird oder erst nach einer Rückfrage.
        """
        def weiter() -> None:
            self.page_stack.clear()
            self._goto_tab(i)

        seite = self.page_stack[-1] if self.page_stack else None
        frage = getattr(seite, "verlassen_erlaubt", None)
        if callable(frage) and not frage(weiter):
            return
        weiter()

    def _handle_page_event(self, event: pygame.event.Event) -> None:
        # Die Tab-Leiste zuerst: was sichtbar ist, muss auch reagieren. Vorher
        # bekam die Seite den Klick zuerst, und Seiten, die jeden Klick
        # beantworten, machten die sichtbare Leiste damit tot (gemeldet
        # 02.08.2026). Seiten, in denen ein Tabwechsel nicht geht, blenden die
        # Leiste über hides_tab_bar() aus — sichtbar heißt jetzt benutzbar.
        if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                and not self._tabs_hidden()):
            from src.core import sfx as _sfx
            for i, rect in enumerate(self._tab_rects()):
                if rect.collidepoint(event.pos):
                    vorher = _sfx.klang_zaehler()
                    self._tab_anspringen(i)
                    _sfx.klick_quittieren(event, vorher)
                    return

        # Give page stack first priority to handle event (e.g. SettingsPage switches categories)
        from src.core import sfx
        vorher = sfx.klang_zaehler()
        consumed = self.page_stack[-1].handle_event(event)
        if consumed:
            # Jeder verarbeitete Klick wird quittiert, auch wenn die Seite ihre
            # eigenen Klickflaechen hat und deshalb nicht durch die FocusGroup
            # laeuft — Farbfelder, Kacheln, Pfeilknoepfe. Sonst bleibt jede neue
            # Seite still, bis jemand daran denkt (gemeldet 03.08.2026).
            sfx.klick_quittieren(event, vorher)
            return

        # If it's a PageUp/PageDown and was not consumed in SettingsPage, pop current page and switch main tabs
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_PAGEUP, pygame.K_PAGEDOWN):
            if not self._tabs_hidden():
                d = -1 if event.key == pygame.K_PAGEUP else 1
                self._tab_anspringen((self.tab + d) % len(_TABS))
                return

        # ESC geht eine Ebene hoch — denselben Weg, den der Zurück-Knopf der
        # Seite nimmt (siehe zurueck_gehen).
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.zurueck_gehen()
            return

    # ------------------------------------------------------------------
    def update(self, dt: float) -> None:
        self._time += dt
        if self._fade < 1.0:
            self._fade = min(1.0, self._fade + dt / 0.25)
        if self._video is not None:
            self._video.update(dt)
        if self.page_stack:
            self.page_stack[-1].update(dt)
        elif self._quit_dialog is None and self._announcement is None:
            info = server_info.get_cached()
            if info:
                from src.core import profile
                anns = info.get("announcements", [])
                prof = profile.current()
                # Erstinstallation: die Liste liegt hier zum ersten Mal vor
                # (beim Erstanlauf war der Servercache noch leer), also jetzt
                # stumm quittieren, bevor irgendetwas aufpoppt (08.08.2026).
                prof.ensure_announcements_seeded(anns)
                self._announcement = newest_unseen_announcement(
                    anns, prof.seen_announcements)

    def exit(self) -> None:
        # Free the video decoder when leaving the menu (e.g. into a race).
        if self._video is not None:
            self._video.close()
            self._video = None
            self._video_stem = None

    def render(self, screen: pygame.Surface) -> None:
        self._draw_tab_background(screen)
        self._draw_tab_bar(screen)

        if self.page_stack:
            self.page_stack[-1].draw(screen, self._content_area())
        else:
            from src.ui import hints
            pulse = 0.5 + 0.5 * math.sin(self._time * 3.0)
            open_lbl = hints.label("confirm")
            text_surf = theme.font(theme.HEADER).render(f"{open_lbl}   {tr('öffnen')}", True, theme.TEXT)

            # Pulse via per-pixel alpha multiply — set_alpha() on an SRCALPHA
            # surface renders as an opaque box on macOS.
            hint = text_surf.convert_alpha()
            alpha = int(120 + 135 * pulse)
            hint.fill((255, 255, 255, alpha), special_flags=pygame.BLEND_RGBA_MULT)

            screen.blit(hint, hint.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT - 120)))
            theme.text(screen, hints.bar(("tabs", tr("Wechseln")), ("back", tr("Beenden"))),
                       theme.HINT, theme.TEXT_DIM,
                       (SCREEN_WIDTH // 2, SCREEN_HEIGHT - 60), center=True)

        # Mode badge (top-right, below the tab bar).
        theme.draw_input_badge(screen, (SCREEN_WIDTH - 20, TAB_H + 12))

        if self._quit_dialog is not None:
            self._quit_dialog.draw(screen)

        if self._notice_dialog is not None:
            self._notice_dialog.draw(screen)

        if self._announcement is not None:
            ann = self._announcement
            from src.core.i18n import current as _lang
            lg = _lang()
            title = (ann.get("title") or {}).get(lg) or (ann.get("title") or {}).get("de") or ""
            text = (ann.get("text") or {}).get(lg) or (ann.get("text") or {}).get("de") or ""
            overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 190))
            screen.blit(overlay, (0, 0))
            bw = 900
            # word-wrapped body (handling newlines)
            font = theme.font(theme.BODY)
            paragraphs = text.split("\n")
            lines = []
            for p in paragraphs:
                words = p.split(" ")
                cur = ""
                for wd in words:
                    t2 = (cur + " " + wd).strip()
                    if font.size(t2)[0] > bw - 120 and cur:
                        lines.append(cur); cur = wd
                    else:
                        cur = t2
                if cur:
                    lines.append(cur)
                if not p:
                    lines.append("")
            
            # Limit display to max 12 lines to prevent going off-screen on low resolutions
            display_lines = lines[:12]
            bh = 140 + len(display_lines) * 34 + 110
            bx, by = SCREEN_WIDTH // 2 - bw // 2, SCREEN_HEIGHT // 2 - bh // 2
            
            theme.panel(screen, pygame.Rect(bx, by, bw, bh), alpha=245, border=theme.ACCENT, fill=(26, 28, 36))
            # Als **Servernachricht** gekennzeichnet (Block H, H2.12): der Text
            # kommt vom Relay, nicht vom Spiel. Ohne diese Zeile sieht ein
            # beliebiger Fremdtext aus wie eine Aussage des Spiels selbst.
            theme.text(screen, tr("ANKÜNDIGUNG") + " · " + tr("Servernachricht"),
                       theme.LABEL, theme.TEXT_DIM, (bx + bw // 2, by + 22),
                       center=True, max_w=bw - 80)
            theme.text(screen, title, theme.HEADER, theme.ACCENT, (bx + bw // 2, by + 58), center=True)
            if ann.get("date"):
                theme.text(screen, str(ann["date"]), theme.HINT, theme.TEXT_FAINT, (bx + bw // 2, by + 100), center=True)
            
            yy = by + 140
            for ln in display_lines:
                theme.text(screen, ln, theme.BODY, theme.TEXT, (bx + 60, yy)); yy += 34
            # OK button
            self._ann_ok_rect = pygame.Rect(bx + bw // 2 - 110, by + bh - 84, 220, 56)
            hover = self._ann_ok_rect.collidepoint(display.mouse_pos())
            pygame.draw.rect(screen, (70, 56, 22) if hover else (44, 38, 18), self._ann_ok_rect, border_radius=8)
            pygame.draw.rect(screen, theme.ACCENT_HOT if hover else theme.ACCENT, self._ann_ok_rect, 2, border_radius=8)
            theme.text(screen, tr("OK"), theme.BODY, theme.TEXT, self._ann_ok_rect.center, center=True)
