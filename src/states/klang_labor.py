"""Klang-Seite des Fahrzeuglabors — den Motorsound abstimmen (Releaseplan C8).

Aufbau **Variante C, Signalweg** (gewählt am 02.08.2026): fünf Stationen von
links nach rechts, jede mit ihren Reglern und einer kleinen Wellenform
*hinter* ihrer Stufe. Man sieht damit, an welcher Station ein Knacks entsteht,
statt ihn am Ausgang zu suchen und dann zu raten.

Zwei Ebenen, farblich getrennt: was für **jeden Motor einer Bauart** gilt
(``motorklang``) und die zwei Werte, die **ein Fahrzeug** ausmachen
(``klang_tonhoehe``, ``klang_faerbung`` in seiner JSON).

Gehört wird mit einem Drehzahlregler von Hand plus Gangwechsel: beim Schalten
springt die Drehzahl über die echte Übersetzung des Fahrzeugs, wie im Rennen.

Bedient wird über Schaltflächen, nicht über gemerkte Tasten — wie auf der
Lackier-Seite.
"""
from __future__ import annotations

import math

import numpy as np
import pygame

from src.core import display, motorklang, sfx
from src.ui import theme

#: Ausschnitt der Wellenform. Eine Motorstimme steuert mit rund 0,13 aus; bei
#: voller Skala wäre die Kurve ein Strich. Der Wert steht in der Beschriftung,
#: damit niemand die Aussteuerung falsch abliest.
WELLE_BEREICH = 0.35

#: (Station, Schlüssel, Beschriftung, Quelle, Einheit)
#: Quelle: "motor" = gilt für die Bauart, "fahrzeug" = nur dieses Auto,
#: "global" = für alle Motoren zusammen.
_REGLER: list[tuple[int, str, str, str, str]] = [
    (0, "schichtblende",      "Schichtüberblendung", "motor",    ""),
    (0, "grundpegel",         "Grundpegel",          "motor",    ""),
    (1, "blocklaenge",        "Blocklänge",          "motor",    ""),
    (1, "puffer",             "Puffer",              "global",   ""),
    (1, "drehzahlglaettung",  "Drehzahlglättung",    "motor",    " ms"),
    # Gegen die Schwebung zwischen zwei Fahrzeugen (03.08.2026). Allein zu
    # hören ist davon fast nichts — der Regler zeigt seine Wirkung erst, wenn
    # ein zweites Auto daneben fährt. Deshalb steht er hier und nicht bei der
    # Färbung: er gehört zur Bauart, nicht zum einzelnen Auto.
    (1, "zyklusstreuung",     "Zyklusstreuung",      "motor",    ""),
    (1, "streuung_hz",        "Streuungstempo",      "motor",    " Hz"),
    (2, "tonhoehe",           "Tonhöhe",             "fahrzeug", ""),
    (2, "faerbung",           "Färbung",             "fahrzeug", ""),
    (3, "hochpass_hz",        "Hochpass",            "motor",    " Hz"),
    (4, "begrenzer_schwelle", "Schwelle",            "motor",    ""),
    (4, "begrenzer_tempo_ms", "Tempo",               "motor",    " ms"),
]

#: Grenzen der beiden Fahrzeugwerte: (min, max, Schritt, Nachkommastellen).
#: Dieselbe Spanne, die ``Motorstimme`` ohnehin erzwingt — ein Regler, der über
#: seine Wirkung hinausläuft, wäre ein falsches Versprechen.
_FAHRZEUG_GRENZEN = {
    "tonhoehe": (0.9, 1.1, 0.01, 2),
    "faerbung": (-1.0, 1.0, 0.02, 2),
}

_STATIONEN = [
    ("1  AUFNAHMEN",   "Schichten mischen"),
    ("2  BLOCKGRENZEN", "Takt der Ausgabe"),
    ("3  FÄRBUNG",     "dieses Fahrzeug"),
    ("4  HOCHPASS",    "Rumpeln und Gleichanteil"),
    ("5  BEGRENZER",   "Spitzen weich fangen"),
]


class KlangLabor:
    """Zeichnet und bedient die Klang-Seite.

    Hält den Klang selbst: eine ``Motorstimme`` samt Mixerkanal. Die Werte
    liegen dagegen dort, wo sie hingehören — in ``motorklang`` und in der
    Fahrzeugkonfiguration —, damit ``Speichern`` im Labor sie ohne Umweg
    mitnimmt.
    """

    def __init__(self, labor) -> None:
        self.labor = labor              # VehicleLabState
        self.zeile = 0
        self.upm = 3000.0
        self.gang = 3
        self.hoeren = False
        self.stimme: sfx.Motorstimme | None = None
        self._kanal_nr: int | None = None
        self._signatur: tuple | None = None
        #: Der Klang an den fünf Stationen — Grundlage aller Anzeigen.
        self._stufen: list[np.ndarray] = []
        self._rects: dict[str, pygame.Rect] = {}
        self._pfeile: list[tuple[int, int, pygame.Rect]] = []

    # ------------------------------------------------------------------
    # Werte
    # ------------------------------------------------------------------
    def motor(self) -> str:
        """Motortyp des gewählten Fahrzeugs — über seine Klasse, wie im Rennen."""
        from src.core import sfx_rennen
        return sfx_rennen.motor_fuer_klasse(
            sfx_rennen.klasse_von_schluessel(self.labor._key))

    #: Damit ein Test die Reglerliste sieht, ohne das Modul zu importieren.
    _REGLER_TEST = _REGLER

    def _grenzen(self, schluessel: str, quelle: str):
        if quelle == "fahrzeug":
            return _FAHRZEUG_GRENZEN[schluessel]
        if quelle == "global":
            return motorklang.GLOBAL_GRENZEN[schluessel]
        return motorklang.GRENZEN[schluessel]

    def _lesen(self, schluessel: str, quelle: str) -> float:
        if quelle == "fahrzeug":
            cfg = self.labor._cfg()
            vorgabe = 1.0 if schluessel == "tonhoehe" else 0.0
            return float(getattr(cfg, f"klang_{schluessel}", vorgabe) if cfg else vorgabe)
        if quelle == "global":
            return float(motorklang.global_werte()[schluessel])
        return float(motorklang.werte(self.motor())[schluessel])

    def _schreiben(self, schluessel: str, quelle: str, wert: float) -> None:
        if quelle == "fahrzeug":
            lo, hi, _s, _d = _FAHRZEUG_GRENZEN[schluessel]
            cfg = self.labor._cfg()
            if cfg is not None:
                setattr(cfg, f"klang_{schluessel}", max(lo, min(hi, wert)))
        elif quelle == "global":
            motorklang.global_setzen(schluessel, wert)
        else:
            motorklang.setzen(self.motor(), schluessel, wert)
        self.labor.dirty = True

    def _verstellen(self, richtung: int) -> None:
        _st, schluessel, _lbl, quelle, _e = _REGLER[self.zeile]
        lo, hi, schritt, dez = self._grenzen(schluessel, quelle)
        neu = self._lesen(schluessel, quelle) + richtung * schritt
        self._schreiben(schluessel, quelle, round(max(lo, min(hi, neu)), dez + 2))

    def _zeile_weiter(self, richtung: int) -> None:
        self.zeile = (self.zeile + richtung) % len(_REGLER)

    def auf_vorgabe(self) -> None:
        """Diesen Motortyp zurücksetzen. Die Fahrzeugwerte bleiben — sie sind
        eine andere Ebene, und beides zugleich wegzuwerfen wäre eine
        Überraschung."""
        motorklang.auf_vorgabe(self.motor())
        self.labor.dirty = True
        self._signatur = None

    # ------------------------------------------------------------------
    # Gang und Drehzahl
    # ------------------------------------------------------------------
    def _uebersetzungen(self) -> list[float]:
        cfg = self.labor._cfg()
        r = list(getattr(cfg, "gear_ratios", []) or []) if cfg else []
        return r or [1.0]

    def schalten(self, d: int) -> None:
        """Gang wechseln — die Drehzahl springt mit, wie im Rennen.

        Genau dieser Sprung ist der Verdächtige: Tonhöhe und Schichtmischung
        wechseln zwischen zwei Blöcken.
        """
        r = self._uebersetzungen()
        neu = max(1, min(len(r), self.gang + d))
        if neu == self.gang:
            return
        self.upm = self._begrenzt(self.upm * (r[neu - 1] / r[self.gang - 1]))
        self.gang = neu

    def _nach_dem_schalten(self, d: int) -> float:
        """Was die Drehzahl nach einem Gangwechsel wäre — für die Anzeige."""
        r = self._uebersetzungen()
        neu = max(1, min(len(r), self.gang + d))
        return self._begrenzt(self.upm * (r[neu - 1] / r[self.gang - 1]))

    def _begrenzt(self, upm: float) -> float:
        lo, hi = sfx.schichten(self.motor()).bereich
        if hi <= lo:
            return max(0.0, upm)
        return max(float(lo), min(float(hi), upm))

    def drehzahl_verstellen(self, richtung: int) -> None:
        lo, hi = sfx.schichten(self.motor()).bereich
        schritt = max(10.0, (hi - lo) / 60.0)
        self.upm = self._begrenzt(self.upm + richtung * schritt)

    # ------------------------------------------------------------------
    # Klang erzeugen und abspielen
    # ------------------------------------------------------------------
    def _werte_stimme(self) -> dict:
        return motorklang.werte(self.motor())

    def _stimme_bauen(self) -> sfx.Motorstimme:
        stimme = sfx.Motorstimme(self.motor(),
                                 self._lesen("tonhoehe", "fahrzeug"),
                                 self._lesen("faerbung", "fahrzeug"),
                                 self._werte_stimme())
        return stimme

    def _signatur_jetzt(self) -> tuple:
        w = self._werte_stimme()
        return (self.labor._key, self.motor(), round(self.upm, 1), self.gang,
                self._lesen("tonhoehe", "fahrzeug"),
                self._lesen("faerbung", "fahrzeug"),
                tuple(sorted(w.items())))

    def _neu_rechnen(self) -> None:
        """Die fünf Stationen neu durchrechnen — nur bei echter Änderung.

        Gerechnet wird auf einer **eigenen** Stimme, nicht auf der spielenden:
        sonst würde jede Anzeige die Phase des laufenden Klangs weiterdrehen
        und ihn zerhacken.
        """
        sig = self._signatur_jetzt()
        if sig == self._signatur and self._stufen:
            return
        self._signatur = sig

        probe = self._stimme_bauen()
        if not probe:
            self._stufen = []
            return
        # Einschwingen lassen: der erste Block einer Stimme beginnt bei
        # Drehzahl null und sagt nichts über den eingeschwungenen Klang.
        for _ in range(4):
            probe.block(self.upm)
        roh = probe._erzeugen(probe._fuehren(self.upm, probe.blocklaenge),
                              probe.blocklaenge)
        nach_faerbung = probe.faerbung(roh)
        nach_hochpass = probe.hochpass(nach_faerbung)
        nach_begrenzer = probe.begrenzer(nach_hochpass)
        self._stufen = [roh, roh, nach_faerbung, nach_hochpass, nach_begrenzer]

    def update(self, dt: float) -> None:
        """Nachschieben, solange gehört wird — dieselbe Regel wie im Rennen:
        genau ein Block in der Warteschlange."""
        if not self.hoeren:
            return
        if self.stimme is None or not self.stimme:
            return
        kanal = self._kanal()
        if kanal is None:
            return
        try:
            if kanal.get_queue() is None:
                block = self.stimme.block(self.upm)
                stereo = np.repeat((block * 32767.0).astype(np.int16)[:, None], 2, axis=1)
                kanal.queue(pygame.sndarray.make_sound(np.ascontiguousarray(stereo)))
        except (pygame.error, ValueError):
            self.hoeren = False

    def _kanal(self):
        if not (pygame.mixer and pygame.mixer.get_init()):
            return None
        if self._kanal_nr is None:
            # Hinter den Einzelklängen, damit ein Menügeräusch die Probe nicht
            # abwürgt.
            nr = min(sfx.EINZEL_KANAELE, pygame.mixer.get_num_channels() - 1)
            if nr < 0:
                return None
            self._kanal_nr = nr
        try:
            return pygame.mixer.Channel(self._kanal_nr)
        except (pygame.error, IndexError):
            return None

    def hoeren_umschalten(self, an: bool | None = None) -> None:
        neu = (not self.hoeren) if an is None else bool(an)
        if neu == self.hoeren:
            return
        self.hoeren = neu
        if neu:
            self.stimme = self._stimme_bauen()
        else:
            self.stimme = None
            kanal = self._kanal()
            if kanal is not None:
                try:
                    kanal.stop()
                except pygame.error:
                    pass

    def werte_uebernehmen(self) -> None:
        """Geänderte Werte an die laufende Stimme geben, ohne sie neu zu bauen.

        Ein Neubau setzte Phase und Filterspeicher zurück — bei jedem
        Reglerklick ein Knacks, und ausgerechnet den sucht man hier.
        """
        if self.stimme is None:
            return
        self.stimme.tonhoehe = max(0.9, min(1.1, self._lesen("tonhoehe", "fahrzeug")))
        staerke = self._lesen("faerbung", "fahrzeug")
        if abs(staerke - self.stimme.faerbung.staerke) > 1e-6:
            rest = self.stimme.faerbung._rest
            erster = self.stimme.faerbung._erster
            self.stimme.faerbung = sfx.Faerbung(staerke)
            self.stimme.faerbung._rest = rest
            self.stimme.faerbung._erster = erster
        self.stimme.werte_setzen(self._werte_stimme())

    def beenden(self) -> None:
        self.hoeren_umschalten(False)

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
            if event.key in (pygame.K_LEFT, pygame.K_RIGHT):
                self._verstellen(-1 if event.key == pygame.K_LEFT else +1)
                self.werte_uebernehmen()
                return True
            if event.key == pygame.K_SPACE:
                self.hoeren_umschalten()
                return True
            return False

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for name, r in self._rects.items():
                if not r.collidepoint(event.pos):
                    continue
                return self._klick(name)
            for zeile, richtung, r in self._pfeile:
                if r.collidepoint(event.pos):
                    self.zeile = zeile
                    self._verstellen(richtung)
                    self.werte_uebernehmen()
                    return True
        elif event.type == pygame.MOUSEWHEEL:
            self.drehzahl_verstellen(1 if event.y > 0 else -1)
            return True
        return False

    def _klick(self, name: str) -> bool:
        if name == "fahrzeug_l":
            self.labor._fahrzeug_wechseln(-1)
        elif name == "fahrzeug_r":
            self.labor._fahrzeug_wechseln(+1)
        elif name == "gang_l":
            self.schalten(-1)
        elif name == "gang_r":
            self.schalten(+1)
        elif name == "upm_l":
            self.drehzahl_verstellen(-1)
        elif name == "upm_r":
            self.drehzahl_verstellen(+1)
        elif name == "hoeren":
            self.hoeren_umschalten(True)
        elif name == "stopp":
            self.hoeren_umschalten(False)
        elif name == "speichern":
            self.labor._save()
        elif name == "verwerfen":
            self.labor._verwerfen()
        elif name == "vorgabe":
            self.auf_vorgabe()
        elif name == "zurueck":
            self.labor.state_machine.zurueck()
            return True
        else:
            return False
        if name.startswith("fahrzeug"):
            # Anderes Auto, anderer Motortyp: die Stimme muss wirklich neu.
            if self.hoeren:
                self.stimme = self._stimme_bauen()
            self.gang = min(self.gang, len(self._uebersetzungen()))
            self.upm = self._begrenzt(self.upm)
        else:
            self.werte_uebernehmen()
        return True

    # ------------------------------------------------------------------
    # Zeichnen
    # ------------------------------------------------------------------
    def draw(self, screen: pygame.Surface, bereich: pygame.Rect) -> None:
        self._neu_rechnen()
        self._rects.clear()
        self._pfeile.clear()

        stationen_h = 320
        self._stationen_zeichnen(
            screen, pygame.Rect(bereich.x, bereich.y, bereich.width, stationen_h))

        y = bereich.y + stationen_h + 16
        ausgang_h = 268
        breit = int(bereich.width * 0.63)
        self._spektrum(screen, pygame.Rect(bereich.x, y, breit, ausgang_h))
        self._wellenform(screen,
                         pygame.Rect(bereich.x + breit + 16, y,
                                     bereich.width - breit - 16, ausgang_h),
                         self._stufe(4), titel="AUSGANG — WELLENFORM",
                         unter="derselbe Block, größer — hier sieht man einzelne Knacks")

        y += ausgang_h + 16
        self._drehzahlband(screen, pygame.Rect(bereich.x, y, bereich.width, 118))

        y += 132
        rest = bereich.bottom - y
        self._wiedergabe(screen, pygame.Rect(bereich.x, y, breit, min(112, rest)))
        self._knopfleiste(screen, pygame.Rect(bereich.x + breit + 16, y,
                                              bereich.width - breit - 16,
                                              min(112, rest)))

    def _stufe(self, i: int) -> np.ndarray:
        if i < len(self._stufen):
            return self._stufen[i]
        return np.zeros(64, dtype=np.float32)

    # -- Stationen ------------------------------------------------------
    def _stationen_zeichnen(self, screen, r: pygame.Rect) -> None:
        luecke = 12
        bw = (r.width - (len(_STATIONEN) - 1) * luecke) // len(_STATIONEN)
        for i, (titel, unter) in enumerate(_STATIONEN):
            x = r.x + i * (bw + luecke)
            kasten = pygame.Rect(x, r.y, bw, r.height)
            self._kasten(screen, kasten)
            theme.text(screen, titel, theme.HINT, theme.ACCENT_DIM,
                       (kasten.x + 12, kasten.y + 10))
            theme.text(screen, unter, theme.SMALL, theme.TEXT_FAINT,
                       (kasten.x + 12, kasten.y + 36), max_w=kasten.width - 24)
            self._mini_welle(screen,
                             pygame.Rect(kasten.x + 12, kasten.y + 62, kasten.width - 24, 92),
                             self._stufe(i), takt=(i == 1))
            y = kasten.y + 170
            for j, (station, schluessel, label, quelle, einheit) in enumerate(_REGLER):
                if station != i:
                    continue
                self._reglerzeile(screen, pygame.Rect(kasten.x + 10, y,
                                                      kasten.width - 20, 40),
                                  j, schluessel, label, quelle, einheit)
                y += 52
            if i < len(_STATIONEN) - 1:
                theme.text(screen, "›", theme.HEADER, theme.ACCENT_DIM,
                           (kasten.right + luecke // 2, kasten.centery), center=True)

    def _reglerzeile(self, screen, r: pygame.Rect, index: int, schluessel: str,
                     label: str, quelle: str, einheit: str) -> None:
        lo, hi, _schritt, dez = self._grenzen(schluessel, quelle)
        wert = self._lesen(schluessel, quelle)
        anteil = (wert - lo) / (hi - lo) if hi > lo else 0.0
        aktiv = (index == self.zeile)
        # Fahrzeugwerte anders eingefärbt: sie gelten nur für dieses eine Auto,
        # alles andere für jeden Motor derselben Bauart.
        eigen = (quelle == "fahrzeug")
        lc = theme.TEXT if aktiv else (theme.ACCENT_DIM if eigen else theme.TEXT_DIM)
        theme.text(screen, label, theme.SMALL, lc, (r.x + 30, r.y))
        theme.text(screen, f"{wert:.{dez}f}{einheit}", theme.SMALL,
                   theme.ACCENT if aktiv else theme.TEXT_DIM,
                   (r.right - 30, r.y), topright=True)
        bahn = pygame.Rect(r.x + 30, r.y + 22, r.width - 60, 8)
        pygame.draw.rect(screen, (30, 33, 44), bahn, border_radius=4)
        pygame.draw.rect(screen, (52, 56, 70), bahn, 1, border_radius=4)
        fw = int(bahn.width * max(0.0, min(1.0, anteil)))
        if fw > 0:
            pygame.draw.rect(screen, theme.ACCENT if aktiv else theme.ACCENT_DIM,
                             (bahn.x, bahn.y, fw, bahn.height), border_radius=4)
        knauf = pygame.Rect(0, 0, 8, 18)
        knauf.center = (bahn.x + fw, bahn.centery)
        pygame.draw.rect(screen, theme.ACCENT_HOT if aktiv else theme.TEXT_DIM,
                         knauf, border_radius=3)
        for x, glyph, richtung in ((r.x, "‹", -1), (r.right - 24, "›", +1)):
            kr = pygame.Rect(x, r.y + 6, 24, 30)
            self._pfeile.append((index, richtung, kr))
            hover = kr.collidepoint(display.mouse_pos())
            pygame.draw.rect(screen, (46, 50, 62) if hover else (28, 31, 40), kr,
                             border_radius=5)
            pygame.draw.rect(screen, theme.ACCENT_HOT if hover else theme.BORDER_LIGHT,
                             kr, 1, border_radius=5)
            theme.text(screen, glyph, theme.BODY,
                       theme.ACCENT_HOT if hover else theme.ACCENT, kr.center, center=True)

    # -- Anzeigen -------------------------------------------------------
    @staticmethod
    def _kasten(screen, r: pygame.Rect, *, rand=theme.BORDER) -> None:
        pygame.draw.rect(screen, (10, 12, 20), r, border_radius=6)
        pygame.draw.rect(screen, rand, r, 1, border_radius=6)

    def _mini_welle(self, screen, r: pygame.Rect, b: np.ndarray, *,
                    takt: bool = False) -> None:
        pygame.draw.rect(screen, (8, 10, 16), r, border_radius=4)
        pygame.draw.rect(screen, (40, 44, 58), r, 1, border_radius=4)
        mitte = r.centery
        pygame.draw.line(screen, (28, 32, 42), (r.x + 2, mitte), (r.right - 2, mitte), 1)
        if takt:
            # Die Blockgrenze sichtbar machen — hier fragt die Station danach.
            for y in range(r.y + 3, r.bottom - 3, 6):
                pygame.draw.line(screen, (60, 52, 30), (r.right - 2, y),
                                 (r.right - 2, y + 3), 1)
        n = len(b)
        if n < 2:
            return
        for px in range(2, r.width - 2):
            i0 = int(px * n / r.width)
            i1 = max(i0 + 1, int((px + 1) * n / r.width))
            st = b[i0:i1]
            yo = mitte - int(float(st.max()) / WELLE_BEREICH * (r.height - 8) / 2)
            yu = mitte - int(float(st.min()) / WELLE_BEREICH * (r.height - 8) / 2)
            pygame.draw.line(screen, (40, 110, 80),
                             (r.x + px, max(r.y + 2, yo)), (r.x + px, min(r.bottom - 2, yu)), 1)

    def _wellenform(self, screen, r: pygame.Rect, b: np.ndarray, *, titel: str,
                    unter: str = "") -> None:
        self._kasten(screen, r)
        theme.text(screen, titel, theme.HINT, theme.TEXT_DIM, (r.x + 12, r.y + 9))
        innen = pygame.Rect(r.x + 12, r.y + 40, r.width - 24, r.height - 74)
        mitte = innen.centery
        pygame.draw.line(screen, (34, 38, 50), (innen.x, mitte), (innen.right, mitte), 1)
        for anteil in (0.5, -0.5):
            y = mitte - int(anteil * innen.height / 2)
            for x in range(innen.x, innen.right, 8):
                pygame.draw.line(screen, (30, 34, 46), (x, y), (x + 4, y), 1)
        theme.text(screen, f"Ausschnitt ±{WELLE_BEREICH:.2f}", theme.SMALL,
                   (70, 74, 88), (innen.right - 4, innen.y + 2), topright=True)

        n = len(b)
        if n >= 2:
            punkte = []
            for px in range(innen.width):
                i0 = int(px * n / innen.width)
                i1 = max(i0 + 1, int((px + 1) * n / innen.width))
                st = b[i0:i1]
                x = innen.x + px

                def y_von(v: float) -> int:
                    return mitte - int(max(-1.2, min(1.2, v / WELLE_BEREICH))
                                       * innen.height / 2)

                pygame.draw.line(screen, (40, 90, 70), (x, y_von(float(st.max()))),
                                 (x, y_von(float(st.min()))), 1)
                punkte.append((x, y_von(float(st.mean()))))
            if len(punkte) > 1:
                pygame.draw.lines(screen, theme.SUCCESS, False, punkte, 1)
        if unter:
            theme.text(screen, unter, theme.SMALL, theme.TEXT_FAINT,
                       (r.x + 12, r.bottom - 24))

    def _spektrum(self, screen, r: pygame.Rect) -> None:
        """Logarithmische Frequenzachse — linear wäre die untere Hälfte, in der
        ein Motor lebt, auf zwei Zentimeter zusammengedrückt."""
        self._kasten(screen, r)
        theme.text(screen, "AUSGANG — FREQUENZBAND", theme.HINT, theme.TEXT_DIM,
                   (r.x + 12, r.y + 9))
        innen = pygame.Rect(r.x + 12, r.y + 40, r.width - 24, r.height - 82)
        f_lo, f_hi = 30.0, 16000.0
        lo, hi = math.log10(f_lo), math.log10(f_hi)

        def x_von(hz: float) -> int:
            return innen.x + int(innen.width * (math.log10(max(hz, f_lo)) - lo) / (hi - lo))

        for hz in (100, 1000, 10000):
            x = x_von(hz)
            pygame.draw.line(screen, (30, 34, 44), (x, innen.y), (x, innen.bottom), 1)
            theme.text(screen, f"{hz // 1000}k" if hz >= 1000 else str(hz),
                       theme.SMALL, (74, 78, 92), (x + 4, innen.bottom + 2))
        for pegel in (-20, -40, -60):
            y = innen.bottom - int(innen.height * (pegel + 80) / 80.0)
            pygame.draw.line(screen, (26, 30, 40), (innen.x, y), (innen.right, y), 1)
            theme.text(screen, str(pegel), theme.SMALL, (74, 78, 92), (innen.x + 2, y - 16))

        b = self._stufe(4)
        if len(b) >= 64:
            fenster = np.hanning(len(b))
            betrag = np.abs(np.fft.rfft(b * fenster)) / (len(b) / 2)
            freq = np.fft.rfftfreq(len(b), 1.0 / sfx.SR)
            db = 20.0 * np.log10(np.maximum(betrag, 1e-6))
            gueltig = (freq >= f_lo) & (freq <= f_hi)
            xs = [x_von(v) for v in freq[gueltig]]
            ys = (innen.bottom - (innen.height
                                  * (np.clip(db[gueltig], -80.0, 0.0) + 80.0) / 80.0))
            punkte = list(zip(xs, ys.astype(int)))
            for x, y in punkte:
                pygame.draw.line(screen, (36, 82, 62), (x, innen.bottom), (x, y), 1)
            if len(punkte) > 1:
                pygame.draw.lines(screen, theme.SUCCESS, False, punkte, 1)

        x = x_von(sfx.FAERBUNG_ECKE)
        pygame.draw.line(screen, theme.ACCENT, (x, innen.y), (x, innen.bottom), 1)
        theme.text(screen, "Färbung", theme.SMALL, theme.ACCENT, (x + 5, innen.y + 4))
        theme.text(screen, "was am Ende der Kette herauskommt", theme.SMALL,
                   theme.TEXT_FAINT, (r.x + 12, r.bottom - 24))

    def _drehzahlband(self, screen, r: pygame.Rect) -> None:
        """Das Drehzahlband mit den aufgenommenen Schichten.

        Der Kern der Seite: man sieht, zwischen welchen zwei Aufnahmen die
        aktuelle Drehzahl hängt und wie weit die Überblendung offen ist. Ohne
        das dreht man an der Blende, ohne zu wissen, ob sie gerade wirkt.
        """
        self._kasten(screen, r)
        theme.text(screen, "AUFGENOMMENE SCHICHTEN", theme.SMALL, theme.TEXT_FAINT,
                   (r.x + 14, r.y + 10))
        theme.text(screen, f"{int(self.upm)} UPM", theme.LABEL, theme.ACCENT_HOT,
                   (r.right - 14, r.y + 6), topright=True)
        sch = sfx.schichten(self.motor())
        lo, hi = sch.bereich
        bahn = pygame.Rect(r.x + 20, r.y + 46, r.width - 40, 16)
        pygame.draw.rect(screen, (22, 25, 33), bahn, border_radius=8)
        pygame.draw.rect(screen, (48, 52, 66), bahn, 1, border_radius=8)
        if hi <= lo:
            theme.text(screen, "keine Aufnahmen für diesen Motor", theme.HINT,
                       theme.TEXT_FAINT, bahn.center, center=True)
            return
        gew = sch.gewichte(self.upm, motorklang.werte(self.motor())["schichtblende"])
        for u, g in zip(sch.drehzahlen, gew):
            x = bahn.x + int(bahn.width * (u - lo) / max(1, hi - lo))
            h = 10 + int(18 * g)
            an = g > 0.01
            pygame.draw.line(screen, theme.ACCENT if an else (60, 64, 80),
                             (x, bahn.y - 6), (x, bahn.y - 6 - h), 3 if an else 1)
            theme.text(screen, str(u), theme.SMALL,
                       theme.ACCENT_DIM if an else (70, 74, 88),
                       (x, bahn.bottom + 6), center=True)
            if an:
                theme.text(screen, f"{g:.2f}", theme.SMALL, theme.ACCENT,
                           (x, bahn.y - 26 - h), center=True)
        x = bahn.x + int(bahn.width * (self.upm - lo) / max(1, hi - lo))
        pygame.draw.rect(screen, theme.ACCENT_HOT,
                         (x - 2, bahn.y - 2, 4, bahn.height + 4), border_radius=2)

    # -- Bedienung unten ------------------------------------------------
    def _wiedergabe(self, screen, r: pygame.Rect) -> None:
        self._kasten(screen, r)
        theme.text(screen, "WIEDERGABE", theme.SMALL, theme.TEXT_FAINT,
                   (r.x + 14, r.y + 8))
        lo, hi = sfx.schichten(self.motor()).bereich
        anteil = (self.upm - lo) / max(1.0, hi - lo)

        dz = pygame.Rect(r.x + 14, r.y + 34, int(r.width * 0.46), 40)
        theme.text(screen, "Drehzahl", theme.SMALL, theme.TEXT, (dz.x + 30, dz.y))
        theme.text(screen, f"{int(self.upm)} UPM", theme.SMALL, theme.ACCENT,
                   (dz.right - 30, dz.y), topright=True)
        bahn = pygame.Rect(dz.x + 30, dz.y + 22, dz.width - 60, 8)
        pygame.draw.rect(screen, (30, 33, 44), bahn, border_radius=4)
        fw = int(bahn.width * max(0.0, min(1.0, anteil)))
        if fw > 0:
            pygame.draw.rect(screen, theme.ACCENT, (bahn.x, bahn.y, fw, bahn.height),
                             border_radius=4)
        knauf = pygame.Rect(0, 0, 8, 18)
        knauf.center = (bahn.x + fw, bahn.centery)
        pygame.draw.rect(screen, theme.ACCENT_HOT, knauf, border_radius=3)
        for x, glyph, name in ((dz.x, "‹", "upm_l"), (dz.right - 24, "›", "upm_r")):
            kr = pygame.Rect(x, dz.y + 6, 24, 30)
            self._rects[name] = kr
            self._pfeilknopf(screen, kr, glyph)

        gr = pygame.Rect(dz.right + 16, r.y + 30, 230, 48)
        self._stepper(screen, gr, "", f"Gang {self.gang} / {len(self._uebersetzungen())}",
                      "gang")
        r_ = self._uebersetzungen()
        hoch = self._nach_dem_schalten(+1)
        runter = self._nach_dem_schalten(-1)
        theme.text(screen, f"hoch → {int(self._begrenzt(hoch))}   ·   "
                           f"runter → {int(self._begrenzt(runter))} UPM",
                   theme.SMALL, theme.TEXT_FAINT, (gr.x + 2, gr.bottom + 4))

        px = gr.right + 16
        for name, label, stil in (("hoeren", "● HÖREN", "primary"),
                                  ("stopp", "■ STOPP", "secondary")):
            b = pygame.Rect(px, r.y + 30, 108, 48)
            self._rects[name] = b
            an = (name == "hoeren") != self.hoeren
            self._knopf(screen, b, label, stil, hervor=not an)
            px += 116

    def _knopfleiste(self, screen, r: pygame.Rect) -> None:
        self._kasten(screen, r)
        st = pygame.Rect(r.x + 12, r.y + 10, r.width - 24, 44)
        cfg = self.labor._cfg()
        self._stepper(screen, st, "Fahrzeug",
                      f"{cfg.name if cfg else '?'}  "
                      f"{self.labor.veh_index + 1}/{max(1, len(self.labor.keys))}",
                      "fahrzeug")
        breite = (r.width - 24 - 3 * 8) // 4
        y = r.y + 60
        for i, (name, label, stil) in enumerate((
                ("speichern", "Speichern", "primary"),
                ("verwerfen", "Verwerfen", "secondary"),
                ("vorgabe", "Auf Vorgabe", "secondary"),
                ("zurueck", "‹ Zurück", "secondary"))):
            b = pygame.Rect(r.x + 12 + i * (breite + 8), y, breite, 42)
            self._rects[name] = b
            self._knopf(screen, b, label, stil)

    def _stepper(self, screen, r: pygame.Rect, label: str, wert: str, name: str) -> None:
        pygame.draw.rect(screen, theme.PANEL_LIGHT, r, border_radius=8)
        pygame.draw.rect(screen, theme.BORDER, r, 2, border_radius=8)
        sz = 42
        if label:
            links = pygame.Rect(r.right - min(250, r.width // 2), r.y + 4, sz, r.height - 8)
        else:
            # Ohne Beschriftung gehoert der Pfeil an den linken Rand — sonst
            # bleibt fuer den Wert ein Streifen uebrig und er wird abgeschnitten.
            links = pygame.Rect(r.x + 6, r.y + 4, sz, r.height - 8)
        rechts = pygame.Rect(r.right - sz - 6, r.y + 4, sz, r.height - 8)
        self._rects[f"{name}_l"] = links
        self._rects[f"{name}_r"] = rechts
        if label:
            theme.text_fit(screen, label, theme.BODY, theme.TEXT,
                           pygame.Rect(r.x + 16, r.y, links.left - r.x - 24, r.height))
        mp = display.mouse_pos()
        theme.text(screen, "‹", theme.HEADER,
                   theme.ACCENT_HOT if links.collidepoint(mp) else theme.ACCENT,
                   links.center, center=True)
        theme.text(screen, "›", theme.HEADER,
                   theme.ACCENT_HOT if rechts.collidepoint(mp) else theme.ACCENT,
                   rechts.center, center=True)
        theme.text_fit(screen, wert, theme.BODY, theme.TEXT,
                       pygame.Rect(links.right + 4, r.y,
                                   rechts.left - links.right - 8, r.height), center=True)

    def _pfeilknopf(self, screen, r: pygame.Rect, glyph: str) -> None:
        hover = r.collidepoint(display.mouse_pos())
        pygame.draw.rect(screen, (46, 50, 62) if hover else (28, 31, 40), r, border_radius=5)
        pygame.draw.rect(screen, theme.ACCENT_HOT if hover else theme.BORDER_LIGHT, r, 1,
                         border_radius=5)
        theme.text(screen, glyph, theme.BODY,
                   theme.ACCENT_HOT if hover else theme.ACCENT, r.center, center=True)

    def _knopf(self, screen, r: pygame.Rect, label: str, stil: str,
               *, hervor: bool = False) -> None:
        hover = r.collidepoint(display.mouse_pos()) or hervor
        if hover:
            fill = (70, 56, 22) if stil == "primary" else (46, 50, 62)
            rand = theme.ACCENT_HOT
        else:
            fill = (44, 38, 18) if stil == "primary" else (32, 36, 46)
            rand = theme.ACCENT if stil == "primary" else theme.BORDER_LIGHT
        pygame.draw.rect(screen, fill, r, border_radius=8)
        pygame.draw.rect(screen, rand, r, 2, border_radius=8)
        theme.text_fit(screen, label, theme.HINT, theme.TEXT, r.inflate(-12, 0),
                       center=True)
