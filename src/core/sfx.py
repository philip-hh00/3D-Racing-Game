"""Soundeffekte: Kanalverwaltung, Motorstimmen, Lautstärke (Block C, §C6).

Zwei Arten von Klang, die sich grundlegend unterscheiden:

**Einzelklänge** — Aufprall, Reifen, Menü. Kurz, werden angestoßen und laufen
aus. Das Problem dabei ist die Kanalverwaltung: pygame hat eine feste Anzahl
Kanäle, und ohne Verwaltung würgt eine zweite Kollision die erste ab. Hier wird
deshalb ein freier Kanal gesucht und, wenn keiner frei ist, der leiseste
verdrängt — nicht der erste, der gefunden wird.

**Motorstimmen** — dauerhaft, eine je Fahrzeug, und die Tonhöhe folgt der
Drehzahl. Dafür reicht kein abgespielter Klang: die Drehzahl ändert sich
ständig, und pygame kann keinen Klang mit veränderlicher Rate abspielen. Die
Stimme erzeugt ihre Blöcke deshalb selbst aus den aufgenommenen
Drehzahlschichten (siehe ``tools/motor_import.py``) und schiebt sie in den
Kanal nach.

Die Zustandsführung steckt in ``Motorstimme``: sie hält die Phase über
Blockgrenzen hinweg fest. Ohne das würde jeder Block bei Phase 0 anfangen, und
es knackte im Takt der Blocklänge.
"""
from __future__ import annotations

import json
import os

import numpy as np

#: Abtastrate der Aufnahmen. Der Mixer wird passend initialisiert, damit nichts
#: umgerechnet werden muss.
SR = 48000
#: Blocklänge der Motorstimmen in Samples. 4096 sind bei 48 kHz gut 85 ms.
#:
#: Der Wert ist die **Frist**, in der das nächste Bild nachlegen muss: eine
#: Stimme hält genau einen Block vor, weil pygame nur einen Klang in die
#: Warteschlange nimmt. Bei den früheren 2048 (42,67 ms) blieben bei 30 Bildern
#: nur 1,28 Bilder Reserve — jedes verspätete Bild riss eine hörbare Lücke
#: (gemeldet 04.08.2026, gemessen und angehoben am 05.08.2026). Der Preis ist
#: Nachlauf: die Drehzahl folgt dem Bild um bis zu 85 ms verzögert.
#:
#: Je Motortyp einstellbar (`motorklang`, Fahrzeuglabor §C8); das hier ist nur
#: der Rückfall, wenn nichts in der Kennwertdatei steht.
BLOCK = 4096
#: Kanäle für Einzelklänge. Der Rest bleibt den Motorstimmen.
EINZEL_KANAELE = 16
#: Wie breit zwischen zwei Drehzahlschichten übergeblendet wird, als Anteil
#: ihres halben Abstands. 1,0 heißt durchgehend überblenden — im Hörtest
#: gewählt: die Bänder überlagern sich, aber es sind keine Sprünge zu hören,
#: und im Rennen fällt das weniger auf als ein sauberer Wechsel.
BLENDE = 1.0

_sfx_pfad = os.path.join("data", "audio", "sfx")


def _pfad(*teile: str) -> str:
    """Effektdatei über alle Wurzeln suchen.

    Nicht bloß relativ zum Arbeitsverzeichnis: auf einem gepackten macOS-Build
    liegen Nutzerdaten woanders als die mitgelieferten Dateien (siehe
    paths.track_roots).
    """
    from src.core import paths
    kandidat = os.path.join(_sfx_pfad, *teile)
    if os.path.isfile(kandidat):
        return kandidat
    for wurzel in paths.track_roots():
        p = os.path.join(str(wurzel), _sfx_pfad, *teile)
        if os.path.isfile(p):
            return p
    return kandidat


# ── Lautstärke ──────────────────────────────────────────────────────────────

#: Die beiden Bereiche, für die es je einen Regler gibt.
MENUE = "menue"
RENNEN = "rennen"
#: Kein Regler dazwischen — der Aufrufer hat die Lautstärke schon gesetzt.
#: Gebraucht beim Vorhören in den Einstellungen: dort soll der *eingestellte*
#: Wert zu hören sein, nicht der zuletzt gespeicherte.
DIREKT = "direkt"


def effekt_lautstaerke(bereich: str = RENNEN) -> float:
    """Reglerwert „Effekte" aus dem Profil, 0..1.

    Zwei Regler statt einem (02.08.2026): Menügeräusche sollen leise
    bestätigen, Rennklänge tragen. Mit einem gemeinsamen Wert musste man sich
    für eines von beiden entscheiden.
    """
    if bereich == DIREKT:
        return 1.0
    from src.core import profile
    p = profile.current()
    feld = "sfx_menu_volume" if bereich == MENUE else "sfx_race_volume"
    return max(0.0, min(1.0, float(getattr(p, feld, 0.7))))


# ── Drehzahlschichten ───────────────────────────────────────────────────────

class Schichten:
    """Die aufgenommenen Schleifen eines Motors, nach Drehzahl sortiert."""

    def __init__(self, motor: str) -> None:
        self.motor = motor
        self.drehzahlen: list[int] = []
        self.schleifen: list[np.ndarray] = []
        self._laden(motor)

    def _laden(self, motor: str) -> None:
        try:
            import soundfile as sf
        except ImportError:
            # Fehlt die Bibliothek, gibt es eben keine Aufnahmen — genau der
            # Fall, den ``Rennklang._stimme_fuer`` schon behandelt ("lieber
            # still als verzerrt"). Vorher flog der ImportError durch bis zum
            # ersten Rennstart und beendete das Spiel; im gepackten Buendel
            # fehlte soundfile bis zum 04.08.2026 tatsaechlich, weil es nicht in
            # requirements.txt stand. Ein stummer Motor ist ein Mangel, ein
            # Absturz ist einer mehr.
            return
        tabelle_pfad = _pfad("motor_aufnahmen.json")
        if not os.path.isfile(tabelle_pfad):
            return
        with open(tabelle_pfad, encoding="utf-8") as fh:
            tabelle = json.load(fh)
        for eintrag in tabelle.get(motor, []):
            if eintrag.get("rev") or eintrag.get("schub"):
                continue
            pfad = _pfad(eintrag["datei"])
            if not os.path.isfile(pfad):
                continue
            daten, sr = sf.read(pfad, always_2d=True, dtype="float32")
            if sr != SR:
                continue
            self.drehzahlen.append(int(eintrag["upm"]))
            self.schleifen.append(daten.mean(axis=1).astype(np.float32))
        paare = sorted(zip(self.drehzahlen, self.schleifen), key=lambda x: x[0])
        self.drehzahlen = [u for u, _s in paare]
        self.schleifen = [s for _u, s in paare]

    def __bool__(self) -> bool:
        return bool(self.schleifen)

    @property
    def bereich(self) -> tuple[int, int]:
        if not self.drehzahlen:
            return (0, 0)
        return (self.drehzahlen[0], self.drehzahlen[-1])

    def gewichte(self, upm: float, blende: float | None = None) -> list[float]:
        """Anteil jeder Schicht bei dieser Drehzahl.

        Dreieck um die eigene Drehzahl, aber nur *blende* breit — zwischen den
        Blendbereichen klingt genau eine Schicht. Zu schmal springen die
        Wechsel hörbar, zu breit schwebt es. Seit §C8 je Motortyp einstellbar;
        ohne Angabe gilt die frühere Konstante BLENDE.
        """
        if blende is None:
            blende = BLENDE
        blende = max(0.0, min(1.0, float(blende)))
        n = len(self.drehzahlen)
        aus = [0.0] * n
        if n == 0:
            return aus
        if n == 1 or upm <= self.drehzahlen[0]:
            aus[0] = 1.0
            return aus
        if upm >= self.drehzahlen[-1]:
            aus[-1] = 1.0
            return aus
        for i in range(n - 1):
            u_lo, u_hi = self.drehzahlen[i], self.drehzahlen[i + 1]
            if not (u_lo <= upm <= u_hi):
                continue
            mitte = (u_lo + u_hi) / 2.0
            halbe = (u_hi - u_lo) / 2.0
            rand = halbe * blende
            if upm <= mitte - rand:
                aus[i] = 1.0
            elif upm >= mitte + rand:
                aus[i + 1] = 1.0
            else:
                oben = (upm - (mitte - rand)) / max(1e-9, 2.0 * rand)
                aus[i] = 1.0 - oben
                aus[i + 1] = oben
            break
        return aus


_schichten_cache: dict[str, Schichten] = {}


def schichten(motor: str) -> Schichten:
    if motor not in _schichten_cache:
        _schichten_cache[motor] = Schichten(motor)
    return _schichten_cache[motor]


# ── Klangfärbung je Fahrzeug (§C5) ──────────────────────────────────────────

#: Eckfrequenz der Färbung. Darüber wirkt sie, darunter bleibt der Klang wie
#: aufgenommen — der Grundcharakter eines Motors sitzt in den unteren Ordnungen.
FAERBUNG_ECKE = 1800.0
#: Länge des Filters. 33 Werte reichen für eine sanfte Neigung und kosten pro
#: Block weniger als ein Prozent der Rechenzeit einer Stimme.
FAERBUNG_LAENGE = 33


def _tiefpass(ecke: float, laenge: int = FAERBUNG_LAENGE) -> np.ndarray:
    """Tiefpass als gefensterte sinc-Funktion, auf Summe 1 gebracht."""
    mitte = (laenge - 1) / 2.0
    k = np.arange(laenge) - mitte
    h = np.sinc(2.0 * ecke / SR * k) * np.hanning(laenge)
    return (h / h.sum()).astype(np.float64)


class Faerbung:
    """Leichte Höhen- oder Tiefenabsenkung, über Blockgrenzen hinweg stetig.

    *staerke* > 0 nimmt Höhen weg (dumpfer), < 0 hebt sie an (heller).

    Zwei Fallen stecken darin. Erstens muss der ungefilterte Anteil um die halbe
    Filterlänge verzögert werden — sonst liegen trockenes und gefiltertes Signal
    16 Samples auseinander und die Summe kämmt. Zweitens braucht es die Reste des
    letzten Blocks, sonst fängt der Filter an jeder Blockgrenze bei null an.
    """

    def __init__(self, staerke: float) -> None:
        self.staerke = max(-1.0, min(1.0, float(staerke)))
        self._taps = _tiefpass(FAERBUNG_ECKE)
        n = len(self._taps)
        self._rest = np.zeros(n - 1, dtype=np.float64)
        #: Beim allerersten Block gibt es keine Vergangenheit. Mit Nullen
        #: gefuellt gab das einen Knacks von 0,109 bei Sample 15 — die ersten
        #: 16 Ausgaben lagen bei null, dann sprang das Signal auf seinen echten
        #: Wert. Hoerbar bei **jedem** Motorstart, im Rennen also einmal je
        #: Fahrzeug (gemessen 02.08.2026). Deshalb wird die Vergangenheit beim
        #: ersten Aufruf mit dem ersten Abtastwert gefuellt: eine Konstante
        #: davor, kein Sprung hinein.
        self._erster = True

        # Wirksame Impulsantwort, um den Pegel auszugleichen: sonst wäre ein
        # dunkler gefärbtes Fahrzeug auch leiser.
        trocken = np.zeros(n)
        trocken[(n - 1) // 2] = 1.0
        f = abs(self.staerke)
        if self.staerke >= 0.0:
            h = (1.0 - f) * trocken + f * self._taps
        else:
            h = (1.0 + f) * trocken - f * self._taps
        self._ausgleich = 1.0 / max(1e-6, float(np.sqrt(np.sum(np.square(h)))))
        #: Nachgeführter Pegelausgleich.
        #:
        #: ``_ausgleich`` rechnet mit der Filterenergie und trifft damit ein
        #: Signal, das über das ganze Band gleich verteilt ist. Ein Motor ist
        #: das nicht — seine Energie sitzt unter der Eckfrequenz, wo der Filter
        #: kaum etwas wegnimmt, und der Ausgleich hebt trotzdem an. Gemessen am
        #: 02.08.2026: drei Fahrzeuge derselben Klasse unterschieden sich allein
        #: durch ihre Färbung um **Faktor 2,3** in der Lautstärke.
        #:
        #: Deshalb wird zusätzlich am laufenden Signal gemessen und langsam
        #: nachgeregelt. Langsam mit Absicht: eine blockweise Normalisierung
        #: würde die Dynamik des Motors flachdrücken.
        self._nach = 1.0

    def __bool__(self) -> bool:
        return abs(self.staerke) > 0.001

    def __call__(self, block: np.ndarray) -> np.ndarray:
        if not self:
            return block
        n = len(self._taps)
        mitte = (n - 1) // 2
        if self._erster:
            self._rest = np.full(n - 1, float(block[0]) if len(block) else 0.0)
            self._erster = False
        x = np.concatenate([self._rest, block.astype(np.float64)])
        self._rest = x[-(n - 1):]
        tief = np.convolve(x, self._taps, mode="valid")
        trocken = x[mitte:mitte + len(block)]
        f = abs(self.staerke)
        if self.staerke >= 0.0:
            aus = (1.0 - f) * trocken + f * tief
        else:
            aus = (1.0 + f) * trocken - f * tief
        aus = aus * self._ausgleich

        rein_rms = float(np.sqrt(np.mean(np.square(trocken))))
        raus_rms = float(np.sqrt(np.mean(np.square(aus))))
        if rein_rms > 1e-5 and raus_rms > 1e-5:
            ziel = max(0.25, min(4.0, rein_rms / raus_rms))
            # Zeitkonstante rund eine halbe Sekunde bei 2048er Blöcken.
            self._nach += (ziel - self._nach) * 0.08
        return np.clip(aus * self._nach, -1.0, 1.0).astype(np.float32)


# ── Hochpass und Begrenzer (§C8) ────────────────────────────────────────────

def _einpolig(x: np.ndarray, a: float, start: float) -> np.ndarray:
    """``y[n] = a*y[n-1] + (1-a)*x[n]``, ohne Schleife.

    Ein Einpolfilter ist rekursiv, numpy kann das nicht direkt. Aufgelöst:

        y[n] = a^(n+1)·start + (1-a)·a^n·Σ_k x[k]·a^(-k)

    Der Faktor ``a^-k`` wächst über einen Block auf höchstens etwa 4·10⁴ (bei
    40 Hz und 2048 Samples) — in float64 unkritisch, und es spart die
    Python-Schleife, die hier 2048 Durchläufe je Block und Fahrzeug wäre.

    scipy hätte ``lfilter``, steht aber nicht in requirements.txt und wäre im
    gepackten Build nicht dabei.
    """
    n = len(x)
    if n == 0:
        return x
    k = np.arange(n, dtype=np.float64)
    hoch = np.power(a, k)                       # a^n
    with np.errstate(over="ignore", invalid="ignore"):
        runter = np.power(a, -k)                # a^-k
    if not np.all(np.isfinite(runter)):
        # Nur bei absurd kleinem a; dann folgt der Filter dem Eingang ohnehin.
        return x.astype(np.float64, copy=True)
    summe = np.cumsum(x.astype(np.float64) * runter)
    return a * hoch * start + (1.0 - a) * hoch * summe


class Hochpass:
    """Nimmt die tiefsten Frequenzen weg, stetig über Blockgrenzen.

    Warum überhaupt: ein Gleichanteil in einer Aufnahme frisst
    Aussteuerungsreserve, ohne dass man ihn hört — und er sorgt an jeder
    Blockgrenze für einen Versatz, der als Knacken hörbar wird.

    Gerechnet als „Eingang minus Tiefpass". Der Tiefpass ist das Einpolfilter
    oben; sein Zustand wird mitgeführt, sonst fängt der Filter alle 42 ms neu
    an und erzeugt genau das Knacken, das er wegnehmen soll.
    """

    def __init__(self, ecke_hz: float) -> None:
        self.ecke = max(0.0, float(ecke_hz))
        self._mittel = 0.0
        self._erster = True

    def __bool__(self) -> bool:
        return self.ecke > 0.5

    def __call__(self, block: np.ndarray) -> np.ndarray:
        if not self:
            return block
        if self._erster:
            # Mit Mittelwert null zöge der Filter das erste Stück nach unten —
            # dieselbe Falle wie bei der Färbung, nur weicher.
            self._mittel = float(block[0]) if len(block) else 0.0
            self._erster = False
        # Zeitkonstante eines Einpol-Tiefpasses bei der Eckfrequenz.
        a = float(np.exp(-2.0 * np.pi * self.ecke / SR))
        tief = _einpolig(block, a, self._mittel)
        self._mittel = float(tief[-1])
        return (block.astype(np.float64) - tief).astype(np.float32)


class Begrenzer:
    """Fängt Spitzen weich ab, statt sie hart abschneiden zu lassen.

    Hartes Abschneiden im Mixer **ist** das Knistern: sobald die Summe über die
    Vollaussteuerung geht, wird der Kopf der Welle gerade abgesägt, und das
    hört man als Bruzeln.

    Angriff sofort, Rückkehr über *tempo_ms*: eine Spitze wird augenblicklich
    gefasst, danach kommt die Lautstärke langsam zurück. Andersherum — träger
    Angriff — käme die Spitze durch, und der Begrenzer wäre wirkungslos.
    """

    def __init__(self, schwelle: float, tempo_ms: float) -> None:
        self.schwelle = max(0.05, min(1.0, float(schwelle)))
        self.tempo = max(0.5, float(tempo_ms))
        self._huellkurve = 0.0

    def __bool__(self) -> bool:
        return self.schwelle < 0.999

    def __call__(self, block: np.ndarray) -> np.ndarray:
        if not self:
            return block
        betrag = np.abs(block.astype(np.float64))
        a = float(np.exp(-1000.0 / (self.tempo * SR)))
        geglättet = _einpolig(betrag, a, self._huellkurve)
        self._huellkurve = float(geglättet[-1])
        # Die geglättete Hülle allein liefe einer Spitze hinterher; das Maximum
        # aus beiden fasst sie sofort und lässt sie langsam wieder los.
        huelle = np.maximum(betrag, geglättet)
        faktor = np.where(huelle > self.schwelle, self.schwelle / np.maximum(huelle, 1e-9), 1.0)
        return (block.astype(np.float64) * faktor).astype(np.float32)


#: Fortlaufende Nummer je erzeugter Zyklusstreuung. Jede Stimme braucht ihre
#: eigene Zufallsfolge — zwei Motoren, die identisch schwanken, schwanken
#: gemeinsam und sind damit genauso streng gekoppelt wie ohne Streuung.
_streuung_nr = 0


def _streuung_saat() -> int:
    global _streuung_nr
    _streuung_nr += 1
    return 0xC0FFEE + _streuung_nr * 7919


class Zyklusstreuung:
    """Das Eigenleben eines Motors: Zyklus-zu-Zyklus-Schwankung der Drehzahl.

    **Warum es das braucht** (gemessen am 03.08.2026). Jede Schicht ist eine
    Aufnahme, die als *Schleife* läuft — eine Stimme ist damit streng periodisch:
    ihre Ähnlichkeit mit sich selbst nach einer Schleifenlänge ist 1,000, auf
    vier Stellen. Ein echter Motor erreicht das nie, jeder Arbeitstakt fällt
    etwas anders aus. Die Folge dieser Perfektion ist ein Linienspektrum mit
    messerscharfen Oberwellen, und **zwei** davon erzeugen eine saubere, laute
    Schwebung: bei 4500 und 4680 UPM sitzt sie bei genau 12,1 Hz — der zweiten
    Oberwelle der Zündfrequenzdifferenz — und ist zehnmal so hoch wie alles, was
    eine Stimme allein an Schwankung mitbringt.

    Das erklärt auch, warum die beiden früheren Versuche nichts gebracht haben:
    weder der Tonhöhenversatz je Fahrzeug (die Drehzahlen unterscheiden sich im
    Rennen ohnehin) noch verschiedene Aufnahmen (4zyl gegen 8zyl schwebt
    genauso). Es ist nicht die *gleiche* Aufnahme, es ist die *perfekte*.

    Ein halbes Prozent Streuung genügt: die Schärfe der Schwebungslinie fällt
    von 25,8 auf 2,4 — sie hört auf, ein Ton zu sein, und wird zu der Rauheit,
    die zwei Motoren nebeneinander eben haben. Die Bandenergie bleibt dabei fast
    gleich; wer nur die messt, hält den Eingriff für wirkungslos.

    Gerechnet wird **je Block, nicht je Sample**: ein Wert alle 42 ms, linear
    dazwischen. Bei 2 bis 6 Hz Schwankung sind das reichlich Stützstellen, und
    es kostet nichts.
    """

    def __init__(self, staerke: float, hz: float, saat: int | None = None) -> None:
        self.staerke = max(0.0, min(0.1, float(staerke)))
        self.hz = max(0.1, float(hz))
        self._rng = np.random.default_rng(_streuung_saat() if saat is None else saat)
        self._letzter = 0.0

    def __bool__(self) -> bool:
        return self.staerke > 1e-4

    def rate(self, laenge: int) -> np.ndarray | float:
        """Ratenfaktor um 1,0 über *laenge* Samples."""
        if not self or laenge <= 0:
            return 1.0
        a = float(np.exp(-2.0 * np.pi * self.hz * laenge / SR))
        # Ein Einpolfilter auf weißem Rauschen hat die Streuung
        # sqrt((1-a)/(1+a)) — herausgerechnet, damit die Stärke in der
        # Einstellung wirklich die Streuung ist und nicht vom Tempo abhängt.
        norm = float(np.sqrt((1.0 - a) / (1.0 + a))) or 1.0
        neu = a * self._letzter + (1.0 - a) * float(self._rng.standard_normal()) / norm
        rampe = np.linspace(self._letzter, neu, laenge)
        self._letzter = neu
        return 1.0 + rampe * self.staerke


# ── Motorstimme ─────────────────────────────────────────────────────────────

class Motorstimme:
    """Erzeugt fortlaufend Motorklang für **ein** Fahrzeug.

    Die Phase wird über Blockgrenzen hinweg mitgeführt. Ohne das fing jeder
    Block bei null an, und es knackte im Takt der Blocklänge.

    *tonhoehe* und *faerbung* geben dem einzelnen Fahrzeug seinen Charakter
    (§C5): der Versatz verschiebt Tonhöhe **und** Wiederholrate, klingt also nach
    einem anders übersetzten Motor und nicht nach abgespielter Bandmaschine.
    """

    def __init__(self, motor: str, tonhoehe: float = 1.0,
                 faerbung: float = 0.0, werte: dict | None = None) -> None:
        self.schichten = schichten(motor)
        self.motor = motor
        self.phase = 0.0        # in Arbeitsspielen
        self.upm = 0.0
        self.lautstaerke = 1.0
        # Eng begrenzt: ab etwa 10 % klingt es nach einer anderen Motorbauart
        # statt nach einem anderen Fahrzeug derselben Klasse.
        self.tonhoehe = max(0.9, min(1.1, float(tonhoehe)))
        self.faerbung = Faerbung(faerbung)
        #: Gewichte des letzten Blocks. Werden zum neuen hin geführt, sonst
        #: springt die Mischung an der Blockgrenze und es knackt.
        self._gewichte: list[float] | None = None
        #: Geführte Drehzahl (§C8). Getrennt von self.upm, weil das der Wert
        #: ist, den der Motor *hört* — nicht der, den die Physik meldet.
        self._gefuehrt = 0.0
        #: Saat der Zyklusstreuung. Eine je Stimme, damit zwei Fahrzeuge nicht
        #: im Gleichschritt schwanken (siehe Zyklusstreuung).
        self._streu_saat = _streuung_saat()
        self.werte_setzen(werte)

    def werte_setzen(self, werte: dict | None = None) -> None:
        """Klangwerte des Motortyps übernehmen (§C8).

        Ohne Angabe werden sie aus ``motorklang`` gelesen. Getrennte Methode,
        damit die Laborseite beim Drehen an einem Regler nicht die ganze Stimme
        neu bauen muss — das setzte Phase und Filter zurück und knackte bei
        jedem Reglerklick.
        """
        if werte is None:
            from src.core import motorklang
            werte = motorklang.werte(self.motor)
        self.werte = dict(werte)
        self.blende = float(werte.get("schichtblende", BLENDE))
        self.grundpegel = float(werte.get("grundpegel", 1.0))
        self.blocklaenge = max(64, int(werte.get("blocklaenge", BLOCK)))
        self.glaettung = max(0.0, float(werte.get("drehzahlglaettung", 0.0)))
        self.knie_upm = max(0.0, float(werte.get("knie_upm", 0.0)))
        self.kompression = max(0.05, min(1.0, float(werte.get("kompression", 1.0))))
        # Die Zufallsfolge der Streuung wird mitgenommen, nicht neu gesetzt: im
        # Labor wird an den Reglern gedreht, während der Motor läuft, und eine
        # neue Folge wäre ein Sprung in der Tonhöhe.
        alt_streu = getattr(self, "streuung", None)
        self.streuung = Zyklusstreuung(float(werte.get("zyklusstreuung", 0.0)),
                                       float(werte.get("streuung_hz", 2.5)),
                                       saat=self._streu_saat)
        if alt_streu is not None:
            self.streuung._rng = alt_streu._rng
            self.streuung._letzter = alt_streu._letzter
        # Filterzustand mitnehmen, statt die Filter neu zu bauen: im Labor wird
        # an den Reglern gedreht, während der Motor läuft. Ein Neubau setzte
        # Hüllkurve und Filterspeicher auf null — und knackte bei jedem Klick.
        alt_hp = getattr(self, "hochpass", None)
        alt_bg = getattr(self, "begrenzer", None)
        self.hochpass = Hochpass(float(werte.get("hochpass_hz", 0.0)))
        self.begrenzer = Begrenzer(float(werte.get("begrenzer_schwelle", 1.0)),
                                   float(werte.get("begrenzer_tempo_ms", 12.0)))
        if alt_hp is not None:
            self.hochpass._mittel = alt_hp._mittel
        if alt_bg is not None:
            self.begrenzer._huellkurve = alt_bg._huellkurve

    def __bool__(self) -> bool:
        return bool(self.schichten)

    def _fuehren(self, upm: float, laenge: int) -> float:
        """Die Drehzahl, der der Klang folgen soll.

        Ohne Glättung ist das die gemeldete. Mit Glättung läuft sie ihr über
        die eingestellte Zeit hinterher — gegen den Gangwechsel, bei dem die
        Drehzahl in einem Block um über tausend Umdrehungen springt und die
        Tonhöhe entsprechend durchrutscht.
        """
        ziel = float(upm)
        if self.glaettung <= 0.5:
            self._gefuehrt = ziel
            return ziel
        if self._gefuehrt <= 0.0:
            self._gefuehrt = ziel
            return ziel
        dauer_ms = 1000.0 * laenge / SR
        a = float(np.exp(-dauer_ms / self.glaettung))
        self._gefuehrt = a * self._gefuehrt + (1.0 - a) * ziel
        return self._gefuehrt

    def block(self, upm: float, laenge: int | None = None) -> np.ndarray:
        """Nächster Block, mono float32 in [-1, 1].

        Reihenfolge wie im Signalweg der Laborseite: Schichten mischen,
        Färbung, Hochpass, Begrenzer.
        """
        laenge = self.blocklaenge if laenge is None else int(laenge)
        aus = self._erzeugen(self._fuehren(upm, laenge), laenge)
        aus = self.faerbung(aus)
        aus = self.hochpass(aus)
        aus = self.begrenzer(aus)
        return np.clip(aus, -1.0, 1.0).astype(np.float32)

    def akustische_drehzahl(self, upm: float) -> float:
        """Drehzahl, mit der der **Klang** rechnet — nicht die des Motors.

        Der Grundton steigt bei den Aufnahmen streng proportional zur Drehzahl:
        UPM/5. Beim Verbrenner ist das unauffällig, weil das Getriebe ihn
        zwischen Leerlauf und Drehzahlgrenze hält. Der Elektro-Prototyp hat
        **keine Gänge** und dreht bis 16000 — dort liegt der Grundton bei
        3200 Hz, also mitten im empfindlichsten Bereich des Gehörs, und ein
        annähernd reiner Ton dort ist keine Maschine mehr, sondern eine Pfeife.

        Gemeldet am 05.08.2026, und zwar mit der Stelle: „In den sound dateien
        beginnt ab ca. 4sec der unrealistische Bereich" — 4 s der Hörprobe sind
        genau 6000 UPM, also 1200 Hz. Darunter trägt der Klang, darüber kippt er.

        Oberhalb von ``knie_upm`` steigt der Ton deshalb nur noch gebremst
        weiter. Er steigt weiter — ein Elektromotor, dessen Ton bei Vollgas
        stehen bliebe, klänge tot —, aber eben nicht mehr bis zur Pfeife. Bei
        ``knie_upm = 6000`` und ``kompression = 0.25`` landen 16000 UPM
        akustisch bei 8500, also bei 1700 Hz statt 3200 Hz.

        ``knie_upm = 0`` schaltet das ab; so laufen die Verbrenner.
        """
        if self.knie_upm <= 0.0 or upm <= self.knie_upm:
            return upm
        return self.knie_upm + (upm - self.knie_upm) * self.kompression

    def _erzeugen(self, upm: float, laenge: int) -> np.ndarray:
        """Rohe Mischung der Schichten, ohne Färbung und Filter."""
        fortschritt = laenge
        if not self.schichten:
            return np.zeros(laenge, dtype=np.float32)
        # Ab hier rechnet alles mit der akustischen Drehzahl: sowohl die Wahl
        # der Schicht als auch die Abspielrate. Nur eines von beiden zu
        # beugen ergäbe eine Aufnahme, die mit der falschen Rate läuft.
        upm = self.akustische_drehzahl(upm)
        lo, hi = self.schichten.bereich
        ziel = float(np.clip(upm, lo, hi))
        von = self.upm if self.upm > 0 else ziel
        verlauf = np.linspace(von, ziel, laenge, dtype=np.float64)
        self.upm = ziel

        # Gemeinsame Phase in Arbeitsspielen: ein Viertakter braucht dafuer zwei
        # Umdrehungen, also 120/UPM Sekunden. Tonhoehenversatz und
        # Zyklusstreuung greifen hier und nur hier: die Schichtwahl bleibt bei
        # der echten Drehzahl, sonst wuerde ein hoeher klingendes Fahrzeug
        # frueher auf die naechste Aufnahme wechseln und damit anders klingen
        # als gedacht.
        schritte = verlauf * self.tonhoehe * self.streuung.rate(laenge) / (120.0 * SR)
        phase = self.phase + np.cumsum(schritte)
        # Nur bis zum ausgegebenen Ende weiterrücken, nicht bis zum Ende des
        # Überhangs — sonst fehlte beim nächsten Block genau die Blendkante.
        self.phase = float(phase[fortschritt - 1]) % 1e6

        neu = self.schichten.gewichte(ziel, self.blende)
        alt = self._gewichte if self._gewichte is not None else neu
        self._gewichte = neu
        # Gewichte ueber den Block fuehren, nicht nur die Drehzahl. Sprang die
        # Mischung an der Blockgrenze, knackte es dort messbar: 0,194 Sprung
        # gegen 0,032 im Inneren des Blocks.
        rampe = np.linspace(0.0, 1.0, laenge)

        aus = np.zeros(laenge, dtype=np.float64)
        for g_alt, g_neu, u_i, schleife in zip(alt, neu, self.schichten.drehzahlen,
                                               self.schichten.schleifen):
            if g_alt <= 0.001 and g_neu <= 0.001:
                continue
            gewicht = g_alt + (g_neu - g_alt) * rampe
            spiel = 120.0 * SR / max(1.0, float(u_i))
            zyklen = len(schleife) / spiel
            stelle = (phase % zyklen) * spiel
            i0 = np.floor(stelle).astype(np.int64) % len(schleife)
            frac = stelle - np.floor(stelle)
            i1 = (i0 + 1) % len(schleife)
            # Wurzelblende: sonst bricht die Lautstaerke in der Mitte ein.
            aus += (schleife[i0] * (1.0 - frac) + schleife[i1] * frac) \
                * np.sqrt(gewicht)

        aus *= self.lautstaerke * self.grundpegel
        return np.clip(aus, -1.0, 1.0).astype(np.float32)


# ── Kanalverwaltung für Einzelklänge ────────────────────────────────────────

class Kanaele:
    """Vergibt Mixerkanäle für Einzelklänge.

    Ist keiner frei, wird der **leiseste** laufende verdrängt. Den ersten
    gefundenen zu nehmen würgt sonst genau den Klang ab, der gerade am
    wichtigsten ist — bei zwei Kollisionen die laute.
    """

    def __init__(self, anzahl: int = EINZEL_KANAELE) -> None:
        self.anzahl = anzahl
        self._belegt: dict[int, float] = {}     # Kanalnummer -> Lautstärke

    def frei_geben(self, nummer: int) -> None:
        self._belegt.pop(nummer, None)

    def belegen(self, lautstaerke: float, ist_frei) -> int | None:
        """Kanalnummer für einen neuen Klang, oder None wenn keiner taugt.

        *ist_frei* sagt für eine Nummer, ob der Mixerkanal gerade still ist —
        als Funktion übergeben, damit die Verwaltung ohne Audiogerät prüfbar
        bleibt.
        """
        for nummer in range(self.anzahl):
            if ist_frei(nummer):
                self._belegt[nummer] = lautstaerke
                return nummer
        if not self._belegt:
            return None
        leisester = min(self._belegt, key=lambda k: self._belegt[k])
        if self._belegt[leisester] >= lautstaerke:
            # Alles Laufende ist wichtiger als der neue Klang.
            return None
        self._belegt[leisester] = lautstaerke
        return leisester


_kanaele = Kanaele()


def _mixer_bereit() -> bool:
    try:
        import pygame
        return bool(pygame.mixer and pygame.mixer.get_init())
    except Exception:
        return False


def spielen(name: str, lautstaerke: float = 1.0, panorama: float = 0.0,
            bereich: str = RENNEN) -> None:
    """Einzelklang anstoßen. *panorama* von -1 (links) bis +1 (rechts)."""
    if not _mixer_bereit():
        return
    import pygame
    from src.core.resource_manager import ResourceManager
    pfad = _pfad(f"{name}.wav")
    if not os.path.isfile(pfad):
        return
    try:
        klang = ResourceManager().load_sound(pfad)
    except Exception:
        return

    staerke = max(0.0, min(1.0, lautstaerke)) * effekt_lautstaerke(bereich)
    if staerke <= 0.001:
        return

    # Wie viele Kanäle es **wirklich** gibt. EINZEL_KANAELE ist der Wunsch,
    # den mixer_starten() anmeldet — ist der Start fehlgeschlagen oder hat
    # pygame.init() den Mixer vorher mit acht Kanälen hochgezogen, gibt es
    # weniger, und pygame.mixer.Channel(8) wirft dann IndexError mitten im
    # Menü. Erst aufgefallen, als jeder Knopfdruck einen Klang bekam.
    verfuegbar = min(_kanaele.anzahl, pygame.mixer.get_num_channels())
    if verfuegbar <= 0:
        return
    nummer = _kanaele.belegen(
        staerke,
        lambda k: k < verfuegbar and not pygame.mixer.Channel(k).get_busy())
    if nummer is None or nummer >= verfuegbar:
        return
    kanal = pygame.mixer.Channel(nummer)
    p = max(-1.0, min(1.0, panorama))
    links = staerke * min(1.0, 1.0 - p)
    rechts = staerke * min(1.0, 1.0 + p)
    kanal.set_volume(links, rechts)
    kanal.play(klang)


# ── Menügeräusche ───────────────────────────────────────────────────────────

#: Welcher Anlass welche Datei bekommt und wie laut.
#:
#: Kurz gehalten mit Absicht: nicht jeder Klick klingt, sonst bedeutet keiner
#: mehr etwas. Es klingt, was **etwas bewirkt** — ein verstellter Wert, ein
#: ausgelöster Knopf, ein Schritt zurück — und was **nicht** geht.
#: Bloßes Bewegen des Fokus bleibt still.
MENUE_KLAENGE = {
    "verstellt":   ("click",   0.45),   # ‹ › hat einen Wert geändert
    "ausgeloest":  ("click",   0.70),   # Knopf gedrückt: Start, Weiter, OK
    "zurueck":     ("ui-back", 0.60),   # eine Ebene hoch (B / ESC / Zurück)
    "gesperrt":    ("fehler",  0.55),   # gesperrter Knopf, abgelehnte Eingabe
}


#: Wie oft ``menue()`` schon geklungen hat. Gebraucht als Nachweis, dass ein
#: Klick beantwortet wurde — siehe :func:`klick_quittieren`.
_menue_zaehler = 0


def klang_zaehler() -> int:
    return _menue_zaehler


def menue(anlass: str) -> None:
    """Menügeräusch für einen Anlass aus MENUE_KLAENGE.

    Eine Stelle für alle Menüklänge: die Seiten rufen den Anlass, nicht den
    Dateinamen. Sonst müsste jede Seite wissen, welche Datei gerade gilt, und
    eine neue Seite bringt garantiert eine vierte Lautstärke mit.
    """
    global _menue_zaehler
    eintrag = MENUE_KLAENGE.get(anlass)
    if eintrag is None:
        return
    _menue_zaehler += 1
    name, laut = eintrag
    spielen(name, laut, bereich=MENUE)


def klick_quittieren(event, zaehler_vorher: int, anlass: str = "ausgeloest") -> None:
    """Einen Klick beantworten, der sonst still geblieben wäre.

    Gemeldet im Playtest am 03.08.2026: „Klick-Sound wird nicht bei jedem Klick
    auf einen Button oder ein Textfeld abgespielt." Die Ursache ist die Bauweise
    und nicht eine vergessene Zeile: der Klang hängt an ``FocusGroup``, und
    jede Seite mit **eigenen** Klickflächen — Farbfelder der Werkstatt,
    Fahrzeugkacheln, Streckenkacheln, Pfeilknöpfe — läuft daran vorbei. Das sind
    Dutzende Stellen, und die nächste neue Seite wäre die nächste stille.

    Deshalb das Netz von oben: der Aufrufer weiß, dass der Klick *verarbeitet*
    wurde, und fragt hier nach, ob dabei schon etwas geklungen hat. Wenn nicht,
    klingt es jetzt. Doppelt kann es nicht klingen, und ein Klick ins Leere
    bleibt still — beides wäre schlimmer als eine fehlende Quittung.
    """
    import pygame
    if event.type != pygame.MOUSEBUTTONDOWN or getattr(event, "button", 0) != 1:
        return
    if klang_zaehler() != zaehler_vorher:
        return
    menue(anlass)


#: Kanäle insgesamt: Einzelklänge, einer je Motor, einer fürs Quietschen.
#: Ein Online-Grand-Prix hat mehr Fahrzeuge im Bild als ein lokales Rennen; wer
#: keinen Kanal bekommt, bleibt stumm.
KANAELE_GESAMT = EINZEL_KANAELE + 17


def _puffer() -> int:
    """Puffergroesse aus der Klangabstimmung (§C8), mit Rueckfall auf 512.

    Der Mixer nimmt sie nur beim Start an — deshalb steht auf der Laborseite
    dabei, dass sie erst nach einem Neustart gilt. Ein Fehler beim Lesen darf
    den Ton nicht verhindern: dann eben der alte Wert.
    """
    try:
        from src.core import motorklang
        return int(motorklang.puffer())
    except Exception:
        return 512


def mixer_vorbereiten() -> None:
    """Abtastrate anmelden, **bevor** ``pygame.init()`` läuft.

    ``pygame.init()`` startet den Mixer mit — und zwar mit 44,1 kHz. Ein
    späteres ``mixer.init`` wäre dann wirkungslos. ``pre_init`` legt die Werte
    vorher fest, sodass es keinen Neustart des Mixers braucht.
    """
    try:
        import pygame
        pygame.mixer.pre_init(frequency=SR, size=-16, channels=2, buffer=_puffer())
    except Exception as exc:
        print(f"[sfx] Mixer-Vorgabe nicht gesetzt: {exc}")


def mixer_starten() -> bool:
    """Mixer mit der Abtastrate der Aufnahmen starten.

    48 kHz mit Absicht: alle Effektdateien liegen so vor, und ein Mixer mit
    44,1 kHz würde jeden davon beim Laden umrechnen — samt der Motorschleifen,
    deren Länge dabei nicht mehr zur Drehzahl passt.

    Läuft der Mixer bereits mit der falschen Rate (etwa weil ``pygame.init()``
    ihn ohne Vorgabe gestartet hat), wird er neu gestartet. Ein bloßes „läuft
    schon, alles gut" hat genau das verdeckt: 44,1 kHz und acht Kanäle, also
    keiner für einen Motor.
    """
    try:
        import pygame
        laeuft = pygame.mixer.get_init()
        if laeuft and laeuft[0] != SR:
            pygame.mixer.quit()
            laeuft = None
        if not laeuft:
            pygame.mixer.init(frequency=SR, size=-16, channels=2, buffer=_puffer())
        if pygame.mixer.get_num_channels() < KANAELE_GESAMT:
            pygame.mixer.set_num_channels(KANAELE_GESAMT)
        return True
    except Exception as exc:
        print(f"[sfx] Mixer konnte nicht starten: {exc}")
        return False
