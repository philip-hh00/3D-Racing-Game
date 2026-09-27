"""Spieldateien gegen Austausch prüfen (Release 1.0.0).

Die Fahrwerte stehen im ausgelieferten Paket als offenes JSON
(``data/vehicles/*.json``): Motorleistung, Grip, Bremskraft. Wer dort eine
Zahl ändert, fährt online schneller als die anderen. Beim Bauen werden die
spielrelevanten Dateien deshalb gehasht und die Liste signiert; das Spiel
prüft sie beim Start. Stimmt etwas nicht, ist Online gesperrt — offline darf
jeder mit seinen eigenen Dateien machen, was er will.
"""
from __future__ import annotations

import json

from src.core import integritaet


def _baum(tmp_path):
    (tmp_path / "data" / "vehicles").mkdir(parents=True)
    (tmp_path / "data" / "tracks").mkdir(parents=True)
    (tmp_path / "data" / "settings").mkdir(parents=True)
    (tmp_path / "data" / "vehicles" / "rookie.json").write_text(
        json.dumps({"physics": {"engine_power": 100.0}}), encoding="utf-8")
    (tmp_path / "data" / "tracks" / "oval.json").write_text("{}", encoding="utf-8")
    return tmp_path


def test_unveraenderte_dateien_bestehen(tmp_path):
    w = _baum(tmp_path)
    integritaet.schreiben(w)
    e = integritaet.pruefen(w)
    assert e.ok and not e.abweichend
    assert len(e.digest) == 64


def test_geaenderte_fahrwerte_fallen_auf(tmp_path):
    w = _baum(tmp_path)
    integritaet.schreiben(w)
    (w / "data" / "vehicles" / "rookie.json").write_text(
        json.dumps({"physics": {"engine_power": 999.0}}), encoding="utf-8")
    e = integritaet.pruefen(w)
    assert not e.ok
    assert "data/vehicles/rookie.json" in e.abweichend


def test_neue_und_fehlende_dateien_fallen_auf(tmp_path):
    w = _baum(tmp_path)
    integritaet.schreiben(w)
    (w / "data" / "vehicles" / "turbo.json").write_text("{}", encoding="utf-8")
    assert not integritaet.pruefen(w).ok
    (w / "data" / "vehicles" / "turbo.json").unlink()
    (w / "data" / "tracks" / "oval.json").unlink()
    assert not integritaet.pruefen(w).ok


def test_eine_nachgerechnete_liste_ohne_schluessel_faellt_auf(tmp_path):
    """Die Liste selbst zu fälschen reicht nicht: sie ist signiert."""
    w = _baum(tmp_path)
    integritaet.schreiben(w)
    (w / "data" / "vehicles" / "rookie.json").write_text("{}", encoding="utf-8")
    pfad = w / integritaet.LISTE
    liste = json.loads(pfad.read_text(encoding="utf-8"))
    liste["dateien"] = integritaet.hashes(w)
    pfad.write_text(json.dumps(liste), encoding="utf-8")
    assert not integritaet.pruefen(w).ok


def test_ohne_liste_nur_im_quelltext_in_ordnung(tmp_path):
    w = _baum(tmp_path)
    assert integritaet.pruefen(w, ausgeliefert=False).ok
    assert not integritaet.pruefen(w, ausgeliefert=True).ok
