"""
Uhrabgleich mit dem Relay (NTP-Art) ueber die vorhandenen UDP PING/PONG.

Jeder Client kennt nur seine eigene ``time.monotonic()``. Damit der Empfaenger
eines STATE-Pakets weiss, wie alt dessen Lage beim Eintreffen ist, rechnet
jeder Client seine Uhr auf die **Uhr des Relays** um: das PONG traegt neben dem
zurueckgespiegelten PING-Stempel die Relayzeit ``Ts`` (``protocol.PONG_EXT_FMT``).

    Umlauf  rtt = t3 - t0            (t0 Absenden, t3 Eintreffen der Antwort)
    Versatz off = Ts - (t0 + t3) / 2 (Relayuhr minus eigene Uhr)

Der Versatz ist nur so genau wie die Strecke symmetrisch ist; der Fehler ist
hoechstens ``rtt / 2``. Darum gilt der Probe mit der **kleinsten Umlaufzeit**
(Warteschlangen machen die Laufzeit nur groesser, nie kleiner): aus den letzten
Proben zaehlen nur die, die hoechstens ``RTT_SPIEL`` ueber der kleinsten liegen,
und deren Versatz wird gemittelt. Der benutzte Versatz folgt diesem Ziel nur in
kleinen Schritten, damit gezeichnete Mitspieler nicht ruckeln, wenn eine andere
Probe die beste wird.

Sender und Empfaenger eines Pakets benutzen je ihren eigenen Versatz; die
Differenz beider ergibt das Alter des Pakets.
"""
from __future__ import annotations

import collections
import math

#: Wie viele Proben hinter dem Versatz stehen (bei einer Probe je Sekunde im
#: Betrieb rund eine halbe Minute) und wie alt eine Probe hoechstens sein darf.
PROBEN_MAX = 24
PROBE_ALTER_MAX = 40.0
#: Mindestzahl an Proben, ab der der Abgleich als brauchbar gilt.
PROBEN_MIN = 3
#: Eine Probe zaehlt zum besten Teil, wenn ihre Umlaufzeit hoechstens so viel
#: ueber der kleinsten liegt (Sekunden).
RTT_SPIEL = 0.003
#: Umlaufzeiten darueber sind kein Messwert mehr.
RTT_MAX = 1.5
#: Schrittweite beim Nachziehen des benutzten Versatzes: dieser Anteil der
#: Abweichung, mindestens jedoch SCHRITT_MIN (Sekunden) je neuer Probe.
SCHRITT_ANTEIL = 0.25
SCHRITT_MIN = 0.0003
#: Eine so grosse Abweichung ist ein Sprung der Uhr (Ruhezustand, Zeitumstellung
#: des Relays): dann wird sofort gesetzt.
SPRUNG = 0.25


class UhrSync:
    """Versatz zwischen der eigenen Uhr und der Relayuhr."""

    def __init__(self) -> None:
        # (t3, rtt, versatz)
        self._proben: collections.deque = collections.deque(maxlen=PROBEN_MAX)
        self._versatz: float | None = None
        self._anzahl = 0

    def probe(self, t0: float, t3: float, server_zeit: float) -> bool:
        """Eine PING/PONG-Runde eintragen. Gibt an, ob sie brauchbar war."""
        if not all(math.isfinite(v) for v in (t0, t3, server_zeit)):
            return False
        rtt = t3 - t0
        if rtt < 0.0 or rtt > RTT_MAX:
            return False
        versatz = server_zeit - (t0 + t3) * 0.5
        self._proben.append((t3, rtt, versatz))
        self._anzahl += 1
        while self._proben and t3 - self._proben[0][0] > PROBE_ALTER_MAX:
            self._proben.popleft()
        ziel = self._ziel()
        if ziel is None:
            return True
        if (self._versatz is None or self._anzahl <= PROBEN_MIN
                or abs(ziel - self._versatz) > SPRUNG):
            self._versatz = ziel
        else:
            diff = ziel - self._versatz
            schritt = max(SCHRITT_MIN, abs(diff) * SCHRITT_ANTEIL)
            self._versatz += math.copysign(min(abs(diff), schritt), diff)
        return True

    def _ziel(self) -> float | None:
        if not self._proben:
            return None
        kleinste = min(p[1] for p in self._proben)
        gute = [p[2] for p in self._proben if p[1] <= kleinste + RTT_SPIEL]
        return sum(gute) / len(gute)

    @property
    def gueltig(self) -> bool:
        """Ob schon genug Proben da sind, um der Uhr zu trauen."""
        return self._versatz is not None and self._anzahl >= PROBEN_MIN

    @property
    def versatz(self) -> float | None:
        """Relayuhr minus eigene Uhr (Sekunden), oder None, solange ungueltig."""
        return self._versatz if self.gueltig else None

    @property
    def kleinste_rtt(self) -> float | None:
        return min((p[1] for p in self._proben), default=None)

    @property
    def anzahl(self) -> int:
        return self._anzahl

    def relayzeit(self, eigene_zeit: float) -> float | None:
        v = self.versatz
        return None if v is None else eigene_zeit + v
