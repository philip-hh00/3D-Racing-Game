"""Laub, das beim Näherkommen nicht „nachlädt".

Gemeldet am 27.09.2026: „Es ist sehr auffällig, wie Texturen z. B. von Laub
im Baum nachladen, wenn man etwas näher rankommt." Zwei Ursachen:

* **Mipmaps verlieren Deckung.** Eine Blattkarte wird mit ``alpha < 0.45``
  ausgestanzt. Die kleinen Mipstufen mitteln das Alpha — aus einem Blattrand
  mit 0/1 wird 0.3, und der fällt unter die Schwelle. Fern sind die Bäume
  deshalb licht und füllen sich beim Heranfahren. Abhilfe: das Alpha jeder
  Stufe so skalieren, dass derselbe Anteil über der Schwelle bleibt.
* **Harter LOD-Wechsel.** Siehe ``test_lod_ueberblendung``.
"""
from __future__ import annotations

import numpy as np

from src.render3d import mesh


def _blatt(groesse=256, seed=3):
    rng = np.random.default_rng(seed)
    alpha = np.zeros((groesse, groesse), dtype=np.float32)
    # Viele kleine Blätter: dünne Strukturen, genau die verschwinden in Mips.
    for _ in range(400):
        x, y = rng.integers(0, groesse, 2)
        alpha[max(0, y - 2):y + 2, max(0, x - 1):x + 1] = 1.0
    return alpha


def _deckung(alpha, schwelle):
    return float((alpha >= schwelle).mean())


def test_die_deckung_bleibt_in_allen_mipstufen_erhalten():
    alpha = _blatt()
    stufen = mesh.alpha_mipstufen(alpha, 0.45)
    ziel = _deckung(alpha, 0.45)
    assert len(stufen) >= 6
    for stufe in stufen[1:6]:
        assert abs(_deckung(stufe, 0.45) - ziel) < 0.05, "Stufe verliert oder gewinnt Laub"


def test_ohne_ausgleich_wuerde_das_laub_ausduennen():
    """Gegenprobe: einfaches Mitteln verliert fern tatsächlich Deckung."""
    alpha = _blatt()
    a = alpha
    for _ in range(4):
        a = a.reshape(a.shape[0] // 2, 2, a.shape[1] // 2, 2).mean(axis=(1, 3))
    assert _deckung(a, 0.45) < _deckung(alpha, 0.45) * 0.8
