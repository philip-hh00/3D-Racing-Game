"""Grand-Prix-Übersicht: Streckenliste, Wertung und Bereit-Zustand.

Eigene Ebene zwischen Lobby und Rennen. Die Lobby *richtet* eine Serie ein —
Fahrzeuge, Anzahl der Läufe, Runden je Lauf. Danach führt die Übersicht die
Serie: hier wählt der Host vor jedem Lauf die Strecke, alle melden sich bereit,
und zwischen den Rennen steht die Gruppe hier statt in der Lobby.

Warum das eine eigene Ebene ist: die Lobby wurde vorher als Zwischenstation
missbraucht. Sie sperrt aber Einstellungen, sobald die Serie läuft, und hat
keinen vorgesehenen Ort für eine Wertung — die Folge waren verschwindende
Bedienelemente und eine Tabelle dort, wo gerade Platz war.

Gezeichnet wird ausschließlich aus dem **verteilten** Serienzustand
(``gp_view``), nie aus ``grand_prix.current()``. Nur der Host führt die Serie;
läse die Anzeige beim Host aus einer anderen Quelle als beim Gast, fiele ein
Auseinanderlaufen niemandem auf, weil beim Host zufällig beides stimmt.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pygame

from src.core.i18n import tr
from src.net import payload
from src.ui import theme

#: Linke Spalte: Streckendaten. Danach die Kacheln.
INFO_X, INFO_W = 60, 300
TILE_X, TILE_W = 380, 420
TILE_H, TILE_GAP = 132, 12
LIST_Y = 212
VISIBLE_TILES = 5

#: Rechte Spalte: Fahrer und Wertung.
RIGHT_X = 900
RIGHT_W = 940

#: Streckenvorschläge (Block G) — der Bereich unter der Fahrertabelle.
OFFER_X, OFFER_Y = RIGHT_X, 620
OFFER_W, OFFER_H = RIGHT_W - 60, 320
OFFER_ROW_Y, OFFER_ROW_H = OFFER_Y + 62, 44
#: Ein Platz je Spieler, also nie mehr Zeilen als Fahrzeuge in einer Lobby.
OFFER_MAX_ROWS = 6

#: Siegerehrung. Der Sieger steht mittig und am höchsten, die Stufen daneben.
SCHIRM_MITTE = 960
#: Oberkante der hoechsten Stufe. Darueber steht der Name (-62) und die
#: Punktzahl (-28), darunter faengt bei PODEST_UNTEN die volle Tabelle an.
PODEST_Y, PODEST_W, PODEST_MAX_H = 360, 260, 200
PODEST = {
    1: (0,    200, (255, 215, 0)),
    2: (-290, 150, (200, 200, 210)),
    3: (290,  110, (205, 127, 50)),
}
PODEST_UNTEN = PODEST_Y + PODEST_MAX_H + 70


def load_track_infos() -> dict[str, dict[str, Any]]:
    """Alle spielbaren Strecken mit den Daten für Kachel und Infospalte.

    Beschädigte Dateien werden übersprungen statt die Liste zu sprengen —
    dieselbe Regel wie im Streckenlader, hier nur für die Vorschau.
    """
    from src.core import paths
    eintraege: list[tuple[str, Path, bool]] = [
        (k, Path(f"data/tracks/{k}.json"), False)
        for k in ("oval", "desert", "city", "mountain", "gp")
    ]
    # Ueber alle Wurzeln, nicht nur relativ zum Arbeitsverzeichnis: auf einem
    # gepackten macOS-Build liegen geschenkte Strecken woanders als die
    # mitgelieferten (siehe paths.track_roots).
    for ordner in ("custom", "online"):
        for p in paths.track_files(ordner):
            eintraege.append((f"{ordner}/{p.stem}", p, True))

    out: dict[str, dict[str, Any]] = {}
    for key, pfad, ist_eigen in eintraege:
        if not pfad.exists():
            continue
        try:
            with open(pfad, encoding="utf-8") as f:
                daten = json.load(f)
            mittellinie = [(float(p["x"]), float(p["y"]))
                           for p in daten.get("centerline", [])
                           if isinstance(p, dict)]
            if len(mittellinie) < 3:
                continue
            xs = [p[0] for p in mittellinie]
            ys = [p[1] for p in mittellinie]
            out[key] = {
                "name": daten.get("name", key),
                "difficulty": daten.get("difficulty", "Einfach"),
                "track_width": float(daten.get("track_width", 200.0)),
                "checkpoints": sum(1 for w in daten.get("waypoints", [])
                                   if isinstance(w, dict) and w.get("is_checkpoint")),
                "centerline": mittellinie,
                "cx": (min(xs) + max(xs)) / 2.0,
                "cy": (min(ys) + max(ys)) / 2.0,
                "max_dim": max(max(xs) - min(xs), max(ys) - min(ys)),
                "path": str(pfad),
                "is_custom": ist_eigen,
            }
        except Exception:
            continue
    return out


def track_length_km(info: dict) -> float:
    """Grobe Streckenlänge aus der Mittellinie (1000 px ≈ 1 km)."""
    punkte = info.get("centerline") or []
    if len(punkte) < 2:
        return 0.0
    laenge = sum(math.dist(punkte[i], punkte[(i + 1) % len(punkte)])
                 for i in range(len(punkte)))
    return laenge / 1000.0


def draw_outline(screen: pygame.Surface, info: dict, rect: pygame.Rect,
                 farbe=(0, 210, 230), staerke: int = 2) -> None:
    """Streckenverlauf in *rect* einpassen und zeichnen."""
    punkte = info.get("centerline") or []
    max_dim = info.get("max_dim") or 0
    if len(punkte) < 3 or max_dim <= 0:
        return
    skala = min(rect.width, rect.height) * 0.86 / max_dim
    cx, cy = info["cx"], info["cy"]
    auf_schirm = [
        (rect.centerx + (px - cx) * skala,
         rect.centery - (py - cy) * skala)      # Welt ist Y-oben, Schirm Y-unten
        for px, py in punkte
    ]
    if len(auf_schirm) >= 3:
        pygame.draw.lines(screen, farbe, True, auf_schirm, staerke)


class GPOverview:
    """Zeichnen und Bedienen der Übersicht.

    Bewusst keine eigene Netzverbindung: die Online-Seite besitzt Sitzung,
    Bereit-System und Zustandsverteilung bereits. Diese Klasse bekommt beides
    übergeben und liefert Aktionen zurück.
    """

    def __init__(self) -> None:
        self.tracks = load_track_infos()
        self.keys = list(self.tracks.keys())
        #: Was der Betrachter gerade ansieht. Beim Gast unabhängig von der Wahl
        #: des Hosts — er darf blättern, ohne etwas zu entscheiden.
        self.cursor = 0
        self.scroll = 0
        #: Namen der Strecken, die der Host anbietet, wir aber nicht haben.
        #: Ohne sie zeigte ein Gast nur seine eigenen Dateien — auf einer
        #: Strecke, die er gar nicht in der Liste hatte, wirkte die Wahl des
        #: Hosts wie „nichts ausgewählt".
        self._fremd_namen: dict[str, str] = {}
        self._fremd_eigen: set[str] = set()

    # ── Streckenliste des Hosts ─────────────────────────────────────────────

    def set_host_tracks(self, eintraege: list) -> bool:
        """Liste des Hosts übernehmen. True, wenn sich etwas geändert hat.

        Der Host bestimmt, was zur Wahl steht — auch Strecken, die es hier
        nicht gibt. Für die fehlenden zeigt die Kachel den Namen und einen
        Hinweis statt des Verlaufs; übertragen wird die Datei ohnehin erst
        beim Start des Laufs.
        """
        keys: list[str] = []
        namen: dict[str, str] = {}
        eigen: set[str] = set()
        for e in payload.dict_entries(eintraege):
            key = str(e.get("key", ""))
            if not key or key in namen:
                continue
            keys.append(key)
            namen[key] = str(e.get("name", "") or key)
            if e.get("is_custom"):
                eigen.add(key)
        if not keys or (keys == self.keys and namen == self._fremd_namen):
            return False
        self.keys = keys
        self._fremd_namen = namen
        self._fremd_eigen = eigen
        self.cursor = max(0, min(self.cursor, len(keys) - 1))
        self.scroll = max(0, min(self.scroll, max(0, len(keys) - VISIBLE_TILES)))
        return True

    def name_of(self, key: str | None) -> str:
        info = self.tracks.get(key or "")
        if info:
            return str(info["name"])
        return self._fremd_namen.get(key or "", key or "—")

    def host_track_payload(self) -> list[dict]:
        """Was der Host verteilt: Schlüssel und Name, sonst nichts.

        Der Streckenverlauf bleibt bewusst draußen — er sind tausende Punkte je
        Strecke, und dieser Block reist bei jeder Einstellungsänderung mit.
        """
        return [{"key": k, "name": str(i["name"]), "is_custom": bool(i.get("is_custom"))}
                for k, i in self.tracks.items()]

    # ── Auswahl ──────────────────────────────────────────────────────────────

    def key_at(self, index: int) -> str | None:
        return self.keys[index] if 0 <= index < len(self.keys) else None

    def key_for_path(self, pfad: str | None) -> str | None:
        """Streckenschlüssel zu einem Pfad, wie ihn der Host verteilt."""
        if not pfad:
            return None
        ziel = Path(str(pfad)).stem
        for key, info in self.tracks.items():
            if Path(info["path"]).stem == ziel:
                return key
        return None

    def move(self, delta: int) -> None:
        if not self.keys:
            return
        self.cursor = max(0, min(len(self.keys) - 1, self.cursor + delta))
        if self.cursor < self.scroll:
            self.scroll = self.cursor
        elif self.cursor >= self.scroll + VISIBLE_TILES:
            self.scroll = self.cursor - VISIBLE_TILES + 1

    def scroll_by(self, delta: int) -> None:
        """Nur die Ansicht verschieben, die Auswahl bleibt stehen.

        Getrennt von :meth:`move`, weil Blättern und Auswählen zwei Dinge sind:
        das Mausrad schiebt die Liste wie auf jeder Webseite, ohne dem Host
        unter der Hand eine andere Strecke unterzuschieben.
        """
        max_scroll = max(0, len(self.keys) - VISIBLE_TILES)
        self.scroll = max(0, min(max_scroll, self.scroll + delta))

    def scrollbar_rects(self) -> tuple[pygame.Rect, pygame.Rect] | None:
        """Bahn und Daumen der Bildlaufleiste, oder None wenn alles sichtbar ist.

        Getrennt vom Zeichnen, damit die Geometrie ohne Bildschirm prüfbar ist.
        Die Höhe des Daumens ist der sichtbare Anteil der Liste — daran sieht
        man, wie viel noch folgt, nicht nur *dass* noch etwas folgt.
        """
        gesamt = len(self.keys)
        if gesamt <= VISIBLE_TILES:
            return None
        bahn = pygame.Rect(TILE_X + TILE_W + 12, LIST_Y, 8,
                           VISIBLE_TILES * (TILE_H + TILE_GAP) - TILE_GAP)
        hoehe = max(30, int(bahn.height * VISIBLE_TILES / gesamt))
        max_scroll = gesamt - VISIBLE_TILES
        anteil = min(1.0, max(0.0, self.scroll / max_scroll)) if max_scroll else 0.0
        daumen = pygame.Rect(bahn.x, bahn.y + int((bahn.height - hoehe) * anteil),
                             bahn.width, hoehe)
        return bahn, daumen

    def tile_rects(self) -> list[tuple[int, pygame.Rect]]:
        out = []
        ende = min(len(self.keys), self.scroll + VISIBLE_TILES)
        for reihe, i in enumerate(range(self.scroll, ende)):
            out.append((i, pygame.Rect(TILE_X, LIST_Y + reihe * (TILE_H + TILE_GAP),
                                       TILE_W, TILE_H)))
        return out

    # ── Zeichnen ─────────────────────────────────────────────────────────────

    # ── Siegerehrung ─────────────────────────────────────────────────────────

    def draw_ceremony(self, screen: pygame.Surface, *, gp_view: dict,
                      players: list[dict], eigener_slot: int) -> None:
        """Endstand nach dem letzten Lauf: Treppchen und volle Wertung.

        Eigene Ansicht statt eines Zusatzes in der Streckenliste — nach dem
        letzten Lauf gibt es keine Strecke mehr zu wählen, und ohne sichtbaren
        Abschluss ließ sich einfach weiterfahren, als liefe die Serie noch.
        """
        stand = payload.dict_entries(gp_view.get("gp_standings"))
        gesamt = payload.as_int(gp_view.get("gp_total"), len(stand) or 1)
        theme.text(screen, tr("GRAND PRIX — ENDSTAND"), theme.TITLE, theme.ACCENT,
                   (SCHIRM_MITTE, 190), center=True)
        theme.text(screen, tr("{n} Läufe gefahren").format(n=gesamt), theme.BODY,
                   theme.TEXT_DIM, (SCHIRM_MITTE, 246), center=True)

        self._draw_podium(screen, stand)

        # Volle Tabelle unter dem Treppchen — auch Platz 4 und tiefer wollen
        # ihr Ergebnis sehen.
        y = PODEST_UNTEN
        namen = {str(p.get("name", "")) for p in payload.dict_entries(players)}
        for rang, eintrag in enumerate(stand, start=1):
            name = str(eintrag.get("name", ""))
            ist_ich = any(p.get("slot") == eigener_slot
                          and str(p.get("name", "")) == name
                          for p in payload.dict_entries(players))
            farbe = (255, 165, 0) if ist_ich else (
                theme.TEXT if name in namen else theme.TEXT_DIM)
            theme.text(screen, f"{rang}.", theme.LABEL, theme.TEXT_FAINT,
                       (SCHIRM_MITTE - 300, y))
            theme.text_fit(screen, name, theme.LABEL, farbe,
                           pygame.Rect(SCHIRM_MITTE - 240, y - 4, 380, 30), center=False)
            theme.text(screen, str(payload.as_int(eintrag.get("points"), 0)),
                       theme.LABEL, farbe, (SCHIRM_MITTE + 300, y), midright=True)
            y += 38

    def _draw_podium(self, screen: pygame.Surface, stand: list[dict]) -> None:
        """Drei Stufen, Sieger in der Mitte. Fehlende Plätze bleiben leer."""
        for platz, (dx, hoehe, farbe) in PODEST.items():
            if platz > len(stand):
                continue
            eintrag = stand[platz - 1]
            rect = pygame.Rect(SCHIRM_MITTE + dx - PODEST_W // 2,
                               PODEST_Y + (PODEST_MAX_H - hoehe), PODEST_W, hoehe)
            pygame.draw.rect(screen, theme.PANEL, rect, border_radius=6)
            pygame.draw.rect(screen, farbe, rect, 3, border_radius=6)
            theme.text(screen, str(platz), theme.TITLE, farbe,
                       (rect.centerx, rect.centery), center=True)
            theme.text_fit(screen, str(eintrag.get("name", "")), theme.LABEL, farbe,
                           pygame.Rect(rect.x - 20, rect.y - 62, PODEST_W + 40, 30),
                           center=True)
            theme.text(screen,
                       tr("{p} Punkte").format(p=payload.as_int(eintrag.get("points"), 0)),
                       theme.HINT, theme.TEXT_DIM, (rect.centerx, rect.y - 28), center=True)

    def draw(self, screen: pygame.Surface, *, gewaehlt_key: str | None,
             ist_host: bool, gp_view: dict, players: list[dict],
             eigener_slot: int, online: bool = True,
             offers: list | None = None, offers_aktiv: bool = False) -> None:
        # Die Menue-Shell zeichnet auf y=128 bereits "MEHRSPIELER ONLINE".
        # Eine eigene Ueberschrift dort ueberlagert sie - deshalb darunter.
        lauf = payload.as_int(gp_view.get("gp_race"), 1)
        gesamt = payload.as_int(gp_view.get("gp_total"), 1)
        theme.text(screen, tr("GRAND PRIX") + f" — {tr('Lauf {i} von {n}').format(i=lauf, n=gesamt)}",
                   theme.LABEL, theme.ACCENT, (INFO_X, 172))

        self._draw_info(screen, gewaehlt_key)
        self._draw_tiles(screen, gewaehlt_key, ist_host)
        self._draw_drivers(screen, gp_view, players, eigener_slot, online)
        # Bereit-Spalte und Streckentausch gibt es nur mit Mitspielern am Netz.
        # Offline waeren beide eine Behauptung: auf niemanden wird gewartet und
        # niemandem laesst sich etwas schicken.
        if online:
            self._draw_offers(screen, offers or [], offers_aktiv, eigener_slot)

    def _draw_info(self, screen: pygame.Surface, gewaehlt_key: str | None) -> None:
        """Daten der gerade angesehenen Strecke, links neben den Kacheln."""
        key = self.key_at(self.cursor)
        info = self.tracks.get(key or "")
        if not info:
            # Strecke des Hosts, die wir nicht haben: Name und Hinweis statt
            # einer leeren Spalte.
            if key:
                theme.text_fit(screen, tr(self.name_of(key)), theme.BODY, theme.TEXT,
                               pygame.Rect(INFO_X, LIST_Y, INFO_W, 34), center=False)
                theme.text(screen, tr("● Für dieses Rennen gewählt") if key == gewaehlt_key
                           else tr("Vorschau"), theme.HINT,
                           theme.ACCENT if key == gewaehlt_key else theme.TEXT_FAINT,
                           (INFO_X, LIST_Y + 44))
                theme.text(screen, tr("Strecke liegt beim Gastgeber"), theme.HINT,
                           theme.TEXT_DIM, (INFO_X, LIST_Y + 84))
                theme.text(screen, tr("Sie wird vor dem Start übertragen"), theme.HINT,
                           theme.TEXT_FAINT, (INFO_X, LIST_Y + 110))
            return
        y = LIST_Y
        theme.text_fit(screen, tr(info["name"]), theme.BODY, theme.TEXT,
                       pygame.Rect(INFO_X, y, INFO_W, 34), center=False)
        y += 44
        if key == gewaehlt_key:
            theme.text(screen, tr("● Für dieses Rennen gewählt"), theme.HINT,
                       theme.ACCENT, (INFO_X, y))
        else:
            theme.text(screen, tr("Vorschau"), theme.HINT, theme.TEXT_FAINT, (INFO_X, y))
        y += 40

        for label, wert in (
            (tr("Streckenlänge"), f"{track_length_km(info):.1f} km"),
            (tr("Schwierigkeitsgrad"), tr(info["difficulty"])),
            (tr("{cp} Checkpoints").format(cp=info["checkpoints"]), ""),
            (tr("Fahrbahnbreite (Road Width)"), f"{info['track_width']:.0f}"),
        ):
            theme.text(screen, label, theme.HINT, theme.TEXT_FAINT, (INFO_X, y))
            if wert:
                theme.text(screen, wert, theme.LABEL, theme.TEXT, (INFO_X, y + 22))
                y += 56
            else:
                y += 30
        if info.get("is_custom"):
            theme.text(screen, tr("♦ Eigene"), theme.HINT, (120, 200, 255), (INFO_X, y))

    def _draw_tiles(self, screen: pygame.Surface, gewaehlt_key: str | None,
                    ist_host: bool) -> None:
        for i, rect in self.tile_rects():
            key = self.keys[i]
            info = self.tracks.get(key)
            ist_gewaehlt = (key == gewaehlt_key)
            ist_cursor = (i == self.cursor)

            if ist_gewaehlt:
                fuell, rand = (52, 44, 20), theme.ACCENT
            elif ist_cursor:
                fuell, rand = theme.PANEL_LIGHT, theme.BORDER_LIGHT
            else:
                fuell, rand = theme.PANEL, theme.BORDER
            pygame.draw.rect(screen, fuell, rect, border_radius=8)
            pygame.draw.rect(screen, rand, rect, 3 if ist_gewaehlt else 2, border_radius=8)

            # Name oben in der Kachel, Verlauf darunter.
            theme.text_fit(screen, tr(self.name_of(key)), theme.LABEL,
                           theme.ACCENT if ist_gewaehlt else theme.TEXT,
                           pygame.Rect(rect.x + 12, rect.y + 6, rect.width - 110, 28),
                           center=False)
            verlauf = pygame.Rect(rect.x + 12, rect.y + 36, rect.width - 24,
                                  rect.height - 46)
            if info:
                draw_outline(screen, info, verlauf,
                             farbe=theme.ACCENT if ist_gewaehlt else (0, 190, 210))
            else:
                theme.text(screen, tr("Strecke vom Gastgeber"), theme.HINT,
                           theme.TEXT_FAINT, (verlauf.centerx, verlauf.centery),
                           center=True)

            if ist_gewaehlt:
                theme.text(screen, tr("GEWÄHLT"), theme.SMALL, theme.ACCENT,
                           (rect.right - 12, rect.y + 10), topright=True)

        leiste = self.scrollbar_rects()
        if leiste is not None:
            bahn, daumen = leiste
            pygame.draw.rect(screen, theme.PANEL, bahn, border_radius=4)
            pygame.draw.rect(screen, theme.BORDER, bahn, 1, border_radius=4)
            pygame.draw.rect(screen, theme.ACCENT, daumen, border_radius=4)
            theme.text(screen, f"{self.cursor + 1} / {len(self.keys)}", theme.SMALL,
                       theme.TEXT_FAINT,
                       (TILE_X + TILE_W, LIST_Y - 24), topright=True)
        if not ist_host:
            theme.text(screen, tr("Nur der Gastgeber wählt die Strecke"), theme.HINT,
                       theme.TEXT_FAINT, (TILE_X, LIST_Y - 26))

    def _draw_drivers(self, screen: pygame.Surface, gp_view: dict,
                      players: list[dict], eigener_slot: int,
                      online: bool = True) -> None:
        x = RIGHT_X
        theme.text(screen, tr("WERTUNG & FAHRER"), theme.LABEL, theme.TEXT_DIM, (x, 165))

        spalten = [(tr("Rang"), x), (tr("Name"), x + 70), (tr("Fahrzeug"), x + 330),
                   (tr("Punkte"), x + 600)]
        if online:
            spalten.append((tr("Bereit"), x + 730))
        for label, sx in spalten:
            theme.text(screen, label, theme.SMALL, theme.TEXT_FAINT, (sx, LIST_Y - 26))
        pygame.draw.line(screen, theme.BORDER, (x, LIST_Y - 4),
                         (x + RIGHT_W - 60, LIST_Y - 4), 1)

        # Bereit-Zustand und Fahrzeug kommen aus der Spielerliste, Punkte aus
        # der verteilten Wertung. Beide sind nach Namen verknüpft.
        nach_name = {str(p.get("name", "")): p for p in payload.dict_entries(players)}
        stand = payload.dict_entries(gp_view.get("gp_standings"))

        y = LIST_Y + 8
        gezeigt = set()
        for rang, eintrag in enumerate(stand, start=1):
            name = str(eintrag.get("name", ""))
            gezeigt.add(name)
            p = nach_name.get(name)
            self._draw_driver_row(screen, x, y, rang, name,
                                  p, payload.as_int(eintrag.get("points"), 0),
                                  eigener_slot, online=online)
            y += 44

        # Wer noch keine Punkte hat, steht sonst nirgends - etwa vor dem ersten
        # Lauf oder nach einem Wiedereinstieg.
        for name, p in nach_name.items():
            if name in gezeigt:
                continue
            gezeigt.add(name)
            self._draw_driver_row(screen, x, y, None, name, p, 0, eigener_slot,
                                  online=online)
            y += 44

        # Die KI des Hosts gehoert ins Feld. Vor dem ersten Lauf hat sie noch
        # keine Punkte und stand deshalb nirgends - das Feld sah aus, als
        # fuehren nur die Menschen mit.
        for fahrer in payload.dict_entries(gp_view.get("ai_roster")):
            name = str(fahrer.get("name", ""))
            if not name or name in gezeigt:
                continue
            gezeigt.add(name)
            self._draw_driver_row(screen, x, y, None, name, None, 0, eigener_slot,
                                  ki_fahrzeug=str(fahrer.get("vehicle", "")),
                                  online=online)
            y += 44

    def _draw_driver_row(self, screen: pygame.Surface, x: int, y: int,
                         rang: int | None, name: str, spieler: dict | None,
                         punkte: int, eigener_slot: int,
                         ki_fahrzeug: str = "", online: bool = True) -> None:
        ist_ich = bool(spieler and spieler.get("slot") == eigener_slot)
        farbe = (255, 165, 0) if ist_ich else theme.TEXT

        theme.text(screen, f"{rang}." if rang else "—", theme.LABEL,
                   theme.TEXT_FAINT, (x, y))
        theme.text_fit(screen, name, theme.LABEL, farbe,
                       pygame.Rect(x + 70, y - 4, 250, 30), center=False)

        from src.entities.vehicle_factory import VehicleFactory
        if spieler is None:
            cfg = VehicleFactory.get_config(ki_fahrzeug) if ki_fahrzeug else None
            fahrzeug = f"{tr(cfg.name)}  ({tr('KI')})" if cfg else tr("KI")
        else:
            cfg = VehicleFactory.get_config(str(spieler.get("vehicle", "")))
            fahrzeug = tr(cfg.name) if cfg else tr("wählt noch …")
        theme.text_fit(screen, fahrzeug, theme.LABEL, theme.TEXT_DIM,
                       pygame.Rect(x + 330, y - 4, 250, 30), center=False)

        theme.text(screen, str(punkte), theme.LABEL, farbe, (x + 660, y), midright=True)

        if not online:
            return
        if spieler is None:
            zeichen, zfarbe = "—", theme.TEXT_FAINT
        elif spieler.get("lobby_ready"):
            zeichen, zfarbe = tr("Bereit") + f" {theme.HAKEN}", theme.SUCCESS
        else:
            zeichen, zfarbe = tr("Wartet …"), theme.TEXT_DIM
        theme.text(screen, zeichen, theme.LABEL, zfarbe, (x + 730, y))

    # ── Streckenvorschläge (Block G) ────────────────────────────────────────

    @staticmethod
    def offer_download_rects(anzahl: int) -> list[tuple[int, pygame.Rect]]:
        """Knopfflächen der Vorschlagszeilen. Die Knöpfe selbst gehören der
        Seite — nur sie kennt Fokus, Netz und was ein Klick auslösen soll."""
        return [(i, pygame.Rect(OFFER_X + OFFER_W - 190,
                                OFFER_ROW_Y + i * OFFER_ROW_H - 4, 170, 36))
                for i in range(min(anzahl, OFFER_MAX_ROWS))]

    @staticmethod
    def offer_add_rect() -> pygame.Rect:
        return pygame.Rect(OFFER_X + 16, OFFER_Y + OFFER_H - 52, 300, 40)

    @staticmethod
    def offer_toggle_rect() -> pygame.Rect:
        """Schaltflaeche des Gastgebers, oben rechts in der Vorschlagstafel.

        Der Schalter stand bis zum 05.08.2026 in der Lobby und war damit vor
        dem Serienstart einmalig zu entscheiden. Gemeldet: er gehoert „eine
        Seite später", damit der Host auch waehrend der Rennserie umschalten
        kann — dort steht die Liste, auf die er sich bezieht.
        """
        return pygame.Rect(OFFER_X + OFFER_W - 150, OFFER_Y + 12, 134, 34)

    def _draw_offers(self, screen: pygame.Surface, offers: list,
                     aktiv: bool, eigener_slot: int) -> None:
        """Was gerade in der Lobby liegt.

        Ohne Ja/Nein-Freigabe durch den Gastgeber: jeder bedient sich selbst.
        Deshalb landet auch nichts ungefragt auf einer fremden Platte — der
        Download ist immer ein bewusster Klick.
        """
        rect = pygame.Rect(OFFER_X, OFFER_Y, OFFER_W, OFFER_H)
        pygame.draw.rect(screen, (22, 24, 30), rect, border_radius=10)
        pygame.draw.rect(screen, theme.BORDER, rect, 1, border_radius=10)
        theme.text(screen, tr("STRECKENVORSCHLÄGE"), theme.LABEL,
                   theme.TEXT_DIM if aktiv else theme.TEXT_FAINT,
                   (rect.x + 20, rect.y + 18))

        if not aktiv:
            theme.text(screen, tr("Vom Gastgeber ausgeschaltet"), theme.HINT,
                       theme.DISABLED, (rect.x + 20, rect.y + 56))
            return

        eintraege = payload.dict_entries(offers)
        if not eintraege:
            theme.text(screen, tr("Noch keine Vorschläge"), theme.HINT,
                       theme.TEXT_FAINT, (rect.x + 20, rect.y + 56))

        for i, eintrag in enumerate(eintraege[:OFFER_MAX_ROWS]):
            y = OFFER_ROW_Y + i * OFFER_ROW_H
            eigen = payload.as_int(eintrag.get("slot"), -1) == eigener_slot
            # Streckenname, nicht Dateiname: "Hausstrecke" statt
            # "Hausstrecke.json" oder gar einem ganzen Pfad.
            titel = str(eintrag.get("title") or eintrag.get("name", ""))
            if titel.lower().endswith(".json"):
                titel = titel[:-5]
            theme.text_fit(screen, tr(titel), theme.LABEL,
                           (255, 165, 0) if eigen else theme.TEXT,
                           pygame.Rect(rect.x + 20, y - 4, 340, 30), center=False)
            von = str(eintrag.get("from", ""))
            theme.text_fit(screen, tr("von {n}").format(n=von), theme.HINT,
                           theme.TEXT_DIM,
                           pygame.Rect(rect.x + 380, y, 180, 26), center=False)
            kb = max(1, payload.as_int(eintrag.get("size"), 0) // 1024)
            theme.text(screen, f"{kb} KB", theme.HINT, theme.TEXT_FAINT,
                       (rect.x + 580, y))
