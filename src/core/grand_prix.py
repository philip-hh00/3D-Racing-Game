from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

# Points mapping for Grand Prix series positions (1-indexed)
GP_POINTS = {
    1: 10,
    2: 8,
    3: 6,
    4: 4,
    5: 2,
    6: 1
}

@dataclass
class GrandPrixSeries:
    races_total: int
    laps_per_race: int
    race_index: int = 0
    points: dict[str, int] = field(default_factory=dict)
    # history stores a list for each race. Each race entry is dict[driver_name, dict[str, Any]]
    # e.g., history[race_idx][driver_name] = {"position": pos, "points_gained": pts}
    history: list[dict[str, dict[str, Any]]] = field(default_factory=list)
    #: Streckenschluessel der bereits gefahrenen Laeufe, in Reihenfolge.
    #: Wiederholungen sind erlaubt - die Streckenauswahl markiert sie nur,
    #: damit man nicht versehentlich zweimal dieselbe nimmt.
    raced_tracks: list[str] = field(default_factory=list)

    @property
    def is_finished(self) -> bool:
        """Alle Laeufe gefahren?

        Gezaehlt werden die **gefahrenen** Laeufe, nicht der Zeiger auf den
        naechsten. `race_index` wird nach jedem Lauf weitergeschaltet und zeigt
        damit auf den kommenden - bei drei Laeufen stand er nach dem zweiten
        Rennen schon auf 2 und die Serie galt als beendet. Das kostete online
        den letzten Lauf (Playtest 29.07.2026).
        """
        return len(self.history) >= self.races_total

    @property
    def races_left(self) -> int:
        return max(0, self.races_total - len(self.history))

    def next_race(self) -> None:
        """Zum naechsten Lauf weiterschalten."""
        self.race_index = min(self.race_index + 1, self.races_total - 1)

    def note_track(self, track_key: str) -> None:
        """Merken, welche Strecke gefahren wurde (fuer die Markierung)."""
        if track_key:
            self.raced_tracks.append(str(track_key))

    def was_raced(self, track_key: str) -> bool:
        return str(track_key) in self.raced_tracks

    def add_race_results(self, rows: list[dict[str, Any]]) -> None:
        """Add results from the completed race and award points.

        Unbrauchbare Zeilen werden uebersprungen statt die Wertung zu sprengen:
        online kommen die Ergebnisse ueber das Netz, und ein einzelner
        beschaedigter Eintrag darf nicht die ganze Serie beenden.
        """
        from src.net import payload

        race_result = {}
        for row in payload.dict_entries(rows):
            name = row.get("name")
            if not name:
                continue
            is_dnf = bool(row.get("dnf", False))
            pos = payload.as_int(row.get("position"), 99)

            pts = GP_POINTS.get(pos, 0) if not is_dnf else 0

            # Update accumulated points
            if name not in self.points:
                self.points[name] = 0
            self.points[name] += pts

            race_result[name] = {
                "position": pos if not is_dnf else 99,
                "points_gained": pts,
                "dnf": is_dnf
            }
        self.history.append(race_result)

    def get_standings(self) -> list[dict[str, Any]]:
        """Calculate and return sorted standings with rank change comparison."""
        return self._compute_standings_at_race(len(self.history) - 1)

    def _compute_standings_at_race(self, history_idx: int) -> list[dict[str, Any]]:
        """Compute standings up to a specific history index."""
        if history_idx < 0 or not self.history:
            return []

        # 1. Accumulate points up to history_idx
        driver_points = {}
        for r_idx in range(history_idx + 1):
            race = self.history[r_idx]
            for name, details in race.items():
                if name not in driver_points:
                    driver_points[name] = 0
                driver_points[name] += details["points_gained"]

        # 2. Sortierschluessel fuer Gleichstand: mehr Punkte, dann mehr Siege,
        #    dann mehr zweite Plaetze und so weiter - die uebliche
        #    Motorsport-Regel.
        def get_sort_key(name: str) -> tuple:
            pts = driver_points.get(name, 0)
            # Index 1..6 = Platzierungen. Ausfaelle werden getrennt gezaehlt:
            # frueher teilten sie sich den Zaehler mit dem sechsten Platz, und
            # weil alle Zaehler absteigend sortiert werden, brachte ein
            # zusaetzlicher Ausfall den Fahrer nach VORN. Bei gleichen Punkten
            # und gleichen Siegen gewann damit, wer haeufiger ausgefallen war.
            places = [0] * 7
            dnfs = 0
            for r_idx in range(history_idx + 1):
                eintrag = self.history[r_idx].get(name)
                if eintrag is None:
                    # Gar nicht mitgefahren. Das ist weder eine Platzierung
                    # noch ein Ausfall - sonst wuerde ein spaeter dazugekommener
                    # Fahrer fuer jedes verpasste Rennen bestraft.
                    continue
                pos = eintrag.get("position", 99)
                if eintrag.get("dnf", False) or pos > 6:
                    dnfs += 1
                else:
                    places[pos] += 1

            latest_pos = self.history[history_idx].get(name, {}).get("position", 99)
            # Alles absteigend sortiert, deshalb wird die Ausfallzahl negiert:
            # weniger Ausfaelle muss besser sein.
            return (pts, places[1], places[2], places[3], places[4], places[5],
                    places[6], -dnfs, 99 - latest_pos)

        drivers = list(driver_points.keys())
        drivers.sort(key=get_sort_key, reverse=True)

        standings = []
        for rank_idx, name in enumerate(drivers):
            standings.append({
                "name": name,
                "points": driver_points[name],
                "rank_idx": rank_idx
            })

        # 3. Calculate rank changes compared to previous race
        if history_idx > 0:
            prev_standings = self._compute_standings_at_race(history_idx - 1)
            prev_ranks = {entry["name"]: entry["rank_idx"] for entry in prev_standings}
            for entry in standings:
                prev_rank = prev_ranks.get(entry["name"])
                if prev_rank is not None:
                    # e.g., went from index 3 (prev) to index 1 (curr) -> rank_change = prev_rank - entry["rank_idx"]
                    entry["rank_change"] = prev_rank - entry["rank_idx"]
                else:
                    entry["rank_change"] = 0
        else:
            for entry in standings:
                entry["rank_change"] = 0

        return standings


_current_gp: GrandPrixSeries | None = None

def startreihenfolge(stand_namen: list, feld: list) -> list:
    """Startaufstellung des naechsten Laufs: Wertung vorn, Rest hinterher.

    Ueber das **ganze Feld**, Mensch wie KI. Nur die Menschen umzusortieren
    reicht nicht: die belegen ohnehin die vorderen Plaetze, der Vierte der
    Wertung stuende damit weiter in Reihe eins (Playtest 29.07.2026).

    Wer noch in keiner Wertung steht - erster Lauf, Wiedereinstieg, frisch
    aufgefuellte KI - haengt in Feldreihenfolge hinten dran. Doppelte Namen
    zaehlen einmal, sonst faellt hinten ein Platz weg.
    """
    feld_ohne_doppel = list(dict.fromkeys(str(n) for n in feld if n))
    vorn = [str(n) for n in stand_namen if str(n) in feld_ohne_doppel]
    vorn = list(dict.fromkeys(vorn))
    gesehen = set(vorn)
    return vorn + [n for n in feld_ohne_doppel if n not in gesehen]


def is_active() -> bool:
    return _current_gp is not None

def start_series(races_total: int, laps_per_race: int) -> GrandPrixSeries:
    global _current_gp
    _current_gp = GrandPrixSeries(races_total=races_total, laps_per_race=laps_per_race)
    return _current_gp

def current() -> GrandPrixSeries | None:
    return _current_gp

def cancel() -> None:
    global _current_gp
    _current_gp = None
