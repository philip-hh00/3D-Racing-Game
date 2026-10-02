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

from src.core import tonmischer, tonprozess

#: Wie lange ein Stück ist, das der Erzeuger am Stück rechnet (Abtastwerte).
#: 1024 sind bei 48 kHz gut 21 ms — klein genug, dass der Vorrat fein dosiert
#: werden kann, groß genug, dass die Synthese nicht in Kleinkram zerfällt.
STUECK = 1024

#: Vorrat im Ring in Millisekunden (Fund 01.10.2026: 85 ms reichten im Pulk
#: nicht, weil der Erzeuger vom Spielfaden um bis zu 40 ms aufgehalten wurde).
#: 100 ms sind sechs Bilder Reserve bei 60 Bildern je Sekunde — mehr Vorrat
#: schützt besser, lässt den Motor aber hinter dem Gaspedal herhinken.
VORRAT_MS = 100.0

#: Vorrat in Abtastwerten bei 48 kHz (Ausgangswert; nach dem Öffnen des Stroms
#: gilt :func:`vorrat_fuer` mit der tatsächlichen Rate).
VORRAT = 4800

#: Der Ring fasst mehr als den Vorrat, sonst hätte der Erzeuger nie Platz.
#: Auch grosse Geraetepuffer (Abrufe von 4000+ Frames) muessen noch hineinpassen.
KAPAZITAET = 16384

#: Wie lange der GIL dem laufenden Faden gehoert, bevor ein anderer drankommt.
#: Der Standard von 5 ms ist der Kern des Fundes vom 01.10.2026: der Erzeuger
#: gibt den GIL bei jeder numpy-Operation ab und musste ihn danach bis zu 5 ms
#: zurueckerbetteln, solange der Spielfaden reines Python rechnete (KI, Physik).
#: Ein Stueck, das 3 ms kostet, brauchte so 17 ms; gemessen mit 0,5 ms: 8 ms.
SCHALTINTERVALL = 0.0005

#: Wie oft nachgesehen wird, ob das Standardgerät gewechselt hat. Eine Sekunde
#: ist der Kompromiss: schnell genug, dass ein Umstecken sofort wirkt, selten
#: genug, dass die Abfrage nicht ins Gewicht fällt.
WACHE_SEKUNDEN = 1.0

#: Laeuft der Erzeuger in einem eigenen Prozess (``tonprozess``)? Die Tests
#: schalten es ab (Umgebungsvariable ``RACING_TON_PROZESS=0``), ein Spiel ohne
#: die Moeglichkeit faellt von selbst auf den Faden zurueck.
PROZESS = True

_mischer: tonmischer.Mischer | None = None
_prozess: tonprozess.Erzeugerprozess | None = None
_wache_faden: threading.Thread | None = None
_prozess_grund = ""
#: Laeuft der Erzeuger gerade im Prozess? Falsch im Fadenbetrieb und nach einem
#: Rueckfall, auch wenn ``_prozess`` noch den Speicher des Rings haelt.
_im_prozess = False
_rueckfall_schloss = threading.Lock()
#: So lange darf der Erzeugerprozess brauchen, bis er bereit meldet.
BEREIT_FRIST = 8.0
#: So lange darf der Herzschlag des bereiten Erzeugers stehen, bevor er als
#: haengend gilt.
HERZ_FRIST = 1.5
_strom = None
_faden: threading.Thread | None = None
_halt = threading.Event()
_grund = ""
_rate = 0
_geraet = ""
_api = ""
_latenz_ms = 0.0
#: Name des Standardgeräts beim letzten Nachsehen — der Fingerabdruck, an dem
#: ein Wechsel erkannt wird.
_standard = ""
_wechsel = 0
_alt_intervall: float | None = None


def vorrat_fuer(rate: int, ms: float = VORRAT_MS) -> int:
    """Vorrat in Abtastwerten für eine Geräterate, immer unter der Kapazität."""
    frames = int(round(int(rate) * float(ms) / 1000.0)) if rate else VORRAT
    return max(STUECK * 2, min(frames, KAPAZITAET - 2 * STUECK))


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
    p = _prozess if _im_prozess else None
    mess = p.speicher.mess if (p is not None and p.speicher is not None) else None
    if mess is not None:
        kopf = p.speicher.kopf
        zahl = float(mess[tonprozess.M_ZAHL])
        return {
            "laeuft": laeuft(),
            "grund": grund(),
            "geraet": _geraet,
            "rate": _rate,
            "vorrat_frames": int(kopf[tonprozess.K_VORRAT_IST]),
            "vorrat_ms": (round(1000.0 * int(kopf[tonprozess.K_VORRAT_IST]) / _rate, 1)
                          if _rate else 0.0),
            "unterlaeufe": m.unterlaeufe if m else 0,
            "geraete_unterlaeufe": m.geraete_unterlaeufe if m else 0,
            "abruf_frames": m.max_abruf if m else 0,
            "erzeugen_max_ms": round(float(mess[tonprozess.M_MAX]), 2),
            "erzeugen_mittel_ms": (round(float(mess[tonprozess.M_SUMME]) / zahl, 2)
                                   if zahl else 0.0),
            "erzeugen_spaet": int(mess[tonprozess.M_SPAET]),
            "api": _api,
            "latenz_ms": _latenz_ms,
            "stimmen": p.stimmen,
            "standardgeraet": _standard,
            "wechsel": _wechsel,
            "erzeuger": "prozess" if p.lebt() else "prozess (beendet)",
        }
    return {
        "erzeuger": ("faden (Rueckfall)" if _prozess is not None else "faden") if m else "",
        "laeuft": laeuft(),
        "grund": grund(),
        "geraet": _geraet,
        "rate": _rate,
        "vorrat_frames": m.vorrat if m else VORRAT,
        "vorrat_ms": round(1000.0 * m.vorrat / _rate, 1) if (_rate and m) else 0.0,
        "unterlaeufe": m.unterlaeufe if m else 0,
        "geraete_unterlaeufe": m.geraete_unterlaeufe if m else 0,
        "abruf_frames": m.max_abruf if m else 0,
        "erzeugen_max_ms": round(m.erzeugen_max_ms, 2) if m else 0.0,
        "erzeugen_mittel_ms": (round(m.erzeugen_summe_ms / m.erzeugen_zahl, 2)
                               if m and m.erzeugen_zahl else 0.0),
        "erzeugen_spaet": m.erzeugen_spaet if m else 0,
        "api": _api,
        "latenz_ms": _latenz_ms,
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

        _prozess_vorbereiten(rate)
        if _mischer is None:
            _mischer = tonmischer.Mischer(kapazitaet=KAPAZITAET, vorrat=VORRAT,
                                          stueck=STUECK, quellrate=rate,
                                          begrenzen=True)
        m = _mischer

        _strom = _strom_oeffnen(sd, rate, _rueckruf_bauen(m))
        _rate = int(_strom.samplerate)
        m.ausgaberate_setzen(_rate)
        m.vorrat = vorrat_fuer(_rate)
        _geraet = _geraetename(sd, _strom)
        _stromdaten(sd, _strom)
        globals()["_standard"] = standardgeraet()
        _halt.clear()
        if _prozess is not None:
            _geraeterate_melden()
            try:
                _prozess.werte_senden()
                _prozess.starten()
                globals()["_im_prozess"] = True
                from src.core import motorklang
                motorklang.beobachten(_werte_weitergeben)
            except Exception as exc:
                print(f"[Klang] Erzeugerprozess startet nicht ({exc}), Erzeugung im Faden")
                _prozess.stoppen()
        if _im_prozess:
            _faden = threading.Thread(target=_wachen_bis_halt, name="Tonwache",
                                      daemon=True)
        else:
            if _prozess is not None:
                _prozess.speicher.kopf[tonprozess.K_BEREIT] = 1   # Rueckruf gibt frei
            _intervall_setzen()
            _faden = threading.Thread(target=_erzeugen_bis_halt,
                                      name="Tonerzeuger", daemon=True)
        _faden.start()
        _grund = ""
        return True
    except Exception as exc:
        _grund = f"Audiofaden liess sich nicht oeffnen: {exc}"
        _aufraeumen()
        return False


def _prozess_vorbereiten(rate: int) -> None:
    """Erzeuger als eigener Prozess vorbereiten, wenn das moeglich und gewollt ist.

    Setzt ``_prozess`` und den Mischer des Audiofadens (ohne eigene Erzeugung,
    mit dem Ring im gemeinsamen Speicher). Misslingt etwas, bleibt beides
    ``None`` und :func:`starten` nimmt den Faden.
    """
    global _prozess, _mischer, _prozess_grund
    _prozess_grund = ""
    if not PROZESS:
        _prozess_grund = "abgeschaltet"
        return
    gut, warum = tonprozess.prozess_moeglich()
    if not gut:
        _prozess_grund = warum
        return
    try:
        p = tonprozess.Erzeugerprozess(KAPAZITAET, STUECK, rate, True, VORRAT)
    except Exception as exc:
        _prozess_grund = f"Speicher nicht anlegbar: {exc}"
        return
    _prozess = p
    sp = p.speicher
    _mischer = tonmischer.Mischer(kapazitaet=KAPAZITAET, vorrat=VORRAT, stueck=STUECK,
                                  quellrate=rate, begrenzen=True,
                                  ring=sp.ring, zaehler=sp.zaehler)


def _rueckruf_bauen(m):
    """Der Rueckruf fuer PortAudio. Er kopiert nur (siehe Modulkopf).

    Laeuft der Erzeuger in einem eigenen Prozess, gibt er bis zu dessen
    Bereitmarke Stille aus und zaehlt dabei keine Unterlaeufe: das Laden der
    Aufnahmen dauert einen Augenblick und ist kein Ausfall.
    """
    p = _prozess
    kopf = p.speicher.kopf if (p is not None and p.speicher is not None) else None

    def _rueckruf(aus, frames, zeit, status):
        # **Audiofaden.** Nur kopieren. Kein Rechnen, keine Sperre, kein
        # Warten, keine Ausnahme nach draussen — was hier haengt, hoert man.
        try:
            if kopf is not None and not kopf[tonprozess.K_BEREIT]:
                aus.fill(0.0)
                if frames > m.max_abruf:
                    m.max_abruf = frames
                return
            m.status_melden(status)
            aus[:] = m.abrufen(frames)
        except Exception:
            aus.fill(0.0)
    return _rueckruf


def _werte_weitergeben() -> None:
    """Aenderung an den Klangwerten (Labor) an den Erzeugerprozess schicken."""
    p = _prozess
    if _im_prozess and p is not None:
        p.werte_senden()


def _geraeterate_melden() -> None:
    """Geraeterate und Vorrat an den Erzeugerprozess weitergeben."""
    p = _prozess
    m = _mischer
    if p is None or p.speicher is None or m is None:
        return
    p.speicher.kopf[tonprozess.K_AUSGABERATE] = int(_rate)
    p.speicher.kopf[tonprozess.K_VORRAT] = int(m.vorrat)


def motorstimme_anlegen(erzeuger, motor: str, tonhoehe: float, faerbung: float,
                        links: float = 0.0, rechts: float = 0.0):
    """Motorstimme anlegen, im Erzeugerprozess oder im Faden, je nach Betrieb.

    Gibt eine Stimme mit ``einstellen`` und ``beenden`` zurueck (im Prozess
    zusaetzlich ``drehzahl_setzen``), oder ``None``, wenn der Weg nicht laeuft.
    *erzeuger* wird nur im Fadenbetrieb gebraucht.
    """
    with _rueckfall_schloss:
        p = _prozess
        if _im_prozess and p is not None and p.speicher is not None:
            return p.stimme_anlegen(motor, tonhoehe, faerbung, links, rechts, erzeuger)
        return stimme_anlegen(erzeuger, links, rechts)


def raten_kandidaten(sd, wunsch: int = 48000) -> list[int]:
    """In dieser Reihenfolge wird versucht, den Strom zu öffnen.

    Erst die Rate der Aufnahmen (48 kHz) — dann ist keine Umrechnung nötig.
    Danach die **Standardrate des Geräts**, wie PortAudio sie meldet: im
    geteilten Modus (WASAPI, CoreAudio, Bluetooth-Headsets mit 16/32 kHz,
    44,1-kHz-Karten) nimmt der Treiber oft nur diese an. Zuletzt 44,1 kHz als
    übliche Ersatzrate. Der Mischer rechnet dann selbst um (Erzeugerfaden).
    """
    liste = [int(wunsch)]
    try:
        info = sd.query_devices(kind="output")
        nativ = int(round(float(info["default_samplerate"])))
        if nativ > 0 and nativ not in liste:
            liste.append(nativ)
    except Exception:
        pass
    if 44100 not in liste:
        liste.append(44100)
    return liste


def _strom_oeffnen(sd, wunsch: int, rueckruf):
    """Strom öffnen und starten; bei abgelehnter Rate die nächste versuchen.

    Unter Windows (WASAPI geteilt) lehnt PortAudio eine Rate ab, die vom
    Mischformat des Geräts abweicht, es sei denn ``auto_convert`` ist gesetzt.
    Das wird zuerst versucht, danach ohne. Wirft, wenn nichts geht.
    """
    letzter = None
    extras = [None]
    try:
        import sys
        if sys.platform == "win32" and hasattr(sd, "WasapiSettings"):
            extras = [sd.WasapiSettings(auto_convert=True), None]
    except Exception:
        extras = [None]
    for rate in raten_kandidaten(sd, wunsch):
        for extra in extras:
            try:
                kw = {} if extra is None else {"extra_settings": extra}
                strom = None
                strom = sd.OutputStream(samplerate=rate, channels=2,
                                        dtype="float32", blocksize=0,
                                        latency="low", callback=rueckruf, **kw)
                strom.start()
                return strom
            except Exception as exc:
                letzter = exc
                # Gebaut, aber nicht startbar: freigeben, bevor der naechste
                # Versuch das Geraet erneut oeffnet.
                if strom is not None:
                    try:
                        strom.close()
                    except Exception:
                        pass
    raise letzter if letzter else RuntimeError("kein Ausgabegeraet")


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

        neu = _strom_oeffnen(sd, m.quellrate, _rueckruf_bauen(m))
        _strom = neu
        _rate = int(neu.samplerate)
        m.ausgaberate_setzen(_rate)
        m.vorrat = vorrat_fuer(_rate)
        _geraeterate_melden()
        _stromdaten(sd, neu)
        _geraet = _geraetename(sd, neu)
        _standard = standardgeraet()
        _wechsel += 1
        return True
    except Exception as exc:
        globals()["_grund"] = f"Neuverbinden fehlgeschlagen: {exc}"
        return False


def _stromdaten(sd, strom) -> None:
    """Host-API und Latenz des geöffneten Stroms merken (fürs Protokoll)."""
    global _api, _latenz_ms
    try:
        nummer = strom.device
        if isinstance(nummer, (list, tuple)):
            nummer = nummer[-1]
        _api = str(sd.query_hostapis(sd.query_devices(nummer)["hostapi"])["name"])
    except Exception:
        _api = ""
    try:
        lat = strom.latency
        if isinstance(lat, (list, tuple)):
            lat = lat[-1]
        _latenz_ms = round(1000.0 * float(lat), 1)
    except Exception:
        _latenz_ms = 0.0


def _intervall_setzen() -> None:
    """GIL-Wechselintervall verkürzen (siehe :data:`SCHALTINTERVALL`)."""
    global _alt_intervall
    import sys
    try:
        if _alt_intervall is None:
            _alt_intervall = sys.getswitchinterval()
        sys.setswitchinterval(SCHALTINTERVALL)
    except Exception:
        pass


def _intervall_zurueck() -> None:
    global _alt_intervall
    import sys
    if _alt_intervall is not None:
        try:
            sys.setswitchinterval(_alt_intervall)
        except Exception:
            pass
        _alt_intervall = None


def _faden_vorrang() -> None:
    """Erzeugerfaden unter Windows etwas über normal stellen (Best Effort)."""
    import sys
    if sys.platform != "win32":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.SetThreadPriority(k.GetCurrentThread(), 1)   # ABOVE_NORMAL
    except Exception:
        pass


def zaehler_zuruecksetzen() -> None:
    """Messwerte für ein neues Rennen auf null (Vorrat bleibt)."""
    m = _mischer
    if m is None:
        return
    if _im_prozess and _prozess is not None:
        _prozess.zuruecksetzen()
    m.unterlaeufe = 0
    m.geraete_unterlaeufe = 0
    m.erzeugen_max_ms = 0.0
    m.erzeugen_summe_ms = 0.0
    m.erzeugen_zahl = 0
    m.erzeugen_spaet = 0


def protokollzeile() -> str:
    """Eine Zeile mit Gerät, Strom und Zählern — einmal je Rennen ins Log."""
    z = zustand()
    if not z["laeuft"]:
        return f"[Klang] Audiofaden aus ({z['grund']})"
    return (f"[Klang] {z['geraet']} | {z['api']} | {z['rate']} Hz | "
            f"Latenz {z['latenz_ms']} ms | Vorrat {z['vorrat_ms']} ms | "
            f"Abruf max {z['abruf_frames']} | Stimmen {z['stimmen']} | "
            f"Erzeuger {z.get('erzeuger', '')} | "
            f"Unterlaeufe Ring {z['unterlaeufe']} / Geraet {z['geraete_unterlaeufe']} | "
            f"Erzeugen Mittel {z['erzeugen_mittel_ms']} ms, Max {z['erzeugen_max_ms']} ms, "
            f"zu spaet {z['erzeugen_spaet']}")


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
    _faden_vorrang()
    while not _halt.is_set():
        m = _mischer
        if m is None:
            return
        try:
            m.vorrat_nachfuehren()
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


def _wachen_bis_halt() -> None:
    """Wache fuer den Prozessbetrieb.

    Alle Viertelsekunde: lebt der Erzeuger, ist er bereit, schlaegt sein Herz?
    Einmal je :data:`WACHE_SEKUNDEN`: hat das Standardgeraet gewechselt?
    """
    takt = min(0.25, WACHE_SEKUNDEN)
    naechste_geraetewache = time.monotonic() + WACHE_SEKUNDEN
    while not _halt.wait(takt):
        try:
            jetzt = time.monotonic()
            if jetzt >= naechste_geraetewache:
                naechste_geraetewache = jetzt + WACHE_SEKUNDEN
                _wache()
            p = _prozess
            if p is None or _halt.is_set() or p.speicher is None:
                continue
            if not p.lebt():
                _auf_faden_zurueck("Erzeugerprozess beendet")
                return
            if not p.bereit:
                if jetzt - p.gestartet > BEREIT_FRIST:
                    _auf_faden_zurueck("Erzeugerprozess wird nicht bereit")
                    return
                continue
            herz = int(p.speicher.kopf[tonprozess.K_HERZ])
            alt, seit = p.letzter_herzschlag
            if herz != alt:
                p.letzter_herzschlag = (herz, jetzt)
            elif jetzt - seit > HERZ_FRIST:
                _auf_faden_zurueck("Erzeugerprozess haengt")
                return
        except Exception:
            pass


def _auf_faden_zurueck(warum: str) -> None:
    """Der Erzeugerprozess ist ausgefallen: im Faden weiterrechnen, ohne Stille.

    Der Ring (gemeinsamer Speicher) und der Mischer des Audiofadens bleiben, es
    kommt nur ein Erzeugerfaden dazu, und die Stimmen werden dort neu
    angemeldet (mit Lautstaerke, ohne ihre Phase: sie fangen an einer eigenen
    Stelle an). Wird einmal gemeldet.
    """
    global _im_prozess, _faden
    with _rueckfall_schloss:
        p = _prozess
        m = _mischer
        if not _im_prozess or p is None or m is None or p.speicher is None:
            return
        _im_prozess = False             # neue Stimmen gehen ab jetzt in den Faden
        print(f"[Klang] {warum} - Rueckfall auf den Erzeugerfaden")
        for f in list(p.fernstimmen):
            f.uebernehmen(m)
    # Ausserhalb der Sperre: das Beenden kann bis zu einer Sekunde dauern und
    # soll den Spielfaden (motorstimme_anlegen) nicht aufhalten. Erst wenn der
    # Erzeuger wirklich weg ist, darf der Faden schreiben - sonst gaebe es zwei
    # Schreiber im Ring.
    p.stoppen()
    try:
        from src.core import motorklang
        motorklang.nicht_mehr_beobachten(_werte_weitergeben)
    except Exception:
        pass
    p.speicher.kopf[tonprozess.K_BEREIT] = 1      # der Rueckruf gibt wieder frei
    _intervall_setzen()
    _faden = threading.Thread(target=_erzeugen_bis_halt, name="Tonerzeuger",
                              daemon=True)
    _faden.start()


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
    p = _prozess
    if _im_prozess and p is not None and p.speicher is not None:
        p.alle_beenden()
        ende = time.monotonic() + 0.15
        while time.monotonic() < ende and p.stimmen and p.lebt():
            time.sleep(0.005)
    elif m is not None:
        m.alle_beenden()
        # Den Ausblendungen noch einen Durchgang goennen, sonst bricht der Ton
        # mitten in der Welle ab — genau der Knacks vom 03.08.2026.
        ende = time.monotonic() + 0.15
        while time.monotonic() < ende and m.stimmen:
            time.sleep(0.005)
    _aufraeumen()
    _grund = ""


def _aufraeumen() -> None:
    global _mischer, _strom, _faden, _rate, _geraet, _prozess, _im_prozess
    _halt.set()
    try:
        from src.core import motorklang
        motorklang.nicht_mehr_beobachten(_werte_weitergeben)
    except Exception:
        pass
    _im_prozess = False
    if _faden is not None:
        _faden.join(1.0)
    _faden = None
    _intervall_zurueck()
    if _strom is not None:
        try:
            _strom.stop()
            _strom.close()
        except Exception:
            pass
    _strom = None
    _mischer = None
    if _prozess is not None:
        p, _prozess = _prozess, None
        try:
            p.beenden()
        except Exception:
            pass
    _rate = 0
    _geraet = ""
    globals()["_api"] = ""
    globals()["_latenz_ms"] = 0.0
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
