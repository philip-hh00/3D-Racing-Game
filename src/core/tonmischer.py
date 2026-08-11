"""Ringpuffer und Mischer für den Motorklang — ohne Gerät (06.08.2026).

**Warum es das gibt.** Bis heute lag der Motorklang auf ``pygame.mixer``: das
Spiel legte einmal je **Bild** einen Block nach, und pygame nimmt genau einen
Block in die Warteschlange. Der Vorsprung war damit ein einziger Block, und der
Ton hing am Bildtakt. Auf einem Kopfhörer ging das knapp gut (zwei Störungen je
Runde), über Monitorlautsprecher nicht mehr: dort war **jede Sekunde** ein
Aussetzer zu hören — regelmäßig, was heißt, dass zwei Uhren gegeneinander liefen
und der eine Block Vorsprung regelmäßig aufgebraucht war.

So arbeitet kein Spiel, das auf fremden Rechnern laufen soll. Der übliche Aufbau
ist umgekehrt: der Treiber **ruft ab**, wenn er Ton braucht, und zwischen
Erzeuger und Treiber liegt ein Ringpuffer mit Vorrat. Genau das steht hier.

**Warum ohne Gerät.** Die Aufteilung ist Absicht. Dieses Modul rechnet nur und
kennt keine Soundkarte — dadurch ist der ganze heikle Teil (Ringpuffer,
Unterlauf, Lautstärkeverläufe) im Test vollständig nachstellbar, ohne dass ein
Gerät vorhanden sein muss. Das Gerät selbst hängt in ``tonausgabe.py`` daran.

**Drei Fäden, klar getrennt:**

* Der **Spielfaden** legt Stimmen an, setzt Drehzahl, Lautstärke und Panorama.
  Er blockiert nie und rechnet keinen Ton.
* Der **Erzeugerfaden** ruft :meth:`Mischer.erzeugen` auf, solange Platz im Ring
  ist. Dort läuft die eigentliche Synthese.
* Der **Audiofaden** des Treibers ruft :meth:`Mischer.abrufen` auf. Der Aufruf
  kopiert nur — er rechnet nichts, legt nichts an und wartet auf nichts. Das ist
  die wichtigste Regel überhaupt: was im Audiofaden hängt, hört man sofort.

**Der Ring ohne Sperre.** Ein Schreiber, ein Leser, zwei fortlaufende Zähler.
Der Schreiber erhöht ``_geschrieben`` **erst**, nachdem die Daten im Ring
stehen; der Leser erhöht ``_gelesen`` erst, nachdem er sie herausgeholt hat.
Damit sieht keiner der beiden je halbfertige Daten, und es braucht keine Sperre,
die den Audiofaden aufhalten könnte.

**Unterlauf.** Wenn doch einmal nichts da ist, wird nicht Stille ausgegeben. Eine
Lücke knackt, weil das Signal von seinem Wert auf null springt. Stattdessen läuft
der zuletzt ausgegebene Wert weich aus (:data:`AUSLAUF_FRAMES`). Das hört man als
ganz kurzes Nachlassen statt als Knacken — und der Zähler
:attr:`Mischer.unterlaeufe` sagt hinterher, wie oft es nötig war.
"""
from __future__ import annotations

import threading

import numpy as np

#: Über so viele Abtastwerte läuft das Signal bei einem Unterlauf aus. 64 sind
#: bei 48 kHz gut eine Millisekunde — kurz genug, um nicht als Verlangsamung
#: aufzufallen, lang genug, um den Sprung auf null zu vermeiden.
AUSLAUF_FRAMES = 64


class Stimme:
    """Eine Quelle im Mischer.

    *erzeuger* wird im **Erzeugerfaden** aufgerufen: ``erzeuger(n)`` liefert
    ``n`` Abtastwerte als einkanaliges float32. Alles, was die Quelle an
    Zustand braucht (Drehzahl etwa), gehört ihr selbst — der Mischer kennt nur
    Lautstärke und Lage im Raum.

    Lautstärke und Panorama setzt der **Spielfaden** über :meth:`einstellen`.
    Übernommen werden sie erst im nächsten erzeugten Block, und zwar als
    Verlauf über dessen Länge: ein Sprung in der Lautstärke ist selbst ein
    hörbares Knacken, und bei sechs Fahrzeugen passiert er ständig.
    """

    __slots__ = ("erzeuger", "_ziel", "_ist", "_beendet", "_stumm_seit")

    def __init__(self, erzeuger, links: float = 0.0, rechts: float = 0.0) -> None:
        self.erzeuger = erzeuger
        # Ein Tupel, das als Ganzes ersetzt wird. Die Zuweisung ist unteilbar,
        # deshalb sieht der Erzeugerfaden nie ein halb gesetztes Paar.
        self._ziel: tuple[float, float] = (links, rechts)
        self._ist: tuple[float, float] = (links, rechts)
        self._beendet = False

    def einstellen(self, links: float, rechts: float) -> None:
        """Aus dem Spielfaden: neue Lautstärke je Seite (0…1)."""
        self._ziel = (max(0.0, float(links)), max(0.0, float(rechts)))

    def beenden(self) -> None:
        """Stimme abmelden. Sie blendet über einen Block aus, statt zu brechen."""
        self._ziel = (0.0, 0.0)
        self._beendet = True

    @property
    def beendet(self) -> bool:
        return self._beendet

    @property
    def still(self) -> bool:
        """Ist die Stimme sowohl am Ziel als auch stumm?"""
        return self._ziel == (0.0, 0.0) and self._ist == (0.0, 0.0)


class Mischer:
    """Ringpuffer mit Vorrat zwischen Erzeugung und Ausgabe.

    *kapazitaet* und *vorrat* sind in Abtastwerten (je Kanal) angegeben. Der
    Vorrat ist der Kern der Sache und ein Abwägen: zu wenig, und ein
    Verzögerer im System reisst ein Loch; zu viel, und der Motor hinkt dem Gaspedal
    hörbar hinterher. Rund 85 ms sind der Punkt, an dem beides erträglich ist —
    fünf Bilder Reserve bei 60 Bildern je Sekunde, und eine Verzögerung, die bei
    einem Motorgeräusch niemand als solche erkennt.
    """

    def __init__(self, kapazitaet: int = 8192, vorrat: int = 4096,
                 stueck: int = 1024) -> None:
        if not (0 < vorrat < kapazitaet):
            raise ValueError("vorrat muss zwischen 0 und kapazitaet liegen")
        self.kapazitaet = int(kapazitaet)
        self.vorrat = int(vorrat)
        self.stueck = int(stueck)

        self._ring = np.zeros((self.kapazitaet, 2), dtype=np.float32)
        self._geschrieben = 0
        self._gelesen = 0

        #: Letzter ausgegebener Abtastwert je Kanal — Anker fürs Auslaufen.
        self._letzter = np.zeros(2, dtype=np.float32)

        self._stimmen: list[Stimme] = []
        # Nur um die Liste, nie um den Ring. Der Audiofaden fasst sie nicht an.
        self._schloss = threading.Lock()

        self.unterlaeufe = 0
        self.ausgegeben = 0
        self.erzeugt = 0

    # ── Spielfaden ──────────────────────────────────────────────────────────
    def stimme_anlegen(self, erzeuger, links: float = 0.0,
                       rechts: float = 0.0) -> Stimme:
        stimme = Stimme(erzeuger, links, rechts)
        with self._schloss:
            self._stimmen.append(stimme)
        return stimme

    @property
    def stimmen(self) -> int:
        with self._schloss:
            return len(self._stimmen)

    def alle_beenden(self) -> None:
        with self._schloss:
            for s in self._stimmen:
                s.beenden()

    # ── Erzeugerfaden ───────────────────────────────────────────────────────
    @property
    def fuellstand(self) -> int:
        """Wie viele Abtastwerte im Ring bereitliegen."""
        return self._geschrieben - self._gelesen

    def braucht_nachschub(self) -> bool:
        return self.fuellstand < self.vorrat

    def erzeugen(self) -> int:
        """Ein Stück erzeugen und in den Ring legen. Gibt die Länge zurück.

        Wird vom Erzeugerfaden in einer Schleife gerufen, solange
        :meth:`braucht_nachschub` wahr ist. Gibt 0 zurück, wenn kein Platz ist.
        """
        platz = self.kapazitaet - self.fuellstand
        laenge = min(self.stueck, platz)
        if laenge <= 0:
            return 0

        summe = np.zeros((laenge, 2), dtype=np.float32)
        with self._schloss:
            stimmen = list(self._stimmen)
        uebrig = []
        for stimme in stimmen:
            fertig = self._stimme_mischen(stimme, summe, laenge)
            if not fertig:
                uebrig.append(stimme)
        if len(uebrig) != len(stimmen):
            with self._schloss:
                self._stimmen = [s for s in self._stimmen if s in uebrig]

        # Erst schreiben, dann den Zähler erhöhen — sonst liest der Audiofaden
        # Daten, die noch gar nicht dastehen.
        self._in_ring(summe, laenge)
        self._geschrieben += laenge
        self.erzeugt += laenge
        return laenge

    def _stimme_mischen(self, stimme: Stimme, summe: np.ndarray,
                        laenge: int) -> bool:
        """Eine Stimme dazumischen. Gibt True, wenn sie abgeräumt werden kann."""
        ziel = stimme._ziel          # einmal lesen: der Spielfaden schreibt weiter
        ist = stimme._ist
        if ziel == (0.0, 0.0) and ist == (0.0, 0.0):
            # Nichts zu hören. Der Erzeuger wird trotzdem nicht gerufen — das
            # spart bei sechs Fahrzeugen die Synthese fuer die stummen.
            return stimme.beendet

        try:
            roh = stimme.erzeuger(laenge)
        except Exception:
            # Eine kaputte Quelle darf den ganzen Ton nicht mitreissen.
            stimme._ist = (0.0, 0.0)
            return True
        if roh is None or len(roh) != laenge:
            stimme._ist = (0.0, 0.0)
            return stimme.beendet

        roh = np.asarray(roh, dtype=np.float32)
        # Lautstaerke als Verlauf, nicht als Sprung: ein Sprung ist selbst ein
        # Knacken, und bei sechs fahrenden Autos passiert er in jedem Block.
        for kanal in (0, 1):
            a, b = ist[kanal], ziel[kanal]
            if a == b:
                if b != 0.0:
                    summe[:, kanal] += roh * b
            else:
                verlauf = np.linspace(a, b, laenge, endpoint=False,
                                      dtype=np.float32)
                summe[:, kanal] += roh * verlauf
        stimme._ist = ziel
        return stimme.beendet and ziel == (0.0, 0.0)

    def _in_ring(self, daten: np.ndarray, laenge: int) -> None:
        anfang = self._geschrieben % self.kapazitaet
        ende = anfang + laenge
        if ende <= self.kapazitaet:
            self._ring[anfang:ende] = daten
        else:
            erste = self.kapazitaet - anfang
            self._ring[anfang:] = daten[:erste]
            self._ring[:laenge - erste] = daten[erste:]

    # ── Audiofaden ──────────────────────────────────────────────────────────
    def abrufen(self, frames: int) -> np.ndarray:
        """Die nächsten *frames* Abtastwerte, zweikanalig.

        **Der Audiofaden ruft das auf.** Deshalb wird hier nur kopiert: keine
        Synthese, keine Sperre, kein Warten. Was hier hängt, hört man sofort.
        """
        aus = np.empty((frames, 2), dtype=np.float32)
        da = min(frames, self.fuellstand)

        if da > 0:
            anfang = self._gelesen % self.kapazitaet
            ende = anfang + da
            if ende <= self.kapazitaet:
                aus[:da] = self._ring[anfang:ende]
            else:
                erste = self.kapazitaet - anfang
                aus[:erste] = self._ring[anfang:]
                aus[erste:da] = self._ring[:da - erste]
            self._gelesen += da
            self._letzter = aus[da - 1].copy()

        if da < frames:
            # Unterlauf. Nicht auf null springen — das ist genau das Knacken,
            # gegen das dieser ganze Umbau gemacht ist.
            self.unterlaeufe += 1
            self._auslaufen(aus, da, frames)

        self.ausgegeben += frames
        return aus

    def _auslaufen(self, aus: np.ndarray, ab: int, frames: int) -> None:
        fehlt = frames - ab
        laenge = min(fehlt, AUSLAUF_FRAMES)
        if laenge > 0 and np.any(self._letzter):
            blende = np.linspace(1.0, 0.0, laenge, endpoint=False,
                                 dtype=np.float32)[:, None]
            aus[ab:ab + laenge] = self._letzter[None, :] * blende
        else:
            laenge = 0
        aus[ab + laenge:] = 0.0
        self._letzter[:] = 0.0
