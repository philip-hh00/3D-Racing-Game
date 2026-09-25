"""Player profile: username and per-track best lap times.

Stored in data/settings/profile.json. A username validator enforces length and
character rules and screens against a supplied blacklist
(data/settings/name_blacklist.json — a JSON array of forbidden substrings).

Seit dem 02.08.2026 liegt die Datei **verschlüsselt und signiert** ab, mit
``profile.bak`` als Sicherung (Releaseplan E4). Wie das geht und warum es
ausdrücklich nur eine Bremsschwelle ist, steht in :mod:`src.core.tresor`; hier
bleibt nur, dass gelesen und geschrieben durch ihn läuft. Ein Klartextprofil von
vorher wird beim Lesen übernommen und beim nächsten Speichern umgestellt.
"""
from __future__ import annotations

import json
import os
import re

_DIR = os.path.join("data", "settings")
# name_blacklist.json is a bundled read-only asset (resolved via cwd).
_BLACKLIST_PATH = os.path.join(_DIR, "name_blacklist.json")


def _profile_path() -> str:
    """Writable profile location (user-data dir; survives app being read-only)."""
    from src.core.paths import user_path
    return user_path("data", "settings", "profile.json")

NAME_MIN = 3
NAME_MAX = 15
NAME_ALLOWED = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
_NAME_RE = re.compile(r"^[A-Za-z0-9_]{%d,%d}$" % (NAME_MIN, NAME_MAX))


class Profile:
    """In-memory profile, loaded once and saved on change."""

    def __init__(self, username: str = "", best_laps: dict | None = None,
                 menu_volume: float = 0.7, race_volume: float = 0.7,
                 sfx_menu_volume: float = 0.7, sfx_race_volume: float = 0.7,
                 resolution: str = "1920x1080", fullscreen: bool = False,
                 fps_limit: int = 60, vsync: bool = False,
                 texture_quality: str = "Hoch", language: str = "en",
                 seen_announcements: list | None = None,
                 paints: dict | None = None,
                 statistik: dict | None = None,
                 announcements_seeded: bool = False,
                 grafik: dict | None = None) -> None:
        self.username = username
        self.best_laps: dict[str, float] = best_laps or {}
        self.menu_volume = menu_volume
        self.race_volume = race_volume
        #: Zwei Effektregler statt einem (02.08.2026). Menuegeraeusche und
        #: Rennklaenge haben nichts miteinander zu tun: das Menue soll leise
        #: bestaetigen, das Rennen soll traegen. Mit einem gemeinsamen Regler
        #: musste man sich fuer eines von beiden entscheiden.
        self.sfx_menu_volume = sfx_menu_volume
        self.sfx_race_volume = sfx_race_volume
        # Video settings
        self.resolution = resolution      # "WxH" string, e.g. "1920x1080"
        self.fullscreen = fullscreen
        self.fps_limit = fps_limit        # 0 = unlimited
        self.vsync = vsync
        self.texture_quality = texture_quality
        #: Sprache "de" oder "en". Ein frisch angelegtes Profil startet auf
        #: Englisch (08.08.2026): das Spiel geht auf itch.io/GameJolt an ein
        #: internationales Publikum, Deutsch ist ueber Einstellungen einen Klick
        #: entfernt. Ein bestehendes Profil behaelt seine gespeicherte Wahl.
        self.language = language
        self.seen_announcements: list[str] = seen_announcements or []
        #: Ob die Ankuendigungen bei der Erstinstallation schon einmal als
        #: gesehen verbucht wurden (08.08.2026). Ein frisches Profil (False) soll
        #: nicht mit der ganzen bisherigen Sammlung begruesst werden; sobald die
        #: Liste zum ersten Mal vorliegt, wird sie stumm quittiert. Ein
        #: bestehendes Profil ohne dieses Feld gilt als laengst versorgt (True in
        #: load), damit ihm neue Ankuendigungen weiter erscheinen.
        self.announcements_seeded = bool(announcements_seeded)
        #: Lackierung je Fahrzeug: Fahrzeugschluessel -> Lackkennung.
        #: Fehlender Eintrag heisst Werkslack; das gilt auch fuer jedes Profil,
        #: das vor Block D geschrieben wurde.
        self.paints: dict[str, str] = dict(paints) if isinstance(paints, dict) else {}
        #: Gezaehlte Rennen, Siege, Kilometer ... (Releaseplan E1). Die Regeln,
        #: was zaehlt, stehen in src/core/statistik.py und nur dort. Ein
        #: fehlender Schluessel ist kein Fehler, sondern eine Null — dieselbe
        #: Regel wie bei paints.
        self.statistik: dict = dict(statistik) if isinstance(statistik, dict) else {}
        #: Grafikeinstellungen der 3D-Welt (``src/render3d/grafik.py``,
        #: ``als_dict``). ``None`` heißt: noch nie gewählt — beim ersten Start
        #: sucht ``display`` eine Stufe nach der Grafikkarte aus und legt sie hier ab.
        self.grafik: dict | None = dict(grafik) if isinstance(grafik, dict) else None

    # -- persistence -----------------------------------------------------
    @classmethod
    def load(cls) -> "Profile":
        try:
            from src.core import tresor
            roh = tresor.lesen(_profile_path())
            if roh is None:
                return cls()
            data = json.loads(roh)
            old_vol = data.get("volume", 0.7)
            # Ein Profil von vor dem 02.08.2026 kennt nur "sfx_volume". Beide
            # neuen Regler erben diesen Wert — wer die Effekte leise gestellt
            # hatte, findet sie nach dem Update nicht ploetzlich laut vor.
            alt_sfx = data.get("sfx_volume", 0.7)
            return cls(
                data.get("username", ""),
                data.get("best_laps", {}),
                data.get("menu_volume", old_vol),
                data.get("race_volume", old_vol),
                data.get("sfx_menu_volume", alt_sfx),
                data.get("sfx_race_volume", alt_sfx),
                data.get("resolution", "1920x1080"),
                data.get("fullscreen", False),
                data.get("fps_limit", 60),
                data.get("vsync", False),
                data.get("texture_quality", "Hoch"),
                data.get("language", "de"),
                data.get("seen_announcements", []),
                data.get("paints", {}),
                data.get("statistik", {}),
                # Fehlt das Feld, ist es ein Profil von vor dieser Aenderung:
                # als versorgt behandeln, sonst wuerde einem bestehenden Spieler
                # die ganze Sammlung nachtraeglich verschluckt (08.08.2026).
                data.get("announcements_seeded", True),
                data.get("grafik"),
            )
        except Exception:
            return cls()

    def save(self) -> None:
        """Profil ablegen — verschlüsselt, signiert, mit Sicherung (E4).

        Ein Klartextprofil von vor der Umstellung wird beim Lesen übernommen und
        hier zum ersten Mal verschlüsselt zurückgeschrieben; einen eigenen
        Migrationsschritt braucht das nicht.
        """
        try:
            from src.core import tresor
            tresor.schreiben(_profile_path(), json.dumps({
                "username": self.username,
                "best_laps": self.best_laps,
                "menu_volume": self.menu_volume,
                "race_volume": self.race_volume,
                "sfx_menu_volume": self.sfx_menu_volume,
                "sfx_race_volume": self.sfx_race_volume,
                "resolution": self.resolution,
                "fullscreen": self.fullscreen,
                "fps_limit": self.fps_limit,
                "vsync": self.vsync,
                "texture_quality": self.texture_quality,
                "language": self.language,
                "seen_announcements": self.seen_announcements,
                "paints": self.paints,
                "statistik": self.statistik,
                "announcements_seeded": self.announcements_seeded,
                "grafik": self.grafik,
            }, indent=2, ensure_ascii=False))
        except Exception:
            pass

    def set_sfx_menu_volume(self, val: float) -> None:
        """Regler "Effekte (Menue)". Wirkt sofort auf den naechsten Klang."""
        self.sfx_menu_volume = max(0.0, min(1.0, val))
        self.save()

    def set_sfx_race_volume(self, val: float) -> None:
        """Regler "Effekte (Rennen)". Wirkt sofort, auch auf laufende
        Motorstimmen - die lesen den Wert je Block neu."""
        self.sfx_race_volume = max(0.0, min(1.0, val))
        self.save()

    def set_menu_volume(self, val: float) -> None:
        self.menu_volume = max(0.0, min(1.0, val))
        self.save()
        from src.core import audio
        if getattr(audio, "_current_track", None) == "menu":
            import pygame
            if pygame.mixer and pygame.mixer.get_init():
                pygame.mixer.music.set_volume(self.menu_volume)

    def set_race_volume(self, val: float) -> None:
        self.race_volume = max(0.0, min(1.0, val))
        self.save()
        from src.core import audio
        if getattr(audio, "_current_track", None) == "race":
            import pygame
            if pygame.mixer and pygame.mixer.get_init():
                pygame.mixer.music.set_volume(self.race_volume)

    def exists(self) -> bool:
        return bool(self.username)

    # -- best laps -------------------------------------------------------
    def record_lap(self, track_key: str, lap_time: float) -> bool:
        """Store *lap_time* if it beats the stored best. Returns True on a record."""
        if lap_time <= 0:
            return False
        prev = self.best_laps.get(track_key)
        if prev is None or lap_time < prev:
            self.best_laps[track_key] = lap_time
            self.save()
            return True
        return False

    def best_lap(self, track_key: str) -> float | None:
        return self.best_laps.get(track_key)

    # -- Lackierungen ----------------------------------------------------
    def paint(self, vehicle_key: str) -> str:
        """Gewaehlte Lackierung eines Fahrzeugs, sonst Werkslack.

        Geht immer durch ``lack.normalisiere``: eine Kennung aus einem neueren
        Build oder eine von Hand verbogene Zeile darf hoechstens Werkslack
        ergeben, nie einen Absturz.
        """
        from src.core import lack
        return lack.normalisiere(self.paints.get(vehicle_key))

    def set_paint(self, vehicle_key: str, kennung: str) -> None:
        """Lackierung waehlen. Werkslack wird ausgetragen statt gespeichert,
        damit ein unveraendertes Profil auch keinen Eintrag mitschleppt."""
        from src.core import lack
        kennung = lack.normalisiere(kennung)
        if kennung == lack.WERK:
            self.paints.pop(vehicle_key, None)
        else:
            self.paints[vehicle_key] = kennung
        self.save()

    def mark_announcement_seen(self, ann_id: str) -> None:
        if ann_id not in self.seen_announcements:
            self.seen_announcements.append(ann_id)
            self.save()

    def seed_seen_announcements(self) -> None:
        """Ein druckfrisches Profil bekommt die Ankündigungen von heute geschenkt
        als "gesehen" (Playtest-Fund 05.08.2026).

        Wer das Spiel gerade zum ersten Mal startet, soll nicht mit der ganzen
        bisherigen Ankündigungssammlung begrüßt werden — nur was DANACH neu
        erscheint, ist für ihn wirklich neu. Die Liste kommt vom Server und
        liegt hier nur vor, wenn sie schon vor dem Aufruf zwischengespeichert
        wurde (``server_info.get_cached``); ein eigener Netzaufruf gehört nicht
        in den Startpfad, der könnte hängen oder scheitern, wenn der Server
        gerade nicht erreichbar ist. Liegt nichts vor, bleibt es einfach beim
        leeren Stand — dann sieht der Erstnutzer eben auch die aktuellen
        Ankündigungen, was kein Fehler ist, nur nicht der Idealfall.

        Ruft nur der Erstanlage-Weg (welcome_state) auf; ein bestehendes Profil
        fasst diese Methode nicht an.
        """
        from src.net import server_info
        info = server_info.get_cached()
        if not info:
            return
        geaendert = False
        for ann in info.get("announcements", []):
            if isinstance(ann, dict) and ann.get("id") and ann["id"] not in self.seen_announcements:
                self.seen_announcements.append(ann["id"])
                geaendert = True
        if geaendert:
            self.save()

    def ensure_announcements_seeded(self, announcements) -> None:
        """Beim allerersten Vorliegen der Ankuendigungsliste alles stumm als
        gesehen verbuchen — eine Neuinstallation begruesst niemanden mit der
        bisherigen Sammlung (08.08.2026).

        ``seed_seen_announcements`` griff nur, wenn die Liste schon zwischenge-
        speichert war; bei einer Neuinstallation ist sie das nie (noch nie
        verbunden), also blieb die Saat aus und der Erstnutzer sah alles. Diese
        Methode holt das nach, sobald die Liste zum ersten Mal wirklich da ist:
        einmal quittieren, ``announcements_seeded`` setzen, fertig. Danach ist es
        ein no-op, und alles NEUE erscheint wieder ganz normal.

        Ein bestehendes Profil hat das Feld bereits auf True (siehe load) und
        laeuft hier sofort ins Leere — ihm wird nichts verschluckt.
        """
        if self.announcements_seeded:
            return
        for ann in announcements:
            if isinstance(ann, dict) and ann.get("id") and ann["id"] not in self.seen_announcements:
                self.seen_announcements.append(ann["id"])
        self.announcements_seeded = True
        self.save()


# ---------------------------------------------------------------------------
# Name validation
# ---------------------------------------------------------------------------
_blacklist_cache: tuple[list[str], list[str]] | None = None


def _load_blacklist() -> tuple[list[str], list[str]]:
    """Die Sperrliste als ``(enthalten, ganzes_wort)``.

    Zwei Gruppen, weil eine allein nicht reicht. Bis zum 07.08.2026 wurde jedes
    Wort als Teilzeichenkette geprueft, und damit waren *Sigmund* (gm),
    *Modena* (mod), *Devin* (dev), *Sussex* (sex) und *Robotex* (bot) gesperrt.
    Solche Fehlalarme wiegen schwer: ein durchgerutschter Name laesst sich
    melden, ein abgewiesener Spieler ist weg.

    Die alte Form — eine schlichte Liste — wird weiter gelesen und wie
    ``enthalten`` behandelt. Ein Spielstand mit einer aelteren Datei soll nicht
    ploetzlich alles erlauben.
    """
    global _blacklist_cache
    if _blacklist_cache is None:
        enthalten: list[str] = []
        ganzes_wort: list[str] = []
        try:
            with open(_BLACKLIST_PATH, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                enthalten = [str(w).lower() for w in data]
            elif isinstance(data, dict):
                enthalten = [str(w).lower()
                             for w in data.get("enthalten", []) if w]
                ganzes_wort = [str(w).lower()
                               for w in data.get("ganzes_wort", []) if w]
        except Exception:
            pass
        _blacklist_cache = (enthalten, ganzes_wort)
    return _blacklist_cache


def _ist_gesperrt(text: str) -> bool:
    """Ob *text* ein verbotenes Wort enthaelt.

    ``ganzes_wort`` trifft nur, wenn links und rechts kein Buchstabe steht.
    Ziffern und Unterstriche zaehlen dabei als Trennung: ``bot99`` und
    ``x_bot`` sind gesperrt, ``Robotex`` nicht — Anhaengsel sind der uebliche
    Weg, eine Sperre zu umgehen, eine Silbe mitten im Wort ist es nicht.
    """
    low = text.lower()
    enthalten, ganzes_wort = _load_blacklist()
    for wort in enthalten:
        if wort in low:
            return True
    for wort in ganzes_wort:
        if re.search(r"(?<![a-zA-Z])%s(?![a-zA-Z])" % re.escape(wort), low):
            return True
    return False


def validate_username(name: str) -> tuple[bool, str]:
    """Return (ok, message). Message is a user-facing reason on failure."""
    from src.core.i18n import tr
    name = name.strip()
    if len(name) < NAME_MIN:
        return False, tr("Mindestens {n} Zeichen.").format(n=NAME_MIN)
    if len(name) > NAME_MAX:
        return False, tr("Höchstens {n} Zeichen.").format(n=NAME_MAX)
    if not _NAME_RE.match(name):
        return False, tr("Nur Buchstaben, Zahlen und Unterstrich.")
    if _ist_gesperrt(name):
        return False, tr("Dieser Name ist nicht erlaubt.")
    return True, ""


#: Streckennamen duerfen mehr als Benutzernamen: Leerzeichen, Bindestriche und
#: Klammern gehoeren zu einem Streckentitel („Alte Muehle (Nacht)").
TRACK_NAME_MAX = 40


def validate_track_name(name: str) -> tuple[bool, str]:
    """Dieselbe Sperrliste fuer Streckennamen. Gibt ``(ok, Grund)``.

    **Warum das noetig ist.** Bis zum 07.08.2026 wurde ein Streckenname nur auf
    unbedenkliche *Zeichen* geprueft (``paths.safe_track_filename``) — gegen
    Pfadangriffe, nicht gegen Inhalte. Ein Titel selbst war voellig frei, und
    eigene Strecken reisen im Online-Rennen **automatisch zu allen
    Mitspielern**. Damit war der Streckenname der einzige Text, den ein Spieler
    Fremden ungefiltert vor die Nase setzen konnte, und ausgerechnet der wurde
    nicht angesehen.
    """
    from src.core.i18n import tr
    name = str(name or "").strip()
    if not name:
        return False, tr("Bitte einen Namen eingeben.")
    if len(name) > TRACK_NAME_MAX:
        return False, tr("Höchstens {n} Zeichen.").format(n=TRACK_NAME_MAX)
    if _ist_gesperrt(name):
        return False, tr("Dieser Name ist nicht erlaubt.")
    return True, ""


# Process-wide current profile (loaded lazily).
_current: Profile | None = None


def current() -> Profile:
    global _current
    if _current is None:
        _current = Profile.load()
    return _current


def set_username(name: str) -> None:
    p = current()
    p.username = name
    p.save()


def namensneuwahl_noetig() -> bool:
    """Ob der gespeicherte Name gegen die **heutige** Sperrliste verstoesst.

    Der Fall aus der Meldung vom 07.08.2026: ein Spieler traegt seinen Namen
    seit Monaten, ein Update verbietet ihn. Geprueft wird beim Start, und die
    Antwort ist eine Neuwahl — **nur** des Namens.

    Ausdruecklich nicht: das Profil verwerfen. Bestzeiten, Statistik,
    Freischaltungen und Lackierungen haengen daran, und wer fuer ein Wort seine
    Erfolge verliert, hoert auf zu spielen. Der Name ist ein Feld unter vielen;
    getauscht wird das Feld, nicht die Datei.

    Nur Laenge und Sperrliste zaehlen. Die Zeichenregel bleibt aussen vor: sie
    koennte sich zwischen zwei Fassungen genauso aendern, und dann stuenden
    Spieler mit einem Namen aus einer aelteren Fassung vor einer Neuwahl,
    obwohl an ihrem Namen nichts anstoessig ist.
    """
    name = (current().username or "").strip()
    if not name:
        return False           # noch gar kein Profil — das ist der erste Start
    if len(name) > NAME_MAX:
        return True
    return _ist_gesperrt(name)
