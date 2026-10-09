"""Verwaltungswerkzeug tools/strecken_verwalten.py (Plan 1.1.0 §5).

Arbeitet auf denselben Dateien wie der Relay: ein Relay legt Strecken an, das
Werkzeug listet, versteckt, gibt frei und loescht, der Relay sieht die Aenderung.
"""
from __future__ import annotations

import asyncio
import os

from tests.strecken_hilfe import Relay, rundkurs, srv


def _lauf(coro):
    return asyncio.run(coro)


def _hoch(entwurf, **extra) -> dict:
    return {"type": "TRACK_UPLOAD", "track": entwurf, "author": "Anna", **extra}


def _werkzeug():
    import importlib.util
    pfad = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "tools", "strecken_verwalten.py")
    spec = importlib.util.spec_from_file_location("strecken_verwalten", pfad)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_werkzeug_list_freigeben_loeschen(tmp_path, capsys):
    w = _werkzeug()

    async def anlegen():
        async with Relay(str(tmp_path), pro_tag=99) as r:
            a = (await r.frage(_hoch(rundkurs(5, 4, name="Eins"))))["id"]
            b = (await r.frage(_hoch(rundkurs(6, 4, name="Zwei"))))["id"]
            srv.TRUSTED_PROXIES = frozenset({"127.0.0.1"})
            for n in range(3):                      # Zwei wird gemeldet und versteckt
                await r.frage({"type": "TRACK_REPORT", "id": b, "cid": f"melder{n}xxxx"})
            return a, b
    a, b = _lauf(anlegen())

    assert w.main(["--dir", str(tmp_path), "list"]) == 0
    aus = capsys.readouterr().out
    assert a in aus and b in aus and "VERSTECKT" in aus and "2 gespeichert" in aus
    assert w.main(["--dir", str(tmp_path), "list", "--versteckt"]) == 0
    aus = capsys.readouterr().out
    assert b in aus and a not in aus

    # Freigeben: wieder sichtbar, Meldungen null.
    assert w.main(["--dir", str(tmp_path), "freigeben", b]) == 0

    async def liste():
        async with Relay(str(tmp_path)) as r:
            return (await r.frage({"type": "TRACK_LIST"}))["total"]
    assert _lauf(liste()) == 2

    # Loeschen: weg, Datei auch; unbekannte und ungueltige Kennungen geben Fehler.
    assert w.main(["--dir", str(tmp_path), "loeschen", a, "deadbeef", "xyz"]) == 1
    assert not os.path.exists(tmp_path / f"{a}.json")

    async def nochmal():
        async with Relay(str(tmp_path), pro_tag=99) as r:
            assert (await r.frage({"type": "TRACK_LIST"}))["total"] == 1
            # Das Duplikat darf nach dem Loeschen wieder hoch.
            return (await r.frage(_hoch(rundkurs(5, 4, name="Eins"))))["type"]
    assert _lauf(nochmal()) == "TRACK_UPLOAD_OK"


def test_werkzeug_verstecken_zeige_und_fehler(tmp_path, capsys):
    w = _werkzeug()

    async def anlegen():
        async with Relay(str(tmp_path)) as r:
            return (await r.frage(_hoch(rundkurs())))["id"]
    tid = _lauf(anlegen())
    assert w.main(["--dir", str(tmp_path), "verstecken", tid]) == 0
    assert w.main(["--dir", str(tmp_path), "zeige", tid]) == 0
    assert "hidden      True" in capsys.readouterr().out
    assert w.main(["--dir", str(tmp_path), "zeige", "00000000"]) == 1
    assert w.main(["--dir", str(tmp_path / "gibtsnicht"), "list"]) == 2
