"""Fahrhilfen eines Menschen: ABS und Traktionskontrolle (Plan 1.1.0, Punkt 3).

Gilt **nur** für Fahrzeuge, denen der Rennzustand ein :class:`Fahrhilfen`-Objekt
gibt — das ist der menschliche Spieler, wenn er die Hilfe eingeschaltet hat. Die
KI, Ghosts und die Abbilder der Mitspieler online haben keines; ohne Objekt
läuft ``Vehicle.update`` Zeile für Zeile wie vorher. Online ist die Hilfe damit
eine reine Sache des eigenen Rechners: sie ändert, welche Eingabe die Physik
dieses einen Autos sieht, und sonst nichts. Über das Netz geht nichts Neues.

**Was die Physik hier kennt.** Die Bremse ist eine Verzögerung gegen die
Fahrtrichtung (``PhysicsBody.apply_brake_force``), ohne eigenes Reifenlimit;
die Antriebskraft dagegen wird an der angetriebenen Achse auf Haftung × Achslast
gekappt (``apply_drive_force``) — was darüber liegt, verpufft als Durchdrehen
(``PhysicsBody.antriebs_ueberschuss``). Daran hängen die Hilfen:

* **Traktionskontrolle** nimmt Gas weg, bis die Achse die Kraft gerade noch
  überträgt (Rückkopplung über ``antriebs_ueberschuss_min``), und weiter, wenn die
  angetriebene Achse über das Haftungsmaximum hinaus schräg läuft (Heck kommt,
  Vorderachse schiebt). Beschleunigung gleich, Reifenrauch weg.
* **ABS** nimmt Bremsdruck weg, wenn eine Achse über dem Haftungsmaximum
  rutscht (Schräglauf über ``SCHLUPF_SPITZE_DEG``) oder die Seitenhaftung schon
  ausgereizt ist (Reibkreis: wer quer alles braucht, hat längs nichts mehr).
  Geradeaus nichts: dort bremst das Auto wie ohne Hilfe, sein Bremsweg bleibt.

Die Handbremse bleibt außen vor — wer sie zieht, will das Heck lösen.
"""
from __future__ import annotations

import math

from src.entities.components.physics_body import PhysicsBody

#: Unter diesem Tempo (px/s, ~10 km/h) greift kein ABS: ein Auto, das kriecht,
#: soll ganz zum Stehen kommen.
MIN_TEMPO = 22.0

#: Kleinster Anteil, auf den die Hilfen Gas bzw. Bremse zurücknehmen.
MIN_GAS = 0.18
MIN_BREMSE = 0.30

#: ABS: ab welchem Schräglauf (Grad) Bremsdruck weggenommen wird, und bei welchem
#: Winkel die volle Wirkung (``ABS_TIEF``) erreicht ist. Das Maximum der
#: Reifenkennlinie liegt bei ``PhysicsBody.SCHLUPF_SPITZE_DEG``.
ABS_SCHLUPF_AB = PhysicsBody.SCHLUPF_SPITZE_DEG
ABS_SCHLUPF_VOLL = 20.0
#: ABS: ab welcher Auslastung der Seitenhaftung (1 = am Limit) der Reibkreis
#: den Bremsdruck beschneidet, und voll bei.
ABS_QUER_AB = 0.9
ABS_QUER_VOLL = 1.8
#: Wie weit ABS den Druck höchstens drosselt (Rest bleibt als Bremse).
ABS_TIEF = 0.7
#: Zeitkonstanten (s): schnell lösen, etwas langsamer wieder aufbauen.
ABS_LOESEN_S = 0.03
ABS_AUFBAUEN_S = 0.12

#: Traktionskontrolle: Überschuss (Anteil der Kraft, der nicht ankommt), ab dem
#: Gas weggenommen wird, und das Ziel, das knapp unterhalb der Grenze liegt.
TC_UEBERSCHUSS_AB = 0.04
TC_RESERVE = 1.0
#: Anteil des Gaspedals, der pro Sekunde wiederkommt, solange nichts durchdreht.
TC_ERHOLUNG_JE_S = 0.8
#: Schräglauf der angetriebenen Achse (Grad), ab dem TC zusätzlich dämpft.
TC_SCHLUPF_AB = PhysicsBody.SCHLUPF_SPITZE_DEG
TC_SCHLUPF_VOLL = 22.0


def _glatt(a: float, b: float, x: float) -> float:
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3.0 - 2.0 * t)


class Fahrhilfen:
    """Zustand und Regeln von ABS und Traktionskontrolle für **ein** Auto."""

    def __init__(self, abs_an: bool = False, tc_an: bool = False) -> None:
        self.abs_an = bool(abs_an)
        self.tc_an = bool(tc_an)
        #: Aktueller Faktor auf Bremse bzw. Gas (1 = unberührt).
        self.bremse_faktor = 1.0
        self.gas_faktor = 1.0
        #: Eingriff dieses Bildes, 0..1 — für Anzeige und Vibration.
        self.abs_eingriff = 0.0
        self.tc_eingriff = 0.0

    # -- Aufruf aus Vehicle.update ------------------------------------------
    def anwenden(self, fahrzeug, gas: float, bremse: float, dt: float) -> tuple[float, float]:
        """Die Eingaben, die die Physik wirklich sieht: ``(gas, bremse)``."""
        koerper = fahrzeug.physics
        tempo = koerper.body.velocity.length
        hand = bool(fahrzeug.handbrake)
        if self.abs_an and bremse > 0.0 and not hand and tempo >= MIN_TEMPO:
            bremse = self._abs(koerper, bremse, dt)
        else:
            self._abs_ruhe(dt)
        # Traktionskontrolle gerade beim Anfahren — daher ohne Tempogrenze.
        if self.tc_an and gas > 0.0 and not hand:
            gas = self._tc(fahrzeug, koerper, gas, dt)
        else:
            self._tc_ruhe(dt)
        return gas, bremse

    # -- ABS ------------------------------------------------------------------
    def _abs(self, koerper: PhysicsBody, bremse: float, dt: float) -> float:
        schlupf = max(koerper.vorn_schlupf_deg, koerper.hinten_schlupf_deg)
        quer = max(koerper.quer_auslastung)
        k_schlupf = 1.0 - ABS_TIEF * _glatt(ABS_SCHLUPF_AB, ABS_SCHLUPF_VOLL, schlupf)
        k_quer = 1.0 - ABS_TIEF * 0.6 * _glatt(ABS_QUER_AB, ABS_QUER_VOLL, quer)
        ziel = max(MIN_BREMSE, min(k_schlupf, k_quer))
        tau = ABS_LOESEN_S if ziel < self.bremse_faktor else ABS_AUFBAUEN_S
        self.bremse_faktor += (ziel - self.bremse_faktor) * min(1.0, dt / tau)
        self.abs_eingriff = max(0.0, 1.0 - self.bremse_faktor)
        return bremse * self.bremse_faktor

    def _abs_ruhe(self, dt: float) -> None:
        self.bremse_faktor += (1.0 - self.bremse_faktor) * min(1.0, dt / ABS_AUFBAUEN_S)
        self.abs_eingriff = max(0.0, 1.0 - self.bremse_faktor) if self.abs_an else 0.0

    # -- Traktionskontrolle ---------------------------------------------------
    def _tc(self, fahrzeug, koerper: PhysicsBody, gas: float, dt: float) -> float:
        antrieb = str(getattr(fahrzeug.config, "drive_type", "rwd") or "rwd").lower()
        if antrieb == "fwd":
            schlupf = koerper.vorn_schlupf_deg
        elif antrieb == "awd":
            schlupf = max(koerper.vorn_schlupf_deg, koerper.hinten_schlupf_deg)
        else:
            schlupf = koerper.hinten_schlupf_deg
        ueberschuss = koerper.antriebs_ueberschuss_min
        faktor = self.gas_faktor
        if ueberschuss > TC_UEBERSCHUSS_AB:
            # Kraft ~ Gas: genau so viel weniger Gas, wie über der Grenze lag,
            # und etwas darunter, damit die Achse nicht gleich wieder kippt.
            faktor *= (1.0 - ueberschuss) * TC_RESERVE
        else:
            faktor = min(1.0, faktor + TC_ERHOLUNG_JE_S * dt)
        faktor = max(MIN_GAS, faktor)
        # Schräglauf der angetriebenen Achse über dem Maximum: zusätzlich weg.
        zusatz = 1.0 - 0.7 * _glatt(TC_SCHLUPF_AB, TC_SCHLUPF_VOLL, schlupf)
        self.gas_faktor = faktor
        wirksam = max(MIN_GAS, faktor * zusatz)
        self.tc_eingriff = max(0.0, 1.0 - wirksam)
        return gas * wirksam

    def _tc_ruhe(self, dt: float) -> None:
        self.gas_faktor = min(1.0, self.gas_faktor + TC_ERHOLUNG_JE_S * dt)
        self.tc_eingriff = 0.0
