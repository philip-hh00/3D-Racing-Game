"""Der Streckeneditor darf nicht abstuerzen, wenn ein Bauteil waehrend des
Verschiebens geloescht oder rueckgaengig gemacht wird.

``_moving_idx`` zeigte dann auf einen Index, der es nicht mehr gab —
``render`` und ``_drop_moving`` stuerzten ab oder verschieben das falsche
Bauteil. Die Tests sichern ab, dass der Index in so einer Situation sauber
zurueckgesetzt wird.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.core import profile  # noqa: E402
from tests import spielhilfe  # noqa: E402


@pytest.fixture(autouse=True)
def _aufbau_bewahren(monkeypatch):
    spielhilfe.aufbau_bewahren(monkeypatch)


@pytest.fixture
def spielstand(monkeypatch):
    p = profile.Profile(username="Testfahrer")
    p.save = lambda: None
    p.statistik = {}
    monkeypatch.setattr(profile, "_current", p, raising=False)
    monkeypatch.setattr(profile, "current", lambda: p)
    return p


class _Maschine:
    """Eine Zustandsmaschine, die Wechsel merkt, statt sie zu gehen."""

    def __init__(self) -> None:
        self.wechsel: list[tuple[str, dict]] = []
        self.zurueck_zaehler = 0

    def change(self, name: str, **kw) -> None:
        self.wechsel.append((name, kw))

    def go_back(self) -> None:
        self.zurueck_zaehler += 1

    def push(self, name: str, **kw) -> None:
        self.wechsel.append((name, kw))

    def pop(self) -> None:
        self.zurueck_zaehler += 1


@pytest.fixture
def editor(spielstand):
    from src.states.editor_state import EditorState
    from src.track.tile_track import TileTrackDraft

    z = EditorState(_Maschine())
    z.enter()
    z.draft = TileTrackDraft.new_with_start()
    z._mode = "edit"
    return z


def test_loeschen_waehrend_verschieben(editor):
    """Geloescht wird das Bauteil, das gerade verschoben wird: Der Index
    muss zurueckgesetzt werden, sonst greift ``render`` auf ein Bauteil zu,
    das es nicht mehr gibt."""
    z = editor
    idx = len(z.draft.pieces) - 1
    z._push_undo()
    z._moving_idx = idx
    z._delete_piece(idx)
    z.render(pygame.Surface((1920, 1080)))
    assert z._moving_idx is None


def test_ungueltiger_index_stuerzt_nicht_ab(editor):
    """Ein Index auesserhalb der Liste (z. B. nach einem fremden Loeschen)
    darf weder bei ``render`` noch bei ``_drop_moving`` stuerzen — er wird
    einfach verworfen."""
    z = editor
    z._moving_idx = len(z.draft.pieces) + 3
    z.render(pygame.Surface((1920, 1080)))
    assert z._moving_idx is None
    z._moving_idx = len(z.draft.pieces) + 3
    z._drop_moving(500, 500)
    assert z._moving_idx is None


def test_rueckgaengig_waehrend_verschieben(editor):
    """Rueckgaengig macht die Aenderung ungeschehen, die das gewaehlte
    Bauteil betraf: Der Index zeigt auf ein anderes Bauteil und wird
    verworfen, statt das falsche zu verschieben."""
    z = editor
    anzahl = len(z.draft.pieces)
    z._push_undo()
    z._moving_idx = 0
    z._undo_action()
    assert z._moving_idx is None
    z.render(pygame.Surface((1920, 1080)))
    assert len(z.draft.pieces) == anzahl


def test_wiederholen_waehrend_verschieben(editor):
    """Wie Rueckgaengig, aber in die andere Richtung: Wiederholen waehrend
    des Verschiebens darf nicht stuerzen."""
    z = editor
    z._push_undo()
    z._moving_idx = 0
    z._redo_action()
    assert z._moving_idx is None
    z.render(pygame.Surface((1920, 1080)))
