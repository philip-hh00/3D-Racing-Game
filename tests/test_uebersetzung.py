"""Jeder Text, den ein Spieler sieht, hat eine englische Fassung (Block F1).

Die Sprachdatei ist eine Bringschuld, die niemand bemerkt: `tr()` fällt bei
einem fehlenden Eintrag auf das **deutsche** Original zurück. Auf Englisch
gestellt sieht man dann kein Fragezeichen und keinen leeren Kasten, sondern
einfach einen deutschen Satz zwischen englischen — und beim Entwickeln (Sprache
Deutsch) fällt genau nichts auf. Am 05.08.2026 waren es 104 Texte, davon **61
Erfolge**, also der komplette Block E: er ist nach der letzten Messung
dazugekommen und hat nie eine Übersetzung bekommen.

Deshalb wird hier nicht die Datei geprüft, sondern **jede Quelle, aus der ein
sichtbarer Text stammt**:

* Zeichenketten in `tr(...)` — im Quelltext gesucht, nicht zur Laufzeit: eine
  Seite, die nie gezeichnet wird, hat trotzdem Texte
* die Erfolge aus `statistik.ERFOLGE` (Gruppe, Name, Bedingung)
* Modi, Schwierigkeiten, Eingabegeräte und Fahrzeugklassen aus `race_setup`
* die Bedienhinweise aus `hints._LABELS`
* Lackfarben, Finishes und Fortschrittsvorlagen
* Name und Beschreibung jedes Fahrzeugs und jeder mitgelieferten Strecke

Was in beiden Sprachen gleich heißt — Tastennamen wie `ENTER`, Knopfnamen wie
`LB/RB`, Eigennamen wie „GP Arena" — steht mit sich selbst als Übersetzung in
der Datei. Das ist mit Absicht keine Ausnahmeliste im Test: eine Ausnahmeliste
wächst still mit, ein Eintrag in der Sprachdatei ist eine Aussage („so heißt es
auf Englisch"), die jemand getroffen hat.
"""
from __future__ import annotations

import ast
import glob
import json
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from src.core import lack, race_setup, statistik  # noqa: E402
from src.core.i18n import LANGUAGES, set_language, tr  # noqa: E402
from src.ui import hints  # noqa: E402

_TABELLE = _ROOT / "data" / "i18n" / "en.json"


def _tabelle() -> dict[str, str]:
    with open(_TABELLE, encoding="utf-8") as f:
        return json.load(f)


def _tr_literale() -> dict[str, str]:
    """Jede Zeichenkette, die im Quelltext direkt in ``tr()`` steht.

    Über den Syntaxbaum und nicht über eine Textsuche: `tr("…")` kommt auch in
    Kommentaren und Beispielen vor, und ein Aufruf über mehrere Zeilen fiele
    einer Textsuche durch.
    """
    raus: dict[str, str] = {}
    for pfad, _ordner, dateien in os.walk(_ROOT / "src"):
        for d in sorted(dateien):
            if not d.endswith(".py"):
                continue
            p = os.path.join(pfad, d)
            with open(p, encoding="utf-8") as f:
                baum = ast.parse(f.read(), p)
            for k in ast.walk(baum):
                if not isinstance(k, ast.Call):
                    continue
                name = getattr(k.func, "id", None) or getattr(k.func, "attr", None)
                if name != "tr" or not k.args:
                    continue
                erst = k.args[0]
                if isinstance(erst, ast.Constant) and isinstance(erst.value, str):
                    raus.setdefault(erst.value,
                                    f"{os.path.relpath(p, _ROOT)}:{k.lineno}")
    return raus


def _aus_daten() -> dict[str, str]:
    """Sichtbare Texte, die nicht im Quelltext stehen, sondern in Listen und
    JSON-Dateien — die Stellen, an denen ``tr()`` einen *Wert* übersetzt."""
    raus: dict[str, str] = {}

    def merke(quelle: str, *werte) -> None:
        for w in werte:
            if isinstance(w, str) and w.strip():
                raus.setdefault(w, quelle)

    for _key, gruppe, name, text, _quelle, _ziel in statistik.ERFOLGE:
        merke("statistik.ERFOLGE", gruppe, name, text)
    merke("race_setup.MODES", *race_setup.MODES)
    merke("race_setup.MODE_DESCRIPTIONS", *race_setup.MODE_DESCRIPTIONS.values())
    merke("race_setup.DIFFICULTY_LABELS", *race_setup.DIFFICULTY_LABELS.values())
    merke("race_setup.INPUT_LABELS", *race_setup.INPUT_LABELS.values())
    merke("race_setup.CLASS_NAMES", *race_setup.CLASS_NAMES)
    for paar in hints._LABELS.values():
        merke("hints._LABELS", *paar)
    merke("lacke.json", *[f["name"] for f in lack.farben() + lack.finishes()])
    merke("lack._VORLAGE", *lack._VORLAGE.values())

    for p in sorted(glob.glob(str(_ROOT / "data" / "vehicles" / "*.json"))):
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if "visual_type" in d:                      # lacke.json ist kein Fahrzeug
            merke(os.path.basename(p), d.get("name"), d.get("description"))
    for p in sorted(glob.glob(str(_ROOT / "data" / "tracks" / "*.json"))):
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        merke(os.path.basename(p), d.get("name"), d.get("description"),
              d.get("difficulty"))
    return raus


# ---------------------------------------------------------------------------
# Vollständigkeit
# ---------------------------------------------------------------------------
def test_jeder_text_im_quelltext_hat_eine_englische_fassung():
    tab = _tabelle()
    fehlt = {s: o for s, o in _tr_literale().items() if s and s not in tab}
    assert not fehlt, "ohne englische Fassung:\n" + "\n".join(
        f"  {o:50s} {s!r}" for s, o in sorted(fehlt.items(), key=lambda x: x[1]))


def test_jeder_text_aus_den_datendateien_hat_eine_englische_fassung():
    """Der Fall, der 2026 durchgerutscht ist: die 61 Erfolge stehen in einer
    Liste, nicht in einem ``tr("…")`` — eine Suche nach Aufrufen findet sie nie."""
    tab = _tabelle()
    fehlt = {s: o for s, o in _aus_daten().items() if s not in tab}
    assert not fehlt, "ohne englische Fassung:\n" + "\n".join(
        f"  {o:30s} {s!r}" for s, o in sorted(fehlt.items(), key=lambda x: x[1]))


def test_alle_erfolge_sind_uebersetzt():
    """Eigener Test, weil es der größte Einzelblock ist und beim Lesen des
    Fehlschlags sonst in 100 Zeilen untergeht."""
    tab = _tabelle()
    for _key, gruppe, name, text, _quelle, _ziel in statistik.ERFOLGE:
        for s in (gruppe, name, text):
            assert s in tab, f"Erfolg ohne Übersetzung: {s!r}"


# ---------------------------------------------------------------------------
# Brauchbarkeit der Einträge
# ---------------------------------------------------------------------------
def test_keine_leeren_uebersetzungen():
    leer = [k for k, v in _tabelle().items() if not str(v).strip()]
    assert not leer, leer


def test_platzhalter_bleiben_erhalten():
    """``"{a} von {b} Erfolgen"`` wird nach der Übersetzung formatiert. Fehlt
    ein Platzhalter, kostet das kein hässliches Wort, sondern einen
    ``KeyError`` mitten im Zeichnen."""
    import re
    kaputt = []
    for de, en in _tabelle().items():
        if set(re.findall(r"\{(\w+)\}", de)) != set(re.findall(r"\{(\w+)\}", en)):
            kaputt.append((de, en))
    assert not kaputt, kaputt


def test_uebersetzungen_sind_nicht_versehentlich_deutsch():
    """Ein kopierter Eintrag („Siege": „Siege") sieht in der Datei aus wie
    erledigt und ist doch keiner.

    Gleiche Fassungen sind erlaubt und häufig: Tastennamen („ENTER"),
    Knopfpaare („Trigger LT/RT"), Eigennamen („GP Arena", „Mountain Ridge"),
    Fachwörter („Hatchback"). Alle sind **kurz** und kommen ohne deutsche
    Sonderzeichen aus. Ein deutscher Satz, den jemand nur kopiert hat, fällt an
    einem der beiden Merkmale auf."""
    grenze = 24
    verdaechtig = [de for de, en in _tabelle().items()
                   if de == en and (len(de) > grenze
                                    or any(c in de for c in "äöüßÄÖÜ"))]
    assert not verdaechtig, verdaechtig


def test_die_sprachdatei_bleibt_lesbar():
    """UTF-8 ohne Escapes und mit fester Einrückung — die Datei wird von Hand
    gepflegt und soll im Diff lesbar bleiben."""
    roh = _TABELLE.read_text(encoding="utf-8")
    assert roh.startswith("{\n  \"")
    assert "\\u00" not in roh, "ASCII-Escapes statt Umlauten"


# ---------------------------------------------------------------------------
# Der Weg durch tr()
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _sprache_zuruecksetzen():
    yield
    set_language("de")


def test_englisch_liefert_wirklich_englisch():
    set_language("en")
    assert tr("Siege") == "Wins"
    assert tr("Erste Runden") == "First laps"
    assert tr("Los geht's") == "Let's go"


def test_deutsch_reicht_das_original_durch():
    set_language("de")
    assert tr("Siege") == "Siege"


def test_unbekanntes_faellt_auf_deutsch_zurueck():
    """Der Grund, warum eine fehlende Übersetzung so lange unbemerkt bleibt —
    festgehalten, damit niemand das für einen Fehler hält und „repariert"."""
    set_language("en")
    assert tr("Diesen Satz gibt es nirgends") == "Diesen Satz gibt es nirgends"


@pytest.mark.parametrize("sprache", LANGUAGES)
def test_keine_sprache_stuerzt_an_einem_erfolg_ab(sprache):
    set_language(sprache)
    for _key, gruppe, name, text, _quelle, _ziel in statistik.ERFOLGE:
        for s in (gruppe, name, text):
            assert tr(s).strip()


def test_grand_prix_beenden_heisst_verlassen_nicht_finish():
    """Regel: die englische Fassung der Aktion "Grand Prix beenden" bedeutet
    Verlassen, nicht "zu Ende fahren".

    Gemeldet 08.08.2026: "Finish Grand Prix" las sich wie "die Serie
    auszufahren", gemeint war das Verlassen. Geprueft wird jeder Schluessel, der
    mit "Grand Prix beenden" beginnt — nicht die beiden Einzelfaelle: eine
    kuenftige dritte Variante desselben Knopfes faellt damit ebenso auf.
    """
    tabelle = _tabelle()
    schluessel = [k for k in tabelle if k.startswith("Grand Prix beenden")]
    # Die beiden Aktions-Schluessel muessen ueberhaupt da sein, sonst prueft der
    # Test nichts.
    assert "Grand Prix beenden" in schluessel
    assert "Grand Prix beenden  ›" in schluessel
    for k in schluessel:
        assert "finish" not in tabelle[k].lower(), (
            f"{k!r} -> {tabelle[k]!r} liest sich wie 'zu Ende fahren'")
    # Die reinen Aktions-Knoepfe sagen ausdruecklich "Exit".
    assert "Exit" in tabelle["Grand Prix beenden"]
    assert "Exit" in tabelle["Grand Prix beenden  ›"]
