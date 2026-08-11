"""Grand-Prix-Übersicht ohne Netz — Einzelspieler und lokaler Mehrspieler.

Dieselbe Ebene wie online, nur ohne Mitspieler, auf die man warten müsste:
zwischen den Läufen steht die Serie hier, hier wird die nächste Strecke
gewählt, und hier endet sie mit der Siegerehrung.

Warum eine eigene Seite statt der Online-Seite mit abgeschaltetem Netz: die
Online-Seite ist eine Sitzung mit Rollen, Bereit-System und verteiltem Zustand.
Offline gibt es davon nichts — jeder dieser Teile müsste durchgehend geprüft
werden, ob er gerade gilt. Geteilt wird deshalb das Zeichnen (``GPOverview``),
nicht der Ablauf.

Im lokalen Mehrspieler entscheidet Spieler 1: Strecke, Start, Abbruch. Ein
zweiter Bereit-Schritt wäre sinnlos, beide sitzen am selben Bildschirm.
"""
from __future__ import annotations

import pygame

from src.core import grand_prix, race_setup
from src.core.i18n import tr
from src.states.menu.gp_overview import GPOverview
from src.states.menu.page import Page
from src.ui import theme
from src.ui.focus import FocusGroup
from src.ui.widgets import Button, Dialog


class GPOverviewPage(Page):

    def enter(self, shell, **kwargs) -> None:
        self.shell = shell
        self._dialog: Dialog | None = None
        self._msg = ""
        self.ui = GPOverview()

        s = race_setup.current()
        key = self.ui.key_for_path(s.track_path)
        if key and key in self.ui.keys:
            self.ui.cursor = self.ui.keys.index(key)
            self.ui.move(0)
        else:
            # Ohne gültige Vorauswahl steht der Cursor auf der ersten Strecke —
            # und die ist dann auch gewählt, nicht bloß angesehen.
            self._pick(self.ui.cursor)

        y = 960
        self._btn_start = Button(pygame.Rect(700, y, 340, 60),
                                 tr("Rennen starten") + "  ›", "start")
        self._btn_leave = Button(pygame.Rect(380, y, 300, 60),
                                 tr("Grand Prix beenden"), "gp_leave",
                                 style="secondary")
        self.group = FocusGroup([self._btn_start, self._btn_leave], vertical=False)
        self._rebuild_group()

    # ── Zustand ──────────────────────────────────────────────────────────────

    def _serie(self):
        return grand_prix.current()

    def _ist_beendet(self) -> bool:
        gp = self._serie()
        return bool(gp and gp.is_finished)

    def _gp_view(self) -> dict:
        """Derselbe Datensatz, den online der Host verteilt.

        Die Anzeige liest damit offline wie online aus einer Quelle — sonst
        müsste ``GPOverview`` zwei Wege kennen und beide könnten auseinander
        laufen, ohne dass es auffällt.
        """
        gp = self._serie()
        if not gp:
            return {}
        return {
            "gp_active": True,
            "gp_finished": gp.is_finished,
            "gp_race": gp.race_index + 1,
            "gp_total": gp.races_total,
            "gp_raced": list(gp.raced_tracks),
            "gp_standings": [{"name": e["name"], "points": e["points"]}
                             for e in gp.get_standings()],
            "ai_roster": [{"name": d.name, "vehicle": d.vehicle}
                          for d in race_setup.current().ai_roster],
        }

    def _spieler(self) -> list[dict]:
        """Die Menschen am Bildschirm. Slots sind hier reine Anzeigenummern."""
        from src.core import profile
        s = race_setup.current()
        name = (profile.current().username or tr("Spieler")).strip()
        leute = [{"slot": 0, "name": name, "vehicle": s.player_vehicle}]
        if s.is_multiplayer:
            leute.append({"slot": 1, "name": tr("Spieler 2"),
                          "vehicle": s.player2_vehicle})
        return leute

    def _rebuild_group(self) -> None:
        if self._ist_beendet():
            self._btn_leave = Button(pygame.Rect(810, 960, 300, 60),
                                     tr("Grand Prix beenden"), "gp_leave")
            self.group = FocusGroup([self._btn_leave], vertical=False)
        else:
            self.group = FocusGroup([self._btn_start, self._btn_leave],
                                    vertical=False)

    # ── Bedienung ────────────────────────────────────────────────────────────

    def _pick(self, index: int) -> None:
        info = self.ui.tracks.get(self.ui.key_at(index) or "")
        if info:
            race_setup.current().track_path = info["path"]

    def handle_event(self, event: pygame.event.Event) -> bool | None:
        if self._dialog is not None:
            res = self._dialog.handle_event(event)
            if res == "ok":
                self._dialog = None
                self._beenden()
            elif res is not None:
                self._dialog = None
            return True

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self._frage_beenden()
            return True

        if not self._ist_beendet():
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_UP, pygame.K_w):
                self.ui.move(-1)
                self._pick(self.ui.cursor)
                return True
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_DOWN, pygame.K_s):
                self.ui.move(+1)
                self._pick(self.ui.cursor)
                return True
            if event.type == pygame.MOUSEWHEEL:
                # Blättern verschiebt nur die Ansicht, wie online.
                self.ui.scroll_by(-event.y)
                return True
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for i, rect in self.ui.tile_rects():
                    if rect.collidepoint(event.pos):
                        self.ui.cursor = i
                        self._pick(i)
                        return True

        aktion = self.group.handle_event(event)
        if aktion == "start":
            self._starten()
        elif aktion == "gp_leave":
            self._frage_beenden()
        return True

    def _startreihenfolge(self) -> list[str]:
        """Ganzes Feld nach dem Stand der Serie, Mensch wie KI."""
        gp = self._serie()
        if not gp or not gp.history:
            return []
        s = race_setup.current()
        feld = [p["name"] for p in self._spieler()] + [d.name for d in s.ai_roster]
        stand = [e["name"] for e in gp.get_standings()]
        return grand_prix.startreihenfolge(stand, feld)

    def _starten(self) -> None:
        s = race_setup.current()
        if not s.track_path:
            self._msg = tr("Bitte zuerst eine Strecke wählen.")
            return
        # Wie online: der Stand der Serie ist die Startaufstellung. Offline
        # rechnet dieselbe Funktion, damit beide Wege nicht auseinanderlaufen.
        gitter = self._startreihenfolge()
        leute = self._spieler()

        def platz(name: str):
            """Gitterplatz aus der Wertung, oder None fuer 'noch keiner'."""
            return gitter.index(name) if name in gitter else None

        # Spieler 2 braucht seinen eigenen Platz. Vorher bekam nur Spieler 1
        # einen, und das Rennen setzte den zweiten fest auf Gitterplatz 1 —
        # stand Spieler 1 laut Wertung ebenfalls dort, spawnten beide Autos
        # ineinander (gemeldet 31.07.2026, lokaler Mehrspieler-Grand-Prix).
        self.shell.state_machine.transition(
            "race", track_path=s.track_path, total_laps=s.laps,
            vehicle_config=s.player_vehicle,
            grid_slot=(platz(leute[0]["name"]) if gitter else None) or 0,
            grid_slot2=(platz(leute[1]["name"]) if (gitter and len(leute) > 1) else None),
            ai_grid_slots=([platz(d.name) for d in s.ai_roster] if gitter else None))

    def _frage_beenden(self) -> None:
        if self._ist_beendet():
            self._beenden()
            return
        self._dialog = Dialog(
            tr("Grand Prix beenden?"),
            tr("Der Zwischenstand geht verloren."),
            [(tr("Ja"), "ok"), (tr("Nein"), "cancel")])

    def _beenden(self) -> None:
        from src.states.menu.lobby_page import LobbyPage
        from src.states.menu.mp_lobby_page import MPLobbyPage
        s = race_setup.current()
        grand_prix.cancel()
        self.shell.tab = 1 if s.is_multiplayer else 0
        self.shell.page_stack = [MPLobbyPage() if s.is_multiplayer else LobbyPage()]
        self.shell.page_stack[-1].enter(self.shell)

    # ── Anzeige ──────────────────────────────────────────────────────────────

    def hides_tab_bar(self) -> bool:
        """Wie online: eine eigene Ebene, keine Menüseite. Ein Tabwechsel
        mitten in der Serie wäre ein stiller Abbruch."""
        return True

    def draw(self, screen: pygame.Surface, area: pygame.Rect) -> None:
        ansicht = self._gp_view()
        if self._ist_beendet():
            self.ui.draw_ceremony(screen, gp_view=ansicht,
                                  players=self._spieler(), eigener_slot=0)
        else:
            self.ui.draw(screen,
                         gewaehlt_key=self.ui.key_for_path(race_setup.current().track_path),
                         ist_host=True, gp_view=ansicht,
                         players=self._spieler(), eigener_slot=0, online=False)
        self.group.draw(screen)

        if self._msg:
            theme.text(screen, self._msg, theme.BODY, theme.DANGER,
                       (area.centerx, area.bottom - 120), center=True)
        if self._dialog is not None:
            self._dialog.draw(screen)
