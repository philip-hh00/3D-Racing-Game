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
import time

import numpy as np

#: Über so viele Abtastwerte läuft das Signal bei einem Unterlauf aus. 64 sind
#: bei 48 kHz gut eine Millisekunde — kurz genug, um nicht als Verlangsamung
#: aufzufallen, lang genug, um den Sprung auf null zu vermeiden.
AUSLAUF_FRAMES = 64

#: Ab diesem Betrag beginnt der Weichbegrenzer. Darunter bleibt das Signal
#: **unverändert** (ein einzelner Motor erreicht etwa 0,6).
KNIE = 0.7

#: Beim Verkleinern der Rate um mehr als diesen Faktor wird vorher tiefpass-
#: gefiltert (sonst spiegeln sich Anteile ueber der neuen Nyquist nach unten:
#: Bluetooth-Freisprechgeraete mit 16/32 kHz).
AA_AB = 1.2
AA_TAPS = 63


def weich_begrenzen(x: np.ndarray, knie: float = KNIE) -> np.ndarray:
    """Weiche Begrenzung der Summe auf höchstens ±1.

    Die Summe mehrerer Motoren kann über 1,0 liegen (gemessen: 1,05 schon bei
    einem Gegner in 100 px). Was der Treiber dann mit dem Überschuss tut, hängt
    vom Gerät ab — hartes Abschneiden, Verzerren, Lauterregeln des
    Systemlimiters — und klingt je nach Ausgabegerät verschieden schlecht.
    Hier wird es vorher und gerätunabhängig getan: unter dem Knie linear,
    darüber ein tanh-Auslauf mit gleicher Steigung am Knie (stetig, monoton).
    """
    x = np.asarray(x, dtype=np.float32)
    a = np.abs(x)
    if not np.any(a > knie):
        return x
    rest = 1.0 - knie
    ueber = knie + rest * np.tanh((a - knie) / rest)
    return np.where(a > knie, np.sign(x) * ueber, x).astype(np.float32)


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
                 stueck: int = 1024, quellrate: int = 48000,
                 ausgaberate: int | None = None,
                 begrenzen: bool = False, ring: np.ndarray | None = None,
                 zaehler: np.ndarray | None = None,
                 bei_entfernt=None) -> None:
        if not (0 < vorrat < kapazitaet):
            raise ValueError("vorrat muss zwischen 0 und kapazitaet liegen")
        #: Rate der Stimmen (Aufnahmen) und Rate des Geräts. Weichen sie ab,
        #: rechnet der **Erzeugerfaden** um — nie der Audiofaden.
        self.quellrate = int(quellrate)
        #: Weichbegrenzer auf der Summe. Das Geraet schaltet ihn ein; reine
        #: Transporttests (Zaehlerrampen weit ueber 1) lassen ihn aus.
        self.begrenzen = bool(begrenzen)
        self.ausgaberate = int(ausgaberate or quellrate)
        self._umr_pos = 1.0
        self._umr_letzter = np.zeros(2, dtype=np.float32)
        self.kapazitaet = int(kapazitaet)
        self.vorrat = int(vorrat)
        self.stueck = int(stueck)

        #: Ring und Zaehler koennen in einem gemeinsamen Speicher liegen
        #: (``tonprozess``): der Erzeuger laeuft dann in einem anderen Prozess
        #: und der Audiofaden hier liest nur. ``_z`` = geschrieben, gelesen,
        #: groesster Abruf.
        self._ring = (ring if ring is not None
                      else np.zeros((self.kapazitaet, 2), dtype=np.float32))
        if zaehler is None:
            self._z = np.zeros(4, dtype=np.int64)
        else:
            self._z = zaehler
        #: Wird mit jeder Stimme gerufen, die der Mischer abraeumt.
        self.bei_entfernt = bei_entfernt

        #: Letzter ausgegebener Abtastwert je Kanal — Anker fürs Auslaufen.
        self._letzter = np.zeros(2, dtype=np.float32)

        self._stimmen: list[Stimme] = []
        # Nur um die Liste, nie um den Ring. Der Audiofaden fasst sie nicht an.
        self._schloss = threading.Lock()

        self.unterlaeufe = 0
        self.ausgegeben = 0
        self.erzeugt = 0
        #: Wie viele Stimmen insgesamt gerechnet wurden (stumme zaehlen nicht).
        self.gerechnet = 0
        self._summe: np.ndarray | None = None

        #: Messwerte fuers Protokoll (Fund 01.10.2026: Starvation des Erzeugers).
        #: ``geraete_unterlaeufe`` zaehlt, was PortAudio selbst meldet
        #: (``status.output_underflow``); ``unterlaeufe`` zaehlt, was der Ring
        #: nicht liefern konnte. ``max_abruf`` ist der groesste Abruf des
        #: Treibers (Frames), ``erzeugen_max_ms`` das teuerste Stueck.
        self.geraete_unterlaeufe = 0
        self.erzeugen_max_ms = 0.0
        self.erzeugen_summe_ms = 0.0
        self.erzeugen_zahl = 0
        self.erzeugen_spaet = 0
        #: Verlaeufe von 0 nach 1 je Blocklaenge. Eine Stimme braucht je Seite
        #: einen Verlauf je Stueck; ``np.linspace`` ist dafuer erstaunlich teuer
        #: und gibt dem GIL jedes Mal Gelegenheit zu wechseln.
        self._rampen: dict[int, np.ndarray] = {}

    @property
    def _geschrieben(self) -> int:
        return int(self._z[0])

    @_geschrieben.setter
    def _geschrieben(self, wert: int) -> None:
        self._z[0] = wert

    @property
    def _gelesen(self) -> int:
        return int(self._z[1])

    @_gelesen.setter
    def _gelesen(self, wert: int) -> None:
        self._z[1] = wert

    @property
    def max_abruf(self) -> int:
        return int(self._z[2])

    @max_abruf.setter
    def max_abruf(self, wert: int) -> None:
        self._z[2] = wert

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
        """Ein Stück erzeugen und messen (siehe :meth:`_erzeugen_stueck`)."""
        anfang = time.perf_counter()
        n = self._erzeugen_stueck()
        if n > 0:
            ms = 1000.0 * (time.perf_counter() - anfang)
            self.erzeugen_zahl += 1
            self.erzeugen_summe_ms += ms
            if ms > self.erzeugen_max_ms:
                self.erzeugen_max_ms = ms
            # Zu spaet heisst: laenger gebraucht, als das Stueck Echtzeit dauert.
            if ms > 1000.0 * n / max(1, self.ausgaberate):
                self.erzeugen_spaet += 1
        return n

    def vorrat_nachfuehren(self) -> None:
        """Den Vorrat an die tatsaechlichen Abrufe des Treibers anpassen.

        Ruft der Treiber auf einmal mehr Frames ab, als der Vorrat hergibt
        (grosse Geraetepuffer, Bluetooth), ist der Ring bei jedem Abruf zu
        leer — Dauer-Unterlauf, obwohl der Erzeuger nichts falsch macht. Der
        Vorrat muss deshalb mindestens zwei Abrufe plus ein Stueck tragen.
        """
        noetig = 2 * self.max_abruf + self.stueck
        grenze = self.kapazitaet - self.stueck
        if noetig > self.vorrat:
            self.vorrat = min(noetig, grenze)

    def status_melden(self, status) -> None:
        """Aus dem Audiofaden: Statusmeldung von PortAudio zaehlen."""
        try:
            if status and getattr(status, "output_underflow", False):
                self.geraete_unterlaeufe += 1
        except Exception:
            pass

    def _rampe(self, laenge: int) -> np.ndarray:
        r = self._rampen.get(laenge)
        if r is None:
            r = np.linspace(0.0, 1.0, laenge, endpoint=False, dtype=np.float32)
            self._rampen[laenge] = r
        return r

    def _erzeugen_stueck(self) -> int:
        """Ein Stück erzeugen und in den Ring legen. Gibt die Länge zurück.

        Wird vom Erzeugerfaden in einer Schleife gerufen, solange
        :meth:`braucht_nachschub` wahr ist. Gibt 0 zurück, wenn kein Platz ist.
        """
        platz = self.kapazitaet - self.fuellstand
        # Einmal lesen: die Wache kann die Rate beim Geraetewechsel
        # zwischendurch aendern.
        rate = self.ausgaberate
        umrechnen = rate != self.quellrate
        if umrechnen:
            # Quellwerte, deren umgerechnete Menge noch in den Ring passt.
            schritt = self.quellrate / rate
            laenge = min(self.stueck, int(platz * schritt) - 2)
        else:
            laenge = min(self.stueck, platz)
        if laenge <= 0:
            return 0

        summe = self._summe_puffer(laenge)
        with self._schloss:
            stimmen = list(self._stimmen)
        uebrig = []
        gruppen: dict = {}
        for stimme in stimmen:
            rechner = getattr(stimme.erzeuger, "stapel", None)
            if rechner is None:
                if not self._stimme_mischen(stimme, summe, laenge):
                    uebrig.append(stimme)
                continue
            if stimme._ziel == (0.0, 0.0) and stimme._ist == (0.0, 0.0):
                if not stimme.beendet:
                    uebrig.append(stimme)
                continue
            gruppen.setdefault(rechner, []).append(stimme)
        for rechner, mitglieder in gruppen.items():
            self._stapel_mischen(rechner, mitglieder, summe, laenge, uebrig)
        if len(uebrig) != len(stimmen):
            with self._schloss:
                self._stimmen = [s for s in self._stimmen if s in uebrig]
            if self.bei_entfernt is not None:
                for stimme in stimmen:
                    if stimme not in uebrig:
                        self.bei_entfernt(stimme)

        # Erst schreiben, dann den Zähler erhöhen — sonst liest der Audiofaden
        # Daten, die noch gar nicht dastehen.
        if self.begrenzen:
            summe = weich_begrenzen(summe)
        if umrechnen:
            summe = self._umrechnen(summe, rate)
            laenge = len(summe)
            if laenge <= 0:
                return 0
        self._in_ring(summe, laenge)
        self._geschrieben += laenge
        self.erzeugt += laenge
        return laenge

    def ausgaberate_setzen(self, rate: int) -> None:
        """Geräterate ändern (Gerätewechsel). Zustand der Umrechnung bleibt."""
        self.ausgaberate = int(rate)

    def _tiefpass_taps(self, rate: int) -> np.ndarray:
        """Gefensterter Sinc-Tiefpass gegen Spiegelfrequenzen beim Verkleinern.

        Eckfrequenz 0,45 x Zielrate (unter deren Nyquist), 63 Taps, auf
        Gleichanteil 1 normiert. Wird je Rate einmal gerechnet.
        """
        if getattr(self, "_tp_rate", None) != rate:
            fc = 0.45 * rate / self.quellrate        # in Zyklen je Quellwert
            k = np.arange(AA_TAPS) - (AA_TAPS - 1) / 2.0
            h = 2.0 * fc * np.sinc(2.0 * fc * k) * np.hanning(AA_TAPS)
            self._tp_taps = (h / h.sum()).astype(np.float32)
            self._tp_rate = rate
            self._tp_rest = np.zeros((AA_TAPS - 1, 2), dtype=np.float32)
        return self._tp_taps

    def _anti_alias(self, x: np.ndarray, rate: int) -> np.ndarray:
        taps = self._tiefpass_taps(rate)
        ext = np.concatenate([self._tp_rest, x], axis=0)
        aus = np.empty_like(x)
        for c in (0, 1):
            aus[:, c] = np.convolve(ext[:, c], taps, mode="valid")
        self._tp_rest = ext[-(AA_TAPS - 1):].copy()
        return aus

    def _umrechnen(self, x: np.ndarray, rate: int | None = None) -> np.ndarray:
        """Lineare Umrechnung quellrate -> ausgaberate, stetig über Stücke.

        ``_umr_letzter`` ist der letzte Wert des Vorstücks, ``_umr_pos`` die
        Lesestelle (in Quellwerten, 0 = dieser Letzte). Dadurch gibt es an den
        Stückgrenzen weder Sprung noch Doppelwert.
        """
        rate = rate or self.ausgaberate
        n = len(x)
        schritt = self.quellrate / rate
        if schritt > AA_AB:
            x = self._anti_alias(x, rate)
        quelle = np.concatenate([self._umr_letzter[None, :], x], axis=0)
        pos = self._umr_pos
        k = int(np.ceil((n - pos) / schritt)) if n > pos else 0
        if k <= 0:
            self._umr_pos = pos - n
            self._umr_letzter = x[-1].copy()
            return np.zeros((0, 2), dtype=np.float32)
        stellen = pos + np.arange(k) * schritt
        i0 = np.floor(stellen).astype(np.int64)
        f = (stellen - i0).astype(np.float32)[:, None]
        aus = quelle[i0] * (1.0 - f) + quelle[i0 + 1] * f
        self._umr_pos = float(pos + k * schritt - n)
        self._umr_letzter = x[-1].copy()
        return aus.astype(np.float32)

    def _summe_puffer(self, laenge: int) -> np.ndarray:
        """Summenpuffer, einmal angelegt und je Stueck auf null gesetzt."""
        p = self._summe
        if p is None or len(p) != laenge:
            p = self._summe = np.zeros((laenge, 2), dtype=np.float32)
        else:
            p.fill(0.0)
        return p

    def _stapel_mischen(self, rechner, mitglieder: list, summe: np.ndarray,
                        laenge: int, uebrig: list) -> None:
        """Stimmen, die ihr Rechner gemeinsam erzeugt, in einem Durchgang.

        Ein Durchgang statt je Stimme einer: das spart nicht Rechenzeit,
        sondern Wechsel des GIL (siehe ``motorstapel``). Geht der gemeinsame
        Weg schief, faellt jede Stimme auf ihren eigenen Aufruf zurueck, damit
        eine kaputte Quelle nicht alle mitreisst.
        """
        try:
            roh = np.asarray(rechner([s.erzeuger for s in mitglieder], laenge),
                             dtype=np.float32)
            if roh.shape != (len(mitglieder), laenge):
                raise ValueError("falsche Form")
        except Exception:
            for stimme in mitglieder:
                if not self._stimme_mischen(stimme, summe, laenge):
                    uebrig.append(stimme)
            return
        self.gerechnet += len(mitglieder)
        ist = np.array([s._ist for s in mitglieder], dtype=np.float32)    # V x 2
        ziel = np.array([s._ziel for s in mitglieder], dtype=np.float32)
        rampe = self._rampe(laenge)
        for kanal in (0, 1):
            a = ist[:, kanal:kanal + 1]
            verlauf = a + (ziel[:, kanal:kanal + 1] - a) * rampe[None, :]
            summe[:, kanal] += np.einsum("vl,vl->l", roh, verlauf)
        for stimme in mitglieder:
            z = stimme._ziel
            stimme._ist = z
            if not (stimme.beendet and z == (0.0, 0.0)):
                uebrig.append(stimme)

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

        self.gerechnet += 1
        roh = np.asarray(roh, dtype=np.float32)
        # Lautstaerke als Verlauf, nicht als Sprung: ein Sprung ist selbst ein
        # Knacken, und bei sechs fahrenden Autos passiert er in jedem Block.
        for kanal in (0, 1):
            a, b = ist[kanal], ziel[kanal]
            if a == b:
                if b != 0.0:
                    summe[:, kanal] += roh * b
            else:
                verlauf = np.float32(a) + np.float32(b - a) * self._rampe(laenge)
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
        if frames > self.max_abruf:
            self.max_abruf = frames
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
