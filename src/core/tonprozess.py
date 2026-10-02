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

import json
import os
import subprocess
import sys
import time
import weakref
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
#: Stand der Klangwerte (``motorklang``): der Spielprozess zaehlt hoch, nachdem er
#: den Text im Wertefeld abgelegt hat; der Erzeuger meldet in ``K_NEU_IST``, was er
#: uebernommen hat.
K_NEU_LADEN, K_NEU_IST, K_WERTE_LAENGE, K_AUSGABERATE_IST = 16, 17, 18, 19
KOPF_N = 32
#: Platz fuer den Klangwerte-Text (JSON, derzeit unter 3 KB).
WERTEFELD = 32768

# Messwerte des Erzeugers (float64)
M_MAX, M_SUMME, M_ZAHL, M_SPAET, M_GERECHNET = 0, 1, 2, 3, 4
MESS_N = 16

# Zustand eines Stimmenplatzes. FEHLER setzt der Erzeuger, wenn er die Stimme nicht
# bauen konnte; nur der Spielprozess raeumt ihn ab (ueber ENDE). So wird ein Platz
# nie unter einer noch lebenden Fernstimme neu vergeben.
FREI, AKTIV, ENDE, FEHLER = 0, 1, 2, 3

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
        pos += kapazitaet * 2 * 4
        self.wertefeld = np.ndarray((WERTEFELD,), dtype=np.uint8, buffer=buf,
                                    offset=pos)
        self.zaehler = self.kopf[0:4]

    @staticmethod
    def groesse(kapazitaet: int) -> int:
        return (KOPF_N * 8 + MESS_N * 8 + PLAETZE * 4 + 8 + PLAETZE * MOTORNAME + 8
                + PLAETZE * WERTE_N * 8 + 8 + kapazitaet * 2 * 4 + WERTEFELD)

    def freigeben(self) -> None:
        """Sichten loesen, damit der Block geschlossen werden kann."""
        for name in ("kopf", "mess", "zustand", "motor", "werte", "ring", "zaehler",
                     "wertefeld"):
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
    # Nur unter Windows: ``SharedMemory`` meldet sich auf POSIX beim
    # resource_tracker an, der im gepackten Spiel dessen Programmdatei erneut
    # startet (ohne freeze_support) und beim Ende des Erzeugers den Block loescht.
    if sys.platform != "win32":
        return False, "nur unter Windows"
    if not sys.executable or not os.path.isfile(sys.executable):
        return False, "kein Interpreter"
    return True, ""


#: Argument, mit dem das gepackte Spiel (und ``main.py``) als Erzeuger startet.
FLAGGE = "--tonprozess"


def kommando(name: str, eltern_pid: int, kapazitaet: int, gepackt: bool | None = None,
             interpreter: str | None = None) -> list[str]:
    """Befehlszeile des Erzeugerprozesses.

    Gepackt (PyInstaller) ist ``sys.executable`` das Spiel selbst; es wird mit
    :data:`FLAGGE` gestartet, und ``main.py`` springt dann vor allem anderen
    (Fenster, Einzelinstanz) in :func:`haupt`. Aus den Quellen ist es der
    Interpreter mit ``-m``.
    """
    gepackt = bool(getattr(sys, "frozen", False)) if gepackt is None else gepackt
    exe = interpreter or sys.executable
    rest = [name, str(eltern_pid), str(kapazitaet)]
    if gepackt:
        return [exe, FLAGGE] + rest
    return [exe, "-m", "src.core.tonprozess"] + rest


class Fernstimme:
    """Eine Stimme im Erzeugerprozess, vom Spielfaden aus gesteuert.

    Dieselbe Schnittstelle wie :class:`tonmischer.Stimme`, soweit der Spielfaden
    sie benutzt (``einstellen``, ``beenden``), dazu :meth:`drehzahl_setzen`.
    """

    __slots__ = ("_s", "_i", "_beendet", "_erzeuger", "_ersatz", "__weakref__")

    def __init__(self, speicher: Speicher, platz: int, erzeuger=None) -> None:
        self._s = speicher
        self._i = platz
        self._beendet = False
        self._erzeuger = erzeuger
        #: Stimme im Mischer des Spielprozesses, falls der Erzeuger ausgefallen
        #: ist und der Faden uebernommen hat; dann gehen alle Aufrufe dorthin.
        self._ersatz = None

    def uebernehmen(self, mischer) -> None:
        """Rueckfall: die Stimme im Faden des Spielprozesses weiterfuehren."""
        if self._beendet or self._erzeuger is None or self._s.werte is None:
            return
        w = self._s.werte[self._i]
        self._ersatz = mischer.stimme_anlegen(self._erzeuger, float(w[W_LINKS]),
                                              float(w[W_RECHTS]))

    def einstellen(self, links: float, rechts: float) -> None:
        if self._ersatz is not None:
            self._ersatz.einstellen(links, rechts)
            return
        if self._beendet or self._s.werte is None:
            return
        w = self._s.werte[self._i]
        w[W_LINKS] = max(0.0, float(links))
        w[W_RECHTS] = max(0.0, float(rechts))

    def drehzahl_setzen(self, upm: float) -> None:
        if self._ersatz is None and not self._beendet and self._s.werte is not None:
            self._s.werte[self._i, W_UPM] = float(upm)

    def beenden(self) -> None:
        if self._beendet:
            return
        self._beendet = True
        if self._ersatz is not None:
            self._ersatz.beenden()
            return
        if self._s.werte is None:
            return
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
        self.letzter_herzschlag = (-1, 0.0)
        #: Handle auf den eigentlichen Erzeuger (``K_KIND_PID``), einmal geoeffnet.
        self.kind_handle = None
        self._oversize_gemeldet = False
        self.fernstimmen: weakref.WeakSet = weakref.WeakSet()
        self.gestartet = 0.0

    def starten(self) -> None:
        wurzel = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        flags = 0x08000000 if sys.platform == "win32" else 0   # CREATE_NO_WINDOW
        # Gepackt liegt ``data/`` neben dem Spiel und ``main.py`` stellt das
        # Arbeitsverzeichnis selbst um; aus den Quellen ist es die Wurzel.
        cwd = None if getattr(sys, "frozen", False) else wurzel
        self.gestartet = time.monotonic()
        self.prozess = subprocess.Popen(
            kommando(self.speicher.shm.name, os.getpid(), self.kapazitaet),
            cwd=cwd, stdin=subprocess.DEVNULL, creationflags=flags)

    def _kind_beenden(self, warte: float = 1.0) -> None:
        """Den Erzeuger sicher loswerden, auch den hinter dem Startprogramm.

        Unter Windows startet die virtuelle Umgebung den eigentlichen Interpreter
        als Kind des Startprogramms; ``prozess`` ist dann nur das Startprogramm,
        der Schreiber im Ring aber der Prozess mit ``K_KIND_PID``. Beide werden
        beendet und gewartet, bis der Herzschlag steht - erst dann gibt es keinen
        zweiten Schreiber mehr.
        """
        k = self.speicher.kopf if self.speicher is not None else None
        if k is None:
            return
        # Zuerst das Handle: jetzt lebt der Erzeuger sicher noch.
        self.kind_festhalten()
        k[K_HALT] = 1
        p = self.prozess
        if p is not None and p.poll() is None:
            try:
                p.terminate()
                p.wait(timeout=warte)
            except Exception:
                pass
        # Nie ueber die blanke Prozessnummer: sie koennte laengst neu vergeben sein.
        self.kind_festhalten()
        if self.kind_handle is not None:
            _prozess_beenden(self.kind_handle, warte)
        ende = time.monotonic() + warte
        while time.monotonic() < ende:
            davor = int(k[K_HERZ])
            time.sleep(0.04)
            if int(k[K_HERZ]) == davor:
                break

    def kind_festhalten(self) -> bool:
        """Handle auf den Erzeuger oeffnen, solange er sicher der unsere ist.

        Gemeint ist der Prozess mit ``K_KIND_PID``; geoeffnet wird einmal, nachdem
        er sich bereit gemeldet hat (oder solange das Startprogramm noch lebt).
        Gelingt es nicht, wird er nicht angefasst.
        """
        if self.kind_handle is not None:
            return True
        k = self.speicher.kopf if self.speicher is not None else None
        if k is None:
            return False
        pid = int(k[K_KIND_PID])
        if not pid or pid == os.getpid():
            return False
        if not (k[K_BEREIT] or self.lebt()):
            return False
        self.kind_handle = _prozess_oeffnen(pid)
        return self.kind_handle is not None

    def stoppen(self) -> None:
        """Prozess anhalten, Speicher **behalten** (der Rueckfall liest den Ring weiter)."""
        self._kind_beenden()

    @property
    def bereit(self) -> bool:
        return bool(self.speicher and self.speicher.kopf[K_BEREIT])

    def lebt(self) -> bool:
        return self.prozess is not None and self.prozess.poll() is None

    def stimme_anlegen(self, motor: str, tonhoehe: float, faerbung: float,
                       links: float = 0.0, rechts: float = 0.0,
                       erzeuger=None) -> Fernstimme | None:
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
                f = Fernstimme(s, i, erzeuger)
                self.fernstimmen.add(f)
                return f
        return None

    @property
    def stimmen(self) -> int:
        return int(np.count_nonzero(self.speicher.zustand))

    def alle_beenden(self) -> None:
        s = self.speicher
        for i in range(PLAETZE):
            if s.zustand[i] in (AKTIV, FEHLER):
                s.werte[i, W_LINKS] = 0.0
                s.werte[i, W_RECHTS] = 0.0
                s.zustand[i] = ENDE

    def werte_senden(self, text: str | None = None) -> None:
        """Klangwerte (``motorklang``) an den Erzeuger geben."""
        s = self.speicher
        if s is None or s.kopf is None:
            return
        if text is None:
            from src.core import motorklang
            text = motorklang.stand_als_json()
        roh = text.encode("utf-8")
        if len(roh) > WERTEFELD:
            if not self._oversize_gemeldet:
                self._oversize_gemeldet = True
                _protokoll(f"Klangwerte ({len(roh)} Byte) passen nicht in das "
                           f"Wertefeld ({WERTEFELD}); der Erzeuger behaelt den alten Stand")
            return
        # Seqlock: ungerader Zaehler heisst "wird geschrieben".
        s.kopf[K_NEU_LADEN] += 1
        s.wertefeld[:len(roh)] = np.frombuffer(roh, dtype=np.uint8)
        s.kopf[K_WERTE_LAENGE] = len(roh)
        s.kopf[K_NEU_LADEN] += 1

    def zuruecksetzen(self) -> None:
        """Messwerte des Erzeugers fuer ein neues Rennen auf null."""
        self.speicher.kopf[K_ZURUECK] += 1

    def beenden(self) -> None:
        """Halten, kurz warten, im Zweifel beenden, Speicher freigeben."""
        s = self.speicher
        if s is None:
            return
        try:
            self._kind_beenden(1.0)
        except Exception:
            pass
        self.prozess = None
        if self.kind_handle is not None:
            _prozess_schliessen(self.kind_handle)
            self.kind_handle = None
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
            k = _kernel32()
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


_kern = None


def _kernel32():
    """Eigene kernel32-Instanz: ``restype``/``argtypes`` der gemeinsamen
    ``ctypes.windll.kernel32`` gehoeren dem ganzen Prozess, nicht uns."""
    global _kern
    if _kern is None:
        import ctypes
        _kern = ctypes.WinDLL("kernel32", use_last_error=True)
    return _kern


def _prozess_oeffnen(pid: int):
    """Handle auf einen Prozess (nur Windows), zum Warten und Beenden.

    Ueber das Handle lebt man nicht Gefahr, eine wiederverwendete Prozessnummer
    zu treffen: es zeigt auf genau den Prozess, der beim Oeffnen gemeint war.
    """
    if sys.platform != "win32" or not pid:
        return None
    try:
        import ctypes
        k = _kernel32()
        k.OpenProcess.restype = ctypes.c_void_p
        h = k.OpenProcess(0x00100000 | 0x0001, False, int(pid))  # SYNCHRONIZE | TERMINATE
        return h or None
    except Exception:
        return None


def _prozess_beenden(handle, warte: float) -> None:
    try:
        import ctypes
        k = _kernel32()
        k.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        k.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k.TerminateProcess(handle, 1)
        k.WaitForSingleObject(handle, int(warte * 1000))
    except Exception:
        pass


def _prozess_schliessen(handle) -> None:
    try:
        import ctypes
        k = _kernel32()
        k.CloseHandle.argtypes = [ctypes.c_void_p]
        k.CloseHandle(handle)
    except Exception:
        pass


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
            kern = _kernel32()
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

    neu_ist = 0
    neu_ist = _werte_holen(sp, neu_ist)
    k[K_NEU_IST] = neu_ist

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
            if int(k[K_NEU_LADEN]) != neu_ist:
                neu = _werte_holen(sp, neu_ist)
                if neu != neu_ist:
                    neu_ist = neu
                    for _st, kind in kinder.values():
                        kind.stimme.werte_setzen()
                    k[K_NEU_IST] = neu_ist
            _abgleichen(sp, m, kinder, tonmischer)
            if int(k[K_AUSGABERATE]) != m.ausgaberate:
                m.ausgaberate_setzen(int(k[K_AUSGABERATE]))
            k[K_AUSGABERATE_IST] = m.ausgaberate
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


def _werte_holen(sp: Speicher, bekannt: int) -> int:
    """Klangwerte aus dem gemeinsamen Speicher uebernehmen; gibt den Stand zurueck.

    Seqlock: der Spielprozess zaehlt vor dem Schreiben hoch (ungerade) und danach
    noch einmal (gerade). Gelesen wird nur bei geradem Zaehler, und nur gilt, wenn
    er sich waehrenddessen nicht geaendert hat; sonst bleibt der alte Stand
    (*bekannt*) und der naechste Durchlauf versucht es erneut.
    """
    from src.core import motorklang
    c1 = int(sp.kopf[K_NEU_LADEN])
    if c1 % 2:
        return bekannt
    laenge = int(sp.kopf[K_WERTE_LAENGE])
    if c1 == 0 or laenge <= 0:
        return c1
    text = bytes(sp.wertefeld[:laenge]).decode("utf-8", "replace")
    if int(sp.kopf[K_NEU_LADEN]) != c1:
        return bekannt
    try:
        motorklang.stand_uebernehmen(text)
    except Exception:
        pass
    return c1


def _abgleichen(sp: Speicher, m, kinder: dict, tonmischer) -> None:
    """Stimmenplaetze und ihre Werte uebernehmen."""
    zust = sp.zustand.tolist()
    werte = None
    for i, z in enumerate(zust):
        kind = kinder.get(i)
        if z == FEHLER:
            continue
        if z == AKTIV:
            if kind is None:
                roh = bytes(sp.motor[i]).split(b"\0", 1)[0].decode("ascii", "replace")
                w = sp.werte[i]
                try:
                    stimme = _Kind(roh, float(w[W_TON]), float(w[W_FARB]))
                except Exception:
                    stimme = None
                if stimme is None or not stimme.stimme:
                    # Keine Aufnahmen: still bleiben. Nicht FREI: der Platz
                    # gehoert noch der Fernstimme des Spielprozesses.
                    # Erst nachsehen: hat der Spielprozess inzwischen ENDE
                    # gesetzt, darf das nicht mit FEHLER ueberschrieben werden.
                    if sp.zustand[i] == AKTIV:
                        sp.zustand[i] = FEHLER
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


def _protokoll(text: str) -> None:
    """Ausfall in eine Datei schreiben - ein Fenster gibt es hier nie."""
    try:
        try:
            from src.core.paths import user_path
            pfad = user_path("data", "settings", "tonprozess.log")
        except Exception:
            pfad = "tonprozess.log"
        with open(pfad, "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")
    except Exception:
        pass


def haupt(argumente: list[str]) -> int:
    """Einstieg des Erzeugerprozesses: ``[name, eltern_pid, kapazitaet]``.

    Faengt **alles** und meldet es nur in die Protokolldatei: im gepackten Spiel
    zeigte eine unbehandelte Ausnahme einen Fehlerdialog des Bootloaders. Das
    Spiel merkt den Ausfall an der fehlenden Bereit- bzw. Herzschlagmarke und
    rechnet im Faden weiter.
    """
    try:
        return _lauf(argumente[0], int(argumente[1]), int(argumente[2]))
    except KeyboardInterrupt:
        return 0
    except BaseException:
        import traceback
        _protokoll("Erzeugerprozess ausgefallen:\n" + traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(haupt(sys.argv[1:]))
