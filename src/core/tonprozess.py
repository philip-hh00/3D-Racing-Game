"""Der Erzeuger des Motorklangs in einem eigenen Prozess (01.10.2026).

**Warum.** Der Erzeugerfaden im Spielprozess kostete den Spielfaden gemessen
sechs bis acht Millisekunden je Bild (``tools/rennen_probe.py gp --stufe hoch``:
14,5 ms ohne Ton, 22,6 ms mit), obwohl er nur rund einen Millisekunden rechnet.
Das liegt nicht an der Menge, sondern am GIL: jeder numpy-Aufruf des Erzeugers
gibt ihn ab, und jede Rueckgabe ist ein erzwungener Wechsel, der den Spielfaden
anhaelt. Mit gestapelten Stimmen (``motorstapel``) sank die Rechenzeit auf ein
Drittel, der Wechsel blieben (Mikrotest: ein Python-Faden mit 0,8 ms Rechnung
kostet den anderen 1,9 ms je Bild). Solange beide Faeden im selben Prozess
laufen, bleibt es ein Vielfaches der Rechenzeit.

Ein **eigener Prozess** hat einen eigenen GIL: der Spielfaden schreibt je Bild
nur noch ein paar Zahlen in einen gemeinsamen Speicher, den Rest erledigt der
Erzeuger nebenan.

**Was im gemeinsamen Speicher liegt.** Alles in einem Block, ohne Sperre:

* ein Kopf mit Zaehlern (geschrieben, gelesen, groesster Abruf), Haltmarke,
  Bereitmarke, Geraeterate, Vorrat und einem Herzschlag,
* Messwerte des Erzeugers (damit ``zustand()`` sie weiter melden kann),
* eine Tabelle von Stimmenplaetzen: Zustand, Motor, Klangfarbe und die Werte,
  die der Spielfaden je Bild setzt (Drehzahl, Lautstaerke links und rechts),
* der Ring selbst.

Der Spielfaden legt eine Stimme an, indem er einen freien Platz fuellt und den
Zustand **zuletzt** auf 1 setzt; er beendet sie mit Zustand 2. Der Erzeuger
raeumt auf und setzt den Platz auf 0 zurueck. Jede Zahl hat einen Schreiber.

**Start ohne ``multiprocessing``.** Der Erzeuger wird als eigener Interpreter
gestartet (``python -m src.core.tonprozess``) und bekommt nur den Namen des
Speichers und die Prozessnummer des Spiels. ``multiprocessing`` mit ``spawn``
fuehrt das Hauptmodul erneut aus; in einem Skript ohne Schutz (Werkzeuge, Tests)
wuerde das ein zweites Spiel starten. In einem gepackten Spiel (``frozen``)
bleibt es beim Faden: dort ist ``sys.executable`` das Spiel selbst.

**Elternlos beenden.** Der Erzeuger prueft jede halbe Sekunde, ob das Spiel noch
lebt, und endet sonst von selbst; ein abgestuerztes Spiel hinterlaesst keinen
Prozess, der das Geraet nicht mehr bedient.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from multiprocessing import shared_memory

import numpy as np

#: Stimmenplaetze. Ein Rennen hat hoechstens acht Fahrzeuge; der Rest ist Luft
#: fuer Wiedereinstiege, die noch ausblenden.
PLAETZE = 24
MOTORNAME = 16

# Kopf (int64)
K_GESCHRIEBEN, K_GELESEN, K_MAX_ABRUF = 0, 1, 2
K_HALT, K_BEREIT, K_AUSGABERATE, K_VORRAT, K_QUELLRATE = 4, 5, 6, 7, 8
K_BEGRENZEN, K_ZURUECK, K_KAPAZITAET, K_STUECK, K_HERZ = 9, 10, 11, 12, 13
K_VORRAT_IST, K_KIND_PID = 14, 15
KOPF_N = 32

# Messwerte des Erzeugers (float64)
M_MAX, M_SUMME, M_ZAHL, M_SPAET, M_GERECHNET = 0, 1, 2, 3, 4
MESS_N = 16

# Zustand eines Stimmenplatzes
FREI, AKTIV, ENDE = 0, 1, 2

# Spalten der Werte
W_UPM, W_LINKS, W_RECHTS, W_TON, W_FARB = 0, 1, 2, 3, 4
WERTE_N = 5


class Speicher:
    """Die Sicht auf den gemeinsamen Block (Spiel und Erzeuger benutzen sie gleich)."""

    def __init__(self, shm: shared_memory.SharedMemory, kapazitaet: int) -> None:
        self.shm = shm
        buf = shm.buf
        pos = 0
        self.kopf = np.ndarray((KOPF_N,), dtype=np.int64, buffer=buf, offset=pos)
        pos += KOPF_N * 8
        self.mess = np.ndarray((MESS_N,), dtype=np.float64, buffer=buf, offset=pos)
        pos += MESS_N * 8
        self.zustand = np.ndarray((PLAETZE,), dtype=np.int32, buffer=buf, offset=pos)
        pos += PLAETZE * 4
        pos += (-pos) % 8
        self.motor = np.ndarray((PLAETZE, MOTORNAME), dtype=np.uint8, buffer=buf,
                                offset=pos)
        pos += PLAETZE * MOTORNAME
        pos += (-pos) % 8
        self.werte = np.ndarray((PLAETZE, WERTE_N), dtype=np.float64, buffer=buf,
                                offset=pos)
        pos += PLAETZE * WERTE_N * 8
        pos += (-pos) % 8
        self.ring = np.ndarray((kapazitaet, 2), dtype=np.float32, buffer=buf,
                               offset=pos)
        self.zaehler = self.kopf[0:4]

    @staticmethod
    def groesse(kapazitaet: int) -> int:
        return (KOPF_N * 8 + MESS_N * 8 + PLAETZE * 4 + 8 + PLAETZE * MOTORNAME + 8
                + PLAETZE * WERTE_N * 8 + 8 + kapazitaet * 2 * 4)

    def freigeben(self) -> None:
        """Sichten loesen, damit der Block geschlossen werden kann."""
        for name in ("kopf", "mess", "zustand", "motor", "werte", "ring", "zaehler"):
            setattr(self, name, None)
        try:
            self.shm.close()
        except Exception:
            pass


# ── Spielprozess ─────────────────────────────────────────────────────────────

def prozess_moeglich() -> tuple[bool, str]:
    """Darf der Erzeuger als eigener Prozess laufen? Zweiter Wert: warum nicht."""
    if os.environ.get("RACING_TON_PROZESS", "1") == "0":
        return False, "per Umgebungsvariable abgeschaltet"
    if getattr(sys, "frozen", False):
        return False, "gepacktes Spiel"
    if not sys.executable or not os.path.isfile(sys.executable):
        return False, "kein Interpreter"
    return True, ""


class Fernstimme:
    """Eine Stimme im Erzeugerprozess, vom Spielfaden aus gesteuert.

    Dieselbe Schnittstelle wie :class:`tonmischer.Stimme`, soweit der Spielfaden
    sie benutzt (``einstellen``, ``beenden``), dazu :meth:`drehzahl_setzen`.
    """

    __slots__ = ("_s", "_i", "_beendet")

    def __init__(self, speicher: Speicher, platz: int) -> None:
        self._s = speicher
        self._i = platz
        self._beendet = False

    def einstellen(self, links: float, rechts: float) -> None:
        if self._beendet:
            return
        w = self._s.werte[self._i]
        w[W_LINKS] = max(0.0, float(links))
        w[W_RECHTS] = max(0.0, float(rechts))

    def drehzahl_setzen(self, upm: float) -> None:
        if not self._beendet:
            self._s.werte[self._i, W_UPM] = float(upm)

    def beenden(self) -> None:
        if self._beendet:
            return
        self._beendet = True
        self._s.werte[self._i, W_LINKS] = 0.0
        self._s.werte[self._i, W_RECHTS] = 0.0
        self._s.zustand[self._i] = ENDE

    @property
    def beendet(self) -> bool:
        return self._beendet


class Erzeugerprozess:
    """Spielseite: Block anlegen, Prozess starten, Stimmen vergeben, aufraeumen."""

    def __init__(self, kapazitaet: int, stueck: int, quellrate: int,
                 begrenzen: bool, vorrat: int) -> None:
        self.kapazitaet = int(kapazitaet)
        shm = shared_memory.SharedMemory(create=True,
                                         size=Speicher.groesse(self.kapazitaet))
        self.speicher = Speicher(shm, self.kapazitaet)
        self.speicher.kopf[:] = 0
        self.speicher.mess[:] = 0.0
        self.speicher.zustand[:] = FREI
        self.speicher.ring[:] = 0.0
        k = self.speicher.kopf
        k[K_QUELLRATE] = int(quellrate)
        k[K_AUSGABERATE] = int(quellrate)
        k[K_BEGRENZEN] = 1 if begrenzen else 0
        k[K_KAPAZITAET] = self.kapazitaet
        k[K_STUECK] = int(stueck)
        k[K_VORRAT] = int(vorrat)
        k[K_VORRAT_IST] = int(vorrat)
        self.prozess: subprocess.Popen | None = None

    def starten(self) -> None:
        wurzel = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        flags = 0x08000000 if sys.platform == "win32" else 0   # CREATE_NO_WINDOW
        self.prozess = subprocess.Popen(
            [sys.executable, "-m", "src.core.tonprozess", self.speicher.shm.name,
             str(os.getpid()), str(self.kapazitaet)],
            cwd=wurzel, stdin=subprocess.DEVNULL, creationflags=flags)

    @property
    def bereit(self) -> bool:
        return bool(self.speicher and self.speicher.kopf[K_BEREIT])

    def lebt(self) -> bool:
        return self.prozess is not None and self.prozess.poll() is None

    def stimme_anlegen(self, motor: str, tonhoehe: float, faerbung: float,
                       links: float = 0.0, rechts: float = 0.0) -> Fernstimme | None:
        s = self.speicher
        zust = s.zustand
        for i in range(PLAETZE):
            if zust[i] == FREI:
                roh = motor.encode("ascii", "replace")[:MOTORNAME]
                s.motor[i, :] = 0
                s.motor[i, :len(roh)] = np.frombuffer(roh, dtype=np.uint8)
                w = s.werte[i]
                w[W_UPM] = 0.0
                w[W_LINKS] = max(0.0, float(links))
                w[W_RECHTS] = max(0.0, float(rechts))
                w[W_TON] = float(tonhoehe)
                w[W_FARB] = float(faerbung)
                zust[i] = AKTIV                     # zuletzt: macht den Platz sichtbar
                return Fernstimme(s, i)
        return None

    @property
    def stimmen(self) -> int:
        return int(np.count_nonzero(self.speicher.zustand))

    def alle_beenden(self) -> None:
        s = self.speicher
        for i in range(PLAETZE):
            if s.zustand[i] == AKTIV:
                s.werte[i, W_LINKS] = 0.0
                s.werte[i, W_RECHTS] = 0.0
                s.zustand[i] = ENDE

    def zuruecksetzen(self) -> None:
        """Messwerte des Erzeugers fuer ein neues Rennen auf null."""
        self.speicher.kopf[K_ZURUECK] += 1

    def beenden(self) -> None:
        """Halten, kurz warten, im Zweifel beenden, Speicher freigeben."""
        s = self.speicher
        if s is None:
            return
        try:
            s.kopf[K_HALT] = 1
        except Exception:
            pass
        p = self.prozess
        if p is not None:
            try:
                p.wait(timeout=1.0)
            except Exception:
                try:
                    p.terminate()
                    p.wait(timeout=1.0)
                except Exception:
                    pass
            # Hinter dem Startprogramm der virtuellen Umgebung steckt der
            # eigentliche Interpreter; er endet an der Haltmarke selbst.
            self.prozess = None
        name = s.shm.name
        s.freigeben()
        import gc
        gc.collect()          # Sichten anderer Stellen loesen, sonst haelt der Block
        try:
            shm = shared_memory.SharedMemory(name=name)
            shm.close()
            shm.unlink()
        except Exception:
            pass
        self.speicher = None


# ── Erzeugerprozess ──────────────────────────────────────────────────────────

def _eltern_lebt(pid: int):
    """Funktion, die sagt, ob das Spiel (``pid``) noch lebt."""
    if sys.platform == "win32":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            k.OpenProcess.restype = ctypes.c_void_p
            k.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            handle = k.OpenProcess(0x00100000, False, int(pid))   # SYNCHRONIZE
            if not handle:
                return lambda: False

            def lebt() -> bool:
                return k.WaitForSingleObject(handle, 0) != 0
            return lebt
        except Exception:
            return lambda: True

    def lebt_posix() -> bool:
        try:
            os.kill(int(pid), 0)
            return True
        except OSError:
            return False
    return lebt_posix


class _Kind:
    """Eine Stimme im Erzeugerprozess; ``stapel`` rechnet alle in einem Durchgang."""

    def __init__(self, motor: str, tonhoehe: float, faerbung: float) -> None:
        from src.core import sfx
        self.stimme = sfx.Motorstimme(motor, tonhoehe, faerbung,
                                      startphase_streuen=True)
        self._upm = 0.0

    def __call__(self, laenge: int):
        return self.stimme.block(self._upm, laenge)

    @staticmethod
    def stapel(stimmen: list, laenge: int):
        from src.core import motorstapel
        return motorstapel.bloecke([s.stimme for s in stimmen],
                                   [s._upm for s in stimmen], laenge)


def _lauf(name: str, eltern_pid: int, kapazitaet: int) -> int:
    from src.core import sfx, tonmischer

    shm = shared_memory.SharedMemory(name=name)
    sp = Speicher(shm, kapazitaet)
    k = sp.kopf
    k[K_KIND_PID] = os.getpid()
    lebt = _eltern_lebt(eltern_pid)
    try:
        import ctypes
        if sys.platform == "win32":
            kern = ctypes.windll.kernel32
            kern.SetThreadPriority(kern.GetCurrentThread(), 1)   # ABOVE_NORMAL
    except Exception:
        pass

    # Aufnahmen vor der Bereitmarke laden: danach ruft der Spielfaden die
    # ersten Stimmen an, und ein Laden mitten im Erzeugen risse ein Loch.
    for motor in ("4zyl", "6zyl", "8zyl"):
        try:
            sfx.schichten(motor)
        except Exception:
            pass

    kinder: dict[int, tuple] = {}

    def entfernt(stimme) -> None:
        for platz, (st, _kind) in list(kinder.items()):
            if st is stimme:
                del kinder[platz]
                sp.zustand[platz] = FREI

    m = tonmischer.Mischer(kapazitaet=kapazitaet, vorrat=int(k[K_VORRAT]),
                           stueck=int(k[K_STUECK]), quellrate=int(k[K_QUELLRATE]),
                           ausgaberate=int(k[K_AUSGABERATE]),
                           begrenzen=bool(k[K_BEGRENZEN]), ring=sp.ring,
                           zaehler=sp.zaehler, bei_entfernt=entfernt)
    vorrat_basis = int(k[K_VORRAT])
    zurueck = int(k[K_ZURUECK])
    k[K_BEREIT] = 1
    naechste_wache = time.monotonic() + 0.5

    while not k[K_HALT]:
        try:
            _abgleichen(sp, m, kinder, tonmischer)
            if int(k[K_AUSGABERATE]) != m.ausgaberate:
                m.ausgaberate_setzen(int(k[K_AUSGABERATE]))
            if int(k[K_VORRAT]) != vorrat_basis:
                vorrat_basis = int(k[K_VORRAT])
                m.vorrat = vorrat_basis
            if int(k[K_ZURUECK]) != zurueck:
                zurueck = int(k[K_ZURUECK])
                m.erzeugen_max_ms = m.erzeugen_summe_ms = 0.0
                m.erzeugen_zahl = m.erzeugen_spaet = m.gerechnet = 0
            m.vorrat_nachfuehren()
            if m.braucht_nachschub():
                if m.erzeugen() <= 0:
                    time.sleep(0.002)
                mess = sp.mess
                mess[M_MAX] = m.erzeugen_max_ms
                mess[M_SUMME] = m.erzeugen_summe_ms
                mess[M_ZAHL] = m.erzeugen_zahl
                mess[M_SPAET] = m.erzeugen_spaet
                mess[M_GERECHNET] = m.gerechnet
                k[K_VORRAT_IST] = m.vorrat
            else:
                time.sleep(0.002)
            k[K_HERZ] += 1
            jetzt = time.monotonic()
            if jetzt >= naechste_wache:
                naechste_wache = jetzt + 0.5
                if not lebt():
                    break
        except Exception:
            time.sleep(0.01)
    # Nicht freigeben: ``sp`` haelt Sichten auf den Block, der Prozess endet ohnehin.
    return 0


def _abgleichen(sp: Speicher, m, kinder: dict, tonmischer) -> None:
    """Stimmenplaetze und ihre Werte uebernehmen."""
    zust = sp.zustand.tolist()
    werte = None
    for i, z in enumerate(zust):
        kind = kinder.get(i)
        if z == AKTIV:
            if kind is None:
                roh = bytes(sp.motor[i]).split(b"\0", 1)[0].decode("ascii", "replace")
                w = sp.werte[i]
                try:
                    stimme = _Kind(roh, float(w[W_TON]), float(w[W_FARB]))
                except Exception:
                    stimme = None
                if stimme is None or not stimme.stimme:
                    sp.zustand[i] = FREI          # keine Aufnahmen: still bleiben
                    continue
                st = m.stimme_anlegen(stimme, 0.0, 0.0)
                kinder[i] = (st, stimme)
                kind = kinder[i]
            if werte is None:
                werte = sp.werte.copy()
            st, stimme = kind
            stimme._upm = float(werte[i, W_UPM])
            st.einstellen(werte[i, W_LINKS], werte[i, W_RECHTS])
        elif z == ENDE:
            if kind is None:
                sp.zustand[i] = FREI
            else:
                kind[0].beenden()


if __name__ == "__main__":
    try:
        sys.exit(_lauf(sys.argv[1], int(sys.argv[2]), int(sys.argv[3])))
    except KeyboardInterrupt:
        sys.exit(0)
