"""Schutz vor Schummeln auf dem Relay (Plan 1.1.0, Abschnitt „Online-Schutz").

Vier Teile, alle reine Logik ohne Netz — ``server.py`` ruft sie nur auf:

1. **Dateipruefsumme** (:func:`dateien_pruefen`). Beim ``HOST``/``JOIN`` schickt
   der Client ``game`` (``"2d"``/``"3d"``) und ``files`` (SHA-256 ueber die
   spielrelevanten Dateien, siehe ``src/core/integritaet.py`` des Spiels). Der
   Relay laesst nur Spieler mit der Summe herein, die zu ``(game, version)`` in
   ``pruefsummen.json`` steht. Die Datei entsteht beim Release
   (``tools/pruefsummen.py``), nicht von Hand.
2. **Plausibilitaet** (:class:`LobbySchutz`). Der Positionsstrom (UDP) wird auf
   Spruenge und Tempo geprueft, die Ergebniszeilen (``RACE_RESULT``) auf
   unmoegliche Zeiten, fremde Zeilen und Widersprueche zum beobachteten
   Rennverlauf. Wer auffaellt, dessen Zeilen gehen als ``invalid`` hinaus.
3. **Rauswurf** (:meth:`LobbySchutz.sperren`): wer vom Host entfernt wurde, kommt
   in diese Lobby nicht wieder hinein (Kennung, Adresse, zuletzt der Name).
4. **Meldungen** (:class:`MeldungsSpeicher`): Spieler melden Spieler, der Relay
   legt die Meldung samt Verdachtsmarken ab; ``tools/meldungen_verwalten.py``
   liest sie.

**Wie vorsichtig.** Eine falsche Beschuldigung ist schlimmer als ein
durchgerutschter Schummler. Alle Grenzen liegen deshalb weit ueber dem, was die
Physik des Spiels hergibt, und die Wegpruefung rechnet mit der Ankunftszeit am
Relay samt Guthaben (siehe :meth:`LobbySchutz._strom`): verzoegerte, geballte
oder verlorene Pakete aendern die Lage der Autos nicht, nur wann sie ankommen,
und das Guthaben waechst mit der Zeit. Was das nicht abfaengt (ein Spieler, der
langsam faehrt und dann einmal ein Stueck weit springt, das kleiner ist als das
Guthaben), bleibt ungestraft — das ist Absicht.

Nur Standardbibliothek.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import secrets
import struct
import time
from collections import deque
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("schutz")

# ══ 1. Dateipruefsumme ═══════════════════════════════════════════════════════

SPIELE = ("2d", "3d")
CODE_DATEIEN = "MODIFIED_FILES"
CODE_SPIEL = "WRONG_GAME"
CODE_GESPERRT = "KICKED"

_SUMME = re.compile(r"^[0-9a-f]{64}$")

#: Vorgabe: genau die Summe aus ``pruefsummen.json`` zaehlt. ``log``: nur
#: protokollieren, alle hereinlassen (Entwicklungsinstanz). ``off``: gar nicht
#: pruefen. Gelesen wird bei **jedem** Aufruf aus der Umgebung
#: (``RACE_FILES_CHECK``), damit Tests und Betreiber nicht neu starten muessen.
MODUS_DURCHSETZEN = "enforce"
MODUS_PROTOKOLL = "log"
MODUS_AUS = "off"

PRUEFSUMMEN_DATEI = os.environ.get(
    "RACE_PRUEFSUMMEN_DATEI",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "pruefsummen.json"))

#: Was der Spieler zu einer Absage zu lesen bekommt (Fallback; der Client
#: uebersetzt nach ``code``).
TEXT = {
    CODE_DATEIEN: "Die Spieldateien sind verändert oder veraltet — online geht es "
                  "nur mit dem unveränderten Spiel.",
    CODE_SPIEL:   "Diese Lobby gehört zum anderen Spiel (2D/3D).",
    CODE_GESPERRT: "Du wurdest aus dieser Lobby entfernt.",
}


def dateien_modus() -> str:
    roh = os.environ.get("RACE_FILES_CHECK", MODUS_DURCHSETZEN).strip().lower()
    if roh in ("off", "aus", "0", "no", "false"):
        return MODUS_AUS
    if roh in ("log", "warn", "protokoll"):
        return MODUS_PROTOKOLL
    return MODUS_DURCHSETZEN


_tabelle_cache: dict = {"pfad": None, "stand": None, "daten": {}}


def pruefsummen_laden() -> dict:
    """``pruefsummen.json`` lesen, neu nur wenn die Datei sich aendert."""
    pfad = os.environ.get("RACE_PRUEFSUMMEN_DATEI", PRUEFSUMMEN_DATEI)
    try:
        st = os.stat(pfad)
        stand = (st.st_mtime_ns, st.st_size)
    except OSError:
        _tabelle_cache.update(pfad=pfad, stand=None, daten={})
        return {}
    c = _tabelle_cache
    if c["pfad"] == pfad and c["stand"] == stand:
        return c["daten"]
    try:
        with open(pfad, encoding="utf-8") as f:
            daten = json.load(f)
        if not isinstance(daten, dict) or not isinstance(daten.get("spiele"), dict):
            raise ValueError("kein Feld 'spiele'")
    except Exception as exc:
        log.error(f"pruefsummen.json unlesbar: {exc}")
        daten = {}
    c.update(pfad=pfad, stand=stand, daten=daten)
    return daten


def eintrag_fuer(spiel: str, version: str) -> Optional[dict]:
    """Der Eintrag zu ``(Spiel, Version)`` oder ``None``."""
    e = pruefsummen_laden().get("spiele", {}).get(spiel, {})
    e = e.get(version) if isinstance(e, dict) else None
    return e if isinstance(e, dict) else None


def dateien_pruefen(msg: dict, version: str, ip: str = "") -> Optional[dict]:
    """Ob die Dateien des Clients zum Release passen.

    ``None``: herein. Sonst die fertige ``JOIN_FAIL``-Nachricht.
    """
    modus = dateien_modus()
    if modus == MODUS_AUS:
        return None
    spiel = msg.get("game")
    summe = msg.get("files")
    grund = ""
    if not (isinstance(spiel, str) and spiel in SPIELE):
        grund = f"kein gültiges Spiel ({str(spiel)[:12]!r})"
    elif not (isinstance(summe, str) and _SUMME.match(summe)):
        grund = "keine Prüfsumme"
    else:
        e = eintrag_fuer(spiel, version)
        if e is None:
            grund = (f"keine bekannte Summe für {spiel} {version[:16]!r} — "
                     f"pruefsummen.json nicht aktuell?")
        elif summe not in [str(s) for s in e.get("summen", [])]:
            grund = f"Summe {summe[:12]}… passt nicht zu {spiel} {version[:16]}"
    if not grund:
        return None
    log.warning(f"Dateipruefung ({modus}): {ip} — {grund}")
    if modus == MODUS_PROTOKOLL:
        return None
    return {"type": "JOIN_FAIL", "code": CODE_DATEIEN, "reason": TEXT[CODE_DATEIEN]}


def cid_von(msg: dict) -> str:
    """Die Kennung, die der Client mitschickt (zufaellig, vom Spieler erzeugt)."""
    cid = "".join(z for z in str(msg.get("cid", ""))[:32] if z.isalnum())
    return cid if len(cid) >= 8 else ""


# ══ 2. Plausibilitaet ════════════════════════════════════════════════════════

#: Fahrzeugnummer im Paket -> Name. Muss zu ``VEHICLE_TYPES`` in
#: ``src/net/protocol.py`` passen (nur anhaengen, nie umordnen); die Tests der
#: Spiele vergleichen beides.
VEHICLE_TYPES = [
    "rookie", "supercar", "drifter", "limousine", "electric",
    "rookie_2", "rookie_3",
    "supercar_2", "supercar_3",
    "drifter_2", "drifter_3",
    "limousine_2", "limousine_3",
    "electric_2", "electric_3",
]

_STATE_KOPF = struct.Struct("!B 6s B B d")
_STATE_FAHRZEUG = struct.Struct("!BB ffffff B H")
UDP_STATE = 0x01

#: Hoechstgeschwindigkeit in px/s, wenn die Tabelle das Fahrzeug nicht kennt.
VMAX_VORGABE = 1100.0
#: Wegstrecke: so viel Mal die Hoechstgeschwindigkeit ist erlaubt (Stoesse,
#: Rutschen, Rundung).
TOLERANZ_WEG = 1.35
#: Obergrenze des angesparten Guthabens, in Sekunden Fahrt bei Hoechsttempo. Das
#: ist die Luft fuer geballt eintreffende Pakete; waehrend einer Funkstille waechst
#: das Guthaben ohne Grenze (siehe :meth:`LobbySchutz._strom`).
PUFFER_S = 3.0
#: Pixel ueber dem Guthaben: ab hier ein Verstoss (1 Punkt) ...
UEBERSCHUSS_LEICHT = 100.0
#: ... und ab hier ein Sprung (3 Punkte, also sofort verdaechtig).
UEBERSCHUSS_HART = 600.0
#: Gemeldetes Tempo: Faktor auf die Hoechstgeschwindigkeit, so lange am Stueck.
TEMPO_FAKTOR = 1.6
TEMPO_DAUER_S = 2.0
#: Ab so vielen Punkten ist ein Spieler fuer dieses Rennen verdaechtig.
SCHWELLE = 3.0

#: Rundenzeit: Anteil der rechnerischen Mindestzeit (Streckenlaenge der
#: Mittellinie / hoechste Geschwindigkeit), unter dem keine Runde moeglich ist.
#: 0,7 laesst der Ideallinie reichlich Luft gegenueber der Mittellinie.
MIN_RUNDE_ANTEIL = 0.7
#: Ohne bekannte Strecke: kuerzeste Runde ueberhaupt, in Sekunden.
MIN_RUNDE_ABSOLUT = 2.0
#: Spielraum beim Vergleich mit dem beobachteten Rennverlauf (Laufzeit,
#: Zeitversatz des Starts): Sekunden plus Anteil der Zeit.
BEOB_SPIEL_S = 3.0
BEOB_SPIEL_ANTEIL = 0.03

MAX_ZEILEN = 8
_ZEILE_TEXT = 40


def _endlich(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def strecke_laenge(daten) -> Optional[float]:
    """Laenge der Mittellinie einer Streckendatei in px, oder ``None``.

    *daten*: Bytes/Text einer Streckendatei oder schon das Woerterbuch.
    """
    try:
        if isinstance(daten, (bytes, bytearray)):
            daten = json.loads(bytes(daten).decode("utf-8"))
        elif isinstance(daten, str):
            daten = json.loads(daten)
        pts = daten["centerline"]
        if not isinstance(pts, list) or not (8 <= len(pts) <= 20000):
            return None
        xy = [(float(p["x"]), float(p["y"])) for p in pts]
    except Exception:
        return None
    gesamt = 0.0
    for i, (x, y) in enumerate(xy):
        nx, ny = xy[(i + 1) % len(xy)]
        gesamt += math.hypot(nx - x, ny - y)
    if not math.isfinite(gesamt) or gesamt < 1500.0:
        return None
    return gesamt


class _Strom:
    """Ein Fahrzeug, wie es am Relay ankommt."""
    __slots__ = ("x", "y", "t", "guthaben", "send", "uebersprungen", "ueber_seit")

    def __init__(self, x, y, t, guthaben, send):
        self.x, self.y, self.t = x, y, t
        self.guthaben = guthaben
        self.send = send
        self.uebersprungen = 0
        self.ueber_seit: Optional[float] = None


class _Verlauf:
    """Was der Relay vom Rundenstand eines Spielers gesehen hat."""
    __slots__ = ("lap", "uebergaenge", "unsicher")

    def __init__(self):
        self.lap: Optional[int] = None
        #: Runde -> Rennzeit, zu der das Paket mit dieser Rundennummer zuerst kam
        self.uebergaenge: Dict[int, float] = {}
        self.unsicher = False


class LobbySchutz:
    """Alles, was der Schutz je Lobby weiss."""

    def __init__(self, lobby_id: str, spiel: str = "", version: str = "") -> None:
        self.lobby_id = lobby_id
        self.spiel = spiel if spiel in SPIELE else ""
        self.version = version
        # Rauswurf
        self._gesperrt_cid: set = set()
        self._gesperrt_ip: set = set()
        self._gesperrt_name: set = set()
        # Wer war dabei: Name -> Angaben (fuer Meldungen, auch nach dem Gehen)
        self.teilnehmer: "Dict[str, dict]" = {}
        self.namen: Dict[int, str] = {}
        #: Verdachtsmarken je Name ueber alle Rennen dieser Lobby
        self.marken: "Dict[str, List[str]]" = {}
        self.meldungen_von: "Dict[str, set]" = {}
        self._rennen_leeren()

    # -- Rennen ---------------------------------------------------------------
    def _rennen_leeren(self) -> None:
        self.stroeme: "Dict[Tuple[int, int], _Strom]" = {}
        self.verlauf: "Dict[int, _Verlauf]" = {}
        self.punkte: Dict[int, float] = {}
        self.gruende: "Dict[int, List[str]]" = {}
        self.go_ts: Optional[float] = None
        self._pausen: "List[List[float]]" = []
        self._pause_seit: Optional[float] = None
        self.laps: Optional[int] = None
        self.strecken_laenge: Optional[float] = None
        self.min_runde: Optional[float] = None
        self.zeilen_slots: set = set()

    def rennen_neu(self, settings: dict, karte: bytes = b"", kartenname: str = "") -> None:
        """Beim Start eines Rennens (``_do_start``): alles Rennbezogene zurueck."""
        self._rennen_leeren()
        laps = settings.get("laps") if isinstance(settings, dict) else None
        if isinstance(laps, int) and not isinstance(laps, bool) and 1 <= laps <= 99:
            self.laps = laps
        self.strecken_laenge = strecke_laenge(karte) if karte else None
        if self.strecken_laenge is None and kartenname:
            e = eintrag_fuer(self.spiel, self.version) or {}
            stamm = os.path.basename(str(kartenname)).lower()
            if stamm.endswith(".json"):
                stamm = stamm[:-5]
            laenge = (e.get("strecken") or {}).get(stamm) if isinstance(e.get("strecken"), dict) else None
            if _endlich(laenge) and laenge > 0:
                self.strecken_laenge = float(laenge)
        if self.strecken_laenge:
            self.min_runde = max(MIN_RUNDE_ABSOLUT,
                                 MIN_RUNDE_ANTEIL * self.strecken_laenge / self._vmax_alle())

    def go(self, jetzt: float, countdown_ms: float) -> None:
        """``RACE_GO`` wurde gesendet: die Rennuhr beginnt nach dem Countdown."""
        neu = jetzt + max(0.0, float(countdown_ms)) / 1000.0
        # Ein erneutes RACE_GO (ein Spieler ging waehrend des Ladens) verschiebt
        # den Start nur, solange er noch nicht stattgefunden hat.
        if self.go_ts is None or jetzt < self.go_ts:
            self.go_ts = neu

    def pause(self, jetzt: float, an: bool) -> None:
        if an and self._pause_seit is None:
            self._pause_seit = jetzt
        elif not an and self._pause_seit is not None:
            self._pausen.append([self._pause_seit, jetzt])
            self._pause_seit = None

    def rennzeit(self, jetzt: float) -> Optional[float]:
        """Sekunden Rennuhr zum Zeitpunkt *jetzt* (ohne Pausen), oder ``None``."""
        if self.go_ts is None or jetzt < self.go_ts:
            return None if self.go_ts is None else 0.0
        pausiert = 0.0
        for a, b in self._pausen + ([[self._pause_seit, jetzt]] if self._pause_seit is not None else []):
            lo, hi = max(a, self.go_ts), min(b, jetzt)
            if hi > lo:
                pausiert += hi - lo
        return max(0.0, jetzt - self.go_ts - pausiert)

    # -- Tabellen ----------------------------------------------------------------
    def _fahrzeuge(self) -> dict:
        e = eintrag_fuer(self.spiel, self.version) or {}
        f = e.get("fahrzeuge")
        return f if isinstance(f, dict) else {}

    def _vmax_alle(self) -> float:
        werte = [float(v) for v in self._fahrzeuge().values() if _endlich(v) and v > 0]
        return max(werte) if werte else VMAX_VORGABE

    def _vmax(self, idx: int) -> float:
        name = VEHICLE_TYPES[idx] if 0 <= idx < len(VEHICLE_TYPES) else ""
        v = self._fahrzeuge().get(name)
        return float(v) if _endlich(v) and v > 0 else self._vmax_alle()

    # -- Verdacht --------------------------------------------------------------
    def _verdacht(self, slot: int, code: str, punkte: float) -> None:
        self.punkte[slot] = self.punkte.get(slot, 0.0) + punkte
        liste = self.gruende.setdefault(slot, [])
        if code not in liste:
            liste.append(code)
        name = self.namen.get(slot, f"Slot {slot}")
        log.warning(f"Schutz: Lobby {self.lobby_id} '{name}' (Slot {slot}): {code} "
                    f"(+{punkte:g} = {self.punkte[slot]:g})")
        if self.punkte[slot] >= SCHWELLE:
            m = self.marken.setdefault(name, [])
            if code not in m:
                m.append(code)

    def verdaechtig(self, slot: int) -> bool:
        return self.punkte.get(slot, 0.0) >= SCHWELLE

    def marken_von(self, name: str) -> List[str]:
        return list(self.marken.get(name, []))

    # -- UDP-Strom -------------------------------------------------------------
    def paket(self, slot: int, daten: bytes, jetzt: float) -> None:
        """Ein ``UDP_STATE`` auswerten. Wirft nie."""
        try:
            self._paket(slot, daten, jetzt)
        except Exception as exc:     # der Schutz darf den Relay nie behindern
            log.error(f"Schutz: Paket nicht auswertbar: {exc}")

    def _paket(self, slot: int, daten: bytes, jetzt: float) -> None:
        if len(daten) < _STATE_KOPF.size or daten[0] != UDP_STATE:
            return
        _, _, _, anzahl, send = _STATE_KOPF.unpack(daten[:_STATE_KOPF.size])
        if not math.isfinite(send):
            self._verdacht(slot, "PAKET_ZAHL", 3.0)
            return
        pos = _STATE_KOPF.size
        for i in range(min(anzahl, 8)):
            if pos + _STATE_FAHRZEUG.size > len(daten):
                break
            vid, vtyp, x, y, _w, vx, vy, _om, lap, _wp = _STATE_FAHRZEUG.unpack(
                daten[pos:pos + _STATE_FAHRZEUG.size])
            pos += _STATE_FAHRZEUG.size
            if not all(math.isfinite(v) for v in (x, y, vx, vy)) or max(abs(x), abs(y)) > 1e7:
                self._verdacht(slot, "PAKET_ZAHL", 3.0)
                continue
            self._strom(slot, vid, vtyp, x, y, vx, vy, send, jetzt)
            if i == 0 and lap > 0:
                self._runde(slot, lap, jetzt)

    def _strom(self, slot, vid, vtyp, x, y, vx, vy, send, jetzt) -> None:
        """Weg und Tempo eines Fahrzeugs gegen das Guthaben rechnen.

        Das Fahrzeug darf je Sekunde Ankunftszeit ``vmax * TOLERANZ_WEG`` Pixel
        zuruecklegen. Diese erlaubte Strecke sammelt sich als **Guthaben**: jedes
        Paket bringt ``erlaubt * Zeit seit dem letzten`` dazu und kostet die
        zurueckgelegte Strecke. Daraus folgt:

        * Geballte Pakete (Funkloch, dann alles auf einmal): die Pakete tragen
          die wahre, stetige Lage, ihre Wege summieren sich zur Strecke der
          Pause — und die Pause hat das Guthaben gefuellt.
        * Verlorene Pakete: das naechste traegt die Lage nach der Luecke, die
          Luecke hat das Guthaben gefuellt (ohne Obergrenze bis zum Verbrauch).
        * Ein Spieler, der erst steht und dann springt, kann hoechstens
          ``PUFFER_S`` Sekunden Fahrt vorweg ansparen, danach ist Schluss.
        """
        vmax = self._vmax(vtyp)
        erlaubt = vmax * TOLERANZ_WEG
        s = self.stroeme.get((slot, vid))
        if s is None:
            self.stroeme[(slot, vid)] = _Strom(x, y, jetzt, erlaubt * PUFFER_S, send)
            return
        # Reihenfolge am Absender: ein spaeter eintreffendes aelteres Paket zaehlt
        # nicht. Wer die Sendezeit rueckwaerts laufen laesst, um unbeobachtet zu
        # bleiben, wird nach 20 Paketen trotzdem gelesen.
        if send <= s.send and s.uebersprungen < 20:
            s.uebersprungen += 1
            return
        s.uebersprungen = 0
        s.send = send
        dt = max(0.0, jetzt - s.t)
        weg = math.hypot(x - s.x, y - s.y)
        s.x, s.y, s.t = x, y, jetzt
        s.guthaben += erlaubt * dt - weg
        if s.guthaben < -UEBERSCHUSS_LEICHT:
            # Mehr Weg, als das Guthaben und die Luft hergeben. Kleine Fehlbetraege
            # bleiben stehen und summieren sich bei dauerhaft zu hohem Tempo
            # (jedes Paket ein bisschen zu weit), ein Sprung zaehlt sofort.
            ueber = -s.guthaben
            s.guthaben = 0.0
            if ueber > UEBERSCHUSS_HART:
                self._verdacht(slot, "SPRUNG", 3.0)
            else:
                self._verdacht(slot, "TEMPO_WEG", 1.0)
        elif s.guthaben > erlaubt * PUFFER_S:
            s.guthaben = erlaubt * PUFFER_S
        # Gemeldetes Tempo, so lange am Stueck. Der Wert kommt vom Client und
        # laesst sich faelschen; die Wegpruefung oben nicht.
        if math.hypot(vx, vy) > vmax * TEMPO_FAKTOR:
            if s.ueber_seit is None:
                s.ueber_seit = jetzt
            elif jetzt - s.ueber_seit >= TEMPO_DAUER_S:
                s.ueber_seit = jetzt
                self._verdacht(slot, "TEMPO_MELDUNG", 1.5)
        else:
            s.ueber_seit = None

    def _runde(self, slot: int, lap: int, jetzt: float) -> None:
        v = self.verlauf.setdefault(slot, _Verlauf())
        if v.lap is None:
            v.lap = lap
            return
        if lap > v.lap:
            if lap == v.lap + 1:
                rz = self.rennzeit(jetzt)
                if rz is not None:
                    v.uebergaenge[lap] = rz
            else:
                v.unsicher = True
            v.lap = lap

    # -- Ziel und Ergebnisse -----------------------------------------------------
    def erster_im_ziel(self, slot: int, schonfrist: float, jetzt: float) -> Tuple[bool, float]:
        """``FIRST_FINISH``: ob die Meldung glaubhaft ist, und die Schonfrist.

        Die Meldung loest fuer alle anderen einen Countdown bis zum DNF aus. Ein
        veraenderter Client konnte mit einer Schonfrist von einer Sekunde alle
        Mitspieler aus dem Rennen werfen. Die Schonfrist ist im Spiel die
        langsamste Runde des Spitzenreiters, also nie kuerzer als die kuerzeste
        moegliche Runde.
        """
        rz = self.rennzeit(jetzt)
        if rz is not None and self.laps and self.min_runde:
            if rz < self.laps * self.min_runde - 1.0:
                self._verdacht(slot, "ZIEL_ZU_FRUEH", 3.0)
                return False, schonfrist
        if self.min_runde:
            schonfrist = max(schonfrist, self.min_runde)
        return True, schonfrist

    def zeilen_aufnehmen(self, slot: int, ist_host: bool, roh, jetzt: float) -> List[dict]:
        """Die Zeilen eines ``RACE_RESULT`` bereinigen und pruefen.

        Rueckgabe: nur bekannte Felder in sauberen Typen. Zeilen, deren Zeit
        nicht stimmen kann, tragen ``_grund``; ``_von`` ist der Absender. Beide
        Felder entfernt :meth:`bewerten` vor dem Versand.
        """
        if not isinstance(roh, list):
            return []
        aus = []
        for r in roh[:MAX_ZEILEN]:
            z = _zeile_bereinigen(r)
            if z is None:
                continue
            zs = z["slot"]
            if zs >= 0 and zs != slot:
                self._verdacht(slot, "ZEILE_FREMD", 3.0)       # Zeile fuer einen anderen Platz
                continue
            if zs < 0 and not ist_host:
                self._verdacht(slot, "ZEILE_KI", 3.0)          # nur der Host faehrt KI
                continue
            if zs >= 0:
                if zs in self.zeilen_slots:
                    continue                                    # doppelt: die erste gilt
                self.zeilen_slots.add(zs)
            z["_von"] = slot
            grund = self._zeit_pruefen(zs, z, jetzt)
            if grund:
                z["_grund"] = grund
                if zs < 0:                                      # KI-Zeit unmoeglich: der Host wars
                    self._verdacht(slot, "KI_ZEIT", 3.0)
                else:
                    self._verdacht(slot, grund, 3.0)
            aus.append(z)
        return aus

    def _zeit_pruefen(self, zs: int, z: dict, jetzt: float) -> str:
        ft, bl = z["finish_time"], z["best_lap"]
        if z["dnf"] or ft is None:
            return ""
        laps = self.laps
        mindest = self.min_runde or MIN_RUNDE_ABSOLUT
        if laps and ft < laps * mindest:
            return "ZEIT_ZU_KURZ"
        if bl is not None and bl < mindest:
            return "RUNDE_ZU_KURZ"
        # Alle Runden zusammen koennen nicht weniger sein als die beste, mal Anzahl.
        if bl is not None and laps and bl * laps > ft + 1.0 + 0.01 * ft:
            return "ZEIT_WIDERSPRUCH"
        # Gegen das, was der Relay vom Rennen selbst gesehen hat.
        v = self.verlauf.get(zs) if zs >= 0 else None
        if v is not None and not v.unsicher and laps:
            def spiel(t): return BEOB_SPIEL_S + BEOB_SPIEL_ANTEIL * t
            ziel = v.uebergaenge.get(laps + 1)
            if ziel is not None and ft < ziel - spiel(ziel):
                return "ZEIT_BEOBACHTET"
            if bl is not None:
                dauern = []
                vorher = 0.0
                for k in range(2, laps + 2):
                    t = v.uebergaenge.get(k)
                    if t is None:
                        break
                    dauern.append(t - vorher)
                    vorher = t
                if dauern and bl < min(dauern) - spiel(min(dauern)):
                    return "RUNDE_BEOBACHTET"
        return ""

    def bewerten(self, zeilen: List[dict]) -> List[dict]:
        """Vor dem Versand der Ergebnisse: Verdaechtige und unmoegliche Zeilen
        als ``invalid`` kennzeichnen, interne Felder entfernen."""
        aus = []
        for z in zeilen:
            z = dict(z)
            von = z.pop("_von", None)
            grund = z.pop("_grund", "")
            if not grund and von is not None and self.verdaechtig(von):
                grund = (self.gruende.get(von) or ["VERDACHT"])[0]
            if grund:
                log.warning(f"Schutz: Lobby {self.lobby_id}: Zeile '{z.get('name')}' "
                            f"ungültig ({grund}), gemeldet von Slot {von}")
                z["invalid"] = True
                z["dnf"] = True
                z["finish_time"] = None
                z["best_lap"] = None
            aus.append(z)
        return aus

    # -- Rauswurf ----------------------------------------------------------------
    def teilnehmer_merken(self, slot: int, name: str, cid: str, ip: str,
                          ip_eindeutig: bool) -> None:
        self.namen[slot] = name
        kurz = hashlib.sha256(("schutz|" + ip).encode()).hexdigest()[:12] if ip_eindeutig else ""
        self.teilnehmer[name] = {"slot": slot, "name": name, "cid": cid, "ip": ip if ip_eindeutig else "",
                                 "ip_kurz": kurz}
        if len(self.teilnehmer) > 64:
            self.teilnehmer.pop(next(iter(self.teilnehmer)))

    def sperren(self, name: str, cid: str, ip: str, ip_eindeutig: bool) -> None:
        """Wer entfernt wurde, kommt nicht wieder. Greift die Kennung, reicht sie;
        ohne Kennung zaehlt die Adresse (wenn sie jemanden unterscheidet), zuletzt
        der Name."""
        if cid:
            self._gesperrt_cid.add(cid)
        if ip_eindeutig and ip:
            self._gesperrt_ip.add(ip)
        if not cid and not (ip_eindeutig and ip):
            self._gesperrt_name.add(name.lower())

    def gesperrt(self, name: str, cid: str, ip: str, ip_eindeutig: bool) -> bool:
        if cid and cid in self._gesperrt_cid:
            return True
        if ip_eindeutig and ip and ip in self._gesperrt_ip:
            return True
        if not cid and not (ip_eindeutig and ip) and name.lower() in self._gesperrt_name:
            return True
        return False

    def spiel_passt(self, msg: dict) -> bool:
        g = msg.get("game")
        return not (self.spiel and isinstance(g, str) and g in SPIELE and g != self.spiel)


def _zeile_bereinigen(r) -> Optional[dict]:
    """Eine Ergebniszeile auf die Felder bringen, die die Clients kennen."""
    if not isinstance(r, dict):
        return None
    slot = r.get("slot", -1)
    if isinstance(slot, bool) or not isinstance(slot, int) or not (-1 <= slot <= 31):
        slot = -1

    def text(k, n=_ZEILE_TEXT):
        v = r.get(k, "")
        return "".join(c for c in str(v)[:n] if c.isprintable())

    def zeit(k):
        v = r.get(k)
        return float(v) if _endlich(v) and 0 < v < 86400 else None
    dnf = bool(r.get("dnf", False))
    ft, bl = zeit("finish_time"), zeit("best_lap")
    if ft is None:
        dnf = True
    return {
        "slot": slot, "name": text("name") or "?", "vehicle": text("vehicle"),
        "finish_time": ft, "best_lap": bl, "dnf": dnf, "team": text("team", 8) or "A",
        "ai_takeover": bool(r.get("ai_takeover", False)),
    }


# ══ 4. Meldungen ═════════════════════════════════════════════════════════════

MELDEGRUENDE = ("cheating", "griefing", "name", "other")
MELDUNGEN_DIR = os.environ.get(
    "RACE_MELDUNGEN_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "meldungen"))
MELDUNGEN_PRO_STUNDE = int(os.environ.get("RACE_MELDUNGEN_PRO_STUNDE", "6"))
MELDUNGEN_PRO_TAG = int(os.environ.get("RACE_MELDUNGEN_PRO_TAG", "20"))
MELDUNGEN_MAX = int(os.environ.get("RACE_MELDUNGEN_MAX", "2000"))
MELDUNGEN_TEXT = {
    "REPORT_UNKNOWN": "Diesen Spieler gibt es nicht (mehr).",
    "REPORT_SELF":    "Du kannst dich nicht selbst melden.",
    "REPORT_REASON":  "Ungültiger Meldegrund.",
    "REPORT_RATE":    "Du hast zu viele Spieler gemeldet. Versuch es später noch einmal.",
    "REPORT_OFF":     "Meldungen sind auf diesem Server gerade nicht möglich.",
}


class MeldungsFehler(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
        self.reason = MELDUNGEN_TEXT.get(code, "Fehler.")


class MeldungsSpeicher:
    """Die abgelegten Meldungen: eine Datei ``meldungen.json`` im Verzeichnis.

    Gespeichert wird atomar (Nebendatei, dann ``os.replace``). Das
    Verwaltungswerkzeug ``tools/meldungen_verwalten.py`` arbeitet auf derselben
    Datei, waehrend der Server laeuft; der Speicher liest sie bei jeder Meldung
    neu, wenn sie sich geaendert hat.
    """

    def __init__(self, verzeichnis: str, pro_stunde: Optional[int] = None,
                 pro_tag: Optional[int] = None, maximum: Optional[int] = None) -> None:
        self.verzeichnis = verzeichnis
        self.pro_stunde = MELDUNGEN_PRO_STUNDE if pro_stunde is None else pro_stunde
        self.pro_tag = MELDUNGEN_PRO_TAG if pro_tag is None else pro_tag
        self.maximum = MELDUNGEN_MAX if maximum is None else maximum
        self.liste: List[dict] = []
        self.salz = ""
        self._stand = None
        self._zeiten: "Dict[str, deque]" = {}
        os.makedirs(verzeichnis, exist_ok=True)
        self._laden()

    @property
    def pfad(self) -> str:
        return os.path.join(self.verzeichnis, "meldungen.json")

    def _stand_lesen(self):
        try:
            st = os.stat(self.pfad)
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def _laden(self) -> None:
        try:
            with open(self.pfad, encoding="utf-8") as f:
                d = json.load(f)
            if not isinstance(d, dict) or not isinstance(d.get("meldungen"), list):
                raise ValueError("kein Feld 'meldungen'")
            self.liste = [m for m in d["meldungen"] if isinstance(m, dict)]
            self.salz = str(d.get("salz", "")) or secrets.token_hex(8)
        except FileNotFoundError:
            self.liste, self.salz = [], secrets.token_hex(8)
        except Exception as exc:
            log.warning(f"meldungen.json unlesbar, beginne neu: {exc}")
            self.liste, self.salz = [], secrets.token_hex(8)
        self._stand = self._stand_lesen()

    def _speichern(self) -> None:
        tmp = self.pfad + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "salz": self.salz, "meldungen": self.liste},
                      f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.pfad)
        self._stand = self._stand_lesen()

    def _kurz(self, schluessel: str) -> str:
        return hashlib.sha256((self.salz + schluessel).encode()).hexdigest()[:12]

    def melden(self, *, melder_schluessel: str, melder_name: str, melder_cid: str,
               ziel_name: str, ziel_cid: str, ziel_ip_kurz: str, lobby: str,
               spiel: str, version: str, grund: str, marken: List[str]) -> dict:
        """Eine Meldung ablegen. Wirft :class:`MeldungsFehler`.

        Doppelt (gleicher Melder, gleiches Ziel, gleiche Lobby) wird still als
        erledigt behandelt — gemeldet ist gemeldet, ein zweiter Klick soll nicht
        als Fehler erscheinen und zaehlt nicht zur Rate.
        """
        if grund not in MELDEGRUENDE:
            raise MeldungsFehler("REPORT_REASON")
        if self._stand_lesen() != self._stand:
            self._laden()
        kurz = self._kurz(melder_schluessel)
        for m in self.liste:
            if (m.get("melder_key") == kurz and m.get("lobby") == lobby
                    and m.get("ziel", {}).get("name") == ziel_name):
                return m
        jetzt = time.time()
        q = self._zeiten.setdefault(kurz, deque())
        while q and jetzt - q[0] > 86400:
            q.popleft()
        if len(q) >= self.pro_tag or sum(1 for t in q if jetzt - t <= 3600) >= self.pro_stunde:
            raise MeldungsFehler("REPORT_RATE")
        q.append(jetzt)
        if len(self._zeiten) > 4096:
            for k in [k for k, v in self._zeiten.items() if not v or jetzt - v[-1] > 86400]:
                self._zeiten.pop(k, None)
        eintrag = {
            "id": secrets.token_hex(4),
            "zeit": int(jetzt),
            "spiel": spiel, "version": version, "lobby": lobby,
            "melder": {"name": melder_name, "cid": melder_cid},
            "melder_key": kurz,
            "ziel": {"name": ziel_name, "cid": ziel_cid, "ip": ziel_ip_kurz},
            "grund": grund,
            "marken": list(marken),
            "erledigt": False,
        }
        self.liste.append(eintrag)
        if len(self.liste) > self.maximum:
            self.liste = self.liste[-self.maximum:]
        self._speichern()
        log.warning(f"Meldung {eintrag['id']}: '{melder_name}' meldet '{ziel_name}' "
                    f"({grund}) in {lobby}, Marken {marken}")
        return eintrag
