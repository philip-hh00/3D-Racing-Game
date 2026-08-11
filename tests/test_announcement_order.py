"""Ankündigungen: die neueste ungesehene wird gezeigt.

Playtest-Fund vom 28.07.2026: es erschien immer dieselbe alte Ankündigung
zuerst. Zwei Ursachen kamen zusammen — die Auswahl nahm schlicht die erste
ungesehene in Dateireihenfolge, und in ``live_config.json`` stand bei einem
Eintrag als Jahr ``2626`` statt ``2026``. Der Tippfehler allein hätte diesen
Eintrag 600 Jahre lang zur "neuesten" gemacht.

Deshalb prüft dieser Test beides: die Sortierung und die ausgelieferten Daten.
"""
from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from src.states.menu_shell_state import newest_unseen_announcement  # noqa: E402


def _a(id_, date):
    return {"id": id_, "date": date, "text": {"de": id_}}


def test_neueste_gewinnt_unabhaengig_von_der_dateireihenfolge():
    ann = [_a("alt", "2026-01-01"), _a("neu", "2026-07-25"), _a("mittel", "2026-04-01")]
    assert newest_unseen_announcement(ann, set())["id"] == "neu"


def test_gesehene_werden_uebersprungen():
    ann = [_a("alt", "2026-01-01"), _a("neu", "2026-07-25")]
    assert newest_unseen_announcement(ann, {"neu"})["id"] == "alt"


def test_alles_gesehen_ergibt_nichts():
    ann = [_a("a", "2026-01-01"), _a("b", "2026-07-25")]
    assert newest_unseen_announcement(ann, {"a", "b"}) is None


def test_leere_liste():
    assert newest_unseen_announcement([], set()) is None


def test_eintraege_ohne_id_werden_ignoriert():
    ann = [{"date": "2026-12-31", "text": {}}, _a("gueltig", "2026-01-01")]
    assert newest_unseen_announcement(ann, set())["id"] == "gueltig"


def test_kaputte_eintraege_stuerzen_nicht_ab():
    ann = ["kein Objekt", None, 42, _a("gueltig", "2026-01-01")]
    assert newest_unseen_announcement(ann, set())["id"] == "gueltig"


def test_unlesbares_datum_draengelt_sich_nicht_vor():
    """Ohne brauchbares Datum hinten anstellen statt nach vorn rutschen."""
    ann = [_a("kaputt", "irgendwann"), _a("datiert", "2026-01-01")]
    assert newest_unseen_announcement(ann, set())["id"] == "datiert"


def test_fehlendes_datum_draengelt_sich_nicht_vor():
    ann = [{"id": "ohne_datum", "text": {"de": "x"}}, _a("datiert", "2026-01-01")]
    assert newest_unseen_announcement(ann, set())["id"] == "datiert"


def test_nur_undatierte_werden_trotzdem_gezeigt():
    ann = [{"id": "erste", "text": {"de": "x"}}, {"id": "zweite", "text": {"de": "y"}}]
    assert newest_unseen_announcement(ann, set())["id"] == "erste"


def test_eine_ankuendigung_ohne_text_wird_uebersprungen():
    """Sie wäre ein leeres Fenster, das der Spieler wegklicken muss. Seit der
    Säuberung aus Block H (H2.12) fällt sie durch — vorher öffnete sie sich."""
    ann = [{"id": "leer", "text": {}}, _a("mit_text", "2020-01-01")]
    assert newest_unseen_announcement(ann, set())["id"] == "mit_text"
    assert newest_unseen_announcement([{"id": "leer"}], set()) is None


def test_gleiches_datum_behaelt_dateireihenfolge():
    ann = [_a("erste", "2026-07-17"), _a("zweite", "2026-07-17")]
    assert newest_unseen_announcement(ann, set())["id"] == "erste"


# ── Die ausgelieferten Daten selbst ─────────────────────────────────────────

def test_live_config_hat_plausible_datumsangaben():
    """Fängt den 2626-Tippfehler und alles Ähnliche in Zukunft ab."""
    pfad = os.path.join(_ROOT, "server", "live_config.json")
    with open(pfad, encoding="utf-8") as f:
        cfg = json.load(f)
    for ann in cfg.get("announcements", []):
        datum = str(ann.get("date", ""))
        jahr = int(datum.split("-")[0])
        assert 2024 <= jahr <= 2100, (
            f"Ankündigung {ann.get('id')} hat das Jahr {jahr}: {datum}")


def test_live_config_ids_sind_eindeutig():
    pfad = os.path.join(_ROOT, "server", "live_config.json")
    with open(pfad, encoding="utf-8") as f:
        cfg = json.load(f)
    ids = [a.get("id") for a in cfg.get("announcements", [])]
    assert len(ids) == len(set(ids)), "doppelte Ankündigungs-IDs"
