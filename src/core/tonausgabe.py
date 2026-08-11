"""Der Motorklang auf einem echten Audiofaden (06.08.2026).

Hier hängt das Gerät an :mod:`src.core.tonmischer`. Die Aufteilung ist Absicht:
der Mischer rechnet und ist ohne Soundkarte vollständig prüfbar, dieses Modul
redet mit der Hardware und ist es naturgemäß nicht.

**Warum überhaupt.** ``pygame.mixer`` bietet keinen Rückruf für selbst erzeugten
Ton — geprüft an pygame-ce 2.5.7, es gibt dort schlicht keine solche Funktion.
Der Motorklang musste deshalb bisher **geschoben** werden: einmal je Bild ein
Block, und pygame nimmt genau einen in die Warteschlange. Vorsprung: ein Block.
Über Kopfhörer ging das knapp gut, über Monitorlautsprecher war jede Sekunde
ein Aussetzer zu hören.

Ein Spiel, das auf fremden Rechnern laufen soll, macht es andersherum: der
Treiber ruft ab, wenn er Ton braucht. Dafür braucht es einen echten Audiofaden,
und den liefert PortAudio über ``sounddevice``.

**Drei Fäden.**

* Der **Spielfaden** ruft :func:`stimme_anlegen` und setzt Werte. Er wartet nie.
* Der **Erzeugerfaden** (hier gestartet) füllt den Ring nach.
* Der **Audiofaden** von PortAudio ruft :meth:`_rueckruf` — der kopiert nur.

**Der Rückfallweg ist kein Beiwerk.** ``sounddevice`` braucht PortAudio als
Systembibliothek. Unter Windows und macOS liegt sie im Paket bei, unter Linux
nicht immer, und auf einem Rechner ohne Ausgabegerät geht es ohnehin nicht. Wenn
irgendetwas davon fehlt, meldet :func:`starten` schlicht ``False`` — und
``sfx_rennen`` benutzt weiter den alten Weg über pygame. Lieber der bisherige
Klang als gar keiner. Der Rückfall ist deshalb genauso getestet wie der Erfolg.

**Die Abtastrate.** Angefragt werden die 48 kHz der Aufnahmen. Nimmt das Gerät
sie nicht an, rechnet PortAudio bzw. das Betriebssystem im geteilten Modus um —
das ist genau seine Aufgabe und deutlich besser, als es selbst zu versuchen.
Was tatsächlich anliegt, steht in :func:`zustand` und wird im Mitschnitt
festgehalten, damit bei einer Meldung nicht wieder geraten werden muss.
"""
from __future__ import annotations

import threading
import time

import numpy as np

from src.core import tonmischer

#: Wie lange ein Stück ist, das der Erzeuger am Stück rechnet (Abtastwerte).
#: 1024 sind bei 48 kHz gut 21 ms — klein genug, dass der Vorrat fein dosiert
#: werden kann, groß genug, dass die Synthese nicht in Kleinkram zerfällt.
STUECK = 1024

#: Vorrat im Ring. 4096 sind 85 ms: fünf Bilder Reserve bei 60 Bildern je
#: Sekunde. Das ist das Abwägen aus dem Mischer — mehr Vorrat schützt besser,
#: lässt den Motor aber hinter dem Gaspedal herhinken.
VORRAT = 4096

#: Der Ring fasst mehr als den Vorrat, sonst hätte der Erzeuger nie Platz.
KAPAZITAET = 8192

#: Wie oft nachgesehen wird, ob das Standardgerät gewechselt hat. Eine Sekunde
#: ist der Kompromiss: schnell genug, dass ein Umstecken sofort wirkt, selten
#: genug, dass die Abfrage nicht ins Gewicht fällt.
WACHE_SEKUNDEN = 1.0

_mischer: tonmischer.Mischer | None = None
_strom = None
_faden: threading.Thread | None = None
_halt = threading.Event()
_grund = ""
_rate = 0
_geraet = ""
#: Name des Standardgeräts beim letzten Nachsehen — der Fingerabdruck, an dem
#: ein Wechsel erkannt wird.
_standard = ""
_wechsel = 0


def verfuegbar() -> tuple[bool, str]:
    """Ist der Weg über PortAudio gangbar? Zweiter Wert ist der Grund, wenn nicht.

    Getrennt von :func:`starten`, damit sich der Grund auch dann nennen lässt,
    wenn niemand starten will — etwa auf der Info-Seite oder im Mitschnitt.
    """
    try:
        import sounddevice  # noqa: F401
    except Exception as exc:
        return False, f"sounddevice/PortAudio nicht nutzbar: {exc}"
    return True, ""


def laeuft() -> bool:
    return _strom is not None


def grund() -> str:
    """Warum der Rückfallweg benutzt wird, oder leer, wenn der Faden läuft.

    „Läuft nicht" **ohne** Begründung wäre die nutzloseste Auskunft überhaupt —
    sie kommt bei einer Meldung im Mitschnitt an und lässt genau die Frage
    offen, für die er gemacht ist. Deshalb ist auch „es hat nie jemand
    gestartet" eine ausdrückliche Antwort.
    """
    if _strom is not None:
        return ""
    return _grund or "nicht gestartet"


def zustand() -> dict:
    """Was tatsächlich anliegt — fürs Protokoll und den Mitschnitt."""
    m = _mischer
    return {
        "laeuft": laeuft(),
        "grund": grund(),
        "geraet": _geraet,
        "rate": _rate,
        "vorrat_frames": VORRAT,
        "vorrat_ms": round(1000.0 * VORRAT / _rate, 1) if _rate else 0.0,
        "unterlaeufe": m.unterlaeufe if m else 0,
        "stimmen": m.stimmen if m else 0,
        # Gerätewechsel im Betrieb (06.08.2026). ``standard`` leer heisst: auf
        # diesem Rechner nicht feststellbar, die Wache haelt dann still.
        "standardgeraet": _standard,
        "wechsel": _wechsel,
    }


def starten(rate: int = 48000) -> bool:
    """Audiofaden öffnen. ``False`` heißt: den alten Weg benutzen.

    Schlägt fehl, ohne zu werfen — ein Rennen ohne diesen Weg ist immer noch
    ein Rennen, ein Absturz beim Start nicht.
    """
    global _mischer, _strom, _faden, _grund, _rate, _geraet
    if _strom is not None:
        return True

    gut, warum = verfuegbar()
    if not gut:
        _grund = warum
        return False

    try:
        import sounddevice as sd

        _mischer = tonmischer.Mischer(kapazitaet=KAPAZITAET, vorrat=VORRAT,
                                      stueck=STUECK)

        def _rueckruf(aus, frames, zeit, status):
            # **Audiofaden.** Nur kopieren. Kein Rechnen, keine Sperre, kein
            # Warten, keine Ausnahme nach draussen — was hier haengt, hoert man.
            try:
                aus[:] = _mischer.abrufen(frames)
            except Exception:
                aus.fill(0.0)

        _strom = sd.OutputStream(samplerate=rate, channels=2, dtype="float32",
                                 blocksize=0, latency="low", callback=_rueckruf)
        _strom.start()
        _rate = int(_strom.samplerate)
        _geraet = _geraetename(sd, _strom)

        globals()["_standard"] = standardgeraet()

        _halt.clear()
        _faden = threading.Thread(target=_erzeugen_bis_halt, name="Tonerzeuger",
                                  daemon=True)
        _faden.start()
        _grund = ""
        return True
    except Exception as exc:
        _grund = f"Audiofaden liess sich nicht oeffnen: {exc}"
        _aufraeumen()
        return False


def standardgeraet() -> str:
    """Name des **aktuellen** Standard-Ausgabegeräts, oder leer.

    Der Kern des Gerätewechsels (gemeldet 06.08.2026): wird in Windows das
    Ausgabegerät umgestellt, zieht der Menüklang mit, der Rennklang nicht.
    Das liegt an den beiden Wegen, nicht an einem Fehler.

    * SDL öffnet das **Standardgerät** als solches. Windows verschiebt einen
      solchen Strom beim Umschalten von selbst mit — deshalb folgt der
      Menüklang.
    * PortAudio löst beim Öffnen auf einen **konkreten** Endpunkt auf und bleibt
      dort. Deshalb blieb der Rennklang zurück.

    Gefragt wird deshalb SDL, das ohnehin schon läuft: ``SDL_GetDefaultAudioInfo``
    nennt das Gerät, das *jetzt* das Standardgerät ist. Ändert sich der Name,
    wird der PortAudio-Strom neu geöffnet.

    Der Aufruf geht über ``ctypes`` an die SDL-Bibliothek, die pygame ohnehin
    geladen hat — pygame reicht die Funktion nicht durch. Klappt irgendetwas
    davon nicht, kommt ein leerer Name zurück und die Wache hält still: dann
    bleibt es beim heutigen Verhalten, aber nichts geht kaputt.
    """
    try:
        import ctypes
        sdl = _sdl_bibliothek()
        if sdl is None:
            return ""
        name = ctypes.c_char_p()
        spec = (ctypes.c_byte * 64)()
        # SDL_GetDefaultAudioInfo(char **name, SDL_AudioSpec *spec, int iscapture)
        if sdl.SDL_GetDefaultAudioInfo(ctypes.byref(name), ctypes.byref(spec), 0) != 0:
            return ""
        if not name.value:
            return ""
        aus = name.value.decode("utf-8", "replace")
        sdl.SDL_free(name)
        return aus
    except Exception:
        return ""


_sdl_cache: object | None = None


def _sdl_bibliothek():
    """Die SDL-Bibliothek, die pygame geladen hat — einmal gesucht, dann gemerkt."""
    global _sdl_cache
    if _sdl_cache is not None:
        return _sdl_cache or None
    _sdl_cache = False
    try:
        import ctypes
        import ctypes.util
        import os
        import sys

        import pygame
        ordner = os.path.dirname(os.path.abspath(pygame.__file__))
        kandidaten = []
        if sys.platform == "win32":
            kandidaten = [os.path.join(ordner, "SDL2.dll"), "SDL2.dll"]
        elif sys.platform == "darwin":
            kandidaten = [os.path.join(ordner, ".dylibs", "libSDL2-2.0.0.dylib"),
                          "libSDL2-2.0.0.dylib"]
        else:
            gefunden = ctypes.util.find_library("SDL2-2.0")
            kandidaten = [os.path.join(ordner, "libSDL2-2.0.so.0")]
            if gefunden:
                kandidaten.append(gefunden)
        for pfad in kandidaten:
            try:
                lib = ctypes.CDLL(pfad)
            except OSError:
                continue
            # Erst ab SDL 2.24 vorhanden. Fehlt sie, ist dieser Weg zu.
            if hasattr(lib, "SDL_GetDefaultAudioInfo"):
                _sdl_cache = lib
                return lib
    except Exception:
        pass
    return None


def neu_verbinden() -> bool:
    """Den Strom auf dem jetzigen Standardgerät neu öffnen.

    Der Mischer und **alle Stimmen bleiben stehen** — sie gehören ihm, nicht dem
    Gerät. Das Gerät wird also unter ihnen ausgetauscht, ohne dass das Rennen
    etwas davon mitbekommt: keine Stimme wird neu angelegt, keine Drehzahl geht
    verloren, nur der Ton setzt für den Moment des Umschaltens aus.
    """
    global _strom, _rate, _geraet, _standard, _wechsel
    if _strom is None:
        return False
    try:
        import sounddevice as sd
        alt = _strom
        _strom = None                     # der Rueckruf soll nicht mehr zaehlen
        try:
            alt.stop()
            alt.close()
        except Exception:
            pass
        # Ohne diesen Umlauf kennt PortAudio nur die Geraeteliste von frueher
        # und oeffnet wieder denselben Endpunkt.
        try:
            sd._terminate()
            sd._initialize()
        except Exception:
            pass

        m = _mischer

        def _rueckruf(aus, frames, zeit, status):
            try:
                aus[:] = m.abrufen(frames)
            except Exception:
                aus.fill(0.0)

        neu = sd.OutputStream(samplerate=48000, channels=2, dtype="float32",
                              blocksize=0, latency="low", callback=_rueckruf)
        neu.start()
        _strom = neu
        _rate = int(neu.samplerate)
        _geraet = _geraetename(sd, neu)
        _standard = standardgeraet()
        _wechsel += 1
        return True
    except Exception as exc:
        globals()["_grund"] = f"Neuverbinden fehlgeschlagen: {exc}"
        return False


def _geraetename(sd, strom) -> str:
    try:
        nummer = strom.device
        if isinstance(nummer, (list, tuple)):
            nummer = nummer[-1]
        return str(sd.query_devices(nummer)["name"])
    except Exception:
        return ""


def _erzeugen_bis_halt() -> None:
    """Erzeugerfaden: den Ring gefüllt halten.

    Bewusst kein enges Warten: ist der Vorrat voll, wird kurz geschlafen. Ohne
    das hielte dieser Faden den GIL und nähme dem Spiel Rechenzeit weg, für
    nichts.
    """
    naechste_wache = time.monotonic() + WACHE_SEKUNDEN
    while not _halt.is_set():
        m = _mischer
        if m is None:
            return
        try:
            if m.braucht_nachschub():
                if m.erzeugen() <= 0:
                    time.sleep(0.002)
            else:
                time.sleep(0.002)

            # Einmal je Sekunde nachsehen, ob das Standardgeraet gewechselt hat.
            # Hier und nicht in einem eigenen Faden: dieser laeuft ohnehin, und
            # ein zweiter Faden waere ein zweiter Ort zum Aufraeumen.
            jetzt = time.monotonic()
            if jetzt >= naechste_wache:
                naechste_wache = jetzt + WACHE_SEKUNDEN
                _wache()
        except Exception:
            # Der Erzeuger darf nie sterben — sonst verstummt das Rennen still.
            time.sleep(0.01)


def _wache() -> None:
    """Hat das Standardgerät gewechselt? Dann neu verbinden."""
    global _standard
    jetzt = standardgeraet()
    if not jetzt:
        return              # nicht feststellbar — dann lieber gar nichts tun
    if not _standard:
        _standard = jetzt
        return
    if jetzt != _standard:
        _standard = jetzt
        neu_verbinden()


def beenden() -> None:
    """Ausblenden, Faden anhalten, Gerät schliessen."""
    global _grund
    m = _mischer
    if m is not None:
        m.alle_beenden()
        # Den Ausblendungen noch einen Durchgang goennen, sonst bricht der Ton
        # mitten in der Welle ab — genau der Knacks vom 03.08.2026.
        ende = time.monotonic() + 0.15
        while time.monotonic() < ende and m.stimmen:
            time.sleep(0.005)
    _aufraeumen()
    _grund = ""


def _aufraeumen() -> None:
    global _mischer, _strom, _faden, _rate, _geraet
    _halt.set()
    if _faden is not None:
        _faden.join(1.0)
    _faden = None
    if _strom is not None:
        try:
            _strom.stop()
            _strom.close()
        except Exception:
            pass
    _strom = None
    _mischer = None
    _rate = 0
    _geraet = ""
    globals()["_standard"] = ""
    # Der Zaehler gehoert zur Sitzung, nicht zum Modul: sonst schleppt der
    # Mitschnitt Wechsel aus einem frueheren Lauf mit.
    globals()["_wechsel"] = 0


def stimme_anlegen(erzeuger, links: float = 0.0,
                   rechts: float = 0.0) -> tonmischer.Stimme | None:
    """Neue Quelle, oder ``None``, wenn dieser Weg gerade nicht läuft."""
    m = _mischer
    if m is None:
        return None
    return m.stimme_anlegen(erzeuger, links, rechts)


def unterlaeufe() -> int:
    m = _mischer
    return m.unterlaeufe if m else 0
