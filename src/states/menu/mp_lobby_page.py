"""Local multiplayer lobby: race settings + player 2 name + input devices.

Adds the second-player name (max 15 chars, same blacklist, remembered for the
session) and per-player input device choice on top of the standard race
settings. WEITER is blocked until the two players use different devices (and any
chosen controller is actually connected).
"""
from __future__ import annotations

import pygame

from src.states.menu.page import Page
from src.core import race_setup, profile, gamepad
from src.ui import theme
from src.ui.widgets import Stepper, Button
from src.ui.focus import FocusGroup
from src.core.i18n import tr
from src.entities.vehicle_factory import VehicleFactory


class MPLobbyPage(Page):
    #: Der Zurück-Knopf steht mit dem Inhalt auf einer Kante (x + 80); der Titel
    #: rückt dafür nach rechts und liest sich als Fortsetzung: „‹ Zurück  TITEL".
    ZURUECK_VERSATZ = (80, 16)
    #: Unten links: oben ist hier kein Platz (gemeldet 05.08.2026).
    ZURUECK_UNTEN = True

    def enter(self, shell, **kwargs) -> None:
        self.shell = shell
        self.msg = ""
        s = race_setup.current()
        s.is_multiplayer = True
        s._online = False          # clear any leftover online flag (else countdown skips)
        s.sync_ai_roster()

        x, w, h, gap = 80, 800, 56, 12
        y = 170

        def row(i):
            return pygame.Rect(x, y + i * (h + gap), w, h)

        self.mode = Stepper(row(0), tr("Spielmodus"), race_setup.MODES,
                            race_setup.MODES.index(s.mode) if s.mode in race_setup.MODES else 0)

        count_opts = (race_setup.feld_optionen(nur_gerade=True)
                      if s.mode == "Team-Zeitfahren"
                      else race_setup.feld_optionen())
        if s.mode == "Team-Zeitfahren":
            if str(s.vehicle_count) not in count_opts:
                s.vehicle_count = 4
            count_idx = count_opts.index(str(s.vehicle_count))
        else:
            count_idx = max(0, min(len(count_opts) - 1,
                                   s.vehicle_count - race_setup.FELD_MIN))

        self.count = Stepper(row(1), tr("Fahrzeuge (inkl. beide)"),
                             count_opts, count_idx)
        self.klass = Stepper(row(2), tr("Fahrzeugklasse"), [tr("Beliebig") if name == "Alle" else tr(name) for name in race_setup.CLASS_NAMES],
                              race_setup.CLASS_NAMES.index(s.vehicle_class))

        self.laps = Stepper(row(3), tr("Runden"), [str(n) for n in range(1, 11)], s.laps - 1)
        self.gp_races = Stepper(row(3), tr("Strecken (Grand Prix)"), [str(n) for n in range(3, 11)], 1)
        self.gp_laps = Stepper(row(4), tr("Runden je Strecke"), [str(n) for n in range(1, 6)], 2)
        self.diff = Stepper(row(4), tr("KI-Schwierigkeit"),
                            [tr(race_setup.DIFFICULTY_LABELS[k]) for k in race_setup.DIFFICULTY_KEYS],
                            race_setup.DIFFICULTY_KEYS.index(s.ai_difficulty))
        self._p1_row = row(5)
        self._p2_row = row(6)
        self._build_input_steppers(self._p1_row, self._p2_row)
        self.next = Button(pygame.Rect(x + w - 300, y + 7 * (h + gap) + 8, 300, 62), tr("WEITER  ›"), "next")

        self.ai_widgets: list[Stepper] = []
        self.group = FocusGroup([])
        self._rebuild_ai_widgets()

    def _build_input_steppers(self, r1, r2) -> None:
        s = race_setup.current()
        specs = race_setup.available_input_specs()
        self._input_specs = specs
        labels = [tr(race_setup.INPUT_LABELS[k]) for k in specs]
        def _idx(pref, fallback):
            return specs.index(pref) if pref in specs else fallback
        # Default: P1 keyboard (idx 0), P2 first controller if present else keyboard.
        p1_idx = _idx(s.p1_input, 0)
        p2_idx = _idx(s.p2_input, 1 if len(specs) > 1 else 0)
        self.p1in = Stepper(r1, tr("Steuerung Spieler 1"), labels, p1_idx)
        self.p2in = Stepper(r2, tr("Steuerung Spieler 2"), labels, p2_idx)
        self._dev_count = __import__("src.core.gamepad", fromlist=["device_count"]).device_count()

    def _rebuild_ai_widgets(self) -> None:
        from src.core import race_setup
        s = race_setup.current()
        self.ai_widgets = []

        is_team_mode = (self.mode.value == "Team-Zeitfahren")
        is_gp_mode = (self.mode.value == "Grand Prix")
        is_zf_mode = (self.mode.value == "Zeitfahren")

        x, w = 80, 800
        if is_gp_mode or is_team_mode:
            h, gap = 46, 8
        else:
            h, gap = 56, 12

        def row(i):
            return pygame.Rect(x, 170 + i * (h + gap), w, h)

        # Adjust count options based on mode
        if is_team_mode:
            gerade = race_setup.feld_optionen(nur_gerade=True)
            if self.count.options != gerade:
                self.count.options = gerade
                # Auf die naechstkleinere gerade Zahl im Feld runden.
                s.vehicle_count = max(4, s.vehicle_count - s.vehicle_count % 2)
                self.count.index = gerade.index(str(s.vehicle_count))
        else:
            alle = race_setup.feld_optionen()
            if self.count.options != alle:
                self.count.options = alle
                self.count.index = max(0, min(len(alle) - 1,
                                              s.vehicle_count - race_setup.FELD_MIN))

        for widget in (self.mode, self.count, self.klass, self.laps, self.gp_races, self.gp_laps, self.diff, self.p1in, self.p2in):
            widget.rect.height = h

        col = theme.Column(x, 170, gap=gap)
        col.add(self.mode)

        if is_zf_mode:
            col.add(self.klass)
            col.add(self.p1in)
            col.add(self.p2in)
            col.skip(8)
            self.next.rect.height = h + 6
            col.add(self.next)
            self.next.rect.x = x + w - 300
            s.vehicle_count = 2
            s.laps = 1
            self.group.set_widgets([self.mode, self.klass, self.p1in, self.p2in, self.next], keep_focus=True)
            return

        col.add(self.count)

        if is_gp_mode:
            col.add(self.klass)
            col.add(self.gp_races)
            col.add(self.gp_laps)
        else:
            col.add(self.klass)
            col.add(self.laps)

        col.add(self.p1in)
        col.add(self.p2in)
        col.skip(8)
        self.next.rect.height = h + 6
        col.add(self.next)
        self.next.rect.x = x + w - 300


        s.sync_ai_roster()

        ax = 960
        ay = 210
        h_row = 56
        gap_row = 12

        if is_team_mode:
            p1_team_idx = 0 if s.p1_team == "A" else 1
            p2_team_idx = 0 if s.p2_team == "A" else 1
            self.p1_team_stepper = Stepper(
                pygame.Rect(ax + 200, ay, 160, h_row), "", [tr("Team A"), tr("Team B")], p1_team_idx, action="p1_team"
            )
            self.p2_team_stepper = Stepper(
                pygame.Rect(ax + 200, ay + (h_row + gap_row), 160, h_row), "", [tr("Team A"), tr("Team B")], p2_team_idx, action="p2_team"
            )
            self.ai_widgets.extend([self.p1_team_stepper, self.p2_team_stepper])

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

        ai_start_idx = 2

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
            left_side_widgets = [
                self.mode, self.count, self.klass, self.gp_races, self.gp_laps,
                self.p1in, self.p2in
            ]
        else:
            left_side_widgets = [
                self.mode, self.count, self.klass, self.laps,
                self.p1in, self.p2in
            ]

        self.group.set_widgets(left_side_widgets + self.ai_widgets + [self.next], keep_focus=True)

    def update(self, dt: float) -> None:
        from src.core import gamepad
        if gamepad.device_count() != getattr(self, "_dev_count", 0):
            # remember current picks by spec, rebuild option lists, re-layout
            self._build_input_steppers(self._p1_row, self._p2_row)
            self._rebuild_ai_widgets()

    def handle_event(self, event: pygame.event.Event) -> None:
        if self.zurueck_geklickt(event):
            return True
        action = self.group.handle_event(event)
        foc = self.group.focused

        # Rumble a controller when it gets selected as a player's device.
        if action and foc in (getattr(self, "p1in", None), getattr(self, "p2in", None)):
            specs = getattr(self, "_input_specs", race_setup.INPUT_SPECS)
            if 0 <= foc.index < len(specs) and specs[foc.index].startswith("pad"):
                pad_idx = int(specs[foc.index][3:])
                if pad_idx < gamepad.device_count():
                    gamepad.rumble(pad_idx, 0.5, 0.5, 200)

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
            elif action == "p2_team":
                s.p2_team = "A" if stepper.index == 0 else "B"
            elif action.startswith("ai_team_"):
                stepper.driver_ref.team = "A" if stepper.index == 0 else "B"
            elif action.startswith("ai_veh_"):
                stepper.driver_ref.vehicle = stepper.veh_keys[stepper.index]
            elif action.startswith("ai_diff_"):
                stepper.driver_ref.difficulty = stepper.diff_keys[stepper.index]

        if action:
            self.msg = ""

        if s.mode == "Zeitfahren":
            s.vehicle_count = 2
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
            self._advance()

    def _advance(self) -> None:
        s = race_setup.current()
        chosen_mode = race_setup.MODES[self.mode.index]
        if chosen_mode not in race_setup.MODES_ENABLED:
            self.msg = tr("Dieser Modus ist noch nicht verfügbar.")
            return
        specs = getattr(self, "_input_specs", race_setup.INPUT_SPECS)
        if len(specs) < 2:
            self.msg = tr("Lokaler Mehrspieler braucht mindestens einen Controller.")
            return
        p1 = specs[self.p1in.index]
        p2 = specs[self.p2in.index]
        if p1 == p2:
            self.msg = tr("Beide Spieler brauchen unterschiedliche Geräte.")
            return
        for spec, who in ((p1, "Spieler 1"), (p2, "Spieler 2")):
            if spec.startswith("pad"):
                idx = int(spec[3:])
                if idx >= gamepad.device_count():
                    self.msg = tr("{dev} ({who}) ist nicht verbunden.").format(dev=tr(race_setup.INPUT_LABELS[spec]), who=tr(who))
                    return

        s.mode = chosen_mode
        s.is_multiplayer = True
        if s.mode == "Zeitfahren":
            s.vehicle_count = 2
            s.laps = 1
        elif s.mode == "Grand Prix":
            s.vehicle_count = int(self.count.value)
            s.laps = int(self.gp_laps.value)
            from src.core import grand_prix
            grand_prix.start_series(int(self.gp_races.value), int(self.gp_laps.value))
        else:
            s.vehicle_count = int(self.count.value)
            s.laps = int(self.laps.value)
            from src.core import grand_prix
            grand_prix.cancel()

        s.vehicle_class = race_setup.CLASS_NAMES[self.klass.index]
        s.p1_input = p1
        s.p2_input = p2

        if s.mode == "Team-Zeitfahren":
            # Validate team balance
            team_a_count = (1 if s.p1_team == "A" else 0) + (1 if s.p2_team == "A" else 0) + sum(1 for d in s.ai_roster if d.team == "A")
            team_b_count = (1 if s.p1_team == "B" else 0) + (1 if s.p2_team == "B" else 0) + sum(1 for d in s.ai_roster if d.team == "B")
            expected = s.vehicle_count // 2
            if team_a_count != expected or team_b_count != expected:
                self.msg = tr("Teams müssen ausgeglichen sein ({a} vs {b}).").format(a=expected, b=expected)
                return
            s.ai_difficulty = race_setup.DIFFICULTY_KEYS[self.diff.index]
        else:
            s.ai_difficulty = race_setup.DIFFICULTY_KEYS[self.diff.index]

        self.shell.state_machine.transition("car_select", picker="p1")

    def exit(self) -> None:
        race_setup.current().is_multiplayer = False

    def draw(self, screen: pygame.Surface, area: pygame.Rect) -> None:
        self.zurueck_zeichnen(screen, area)
        # Titel zurück nach links gerückt — der Zurück-Knopf sitzt jetzt unten links,
        # nicht oben links. Der alte x=290-Versatz war nur nötig, um Platz zu schaffen.
        theme.text(screen, tr("MEHRSPIELER LOKAL — LOBBY"), theme.HEADER, theme.ACCENT, (80, 120))

        s = race_setup.current()

        if s.mode != "Zeitfahren":
            ax = 960
            ay = 210
            h = 56
            gap = 12
            is_team = (s.mode == "Team-Zeitfahren")
            theme.text(screen, tr("TEAMS & KI") if is_team else tr("KI-FAHRER"), theme.HEADER, theme.ACCENT, (ax, 120))
            theme.text(screen, tr("Passe Teams und Fahrer-Optionen an") if is_team else tr("Passe Namen, Fahrzeuge und Stärke an"), theme.BODY, theme.TEXT_DIM, (ax + 4, 170))

            # Draw Human 1 & 2
            from src.core import profile
            p1_name = profile.current().username or "SPIELER 1"
            p1_rect = pygame.Rect(ax, ay, 180, h)
            theme.text_fit(screen, p1_name, theme.BODY, (255, 165, 0), p1_rect, center=False)

            p2_name = s.player2_name or tr("Spieler_2")
            p2_rect = pygame.Rect(ax, ay + (h + gap), 180, h)
            theme.text_fit(screen, p2_name, theme.BODY, (60, 150, 255), p2_rect, center=False)

            if is_team:
                theme.text(screen, tr("Mensch"), theme.BODY, theme.TEXT_FAINT, (ax + 380, ay + 15))
                theme.text(screen, "—", theme.BODY, theme.TEXT_FAINT, (ax + 640, ay + 15))
                theme.text(screen, tr("Mensch"), theme.BODY, theme.TEXT_FAINT, (ax + 380, ay + (h + gap) + 15))
                theme.text(screen, "—", theme.BODY, theme.TEXT_FAINT, (ax + 640, ay + (h + gap) + 15))
            else:
                theme.text(screen, tr("Mensch"), theme.BODY, theme.TEXT_FAINT, (ax + 240, ay + 15))
                theme.text(screen, "—", theme.BODY, theme.TEXT_FAINT, (ax + 580, ay + 15))
                theme.text(screen, tr("Mensch"), theme.BODY, theme.TEXT_FAINT, (ax + 240, ay + (h + gap) + 15))
                theme.text(screen, "—", theme.BODY, theme.TEXT_FAINT, (ax + 580, ay + (h + gap) + 15))

            for i, driver in enumerate(s.ai_roster):
                row_y = ay + (i + 2) * (h + gap)
                dr_rect = pygame.Rect(ax, row_y, 180 if is_team else 220, h)
                theme.text_fit(screen, driver.name, theme.BODY, theme.TEXT, dr_rect, center=False)
        else:
            # Draw descriptive Ghost card on the right
            ax = 960
            ay = 210
            panel_rect = pygame.Rect(ax, ay, 800, 360)
            pygame.draw.rect(screen, (30, 32, 40), panel_rect, border_radius=12)
            pygame.draw.rect(screen, theme.BORDER, panel_rect, 2, border_radius=12)

            theme.text(screen, tr("GHOST-MODUS (MEHRSPIELER ZEITFAHREN)"), theme.HEADER, theme.ACCENT, (ax + 30, ay + 30))
            
            desc_lines = [
                "Beide Spieler fahren gleichzeitig im Splitscreen gegen denselben Ghost.",
                "Es gibt keine KI-Gegner und Kollisionen sind deaktiviert.",
                "",
                "Schlagt ihr beide den Ghost, wird die Runde des schnelleren Spielers",
                "gespeichert; schlägt ihn nur einer von euch, wird dessen Runde",
                "als neuer Bestzeit-Ghost für diese Strecke gesichert."
            ]
            for idx, line in enumerate(desc_lines):
                theme.text(screen, tr(line) if line else line, theme.BODY, theme.TEXT, (ax + 30, ay + 90 + idx * 32))

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
            theme.text(screen, self.msg, theme.BODY, theme.DANGER, (area.centerx, area.bottom - 84), center=True)
        from src.ui import hints
        theme.text(screen, hints.bar(("confirm", tr("weiter")), ("back", tr("zurück"))),
                   theme.HINT, theme.TEXT_DIM, (area.centerx, area.bottom - 40), center=True)
