"""Controller-Vibration im Rennen (Plan 1.1.0, Punkt 6).

Ein :class:`Vibration` gehört zu **einem** Menschen am Steuer und kennt dessen
Controller. Jeder Spieler im Splitscreen hat seinen eigenen; die Tastatur hat
keinen. Die Anlässe:

* **Treffer** (Fahrzeug, Wand): ein kurzer Stoß, Stärke und Dauer nach dem
  Impuls — dieselben Schwellen wie der Aufprallklang (``sfx_rennen``).
* **Wandschleifen**: gleichmäßiges Brummen, solange das Auto die Wand berührt.
* **Rutschen**: tiefes, gleichmäßiges Grollen nach dem Reifenschlupf, den auch
  Reifenspuren und Quietschen nutzen.
* **Randstein**: kurze, schnelle Schläge auf dem hohen Motor, im Takt des Tempos.

Gestellt wird ein Regler im Profil (``fahrhilfen["vibration"]``, 0 = Aus bis 3 =
Stark); er skaliert alles. Ein Controller ohne Rumble oder ein Fehler im Treiber
darf **nie** ein Rennen stören: jeder Aufruf an das Gerät steckt in
``try/except``, und fehlt die Unterstützung einmal, wird sie nicht
sofort wieder versucht (``SPERRE_S``).

Die Ausgabe geht über ``ausgabe(index, tief, hoch, ms)`` (Vorgabe:
``gamepad.rumble``) — im Test ein Spion, im Spiel der echte Controller. Es wird
nicht jedes Bild ans Gerät geschickt, sondern nur bei merklicher Änderung oder
alle ``ERNEUERN_S`` Sekunden (die Dauer jedes Befehls ist kurz, damit ein
vergessener Befehl von selbst verklingt).
"""
from __future__ import annotations

import math

#: Faktor je Stufe des Reglers: Aus, Schwach, Mittel, Stark.
STAERKEN = (0.0, 0.45, 0.75, 1.0)

#: Treffer: darunter nichts, ab ``IMPULS_VOLL`` die volle Wucht (wie sfx_rennen).
IMPULS_AB = 500.0
IMPULS_VOLL = 8000.0
#: Länge eines Stoßes (s): leichter Treffer .. schwerer Treffer.
STOSS_DAUER_S = (0.10, 0.45)

#: Ab diesem Reifenschlupf (0..1, wie ``reifenspuren.reifenschlupf``) rumpelt es.
SCHLUPF_AB = 0.2
SCHLUPF_STAERKE = 0.55
#: Wandschleifen (konstant) und Randstein (Schlag, Takt in s bei Höchsttempo/Schritttempo).
WAND_STAERKE = 0.5
RANDSTEIN_STAERKE = 0.7
RANDSTEIN_TAKT_S = (0.08, 0.18)
RANDSTEIN_SCHLAG_S = 0.04
#: Unter diesem Tempo (m/s) rumpelt nichts durch Rutschen oder Randstein.
MIN_TEMPO_MS = 2.0
TEMPO_VOLL_MS = 45.0

#: Nur senden, wenn sich eine Stufe um so viel geändert hat, oder nach so vielen
#: Sekunden erneuern (jeder Befehl dauert ``BEFEHL_MS``).
AENDERUNG = 0.06
ERNEUERN_S = 0.10
BEFEHL_MS = 160
#: So lange wird nach einem fehlgeschlagenen Befehl nichts mehr gesendet (s).
SPERRE_S = 5.0


def stufe_faktor(stufe: int) -> float:
    """Faktor zu einer Reglerstufe 0..3; Unsinn ergibt Aus."""
    try:
        i = int(stufe)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return STAERKEN[i] if 0 <= i < len(STAERKEN) else 0.0


def stoss_aus_impuls(impuls: float) -> tuple[float, float, float]:
    """Ein Treffer als ``(tief, hoch, dauer_s)`` — 0, 0, 0 unterhalb der Schwelle.

    Der tiefe Motor trägt die Wucht, der hohe den Schlag; ein leichter Treffer
    ist ein kurzes Klopfen, ein schwerer ein langes Poltern.
    """
    try:
        impuls = float(impuls)
    except (TypeError, ValueError):
        return 0.0, 0.0, 0.0
    if not math.isfinite(impuls) or impuls < IMPULS_AB:
        return 0.0, 0.0, 0.0
    anteil = min(1.0, (impuls - IMPULS_AB) / (IMPULS_VOLL - IMPULS_AB))
    wucht = 0.35 + 0.65 * anteil ** 0.7
    dauer = STOSS_DAUER_S[0] + (STOSS_DAUER_S[1] - STOSS_DAUER_S[0]) * anteil
    return wucht, min(1.0, wucht * 0.9), dauer


def pad_index_von(quelle) -> int | None:
    """Welcher Controller zu einer Eingabequelle gehört (None: Tastatur / keiner)."""
    if quelle is None:
        return None
    index = getattr(quelle, "index", None)
    if isinstance(index, int) and not isinstance(index, bool):
        return index                              # GamepadSource
    if hasattr(quelle, "_pad"):
        return pad_index_von(quelle._pad)         # Tastatur + erster Controller
    return None


class Vibration:
    """Rumble eines Spielers: Anlässe sammeln, in Befehle an den Controller fassen."""

    def __init__(self, pad_index: int | None, stufe: int = 2, ausgabe=None,
                 stopp=None) -> None:
        self.pad_index = pad_index
        self.faktor = stufe_faktor(stufe)
        if ausgabe is None:
            from src.core import gamepad
            ausgabe = gamepad.rumble
            stopp = stopp or gamepad.stop_rumble
        self._ausgabe = ausgabe
        self._stopp = stopp
        #: Stoß in Arbeit: (tief, hoch, Restzeit, Gesamtzeit)
        self._stoss: tuple[float, float, float, float] | None = None
        self._randstein_uhr = 0.0
        self._schlag_rest = 0.0
        #: Zuletzt gesendet: (tief, hoch) und Zeit seitdem.
        self._gesendet = (0.0, 0.0)
        self._seit = 99.0
        #: Sekunden, die nach einem Fehlschlag nicht erneut gesendet wird
        #: (Pad ohne Rumble, abgezogen); danach wird es noch einmal versucht.
        self._sperre = 0.0

    # -- Einstellung -------------------------------------------------------------
    def stufe_setzen(self, stufe: int) -> None:
        self.faktor = stufe_faktor(stufe)
        if self.faktor <= 0.0:
            self.stoppen()

    @property
    def aktiv(self) -> bool:
        return self.faktor > 0.0 and self.pad_index is not None

    # -- Anlässe -----------------------------------------------------------------
    def stoss(self, impuls: float) -> None:
        """Ein Treffer mit diesem Impuls (Fahrzeug oder Wand)."""
        if not self.aktiv:
            return
        tief, hoch, dauer = stoss_aus_impuls(impuls)
        if dauer <= 0.0:
            return
        if self._stoss is not None and self._stoss[2] > dauer and self._stoss[0] >= tief:
            return                                  # ein stärkerer läuft noch
        self._stoss = (tief, hoch, dauer, dauer)

    # -- Bild für Bild -------------------------------------------------------------
    def fortschreiben(self, dt: float, schlupf: float = 0.0, wand: bool = False,
                      randstein: bool = False, tempo_ms: float = 0.0) -> None:
        """Einmal je Bild: aus Zustand und laufendem Stoß den Befehl bilden und senden."""
        if not self.aktiv:
            return
        dt = max(0.0, min(float(dt), 0.1))
        if self._sperre > 0.0:
            self._sperre -= dt
            return
        tief = hoch = 0.0
        rasen = max(0.0, min(1.0, (tempo_ms - MIN_TEMPO_MS) / (TEMPO_VOLL_MS - MIN_TEMPO_MS)))

        if self._stoss is not None:
            s_tief, s_hoch, rest, gesamt = self._stoss
            rest -= dt
            if rest <= 0.0:
                self._stoss = None
            else:
                self._stoss = (s_tief, s_hoch, rest, gesamt)
                abklang = rest / gesamt
                tief = max(tief, s_tief * abklang ** 0.5)
                hoch = max(hoch, s_hoch * abklang)

        if wand:
            tief = max(tief, WAND_STAERKE * (0.4 + 0.6 * rasen))
            hoch = max(hoch, WAND_STAERKE * 0.8 * (0.4 + 0.6 * rasen))

        if schlupf > SCHLUPF_AB and tempo_ms > MIN_TEMPO_MS:
            tief = max(tief, SCHLUPF_STAERKE * min(1.0, (schlupf - SCHLUPF_AB) / (1.0 - SCHLUPF_AB) + 0.25))

        if randstein and tempo_ms > MIN_TEMPO_MS:
            takt = RANDSTEIN_TAKT_S[1] + (RANDSTEIN_TAKT_S[0] - RANDSTEIN_TAKT_S[1]) * rasen
            self._randstein_uhr += dt
            if self._randstein_uhr >= takt:
                self._randstein_uhr = 0.0
                self._schlag_rest = RANDSTEIN_SCHLAG_S
            if self._schlag_rest > 0.0:
                self._schlag_rest -= dt
                hoch = max(hoch, RANDSTEIN_STAERKE * (0.5 + 0.5 * rasen))
        else:
            self._randstein_uhr = 0.0
            self._schlag_rest = 0.0

        self._senden(tief * self.faktor, hoch * self.faktor, dt)

    # -- Ausgabe ------------------------------------------------------------------
    def _senden(self, tief: float, hoch: float, dt: float) -> None:
        tief, hoch = min(1.0, max(0.0, tief)), min(1.0, max(0.0, hoch))
        self._seit += dt
        alt_tief, alt_hoch = self._gesendet
        if tief <= 0.0 and hoch <= 0.0:
            if alt_tief > 0.0 or alt_hoch > 0.0:
                self.stoppen()
            return
        geaendert = abs(tief - alt_tief) > AENDERUNG or abs(hoch - alt_hoch) > AENDERUNG
        if not geaendert and self._seit < ERNEUERN_S:
            return
        try:
            ok = self._ausgabe(self.pad_index, tief, hoch, BEFEHL_MS)
        except Exception:
            ok = False
        self._seit = 0.0
        if ok is False:
            # Gerät ohne Rumble (oder Treiberfehler): nicht jedes Bild neu versuchen.
            self._sperre = SPERRE_S
            self._gesendet = (0.0, 0.0)
            return
        self._gesendet = (tief, hoch)

    def stoppen(self) -> None:
        """Alles aus — beim Pausieren, am Ziel und beim Verlassen des Rennens."""
        self._stoss = None
        self._schlag_rest = 0.0
        if self.pad_index is None:
            return
        if self._gesendet != (0.0, 0.0) and self._stopp is not None:
            try:
                self._stopp(self.pad_index)
            except Exception:
                pass
        self._gesendet = (0.0, 0.0)
