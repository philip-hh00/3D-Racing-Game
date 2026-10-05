"""Den vollständigen Projektordner auf dem NAS sichern und von dort holen.

    python tools/nas_sync.py sichern            # dieses Projekt aufs NAS
    python tools/nas_sync.py holen              # vollständigen Stand vom NAS holen
    python tools/nas_sync.py sichern --projekt F:\\Fahr-Rennspiel-2D --name 2D-Racing-Game

GitHub bleibt, wie es ist: dort liegt nur der Code (``origin``). Auf dem NAS
liegen pro Projekt drei Dinge unter ``<NAS>/freigabe/Repositories``:

``<Name>.git``
    Spiegel des Code-Repos — dieselbe Historie wie GitHub, alle Zweige.
``<Name>-Daten.git``
    Alles, was das Code-Repo nicht verfolgt: GLBs, Menüvideos, Audio,
    Rohdaten, eigene Strecken … Ein zweites git-Repo, dessen Verzeichnis
    ``.git-daten`` im selben Projektordner liegt. Code-Repo und Daten-Repo
    zusammen ergeben den ganzen Ordner.
``<Name>-Builds/``
    Installer und Zips aus ``Release/ausgabe`` als einfache Kopie. Nicht in
    git: jeder Build hat fast 1 GB, git würde jeden davon für immer behalten.

Nicht gesichert wird, was sich jederzeit neu erzeugen lässt (``.venv``,
``build_tmp``, ``__pycache__`` …), und nichts, was nach Zugangsdaten aussieht
(``*token*``, ``*.pem``, ``id_*``, ``.env``) — die gehören in keine Historie.

Der NAS-Pfad wird erkannt (Windows ``Z:/``, macOS ``/Volumes/NAS-Storage``)
oder mit ``--nas`` angegeben. Eingerichtet am 06.10.2026.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
NAS_KANDIDATEN = ("Z:/", "/Volumes/NAS-Storage")
UNTERORDNER = "freigabe/Repositories"
DATEN_GIT = ".git-daten"

#: Wird nie ins Daten-Repo aufgenommen (gitignore-Syntax).
AUSSCHLUSS = """\
.git-daten/
.venv/
.venv*/
venv/
build_tmp/
build/
dist/
Release/ausgabe/
__pycache__/
*.py[cod]
.pytest_cache/
.claude/
*.log
data/settings/instanz.lock
Thumbs.db
desktop.ini
.DS_Store
*token*
*.pem
*.key
id_rsa*
id_ed25519*
.env
"""


def _git(*args: str, cwd: Path, daten: bool = False, check: bool = True,
         eingabe: bytes | None = None) -> str:
    befehl = ["git"]
    if daten:
        befehl += [f"--git-dir={cwd / DATEN_GIT}", f"--work-tree={cwd}"]
    befehl += list(args)
    erg = subprocess.run(befehl, cwd=cwd, input=eingabe, capture_output=True)
    if check and erg.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} fehlgeschlagen:\n"
                         f"{erg.stderr.decode(errors='replace')}")
    return erg.stdout.decode("utf-8", errors="replace")


def _nas(angabe: str | None) -> Path:
    for kandidat in ([angabe] if angabe else NAS_KANDIDATEN):
        pfad = Path(kandidat) / UNTERORDNER
        if pfad.is_dir():
            return pfad
    raise SystemExit("NAS nicht gefunden — mit --nas den Pfad angeben "
                     "(z. B. Z:/ oder /Volumes/NAS-Storage).")


def _url(pfad: Path) -> str:
    return pfad.as_posix()


def _vertrauen(*repos: Path) -> None:
    """Die Repos auf dem NAS gehören dem NAS-Konto, nicht dem angemeldeten
    Benutzer — git verweigert sie dann („dubious ownership“). Einmalig in der
    globalen Konfiguration freigeben, jedes Repo einzeln: der Platzhalter
    ``<ordner>/*`` greift unter Windows beim Push nicht (gemessen 06.10.2026)."""
    vorhanden = subprocess.run(["git", "config", "--global", "--get-all", "safe.directory"],
                               capture_output=True, text=True).stdout.splitlines()
    for repo in repos:
        eintrag = _url(repo)
        if eintrag not in vorhanden:
            subprocess.run(["git", "config", "--global", "--add", "safe.directory", eintrag],
                           check=True)
            print(f"  git vertraut jetzt {eintrag}")


def _bare_anlegen(pfad: Path) -> None:
    if not pfad.exists():
        subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(pfad)], check=True)
        print(f"  angelegt: {pfad}")


def _daten_vorbereiten(projekt: Path) -> None:
    gitdir = projekt / DATEN_GIT
    if not gitdir.exists():
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(gitdir)], check=True)
        _git("config", "core.bare", "false", cwd=projekt, daten=True)
    _git("config", "core.autocrlf", "false", cwd=projekt, daten=True)
    _git("config", "status.showUntrackedFiles", "no", cwd=projekt, daten=True)
    (gitdir / "info").mkdir(exist_ok=True)
    (gitdir / "info" / "exclude").write_text(AUSSCHLUSS, encoding="utf-8")
    # Assets sind Binärdaten; nichts an ihren Zeilenenden umschreiben.
    (gitdir / "info" / "attributes").write_text("* -text\n", encoding="utf-8")


def sichern(projekt: Path, name: str, nas: Path) -> None:
    print(f"== {name}: sichern nach {nas}")
    code_ziel, daten_ziel = nas / f"{name}.git", nas / f"{name}-Daten.git"
    _bare_anlegen(code_ziel)
    _bare_anlegen(daten_ziel)

    # 1. Code: Spiegel aller Zweige und Tags.
    if "nas" not in _git("remote", cwd=projekt).split():
        _git("remote", "add", "nas", _url(code_ziel), cwd=projekt)
    _git("push", "-q", "nas", "--all", cwd=projekt)
    _git("push", "-q", "nas", "--tags", cwd=projekt)
    print("  Code: gepusht")

    # 2. Daten: alles, was das Code-Repo nicht verfolgt, abzüglich Ausschluss.
    excl = projekt / ".git" / "info" / "exclude"
    if DATEN_GIT not in excl.read_text(encoding="utf-8", errors="replace"):
        with excl.open("a", encoding="utf-8") as f:
            f.write(f"\n{DATEN_GIT}/\n")
    _daten_vorbereiten(projekt)
    ausschluss = projekt / DATEN_GIT / "info" / "exclude"
    liste = _git("ls-files", "-z", "--others", f"--exclude-from={ausschluss}",
                 cwd=projekt)
    if liste:
        _git("add", "-f", "--pathspec-from-file=-", "--pathspec-file-nul",
             cwd=projekt, daten=True, eingabe=liste.encode("utf-8"))
    _git("add", "-u", cwd=projekt, daten=True)
    # Was inzwischen das Code-Repo verfolgt, gehört nicht mehr ins Daten-Repo.
    code = set(_git("ls-files", "-z", cwd=projekt).split("\0"))
    doppelt = [p for p in _git("ls-files", "-z", cwd=projekt, daten=True).split("\0")
               if p and p in code]
    if doppelt:
        _git("rm", "-q", "--cached", "--pathspec-from-file=-", "--pathspec-file-nul",
             cwd=projekt, daten=True, eingabe="\0".join(doppelt).encode("utf-8"))
    if _git("status", "--porcelain", cwd=projekt, daten=True).strip():
        stand = _git("rev-parse", "--short", "HEAD", cwd=projekt).strip()
        _git("commit", "-q", "-m", f"Daten zu Code-Stand {stand}", cwd=projekt, daten=True)
        print("  Daten: neuer Stand")
    else:
        print("  Daten: unverändert")
    zweig = _git("symbolic-ref", "--short", "HEAD", cwd=projekt, daten=True).strip()
    if _git("rev-parse", "--verify", "-q", "HEAD", cwd=projekt, daten=True, check=False).strip():
        _git("push", "-q", _url(daten_ziel), f"{zweig}:main", cwd=projekt, daten=True)
        print("  Daten: gepusht")

    # 3. Builds: neue Dateien kopieren, vorhandene gleicher Größe überspringen.
    ausgabe = projekt / "Release" / "ausgabe"
    if ausgabe.is_dir():
        ziel = nas / f"{name}-Builds"
        ziel.mkdir(exist_ok=True)
        neu = 0
        for datei in sorted(ausgabe.iterdir()):
            if not datei.is_file():
                continue
            kopie = ziel / datei.name
            if kopie.exists() and kopie.stat().st_size == datei.stat().st_size:
                continue
            shutil.copy2(datei, kopie)
            neu += 1
        print(f"  Builds: {neu} neu kopiert")


def holen(projekt: Path, name: str, nas: Path) -> None:
    print(f"== {name}: holen von {nas}")
    code_quelle, daten_quelle = nas / f"{name}.git", nas / f"{name}-Daten.git"
    if not (projekt / ".git").exists():
        projekt.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", "-o", "nas", _url(code_quelle), str(projekt)],
                       check=True)
        print(f"  Code: geklont nach {projekt}")
    else:
        if "nas" not in _git("remote", cwd=projekt).split():
            _git("remote", "add", "nas", _url(code_quelle), cwd=projekt)
        zweig = _git("symbolic-ref", "--short", "HEAD", cwd=projekt).strip()
        _git("pull", "-q", "--ff-only", "nas", zweig, cwd=projekt)
        print("  Code: aktuell")

    excl = projekt / ".git" / "info" / "exclude"
    if DATEN_GIT not in excl.read_text(encoding="utf-8", errors="replace"):
        with excl.open("a", encoding="utf-8") as f:
            f.write(f"\n{DATEN_GIT}/\n")
    neu = not (projekt / DATEN_GIT).exists()
    _daten_vorbereiten(projekt)
    _git("fetch", "-q", _url(daten_quelle), "main:refs/remotes/nas/main",
         cwd=projekt, daten=True)
    if neu:
        # Frischer Ordner: Dateien auspacken, ohne Vorhandenes zu überschreiben.
        _git("branch", "-f", "main", "nas/main", cwd=projekt, daten=True)
        _git("symbolic-ref", "HEAD", "refs/heads/main", cwd=projekt, daten=True)
        _git("read-tree", "main", cwd=projekt, daten=True)
        fehlend = [p for p in _git("ls-files", "-z", cwd=projekt, daten=True).split("\0")
                   if p and not (projekt / p).exists()]
        if fehlend:
            _git("checkout-index", "-z", "--stdin", cwd=projekt, daten=True,
                 eingabe="\0".join(fehlend).encode("utf-8"))
        print(f"  Daten: {len(fehlend)} Dateien ausgepackt")
    else:
        _git("merge", "-q", "--ff-only", "nas/main", cwd=projekt, daten=True)
        print("  Daten: aktuell")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("aktion", choices=("sichern", "holen"))
    ap.add_argument("--projekt", default=str(WURZEL),
                    help="Projektordner (Vorgabe: dieser)")
    ap.add_argument("--name", default="",
                    help="Name auf dem NAS (Vorgabe: Ordnername)")
    ap.add_argument("--nas", default=None, help="Wurzel der NAS-Freigabe")
    args = ap.parse_args()
    projekt = Path(args.projekt).resolve()
    name = args.name or projekt.name
    nas = _nas(args.nas)
    _vertrauen(nas / f"{name}.git", nas / f"{name}-Daten.git")
    (sichern if args.aktion == "sichern" else holen)(projekt, name, nas)
    return 0


if __name__ == "__main__":
    os.environ.setdefault("GIT_TERMINAL_PROMPT", "0")
    sys.exit(main())
