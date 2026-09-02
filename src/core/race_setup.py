"""Shared race configuration chosen in the lobby and consumed by the race.

A single process-wide :class:`RaceSetup` carries the lobby choices (mode, field
size, vehicle class, laps, AI difficulty) plus the picked vehicle and track
through the car/track selection into the race, so those screens don't each need
to thread every parameter as call arguments.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Vehicle classes (display name → set of vehicle config keys).
CLASSES: dict[str, list[str]] = {
    "Alle":         ["rookie", "rookie_2", "rookie_3",
                     "supercar", "supercar_2", "supercar_3",
                     "drifter", "drifter_2", "drifter_3",
                     "limousine", "limousine_2", "limousine_3",
                     "electric", "electric_2", "electric_3"],
    "Hatchback":    ["rookie", "rookie_2", "rookie_3"],
    "Drifter":      ["drifter", "drifter_2", "drifter_3"],
    "Rennfahrzeug": ["supercar", "supercar_2", "supercar_3"],
    "Limousine":    ["limousine", "limousine_2", "limousine_3"],
    "Elektroauto":  ["electric", "electric_2", "electric_3"],
}
CLASS_NAMES = list(CLASSES.keys())

MODES = ["Rennen", "Zeitfahren", "Team-Zeitfahren", "Grand Prix"]
MODES_ENABLED = {"Rennen", "Zeitfahren", "Team-Zeitfahren", "Grand Prix"}

MODE_DESCRIPTIONS = {
    "Rennen": "Klassisches Rundrennen gegen die KI. Wer zuerst über die Ziellinie fährt, gewinnt.",
    "Zeitfahren": "Eine Runde gegen den Ghost der Streckenbestzeit. Unterbiete ihn und stelle einen neuen Rekord auf.",
    "Team-Zeitfahren": "Zwei Teams, ein Ziel: die beste Durchschnittszeit. Jede Sekunde jedes Fahrers zählt.",
    "Grand Prix": "Mehrere Rennen, ein Champion. Sammle Punkte über alle Strecken — der Beste gewinnt die Serie.",
}

DIFFICULTY_KEYS = ["easy", "medium", "hard"]
DIFFICULTY_LABELS = {"easy": "Einfach", "medium": "Mittel", "hard": "Schwer"}

# Input device specs for local players.
INPUT_SPECS = ["keyboard", "pad0", "pad1"]
INPUT_LABELS = {"keyboard": "Tastatur", "pad0": "Controller 1", "pad1": "Controller 2"}


def available_input_specs() -> list[str]:
    """Input device specs currently usable for local players: the keyboard
    plus one spec per connected controller (max 2 local players → pad0/pad1)."""
    from src.core import gamepad
    specs = ["keyboard"]
    for i in range(min(2, gamepad.device_count())):
        specs.append(f"pad{i}")
    return specs


@dataclass
class AIDriver:
    name: str
    vehicle: str = "random"     # "random" or concrete vehicle config key
    difficulty: str = "medium"  # "easy", "medium", "hard"
    team: str = "A"             # "A" or "B"


#: Groesstes Startfeld einschliesslich der Menschen.
#:
#: Am 02.09.2026 von sechs auf acht gehoben. Die Zahl steht hier und nur hier:
#: sie taucht sonst in beiden Lobbys und im Streckenbau auf, und drei Kopien
#: waeren drei Gelegenheiten, eine davon zu vergessen. ``Track`` baut so viele
#: Gitterplaetze aus der Mittellinie, wie hier stehen.
FELD_MAX = 8

#: Kleinstes Startfeld. Ein Rennen gegen niemanden ist Zeitfahren, und das ist
#: ein eigener Modus.
FELD_MIN = 2


def feld_optionen(nur_gerade: bool = False) -> list[str]:
    """Die waehlbaren Feldgroessen als Text, fuer die Schrittwaehler der Lobby.

    ``nur_gerade`` fuer das Team-Zeitfahren: zwei gleich grosse Mannschaften
    gehen nur mit einer geraden Zahl auf.
    """
    schritt = 2 if nur_gerade else 1
    beginn = 4 if nur_gerade else FELD_MIN
    return [str(n) for n in range(beginn, FELD_MAX + 1, schritt)]


@dataclass
class RaceSetup:
    mode: str = "Rennen"
    vehicle_count: int = 4          # total incl. player (FELD_MIN..FELD_MAX)
    vehicle_class: str = "Alle"
    laps: int = 3                   # 1–10
    ai_difficulty: str = "medium"
    player_vehicle: str = "rookie"
    track_path: str = "data/tracks/oval.json"

    # Local multiplayer (mode == "mp_local")
    is_multiplayer: bool = False
    player2_name: str = "Spieler_2"      # remembered for the session only
    player2_vehicle: str = "rookie"
    p1_input: str = "keyboard"
    p2_input: str = "pad0"
    p1_team: str = "A"                  # "A" or "B"
    p2_team: str = "B"                  # "A" or "B"
    ai_roster: list[AIDriver] = field(default_factory=list)
    online_players: dict[int, dict] = field(default_factory=dict)
    # Online: vehicle_id -> "A"/"B" für die vom Host simulierte KI. Gäste haben
    # kein ai_roster, brauchen die Team-Zuordnung aber für Farben und Wertung.
    online_ai_teams: dict[int, str] = field(default_factory=dict)

    def class_keys(self) -> list[str]:
        return CLASSES.get(self.vehicle_class, CLASSES["Alle"])

    def human_count(self) -> int:
        return 2 if self.is_multiplayer else 1

    def ai_count(self) -> int:
        return max(0, self.vehicle_count - self.human_count())

    def sync_ai_roster(self) -> None:
        """Keep the AI roster in sync with the current vehicle_count and vehicle_class."""
        from src.core import ai_names
        # Target AI count = total count - human count
        target_ai_count = self.ai_count()

        def get_default_team(idx: int) -> str:
            if self.is_multiplayer:
                return "A" if idx % 2 == 0 else "B"
            else:
                return "B" if idx % 2 == 0 else "A"

        # If roster is empty, initialize it with random names
        if not self.ai_roster:
            names = ai_names.pick(30)
            for i in range(target_ai_count):
                self.ai_roster.append(AIDriver(name=names[i], team=get_default_team(i)))
        else:
            # Roster already exists: adjust size
            if len(self.ai_roster) < target_ai_count:
                existing_names = {d.name for d in self.ai_roster}
                all_names = ai_names.NAMES
                available_names = [n for n in all_names if n not in existing_names]
                import random
                random.shuffle(available_names)
                to_add = target_ai_count - len(self.ai_roster)
                for i in range(to_add):
                    name = available_names[i] if i < len(available_names) else f"AI_{len(self.ai_roster) + 1}"
                    idx = len(self.ai_roster)
                    self.ai_roster.append(AIDriver(name=name, team=get_default_team(idx)))
            elif len(self.ai_roster) > target_ai_count:
                self.ai_roster = self.ai_roster[:target_ai_count]

        # Validate vehicle configs match the current class.
        valid_keys = set(self.class_keys())
        for d in self.ai_roster:
            if d.vehicle != "random" and d.vehicle not in valid_keys:
                d.vehicle = "random"


_current = RaceSetup()


def current() -> RaceSetup:
    return _current
