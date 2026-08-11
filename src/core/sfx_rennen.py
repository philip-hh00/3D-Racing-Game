"""Klang im Rennen: eine Motorstimme je Fahrzeug, Abstand und Panorama (§C6).

Diese Ebene verbindet die Fahrphysik mit den Klangbausteinen aus
``src/core/sfx.py``. Getrennt gehalten, weil sie zwei Dinge tut, die nichts
miteinander zu tun haben: rechnen (welches Fahrzeug wie laut und wo) und
nachschieben (Blöcke in die Mixerkanäle).

**Warum nachgeschoben wird.** pygame kann keinen Klang mit veränderlicher Rate
abspielen. Eine Motorstimme erzeugt ihre Blöcke deshalb selbst und legt sie in
die Warteschlange des Kanals. Genau ein Block darf dort liegen: liegt keiner,
reißt der Klang ab; liegen mehrere, hinkt die Drehzahl hinter dem Bild her.

**Warum die Rechnung von der Wiedergabe getrennt ist.** Abstandsdämpfung und
Panorama sind reine Zahlen und ohne Audiogerät prüfbar. Das ist der Teil, in dem
sich Fehler verstecken — nicht im Nachschieben.
"""
from __future__ import annotations

import math

import numpy as np

from src.core import sfx

#: Ab dieser Entfernung (Weltpixel) ist ein Fahrzeug nicht mehr zu hören.
#: Rund eine halbe Bildbreite. Vorher 2600, also gut eine Bildbreite über den
#: Rand hinaus — dann brummten Fahrzeuge mit, die gar nicht zu sehen waren.
HOERWEITE = 1000.0
#: Halbe Lautstärke bei dieser Entfernung. Steuert, wie schnell es abfällt.
#: Etwa fünf Fahrzeuglängen: was direkt nebenan oder im Windschatten fährt, ist
#: klar zu hören, alles weiter weg fällt schnell ab.
HALBWERT = 260.0
#: Entfernung, ab der voll nach links oder rechts gelegt wird.
PANORAMA_WEITE = 500.0
#: Vorlauf des Startsignals: ``race-start.wav`` ist der ganze Countdown, der
#: lange Ton liegt bei Sekunde 3,0. So viel vor GO muss es also anfangen.
STARTSIGNAL_VORLAUF = 3.0
#: Obergrenze für die Summe aller Motorlautstärken. Der Mixer addiert die Kanäle
#: und schneidet ab, was über die Vollaussteuerung geht — hörbar als Knistern.
#: Eine Stimme steuert bis 0,60 aus; gemessen bleibt die Summe bei diesem Budget
#: auch im dichten Pulk unter 0,75. Bis vier Fahrzeuge greift es nie ein.
PEGELBUDGET = 2.0
#: Reifenquietschen erst ab diesem Schräglaufwinkel, voll ab dem Doppelten.
SCHLUPF_AB = 8.0
#: Aufprall unter diesem Impuls bleibt stumm — sonst knackt jede Berührung.
IMPULS_AB = 500.0
#: Ab diesem Impuls gilt ein Treffer als schwer.
IMPULS_SCHWER = 4000.0
#: Die beiden Reifenklaenge, abwechselnd benutzt. `tire-screeching-2` lag seit
#: Block C ungenutzt herum (C7) — zwei Klaenge im Wechsel klingen weniger nach
#: Endlosschleife als einer.
REIFENKLAENGE = ("tire-screeching-1.wav", "tire-screeching-2.wav")
#: Treffer sind lauter als noetig (gemeldet 05.08.2026: „Kollision ist etwas
#: lauter als noetig — kann um 30% reduziert werden"). Gilt fuer Fahrzeug- und
#: Wandtreffer gemeinsam: es ist derselbe Anlass, und `car-wall` war ohnehin
#: der lauteste Klang im Spiel.
AUFPRALL_DAEMPFUNG = 0.7


# ── Rechnen: prüfbar ohne Audiogerät ────────────────────────────────────────

#: Über diese Strecke vor der Hörweite wird auf null ausgeblendet.
AUSBLENDE = 0.25 * HOERWEITE


def daempfung(entfernung: float) -> float:
    """Lautstärkefaktor 0..1 nach Entfernung.

    Quadratischer Abfall statt linear: linear klingt weit entferntes noch
    unnatürlich präsent und alles gleich laut. Jenseits von HOERWEITE genau
    null, damit ein Kanal ganz abgeschaltet werden kann.

    **Das letzte Viertel wird ausgeblendet** (03.08.2026). Die Kennlinie liegt
    bei HOERWEITE noch bei 0,063; dort einfach auf null zu schalten ist ein
    Sprung im Pegel, und ein Fahrzeug pendelt in einem Rennen dauernd um diese
    Grenze. Jedes Überschreiten war damit ein Knacks — und zwar genau dann, wenn
    ein *anderes* Fahrzeug in Hörweite kommt. Das eigene Auto hat Entfernung
    null und kennt den Fall nicht, was zu „allein klingt es gut" passt.
    """
    if entfernung >= HOERWEITE:
        return 0.0
    e = max(0.0, entfernung)
    g = 1.0 / (1.0 + (e / HALBWERT) ** 2)
    if e > HOERWEITE - AUSBLENDE:
        g *= (HOERWEITE - e) / AUSBLENDE
    return g


def panorama(dx: float) -> float:
    """Seitliche Lage -1 (links) bis +1 (rechts) aus dem x-Abstand."""
    return max(-1.0, min(1.0, dx / PANORAMA_WEITE))


def hoerbar_bei(positionen: list[tuple[float, float]],
                fahrzeug: tuple[float, float]) -> tuple[float, float]:
    """(Lautstärke, Panorama) für mehrere Hörpositionen.

    Im Splitscreen gibt es zwei Kameras, also zwei Hörer. Genommen wird die
    **nähere** Position: die Lautstärken zu addieren würde ein Fahrzeug in der
    Mitte zwischen beiden Spielern doppelt so laut machen wie eines direkt
    neben einem — und das Panorama beider zu mischen ergäbe „von überall".
    """
    if not positionen:
        return (0.0, 0.0)
    beste = None
    for px, py in positionen:
        dx = fahrzeug[0] - px
        dy = fahrzeug[1] - py
        d = math.hypot(dx, dy)
        if beste is None or d < beste[0]:
            beste = (d, dx)
    d, dx = beste
    return (daempfung(d), panorama(dx))


def schlupf_lautstaerke(schraeglauf_grad: float) -> float:
    """Reifenquietschen nach Schräglaufwinkel, 0..1.

    Erst ab SCHLUPF_AB, damit normales Kurvenfahren still bleibt — sonst
    quietscht es dauernd und bedeutet nichts mehr.
    """
    if schraeglauf_grad <= SCHLUPF_AB:
        return 0.0
    return min(1.0, (schraeglauf_grad - SCHLUPF_AB) / SCHLUPF_AB)


def klasse_von_schluessel(schluessel: str) -> str:
    """Fahrzeugklasse zu einem Konfigurationsschlüssel, z.B. rookie_2 → Hatchback.

    Die Zuordnung steht in race_setup.CLASSES, allerdings in der anderen
    Richtung. Hier umgedreht, damit der Klang nicht raten muss.
    """
    from src.core import race_setup
    for klasse, schluessel_liste in race_setup.CLASSES.items():
        if klasse == "Alle":
            continue
        if schluessel in schluessel_liste:
            return klasse
    return ""


def klangfarbe_von_schluessel(schluessel: str) -> tuple[float, float]:
    """(Tonhöhenversatz, Färbung) eines Fahrzeugs (§C5).

    Die Werte stehen in der Fahrzeug-JSON unter ``klang``. Fehlen sie oder ist
    das Fahrzeug unbekannt, klingt es wie die Aufnahme — nicht wie ein anderes
    Fahrzeug, denn ein geratener Versatz wäre schlimmer als keiner.
    """
    try:
        from src.entities.vehicle_factory import VehicleFactory
        cfg = VehicleFactory.get_config(schluessel)
    except Exception:
        cfg = None
    if cfg is None:
        return (1.0, 0.0)
    return (float(getattr(cfg, "klang_tonhoehe", 1.0)),
            float(getattr(cfg, "klang_faerbung", 0.0)))


def kennung(fahrzeug) -> tuple:
    """Eindeutige Kennung eines Fahrzeugs für die Kanalzuordnung.

    ``id`` allein reicht nicht: ein fernes Fahrzeug trägt die ``vehicle_id``
    seines Absenders, und die ist 1 wie beim eigenen Auto. Ohne den Absender im
    Schlüssel würden sich beide denselben Kanal teilen — der eigene Motor würde
    von einem Mitspieler übernommen.
    """
    return (getattr(fahrzeug, "sender_slot", None), getattr(fahrzeug, "id", None))


def motor_fuer_klasse(fahrzeug_klasse: str) -> str:
    """Welche Aufnahme zu welcher Fahrzeugklasse gehört (§C3).

    Zuordnung nach Zylinderzahl, wie festgelegt: Hatchback vier, Limousine und
    Drifter sechs, Rennfahrzeug acht.

    Elektro bekommt bewusst ``"elektro"``, wozu es keine Aufnahmen gibt — das
    Fahrzeug bleibt also still. Ein Sechszylinder unter einem E-Auto wäre kein
    Ersatz, sondern ein hörbarer Fehler. Unbekanntes fällt auf sechs Zylinder,
    weil eine neue Klasse eher nach Mittelklasse klingt als nach nichts.
    """
    return {
        "Hatchback": "4zyl",
        "Limousine": "6zyl",
        "Drifter": "6zyl",
        "Rennfahrzeug": "8zyl",
        "Elektroauto": "elektro",
    }.get(fahrzeug_klasse, "6zyl")


# ── Wiedergabe ──────────────────────────────────────────────────────────────

class _RingStimme:
    """Eine Motorstimme auf dem Audiofaden (06.08.2026).

    Der Weg, der seit dem Umbau gilt: die Stimme meldet sich beim Ringpuffer an,
    und der Treiber **ruft ab**, wenn er Ton braucht. Das Spiel setzt hier nur
    noch Drehzahl und Lautstärke — es legt keinen Ton mehr nach und hängt damit
    nicht mehr am Bildtakt.

    ``_erzeugen`` läuft im **Erzeugerfaden**, alles andere im Spielfaden. Der
    einzige gemeinsame Wert ist ``self._upm``, und eine Zuweisung an einen
    Gleitkommawert ist unteilbar — es braucht keine Sperre.

    Dieselbe Schnittstelle wie :class:`_Stimme`, damit ``Rennklang`` nicht weiss,
    auf welchem Weg es gerade läuft.
    """

    def __init__(self, motor: str, tonhoehe: float = 1.0,
                 faerbung: float = 0.0) -> None:
        from src.core import tonausgabe
        self.stimme = sfx.Motorstimme(motor, tonhoehe, faerbung)
        self._upm = 0.0
        self._ring = None
        if self.stimme:
            self._ring = tonausgabe.stimme_anlegen(self._erzeugen, 0.0, 0.0)

    def _erzeugen(self, laenge: int):
        """**Erzeugerfaden.** Der nächste Abschnitt bei der aktuellen Drehzahl."""
        block = self.stimme.block(self._upm, laenge)
        from src.core import klangmitschnitt
        if klangmitschnitt.laeuft():
            klangmitschnitt.block_gemerkt(block, False)
        return block

    def stille(self) -> None:
        if self._ring is not None:
            self._ring.einstellen(0.0, 0.0)

    def aktualisieren(self, upm: float, links: float, rechts: float) -> None:
        self._upm = float(upm)
        if self._ring is not None:
            self._ring.einstellen(links, rechts)

    def beenden(self) -> None:
        if self._ring is not None:
            self._ring.beenden()
            self._ring = None


class _Stimme:
    """Eine Motorstimme samt Mixerkanal.

    Der **Rückfallweg**, seit dem 06.08.2026. Er gilt, wenn sich kein Audiofaden
    öffnen liess (kein PortAudio, kein Ausgabegerät). Ton, der einen Block
    vorhält und je Bild nachlegt — mit allen Schwächen, die den Umbau nötig
    gemacht haben, aber immer noch besser als Stille.
    """

    def __init__(self, motor: str, kanal_nr: int, tonhoehe: float = 1.0,
                 faerbung: float = 0.0) -> None:
        self.stimme = sfx.Motorstimme(motor, tonhoehe, faerbung)
        self.kanal_nr = kanal_nr
        self._gestartet = False

    def _kanal(self):
        import pygame
        return pygame.mixer.Channel(self.kanal_nr)

    def _als_klang(self, block):
        import pygame
        stereo = np.repeat((block * 32767.0).astype(np.int16)[:, None], 2, axis=1)
        return pygame.sndarray.make_sound(np.ascontiguousarray(stereo))

    def _klang(self, upm: float):
        import pygame
        block = self.stimme.block(upm)
        # Mixer laeuft zweikanalig: derselbe Block auf beide Seiten, die Lage im
        # Raum macht set_volume. So muss der Block bei jeder Bewegung nicht neu
        # gerechnet werden.
        stereo = np.repeat((block * 32767.0).astype(np.int16)[:, None], 2, axis=1)
        return pygame.sndarray.make_sound(np.ascontiguousarray(stereo))

    def stille(self) -> None:
        """Kanal ausblenden, ohne die Stimme aufzugeben.

        Für Fahrzeuge jenseits der Hörweite: sonst rechnet jedes von ihnen
        weiter Blöcke, die niemand hört.

        **Ausgeblendet, nicht angehalten** (03.08.2026). ``stop()`` schneidet den
        laufenden Block mitten in der Welle ab; das ist ein Knacks, und er trifft
        jedes Fahrzeug, das die Hörgrenze überschreitet. Die kurze Blende kostet
        nichts — das Fahrzeug ist an dieser Stelle ohnehin schon fast still.
        """
        if not self._gestartet:
            return
        try:
            self._kanal().fadeout(60)
        except Exception:
            self.beenden()
            return
        self._gestartet = False

    def aktualisieren(self, upm: float, links: float, rechts: float) -> None:
        """Lautstärke setzen und, wenn nötig, den nächsten Block nachlegen.

        **Nur ``queue``, nie ``play``.** ``queue`` startet einen stehenden Kanal
        von selbst, deckt also auch den Anfang und die Rückkehr aus dem
        Pausenmenü ab. Der frühere Neustart über ``get_busy()`` sah dagegen auch
        den kurzen Moment zwischen zwei Blöcken als „steht" und schnitt den
        laufenden Block ab. Das wuchs mit der Bildrate: bei 60 Abfragen je
        Sekunde fünf Fehlstarts in sechs Sekunden, bei 300 Abfragen 37, ohne
        Bremse 141 — dann wurde fast jeder zweite Block gekappt. Gehört hat man
        ein Blubbern über dem Motor.
        """
        if not self.stimme:
            return
        if links <= 0.001 and rechts <= 0.001:
            self.stille()
            return
        kanal = self._kanal()
        kanal.set_volume(links, rechts)
        # Genau einen Block vorhalten. Ohne Nachschieben reisst der Klang ab,
        # mit zu vielen hinkt die Drehzahl hinter dem Bild her — mehr als einen
        # nimmt pygame ohnehin nicht an, der zweite ersetzt den ersten.
        if kanal.get_queue() is None:
            # Stand der Kanal still, war die Warteschlange nicht nur leer,
            # sondern der vorgehaltene Block schon abgespielt — das ist eine
            # Luecke im Ton. Nur fuer den Mitschnitt gezaehlt (05.08.2026);
            # ohne laufenden Mitschnitt kostet es einen Aufruf und sonst nichts.
            from src.core import klangmitschnitt
            if klangmitschnitt.laeuft():
                block = self.stimme.block(upm)
                klangmitschnitt.block_gemerkt(block, not kanal.get_busy())
                kanal.queue(self._als_klang(block))
                self._gestartet = True
                return
            kanal.queue(self._klang(upm))
            self._gestartet = True

    def beenden(self) -> None:
        """Kanal ausblenden, ohne den Block abzuschneiden.

        Wird beim Verlassen des Rennens gerufen (RaceState.exit), also bei
        JEDEM Rennende. Wie stille(): ``stop()`` schneidet die laufende Welle
        mitten durch — das ist ein Knacks (03.08.2026). Ausblendung statt
        Abbruch verhindert das Störgeräusch beim Übergang zu den Menüsounds
        (Playtest 05.08.2026).
        """
        if not self._gestartet:
            return
        try:
            self._kanal().fadeout(60)
        except Exception:
            pass
        self._gestartet = False


class Rennklang:
    """Hält die Motorstimmen eines Rennens und stößt Einzelklänge an."""

    def __init__(self) -> None:
        self._stimmen: dict[tuple, _Stimme] = {}   # Kennung -> Stimme
        self._schluessel: dict[tuple, str] = {}
        self._freie_kanaele: list[int] = []
        self._reifen_kanal: int | None = None
        #: Welcher der beiden Reifenklaenge als naechstes an der Reihe ist.
        self._reifen_naechster = 0
        self._aktiv = False

    # ── Aufbau ──
    def starten(self, fahrzeuge: list, schluessel: dict) -> None:
        """Stimmen anlegen. *schluessel* ist Kennung -> Konfigurationsschlüssel.

        Der Schlüssel statt der Klasse, weil daran beides hängt: welcher Motor
        (über die Klasse) und wie dieses eine Fahrzeug davon abweicht (§C5).

        Ferne Fahrzeuge entstehen erst im laufenden Rennen, sobald das erste
        Paket kommt — ihre Stimmen kommen deshalb in ``aktualisieren`` nach.
        """
        self._schluessel = dict(schluessel)
        self._aktiv = True
        if not _mixer_bereit():
            return
        self._freie_kanaele = list(range(sfx.EINZEL_KANAELE, _kanalzahl()))
        # Ein Kanal geht ans Reifenquietschen, bevor die Motoren zugreifen.
        self._reifen_kanal = self._freie_kanaele.pop(0) if self._freie_kanaele else None
        for fahrzeug in fahrzeuge:
            self._stimme_fuer(fahrzeug)

    def beenden(self) -> None:
        for stimme in self._stimmen.values():
            stimme.beenden()
        self._stimmen.clear()
        if self._reifen_kanal is not None and _mixer_bereit():
            import pygame
            try:
                # Wie in _Stimme.beenden(): ausblenden statt hart anhalten.
                # ``stop()`` schneidet die Welle mitten durch — das ist ein Knacks
                # (03.08.2026, Fund vom 05.08.2026).
                pygame.mixer.Channel(self._reifen_kanal).fadeout(60)
            except Exception:
                pass
        self._freie_kanaele = []
        self._reifen_kanal = None
        self._aktiv = False

    def _stimme_fuer(self, fahrzeug) -> _Stimme | None:
        """Stimme des Fahrzeugs, notfalls neu angelegt."""
        kn = kennung(fahrzeug)
        if kn[1] is None:
            return None
        stimme = self._stimmen.get(kn)
        if stimme is not None:
            return stimme
        # Ferne Fahrzeuge tragen ihren Konfigurationsschlüssel selbst.
        key = self._schluessel.get(kn) or getattr(fahrzeug, "config_key", "")
        tonhoehe, faerbung = klangfarbe_von_schluessel(key)
        motor = motor_fuer_klasse(klasse_von_schluessel(key))

        # Läuft der Audiofaden, braucht diese Stimme gar keinen Mixerkanal —
        # sie hängt am Ringpuffer. Die Kanäle bleiben damit für Reifen,
        # Aufpralle und Menüklänge frei.
        from src.core import tonausgabe
        if tonausgabe.laeuft():
            stimme = _RingStimme(motor, tonhoehe, faerbung)
            if not stimme.stimme:
                return None      # keine Aufnahmen für diesen Motor
            self._stimmen[kn] = stimme
            return stimme

        if not self._freie_kanaele:
            return None      # Kanäle aufgebraucht; lieber still als verzerrt
        stimme = _Stimme(motor, self._freie_kanaele[0], tonhoehe, faerbung)
        if not stimme.stimme:
            return None      # keine Aufnahmen für diesen Motor
        self._freie_kanaele.pop(0)
        self._stimmen[kn] = stimme
        return stimme

    # ── Je Bild ──
    def aktualisieren(self, fahrzeuge: list,
                      hoerpositionen: list[tuple[float, float]]) -> None:
        if not self._aktiv or not _mixer_bereit():
            return
        gesamt = sfx.effekt_lautstaerke()

        vorhanden = set()
        einstellung = []
        for fahrzeug in fahrzeuge:
            stimme = self._stimme_fuer(fahrzeug)
            if stimme is None:
                continue
            vorhanden.add(kennung(fahrzeug))
            laut, pano = hoerbar_bei(hoerpositionen, _position(fahrzeug))
            einstellung.append((stimme, _drehzahl(fahrzeug), laut * gesamt, pano))

        # Der Mixer addiert die Kanäle und schneidet ab, was darüber hinausgeht.
        # Deshalb erst alle Lautstärken sammeln und, wenn es zu viel wird, alle
        # gemeinsam zurücknehmen — einzeln begrenzt würde ausgerechnet das
        # nächste Fahrzeug leiser, wenn ein Feld zusammenrückt.
        summe = sum(laut for _s, _u, laut, _p in einstellung)
        deckel = min(1.0, PEGELBUDGET / summe) if summe > PEGELBUDGET else 1.0

        for stimme, upm, laut, pano in einstellung:
            laut *= deckel
            stimme.aktualisieren(upm, laut * min(1.0, 1.0 - pano),
                                 laut * min(1.0, 1.0 + pano))

        # Verschwundene Fahrzeuge geben ihren Kanal zurück — sonst hat ein
        # Online-Rennen mit Aus- und Wiedereinstiegen irgendwann keinen frei.
        for kn in [k for k in self._stimmen if k not in vorhanden]:
            stimme = self._stimmen.pop(kn)
            stimme.beenden()
            # Eine Ringstimme hat gar keinen Kanal belegt, deshalb gibt es auch
            # keinen zurückzugeben.
            nummer = getattr(stimme, "kanal_nr", None)
            if nummer is not None:
                self._freie_kanaele.append(nummer)

    def reifen(self, fahrzeug, hoerpositionen: list[tuple[float, float]]) -> None:
        """Reifenquietschen des eigenen Fahrzeugs als Schleife führen.

        Nur für das eigene Auto: als Einzelklang je Fahrzeug angestoßen würde
        es bei sechs driftenden Autos zum Maschinengewehr.
        """
        if not self._aktiv or self._reifen_kanal is None or not _mixer_bereit():
            return
        import pygame
        from src.core.resource_manager import ResourceManager
        winkel = abs(_schraeglauf(fahrzeug))
        staerke = schlupf_lautstaerke(winkel) * sfx.effekt_lautstaerke()
        kanal = pygame.mixer.Channel(self._reifen_kanal)
        if staerke <= 0.01:
            if kanal.get_busy():
                kanal.fadeout(200)
            return
        _laut, pano = hoerbar_bei(hoerpositionen, _position(fahrzeug))
        kanal.set_volume(staerke * min(1.0, 1.0 - pano),
                         staerke * min(1.0, 1.0 + pano))
        if not kanal.get_busy():
            # Abwechselnd, nicht immer derselbe (C7): jede neue Drift nimmt den
            # anderen Klang. Innerhalb einer Drift laeuft er als Schleife weiter
            # — mitten im Quietschen zu wechseln waere ein hoerbarer Schnitt.
            pfad = sfx._pfad(REIFENKLAENGE[self._reifen_naechster])
            self._reifen_naechster = (self._reifen_naechster + 1) % len(REIFENKLAENGE)
            try:
                kanal.play(ResourceManager().load_sound(pfad), loops=-1)
            except Exception:
                pass

    # ── Anlässe ──
    def aufprall(self, impuls: float, fahrzeug=None,
                 hoerpositionen: list[tuple[float, float]] | None = None) -> None:
        """Treffer gegen Wand oder Fahrzeug."""
        if impuls < IMPULS_AB:
            return
        anteil = min(1.0, (impuls - IMPULS_AB) / max(1.0, IMPULS_SCHWER - IMPULS_AB))
        name = "car-crash-big" if impuls >= IMPULS_SCHWER else "car-crash-small"
        pano = 0.0
        laut = (0.4 + 0.6 * anteil) * AUFPRALL_DAEMPFUNG
        if fahrzeug is not None and hoerpositionen:
            entfernt, pano = hoerbar_bei(hoerpositionen, _position(fahrzeug))
            laut *= entfernt
        sfx.spielen(name, laut, pano)

    def wandtreffer(self, impuls: float, fahrzeug=None,
                    hoerpositionen: list[tuple[float, float]] | None = None) -> None:
        if impuls < IMPULS_AB:
            return
        pano = 0.0
        laut = min(1.0, 0.4 + impuls / 8000.0) * AUFPRALL_DAEMPFUNG
        if fahrzeug is not None and hoerpositionen:
            entfernt, pano = hoerbar_bei(hoerpositionen, _position(fahrzeug))
            laut *= entfernt
        sfx.spielen("car-wall", laut, pano)

    def startsignal(self) -> None:
        sfx.spielen("race-start", 1.0)


# ── Kleinkram ───────────────────────────────────────────────────────────────

def _kanalzahl() -> int:
    """Wie viele Mixerkanäle es gibt. Eigene Funktion, damit ein Test die
    Kanalvergabe prüfen kann, ohne ein Audiogerät zu haben."""
    import pygame
    return int(pygame.mixer.get_num_channels())


def _mixer_bereit() -> bool:
    try:
        import pygame
        return bool(pygame.mixer and pygame.mixer.get_init())
    except Exception:
        return False


def _position(fahrzeug) -> tuple[float, float]:
    koerper = getattr(fahrzeug, "body", None)
    stelle = getattr(koerper, "position", None)
    if stelle is not None:
        return (float(stelle[0]), float(stelle[1]))
    return (0.0, 0.0)


def _schraeglauf(fahrzeug) -> float:
    """Schräglaufwinkel in Grad — die Zahl, an der das Quietschen hängt.

    Gelesen wurde bis zum 04.08.2026 ``fahrzeug.body.slip_angle_deg``, und
    ``Vehicle.body`` ist der **pymunk-Körper**; den Winkel führt daneben
    ``Vehicle.physics``. ``getattr(..., 0.0)`` lieferte also immer 0, und es hat
    **nie** gequietscht. Aufgefallen ist es nicht, weil das Testdoppel den Wert
    auf seinen falschen Körper legte — der Test prüfte die Attrappe, nicht das
    Spiel.

    Deshalb hier drei Wege in dieser Reihenfolge: das Fahrzeug selbst (es hat
    die Eigenschaft), sein Physikteil, und zuletzt der Körper — damit ein
    Testdoppel, das den Wert dort ablegt, weiterhin bedient wird.
    """
    for quelle in (fahrzeug,
                   getattr(fahrzeug, "physics", None),
                   getattr(fahrzeug, "body", None)):
        wert = getattr(quelle, "slip_angle_deg", None)
        if wert is not None:
            try:
                return float(wert)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _drehzahl(fahrzeug) -> float:
    """Drehzahl des Fahrzeugs, oder aus der Geschwindigkeit geschätzt.

    Ferne Fahrzeuge im Online-Rennen sind kinematische Abbilder ohne Motor —
    sie haben keine Drehzahl. Ohne Schätzung wären alle Mitspieler stumm.
    """
    upm = getattr(fahrzeug, "rpm", None)
    if upm:
        return float(upm)
    koerper = getattr(fahrzeug, "body", None)
    v = getattr(koerper, "velocity", None)
    if v is None:
        return 0.0
    tempo = math.hypot(float(v[0]), float(v[1]))
    # Grobe Kennlinie: Standgas bis Hoechstdrehzahl ueber den Tempobereich.
    return 1200.0 + min(1.0, tempo / 900.0) * 6000.0
