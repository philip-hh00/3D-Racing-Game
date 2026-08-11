"""Jedes Zeichen, das das Spiel zeichnet, muss die Schrift auch haben.

Gefunden beim Nachstellen der Team-Lobby (Playtest 04.08.2026): in der
Fahrerliste stand nicht „√ Bereit", sondern **„□ Bereit"**. Die mitgelieferte
Segoe UI kennt weder ``✓`` (U+2713) noch ``√`` (U+221A) — Windows holt den Haken
aus Segoe UI Symbol, das nicht mit im Bündel liegt. Ein fehlender Glyph stürzt
nicht ab, er zeichnet ein leeres Kästchen, und deshalb hat es niemand gemeldet:
man sieht es nur, wenn man hinsieht.

Betroffen waren **elf Stellen** in sieben Dateien — Bereit in Lobby,
Ergebnisliste, Grand Prix und Rennpause, „gefahren" in der Streckenwahl,
„Version aktuell", „GESCHLOSSEN" im Editor — dazu ``⚠`` in den Editormeldungen,
``▶`` als Zeiger im Fahrzeuglabor und ``↕`` in den Bedienhinweisen.

Der Test prüft deshalb nicht die elf Stellen, sondern die Regel: **kein
Zeichenketten-Literal im Spiel und keine Übersetzung enthält ein Zeichen, das
die Schrift nicht zeichnen kann.** Damit fällt das nächste auf, bevor es
ausgeliefert wird.
"""
from __future__ import annotations

import ast
import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.ui import theme  # noqa: E402

#: Zeichen unterhalb davon sind Latein-1 und in jeder Schrift vorhanden; die
#: deutschen Umlaute fallen damit heraus und der Test bleibt schnell.
_HARMLOS = 0xFF

#: Zeichen aus dem privaten Bereich hat garantiert keine Schrift — sie zeichnen
#: genau das Kästchen, gegen das verglichen wird.
_PRIVAT = (0xE000, 0xE123, 0xF8FF)


def _bild(zeichen: str, groesse: int):
    """Das gezeichnete Bild eines Zeichens, oder ``None`` bei Nullbreite.

    Ein Zeichen ohne Breite (die unsichtbaren Steuerzeichen aus
    :mod:`src.net.servertext`) laesst sich nicht rendern — pygame wirft
    „Text has zero width". Das ist kein Kaestchen, sondern gar nichts.
    """
    try:
        flaeche = theme.font(groesse).render(zeichen, True, (255, 255, 255))
    except pygame.error:
        return None
    return pygame.image.tostring(flaeche, "RGB"), flaeche.get_size()


def _kastenbild(groesse: int):
    bilder = [_bild(chr(c), groesse) for c in _PRIVAT]
    assert bilder[0] == bilder[1] == bilder[2], \
        "Ersatzkästchen ist nicht eindeutig — der Test kann nichts erkennen"
    return bilder[0]


def hat_glyph(zeichen: str, groesse: int = theme.BODY) -> bool:
    """Ob die Schrift *zeichen* wirklich kennt.

    ``Font.metrics`` hilft hier nicht: es liefert auch für ein fehlendes Zeichen
    die Maße des Ersatzkästchens zurück. Verglichen wird deshalb das **Bild** mit
    dem eines Zeichens, das es sicher nicht gibt.
    """
    bild = _bild(zeichen, groesse)
    return bild is not None and bild != _kastenbild(groesse)


#: Module, deren Zeichenketten **nicht** gezeichnet werden.
#:
#: ``servertext`` fuehrt die Liste der unsichtbaren Zeichen, die aus Servertexten
#: **entfernt** werden (Block H, H2.12) — sie stehen dort, damit sie nie auf den
#: Bildschirm kommen. Sie hier zu verlangen waere das Gegenteil der Absicht.
NICHT_GEZEICHNET = {os.path.join("src", "net", "servertext.py")}


def _quelltexte() -> list[str]:
    pfade = []
    for wurzel, ordner, dateien in os.walk(os.path.join(_ROOT, "src")):
        ordner[:] = [o for o in ordner if o != "__pycache__"]
        for n in dateien:
            if not n.endswith(".py"):
                continue
            pfad = os.path.join(wurzel, n)
            if os.path.relpath(pfad, _ROOT) in NICHT_GEZEICHNET:
                continue
            pfade.append(pfad)
    return sorted(pfade)


def _literale(pfad: str) -> list[str]:
    """Alle Zeichenketten im Code — ohne Beschreibungen und Kommentare.

    In einer Beschreibung darf ``✓`` stehen; dort erklärt es ja gerade, warum
    man es nicht benutzen soll. Gezeichnet wird nur, was im Code steht.
    """
    baum = ast.parse(open(pfad, encoding="utf-8").read())
    beschreibungen = {
        id(ast.get_docstring(k, clean=False))
        for k in ast.walk(baum)
        if isinstance(k, (ast.Module, ast.ClassDef, ast.FunctionDef,
                          ast.AsyncFunctionDef))
    }
    return [k.value for k in ast.walk(baum)
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
            and id(k.value) not in beschreibungen]


def _verdaechtig(text: str) -> set[str]:
    return {z for z in text if ord(z) > _HARMLOS}


# ---------------------------------------------------------------------------
# Der Fund selbst
# ---------------------------------------------------------------------------
def test_der_haken_ist_wirklich_zu_sehen():
    """Der Kern: ``√`` und ``✓`` zeichnen beide ein leeres Kästchen."""
    assert not hat_glyph("√"), "sonst war der Fund keiner und der Test ist stumpf"
    assert not hat_glyph("✓")
    assert hat_glyph(theme.HAKEN), f"{theme.HAKEN!r} ist selbst ein Kästchen"


@pytest.mark.parametrize("name", ["HAKEN", "WARNUNG", "ZEIGER", "HOCH_RUNTER"])
def test_jedes_ersatzzeichen_hat_einen_glyph(name):
    for zeichen in getattr(theme, name):
        assert hat_glyph(zeichen), f"theme.{name}: {zeichen!r} fehlt der Schrift"


@pytest.mark.parametrize("groesse", ["HINT", "SMALL", "LABEL", "BODY",
                                     "HEADER", "TITLE"])
def test_die_ersatzzeichen_gelten_in_jeder_groesse(groesse):
    """Die Schrift wird je Größe neu geladen — ein Glyph fehlt entweder überall
    oder nirgends, aber geprüft ist besser als angenommen."""
    for zeichen in theme.HAKEN + theme.ZEIGER + theme.HOCH_RUNTER:
        assert hat_glyph(zeichen, getattr(theme, groesse))


# ---------------------------------------------------------------------------
# Die Regel
# ---------------------------------------------------------------------------
def test_kein_zeichen_im_quelltext_fehlt_der_schrift():
    fehlend: dict[str, list[str]] = {}
    for pfad in _quelltexte():
        for text in _literale(pfad):
            for zeichen in _verdaechtig(text):
                if not hat_glyph(zeichen):
                    fehlend.setdefault(
                        f"U+{ord(zeichen):04X} {zeichen!r}", []
                    ).append(os.path.relpath(pfad, _ROOT))
    assert not fehlend, "leere Kästchen im Spiel: " + json.dumps(
        {k: sorted(set(v)) for k, v in fehlend.items()}, ensure_ascii=False)


def test_keine_uebersetzung_bringt_ein_kaestchen_mitgebracht():
    """Eine Übersetzung ist genauso Anzeigetext wie das Original — und sie fällt
    beim Spielen auf Deutsch nie auf."""
    fehlend: dict[str, list[str]] = {}
    for datei in sorted(os.listdir(os.path.join(_ROOT, "data", "i18n"))):
        if not datei.endswith(".json"):
            continue
        tabelle = json.load(open(os.path.join(_ROOT, "data", "i18n", datei),
                                 encoding="utf-8"))
        for schluessel, wert in tabelle.items():
            for text in (schluessel, str(wert)):
                for zeichen in _verdaechtig(text):
                    if not hat_glyph(zeichen):
                        fehlend.setdefault(
                            f"U+{ord(zeichen):04X} {zeichen!r}", []
                        ).append(f"{datei}: {text[:40]}")
    assert not fehlend, "leere Kästchen in der Übersetzung: " + json.dumps(
        {k: sorted(set(v)) for k, v in fehlend.items()}, ensure_ascii=False)


def test_die_verzierung_steht_nicht_in_den_sprachdateien():
    """Ein Haken ist nichts zu Übersetzen. Steht er im Schlüssel, muss er in
    jeder Sprache einzeln getauscht werden — und genau das wurde vergessen."""
    for datei in os.listdir(os.path.join(_ROOT, "data", "i18n")):
        if not datei.endswith(".json"):
            continue
        tabelle = json.load(open(os.path.join(_ROOT, "data", "i18n", datei),
                                 encoding="utf-8"))
        for schluessel, wert in tabelle.items():
            for text in (schluessel, str(wert)):
                assert theme.HAKEN not in text, (datei, text)


def test_die_bedienhinweise_zeigen_lesbare_tasten():
    """Sie stehen unter jeder Seite — ein Kästchen dort sieht jeder ständig."""
    from src.ui import hints
    for tastatur, pad in hints._LABELS.values():
        for text in (tastatur, pad):
            for zeichen in _verdaechtig(text):
                assert hat_glyph(zeichen), (text, zeichen)
