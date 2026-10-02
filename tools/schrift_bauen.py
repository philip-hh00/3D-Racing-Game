"""Baut data/fonts/NotoSans-Spiel.ttf: Noto Sans plus die Pfeile und Formen,
die das Spiel zeichnet.

    .venv\Scripts\python.exe tools\schrift_bauen.py

Noto Sans selbst kennt weder ``← ↑ → ↓ ↔`` noch ``● ○ ■ ▪ ► ▲ ▼ ♦``. Die kommen
aus Noto Sans Symbols 2 (Formen) und Noto Sans Math (Pfeile) und werden als
eigene Glyphen in die Grundschrift kopiert — pygame kennt keine Ersatzschrift,
ein fehlendes Zeichen wird ein leeres Kästchen (tests/test_schriftzeichen.py).

Alle drei stehen unter der SIL Open Font License ohne reservierten
Schriftnamen; die geänderte Fassung heißt trotzdem „Noto Sans Spiel“, damit
man sie von der Vorlage unterscheiden kann. Lizenz: data/fonts/OFL.txt.

Ersetzt am 02.10.2026 die mitgelieferte Segoe UI, die als Microsoft-Schrift
nicht weitergegeben werden darf.
"""
from __future__ import annotations

import sys
import tempfile
import urllib.request
from pathlib import Path

from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

WURZEL = Path(__file__).resolve().parents[1]
ZIEL = WURZEL / "data" / "fonts" / "NotoSans-Spiel.ttf"
QUELLE = "https://github.com/notofonts/notofonts.github.io/raw/main/fonts/{0}/hinted/ttf/{0}-Regular.ttf"

#: Zeichen je Spenderschrift. Etwas mehr als heute benutzt (✓ ★ ⚠ ▶ √ ↕), damit
#: die naheliegenden Zeichen beim nächsten Mal einfach funktionieren.
SPENDER = {
    "NotoSansSymbols2": "♦●■○▲▼▪►✓★▶⚠◀",
    "NotoSansMath": "→↑←↓↔√↕↺↻",
}


def _laden(name: str, ordner: Path) -> TTFont:
    pfad = ordner / f"{name}-Regular.ttf"
    if not pfad.exists():
        urllib.request.urlretrieve(QUELLE.format(name), pfad)
    return TTFont(pfad)


def bauen(ziel: Path = ZIEL) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ordner = Path(tmp)
        basis = _laden("NotoSans", ordner)
        glyf, hmtx = basis["glyf"], basis["hmtx"]
        basis.getGlyphOrder()
        neu = []
        for name, zeichen in SPENDER.items():
            spender = _laden(name, ordner)
            glyphen, cmap = spender.getGlyphSet(), spender.getBestCmap()
            for z in zeichen:
                cp = ord(z)
                if cp in basis.getBestCmap():
                    continue
                quelle, glyphname = cmap[cp], f"uni{cp:04X}"
                stift = TTGlyphPen(None)
                glyphen[quelle].draw(stift)          # Komponenten aufgelöst
                g = stift.glyph()
                glyf[glyphname] = g
                g.recalcBounds(glyf)
                hmtx[glyphname] = (spender["hmtx"][quelle][0], getattr(g, "xMin", 0))
                neu.append((cp, glyphname))
        basis.setGlyphOrder(list(glyf.glyphOrder))
        for tab in basis["cmap"].tables:
            if tab.isUnicode():
                for cp, glyphname in neu:
                    tab.cmap[cp] = glyphname
        for rec in basis["name"].names:
            if rec.nameID in (1, 3, 4, 16):
                rec.string = rec.toUnicode().replace("Noto Sans", "Noto Sans Spiel")
            elif rec.nameID == 6:
                rec.string = rec.toUnicode().replace("NotoSans", "NotoSansSpiel")
        basis.save(ziel)
    print(f"{ziel}: {len(neu)} Zeichen ergänzt")


if __name__ == "__main__":
    bauen(Path(sys.argv[1]) if len(sys.argv) > 1 else ZIEL)
