"""Der Verkaufstext auf itch.io gegen das Spiel geprueft.

Der Text in ``Documentation/ITCHIO_RELEASE.md`` ist das Einzige, was ein
Interessent vor dem Herunterladen liest. Steht dort eine Zahl, die das Spiel
nicht einloest, ist das ein gebrochenes Versprechen auf der Verkaufsseite — und
genau das ist schon zweimal passiert (siehe ``release_1_0_plan.md`` §0: „5
Unique Vehicles" bei 15 Fahrzeugen, und Grand Prix, den es damals nicht gab).
Beides faellt niemandem beim Programmieren auf, weil die Datei kein Code ist.

Geprueft wird deshalb nicht der Wortlaut, sondern die **Zahl**: jede Angabe im
Text muss aus dem Spiel herleitbar sein. Und weil der Text in zwei Sprachen
dasteht, muessen beide Fassungen dieselben Zahlen nennen — sonst liest ein
deutscher und ein englischer Besucher etwas Verschiedenes.

Gefunden am 07.08.2026 beim Neuschreiben des Seitentexts.
"""
from __future__ import annotations

import json
import os
import re
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.core import race_setup  # noqa: E402

_TEXT_PFAD = os.path.join(_ROOT, "Documentation", "ITCHIO_RELEASE.md")

#: Die Fassung, die wirklich auf der Seite landet. itch.io hat ein
#: Rich-Text-Feld mit HTML-Ansicht; diese Datei wird dort hineingegeben, ohne
#: dass jemand hinterher formatiert.
_HTML_PFAD = os.path.join(_ROOT, "Documentation", "itchio_page.html")


@pytest.fixture(scope="module")
def text() -> str:
    with open(_TEXT_PFAD, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def fassungen(text: str) -> dict[str, str]:
    """Den Text in die beiden Sprachfassungen zerlegen.

    Getrennt wird an den Ueberschriften ``# Deutsch`` und ``# English``; der
    Schlussteil (Einstellungen, Pflegehinweise) gehoert zu keiner von beiden und
    faellt heraus — dort stehen bewusst Zahlen wie „1-6", die nicht als Aussage
    ueber das Spiel gemeint sind.
    """
    teile = re.split(r"^# (Deutsch|English)$", text, flags=re.MULTILINE)
    # re.split liefert [vorspann, "Deutsch", inhalt, "English", inhalt, ...]
    gefunden = {teile[i]: teile[i + 1] for i in range(1, len(teile) - 1, 2)}
    assert set(gefunden) == {"Deutsch", "English"}, sorted(gefunden)
    # Der Schlussteil haengt an der letzten Fassung — abschneiden.
    for name, inhalt in list(gefunden.items()):
        gefunden[name] = inhalt.split("\n# 3. ")[0]
    return gefunden


#: Im Fliesstext stehen kleine Zahlen ausgeschrieben — „Vier Spielmodi" liest
#: sich besser als „4 Spielmodi", und das soll der Test nicht verbieten.
_WORTZAHLEN = {
    "zwei": "2", "two": "2", "drei": "3", "three": "3",
    "vier": "4", "four": "4", "fünf": "5", "five": "5",
    "sechs": "6", "six": "6", "zwölf": "12", "twelve": "12",
}


@pytest.fixture(scope="module")
def html() -> str:
    """Der HTML-Text, von seinen Auszeichnungen befreit.

    Verglichen wird die Sprache, nicht das Markup: ``<strong>12</strong>
    colours`` und ``12 colours`` sollen dasselbe bedeuten. Die Tags fallen
    deshalb heraus, bevor gezaehlt wird.
    """
    with open(_HTML_PFAD, encoding="utf-8") as f:
        roh = f.read()
    return re.sub(r"<[^>]+>", " ", roh)


def _zahl_vor(inhalt: str, *woerter: str) -> set[str]:
    """Alle Zahlen, die im Text unmittelbar vor einem der Woerter stehen.

    Ziffer oder Zahlwort — beides zaehlt, und beides wird auf die Ziffer
    abgebildet, damit der Vergleich mit dem Code eine Zahl gegen eine Zahl
    haelt.
    """
    zahl = r"\d+|" + "|".join(_WORTZAHLEN)
    muster = re.compile(r"(%s)\s+(?:\*\*)?(?:%s)" % (zahl, "|".join(woerter)),
                        re.IGNORECASE)
    return {_WORTZAHLEN.get(t.lower(), t) for t in muster.findall(inhalt)}


# --------------------------------------------------------------------------
# Die Zahlen gegen das Spiel


def test_die_fahrzeuganzahl_stimmt(fassungen):
    erwartet = str(len(race_setup.CLASSES["Alle"]))
    for sprache, inhalt in fassungen.items():
        gefunden = _zahl_vor(inhalt, "Fahrzeuge", "cars")
        assert erwartet in gefunden, (sprache, erwartet, gefunden)


def test_die_klassenanzahl_stimmt(fassungen):
    # "Alle" ist ein Filter in der Auswahl, keine Fahrzeugklasse.
    erwartet = str(len(race_setup.CLASSES) - 1)
    for sprache, inhalt in fassungen.items():
        gefunden = _zahl_vor(inhalt, "Klassen", "classes")
        assert erwartet in gefunden, (sprache, erwartet, gefunden)


def test_jede_beworbene_klasse_hat_drei_modelle(fassungen):
    """Der Text verspricht „Drei Modelle pro Klasse" — ohne Ausnahme."""
    for name, schluessel in race_setup.CLASSES.items():
        if name == "Alle":
            continue
        assert len(schluessel) == 3, (name, schluessel)


def test_die_modi_im_text_sind_die_modi_im_spiel(fassungen):
    erwartet = str(len(race_setup.MODES))
    for sprache, inhalt in fassungen.items():
        gefunden = _zahl_vor(inhalt, "Spielmodi", "game modes")
        assert erwartet in gefunden, (sprache, erwartet, gefunden)
    # Alle vier muessen auch tatsaechlich auswaehlbar sein — der aeltere Fehler
    # war nicht die Zahl, sondern ein beworbener Modus hinter einem Schalter.
    assert set(race_setup.MODES) == set(race_setup.MODES_ENABLED)


def test_die_farben_und_lackarten_stimmen(fassungen):
    with open(os.path.join(_ROOT, "data", "vehicles", "lacke.json"),
              encoding="utf-8") as f:
        lacke = json.load(f)
    farben = str(len(lacke["farben"]))
    arten = str(len(lacke["finishes"]))
    for sprache, inhalt in fassungen.items():
        assert farben in _zahl_vor(inhalt, "Farben", "colours", "colors"), sprache
        assert arten in _zahl_vor(inhalt, "Lackarten", "finishes"), sprache


def test_die_drei_erspielten_lackarten_haengen_an_einer_freischaltung(fassungen):
    """Der Text nennt genau drei Lackarten als Belohnung — der Rest ist frei."""
    with open(os.path.join(_ROOT, "data", "vehicles", "lacke.json"),
              encoding="utf-8") as f:
        lacke = json.load(f)
    erspielt = [f["key"] for f in lacke["finishes"] if f.get("freischaltung")]
    assert sorted(erspielt) == ["metallic", "neon", "zweifarbig"], erspielt
    for sprache, inhalt in fassungen.items():
        niedrig = inhalt.lower()
        for wort in ("metallic", "neon"):
            assert wort in niedrig, (sprache, wort)
        assert "zweifarbig" in niedrig or "two-tone" in niedrig, sprache


def test_die_spielerzahl_stimmt_mit_dem_server(fassungen):
    """„bis zu 6 Spieler" ist keine Formulierung, sondern MAX_SLOTS."""
    sys.path.insert(0, os.path.join(_ROOT, "server"))
    server = pytest.importorskip("server")
    erwartet = str(server.MAX_SLOTS)
    for sprache, inhalt in fassungen.items():
        gefunden = _zahl_vor(inhalt, "Spieler", "players", "Fahrzeuge", "cars")
        assert erwartet in gefunden, (sprache, erwartet, gefunden)


def test_die_mitgelieferten_strecken_stimmen(fassungen):
    """Nur die Dateien direkt in ``data/tracks`` gehen mit — ``custom``,
    ``drafts`` und ``online`` sind seit dem 04.08.2026 bewusst nicht dabei."""
    ordner = os.path.join(_ROOT, "data", "tracks")
    strecken = sorted(n[:-5] for n in os.listdir(ordner) if n.endswith(".json"))
    assert strecken == ["city", "desert", "gp", "mountain", "oval"], strecken
    erwartet = str(len(strecken))
    for sprache, inhalt in fassungen.items():
        gefunden = _zahl_vor(inhalt, "Strecken", "tracks")
        assert erwartet in gefunden, (sprache, erwartet, gefunden)


def test_der_lobbycode_ist_wirklich_sechsstellig(fassungen):
    """Ein Kennzeichen plus fuenf Zeichen — die Sechs im Text ist keine
    ungefaehre Angabe, sondern das, was der Client zum Beitreten annimmt."""
    from src.net import servers
    assert servers.for_code("HABCD") is None, "zu kurz muss abgewiesen werden"
    for sprache, inhalt in fassungen.items():
        niedrig = inhalt.lower()
        assert "sechsstellig" in niedrig or "six-character" in niedrig, sprache


# --------------------------------------------------------------------------
# Die beiden Fassungen gegeneinander


def test_beide_fassungen_nennen_dieselben_zahlen(fassungen):
    """Sonst liest ein deutscher Besucher etwas anderes als ein englischer.

    Verglichen wird die Menge aller Zahlen im Fliesstext. Versionsnummern und
    Ueberschriftennummern gibt es in diesem Teil des Texts nicht.
    """
    zahlen = {}
    for sprache, inhalt in fassungen.items():
        ohne_code = re.sub(r"`[^`]*`", "", inhalt)      # xattr-Befehl, Tasten
        ohne_titel = re.sub(r"^#+ \d+\..*$", "", ohne_code, flags=re.MULTILINE)
        zahlen[sprache] = sorted(set(re.findall(r"\d+", ohne_titel)))
    deutsch, englisch = zahlen["Deutsch"], zahlen["English"]
    assert deutsch == englisch, (
        f"nur deutsch: {sorted(set(deutsch) - set(englisch))}, "
        f"nur englisch: {sorted(set(englisch) - set(deutsch))}")


def test_beide_fassungen_haben_dieselben_abschnitte(fassungen):
    """Ein Abschnitt, den es nur in einer Sprache gibt, ist ein vergessener
    Uebersetzungsschritt — meist beim Nachtragen einer neuen Funktion."""
    anzahl = {s: len(re.findall(r"^## ", i, flags=re.MULTILINE))
              for s, i in fassungen.items()}
    assert anzahl["Deutsch"] == anzahl["English"], anzahl


# --------------------------------------------------------------------------
# Was bewusst *nicht* dasteht


def test_der_hinweis_auf_klartext_steht_nicht_auf_der_verkaufsseite(text):
    """Am 05.08.2026 entschieden, hier in der Gegenrichtung festgehalten.

    ``tests/test_block_f.py`` haelt dieselbe Entscheidung fuer die Info-Seite im
    Spiel; die itch.io-Seite ist der zweite Ort, an dem der Satz nicht stehen
    soll. Am Verkehr aendert das nichts — er ist unveraendert im Klartext, und
    das steht in ``release_1_0_plan.md`` H1 und §9.
    """
    verboten = ("unverschlüsselt", "unencrypted", "Klartext", "plain text",
                "plaintext")
    # Der Pflegeteil am Ende darf ueber den Text reden, der Text nicht.
    seite = text.split("## Hinweise zum Pflegen")[0]
    treffer = [w for w in verboten if w.lower() in seite.lower()]
    assert treffer == [], treffer


def test_kein_toter_verweis_auf_das_alte_repo(text):
    """``philip1307/Fahr-Rennspiel-2D`` gibt es nicht — der Link stand bis zum
    07.08.2026 auf der Seite und fuehrte ins Leere."""
    seite = text.split("## Hinweise zum Pflegen")[0]
    assert "philip1307" not in seite


def test_die_seite_verspricht_keine_signatur(text):
    """Kein Zertifikat gekauft (05.08.2026) — die Warnung beim ersten Start
    bleibt, und der Text muss sie ansprechen statt sie zu verschweigen."""
    niedrig = text.lower()
    assert "unbekannter herausgeber" in niedrig
    assert "unknown publisher" in niedrig


# --------------------------------------------------------------------------
# Die HTML-Fassung, die wirklich eingefuegt wird


def test_die_html_fassung_nennt_dieselben_zahlen_wie_der_text(html, fassungen):
    """Zwei Dateien mit denselben Aussagen driften auseinander, sobald sich eine
    aendert. Der Test haelt sie zusammen.

    Verglichen werden die Angaben **ueber das Spiel**, nicht jede Ziffer:
    Nummern von Aufzaehlungen und die Zeichengrenze der Kurzbeschreibung sagen
    nichts ueber das Spiel und stehen naturgemaess nur in einer der beiden
    Dateien.
    """
    englisch = fassungen["English"]
    for woerter in (("cars",), ("classes",), ("game modes",),
                    ("colours", "colors"), ("finishes",), ("tracks",),
                    ("players",)):
        aus_text = _zahl_vor(englisch, *woerter)
        aus_html = _zahl_vor(html, *woerter)
        assert aus_text == aus_html, (woerter, aus_text, aus_html)


def test_die_html_fassung_stimmt_mit_dem_spiel_ueberein(html):
    """Dieselben Pruefungen wie fuer den Text — an der Datei, die zaehlt."""
    with open(os.path.join(_ROOT, "data", "vehicles", "lacke.json"),
              encoding="utf-8") as f:
        lacke = json.load(f)
    ordner = os.path.join(_ROOT, "data", "tracks")
    strecken = [n for n in os.listdir(ordner) if n.endswith(".json")]

    erwartet = {
        ("cars",): str(len(race_setup.CLASSES["Alle"])),
        ("classes",): str(len(race_setup.CLASSES) - 1),
        ("game modes",): str(len(race_setup.MODES)),
        ("colours", "colors"): str(len(lacke["farben"])),
        ("finishes",): str(len(lacke["finishes"])),
        ("tracks",): str(len(strecken)),
    }
    for woerter, zahl in erwartet.items():
        gefunden = _zahl_vor(html, *woerter)
        assert zahl in gefunden, (woerter, zahl, gefunden)


def test_die_html_fassung_benutzt_nur_erlaubte_auszeichnungen(html):
    """itch.io saeubert das eingefuegte HTML.

    Was nicht auf der Liste steht, verschwindet beim Speichern — und zwar
    stillschweigend. Ein ``<div>`` mit Formatierung waere dann weg und die
    Seite saehe anders aus als hier.
    """
    with open(_HTML_PFAD, encoding="utf-8") as f:
        roh = f.read()

    erlaubt = {
        "p", "br", "hr", "strong", "em", "b", "i", "u", "s",
        "h1", "h2", "h3", "h4", "h5", "h6",
        "ul", "ol", "li", "a", "img", "blockquote", "code", "pre",
        "table", "thead", "tbody", "tr", "td", "th", "span",
    }
    benutzt = {m.lower() for m in re.findall(r"</?([a-zA-Z][a-zA-Z0-9]*)", roh)}
    verboten = sorted(benutzt - erlaubt)
    assert verboten == [], f"itch.io wirft diese Tags weg: {verboten}"


def test_die_html_fassung_ist_ein_ausschnitt_und_keine_ganze_seite(html):
    """Eingefuegt wird in ein Feld, nicht in einen Browser.

    ``<html>``, ``<head>`` oder ``<body>`` waeren dort falsch — itch.io baut
    die Seite drumherum selbst.
    """
    with open(_HTML_PFAD, encoding="utf-8") as f:
        roh = f.read().lower()
    for tag in ("<html", "<head", "<body", "<!doctype", "<script", "<style"):
        assert tag not in roh, f"{tag} gehoert nicht in das Beschreibungsfeld"


def test_die_html_fassung_enthaelt_keinen_deutschen_rest(html):
    """Nur Englisch, wie gewuenscht — ein vergessener Absatz faellt sonst erst
    auf der fertigen Seite auf."""
    verraeter = ["Fahrzeug", "Strecke", "Spieler", "Rennen", "Einstellungen",
                 "Werkstatt", "Lackier"]
    treffer = [w for w in verraeter if w in html]
    assert treffer == [], treffer
