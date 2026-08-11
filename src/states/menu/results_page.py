"""Race results screen: standings table, podium, record banner and exits."""
from __future__ import annotations

import time

import pygame

from src.states.menu.page import Page
from src.core import race_setup
from src.ui import theme
from src.ui.widgets import Button
from src.ui.focus import FocusGroup
from src.core.i18n import tr

_MEDAL = {1: (255, 215, 0), 2: (200, 205, 215), 3: (205, 140, 80)}


def _fmt(t) -> str:
    if not t or t <= 0:
        return "—"
    m = int(t // 60)
    s = t - m * 60
    return f"{m}:{s:05.2f}" if m else f"{s:.2f}"


def get_sector_durations(sectors: list[float], total_time: float) -> list[float]:
    if not sectors:
        return [total_time]
    durations = [sectors[0]]
    for i in range(1, len(sectors)):
        durations.append(sectors[i] - sectors[i - 1])
    # The last checkpoint is normally the finish line (sectors[-1] == total).
    # Only add a trailing segment if it clearly isn't, so we don't emit a
    # phantom ~0 sector.
    if total_time - sectors[-1] > 0.05:
        durations.append(total_time - sectors[-1])
    return durations


#: Sekunden, die das Rennergebnis stehen bleibt, bevor es von selbst in die
#: Grand-Prix-Uebersicht wechselt. Wer frueher weiter will, drueckt einfach.
GP_RESULT_SECONDS = 30.0


class ResultsPage(Page):
    def __init__(self, results, race_config=None) -> None:
        self.rows = results or []
        self.meta = race_config or {}

    def enter(self, shell, **kwargs) -> None:
        self.shell = shell
        self._dialog = None
        self._scroll = 0
        self._rematch_sent = False
        self._status_msg = ""
        self._status_until = 0.0
        self._roster_at_results = 0
        self._restart_fired = False

        if self.meta.get("is_online"):
            from src.net import session
            lp = session.get_lobby_page()
            if lp is not None and session.get() is not None:
                # Allow the hidden lobby page to accept the next START while
                # we're still looking at results.
                lp.shell = self.shell
                lp._race_begun = False
                # Announce we're on the results screen and clear any stale vote,
                # then remember how many players are here now — a rematch is only
                # allowed while this exact set stays put.
                lp.enter_results_vote()
                self._roster_at_results = len(lp._players)

        from src.core.settings import SCREEN_WIDTH
        bw, gap = 340, 40
        total = 3 * bw + 2 * gap
        x0 = SCREEN_WIDTH // 2 - total // 2
        y = 940

        # Online fuehrt nur der Host die Serie - ein Gast hat kein
        # grand_prix.current(). Der verteilte Zustand liegt bei der Lobby-Seite,
        # die die Verbindung besitzt. Ohne das sieht der Gast ein normales
        # Rennergebnis ohne Punkte.
        self._gp_view = {}
        self._gp_wait_until = 0.0
        if self.meta.get("is_online"):
            from src.net import session as _sess
            lp = _sess.get_lobby_page()
            # Der Host hat die Punkte dieses Laufs gerade erst eingetragen
            # (race_state ruft add_race_results). Ohne dieses Nachreichen zeigte
            # die Ergebnisseite den Stand VOR dem Rennen: nach dem ersten Lauf
            # eine leere Tabelle, danach dauerhaft einen Lauf hinterher.
            if lp is not None and getattr(lp, "_is_host", False):
                from src.core import grand_prix as _gp
                if _gp.is_active():
                    lp._gp_view = lp._gp_settings_payload()
                    lp._push_settings()
            ansicht = getattr(lp, "_gp_view", None) if lp else None
            if isinstance(ansicht, dict) and ansicht.get("gp_active"):
                self._gp_view = ansicht
                self.meta["is_grand_prix"] = True

        # Online geht es zurueck in die Uebersicht, nicht in die Streckenauswahl.
        if self._gp_view:
            # Button ist bereits oben importiert - ein lokaler Import wuerde den
            # Namen fuer die ganze Funktion lokal machen und die anderen Zweige
            # mit UnboundLocalError sprengen.
            self._gp_wait_until = time.time() + GP_RESULT_SECONDS
            self.group = FocusGroup([
                Button(pygame.Rect(SCREEN_WIDTH // 2 - 220, y, 440, 64),
                       tr("Weiter zur Übersicht") + "  ›", "gp_overview")
            ], vertical=False)
            self.group.index = 0
        elif self.meta.get("is_grand_prix"):
            from src.core import grand_prix
            gp = grand_prix.current()
            if gp and gp.race_index < gp.races_total - 1:
                self.group = FocusGroup([
                    Button(pygame.Rect(SCREEN_WIDTH // 2 - 360, y, 340, 64), tr("Nächstes Rennen  ›"), "next_gp_race"),
                    Button(pygame.Rect(SCREEN_WIDTH // 2 + 20, y, 340, 64), tr("Grand Prix abbrechen"), "cancel_gp", style="secondary")
                ], vertical=False)
                self.group.index = 0
            else:
                self.group = FocusGroup([
                    Button(pygame.Rect(SCREEN_WIDTH // 2 - 170, y, 340, 64), tr("Grand Prix beenden  ›"), "finish_gp")
                ], vertical=False)
                self.group.index = 0
        else:
            self._btn_again = Button(pygame.Rect(x0, y, bw, 64), tr("Nochmal fahren"), "again", style="secondary")
            self.group = FocusGroup([
                self._btn_again,
                Button(pygame.Rect(x0 + bw + gap, y, bw, 64), tr("Zurück zur Lobby"), "lobby"),
                Button(pygame.Rect(x0 + 2 * (bw + gap), y, bw, 64), tr("Hauptmenü"), "menu", style="secondary"),
            ], vertical=False)
            self.group.index = 1

    def _gp_seconds_left(self) -> int:
        rest = self._gp_wait_until - time.time()
        return max(0, int(rest) + 1) if rest > 0 else 0

    def update(self, dt: float) -> None:
        # Online: keep the hidden lobby page pumping the network queue so a
        # guest sitting on the results screen still receives the host's next
        # track transfer and race start (otherwise those messages are lost).
        if self.meta.get("is_online"):
            from src.net import session
            lp = session.get_lobby_page()
            if lp is not None and session.get() is not None:
                lp.shell = self.shell
                lp.update(dt)
                # Frisch nachlesen statt einmal festhalten: die Lobby-Seite
                # ERSETZT ihr _gp_view bei jeder LOBBY_STATE. Ein Gast haette
                # sonst ewig den Stand gezeigt, der beim Oeffnen galt.
                ansicht = getattr(lp, "_gp_view", None)
                if isinstance(ansicht, dict) and ansicht.get("gp_active"):
                    self._gp_view = ansicht

        # Grand Prix online: das Ergebnis bleibt kurz stehen und wechselt dann
        # von selbst weiter. Sonst haengt die ganze Runde daran, dass jeder
        # einzeln wegklickt.
        if self._gp_wait_until:
            rest = self._gp_seconds_left()
            if self.group.widgets:
                self.group.widgets[0].label = (
                    tr("Weiter zur Übersicht") + f"  ({rest})  ›" if rest
                    else tr("Weiter zur Übersicht") + "  ›")
            if rest <= 0:
                self._gp_wait_until = 0.0
                self._go_to_gp_overview()
                self._update_rematch_button(lp)

    def _rematch_present_ok(self, lp) -> tuple[int, int, bool]:
        """(voted, total, present_ok). present_ok is True only while every
        player that was here when results opened is still on the results screen
        — a disconnect drops the count, a "back to lobby" drops on_results."""
        n, m, _rb, _rs2, all_present = lp.rematch_status()
        present_ok = all_present and m >= 2 and m >= self._roster_at_results
        return n, m, present_ok

    def _update_rematch_button(self, lp) -> None:
        btn = getattr(self, "_btn_again", None)
        if btn is None:
            return
        n, m, present_ok = self._rematch_present_ok(lp)
        if not present_ok:
            btn.label = tr("Nochmal fahren")
            btn.enabled = False
            btn.focusable = False
        elif self._rematch_sent:
            btn.label = tr("Bereit") + f" {theme.HAKEN}  ({n}/{m})"
            btn.enabled = False
            btn.focusable = False
        else:
            btn.label = tr("Nochmal fahren") + f"  ({n}/{m})"
            btn.enabled = True
            btn.focusable = True
        # The host is the single authority that fires the actual restart, and
        # only once the vote is unanimous AND everyone is still present. Guests
        # get pulled into the new race by the regular START flow (their results
        # screen keeps the network pumped via lp.update above).
        if (getattr(lp, "_is_host", False) and present_ok
                and n == m and not self._restart_fired):
            self._restart_fired = True
            self.shell.tab = 2
            lp.shell = self.shell
            lp.resume_after_race()
            self.shell.page_stack = [lp]
            lp.request_restart()

    def _set_status(self, msg: str) -> None:
        import time
        self._status_msg = msg
        self._status_until = time.time() + 4.0

    def handle_event(self, event: pygame.event.Event) -> None:
        if self._dialog is not None:
            res = self._dialog.handle_event(event)
            if res == "ok":
                from src.core import grand_prix
                grand_prix.cancel()
                if self.meta.get("is_online"):
                    self.shell.state_machine.transition(
                        "menu", reopen="online_lobby_resume")
                else:
                    self.shell.page_stack.clear()
                self._dialog = None
            elif res == "cancel":
                self._dialog = None
            return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button in (4, 5):
            self._scroll += 1 if event.button == 5 else -1
        elif event.type == pygame.MOUSEWHEEL:
            self._scroll -= event.y

        action = self.group.handle_event(event)
        if action == "again":
            s = race_setup.current()
            if self.meta.get("is_online"):
                from src.net import session
                lp = session.get_lobby_page()
                net_ok = lp is not None and session.get() is not None
                if net_ok:
                    # Unanimous vote: every player (host included) must press
                    # "Nochmal fahren", and only while everyone is still here.
                    _n, _m, present_ok = self._rematch_present_ok(lp)
                    if not present_ok:
                        self._set_status(
                            tr("Neustart nicht möglich – nicht alle sind im Ergebnis-Bildschirm."))
                        return
                    if not self._rematch_sent:
                        lp.send_rematch_ready()
                        self._rematch_sent = True
                    return          # stay on results; host fires once all voted
                action = "lobby"    # no session: behave as before
            elif s.is_multiplayer:
                self.shell.state_machine.transition("track_select", vehicle_config=s.player_vehicle)
            else:
                self.shell.state_machine.transition(
                    "race", vehicle_config=s.player_vehicle, track_path=s.track_path)
        if action == "lobby":
            from src.states.menu.lobby_page import LobbyPage
            from src.states.menu.mp_lobby_page import MPLobbyPage
            s = race_setup.current()
            if self.meta.get("is_online"):
                # Online race → back to the SAME lobby if it's still alive
                # (session kept through the race). Reuse the persisted lobby page
                # so we land in the roster, not the create/join screen.
                from src.net import session
                self.shell.tab = 2
                page = session.get_lobby_page()
                net = session.get()
                if page is not None and net is not None and net.connected:
                    page.shell = self.shell
                    # Leaving the results screen: drop our presence so the others
                    # can no longer start a rematch that would exclude us.
                    page.leave_results_vote()
                    page.resume_after_race()
                    self.shell.page_stack = [page]
                else:
                    if page is None:
                        from src.states.menu.online_lobby_page import OnlineLobbyPage
                        page = OnlineLobbyPage()
                        page.shell = self.shell
                        page.enter(self.shell)
                    else:
                        page.shell = self.shell
                        page._view = "entry"
                    if not page._msg:
                        page._msg = tr("Verbindung zur Lobby wurde getrennt.")
                    self.shell.page_stack = [page]
                return

            else:
                self.shell.tab = 1 if s.is_multiplayer else 0
                self.shell.page_stack = [MPLobbyPage() if s.is_multiplayer else LobbyPage()]
            self.shell.page_stack[-1].enter(self.shell)
        elif action == "menu":
            # Leaving to the main menu ends the online session/lobby.
            if self.meta.get("is_online"):
                from src.net import session
                lp = session.get_lobby_page()
                if lp is not None and session.get() is not None:
                    lp.leave_results_vote()
                session.clear()
            self.shell.page_stack.clear()
        elif action == "gp_overview":
            self._gp_wait_until = 0.0
            self._go_to_gp_overview()
        elif action == "next_gp_race":
            from src.core import grand_prix
            gp = grand_prix.current()
            if gp:
                gp.next_race()
                if self.meta.get("is_online"):
                    # Online zurueck in die Lobby, NICHT direkt in die
                    # Streckenauswahl: dort wuerde der Host ein lokales Rennen
                    # starten und auf Mitspieler warten, die noch in der Lobby
                    # sitzen. Er waehlt die Strecke in der Lobby und startet
                    # ueber den normalen Bereit-Ablauf, damit alle mitkommen.
                    self.shell.state_machine.transition(
                        "menu", reopen="online_lobby_resume")
                else:
                    # Offline geht es ebenfalls in die Uebersicht - dort steht
                    # der Zwischenstand und wird die naechste Strecke gewaehlt.
                    self.shell.state_machine.transition("menu", reopen="gp_overview")
        elif action == "cancel_gp":
            from src.ui.widgets import Dialog
            self._dialog = Dialog(
                tr("Grand Prix abbrechen?"),
                tr("Der Zwischenstand geht verloren."),
                [(tr("Ja"), "ok"), (tr("Nein"), "cancel")]
            )
        elif action == "finish_gp":
            from src.core import grand_prix
            if self.meta.get("is_online"):
                # Serie vorbei, aber die Lobby lebt weiter - dort steht die
                # Gruppe noch und kann etwas Neues starten.
                grand_prix.cancel()
                self.shell.state_machine.transition(
                    "menu", reopen="online_lobby_resume")
                return
            # Offline endet die Serie in der Uebersicht mit der Siegerehrung -
            # nicht wortlos in der Lobby. Abgeraeumt wird sie erst dort.
            self.shell.state_machine.transition("menu", reopen="gp_overview")

    def _go_to_gp_overview(self) -> None:
        """Zurueck in die Grand-Prix-Uebersicht.

        Der Serienzustand liegt beim Host; hier wird nur die Ebene gewechselt.
        """
        self.shell.state_machine.transition("menu", reopen="online_lobby_resume")

    def _draw_gp_online(self, screen: pygame.Surface, area: pygame.Rect) -> None:
        """Serienstand aus dem verteilten Zustand - fuer Host UND Gast gleich.

        Bewusst nicht aus grand_prix.current(): das haette nur der Host, und der
        Gast saehe weiter ein normales Rennergebnis ohne Punkte.
        """
        from src.net import payload
        # Fester rechter Block statt centerx+380: der lief mit 620 px Breite
        # ueber den Bildrand hinaus, die Spalte "Gesamt" war abgeschnitten.
        x = self.GP_SPALTE_X
        lauf = payload.as_int(self._gp_view.get("gp_race"), 1)
        gesamt = payload.as_int(self._gp_view.get("gp_total"), 1)

        theme.text(screen, tr("GRAND-PRIX-WERTUNG"), theme.HEADER, theme.ACCENT,
                   (x, 180))
        offen = max(0, gesamt - lauf)
        theme.text(screen, tr("Lauf {i} von {n} gefahren").format(i=lauf, n=gesamt),
                   theme.BODY, theme.TEXT_DIM, (x, 232))
        theme.text(screen, tr("Noch {n} Rennen") .format(n=offen) if offen
                   else tr("Letztes Rennen"), theme.HINT, theme.TEXT_FAINT, (x, 266))

        # Punkte fuer diesen Lauf: aus der Platzierung, damit auch der Gast sie
        # sieht, ohne dass der Host sie einzeln verteilen muss.
        from src.core.grand_prix import GP_POINTS
        punkte_lauf = {}
        for r in payload.dict_entries(self.rows):
            if r.get("dnf"):
                continue
            punkte_lauf[str(r.get("name", ""))] = GP_POINTS.get(
                payload.as_int(r.get("position"), 99), 0)

        y = 320
        for label, sx in ((tr("Rang"), x), (tr("Name"), x + 70),
                          (tr("Dieses Rennen"), x + 340), (tr("Gesamt"), x + 540)):
            theme.text(screen, label, theme.SMALL, theme.TEXT_FAINT, (sx, y))
        pygame.draw.line(screen, theme.BORDER, (x, y + 24), (x + self.GP_SPALTE_W, y + 24), 1)
        y += 40

        for rang, eintrag in enumerate(
                payload.dict_entries(self._gp_view.get("gp_standings"))[:6], start=1):
            name = str(eintrag.get("name", ""))
            eigen = any(r.get("is_player") and r.get("name") == name
                        for r in payload.dict_entries(self.rows))
            farbe = (255, 165, 0) if eigen else theme.TEXT
            theme.text(screen, f"{rang}.", theme.LABEL, theme.TEXT_FAINT, (x, y))
            theme.text_fit(screen, name, theme.LABEL, farbe,
                           pygame.Rect(x + 70, y - 4, 260, 30), center=False)
            zugewinn = punkte_lauf.get(name, 0)
            theme.text(screen, f"+{zugewinn}" if zugewinn else "—", theme.LABEL,
                       theme.SUCCESS if zugewinn else theme.TEXT_FAINT, (x + 340, y))
            theme.text(screen, str(payload.as_int(eintrag.get("points"), 0)),
                       theme.LABEL, farbe, (x + self.GP_SPALTE_W - 20, y), midright=True)
            y += 38

    def draw(self, screen: pygame.Surface, area: pygame.Rect) -> None:
        if self._gp_view:
            # Online-Grand-Prix: normale Rennergebnistabelle behalten und die
            # Serienwertung daneben stellen.
            self._draw_normal(screen, area)
            self._draw_gp_online(screen, area)
            self.group.draw(screen)
            return
        if self.meta.get("is_grand_prix"):
            self._draw_grand_prix(screen, area)
        elif self.meta.get("is_team_zeitfahren"):
            self._draw_team_zeitfahren(screen, area)
        elif self.meta.get("is_zeitfahren"):
            self._draw_zeitfahren(screen, area)
        else:
            self._draw_normal(screen, area)

        if self._dialog is not None:
            self._dialog.draw(screen)

    #: Wertungsspalte des Online-Grand-Prix. Sie steht rechts fest, damit die
    #: Rennergebnistabelle links davon ihre Breite kennt.
    GP_SPALTE_X, GP_SPALTE_W = 1250, 610

    def _tabellen_masse(self, eng: bool):
        """(linker Rand, Breite, Namensbreite, Bereit-Spalte, Spaltenköpfe).

        Zwei Sätze statt eines gerechneten: die weite Tabelle ist auf Lesbarkeit
        ausgelegt, die enge auf das, was neben der Serienwertung übrig bleibt.
        Beide enden vor GP_SPALTE_X bzw. vor dem Bildrand — geprüft in
        tests/test_results_layout.py.
        """
        if eng:
            return (60, 1140, 250,
                    1020,
                    [("PLATZ", 80), ("FAHRER", 170), ("FAHRZEUG", 460),
                     ("GESAMT", 700), ("BESTE RUNDE", 850)])
        return (360, 1300, 340,
                1660,
                [("PLATZ", 380), ("FAHRER", 520), ("FAHRZEUG", 900),
                 ("GESAMT", 1240), ("BESTE RUNDE", 1520)])

    def _draw_normal(self, screen: pygame.Surface, area: pygame.Rect) -> None:
        theme.text(screen, tr("ERGEBNIS"), theme.TITLE, theme.ACCENT, (area.centerx, 140), center=True)
        if self.meta.get("is_record"):
            theme.text(screen, tr("♦ NEUER REKORD!  Beste Runde ") + _fmt(self.meta.get("player_best")),
                       theme.HEADER, (255, 215, 0), (area.centerx, 210), center=True)

        # Neben der Serienwertung ist die halbe Breite weg. Die Tabelle ruecke
        # deshalb zusammen, statt unter der Wertung zu verschwinden - vorher
        # lagen "Beste Runde" und "Bereit" unter der Punktetabelle.
        eng = bool(self._gp_view)
        lx, breite, name_w, bereit_x, cols = self._tabellen_masse(eng)
        top = 280
        for label, x in cols:
            theme.text(screen, tr(label), theme.LABEL, theme.TEXT_DIM, (x, top))

        online_ready = None
        # Die Bereit-Spalte gehoert zur Revanche-Abstimmung. Im Grand Prix gibt
        # es die nicht - dort geht es in die Uebersicht weiter -, die Spalte
        # blieb also leer und nahm nur Platz weg.
        if self.meta.get("is_online") and not eng:
            theme.text(screen, tr("BEREIT"), theme.LABEL, theme.TEXT_DIM, (bereit_x, top))
            from src.net import session as _sess
            _lp = _sess.get_lobby_page()
            if _lp is not None:
                _n, _m, _ready_by, _raw_sorted, _all_present = _lp.rematch_status()
                # on_results per raw slot, so a player who left shows as "Raus".
                _present_by = {p.get("slot"): bool(p.get("on_results", False))
                               for p in _lp._players}
                online_ready = (_ready_by, _raw_sorted, _present_by)
        pygame.draw.line(screen, theme.BORDER, (lx, top + 34), (lx + breite, top + 34), 2)

        y = top + 50
        for row in self.rows[:6]:
            is_p = row.get("is_player")
            is_p2 = row.get("is_player2")
            hl = (255, 165, 0) if is_p else ((60, 150, 255) if is_p2 else None)
            rrect = pygame.Rect(lx, y - 4, breite, 56)
            if hl is not None:
                s = pygame.Surface(rrect.size, pygame.SRCALPHA)
                s.fill((*theme.PANEL_SEL, 200))
                screen.blit(s, rrect.topleft)
                pygame.draw.rect(screen, hl, rrect, 2, border_radius=6)
            pos = row.get("position", "-")
            pcol = _MEDAL.get(pos, theme.TEXT)
            dnf = row.get("dnf")
            name = str(row.get("name", ""))
            if row.get("ai_takeover") and not name.endswith(tr(" (KI)")) and "(KI)" not in name:
                name += f" {tr('(KI)')}"
            theme.text(screen, "DNF" if dnf else str(pos), theme.BODY,
                       theme.DANGER if dnf else pcol, (cols[0][1], y))
            theme.text_fit(screen, name, theme.BODY,
                           hl if hl is not None else theme.TEXT,
                           pygame.Rect(cols[1][1], y, name_w, 36))

            theme.text_fit(screen, str(row.get("vehicle", "")), theme.BODY, theme.TEXT_DIM,
                           pygame.Rect(cols[2][1], y, cols[3][1] - cols[2][1] - 20, 36))
            theme.text(screen, "—" if dnf else _fmt(row.get("finish_time")),
                       theme.BODY, theme.TEXT, (cols[3][1], y))
            theme.text(screen, _fmt(row.get("best_lap")), theme.BODY, theme.TEXT, (cols[4][1], y))

            if online_ready is not None:
                _rb, _rs2, _pb = online_ready
                r_slot = row.get("slot", -1)
                if isinstance(r_slot, int) and 0 <= r_slot < len(_rs2):
                    raw = _rs2[r_slot]
                    if not _pb.get(raw, True):
                        theme.text(screen, tr("Raus"), theme.BODY, theme.DANGER, (bereit_x, y))
                    elif _rb.get(raw):
                        theme.text(screen, f"{theme.HAKEN} " + tr("Bereit"), theme.BODY,
                                   (80, 220, 80), (bereit_x, y))
                    else:
                        theme.text(screen, tr("Warte…"), theme.BODY, theme.TEXT_DIM, (bereit_x, y))

            y += 62

        self.group.draw(screen)

        # Rematch status line, shown just above the buttons (never in the footer).
        if self._status_msg:
            import time
            if time.time() < self._status_until:
                theme.text(screen, self._status_msg, theme.BODY, theme.DANGER,
                           (area.centerx, 890), center=True)
            else:
                self._status_msg = ""

        from src.ui import hints
        theme.text(screen, hints.bar(("confirm", tr("Bestätigen"))),
                   theme.HINT, theme.TEXT_DIM, (area.centerx, 1030), center=True)

    def _draw_zeitfahren(self, screen: pygame.Surface, area: pygame.Rect) -> None:
        theme.text(screen, tr("ZEITFAHREN — ERGEBNIS"), theme.TITLE, theme.ACCENT, (area.centerx, 140), center=True)

        new_ghost = self.meta.get("new_ghost_saved", False)
        if new_ghost:
            theme.text(screen, tr("♦ NEUER REKORD!  NEUER GHOST GESPEICHERT! ♦"),
                       theme.HEADER, (255, 215, 0), (area.centerx, 210), center=True)
        else:
            ghost_driver = self.meta.get("ghost_driver", "Ghost")
            theme.text(screen, tr("Aktueller Ghost gehalten von: {d}").format(d=ghost_driver),
                       theme.HEADER, theme.TEXT_DIM, (area.centerx, 210), center=True)

        ghost_sectors = self.meta.get("ghost_sectors", [])
        ghost_lap_time = self.meta.get("ghost_lap_time", 9999.0)
        ghost_durations = get_sector_durations(ghost_sectors, ghost_lap_time)

        has_p2 = any(row.get("is_player2") for row in self.rows)

        def _fmt_sector(t: float | None) -> str:
            if t is None or t <= 0 or t >= 999.0:
                return "—"
            return f"{t:.2f}s"

        def _fmt_diff(d: float | None) -> tuple[str, tuple[int, int, int]]:
            if d is None:
                return "—", theme.TEXT_DIM
            if d < -0.0001:
                return f"-{abs(d):.2f}s", (0, 255, 120)
            elif d > 0.0001:
                return f"+{abs(d):.2f}s", (255, 50, 50)
            return "+0.00s", theme.TEXT_DIM

        top = 285
        if not has_p2:
            cols = [("SEKTOR", 420), ("DEINE ZEIT", 720), ("GHOST", 1020), ("DIFFERENZ", 1320)]
            for label, x in cols:
                theme.text(screen, tr(label), theme.LABEL, theme.TEXT_DIM, (x, top))
            pygame.draw.line(screen, theme.BORDER, (400, top + 34), (1520, top + 34), 2)

            p_row = next((r for r in self.rows if r.get("is_player")), None)
            p_durations = []
            if p_row and not p_row.get("dnf"):
                p_sectors = p_row.get("sectors", [])
                p_durations = get_sector_durations(p_sectors, p_row.get("finish_time", 9999.0))

            num_sectors = max(len(ghost_durations), len(p_durations)) if p_durations else len(ghost_durations)

            row_h = 56
            list_top = top + 55
            total_y = 858
            visible_top = list_top
            visible_bottom = total_y - 40
            max_visible = max(1, (visible_bottom - visible_top) // row_h)
            self._scroll = max(0, min(self._scroll, max(0, num_sectors - max_visible)))

            if self._scroll > 0:
                theme.text(screen, "...", theme.BODY, theme.TEXT_DIM, (420, visible_top - 30))

            for i in range(self._scroll, min(num_sectors, self._scroll + max_visible)):
                y = visible_top + (i - self._scroll) * row_h
                theme.text(screen, tr("Sektor {n}").format(n=i + 1), theme.BODY, theme.TEXT,(420, y))

                p_val = p_durations[i] if i < len(p_durations) else None
                g_val = ghost_durations[i] if i < len(ghost_durations) else None

                theme.text(screen, _fmt_sector(p_val), theme.BODY, theme.TEXT, (720, y))
                theme.text(screen, _fmt_sector(g_val), theme.BODY, theme.TEXT_DIM, (1020, y))

                if p_val is not None and g_val is not None:
                    diff_str, diff_col = _fmt_diff(p_val - g_val)
                    theme.text(screen, diff_str, theme.BODY, diff_col, (1320, y))
                else:
                    theme.text(screen, "—", theme.BODY, theme.TEXT_DIM, (1320, y))

            if self._scroll + max_visible < num_sectors:
                theme.text(screen, "...", theme.BODY, theme.TEXT_DIM, (420, visible_top + max_visible * row_h))

            if p_row:
                p_total = p_row.get("finish_time", 9999.0)
                pygame.draw.line(screen, theme.BORDER, (400, total_y - 10), (1520, total_y - 10), 1)

                theme.text(screen, tr("GESAMTZEIT"), theme.LABEL, theme.TEXT_DIM, (420, total_y))
                theme.text(screen, _fmt(p_total) if not p_row.get("dnf") else "DNF", theme.BODY, theme.TEXT, (720, total_y))
                theme.text(screen, _fmt(ghost_lap_time), theme.BODY, theme.TEXT_DIM, (1020, total_y))

                if not p_row.get("dnf"):
                    diff_str, diff_col = _fmt_diff(p_total - ghost_lap_time)
                    theme.text(screen, diff_str, theme.BODY, diff_col, (1320, total_y))
                else:
                    theme.text(screen, "—", theme.BODY, theme.TEXT_DIM, (1320, total_y))
        else:
            cols = [("SEKTOR", 380), ("SPIELER 1", 580), ("DIFF 1", 780),
                    ("SPIELER 2", 980), ("DIFF 2", 1180), ("GHOST", 1380)]
            for label, x in cols:
                theme.text(screen, tr(label), theme.LABEL, theme.TEXT_DIM, (x, top))
            pygame.draw.line(screen, theme.BORDER, (360, top + 34), (1560, top + 34), 2)

            p1_row = next((r for r in self.rows if r.get("is_player")), None)
            p2_row = next((r for r in self.rows if r.get("is_player2")), None)

            p1_durations = []
            if p1_row and not p1_row.get("dnf"):
                p1_durations = get_sector_durations(p1_row.get("sectors", []), p1_row.get("finish_time", 9999.0))

            p2_durations = []
            if p2_row and not p2_row.get("dnf"):
                p2_durations = get_sector_durations(p2_row.get("sectors", []), p2_row.get("finish_time", 9999.0))

            num_sectors = max(len(ghost_durations), len(p1_durations), len(p2_durations))

            row_h = 56
            list_top = top + 55
            total_y = 858
            visible_top = list_top
            visible_bottom = total_y - 40
            max_visible = max(1, (visible_bottom - visible_top) // row_h)
            self._scroll = max(0, min(self._scroll, max(0, num_sectors - max_visible)))

            if self._scroll > 0:
                theme.text(screen, "...", theme.BODY, theme.TEXT_DIM, (380, visible_top - 30))

            for i in range(self._scroll, min(num_sectors, self._scroll + max_visible)):
                y = visible_top + (i - self._scroll) * row_h
                theme.text(screen, tr("Sektor {n}").format(n=i + 1), theme.BODY, theme.TEXT,(380, y))

                g_val = ghost_durations[i] if i < len(ghost_durations) else None

                p1_val = p1_durations[i] if i < len(p1_durations) else None
                theme.text(screen, _fmt_sector(p1_val), theme.BODY, (255, 165, 0), (580, y))
                if p1_val is not None and g_val is not None:
                    diff_str, diff_col = _fmt_diff(p1_val - g_val)
                    theme.text(screen, diff_str, theme.BODY, diff_col, (780, y))
                else:
                    theme.text(screen, "—", theme.BODY, theme.TEXT_DIM, (780, y))

                p2_val = p2_durations[i] if i < len(p2_durations) else None
                theme.text(screen, _fmt_sector(p2_val), theme.BODY, (60, 150, 255), (980, y))
                if p2_val is not None and g_val is not None:
                    diff_str, diff_col = _fmt_diff(p2_val - g_val)
                    theme.text(screen, diff_str, theme.BODY, diff_col, (1180, y))
                else:
                    theme.text(screen, "—", theme.BODY, theme.TEXT_DIM, (1180, y))

                theme.text(screen, _fmt_sector(g_val), theme.BODY, theme.TEXT_DIM, (1380, y))

            if self._scroll + max_visible < num_sectors:
                theme.text(screen, "...", theme.BODY, theme.TEXT_DIM, (380, visible_top + max_visible * row_h))

            pygame.draw.line(screen, theme.BORDER, (360, total_y - 10), (1560, total_y - 10), 1)

            theme.text(screen, tr("GESAMTZEIT"), theme.LABEL, theme.TEXT_DIM, (380, total_y))

            if p1_row:
                p1_total = p1_row.get("finish_time", 9999.0)
                theme.text(screen, _fmt(p1_total) if not p1_row.get("dnf") else "DNF", theme.BODY, (255, 165, 0), (580, total_y))
                if not p1_row.get("dnf"):
                    diff_str, diff_col = _fmt_diff(p1_total - ghost_lap_time)
                    theme.text(screen, diff_str, theme.BODY, diff_col, (780, total_y))
                else:
                    theme.text(screen, "—", theme.BODY, theme.TEXT_DIM, (780, total_y))

            if p2_row:
                p2_total = p2_row.get("finish_time", 9999.0)
                theme.text(screen, _fmt(p2_total) if not p2_row.get("dnf") else "DNF", theme.BODY, (60, 150, 255), (980, total_y))
                if not p2_row.get("dnf"):
                    diff_str, diff_col = _fmt_diff(p2_total - ghost_lap_time)
                    theme.text(screen, diff_str, theme.BODY, diff_col, (1180, total_y))
                else:
                    theme.text(screen, "—", theme.BODY, theme.TEXT_DIM, (1180, total_y))

            theme.text(screen, _fmt(ghost_lap_time), theme.BODY, theme.TEXT_DIM, (1380, total_y))

        self.group.draw(screen)
        from src.ui import hints
        theme.text(screen, hints.bar(("confirm", tr("Bestätigen"))),
                   theme.HINT, theme.TEXT_DIM, (area.centerx, 1030), center=True)

    def _draw_team_zeitfahren(self, screen: pygame.Surface, area: pygame.Rect) -> None:
        theme.text(screen, tr("TEAM-ZEITFAHREN — ERGEBNIS"), theme.TITLE, theme.ACCENT, (area.centerx, 140), center=True)

        team_a_avg = self.meta.get("team_a_avg", 0.0)
        team_b_avg = self.meta.get("team_b_avg", 0.0)

        # Highlight winner
        if team_a_avg < team_b_avg:
            winner_text = tr("♦ SIEGER: TEAM A (ø {t}) ♦").format(t=_fmt(team_a_avg))
            winner_color = (255, 120, 0)
        elif team_b_avg < team_a_avg:
            winner_text = tr("♦ SIEGER: TEAM B (ø {t}) ♦").format(t=_fmt(team_b_avg))
            winner_color = (0, 140, 255)
        else:
            winner_text = tr("♦ UNENTSCHIEDEN (ø {t}) ♦").format(t=_fmt(team_a_avg))
            winner_color = (255, 215, 0)

        theme.text(screen, winner_text, theme.HEADER, winner_color, (area.centerx, 210), center=True)

        top = 280
        # Draw Team A Table on the left (x0 = 220, w = 700)
        ax = 220
        theme.text(screen, tr("TEAM A"), theme.HEADER, (255, 120, 0), (ax + 350, top), center=True)
        theme.text(screen, tr("Durchschnitt: {t}").format(t=_fmt(team_a_avg)), theme.BODY, theme.TEXT_DIM, (ax + 350, top + 34), center=True)

        cols_a = [("FAHRER", ax + 20), ("FAHRZEUG", ax + 300), ("ZEIT", ax + 540)]
        for label, x in cols_a:
            theme.text(screen, tr(label), theme.LABEL, theme.TEXT_DIM, (x, top + 80))
        pygame.draw.line(screen, theme.BORDER, (ax, top + 114), (ax + 700, top + 114), 2)

        # Draw Team B Table on the right (x0 = 1000, w = 700)
        bx = 1000
        theme.text(screen, tr("TEAM B"), theme.HEADER, (0, 140, 255), (bx + 350, top), center=True)
        theme.text(screen, tr("Durchschnitt: {t}").format(t=_fmt(team_b_avg)), theme.BODY, theme.TEXT_DIM, (bx + 350, top + 34), center=True)

        cols_b = [("FAHRER", bx + 20), ("FAHRZEUG", bx + 300), ("ZEIT", bx + 540)]
        for label, x in cols_b:
            theme.text(screen, tr(label), theme.LABEL, theme.TEXT_DIM, (x, top + 80))
        pygame.draw.line(screen, theme.BORDER, (bx, top + 114), (bx + 700, top + 114), 2)

        # Render rows
        y_a = top + 130
        y_b = top + 130

        # Sort rows by score_time
        sorted_rows = sorted(self.rows, key=lambda r: r.get("score_time", 9999.0))

        for row in sorted_rows:
            is_p = row.get("is_player")
            is_p2 = row.get("is_player2")
            hl = (255, 165, 0) if is_p else ((60, 150, 255) if is_p2 else None)

            team = row.get("team", "A")
            if team == "A":
                tx = ax
                ty = y_a
            else:
                tx = bx
                ty = y_b

            rrect = pygame.Rect(tx, ty - 4, 700, 50)
            if hl is not None:
                s = pygame.Surface(rrect.size, pygame.SRCALPHA)
                s.fill((*theme.PANEL_SEL, 200))
                screen.blit(s, rrect.topleft)
                pygame.draw.rect(screen, hl, rrect, 2, border_radius=6)

            dnf = row.get("dnf")
            name = str(row.get("name", ""))
            if row.get("ai_takeover") and not name.endswith(tr(" (KI)")) and "(KI)" not in name:
                name += f" {tr('(KI)')}"
            theme.text_fit(screen, name, theme.BODY, hl if hl is not None else theme.TEXT, pygame.Rect(tx + 20, ty, 260, 36))

            theme.text(screen, str(row.get("vehicle", "")), theme.BODY, theme.TEXT_DIM, (tx + 300, ty))
            
            time_str = "DNF" if dnf else _fmt(row.get("finish_time"))
            if dnf:
                time_str = f"DNF ({_fmt(row.get('score_time'))})"
            
            theme.text(screen, time_str, theme.BODY, theme.DANGER if dnf else theme.TEXT, (tx + 540, ty))

            if team == "A":
                y_a += 56
            else:
                y_b += 56

        self.group.draw(screen)
        from src.ui import hints
        theme.text(screen, hints.bar(("confirm", tr("Bestätigen"))),
                   theme.HINT, theme.TEXT_DIM, (area.centerx, 1030), center=True)

    def _draw_grand_prix(self, screen: pygame.Surface, area: pygame.Rect) -> None:
        from src.core import grand_prix
        gp = grand_prix.current()
        if not gp:
            return

        is_final = (gp.race_index == gp.races_total - 1)

        if is_final:
            theme.text(screen, tr("GRAND PRIX — FINALER STAND"), theme.TITLE, theme.ACCENT, (area.centerx, 100), center=True)
            standings = gp.get_standings()
            champion = standings[0]["name"] if standings else tr("Niemand")
            theme.text(screen, tr("♦ GLÜCKWUNSCH AN {n}! ♦").format(n=champion.upper()), theme.HEADER, (255, 215, 0), (area.centerx, 170), center=True)

            # Draw standings table on the left (x = 100, w = 600)
            tx = 100
            top = 260
            theme.text(screen, tr("GESAMTWERTUNG"), theme.HEADER, theme.TEXT, (tx + 300, top), center=True)
            pygame.draw.line(screen, theme.BORDER, (tx, top + 34), (tx + 600, top + 34), 2)

            cols = [("RANG", tx + 10), ("FAHRER", tx + 120), ("PUNKTE", tx + 480)]
            for label, x in cols:
                theme.text(screen, tr(label), theme.LABEL, theme.TEXT_DIM, (x, top + 50))
            pygame.draw.line(screen, theme.BORDER, (tx, top + 84), (tx + 600, top + 84), 1)

            y = top + 100
            for entry in standings[:6]:
                rank = entry["rank_idx"] + 1
                name = entry["name"]
                pts = entry["points"]
                
                # Check if this name is the player
                is_p = any(r.get("is_player") for r in self.rows if r.get("name") == name)
                is_p2 = any(r.get("is_player2") for r in self.rows if r.get("name") == name)
                hl = (255, 165, 0) if is_p else ((60, 150, 255) if is_p2 else None)

                rrect = pygame.Rect(tx, y - 4, 600, 50)
                if hl is not None:
                    s = pygame.Surface(rrect.size, pygame.SRCALPHA)
                    s.fill((*theme.PANEL_SEL, 200))
                    screen.blit(s, rrect.topleft)
                    pygame.draw.rect(screen, hl, rrect, 2, border_radius=6)

                pcol = _MEDAL.get(rank, theme.TEXT)
                theme.text(screen, str(rank), theme.BODY, pcol, (tx + 20, y))
                theme.text(screen, name, theme.BODY, hl if hl is not None else theme.TEXT, (tx + 120, y))
                theme.text(screen, tr("{p} Pkt").format(p=pts), theme.BODY, theme.TEXT,(tx + 480, y))
                y += 56

            # Draw Podium on the right (x0 = 800)
            # P1 (Gold), P2 (Silver), P3 (Bronze)
            # Find names and points
            p1_name = standings[0]["name"] if len(standings) > 0 else "—"
            p1_pts = standings[0]["points"] if len(standings) > 0 else 0
            
            p2_name = standings[1]["name"] if len(standings) > 1 else "—"
            p2_pts = standings[1]["points"] if len(standings) > 1 else 0

            p3_name = standings[2]["name"] if len(standings) > 2 else "—"
            p3_pts = standings[2]["points"] if len(standings) > 2 else 0

            from src.core.settings import SCREEN_WIDTH
            # Draw boxes
            # P2: x = 800, y = 500, w = 220, h = 300
            pygame.draw.rect(screen, (34, 38, 48), (800, 500, 220, 300), border_radius=8)
            pygame.draw.rect(screen, (200, 205, 215), (800, 500, 220, 300), 3, border_radius=8)
            theme.text(screen, "2", 120, (200, 205, 215), (910, 600), center=True)
            theme.text_fit(screen, p2_name, theme.HEADER, theme.TEXT, pygame.Rect(910 - 100, 395, 200, 40), center=True)
            theme.text(screen, tr("{p} Pkt").format(p=p2_pts), theme.BODY, theme.TEXT_DIM, (910, 450), center=True)

            # P1: x = 1060, y = 400, w = 240, h = 400
            pygame.draw.rect(screen, (46, 44, 34), (1060, 400, 240, 400), border_radius=8)
            pygame.draw.rect(screen, (255, 215, 0), (1060, 400, 240, 400), 4, border_radius=8)
            theme.text(screen, "1", 140, (255, 215, 0), (1180, 500), center=True)
            theme.text_fit(screen, p1_name, 52, (255, 215, 0), pygame.Rect(1180 - 110, 272, 220, 45), center=True)
            theme.text(screen, tr("{p} Pkt").format(p=p1_pts), theme.BODY, theme.TEXT_DIM, (1180, 340), center=True)

            # P3: x = 1340, y = 560, w = 220, h = 240
            pygame.draw.rect(screen, (38, 32, 28), (1340, 560, 220, 240), border_radius=8)
            pygame.draw.rect(screen, (205, 140, 80), (1340, 560, 220, 240), 3, border_radius=8)
            theme.text(screen, "3", 100, (205, 140, 80), (1450, 640), center=True)
            theme.text_fit(screen, p3_name, theme.HEADER, theme.TEXT, pygame.Rect(1450 - 100, 455, 200, 40), center=True)
            theme.text(screen, tr("{p} Pkt").format(p=p3_pts), theme.BODY, theme.TEXT_DIM, (1450, 510), center=True)

        else:
            theme.text(screen, tr("GRAND PRIX — ZWISCHENSTAND"), theme.TITLE, theme.ACCENT, (area.centerx, 140), center=True)
            theme.text(screen, tr("Rennen {i} / {n}").format(i=gp.race_index + 1, n=gp.races_total), theme.HEADER, theme.TEXT_DIM, (area.centerx, 200), center=True)

            GP_PTS = {1: 10, 2: 8, 3: 6, 4: 4, 5: 2, 6: 1}

            # Left Panel: Rennergebnis
            ax = 160
            top = 280
            theme.text(screen, tr("RENNERGEBNIS"), theme.HEADER, theme.TEXT, (ax + 380, top), center=True)
            pygame.draw.line(screen, theme.BORDER, (ax, top + 34), (ax + 760, top + 34), 2)

            cols_a = [("PLATZ", ax + 20), ("FAHRER", ax + 140), ("FAHRZEUG", ax + 360), ("ZEIT", ax + 540), ("PUNKTE", ax + 680)]
            for label, x in cols_a:
                theme.text(screen, tr(label), theme.LABEL, theme.TEXT_DIM, (x, top + 50))
            pygame.draw.line(screen, theme.BORDER, (ax, top + 84), (ax + 760, top + 84), 1)

            y = top + 100
            for row in self.rows[:6]:
                is_p = row.get("is_player")
                is_p2 = row.get("is_player2")
                hl = (255, 165, 0) if is_p else ((60, 150, 255) if is_p2 else None)

                rrect = pygame.Rect(ax, y - 4, 760, 50)
                if hl is not None:
                    s = pygame.Surface(rrect.size, pygame.SRCALPHA)
                    s.fill((*theme.PANEL_SEL, 200))
                    screen.blit(s, rrect.topleft)
                    pygame.draw.rect(screen, hl, rrect, 2, border_radius=6)

                pos = row.get("position", "-")
                pcol = _MEDAL.get(pos, theme.TEXT)
                dnf = row.get("dnf")
                
                theme.text(screen, "DNF" if dnf else str(pos), theme.BODY, theme.DANGER if dnf else pcol, (ax + 20, y))
                theme.text_fit(screen, str(row.get("name", "")), theme.BODY, hl if hl is not None else theme.TEXT, pygame.Rect(ax + 140, y, 200, 36))
                theme.text(screen, str(row.get("vehicle", "")), theme.BODY, theme.TEXT_DIM, (ax + 360, y))
                theme.text(screen, "—" if dnf else _fmt(row.get("finish_time")), theme.BODY, theme.TEXT, (ax + 540, y))
                
                pts_gained = GP_PTS.get(pos, 0) if not dnf else 0
                theme.text(screen, f"+{pts_gained}", theme.BODY, (0, 255, 120) if pts_gained > 0 else theme.TEXT_DIM, (ax + 680, y))

                y += 56

            # Right Panel: Gesamtwertung
            bx = 1000
            top = 280
            theme.text(screen, tr("GESAMTWERTUNG"), theme.HEADER, theme.TEXT, (bx + 380, top), center=True)
            pygame.draw.line(screen, theme.BORDER, (bx, top + 34), (bx + 760, top + 34), 2)

            cols_b = [("RANG", bx + 20), ("FAHRER", bx + 140), ("PUNKTE", bx + 500), ("TENDENZ", bx + 640)]
            for label, x in cols_b:
                theme.text(screen, tr(label), theme.LABEL, theme.TEXT_DIM, (x, top + 50))
            pygame.draw.line(screen, theme.BORDER, (bx, top + 84), (bx + 760, top + 84), 1)

            standings = gp.get_standings()
            y = top + 100
            for entry in standings[:6]:
                rank = entry["rank_idx"] + 1
                name = entry["name"]
                pts = entry["points"]
                change = entry.get("rank_change", 0)

                is_p = any(r.get("is_player") for r in self.rows if r.get("name") == name)
                is_p2 = any(r.get("is_player2") for r in self.rows if r.get("name") == name)
                hl = (255, 165, 0) if is_p else ((60, 150, 255) if is_p2 else None)

                rrect = pygame.Rect(bx, y - 4, 760, 50)
                if hl is not None:
                    s = pygame.Surface(rrect.size, pygame.SRCALPHA)
                    s.fill((*theme.PANEL_SEL, 200))
                    screen.blit(s, rrect.topleft)
                    pygame.draw.rect(screen, hl, rrect, 2, border_radius=6)

                pcol = _MEDAL.get(rank, theme.TEXT)
                theme.text(screen, str(rank), theme.BODY, pcol, (bx + 20, y))
                theme.text_fit(screen, name, theme.BODY, hl if hl is not None else theme.TEXT, pygame.Rect(bx + 140, y, 320, 36))
                theme.text(screen, tr("{p} Pkt").format(p=pts), theme.BODY, theme.TEXT,(bx + 500, y))

                if change > 0:
                    theme.text(screen, f"▲ {change}", theme.BODY, (0, 255, 120), (bx + 640, y))
                elif change < 0:
                    theme.text(screen, f"▼ {abs(change)}", theme.BODY, (255, 50, 50), (bx + 640, y))
                else:
                    theme.text(screen, "—", theme.BODY, theme.TEXT_DIM, (bx + 640, y))

                y += 56

        self.group.draw(screen)
        from src.ui import hints
        theme.text(screen, hints.bar(("confirm", tr("Bestätigen"))),
                   theme.HINT, theme.TEXT_DIM, (area.centerx, 1030), center=True)
