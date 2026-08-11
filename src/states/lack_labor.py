"""Lackier-Seite des Fahrzeuglabors — Maskenwerte je Fahrzeug abstimmen.

Aufteilung (Releaseplan D3): Regler links, vier Felder rechts —
**Original | Maske | Ergebnis | Helligkeits-Histogramm**.

Die Maske sichtbar zu machen ist der eigentliche Grund fuer diese Seite: am
Ergebnis allein sieht man, *dass* etwas falsch ist, an der Maske *warum*. Das
vierte Feld ist der Zusatz, der die schwierigen Fahrzeuge ueberhaupt abstimmbar
macht — es zeigt, wo das Helligkeitsfenster sitzt und was es fasst. Ohne das
stellt man den Regler blind ein, an dem die unbunten Fahrzeuge haengen.

Bedient wird ueber Stepper und Schaltflaechen, nicht ueber gemerkte Tasten.

Arbeitsbreite: die Vorschau rechnet auf einer 640 px breiten Kopie, nicht auf den
1024 px der Werkstatt. Das haelt eine Reglerbewegung bei ~50 ms statt ~130 ms.
Die Maskenkriterien sind Farb- und Helligkeitsschwellen und damit unabhaengig von
der Groesse; nur die Kantenweichheit wirkt in Pixeln und faellt in der Werkstatt
entsprechend schmaler aus.
"""
from __future__ import annotations

import numpy as np
import pygame

from src.core import display, lack
from src.ui import theme

#: Arbeitsbreite der Laborvorschau — Kompromiss aus Detail und Reaktionszeit.
BREITE_LABOR = 640

_HISTO_KLASSEN = 64

# (Schluessel, Beschriftung, min, max, Schrittweite, Nachkommastellen, Einheit)
_REGLER = [
    ("saettigungsschwelle", "Sättigungsschwelle", 0.0, 1.0, 0.01, 2, ""),
    ("ref_r",               "Referenzfarbe R",    0.0, 255.0, 1.0, 0, ""),
    ("ref_g",               "Referenzfarbe G",    0.0, 255.0, 1.0, 0, ""),
    ("ref_b",               "Referenzfarbe B",    0.0, 255.0, 1.0, 0, ""),
    ("farbtoleranz",        "Farbtoleranz",       0.0, 1.0, 0.01, 2, ""),
    ("helligkeit_min",      "Helligkeit min",     0.0, 1.0, 0.01, 2, ""),
    ("helligkeit_max",      "Helligkeit max",     0.0, 1.0, 0.01, 2, ""),
    ("kantenweichheit",     "Kantenweichheit",    0.0, 4.0, 0.5, 1, " px"),
    ("deckkraft",           "Deckkraft",          0.0, 1.0, 0.05, 2, ""),
]


class LackLabor:
    """Zeichnet und bedient die Lackier-Seite. Haelt keine eigenen Werte —
    gearbeitet wird direkt am ``paint``-Block der laufenden Fahrzeugkonfiguration,
    damit ``S`` im Labor ihn ohne Umweg mitspeichert."""

    def __init__(self, labor) -> None:
        self.labor = labor          # VehicleLabState
        self.zeile = 0              # 0..len(_REGLER)-1
        self.farb_index = 0
        self.finish_index = 0
        self._signatur: tuple | None = None
        self._basis: pygame.Surface | None = None
        self._masken_bild: pygame.Surface | None = None
        self._ergebnis: pygame.Surface | None = None
        self._gewicht: np.ndarray | None = None
        self._lum: np.ndarray | None = None
        self._sichtbar: np.ndarray | None = None
        self._abdeckung = 0.0
        self._rects: dict[str, pygame.Rect] = {}
        self._pfeile: list[tuple[int, int, pygame.Rect]] = []   # (zeile, richtung, rect)

    # ------------------------------------------------------------------
    # Werte
    # ------------------------------------------------------------------
    def _werte(self) -> dict:
        """paint-Block der laufenden Konfiguration, bei Bedarf angelegt."""
        cfg = self.labor._cfg()
        if cfg is None:
            return dict(lack.PAINT_VORGABE)
        if not isinstance(getattr(cfg, "paint", None), dict):
            cfg.paint = dict(lack.PAINT_VORGABE)
        else:
            for k, v in lack.PAINT_VORGABE.items():
                cfg.paint.setdefault(k, v)
        return cfg.paint

    def _lesen(self, schluessel: str) -> float:
        w = self._werte()
        if schluessel.startswith("ref_"):
            ref = w.get("referenzfarbe") or (128, 128, 128)
            return float(ref["rgb".index(schluessel[4])])
        return float(w.get(schluessel, 0.0))

    def _schreiben(self, schluessel: str, wert: float) -> None:
        w = self._werte()
        if schluessel.startswith("ref_"):
            ref = list(w.get("referenzfarbe") or (128, 128, 128))
            ref["rgb".index(schluessel[4])] = int(round(wert))
            w["referenzfarbe"] = [int(v) for v in ref[:3]]
        else:
            w[schluessel] = wert
        self.labor.dirty = True

    def _verstellen(self, richtung: int) -> None:
        schluessel, _, lo, hi, schritt, dez, _ = _REGLER[self.zeile]
        neu = self._lesen(schluessel) + richtung * schritt
        neu = max(lo, min(hi, neu))
        self._schreiben(schluessel, round(neu, dez + 2))
        # Fenstergrenzen dürfen sich nicht überkreuzen — sonst ist die Maske leer
        # und man sucht den Fehler bei der Farbe.
        w = self._werte()
        if float(w["helligkeit_min"]) > float(w["helligkeit_max"]):
            if schluessel == "helligkeit_min":
                w["helligkeit_max"] = w["helligkeit_min"]
            else:
                w["helligkeit_min"] = w["helligkeit_max"]

    def _zeile_weiter(self, richtung: int) -> None:
        """Auf die naechste Zeile, die beim gewaehlten Verfahren etwas tut.
        Ein Fokus auf einem ausgegrauten Regler waere ein Angebot, das nichts
        bewirkt."""
        verfahren = str(self._werte().get("verfahren", "aus"))
        for _ in range(len(_REGLER)):
            self.zeile = (self.zeile + richtung) % len(_REGLER)
            if self._wirkt(_REGLER[self.zeile][0], verfahren):
                return

    def _verfahren_weiter(self, richtung: int) -> None:
        w = self._werte()
        i = lack.VERFAHREN.index(w.get("verfahren", "aus")) if \
            w.get("verfahren") in lack.VERFAHREN else 0
        w["verfahren"] = lack.VERFAHREN[(i + richtung) % len(lack.VERFAHREN)]
        self.labor.dirty = True
        if not self._wirkt(_REGLER[self.zeile][0], str(w["verfahren"])):
            self._zeile_weiter(+1)

    def _referenz_aus_bild(self) -> None:
        basis = lack.arbeitskopie(self._visual_type(), BREITE_LABOR)
        if basis is not None:
            self._werte()["referenzfarbe"] = list(lack.dominante_farbe(basis))
            self.labor.dirty = True

    def _visual_type(self) -> str:
        cfg = self.labor._cfg()
        return getattr(cfg, "visual_type", self.labor._key) if cfg else self.labor._key

    def _kennung(self) -> str:
        farben, finishes = lack.farben(), lack.finishes()
        if not farben or not finishes:
            return lack.WERK
        return lack.kennung(finishes[self.finish_index % len(finishes)]["key"],
                            farben[self.farb_index % len(farben)]["key"])

    # ------------------------------------------------------------------
    # Vorschau
    # ------------------------------------------------------------------
    def _neu_rechnen(self) -> None:
        """Vorschau nur bei tatsaechlicher Aenderung neu rechnen — eine
        Reglerbewegung kostet ~50 ms, je Bild waere das unbenutzbar."""
        w = self._werte()
        sig = (self.labor._key, self._kennung(), tuple(sorted(
            (k, tuple(v) if isinstance(v, (list, tuple)) else v) for k, v in w.items())))
        if sig == self._signatur:
            return
        self._signatur = sig

        basis = lack.arbeitskopie(self._visual_type(), BREITE_LABOR)
        self._basis = basis
        if basis is None:
            self._masken_bild = self._ergebnis = None
            return
        gewicht, lum = lack.maske(basis, w)
        alpha = pygame.surfarray.array_alpha(basis)
        self._gewicht, self._lum = gewicht, lum
        self._sichtbar = np.asarray(alpha) > 40
        fest = gewicht > 0.5
        sichtbar_n = int(self._sichtbar.sum())
        self._abdeckung = (float(fest.sum()) / sichtbar_n) if sichtbar_n else 0.0
        self._masken_bild = self._maskenbild(basis, gewicht)
        self._ergebnis = lack.umfaerben(basis, self._kennung(), w)

    @staticmethod
    def _maskenbild(basis: pygame.Surface, gewicht: np.ndarray) -> pygame.Surface:
        """Maske als Schwarzweissbild, Silhouette schwach angedeutet — damit man
        sieht, welcher Teil des Autos *nicht* erfasst ist."""
        alpha = np.asarray(pygame.surfarray.array_alpha(basis)).astype(np.float32)
        grau = np.repeat((gewicht * 255.0)[..., None], 3, axis=2)
        rumpf = (alpha > 40) & (gewicht <= 0.02)
        grau[rumpf] = np.array((34, 38, 48), dtype=np.float32)
        out = pygame.Surface(grau.shape[:2], pygame.SRCALPHA)
        pygame.surfarray.blit_array(out, np.clip(grau, 0, 255).astype(np.uint8))
        kanal = pygame.surfarray.pixels_alpha(out)
        kanal[:, :] = np.where(alpha > 40, 255, 0).astype(np.uint8)
        del kanal
        return out

    # ------------------------------------------------------------------
    # Ereignisse
    # ------------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_UP:
                self._zeile_weiter(-1)
                return True
            if event.key == pygame.K_DOWN:
                self._zeile_weiter(+1)
                return True
            if event.key == pygame.K_LEFT:
                self._verstellen(-1)
                return True
            if event.key == pygame.K_RIGHT:
                self._verstellen(+1)
                return True
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for name, r in self._rects.items():
                if not r.collidepoint(event.pos):
                    continue
                if name == "fahrzeug_l":
                    self.labor._fahrzeug_wechseln(-1); return True
                if name == "fahrzeug_r":
                    self.labor._fahrzeug_wechseln(+1); return True
                if name == "farbe_l":
                    self.farb_index -= 1; return True
                if name == "farbe_r":
                    self.farb_index += 1; return True
                if name == "finish_l":
                    self.finish_index -= 1; return True
                if name == "finish_r":
                    self.finish_index += 1; return True
                if name == "verfahren_l":
                    self._verfahren_weiter(-1); return True
                if name == "verfahren_r":
                    self._verfahren_weiter(+1); return True
                if name == "speichern":
                    self.labor._save(); return True
                if name == "verwerfen":
                    self.labor._verwerfen(); self._signatur = None; return True
                if name == "referenz":
                    self._referenz_aus_bild(); return True
            for zeile, richtung, r in self._pfeile:
                if r.collidepoint(event.pos):
                    self.zeile = zeile
                    self._verstellen(richtung)
                    return True
        return False

    # ------------------------------------------------------------------
    # Zeichnen
    # ------------------------------------------------------------------
    def draw(self, screen: pygame.Surface, bereich: pygame.Rect) -> None:
        self._neu_rechnen()
        # Beim Betreten steht der Fokus auf Zeile 0; bei Verfahren "dominant" ist
        # das die ausgegraute Saettigungsschwelle. Ein Pfeil auf einem Regler,
        # der nichts tut, ist ein falsches Angebot.
        if not self._wirkt(_REGLER[self.zeile][0],
                           str(self._werte().get("verfahren", "aus"))):
            self._zeile_weiter(+1)
        self._rects.clear()
        self._pfeile.clear()

        links = pygame.Rect(bereich.x, bereich.y, 560, bereich.height)
        self._regler_zeichnen(screen, links)

        gx = links.right + 30
        breite = (bereich.right - gx - 20) // 2
        hoehe = (bereich.height - 20) // 2
        self._feld(screen, pygame.Rect(gx, bereich.y, breite, hoehe),
                   "ORIGINAL", self._basis, theme.BORDER)
        self._feld(screen, pygame.Rect(gx + breite + 20, bereich.y, breite, hoehe),
                   "MASKE", self._masken_bild, (120, 80, 160),
                   unter=f"weiß = Lackfläche   ·   Abdeckung {self._abdeckung * 100:.1f} %"
                         + ("   ·   über 90 % ist ein Warnzeichen"
                            if self._abdeckung > 0.9 else ""))
        self._feld(screen, pygame.Rect(gx, bereich.y + hoehe + 20, breite, hoehe),
                   "ERGEBNIS", self._ergebnis, theme.ACCENT_DIM,
                   unter=lack.anzeigename(self._kennung()))
        self._histogramm(screen, pygame.Rect(gx + breite + 20, bereich.y + hoehe + 20,
                                             breite, hoehe))

    # -- linke Spalte ---------------------------------------------------
    def _regler_zeichnen(self, screen: pygame.Surface, r: pygame.Rect) -> None:
        theme.panel(screen, r, alpha=195)
        w = self._werte()
        farben, finishes = lack.farben(), lack.finishes()
        y = r.y + 14
        durchblaettern = [
            ("fahrzeug", "Fahrzeug",
             f"{self.labor._cfg().name if self.labor._cfg() else '?'}"
             f"  {self.labor.veh_index + 1}/{max(1, len(self.labor.keys))}"),
            ("farbe", "Zielfarbe",
             farben[self.farb_index % len(farben)]["name"] if farben else "—"),
            ("finish", "Finish",
             finishes[self.finish_index % len(finishes)]["name"] if finishes else "—"),
        ]
        for name, label, wert in durchblaettern:
            self._stepper(screen, pygame.Rect(r.x + 16, y, r.width - 32, 54),
                          label, wert, name)
            y += 62

        pygame.draw.line(screen, (46, 50, 62), (r.x + 16, y + 2), (r.right - 16, y + 2), 1)
        y += 16

        # Verfahren zuerst — es entscheidet, welche Regler darunter überhaupt wirken.
        self._stepper(screen, pygame.Rect(r.x + 16, y, r.width - 32, 54),
                      "Verfahren", str(w.get("verfahren", "aus")), "verfahren")
        y += 66

        for i, (schluessel, label, lo, hi, schritt, dez, einheit) in enumerate(_REGLER):
            wert = self._lesen(schluessel)
            anteil = (wert - lo) / (hi - lo) if hi > lo else 0.0
            aktiv = (i == self.zeile)
            benutzt = self._wirkt(schluessel, str(w.get("verfahren", "aus")))
            zeile = pygame.Rect(r.x + 24, y, r.width - 168, 38)
            self._regler(screen, zeile, label, f"{wert:.{dez}f}{einheit}", anteil,
                         aktiv=aktiv, benutzt=benutzt)
            pl = pygame.Rect(r.right - 122, y + 2, 44, 36)
            pr = pygame.Rect(r.right - 70, y + 2, 44, 36)
            self._pfeile.append((i, -1, pl))
            self._pfeile.append((i, +1, pr))
            self._pfeilknopf(screen, pl, "‹", benutzt)
            self._pfeilknopf(screen, pr, "›", benutzt)
            y += 62

        knopf_y = r.bottom - 66
        breite = (r.width - 48) // 3
        for i, (name, label, stil) in enumerate((
                ("speichern", "Speichern", "primary"),
                ("verwerfen", "Verwerfen", "secondary"),
                ("referenz", "Referenz aus Bild", "secondary"))):
            kasten = pygame.Rect(r.x + 16 + i * (breite + 8), knopf_y, breite, 50)
            self._rects[name] = kasten
            self._knopf(screen, kasten, label, stil)

    @staticmethod
    def _wirkt(schluessel: str, verfahren: str) -> bool:
        """Ob ein Regler beim gewaehlten Verfahren etwas tut. Ausgegraute Regler
        sind ehrlicher als Regler, die sichtbar nichts bewirken."""
        if verfahren == "aus":
            return False
        if schluessel == "saettigungsschwelle":
            return verfahren == "saettigung"
        if schluessel.startswith("ref_") or schluessel == "farbtoleranz":
            return verfahren == "dominant"
        return True

    def _stepper(self, screen, r: pygame.Rect, label: str, wert: str, name: str) -> None:
        pygame.draw.rect(screen, theme.PANEL_LIGHT, r, border_radius=8)
        pygame.draw.rect(screen, theme.BORDER, r, 2, border_radius=8)
        sz = 42
        links = pygame.Rect(r.right - min(250, r.width // 2), r.y + 6, sz, r.height - 12)
        rechts = pygame.Rect(r.right - sz - 6, r.y + 6, sz, r.height - 12)
        self._rects[f"{name}_l"] = links
        self._rects[f"{name}_r"] = rechts
        from src.core.i18n import tr
        theme.text_fit(screen, tr(label), theme.BODY, theme.TEXT,
                       pygame.Rect(r.x + 18, r.y, links.left - r.x - 26, r.height))
        mp = display.mouse_pos()
        theme.text(screen, "‹", theme.HEADER,
                   theme.ACCENT_HOT if links.collidepoint(mp) else theme.ACCENT,
                   links.center, center=True)
        theme.text(screen, "›", theme.HEADER,
                   theme.ACCENT_HOT if rechts.collidepoint(mp) else theme.ACCENT,
                   rechts.center, center=True)
        theme.text_fit(screen, tr(wert), theme.BODY, theme.TEXT,
                       pygame.Rect(links.right + 4, r.y,
                                   rechts.left - links.right - 8, r.height), center=True)

    def _regler(self, screen, r: pygame.Rect, label: str, wert: str, anteil: float,
                *, aktiv: bool, benutzt: bool) -> None:
        from src.core.i18n import tr
        farbe_text = theme.TEXT if (aktiv and benutzt) else (
            theme.TEXT_DIM if benutzt else theme.DISABLED)
        farbe_wert = theme.ACCENT if (aktiv and benutzt) else (
            theme.TEXT_DIM if benutzt else theme.DISABLED)
        theme.text(screen, tr(label), theme.HINT, farbe_text, (r.x, r.y))
        theme.text(screen, wert, theme.HINT, farbe_wert, (r.right, r.y), topright=True)
        bar = pygame.Rect(r.x, r.y + 26, r.width, 8)
        pygame.draw.rect(screen, (30, 33, 44), bar, border_radius=4)
        pygame.draw.rect(screen, (52, 56, 70), bar, 1, border_radius=4)
        fw = int(bar.width * max(0.0, min(1.0, anteil)))
        if fw > 0:
            pygame.draw.rect(screen, (theme.ACCENT if aktiv else theme.ACCENT_DIM)
                             if benutzt else theme.DISABLED,
                             (bar.x, bar.y, fw, bar.height), border_radius=4)
        knauf = pygame.Rect(0, 0, 8, 18)
        knauf.center = (bar.x + fw, bar.centery)
        pygame.draw.rect(screen, (theme.ACCENT_HOT if aktiv else theme.TEXT_DIM)
                         if benutzt else theme.DISABLED, knauf, border_radius=3)
        if aktiv:
            pygame.draw.polygon(screen, theme.ACCENT,
                                [(r.x - 18, r.y + 4), (r.x - 8, r.y + 11),
                                 (r.x - 18, r.y + 18)])

    def _pfeilknopf(self, screen, r: pygame.Rect, glyph: str, an: bool = True) -> None:
        hover = an and r.collidepoint(display.mouse_pos())
        pygame.draw.rect(screen, (46, 50, 62) if hover else (32, 36, 46), r, border_radius=8)
        pygame.draw.rect(screen, theme.ACCENT_HOT if hover else
                         (theme.BORDER_LIGHT if an else theme.DISABLED), r, 2,
                         border_radius=8)
        theme.text(screen, glyph, theme.BODY,
                   (theme.ACCENT_HOT if hover else theme.ACCENT) if an else theme.DISABLED,
                   r.center, center=True)

    def _knopf(self, screen, r: pygame.Rect, label: str, stil: str) -> None:
        from src.core.i18n import tr
        hover = r.collidepoint(display.mouse_pos())
        if hover:
            fill = (70, 56, 22) if stil == "primary" else (46, 50, 62)
            rand = theme.ACCENT_HOT
        else:
            fill = (44, 38, 18) if stil == "primary" else (32, 36, 46)
            rand = theme.ACCENT if stil == "primary" else theme.BORDER_LIGHT
        pygame.draw.rect(screen, fill, r, border_radius=8)
        pygame.draw.rect(screen, rand, r, 2, border_radius=8)
        theme.text_fit(screen, tr(label), theme.HINT, theme.TEXT,
                       r.inflate(-12, 0), center=True)

    # -- Bildfelder -----------------------------------------------------
    def _feld(self, screen, r: pygame.Rect, titel: str,
              bild: pygame.Surface | None, rand, *, unter: str = "") -> None:
        pygame.draw.rect(screen, (10, 12, 20), r, border_radius=6)
        pygame.draw.rect(screen, rand, r, 1, border_radius=6)
        theme.text(screen, titel, theme.HINT, theme.TEXT_DIM, (r.x + 12, r.y + 10))
        if bild is not None:
            innen = pygame.Rect(r.x + 10, r.y + 44, r.width - 20, r.height - 80)
            f = min(innen.width / bild.get_width(), innen.height / bild.get_height())
            from src.core import gfx
            skaliert = gfx.scale(bild, (max(1, int(bild.get_width() * f)),
                                        max(1, int(bild.get_height() * f))))
            screen.blit(skaliert, skaliert.get_rect(center=innen.center))
        else:
            theme.text(screen, "kein Sprite", theme.HINT, theme.TEXT_FAINT,
                       r.center, center=True)
        if unter:
            theme.text(screen, unter, theme.SMALL, theme.TEXT_FAINT,
                       (r.x + 12, r.bottom - 26), max_w=r.width - 24)

    def _histogramm(self, screen, r: pygame.Rect) -> None:
        pygame.draw.rect(screen, (10, 12, 20), r, border_radius=6)
        pygame.draw.rect(screen, (70, 90, 130), r, 1, border_radius=6)
        theme.text(screen, "HELLIGKEIT DER SICHTBAREN PIXEL", theme.HINT,
                   theme.TEXT_DIM, (r.x + 12, r.y + 10))
        if self._lum is None or self._sichtbar is None or self._gewicht is None:
            return
        w = self._werte()
        hmin = float(w.get("helligkeit_min", 0.0))
        hmax = float(w.get("helligkeit_max", 1.0))

        alle, _ = np.histogram(self._lum[self._sichtbar], bins=_HISTO_KLASSEN,
                               range=(0.0, 1.0))
        drin, _ = np.histogram(self._lum[self._sichtbar & (self._gewicht > 0.5)],
                               bins=_HISTO_KLASSEN, range=(0.0, 1.0))
        # Wurzelskala: ein einfarbiges Auto haeuft fast alle Pixel auf einer
        # Helligkeit, linear waere ausser einem Balken nichts zu sehen.
        a_s, d_s = np.sqrt(alle.astype(np.float64)), np.sqrt(drin.astype(np.float64))
        hoch = max(1e-6, float(a_s.max()))

        gx, gy = r.x + 16, r.y + 52
        gw, gh = r.width - 32, r.height - 100
        fenster = pygame.Surface((max(1, int((hmax - hmin) * gw)), gh), pygame.SRCALPHA)
        fenster.fill((255, 180, 0, 22))
        screen.blit(fenster, (gx + int(hmin * gw), gy))
        bb = max(1, gw // _HISTO_KLASSEN - 1)
        for i in range(_HISTO_KLASSEN):
            bx = gx + int(i * gw / _HISTO_KLASSEN)
            h1 = int(gh * a_s[i] / hoch)
            h2 = int(gh * d_s[i] / hoch)
            if h1:
                pygame.draw.rect(screen, (52, 56, 72), (bx, gy + gh - h1, bb, h1))
            if h2:
                pygame.draw.rect(screen, (150, 100, 235), (bx, gy + gh - h2, bb, h2))
        pygame.draw.line(screen, (60, 64, 80), (gx, gy + gh), (gx + gw, gy + gh), 1)
        for wert, label in ((hmin, f"min {hmin:.2f}"), (hmax, f"max {hmax:.2f}")):
            lx = gx + int(wert * gw)
            pygame.draw.line(screen, theme.ACCENT, (lx, gy - 8), (lx, gy + gh + 4), 2)
            theme.text(screen, label, theme.SMALL, theme.ACCENT, (lx, gy + gh + 8),
                       center=True)
        theme.text(screen, "grau = alle Pixel      violett = in der Maske      (Wurzelskala)",
                   theme.SMALL, theme.TEXT_FAINT, (r.x + 12, r.bottom - 26),
                   max_w=r.width - 24)
