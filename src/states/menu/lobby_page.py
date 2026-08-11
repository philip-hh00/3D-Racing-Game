from __future__ import annotations

import pygame

from src.states.menu.page import Page
from src.core import race_setup
from src.ui import theme
from src.ui.widgets import Stepper, Button
from src.ui.focus import FocusGroup
from src.entities.vehicle_factory import VehicleFactory
from src.core.i18n import tr


class LobbyPage(Page):
    #: Der Zurück-Knopf steht mit dem Inhalt auf einer Kante (x + 80); der Titel
    #: rückt dafür nach rechts und liest sich als Fortsetzung: „‹ Zurück  TITEL".
    ZURUECK_VERSATZ = (80, 16)
    #: Unten links: oben ist hier kein Platz (gemeldet 05.08.2026).
    ZURUECK_UNTEN = True

    def enter(self, shell, **kwargs) -> None:
        self.shell = shell
        self.msg = ""
        s = race_setup.current()
        s.is_multiplayer = False
        s._online = False          # clear any leftover online flag (else countdown skips)
        s.sync_ai_roster()

        x, w, h = 80, 800, 64
        y = 210
        gap = 20

        self.mode = Stepper(pygame.Rect(x, y, w, h), tr("Spielmodus"), race_setup.MODES,
                            race_setup.MODES.index(s.mode) if s.mode in race_setup.MODES else 0)

        count_opts = ["4", "6"] if s.mode == "Team-Zeitfahren" else [str(n) for n in range(2, 7)]
        if s.mode == "Team-Zeitfahren":
            if s.vehicle_count not in (4, 6):
                s.vehicle_count = 4
            count_idx = 0 if s.vehicle_count == 4 else 1
        else:
            count_idx = max(0, min(len(count_opts)-1, s.vehicle_count - 2))

        self.count = Stepper(pygame.Rect(x, y + (h + gap), w, h), tr("Fahrzeuge (inkl. dir)"),
                              count_opts, count_idx)
        self.klass = Stepper(pygame.Rect(x, y + 2 * (h + gap), w, h), tr("Fahrzeugklasse"),
                              [tr("Beliebig") if name == "Alle" else tr(name) for name in race_setup.CLASS_NAMES],
                              race_setup.CLASS_NAMES.index(s.vehicle_class))

        self.laps = Stepper(pygame.Rect(x, y + 3 * (h + gap), w, h), tr("Runden"),
                            [str(n) for n in range(1, 11)], s.laps - 1)
        self.gp_races = Stepper(pygame.Rect(x, y + 3 * (h + gap), w, h), tr("Strecken (Grand Prix)"),
                                [str(n) for n in range(3, 11)], 1) # default 4 races (index 1)
        self.gp_laps = Stepper(pygame.Rect(x, y + 4 * (h + gap), w, h), tr("Runden je Strecke"),
                               [str(n) for n in range(1, 6)], 2) # default 3 laps (index 2)
        self.diff = Stepper(pygame.Rect(x, y + 4 * (h + gap), w, h), tr("KI-Schwierigkeit"),
                            [tr(race_setup.DIFFICULTY_LABELS[k]) for k in race_setup.DIFFICULTY_KEYS],
                            race_setup.DIFFICULTY_KEYS.index(s.ai_difficulty))
        self.next = Button(pygame.Rect(x + w - 300, y + 5 * (h + gap) + 20, 300, 68),
                           tr("WEITER  ›"), "next")

        self.ai_widgets: list[Stepper] = []
        self.group = FocusGroup([])
        self._rebuild_ai_widgets()

    def _rebuild_ai_widgets(self) -> None:
        from src.core import race_setup
        s = race_setup.current()
        self.ai_widgets = []

        x, w, h = 80, 800, 64
        gap = 20

        is_team_mode = (self.mode.value == "Team-Zeitfahren")
        is_gp_mode = (self.mode.value == "Grand Prix")

        # Adjust count options based on mode
        if is_team_mode:
            if self.count.options != ["4", "6"]:
                self.count.options = ["4", "6"]
                self.count.index = 0 if s.vehicle_count <= 4 else 1
                s.vehicle_count = 4 if s.vehicle_count <= 4 else 6
        else:
            if self.count.options != [str(n) for n in range(2, 7)]:
                self.count.options = [str(n) for n in range(2, 7)]
                self.count.index = max(0, min(4, s.vehicle_count - 2))

        col = theme.Column(80, 210, gap=20)
        col.add(self.mode)

        if self.mode.value == "Zeitfahren":
            col.add(self.klass)
            col.skip(40)
            col.add(self.next)
            self.next.rect.x = 80 + 800 - 300
            s.vehicle_count = 1
            s.laps = 1
            self.group.set_widgets([self.mode, self.klass, self.next], keep_focus=True)
            return

        col.add(self.count)
        col.add(self.klass)

        if is_gp_mode:
            col.add(self.gp_races)
            col.add(self.gp_laps)
        else:
            col.add(self.laps)

        col.skip(20)
        col.add(self.next)
        self.next.rect.x = 80 + 800 - 300


        s.sync_ai_roster()

        ax = 960
        ay = 210
        h_row = 56
        gap_row = 12

        if is_team_mode:
            p1_team_idx = 0 if s.p1_team == "A" else 1
            self.p1_team_stepper = Stepper(
                pygame.Rect(ax + 200, ay, 160, h_row), "", [tr("Team A"), tr("Team B")], p1_team_idx, action="p1_team"
            )
            self.ai_widgets.append(self.p1_team_stepper)

        class_keys = list(s.class_keys())
        veh_labels = [tr("Zufällig")]
        veh_keys = ["random"]
        for k in class_keys:
            cfg = VehicleFactory.get_config(k)
            if cfg:
                veh_labels.append(cfg.name)
                veh_keys.append(k)

        diff_labels = [tr(race_setup.DIFFICULTY_LABELS[k]) for k in race_setup.DIFFICULTY_KEYS]
        diff_keys = race_setup.DIFFICULTY_KEYS

        ai_start_idx = 1 if is_team_mode else 0

        for i, driver in enumerate(s.ai_roster):
            row_y = ay + (i + ai_start_idx) * (h_row + gap_row)

            v_idx = veh_keys.index(driver.vehicle) if driver.vehicle in veh_keys else 0
            d_idx = diff_keys.index(driver.difficulty) if driver.difficulty in diff_keys else 1

            if is_team_mode:
                t_idx = 0 if driver.team == "A" else 1
                t_stepper = Stepper(pygame.Rect(ax + 200, row_y, 160, h_row), "", [tr("Team A"), tr("Team B")], t_idx, action=f"ai_team_{i}")
                v_stepper = Stepper(pygame.Rect(ax + 380, row_y, 240, h_row), "", veh_labels, v_idx, action=f"ai_veh_{i}")
                d_stepper = Stepper(pygame.Rect(ax + 640, row_y, 180, h_row), "", diff_labels, d_idx, action=f"ai_diff_{i}")

                t_stepper.driver_ref = driver
                v_stepper.driver_ref = driver
                v_stepper.veh_keys = veh_keys
                d_stepper.driver_ref = driver
                d_stepper.diff_keys = diff_keys

                self.ai_widgets.extend([t_stepper, v_stepper, d_stepper])
            else:
                v_stepper = Stepper(pygame.Rect(ax + 240, row_y, 320, h_row), "", veh_labels, v_idx, action=f"ai_veh_{i}")
                d_stepper = Stepper(pygame.Rect(ax + 580, row_y, 240, h_row), "", diff_labels, d_idx, action=f"ai_diff_{i}")

                v_stepper.driver_ref = driver
                v_stepper.veh_keys = veh_keys
                d_stepper.driver_ref = driver
                d_stepper.diff_keys = diff_keys

                self.ai_widgets.extend([v_stepper, d_stepper])

        if is_gp_mode:
            left_side_widgets = [self.mode, self.count, self.klass, self.gp_races, self.gp_laps]
        else:
            left_side_widgets = [self.mode, self.count, self.klass, self.laps]

        self.group.set_widgets(left_side_widgets + self.ai_widgets + [self.next], keep_focus=True)

    def handle_event(self, event: pygame.event.Event) -> None:
        if self.zurueck_geklickt(event):
            return True
        action = self.group.handle_event(event)

        s = race_setup.current()
        old_count = s.vehicle_count
        old_class = s.vehicle_class
        old_mode = s.mode

        s.mode = race_setup.MODES[self.mode.index]

        # Handle steppers in ai_widgets dynamically by matching action
        stepper = next((w for w in self.ai_widgets if isinstance(w, Stepper) and w.action == action), None)
        if stepper:
            if action == "p1_team":
                s.p1_team = "A" if stepper.index == 0 else "B"
            elif action.startswith("ai_team_"):
                stepper.driver_ref.team = "A" if stepper.index == 0 else "B"
            elif action.startswith("ai_veh_"):
                stepper.driver_ref.vehicle = stepper.veh_keys[stepper.index]
            elif action.startswith("ai_diff_"):
                stepper.driver_ref.difficulty = stepper.diff_keys[stepper.index]

        # Clear error message on any interaction
        if action:
            self.msg = ""

        if s.mode == "Zeitfahren":
            s.vehicle_count = 1
            s.laps = 1
        elif s.mode == "Grand Prix":
            s.vehicle_count = int(self.count.value)
            s.laps = int(self.gp_laps.value)
        else:
            s.vehicle_count = int(self.count.value)
            s.laps = int(self.laps.value)
        s.vehicle_class = race_setup.CLASS_NAMES[self.klass.index]

        if s.mode != old_mode or s.vehicle_count != old_count or s.vehicle_class != old_class:
            s.sync_ai_roster()
            self._rebuild_ai_widgets()

        if action == "next":
            self._commit_and_advance()

    def _commit_and_advance(self) -> None:
        s = race_setup.current()
        if race_setup.MODES[self.mode.index] not in race_setup.MODES_ENABLED:
            return
        s.mode = race_setup.MODES[self.mode.index]
        s.is_multiplayer = False

        if s.mode == "Zeitfahren":
            s.vehicle_count = 1
            s.laps = 1
        elif s.mode == "Grand Prix":
            s.vehicle_count = int(self.count.value)
            s.laps = int(self.gp_laps.value)
            from src.core import grand_prix
            grand_prix.start_series(int(self.gp_races.value), int(self.gp_laps.value))
        else:
            s.vehicle_count = int(self.count.value)
            s.laps = int(self.laps.value)
            # Make sure no GP is left active
            from src.core import grand_prix
            grand_prix.cancel()

        s.vehicle_class = race_setup.CLASS_NAMES[self.klass.index]
        s.ai_difficulty = race_setup.DIFFICULTY_KEYS[self.diff.index]

        if s.mode == "Team-Zeitfahren":
            # Validate team balance
            team_a_count = (1 if s.p1_team == "A" else 0) + sum(1 for d in s.ai_roster if d.team == "A")
            team_b_count = (1 if s.p1_team == "B" else 0) + sum(1 for d in s.ai_roster if d.team == "B")
            expected = s.vehicle_count // 2
            if team_a_count != expected or team_b_count != expected:
                self.msg = tr("Teams müssen ausgeglichen sein ({a} vs {b}).").format(a=expected, b=expected)
                return

        self.shell.state_machine.transition("car_select")

    def draw(self, screen: pygame.Surface, area: pygame.Rect) -> None:
        self.zurueck_zeichnen(screen, area)
        # Titel zurück nach links gerückt — der Zurück-Knopf sitzt jetzt unten links,
        # nicht oben links. Der alte x=290-Versatz war nur nötig, um Platz zu schaffen.
        theme.text(screen, tr("EINZELSPIELER — LOBBY"), theme.HEADER, theme.ACCENT, (80, 128))
        theme.text(screen, tr("Stelle dein Rennen zusammen"), theme.BODY, theme.TEXT_DIM, (80, 178))

        s = race_setup.current()

        if s.mode != "Zeitfahren":
            ax = 960
            ay = 210
            h = 56
            gap = 12
            is_team = (s.mode == "Team-Zeitfahren")
            theme.text(screen, tr("TEAMS & KI") if is_team else tr("KI-FAHRER"), theme.HEADER, theme.ACCENT, (ax, 128))
            theme.text(screen, tr("Passe Teams und Fahrer-Optionen an") if is_team else tr("Passe Namen, Fahrzeuge und Stärke an"), theme.BODY, theme.TEXT_DIM, (ax + 4, 178))

            if is_team:
                from src.core import profile
                p1_name = profile.current().username or "SPIELER 1"
                p1_rect = pygame.Rect(ax, ay, 180, h)
                theme.text_fit(screen, p1_name, theme.BODY, (255, 165, 0), p1_rect, center=False)
                theme.text(screen, tr("Mensch"), theme.BODY, theme.TEXT_FAINT, (ax + 380, ay + 15))
                theme.text(screen, "—", theme.BODY, theme.TEXT_FAINT, (ax + 640, ay + 15))

                for i, driver in enumerate(s.ai_roster):
                    row_y = ay + (i + 1) * (h + gap)
                    dr_rect = pygame.Rect(ax, row_y, 180, h)
                    theme.text_fit(screen, driver.name, theme.BODY, theme.TEXT, dr_rect, center=False)
            else:
                for i, driver in enumerate(s.ai_roster):
                    row_y = ay + i * (h + gap)
                    dr_rect = pygame.Rect(ax, row_y, 220, h)
                    theme.text_fit(screen, driver.name, theme.BODY, theme.TEXT, dr_rect, center=False)
        else:
            # Draw descriptive Ghost card on the right
            ax = 960
            ay = 210
            panel_rect = pygame.Rect(ax, ay, 800, 360)
            pygame.draw.rect(screen, (30, 32, 40), panel_rect, border_radius=12)
            pygame.draw.rect(screen, theme.BORDER, panel_rect, 2, border_radius=12)

            theme.text(screen, tr("GHOST-MODUS (ZEITFAHREN)"), theme.HEADER, theme.ACCENT, (ax + 30, ay + 30))

            desc_lines = [
                "Fahre eine einzelne Runde auf Bestzeit gegen einen transparenten Ghost.",
                "Sollte noch keine Bestzeit existieren, wird beim ersten Start ein",
                "simulierter Erst-Ghost (Seed) generiert.",
                "",
                "Unterbietest du die Bestzeit, wird dein eigener Lauf als neuer",
                "Bestzeit-Ghost für diese Strecke gespeichert."
            ]
            for idx, line in enumerate(desc_lines):
                theme.text(screen, tr(line), theme.BODY, theme.TEXT, (ax + 30, ay + 90 + idx * 32))

        self.group.draw(screen)

        # Draw Modus-Erklärung box on the left
        desc_y = 550 if s.mode == "Zeitfahren" else 750
        desc_rect = pygame.Rect(80, desc_y, 800, 160)
        pygame.draw.rect(screen, (30, 32, 40), desc_rect, border_radius=8)
        pygame.draw.rect(screen, theme.BORDER, desc_rect, 1, border_radius=8)

        desc_text = tr(race_setup.MODE_DESCRIPTIONS.get(self.mode.value, ""))
        theme.text(screen, tr("MODUS-BESCHREIBUNG"), theme.LABEL, theme.ACCENT, (100, desc_y + 15))

        words = desc_text.split(" ")
        lines = []
        curr_line = ""
        for w in words:
            test_line = (curr_line + " " + w).strip()
            if len(test_line) < 65:
                curr_line = test_line
            else:
                lines.append(curr_line)
                curr_line = w
        if curr_line:
            lines.append(curr_line)

        for idx, line in enumerate(lines[:3]):
            theme.text(screen, line, theme.BODY, theme.TEXT, (100, desc_y + 55 + idx * 30))

        if self.msg:
            theme.text(screen, self.msg, theme.BODY, theme.DANGER, (area.centerx, area.bottom - 90), center=True)
        elif race_setup.MODES[self.mode.index] not in race_setup.MODES_ENABLED:
            theme.text(screen, tr("Dieser Modus ist noch nicht verfügbar (Coming Soon)"),
                       theme.HINT, theme.TEXT_FAINT, (area.centerx, area.bottom - 90), center=True)
        from src.ui import hints
        theme.text(screen, hints.bar(("confirm", tr("Weiter")), ("back", tr("Zurück"))),
                   theme.HINT, theme.TEXT_DIM, (area.centerx, area.bottom - 40), center=True)
