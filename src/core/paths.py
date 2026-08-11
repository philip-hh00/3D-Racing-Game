"""Filesystem locations for reads (bundled assets) vs writes (user data).

Bundled read-only assets live next to the code (resolved via the working
directory, which ``main._fix_cwd`` points at ``sys._MEIPASS`` in a packaged
build). User-writable data (profile, keybindings, crash log) must go somewhere
the user can write even when the app itself is read-only:

* macOS packaged app: ``~/Library/Application Support/2D-Racing-Game`` — the
  ``.app`` in ``/Applications`` is read-only, so writing next to it fails.
* Windows / running from source: the working directory (the per-user install
  folder is writable; a source checkout writes into the repo as before).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "2D-Racing-Game"


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def user_data_dir() -> Path:
    """Base directory for writable user data (created on demand)."""
    if _frozen() and sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path.cwd()
    return base


def user_path(*parts: str) -> str:
    """Absolute path under the writable user-data dir; parent dirs ensured."""
    p = user_data_dir().joinpath(*parts)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return str(p)


def bundle_dir() -> Path:
    """Directory that holds the bundled read-only assets (``_MEIPASS`` in a
    packaged build, the repo root when running from source)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base)
    return Path(__file__).resolve().parents[2]


#: Zeichen, die in einem übernommenen Streckennamen erlaubt sind.
_SAFE_NAME_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-.()[]")
_MAX_NAME_LEN = 80

#: Gerätenamen, die Windows in **jedem** Ordner abfängt: ``C:\x\CON.json`` öffnet
#: die Konsole, nicht eine Datei. Eine geschenkte Strecke mit so einem Namen
#: schreibt damit an einen Treiber statt auf die Platte, und Lesen hängt oder
#: liefert Tastatureingaben (Releaseplan H2.11).
_WIN_GERAETE = {"CON", "PRN", "AUX", "NUL", "CLOCK$"} | {
    f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)}


def safe_track_filename(name: str, fallback: str = "online_track.json") -> str:
    """Dateiname für eine über das Netz empfangene Strecke.

    Der Name kommt von einem anderen Spieler und ist damit nicht
    vertrauenswürdig. Ohne Prüfung schreibt ein Name wie
    ``../../../Startup/x.json`` außerhalb des Streckenordners — mit Inhalt, den
    der Absender bestimmt.

    Deshalb: nur der reine Dateiname, nur unbedenkliche Zeichen, immer mit
    ``.json``. Bleibt nichts Brauchbares übrig, wird *fallback* benutzt.
    """
    roh = str(name or "")
    # Beide Trennzeichen abschneiden: eine Windows-Angabe muss auch unter Linux
    # zerlegt werden und umgekehrt.
    roh = roh.replace("\\", "/").split("/")[-1]
    roh = "".join(c for c in roh if c in _SAFE_NAME_CHARS)
    roh = roh.strip(" .")                      # ".." und Leerraum am Rand
    if not roh:
        return fallback
    if not roh.lower().endswith(".json"):
        roh += ".json"
    if len(roh) > _MAX_NAME_LEN:
        roh = roh[-_MAX_NAME_LEN:].lstrip(" .") or fallback
    # Windows-Gerätenamen abfangen: geprüft wird der Stamm, denn "CON.json"
    # spricht dasselbe Gerät an wie "CON". Ein Unterstrich davor genügt und
    # hält den Namen lesbar.
    stamm = roh[:-5] if roh.lower().endswith(".json") else roh
    if stamm.upper() in _WIN_GERAETE:
        roh = "_" + roh
    return roh


def track_roots() -> list[Path]:
    """Wurzeln, unter denen Strecken liegen können — ohne Doppelte.

    Geschrieben wird ins Nutzerverzeichnis, mitgeliefert kommt aus dem Bundle.
    Aus dem Quellcode gestartet sind beide dasselbe; auf einem gepackten
    macOS-Build nicht, und dort war eine geschenkte Strecke deshalb zwar auf
    der Platte, aber in keiner Liste (Playtest 29.07.2026).
    """
    wurzeln: list[Path] = []
    for w in (user_data_dir(), bundle_dir(), Path.cwd()):
        try:
            aufgeloest = w.resolve()
        except OSError:
            continue
        if aufgeloest not in wurzeln:
            wurzeln.append(aufgeloest)
    return wurzeln


def track_files(unterordner: str) -> list[Path]:
    """Alle Streckendateien in ``data/tracks/<unterordner>`` über alle Wurzeln.

    Nach Dateiname vereinheitlicht: liegt dieselbe Strecke in Bundle und
    Nutzerverzeichnis, gehört sie einmal in die Liste. Das Nutzerverzeichnis
    gewinnt, denn dort landet, was der Spieler selbst hinzugefügt hat.
    """
    gefunden: dict[str, Path] = {}
    for wurzel in track_roots():
        ordner = wurzel / "data" / "tracks" / unterordner
        try:
            if not ordner.is_dir():
                continue
            for p in sorted(ordner.glob("*.json")):
                gefunden.setdefault(p.name, p)
        except OSError:
            continue
    return [gefunden[n] for n in sorted(gefunden)]


#: Die mitgelieferten Strecken, in Anzeigereihenfolge. Nicht alphabetisch: das
#: ist die Reihenfolge, in der sie in der Streckenauswahl stehen, und die kennt
#: der Spieler.
MITGELIEFERT = ("oval", "desert", "city", "mountain", "gp")


def strecken() -> list[tuple[str, Path, bool]]:
    """Jede Strecke, auf der gefahren werden kann: ``(Schlüssel, Pfad, eigen)``.

    Die mitgelieferten zuerst in fester Reihenfolge, dann alles Eigene aus
    ``data/tracks/custom``. Der Schlüssel einer eigenen Strecke trägt das
    Präfix ``custom/``.

    **Eine** Stelle für diese Frage. Die Streckenauswahl hatte sie als eigene
    Methode, und die Profilseite braucht sie seit dem 03.08.2026 auch (Bestzeiten
    für alle Strecken). Zwei Listen wären zwei Wahrheiten darüber, was das Spiel
    überhaupt anbietet — genau die Falle, in die die Menüleiste im Streckeneditor
    schon gelaufen ist.
    """
    eintraege: list[tuple[str, Path, bool]] = [
        (k, Path("data/tracks") / f"{k}.json", False) for k in MITGELIEFERT
    ]
    for p in track_files("custom"):
        eintraege.append((f"custom/{p.stem}", p, True))
    return eintraege


def _name_schon_vergeben(ordner: str, name: str) -> bool:
    """Ob *name* in *ordner* unter **irgendeiner** Wurzel schon liegt.

    Geschrieben wird nur ins Nutzerverzeichnis, gelesen aber ueber alle Wurzeln
    (``track_files``), und dort gewinnt bei Namensgleichheit das
    Nutzerverzeichnis. Wer beim Pruefen nur dorthin sieht, haelt einen Namen
    fuer frei, der in der Liste bereits belegt ist — und die geschenkte Strecke
    verdeckt anschliessend die eigene, statt neben ihr zu stehen.
    """
    teile = ordner.split("/")
    for wurzel in track_roots():
        if os.path.exists(wurzel.joinpath(*teile, name)):
            return True
    return False


def freier_streckenpfad(ordner: str, dateiname: str) -> str:
    """Pfad in *ordner*, der noch keine Datei belegt — sonst mit Nummer.

    Eine geschenkte Strecke darf nichts Eigenes überschreiben: heißt dort
    schon etwas ``Rundkurs.json``, wird daraus ``Rundkurs (2).json``. Bewusst
    eine Nummer und nicht der Name des Absenders — der steht in der Lobby und
    soll nicht dauerhaft im Dateisystem eines anderen Spielers landen.

    „Belegt" heisst ueber **alle** Wurzeln belegt, nicht nur im
    Nutzerverzeichnis (gemeldet 05.08.2026): aus dem Quelltext gestartet fallen
    Bundle und Nutzerverzeichnis zusammen und der Unterschied faellt nie auf,
    im gepackten Build nicht — und genau dort lagen die mitgelieferten
    Strecken.
    """
    name = safe_track_filename(dateiname)
    stamm = name[:-5] if name.lower().endswith(".json") else name
    if not _name_schon_vergeben(ordner, name):
        return user_path(*ordner.split("/"), name)
    for n in range(2, 1000):
        kandidat = f"{stamm} ({n}).json"
        if not _name_schon_vergeben(ordner, kandidat):
            return user_path(*ordner.split("/"), kandidat)
    # Praktisch unerreichbar; lieber überschreiben als gar nicht speichern.
    return user_path(*ordner.split("/"), name)


def find_track(path_or_name: str) -> str | None:
    """Locate a track JSON on this machine, or None.

    Online, the path is dictated by the host and may not exist verbatim here
    (different install dir, custom track from the host's disk). So try the raw
    path first, then the bare filename inside every known track folder.
    """
    if not path_or_name:
        return None
    p = Path(path_or_name)
    cands: list[Path] = [p]
    if not p.is_absolute():
        cands += [Path.cwd() / p, bundle_dir() / p, user_data_dir() / p]
    name = p.name
    for root in (bundle_dir(), Path.cwd(), user_data_dir()):
        cands += [
            root / "data" / "tracks" / name,
            root / "data" / "tracks" / "custom" / name,
            root / "data" / "tracks" / "online" / name,
        ]
    for c in cands:
        try:
            if c.is_file():
                return str(c)
        except OSError:
            continue
    return None
