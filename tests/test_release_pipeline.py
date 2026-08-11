"""Die Bauanleitung muss zu den Dateien passen, die es gibt (06.08.2026).

Am 06.08.2026 sind alle Release-Dateien nach ``Release/`` umgezogen und in
Unterordner sortiert worden. Jeder dieser Pfade steht danach an **zwei** Stellen:
im Skript, das ihn aufruft, und im Ablauf der Pipeline. Ein Tippfehler darin
faellt nicht beim Bauen auf, sondern erst, wenn ein Release erzeugt werden soll
— also im schlechtesten Moment.

Die Tests hier lesen deshalb die Skripte und Ablaufdateien als Text und pruefen,
dass die Pfade darin wirklich existieren. Sie bauen nichts: PyInstaller und Inno
Setup laufen hier nicht, das kann nur die Pipeline selbst. Geprueft wird die
Verkabelung, nicht das Ergebnis.

Dazu die Bauzeit. ``version.BUILD_DATE`` stand bis heute auf ``date.today()``
und wurde damit beim **Start** ausgerechnet — bei einem gepackten Build auf dem
Rechner des Spielers. Seit es Testbuilds gibt, die dieselbe Version tragen und
sich nur in der Bauzeit unterscheiden, ist das die einzige Stelle, an der zwei
Staende auseinanderzuhalten sind.
"""
from __future__ import annotations

import json
import os
import re
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def _lies(*teile: str) -> str:
    with open(os.path.join(_ROOT, *teile), encoding="utf-8") as fh:
        return fh.read()


def _da(*teile: str) -> bool:
    return os.path.exists(os.path.join(_ROOT, *teile))


# ── Der Umzug nach Release/ ───────────────────────────────────────────────────

@pytest.mark.parametrize("pfad", [
    ("Release", "skripte", "build_windows.bat"),
    ("Release", "skripte", "build_macos.sh"),
    ("Release", "skripte", "release_starten.bat"),
    ("Release", "skripte", "release_starten.sh"),
    ("Release", "pyinstaller", "game.spec"),
    ("Release", "pyinstaller", "game_macos.spec"),
    ("Release", "installer", "installer.iss"),
])
def test_jede_release_datei_liegt_an_ihrem_platz(pfad):
    assert _da(*pfad), f"{'/'.join(pfad)} fehlt"


def test_im_wurzelverzeichnis_liegt_nichts_mehr_davon():
    """Sonst gibt es zwei Fassungen und niemand weiß, welche gilt."""
    alt = ["build_release.bat", "build_release_macos.sh",
           "game.spec", "game_macos.spec", "installer.iss"]
    liegen_geblieben = [n for n in alt if _da(n)]
    assert not liegen_geblieben, f"noch im Wurzelverzeichnis: {liegen_geblieben}"


def test_die_skripte_wechseln_ins_wurzelverzeichnis():
    """Sie liegen zwei Ebenen tief, arbeiten aber mit Pfaden ab der Wurzel
    (``data/…``, ``src/…``). Ohne den Wechsel greift jeder davon ins Leere."""
    assert 'cd /d "%~dp0..\\.."' in _lies("Release", "skripte", "build_windows.bat")
    assert 'cd "$(dirname "$0")/../.."' in _lies("Release", "skripte", "build_macos.sh")
    assert 'cd /d "%~dp0..\\.."' in _lies("Release", "skripte", "release_starten.bat")
    assert 'cd "$(dirname "$0")/../.."' in _lies("Release", "skripte", "release_starten.sh")


@pytest.mark.parametrize("skript,muster", [
    (("Release", "skripte", "build_windows.bat"),
     r"PyInstaller\s+(Release\\pyinstaller\\game\.spec)"),
    (("Release", "skripte", "build_macos.sh"),
     r"PyInstaller\s+(Release/pyinstaller/game_macos\.spec)"),
])
def test_die_skripte_zeigen_auf_vorhandene_spezifikationen(skript, muster):
    treffer = re.search(muster, _lies(*skript))
    assert treffer, f"kein PyInstaller-Aufruf in {'/'.join(skript)}"
    pfad = treffer.group(1).replace("\\", "/")
    assert _da(*pfad.split("/")), f"{pfad} gibt es nicht"


def test_der_windows_build_zeigt_auf_den_installer():
    quelle = _lies("Release", "skripte", "build_windows.bat")
    treffer = re.search(r"(Release\\installer\\installer\.iss)", quelle)
    assert treffer, "kein Installer-Aufruf gefunden"
    assert _da(*treffer.group(1).replace("\\", "/").split("/"))


def test_beide_skripte_legen_im_selben_ausgabeordner_ab():
    """Sonst sucht die Pipeline die Pakete an der falschen Stelle."""
    assert "Release\\ausgabe" in _lies("Release", "skripte", "build_windows.bat")
    assert 'OUT="Release/ausgabe"' in _lies("Release", "skripte", "build_macos.sh")


def test_der_ausgabeordner_ist_nicht_versioniert_die_anleitung_schon():
    """Release/ ist beides: Bauanleitung und Gebautes. Wird wieder der ganze
    Ordner ignoriert, verschwinden die Skripte lautlos aus dem Repo."""
    ignore = _lies(".gitignore")
    assert "/Release/ausgabe/" in ignore
    assert re.search(r"^/Release/\s*$", ignore, re.M) is None, \
        "Release/ wird pauschal ignoriert — dann sind die Skripte darin unsichtbar"


# ── Die Spezifikationen, ausgeführt wie PyInstaller es tut ───────────────────
#
# Der Fehler vom 07.08.2026:
#
#     ERROR: script '...\\Release\\pyinstaller\\main.py' not found
#
# **PyInstaller löst Pfade in einer .spec gegen das Verzeichnis der Spec-Datei
# auf** (``SPECPATH``), nicht gegen das Arbeitsverzeichnis. Solange die Specs im
# Wurzelverzeichnis lagen, war das dasselbe. Seit dem Umzug nach
# ``Release/pyinstaller/`` zeigte jeder relative Pfad zwei Ebenen zu tief — und
# das ``cd`` in den Bauskripten half nicht, weil es nicht das
# Arbeitsverzeichnis ist, das zählt.
#
# Ein Test, der nur den Text durchsieht, hätte das nicht gefunden. Deshalb wird
# die Spec hier **ausgeführt**, mit ``SPECPATH`` wie im Ernstfall und mit
# Attrappen für ``Analysis`` und die übrigen Bausteine. Danach lässt sich
# nachsehen, ob jeder Pfad, den sie angibt, wirklich existiert.


class _Fang:
    """Attrappe für ``Analysis`` und die übrigen Bausteine.

    Sie schreibt mit, womit sie gerufen wurde, und beantwortet jeden weiteren
    Zugriff mit sich selbst — die Spec greift auf Zwischenergebnisse zu
    (``a.pure``, ``a.binaries``), und die gibt es hier nicht.
    """

    def __init__(self, protokoll=None):
        self.protokoll = protokoll if protokoll is not None else []

    def __call__(self, *a, **kw):
        self.protokoll.append((a, kw))
        return _Fang(self.protokoll)

    def __getattr__(self, name):
        return _Fang(self.protokoll)

    def __iter__(self):
        return iter(())


def _spec_ausfuehren(name: str) -> tuple[list, dict]:
    """Die Spec ausführen wie PyInstaller. Gibt (Aufrufe, Namensraum) zurück."""
    pfad = os.path.join(_ROOT, "Release", "pyinstaller", name)
    fang = _Fang()
    raum = {
        "SPECPATH": os.path.dirname(pfad),
        "DISTPATH": os.path.join(_ROOT, "build_tmp", "stage"),
        "workpath": os.path.join(_ROOT, "build_tmp"),
        "Analysis": fang, "PYZ": fang, "EXE": fang, "COLLECT": fang,
        "BUNDLE": fang, "Tree": fang, "TOC": fang, "Splash": fang,
        "__file__": pfad, "__name__": "__main__",
    }
    with open(pfad, encoding="utf-8") as fh:
        exec(compile(fh.read(), pfad, "exec"), raum)   # noqa: S102
    return fang.protokoll, raum


@pytest.mark.parametrize("name", ["game.spec", "game_macos.spec"])
def test_die_spec_findet_ihr_hauptskript(name):
    """Der gemeldete Fehler, wörtlich. ``main.py`` liegt im Wurzelverzeichnis,
    die Spec zwei Ebenen tiefer."""
    aufrufe, _raum = _spec_ausfuehren(name)
    skripte = aufrufe[0][0][0]
    assert skripte, f"{name} nennt kein Skript"
    for s in skripte:
        assert os.path.isfile(s), f"{name}: Skript nicht gefunden: {s}"


@pytest.mark.parametrize("name", ["game.spec", "game_macos.spec"])
def test_jede_quelle_der_spec_gibt_es_wirklich(name):
    """Dasselbe für alles, was mit ins Bündel soll. Ein Pfad, der ins Leere
    zeigt, ist entweder ein Abbruch oder — schlimmer — eine still fehlende
    Datei im ausgelieferten Spiel."""
    import glob
    aufrufe, _raum = _spec_ausfuehren(name)
    datas = aufrufe[0][1]["datas"]
    fehlen = []
    for quelle, _ziel in datas:
        # Die Bauzeit entsteht erst beim Packen (tools/baustempel.py).
        if quelle.endswith("build_stamp.json"):
            continue
        if not (os.path.exists(quelle) or glob.glob(quelle)):
            fehlen.append(quelle)
    assert not fehlen, f"{name}: diese Quellen gibt es nicht: {fehlen}"


@pytest.mark.parametrize("name", ["game.spec", "game_macos.spec"])
def test_die_spec_haengt_nicht_am_arbeitsverzeichnis(name):
    """Der Kern der Sache: sie muss über ``SPECPATH`` gehen.

    Gegenprobe von einem anderen Arbeitsverzeichnis aus — genau so läuft sie
    auf dem Bauknecht, wenn jemand das ``cd`` im Skript für ausreichend hält.
    """
    alt = os.getcwd()
    try:
        os.chdir(os.path.dirname(_ROOT))
        aufrufe, _raum = _spec_ausfuehren(name)
        assert os.path.isfile(aufrufe[0][0][0][0])
    finally:
        os.chdir(alt)


def test_die_spec_liest_die_version_aus_version_py():
    """Die macOS-Spec zeigt die Version im Finder. Zeigt der Pfad ins Leere,
    bricht sie nicht ab, sondern trägt eine falsche Nummer ein."""
    _aufrufe, raum = _spec_ausfuehren("game_macos.spec")
    from src.core import version
    assert raum["_version"] == version.VERSION


# ── Die Werkzeuge, ohne Verlass auf das Arbeitsverzeichnis ───────────────────

@pytest.mark.parametrize("skript", ["build_windows.bat", "release_starten.bat",
                                    "build_macos.sh"])
def test_die_werkzeuge_werden_ueber_ihren_pfad_gerufen(skript):
    """``-m tools.x`` hängt daran, dass Python das Arbeitsverzeichnis in den
    Suchpfad legt. Mit ``PYTHONSAFEPATH`` in der Umgebung tut es das **nicht**,
    und dann kommt „No module named 'tools'" (gemeldet 07.08.2026)."""
    quelle = _lies("Release", "skripte", skript)
    assert "-m tools." not in quelle, "haengt am Arbeitsverzeichnis"


def test_die_werkzeuge_laufen_auch_mit_abgeschaltetem_pfad():
    """Die Gegenprobe, ausgeführt: ``-P`` schaltet genau das ab, was gefehlt
    hat. Über den Dateipfad muss es trotzdem gehen."""
    import subprocess
    aus = subprocess.run([sys.executable, "-P", "tools/version_ausgeben.py"],
                         cwd=_ROOT, capture_output=True, text=True, timeout=60)
    assert aus.returncode == 0, aus.stderr
    from src.core import version
    assert aus.stdout.strip() == version.VERSION


# ── Der Installer, und dieselbe Pfadfalle zum dritten Mal ────────────────────
#
# Gemeldet 07.08.2026:
#   Error on line 30 in ...\\Release\\installer\\installer.iss:
#   The system cannot find the path specified.
#
# Zeile 30 war ``SetupIconFile=data\\icon.ico``. Inno Setup löst relative Pfade
# gegen das Verzeichnis der ``.iss``-Datei auf — genau wie PyInstaller bei den
# Specs, und genau wie dort beim Umzug übersehen. Es wäre nicht bei Zeile 30
# geblieben: ``Source: "{#SourceDir}\\*"`` hätte als nächstes zugeschlagen.

def test_der_installer_verankert_seine_pfade():
    """Alles, was im Repo liegt, muss über ``{#Wurzel}`` gehen."""
    quelle = _lies("Release", "installer", "installer.iss")
    assert "#define Wurzel SourcePath" in quelle
    treffer = re.search(r"^SetupIconFile=(.+)$", quelle, re.M)
    assert treffer, "kein SetupIconFile"
    assert treffer.group(1).startswith("{#Wurzel}"), \
        f"nicht verankert: {treffer.group(1)}"


def test_das_symbol_des_installers_gibt_es_wirklich():
    """Der gemeldete Fehler, am Ende aufgelöst wie Inno es tut."""
    quelle = _lies("Release", "installer", "installer.iss")
    rest = re.search(r"^SetupIconFile=\{#Wurzel\}(.+)$", quelle, re.M).group(1)
    assert _da(*rest.replace("\\", "/").split("/")), f"{rest} fehlt"


def test_die_aufrufer_geben_dem_installer_absolute_pfade():
    """``SourceDir`` zeigt aus dem Repo heraus in den Bauordner. Relativ
    übergeben wuerde Inno ihn gegen sein eigenes Verzeichnis aufloesen."""
    bat = _lies("Release", "skripte", "build_windows.bat")
    assert "/DSourceDir=%CD%\\" in bat, "relativer Quellordner im Bauskript"
    ablauf = _lies(".github", "workflows", "release.yml")
    assert "Join-Path $PWD" in ablauf, "relativer Quellordner im Ablauf"


def test_die_versionsnummer_im_installer_ist_nicht_getippt():
    """Hier stand fest „0.1.0", waehrend das Spiel 0.7.1-beta meldete. Windows
    zeigt den Wert in den Dateieigenschaften — dieselbe Lehre wie beim
    macOS-Buendel am 04.08.2026."""
    quelle = _lies("Release", "installer", "installer.iss")
    assert "VersionInfoVersion={#VersionZahl}" in quelle
    assert "VersionInfoVersion=0.1.0" not in quelle


# ── Die Rückfrage im Startskript (07.08.2026) ────────────────────────────────

@pytest.mark.parametrize("skript", ["release_starten.bat", "release_starten.sh"])
def test_das_startskript_fragt_was_gebaut_werden_soll(skript):
    """Vorher entschied das ein Argument, das man beim Aufruf vergisst — und
    vergessen hiess: aus Versehen eine Versionsnummer verbraucht, die sich
    nicht zurueckholen laesst."""
    quelle = _lies("Release", "skripte", skript)
    assert "Was soll gebaut werden" in quelle
    assert "Testbuild" in quelle and "Release" in quelle


@pytest.mark.parametrize("skript", ["release_starten.bat", "release_starten.sh"])
def test_ohne_angabe_ist_der_testbuild_die_vorgabe(skript):
    """Die harmlosere der beiden Antworten gehoert auf die Eingabetaste."""
    quelle = _lies("Release", "skripte", skript)
    assert "Enter = 1" in quelle
    assert "verbraucht KEINE Versionsnummer" in quelle


def test_die_rueckfrage_laeuft_wirklich_durch():
    """Nicht nur der Text — der Ablauf. Antwort „1", dann die Sicherheitsfrage
    verneint: es darf kein Tag entstehen und nichts abstuerzen."""
    import subprocess
    aus = subprocess.run(["bash", "Release/skripte/release_starten.sh"],
                         cwd=_ROOT, input="1\nn\n", capture_output=True,
                         text=True, timeout=120)
    assert aus.returncode == 0, aus.stderr
    assert "Was soll gebaut werden" in aus.stdout
    assert "Testbuild" in aus.stdout
    assert "Abgebrochen" in aus.stdout


# ── Die Pipeline ──────────────────────────────────────────────────────────────

def test_die_ablaufdateien_gibt_es():
    assert _da(".github", "workflows", "tests.yml")
    assert _da(".github", "workflows", "release.yml")


def test_der_release_ablauf_verweist_nur_auf_vorhandene_dateien():
    """Der eigentliche Zweck dieser Datei: nach dem Umzug zeigt hier leicht
    etwas ins Leere, und auffallen wuerde es erst beim echten Release."""
    ablauf = _lies(".github", "workflows", "release.yml")
    for pfad in set(re.findall(r"Release[/\\][\w./\\-]+", ablauf)):
        norm = pfad.replace("\\", "/")
        if norm.startswith("Release/ausgabe"):
            continue                      # entsteht erst beim Bauen
        assert _da(*norm.split("/")), f"{norm} steht im Ablauf, gibt es aber nicht"


def test_gebaut_wird_erst_nach_gruenen_tests():
    """Ein Release aus rotem Stand ist genau das, wogegen die Pipeline gebaut
    wurde. Faellt die Abhaengigkeit weg, laeuft der Build trotzdem."""
    ablauf = _lies(".github", "workflows", "release.yml")
    assert "uses: ./.github/workflows/tests.yml" in ablauf
    assert re.search(r"needs:\s*\[\s*tests\s*,", ablauf), \
        "der Bau-Auftrag haengt nicht mehr an den Tests"


def test_ein_testbuild_veroeffentlicht_nichts():
    """Er traegt dieselbe Version wie ein echtes Release und waere sonst damit
    zu verwechseln."""
    ablauf = _lies(".github", "workflows", "release.yml")
    assert "startsWith(github.ref_name, 'v')" in ablauf


def test_die_testsuite_laeuft_mit_attrappen_fuer_bild_und_ton():
    """Ohne sie sucht pygame einen Bildschirm, den ein Bauknecht nicht hat."""
    ablauf = _lies(".github", "workflows", "tests.yml")
    assert "SDL_VIDEODRIVER: dummy" in ablauf
    assert "SDL_AUDIODRIVER: dummy" in ablauf


def test_beide_startskripte_erzeugen_dieselben_tagnamen():
    """Sie sind Schwestern. Laufen die Namen auseinander, greift der Ablauf auf
    einem der beiden Rechner nicht — und zwar stillschweigend."""
    bat = _lies("Release", "skripte", "release_starten.bat")
    sh = _lies("Release", "skripte", "release_starten.sh")
    ablauf = _lies(".github", "workflows", "release.yml")
    for quelle, name in ((bat, "bat"), (sh, "sh")):
        assert "test-" in quelle, f"{name}: kein Testbuild-Tag"
        assert "v%VERSION%" in quelle or 'v${VERSION}' in quelle, \
            f"{name}: kein Release-Tag"
    # Und der Ablauf muss auf genau diese beiden Formen hoeren.
    assert '- "v*"' in ablauf and '- "test-*"' in ablauf


@pytest.mark.parametrize("skript", ["release_starten.bat", "release_starten.sh"])
def test_ein_veralteter_stand_wird_nicht_getaggt(skript):
    """Der Fehler vom 06.08.2026: getaggt wurde zwei Merges vor dem aktuellen
    Stand. Die Tests waren dort noch rot, es entstand kein Paket — und was der
    Nutzer sah, war GitHubs automatisches Quelltext-Zip zum Tag. Ein Tag auf
    einem alten Commit baut immer das Falsche, deshalb bricht das Skript ab."""
    quelle = _lies("Release", "skripte", skript)
    assert "git fetch" in quelle, "ohne fetch kennt der Vergleich den Stand nicht"
    assert "rev-list --count" in quelle
    assert "pull --ff-only" in quelle, "kein Hinweis, wie es weitergeht"


@pytest.mark.parametrize("skript", ["release_starten.bat", "release_starten.sh"])
def test_ein_tag_auf_github_wird_auch_erkannt(skript):
    """Oertlich zu suchen genuegt nicht: nach einem frischen Klon ist der Tag
    nur drueben, und der Push scheitert dann mit einer nichtssagenden Meldung."""
    assert "ls-remote" in _lies("Release", "skripte", skript)


@pytest.mark.parametrize("skript", ["release_starten.bat", "release_starten.sh"])
def test_das_skript_sagt_was_das_quelltext_zip_ist(skript):
    """Genau die Verwechslung vom 06.08.2026 — „Version erstellt ohne Probleme,
    aber nur ein Zip mit dem Quellcode"."""
    quelle = _lies("Release", "skripte", skript)
    assert "Source code" in quelle
    assert "KEIN Paket" in quelle


def test_der_tag_wird_gegen_version_py_geprueft():
    """Sonst entsteht v1.0.1 aus einem Stand, der sich intern 1.0.0 nennt — und
    das faellt erst auf, wenn ein Spieler die falsche Nummer meldet."""
    ablauf = _lies(".github", "workflows", "release.yml")
    assert "version.py" in ablauf
    assert "passt nicht zu VERSION" in ablauf


# ── Die eingebrannte Bauzeit ──────────────────────────────────────────────────

def test_ohne_stempel_gilt_das_heutige_datum(tmp_path, monkeypatch):
    """Aus dem Quelltext gestartet sind „gebaut" und „gestartet" derselbe
    Moment — dann ist heute die richtige Antwort."""
    from datetime import date
    from src.core import paths, version
    monkeypatch.setattr(paths, "bundle_dir", lambda: tmp_path)
    assert version._baustempel() == {}
    # Und der Modulwert bei genau diesem Zustand:
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", version.BUILD_DATE)
    if not os.path.exists(os.path.join(_ROOT, "data", "settings", "build_stamp.json")):
        assert version.BUILD_DATE == date.today().isoformat()
        assert version.BUILD_TIME == ""


def test_ein_vorhandener_stempel_wird_gelesen(tmp_path, monkeypatch):
    from src.core import paths, version
    ziel = tmp_path / "data" / "settings"
    ziel.mkdir(parents=True)
    (ziel / "build_stamp.json").write_text(json.dumps(
        {"datum": "2026-01-02", "zeit": "03:04", "commit": "abc1234",
         "quelle": "test-0.7.0-beta-0102-0304"}), "utf-8")
    monkeypatch.setattr(paths, "bundle_dir", lambda: tmp_path)
    stempel = version._baustempel()
    assert stempel["datum"] == "2026-01-02"
    assert stempel["zeit"] == "03:04"


def test_ein_kaputter_stempel_bringt_das_spiel_nicht_um(tmp_path, monkeypatch):
    """Die Bauzeit ist eine Anzeige, kein Betriebsmittel. Eine halb
    geschriebene Datei darf den Start nicht verhindern."""
    from src.core import paths, version
    ziel = tmp_path / "data" / "settings"
    ziel.mkdir(parents=True)
    (ziel / "build_stamp.json").write_text('{"datum": "2026-01-0', "utf-8")
    monkeypatch.setattr(paths, "bundle_dir", lambda: tmp_path)
    assert version._baustempel() == {}


def test_baustempel_schreibt_was_die_version_erwartet(tmp_path, monkeypatch):
    """Erzeuger und Leser an einem Test — sonst laufen die Schluesselnamen
    auseinander und niemand merkt es."""
    from src.core import paths, version
    from tools import baustempel
    ziel = tmp_path / "data" / "settings" / "build_stamp.json"
    geschrieben = baustempel.schreiben(str(ziel))
    monkeypatch.setattr(paths, "bundle_dir", lambda: tmp_path)
    gelesen = version._baustempel()
    assert gelesen == geschrieben
    assert set(geschrieben) == {"datum", "zeit", "commit", "quelle"}


def test_die_bauzeit_wandert_ins_buendel():
    """Steht sie nicht in den Spezifikationen, fehlt die Datei im gepackten
    Spiel und die Info-Seite faellt still auf das Tagesdatum zurueck."""
    for spec in ("game.spec", "game_macos.spec"):
        quelle = _lies("Release", "pyinstaller", spec)
        assert "build_stamp.json" in quelle, f"{spec} nimmt die Bauzeit nicht mit"


def test_beide_builds_brennen_die_bauzeit_ein():
    assert "baustempel" in _lies("Release", "skripte", "build_windows.bat")
    assert "baustempel" in _lies("Release", "skripte", "build_macos.sh")
    assert "baustempel" in _lies(".github", "workflows", "release.yml")


# ── Die Anführungszeichenfalle von cmd (gemeldet 06.08.2026) ─────────────────
#
# „Der Befehl "python" -c "from" ist entweder falsch geschrieben oder konnte
# nicht gefunden werden." Die Zeile dahinter war:
#
#     "%PY%" -c "from src.core import version; print(...)" > "%TEMP%\..."
#
# Sie beginnt und endet mit einem Anführungszeichen. Genau dann entfernt ``cmd``
# das äußere Paar, und als Programmname bleibt ``python" -c "from`` übrig.
# Solange der Interpreter mit vollem Pfad dastand, ging es gut; erst der
# Rückfall auf das Python vom Suchpfad hat es aufgedeckt.

def _befehlszeilen(quelle: str) -> list[str]:
    """Zeilen, die ein Programm aufrufen — Kommentare und Labels raus."""
    aus = []
    for zeile in quelle.splitlines():
        s = zeile.strip()
        if not s or s.startswith("::") or s.startswith("@") or s.startswith(":"):
            continue
        if s.lower().startswith("rem "):
            continue
        aus.append(s)
    return aus


@pytest.mark.parametrize("skript", ["build_windows.bat", "release_starten.bat"])
def test_keine_zeile_beginnt_und_endet_mit_einem_anfuehrungszeichen(skript):
    """Das ist die Falle, wörtlich. Eine solche Zeile kann funktionieren — aber
    nur, solange niemand am Interpreterpfad etwas ändert."""
    schlecht = [z for z in _befehlszeilen(_lies("Release", "skripte", skript))
                if z.startswith('"') and z.endswith('"')]
    assert not schlecht, ("cmd entfernt hier das aeussere Anfuehrungszeichenpaar:\n  "
                          + "\n  ".join(schlecht))


@pytest.mark.parametrize("skript", ["build_windows.bat", "release_starten.bat"])
def test_die_version_wird_ohne_inneres_anfuehrungszeichen_gelesen(skript):
    """``-c "…"`` braucht Anführungszeichen mitten im Aufruf, ein eigenes
    Werkzeug nicht. Deshalb liegt die Abfrage in einer eigenen Datei — seit dem
    07.08.2026 über ihren **Pfad** gerufen statt als Modul."""
    quelle = _lies("Release", "skripte", skript)
    assert "version_ausgeben.py" in quelle
    assert "-c \"from src.core import version" not in quelle, \
        "die alte Fassung mit -c ist zurueck"


@pytest.mark.parametrize("skript", ["build_windows.bat", "release_starten.bat"])
def test_der_interpreter_wird_mit_vollem_pfad_gesucht(skript):
    """``set "PY=python"`` war die zweite Hälfte des Fehlers: ein Programmname
    ohne Pfad, in Anführungszeichen, ist genau der Fall, in dem cmd stolpert."""
    quelle = _lies("Release", "skripte", skript)
    assert 'set "PY=python"' not in quelle, "blosser Programmname statt Pfad"
    assert "where python" in quelle, "kein Rueckfall auf den Suchpfad"


def test_das_werkzeug_gibt_genau_die_version_aus():
    """Nur die nackte Nummer — sie landet in Dateinamen und geht an Inno Setup.
    Ein „v" davor oder ein Commit dahinter wuerde beides verderben."""
    import subprocess
    aus = subprocess.run([sys.executable, "-m", "tools.version_ausgeben"],
                         cwd=_ROOT, capture_output=True, text=True, timeout=60)
    assert aus.returncode == 0, aus.stderr
    from src.core import version
    assert aus.stdout.strip() == version.VERSION
    assert not aus.stdout.strip().startswith("v")


def test_die_info_seite_zeigt_die_uhrzeit_wenn_es_eine_gibt():
    """Testbuilds unterscheiden sich **nur** darin. Ohne die Uhrzeit waere am
    laufenden Spiel nicht zu sagen, welcher Stand laeuft."""
    quelle = _lies("src", "states", "menu", "settings_page.py")
    assert "BUILD_TIME" in quelle
