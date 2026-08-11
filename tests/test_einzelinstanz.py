"""Nur ein laufendes Spiel je Rechner (A2, entschieden 05.08.2026).

Der offene A2-Punkt hieß „zwei Instanzen gleichzeitig starten (Schreibkonflikt
auf Profildatei)". Mit E4 ist er teurer geworden: das Profil liegt verschlüsselt
und signiert vor, und wer mittendrin darüberschreibt, macht es **unlesbar**
statt nur veraltet.

Geprüft wird deshalb nicht „gibt es die Datei", sondern das, was schiefgehen
kann: dass die zweite Instanz abgewiesen wird, dass nach einem Absturz **keine**
Sperre liegenbleibt, und dass ein Rechner, auf dem sich gar nicht sperren lässt,
das Spiel trotzdem startet. Der letzte Punkt ist der wichtigste — ein Spiel, das
wegen einer Dateisystemeigenheit nicht mehr aufgeht, ist schlimmer als der
Konflikt, gegen den gesperrt wird.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.core import einzelinstanz  # noqa: E402


@pytest.fixture(autouse=True)
def eigenes_verzeichnis(monkeypatch, tmp_path):
    """Jede Prüfung mit einer frischen Sperrdatei — und hinterher aufgeräumt."""
    from src.core import paths
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    einzelinstanz.freigeben()
    yield tmp_path
    einzelinstanz.freigeben()


def test_die_erste_instanz_darf_starten():
    assert einzelinstanz.beanspruchen() is True


def test_zweimal_beanspruchen_im_selben_prozess_bleibt_wahr():
    """Derselbe Prozess ist nicht sein eigener Konkurrent — sonst scheiterte
    jeder Neustart des Zustands innerhalb eines Laufs."""
    assert einzelinstanz.beanspruchen() is True
    assert einzelinstanz.beanspruchen() is True


def test_die_sperrdatei_entsteht_im_nutzerverzeichnis(eigenes_verzeichnis):
    einzelinstanz.beanspruchen()
    assert (eigenes_verzeichnis / "data" / "settings"
            / einzelinstanz.DATEINAME).is_file()


def test_nach_dem_freigeben_darf_wieder_beansprucht_werden():
    assert einzelinstanz.beanspruchen() is True
    einzelinstanz.freigeben()
    assert einzelinstanz.beanspruchen() is True


def test_freigeben_ohne_beanspruchen_tut_nichts():
    einzelinstanz.freigeben()          # darf nicht werfen


# ---------------------------------------------------------------------------
# Der eigentliche Fall: zwei Prozesse
# ---------------------------------------------------------------------------

_ZWEITE_INSTANZ = """
import sys
sys.path.insert(0, {root!r})
from src.core import paths, einzelinstanz
paths.user_data_dir = lambda: __import__("pathlib").Path({dir!r})
print("FREI" if einzelinstanz.beanspruchen() else "BELEGT")
"""


def _zweite_instanz(verzeichnis) -> str:
    quelle = textwrap.dedent(_ZWEITE_INSTANZ).format(
        root=_ROOT, dir=str(verzeichnis))
    fertig = subprocess.run([sys.executable, "-c", quelle],
                            capture_output=True, text=True, timeout=60)
    return fertig.stdout.strip()


def test_ein_zweiter_prozess_wird_abgewiesen(eigenes_verzeichnis):
    """Der gemeldete Fall, mit echten Prozessen — eine Sperre innerhalb eines
    Prozesses zu prüfen sagt über Prozessgrenzen hinweg nichts."""
    assert einzelinstanz.beanspruchen() is True
    assert _zweite_instanz(eigenes_verzeichnis) == "BELEGT"


def test_nach_dem_ende_der_ersten_ist_der_platz_wieder_frei(eigenes_verzeichnis):
    assert einzelinstanz.beanspruchen() is True
    einzelinstanz.freigeben()
    assert _zweite_instanz(eigenes_verzeichnis) == "FREI"


def test_eine_liegengebliebene_datei_blockiert_nicht(eigenes_verzeichnis):
    """Der Absturzfall, und der Grund für die Sperre über das Betriebssystem.

    Nach einem Absturz bleibt die *Datei* liegen — nur die Sperre nicht, weil
    sie am offenen Dateihandle hängt und das System sie mit dem Prozess
    schließt. Eine Prüfung auf „Datei vorhanden" hätte das Spiel hier dauerhaft
    blockiert, und niemand hätte gewusst, was zu löschen ist.
    """
    ordner = eigenes_verzeichnis / "data" / "settings"
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / einzelinstanz.DATEINAME).write_text("4711", encoding="utf-8")

    assert einzelinstanz.beanspruchen() is True


def test_ohne_schreibrecht_startet_das_spiel_trotzdem(monkeypatch):
    """Im Zweifel aufmachen. Wer hier abwiese, macht aus einem
    Berechtigungsproblem ein Spiel, das gar nicht mehr startet."""
    def _geht_nicht(*a, **k):
        raise OSError("kein Schreibrecht")
    monkeypatch.setattr("builtins.open", _geht_nicht)

    assert einzelinstanz.beanspruchen() is True


def test_ohne_sperrmechanismus_startet_das_spiel_trotzdem(monkeypatch):
    """Dieselbe Haltung eine Ebene tiefer: kann die Plattform nicht sperren,
    gilt das nicht als „belegt"."""
    monkeypatch.setattr(einzelinstanz, "_sperren", lambda fh: True)
    assert einzelinstanz.beanspruchen() is True
