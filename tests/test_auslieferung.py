"""Was im ausgelieferten Bündel drin sein muss (Block F).

Gefunden am 04.08.2026: ``soundfile`` stand nicht in ``requirements.txt``,
obwohl Block C es seit Ende Juli braucht. Auf dem Entwicklungsrechner fiel das
nicht auf — dort ist es ohnehin installiert. Der macOS-Build legt aber eine
frische Umgebung an und installiert **nur** aus dieser Datei; im gepackten
Bündel fehlte die Bibliothek damit, und der erste Rennstart wäre mit einem
ImportError abgebrochen.

Genau das prüft dieser Test: **jede Fremdbibliothek, die der Spielcode
importiert, muss in requirements.txt stehen.** Der Fehler ist unsichtbar, solange
man aus dem Quelltext startet, und fällt sonst erst dem ersten Spieler auf.
"""
from __future__ import annotations

import ast
import os
import re
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# Seit dem 06.08.2026 liegt alles Release-Bezogene in ``Release/`` und ist dort
# in Unterordner sortiert. Die Pfade stehen hier an einer Stelle, damit ein
# weiterer Umzug nur diese drei Zeilen kostet.
_SPEC_WIN = os.path.join("Release", "pyinstaller", "game.spec")
_SPEC_MAC = os.path.join("Release", "pyinstaller", "game_macos.spec")
_SKRIPT_MAC = os.path.join("Release", "skripte", "build_macos.sh")
_SPECS = [_SPEC_WIN, _SPEC_MAC]

#: Modulname → Name des Pakets in requirements.txt. Beides ist nur selten
#: gleich, und geraten wäre hier ein Fehler mit Ansage.
PAKET = {
    "cv2": "opencv-python",
    "pygame": "pygame-ce",
    "PIL": "pillow",            # nur der Build braucht es, nicht das Spiel
}

#: Was der Spielcode importieren darf, ohne dass es ausgeliefert werden muss.
NUR_WERKZEUG = {"pytest", "PyInstaller"}

#: Bibliotheken, die ein Werkzeug bewusst nur **wenn vorhanden** benutzt.
#:
#: Aufnahmekriterium, damit das hier keine Ausrede wird: der Import steht in
#: einem ``try`` und der Fehlerzweig nennt den Installationsbefehl. Dann ist das
#: Fehlen kein Absturz, sondern eine Ansage — und niemand muss ein
#: Hundert-Megabyte-Paket mitinstallieren, um die Testsuite zu starten.
OPTIONAL = {
    # tools/video_ton_extrahieren.py — bringt ein eigenes ffmpeg mit. Einmalig
    # gebraucht, um den Ton aus einer Videoaufnahme zu ziehen.
    "imageio_ffmpeg",
}


def _versionierte_dateien() -> "set[str] | None":
    """Alle vom Repo verfolgten Pfade, relativ zur Wurzel.

    ``None``, wenn git nicht erreichbar ist — dann wird nicht gefiltert, und
    der Test ist eher zu streng als zu locker.
    """
    import subprocess
    try:
        fertig = subprocess.run(["git", "ls-files"], cwd=_ROOT,
                                capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if fertig.returncode != 0:
        return None
    return {os.path.normpath(z) for z in fertig.stdout.splitlines() if z.strip()}


def _fremdmodule(wurzeln: list[str]) -> dict[str, set[str]]:
    """Alle nicht-Standard-Module, die unter *wurzeln* importiert werden.

    Über den Syntaxbaum, nicht über einen regulären Ausdruck: die
    entscheidenden Importe stehen **in Funktionen** (``sfx.py`` holt
    ``soundfile`` erst beim Laden der Aufnahmen), und genau die hätte ein
    Zeilenmuster am Dateianfang übersehen.
    """
    versioniert = _versionierte_dateien()
    treffer: dict[str, set[str]] = {}
    for wurzel in wurzeln:
        dateien = [wurzel] if wurzel.endswith(".py") else [
            os.path.join(o, n)
            for o, _u, ns in os.walk(wurzel) for n in ns if n.endswith(".py")
        ]
        for pfad in dateien:
            # Nur was im Repo liegt. Seit dem 11.08.2026 steht unter
            # tools/ComfyUI/ eine vollstaendige Fremdanwendung mit rund 40 GB
            # (die Erzeugungsseite der 3D-Modelle, siehe
            # tools/install_trellis2.bat). Sie ist bewusst nicht versioniert,
            # und ihre Abhaengigkeiten sind nicht unsere: torch, comfy,
            # folder_paths und ein halbes Hundert weitere. Ueber "versioniert"
            # statt ueber eine Ausschlussliste, damit die naechste eingerichtete
            # Fremdanwendung nicht dieselbe Aenderung noch einmal braucht.
            if versioniert is not None and os.path.relpath(pfad, _ROOT) not in versioniert:
                continue
            with open(pfad, encoding="utf-8") as fh:
                baum = ast.parse(fh.read(), filename=pfad)
            for knoten in ast.walk(baum):
                if isinstance(knoten, ast.Import):
                    namen = [a.name for a in knoten.names]
                elif isinstance(knoten, ast.ImportFrom):
                    namen = [knoten.module or ""] if knoten.level == 0 else []
                else:
                    continue
                for name in namen:
                    oben = name.split(".")[0]
                    if not oben or oben in sys.stdlib_module_names or oben == "src":
                        continue
                    treffer.setdefault(oben, set()).add(
                        os.path.relpath(pfad, _ROOT))
    return treffer


def _requirements(datei: str = "requirements.txt") -> set[str]:
    pfad = os.path.join(_ROOT, datei)
    if not os.path.isfile(pfad):
        return set()
    with open(pfad, encoding="utf-8") as fh:
        zeilen = [z.strip() for z in fh if z.strip() and not z.startswith("#")]
    return {re.split(r"[<>=!\[ ]", z)[0].strip().lower() for z in zeilen}


# ---------------------------------------------------------------------------
# Abhängigkeiten
# ---------------------------------------------------------------------------
def test_jede_bibliothek_des_spiels_steht_in_requirements():
    """Der Fund vom 04.08.2026, als Test.

    Geprüft wird ``src/`` **und** ``main.py`` — Werkzeuge unter ``tools/`` sind
    ausdrücklich nicht dabei, die laufen nur auf dem Entwicklungsrechner.
    """
    gefunden = _fremdmodule([os.path.join(_ROOT, "src"), os.path.join(_ROOT, "main.py")])
    erlaubt = _requirements()
    fehlen = {}
    for modul, dateien in gefunden.items():
        if modul in NUR_WERKZEUG:
            continue
        paket = PAKET.get(modul, modul).lower()
        if paket not in erlaubt:
            fehlen[modul] = (paket, sorted(dateien)[:3])
    assert not fehlen, (
        "nicht in requirements.txt: "
        + "; ".join(f"{m} (Paket {p}, u.a. {d})" for m, (p, d) in fehlen.items()))


def test_jede_bibliothek_der_werkzeuge_und_tests_ist_irgendwo_notiert():
    """Die Kehrseite des Tests darüber, gefunden am 06.08.2026.

    Für ``src/`` galt die Regel schon; für ``tools/`` und ``tests/`` galt sie
    nicht — und dort ist sie genauso nötig, nur aus einem anderen Grund. Nicht
    weil ein Spieler stolpert, sondern weil die **Pipeline** stolpert: sie
    installiert auf einem frischen Rechner nur, was in den Anforderungsdateien
    steht.

    Passiert ist genau das. ``tools/motor_import.py`` importiert ``scipy`` auf
    Modulebene, ``tests/test_motor_import.py`` importiert dieses Werkzeug, und
    auf dem Bauknecht gab es kein scipy. Der Lauf brach schon beim **Einsammeln**
    der Tests ab — ein einziges fehlendes Paket, und keine einzige der 1854
    Prüfungen lief.

    Erlaubt sind beide Dateien: was das Spiel braucht, steht in
    ``requirements.txt``, was nur zum Entwickeln nötig ist, in
    ``requirements-dev.txt``. Verboten ist nur, dass es nirgends steht.
    """
    gefunden = _fremdmodule([os.path.join(_ROOT, "tools"),
                             os.path.join(_ROOT, "tests")])
    erlaubt = _requirements() | _requirements("requirements-dev.txt")
    # Eigene Module und Ordner werden per sys.path importiert und sind keine
    # Fremdbibliotheken.
    eigen = {"src", "tools", "tests", "server"} | {
        os.path.splitext(n)[0]
        for o in ("tools", "tests")
        for n in os.listdir(os.path.join(_ROOT, o)) if n.endswith(".py")}
    fehlen = {}
    for modul, dateien in gefunden.items():
        if modul in eigen or modul in OPTIONAL:
            continue
        paket = PAKET.get(modul, modul).lower()
        if paket not in erlaubt:
            fehlen[modul] = (paket, sorted(dateien)[:3])
    assert not fehlen, (
        "weder in requirements.txt noch in requirements-dev.txt: "
        + "; ".join(f"{m} (Paket {p}, u.a. {d})" for m, (p, d) in fehlen.items()))


def test_scipy_gehoert_nicht_ins_spiel():
    """Namentlich, weil hier eine Grenze verläuft, die leicht verwischt.

    Der bequeme Weg wäre gewesen, scipy einfach in ``requirements.txt`` zu
    schreiben. Dann wäre es im ausgelieferten Bündel gelandet — für eine
    Bibliothek, die nur fünf Werkzeuge auf dem Entwicklungsrechner benutzen.
    """
    assert "scipy" not in _requirements(), \
        "scipy gehoert in requirements-dev.txt, nicht ins Spiel"
    assert "scipy" in _requirements("requirements-dev.txt")
    gefunden = _fremdmodule([os.path.join(_ROOT, "src"),
                             os.path.join(_ROOT, "main.py")])
    assert "scipy" not in gefunden, \
        f"der Spielcode importiert scipy: {sorted(gefunden['scipy'])}"


def test_die_pipeline_installiert_beide_anforderungsdateien():
    """Sonst steht die Trennung nur auf dem Papier."""
    with open(os.path.join(_ROOT, ".github", "workflows", "tests.yml"),
              encoding="utf-8") as fh:
        ablauf = fh.read()
    assert "requirements.txt" in ablauf
    assert "requirements-dev.txt" in ablauf


def test_soundfile_ist_dabei():
    """Namentlich, weil genau das gefehlt hat — ein allgemeiner Test lässt sich
    versehentlich abschwächen, dieser nicht."""
    assert "soundfile" in _requirements()


def test_requirements_enthaelt_nichts_ueberfluessiges():
    """Eine Zeile, die niemand importiert, wandert bei jedem Build mit ins
    Bündel. Bekannte Ausnahme: keine."""
    gefunden = {PAKET.get(m, m).lower()
                for m in _fremdmodule([os.path.join(_ROOT, "src"),
                                       os.path.join(_ROOT, "main.py")])}
    unbenutzt = _requirements() - gefunden
    assert not unbenutzt, f"in requirements, aber nirgends importiert: {unbenutzt}"


# ---------------------------------------------------------------------------
# Ohne die Bibliothek muss es weiterlaufen
# ---------------------------------------------------------------------------
def test_ohne_soundfile_bleibt_der_motor_still_statt_abzustuerzen(monkeypatch):
    """Der stille Weg war gebaut (``Rennklang._stimme_fuer``: „lieber still als
    verzerrt"), wurde aber nie erreicht — der ImportError flog durch bis zum
    ersten Rennstart und beendete das Spiel."""
    import builtins
    from src.core import sfx

    echt = builtins.__import__

    def ohne(name, *a, **k):
        if name == "soundfile":
            raise ImportError("No module named 'soundfile'")
        return echt(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", ohne)
    monkeypatch.setattr(sfx, "_schichten_cache", {})
    stimme = sfx.Motorstimme("4zyl")          # darf nicht werfen
    assert not stimme, "ohne Aufnahmen ist die Stimme leer"
    assert not sfx.schichten("4zyl")


def test_eine_stimme_ohne_aufnahmen_liefert_stille():
    from src.core import sfx
    leer = sfx.Motorstimme("gibtsnicht")
    assert not leer
    block = leer.block(3000.0)
    assert len(block) == leer.blocklaenge
    assert not block.any(), "eine leere Stimme muss Stille liefern"


# ---------------------------------------------------------------------------
# Was in die Bündel gehört
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("spec", _SPECS)
def test_die_spec_nennt_soundfile(spec):
    """Damit PyInstaller den Hook zieht, der libsndfile mitnimmt.

    Nachgeprüft am 04.08.2026 mit einem echten Bau: im Bündel liegt
    ``_internal/_soundfile_data/libsndfile*.so``, das Modul selbst im Archiv.
    ``collect_data_files``/``collect_dynamic_libs`` von Hand aufzurufen bringt
    dagegen **nichts** — soundfile ist eine einzelne Moduldatei und kein Paket,
    beide kommen leer zurück. Ein Aufruf, der wie Absicherung aussieht und keine
    ist, ist schlimmer als keiner.
    """
    quelle = open(os.path.join(_ROOT, spec), encoding="utf-8").read()
    assert "'soundfile'" in quelle
    for scheinbar in ("collect_data_files('soundfile')",
                      "collect_dynamic_libs('soundfile')"):
        assert scheinbar not in quelle, f"{scheinbar} kommt leer zurueck"


@pytest.mark.parametrize("spec", _SPECS)
def test_unfertige_streckenentwuerfe_werden_nicht_ausgeliefert(spec):
    """``data/tracks/drafts`` sind Entwürfe im Editor, kein Spielinhalt."""
    quelle = open(os.path.join(_ROOT, spec), encoding="utf-8").read()
    assert "data/tracks/drafts" not in quelle
    assert "('data/tracks'," not in quelle, "der ganze Ordner nimmt drafts mit"
    assert "data/tracks/*.json" in quelle


@pytest.mark.parametrize("spec", _SPECS)
def test_das_eigene_profil_wird_nicht_ausgeliefert(spec):
    """Es steht im Repo und enthält Benutzername und Bestzeiten. Im Bündel wäre
    es das Startprofil jedes Spielers."""
    quelle = open(os.path.join(_ROOT, spec), encoding="utf-8").read()
    assert "profile.json" not in quelle


def test_die_mac_app_meldet_die_version_aus_version_py():
    """Im info_plist stand '0.1.0', während das Spiel 0.6.0-beta meldete. macOS
    zeigt diesen Wert im Finder — zwei Versionen sind schlimmer als eine."""
    quelle = open(os.path.join(_ROOT, _SPEC_MAC), encoding="utf-8").read()
    assert "'CFBundleShortVersionString': _version" in quelle
    # Seit dem 07.08.2026 wird der Pfad ueber SPECPATH verankert und steht
    # deshalb nicht mehr woertlich da. Geprueft wird die Absicht statt der
    # Schreibweise: die Nummer kommt aus version.py und ist nicht getippt.
    assert "version.py" in quelle
    assert "_version = _mod.VERSION" in quelle


# ---------------------------------------------------------------------------
# Das Build-Skript
# ---------------------------------------------------------------------------
def test_das_mac_skript_haengt_nicht_an_activate():
    """Gemeldet am 04.08.2026: „line 47: .venv-build/bin/activate: No such file
    or directory". Geprüft wurde nur, ob das *Verzeichnis* existiert — eine
    halb angelegte Umgebung ließ das source scheitern."""
    quelle = open(os.path.join(_ROOT, _SKRIPT_MAC), encoding="utf-8").read()
    befehle = [z for z in quelle.splitlines() if not z.strip().startswith("#")]
    assert not any("source " in z or z.strip().startswith(". ") for z in befehle)
    assert 'VPY="$VENV/bin/python"' in quelle
    assert 'if [ ! -x "$VPY" ]' in quelle


def test_das_mac_skript_benutzt_nur_den_interpreter_der_umgebung():
    """Ein blankes ``python`` traf ohne activate den Systeminterpreter — und
    damit eine Umgebung ohne die eben installierten Pakete."""
    quelle = open(os.path.join(_ROOT, _SKRIPT_MAC), encoding="utf-8").read()
    for zeile in quelle.splitlines():
        nackt = zeile.strip()
        if nackt.startswith("#") or not nackt:
            continue
        assert not re.match(r"^python[ 3]", nackt), zeile
        assert " python -m " not in nackt, zeile


# ---------------------------------------------------------------------------
# Schreiben im gepackten Bündel (macOS ist read-only)
# ---------------------------------------------------------------------------
def _als_gepacktes_bundle(monkeypatch, tmp_path):
    """``main._fix_cwd`` wechselt im Bündel nach ``sys._MEIPASS`` — und das liegt
    im ``.app``, das nach der Installation schreibgeschützt ist."""
    from src.core import paths
    bundle = tmp_path / "2D-Racing-Game.app" / "Contents" / "Resources"
    bundle.mkdir(parents=True)
    nutzer = tmp_path / "Application Support" / "2D-Racing-Game"
    nutzer.mkdir(parents=True)
    monkeypatch.chdir(bundle)
    monkeypatch.setattr(paths, "user_data_dir", lambda: nutzer)
    bundle.chmod(0o555)
    return bundle, nutzer


def test_ghosts_landen_im_nutzerverzeichnis_nicht_im_buendel(monkeypatch, tmp_path):
    """Vorher schlug ``save`` im Bündel fehl und verschluckte den Fehler — eine
    gefahrene Bestrunde wurde nie als Ghost gespeichert, und niemand merkte es."""
    from src.core import ghost
    _bundle, nutzer = _als_gepacktes_bundle(monkeypatch, tmp_path)
    daten = ghost.GhostData(samples=[[0.0, 1.0, 2.0, 0.0]], lap_time=12.34,
                            sectors=[12.34], driver="Tester", vehicle="rookie")
    ghost.save("oval", daten)
    assert (nutzer / "data" / "ghosts" / "oval.json").is_file()
    wieder = ghost.load("oval")
    assert wieder is not None and wieder.lap_time == pytest.approx(12.34)


def test_der_streckeneditor_kann_im_buendel_speichern(monkeypatch, tmp_path):
    """Der Editor ist eine Hauptfunktion. Im gepackten .app schrieb er ins
    schreibgeschützte Bündel."""
    from src.track import tile_track
    _bundle, nutzer = _als_gepacktes_bundle(monkeypatch, tmp_path)
    assert str(nutzer) in tile_track.draft_dir()
    assert str(nutzer) in tile_track.custom_dir()
    os.makedirs(tile_track.draft_dir(), exist_ok=True)
    with open(os.path.join(tile_track.draft_dir(), "probe.json"), "w") as fh:
        fh.write("{}")          # muss gehen, ohne PermissionError


def test_kein_schreibpfad_im_spielcode_ist_relativ():
    """Die Regel hinter beiden Funden: was geschrieben wird, geht über
    ``paths.user_path``. Ein relativer Pfad ist im gepackten macOS-Bündel ein
    Schreibversuch in das ``.app``."""
    verdacht = []
    for ordner, _u, namen in os.walk(os.path.join(_ROOT, "src")):
        for name in namen:
            if not name.endswith(".py"):
                continue
            pfad = os.path.join(ordner, name)
            quelle = open(pfad, encoding="utf-8").read()
            for treffer in re.finditer(r"os\.makedirs\(([^)]*)\)", quelle):
                arg = treffer.group(1).split(",")[0].strip()
                # Ein Literal wie os.path.join("data", ...) waere relativ.
                if arg.startswith('os.path.join("') or arg.startswith("'data"):
                    verdacht.append(f"{os.path.relpath(pfad, _ROOT)}: {arg}")
    assert not verdacht, "schreibt relativ statt über user_path: " + "; ".join(verdacht)


@pytest.mark.parametrize("spec", _SPECS)
def test_eigene_strecken_und_ghosts_werden_nicht_ausgeliefert(spec):
    """Entschieden am 04.08.2026. Die drei eigenen Strecken bleiben lokal —
    „mitgeliefert" soll heißen, dass eine Strecke abgestimmt ist. Und die eigenen
    Ghost-Runden bleiben es auch: sonst fährt jeder neue Spieler im Zeitfahren
    gegen eine fremde Zeit mit fremdem Namen, und der Erfolg „eigenen Ghost
    geschlagen" wäre falsch."""
    quelle = open(os.path.join(_ROOT, spec), encoding="utf-8").read()
    assert "data/tracks/custom" not in quelle
    assert "data/ghosts" not in quelle


# ---------------------------------------------------------------------------
# Ein Build-Lauf darf den Arbeitsbaum nicht schmutzig machen (05.08.2026)
# ---------------------------------------------------------------------------
# Gemeldet: „Diese muss ich jedes mal wenn ich neu pullen will restoren damit
# der pull durchgeht. Dabei ändere ich nichts an der Datei sondern führe diese
# nur aus um den Release zu erzeugen."

def _versioniert(pfad: str) -> bool:
    """Ob *pfad* in der Versionsverwaltung liegt."""
    import subprocess
    fertig = subprocess.run(["git", "ls-files", "--", pfad],
                            cwd=_ROOT, capture_output=True, text=True)
    return bool(fertig.stdout.strip())


def _ignoriert(pfad: str) -> bool:
    import subprocess
    return subprocess.run(["git", "check-ignore", "-q", "--", pfad],
                          cwd=_ROOT).returncode == 0


#: Was ``Release/skripte/build_macos.sh`` beim Laufen anlegt oder überschreibt.
#: Nichts davon darf versioniert sein — sonst meldet git nach jedem Build
#: Änderungen, und der nächste Pull scheitert daran.
BUILD_SCHREIBT = [".venv-build/pyvenv.cfg", ".venv-build/bin/python",
                  "build_tmp/x", "Release/ausgabe/x"]


@pytest.mark.parametrize("pfad", BUILD_SCHREIBT)
def test_was_der_build_schreibt_ist_nicht_versioniert(pfad):
    assert not _versioniert(pfad), (
        f"{pfad} liegt im Repo. Ein Build-Lauf schreibt es um, und danach geht "
        f"kein Pull mehr durch, ohne vorher zu restoren.")


@pytest.mark.parametrize("pfad", BUILD_SCHREIBT)
def test_was_der_build_schreibt_wird_ignoriert(pfad):
    """Nicht versioniert genügt nicht — sonst steht es als unversionierte Datei
    im Status und geht beim nächsten ``git add -A`` wieder mit hinein."""
    assert _ignoriert(pfad), f"{pfad} fehlt in .gitignore"


#: Was das **Spiel** im Betrieb schreibt. Dieselbe Regel wie oben, nur die
#: andere Quelle — und die Lücke, durch die es am 06.08.2026 doch passiert ist:
#: geprüft war bis dahin nur, was der Build anlegt.
SPIEL_SCHREIBT = [
    # Die Instanzsperre. Wird bei **jedem** Start angefasst.
    "data/settings/instanz.lock",
    # Mitschnitte des Rennklangs — Messdaten, und eine Aufnahme wog 11,6 MB.
    "data/settings/klangmitschnitt/2026-01-01_000000.wav",
    # Das eigene Profil samt Sicherung und Zwischendatei (E4). Das Profil lag
    # bis zum 06.08.2026 im Repo und wurde bei jeder Einstellungsaenderung
    # umgeschrieben — dieselbe Falle, nur langsamer.
    "data/settings/profile.json",
    "data/settings/profile.bak",
    "data/settings/profile.json.tmp",
]


@pytest.mark.parametrize("pfad", SPIEL_SCHREIBT)
def test_was_das_spiel_schreibt_ist_nicht_versioniert(pfad):
    """Sonst macht jeder Spielstart den Arbeitsbaum schmutzig, und der nächste
    Pull scheitert daran — dieselbe Falle wie `.venv-build/`, nur aus dem
    laufenden Spiel statt aus dem Build."""
    assert not _versioniert(pfad), (
        f"{pfad} liegt im Repo. Das Spiel schreibt es im Betrieb um.")


@pytest.mark.parametrize("pfad", SPIEL_SCHREIBT)
def test_was_das_spiel_schreibt_wird_ignoriert(pfad):
    assert _ignoriert(pfad), f"{pfad} fehlt in .gitignore"


def test_kein_mitschnitt_liegt_im_repo():
    """Nicht nur die Beispieldatei oben: der ganze Ordner. Ein Mitschnitt ist
    Messdaten und wiegt zweistellige Megabyte."""
    import subprocess
    fertig = subprocess.run(["git", "ls-files", "--", "data/settings/klangmitschnitt"],
                            cwd=_ROOT, capture_output=True, text=True)
    assert fertig.stdout.strip() == "", fertig.stdout


def test_die_build_umgebung_ist_vollstaendig_draussen():
    """Die ganze Umgebung, nicht nur die zwei Beispieldateien oben.

    Sie lag mit 23 Dateien im Repo — darunter `pyvenv.cfg` und die
    activate-Skripte mit dem absoluten Pfad des Rechners, auf dem sie entstand,
    und `bin/python` als Symlink auf ein dort installiertes Python. Auf keinem
    anderen Rechner war das je benutzbar.
    """
    import subprocess
    fertig = subprocess.run(["git", "ls-files", "--", ".venv-build"],
                            cwd=_ROOT, capture_output=True, text=True)
    assert fertig.stdout.strip() == "", fertig.stdout


def test_das_skript_legt_die_umgebung_selbst_an():
    """Der Grund, warum sie nicht ins Repo gehört: sie entsteht beim Bauen."""
    quelle = open(os.path.join(_ROOT, _SKRIPT_MAC), encoding="utf-8").read()
    assert '"$PY" -m venv "$VENV"' in quelle
