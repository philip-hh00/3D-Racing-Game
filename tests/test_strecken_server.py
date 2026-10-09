"""Streckenaustausch auf dem Relay: Pruefung, Grenzen, Ablage (Plan 1.1.0 §5).

Alles gegen einen echten Relay auf einem freien Port (``Relay``), mit eigenem
Speicherverzeichnis je Test. Zusaetzlich: die Regeln des Servers gegen die des
Spiels (``TileTrackDraft``), damit sie nicht auseinanderlaufen, und ein alter
Client, der nichts von alledem kennt.
"""
from __future__ import annotations

import asyncio
import json
import os

import pytest

from tests.strecken_hilfe import Relay, empfangen, kopie, rundkurs, senden, srv


def _lauf(coro):
    return asyncio.run(coro)


def _hoch(entwurf, **extra) -> dict:
    return {"type": "TRACK_UPLOAD", "track": entwurf, "author": "Anna", **extra}


# --------------------------------------------------------------------------
# Pruefung des Entwurfs
# --------------------------------------------------------------------------

def test_gueltiger_entwurf_wird_angenommen():
    sauber, angaben = srv.entwurf_pruefen(rundkurs())
    assert sauber["name"] == "Testrunde"
    assert angaben["teile"] == len(sauber["pieces"])
    assert 8000 < angaben["laenge"] < 10000
    assert all(0 <= x <= 255 and 0 <= y <= 255 for x, y in angaben["umriss"])
    assert 8 <= len(angaben["umriss"]) <= 48


@pytest.mark.parametrize("aendern", [
    lambda d: d.pop("pieces"),
    lambda d: d.update(pieces="viele"),
    lambda d: d.update(extra="x"),
    lambda d: d.update(version=2),
    lambda d: d.update(version=True),
    lambda d: d.update(width=1e9),
    lambda d: d.update(width=float("nan")),
    lambda d: d.update(width="breit"),
    lambda d: d.update(difficulty="Brutal"),
    lambda d: d.update(background_texture="../../etc"),
    lambda d: d.update(background_texture=""),
    lambda d: d.update(name=5),
    lambda d: d.update(start_piece_idx=999),
    lambda d: d.update(start_piece_idx=-1),
    lambda d: d.update(start_piece_idx=True),
    lambda d: d["pieces"][0].update(kind="tunnel"),
    lambda d: d["pieces"][0].update(rotation=4),
    lambda d: d["pieces"][0].update(col=10 ** 6),
    lambda d: d["pieces"][0].update(col=1.5),
    lambda d: d["pieces"][0].update(radius_cells=9),
    lambda d: d["pieces"][0].update(zusatz=1),
    lambda d: d["pieces"][0].pop("row"),
    lambda d: d["pieces"].__setitem__(0, "gerade"),
    lambda d: d.update(pieces=d["pieces"][:3]),
    lambda d: d.update(pieces=d["pieces"] * 12),
])
def test_schema_verstoesse_werden_abgewiesen(aendern):
    d = rundkurs()
    aendern(d)
    with pytest.raises(srv._StreckenFehler) as f:
        srv.entwurf_pruefen(d)
    assert f.value.code in ("BAD_FORMAT", "BAD_TRACK")


def test_kein_dict_wird_abgewiesen():
    for roh in (None, [], "x", 5):
        with pytest.raises(srv._StreckenFehler):
            srv.entwurf_pruefen(roh)


def test_offene_strecke_ist_nicht_fahrbar():
    d = rundkurs()
    del d["pieces"][10]
    with pytest.raises(srv._StreckenFehler) as f:
        srv.entwurf_pruefen(d)
    assert f.value.code == "BAD_TRACK"


def test_ueberlappung_ist_nicht_fahrbar():
    d = rundkurs()
    d["pieces"].append(dict(d["pieces"][1]))
    with pytest.raises(srv._StreckenFehler) as f:
        srv.entwurf_pruefen(d)
    assert f.value.code == "BAD_TRACK"


def test_start_braucht_gerade_mit_gerader_davor():
    d = rundkurs()
    d["start_piece_idx"] = 0               # eine Kurve
    with pytest.raises(srv._StreckenFehler):
        srv.entwurf_pruefen(d)
    d["start_piece_idx"] = 1               # Gerade, aber davor die Kurve
    with pytest.raises(srv._StreckenFehler):
        srv.entwurf_pruefen(d)


def test_zu_kurze_strecke_wird_abgewiesen():
    d = rundkurs(3, 3)                      # 4 Ecken + 4 Geraden: ~2900 px
    with pytest.raises(srv._StreckenFehler) as f:
        srv.entwurf_pruefen(d)
    assert f.value.code == "BAD_TRACK"


def test_zwei_getrennte_runden_sind_nicht_fahrbar():
    a = rundkurs(5, 4)
    b = rundkurs(5, 4, versatz=(20, 20))
    d = kopie(a)
    d["pieces"] += b["pieces"]
    with pytest.raises(srv._StreckenFehler) as f:
        srv.entwurf_pruefen(d)
    assert f.value.code == "BAD_TRACK"


def test_namen_werden_gesaeubert():
    d = rundkurs(name="Böse\n‮Name <b>fett</b>" + "x" * 80)
    sauber, _ = srv.entwurf_pruefen(d)
    assert "\n" not in sauber["name"] and "‮" not in sauber["name"]
    assert "<" not in sauber["name"]
    assert len(sauber["name"]) <= 40
    d = rundkurs(name="‮\u0007")
    assert srv.entwurf_pruefen(d)[0]["name"] == "Strecke"


def test_hash_ignoriert_namen_und_lage():
    a = rundkurs(name="Eins")
    b = rundkurs(name="Zwei", versatz=(7, -3))
    assert srv.entwurf_hash(srv.entwurf_pruefen(a)[0]) == srv.entwurf_hash(srv.entwurf_pruefen(b)[0])
    c = rundkurs(9, 6)
    assert srv.entwurf_hash(srv.entwurf_pruefen(c)[0]) != srv.entwurf_hash(srv.entwurf_pruefen(a)[0])


# --------------------------------------------------------------------------
# Server und Spiel muessen dieselbe Strecke gleich beurteilen
# --------------------------------------------------------------------------

@pytest.mark.parametrize("groesse", [(8, 6), (5, 4), (12, 9), (7, 7)])
def test_server_und_spiel_sind_sich_einig(groesse):
    import math
    from src.track.tile_track import TileTrackDraft
    d = rundkurs(*groesse)
    spiel = TileTrackDraft.from_draft_dict(d)
    assert spiel.is_closed_loop() and spiel.start_straight_ok()
    assert spiel.validate_game() == []
    _, angaben = srv.entwurf_pruefen(d)
    cl = spiel.to_centerline()
    laenge = sum(math.dist(cl[i], cl[(i + 1) % len(cl)]) for i in range(len(cl)))
    assert angaben["laenge"] == pytest.approx(laenge, rel=0.01)


def test_server_lehnt_ab_was_das_spiel_offen_nennt():
    from src.track.tile_track import TileTrackDraft
    d = rundkurs()
    del d["pieces"][7]
    d["start_piece_idx"] = 3
    assert not TileTrackDraft.from_draft_dict(d).is_closed_loop()
    with pytest.raises(srv._StreckenFehler):
        srv.entwurf_pruefen(d)


# --------------------------------------------------------------------------
# Ende zu Ende ueber das Netz
# --------------------------------------------------------------------------

def test_hochladen_liste_holen_melden(tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as r:
            ok = await r.frage(_hoch(rundkurs(name="Alpenring")))
            assert ok["type"] == "TRACK_UPLOAD_OK", ok
            tid = ok["id"]

            liste = await r.frage({"type": "TRACK_LIST"})
            assert liste["type"] == "TRACK_LIST"
            assert liste["total"] == 1 and liste["pages"] == 1
            e = liste["tracks"][0]
            assert e["id"] == tid and e["name"] == "Alpenring" and e["author"] == "Anna"
            assert e["theme"] == "Plains" and e["downloads"] == 0 and e["length"] > 8000
            assert e["pieces"] == 24 and len(e["outline"]) > 4
            assert "track" not in e                    # Liste traegt keine Daten

            geholt = await r.frage({"type": "TRACK_GET", "id": tid})
            assert geholt["type"] == "TRACK_DATA" and geholt["track"]["name"] == "Alpenring"
            assert geholt["track"]["pieces"] == srv.entwurf_pruefen(rundkurs())[0]["pieces"]

            liste = await r.frage({"type": "TRACK_LIST"})
            assert liste["tracks"][0]["downloads"] == 1

            m = await r.frage({"type": "TRACK_REPORT", "id": tid})
            assert m == {"type": "TRACK_REPORT_OK", "id": tid, "hidden": False}
    _lauf(go())


def test_unbekannte_und_boese_ids(tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as r:
            for tid in ("deadbeef", "../index", "", "ABCDEF12", "x" * 300, 5, None):
                a = await r.frage({"type": "TRACK_GET", "id": tid})
                assert a["type"] == "TRACK_ERROR" and a["code"] == "NOT_FOUND", (tid, a)
                a = await r.frage({"type": "TRACK_REPORT", "id": tid})
                assert a["code"] == "NOT_FOUND"
    _lauf(go())


def test_zu_grosser_upload(tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as r:
            d = rundkurs()
            d["description"] = "x" * (80 * 1024)
            a = await r.frage(_hoch(d))
            assert a["type"] == "TRACK_ERROR" and a["code"] == "TOO_LARGE"
            assert srv.strecken_speicher().belegt()[0] == 0
    _lauf(go())


def test_ungueltiger_upload_wird_abgewiesen_und_nichts_gespeichert(tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as r:
            d = rundkurs()
            d["pieces"][2]["kind"] = "kaputt"
            a = await r.frage(_hoch(d))
            assert a["type"] == "TRACK_ERROR" and a["code"] == "BAD_FORMAT"
            a = await r.frage({"type": "TRACK_UPLOAD"})
            assert a["code"] == "BAD_FORMAT"
            a = await r.frage({"type": "TRACK_UPLOAD", "track": [1, 2]})
            assert a["code"] == "BAD_FORMAT"
            assert srv.strecken_speicher().belegt()[0] == 0
            assert [n for n in os.listdir(tmp_path) if n != "index.json"] == []
    _lauf(go())


def test_doppelte_strecke_wird_abgewiesen(tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as r:
            assert (await r.frage(_hoch(rundkurs(name="Eins"))))["type"] == "TRACK_UPLOAD_OK"
            a = await r.frage(_hoch(rundkurs(name="Zwei", versatz=(5, 5)), cid="x"))
            assert a["type"] == "TRACK_ERROR" and a["code"] == "DUPLICATE"
            assert (await r.frage(_hoch(rundkurs(9, 6))))["type"] == "TRACK_UPLOAD_OK"
    _lauf(go())


def test_upload_name_und_autor_werden_gesaeubert(tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as r:
            a = await r.frage({"type": "TRACK_UPLOAD", "track": rundkurs(),
                               "name": "Neu‮<x>", "author": "A\nB\u0000‮C" + "d" * 50})
            assert a["type"] == "TRACK_UPLOAD_OK"
            e = (await r.frage({"type": "TRACK_LIST"}))["tracks"][0]
            assert "<" not in e["name"] and "‮" not in e["name"]
            assert "\n" not in e["author"] and len(e["author"]) <= 20
    _lauf(go())


def test_tagesgrenze_je_absender(tmp_path):
    async def go():
        async with Relay(str(tmp_path), pro_tag=2) as r:
            for n in range(2):
                a = await r.frage(_hoch(rundkurs(5 + n, 4)))
                assert a["type"] == "TRACK_UPLOAD_OK", a
            a = await r.frage(_hoch(rundkurs(12, 4)))
            assert a["type"] == "TRACK_ERROR" and a["code"] == "LIMIT_DAY"
            assert "heute" in a["reason"]
    _lauf(go())


def test_tagesgrenze_gilt_am_naechsten_tag_nicht_mehr(tmp_path, monkeypatch):
    async def go():
        async with Relay(str(tmp_path), pro_tag=1) as r:
            assert (await r.frage(_hoch(rundkurs(5, 4))))["type"] == "TRACK_UPLOAD_OK"
            assert (await r.frage(_hoch(rundkurs(6, 4))))["code"] == "LIMIT_DAY"
            sp = srv.strecken_speicher()
            sp.tag = "2000-01-01"                       # der Zaehler ist von gestern
            assert (await r.frage(_hoch(rundkurs(6, 4))))["type"] == "TRACK_UPLOAD_OK"
    _lauf(go())


def test_hinter_tunnel_zaehlt_die_kennung(tmp_path):
    """Hamburg: alle kommen von 127.0.0.1 — jede Kennung hat ihr eigenes Konto."""
    async def go():
        async with Relay(str(tmp_path), pro_tag=1) as r:
            srv.TRUSTED_PROXIES = frozenset({"127.0.0.1"})
            a = await r.frage(_hoch(rundkurs(5, 4), cid="aaaaaaaa11"))
            b = await r.frage(_hoch(rundkurs(6, 4), cid="bbbbbbbb22"))
            assert a["type"] == "TRACK_UPLOAD_OK" and b["type"] == "TRACK_UPLOAD_OK"
            c = await r.frage(_hoch(rundkurs(7, 4), cid="aaaaaaaa11"))
            assert c["code"] == "LIMIT_DAY"
            # Ohne Kennung: ein grosses gemeinsames Konto (10 x), nicht 1.
            for n in range(10):
                z = await r.frage(_hoch(rundkurs(8 + n, 4)))
                assert z["type"] == "TRACK_UPLOAD_OK", (n, z)
            assert (await r.frage(_hoch(rundkurs(30, 4))))["code"] == "LIMIT_DAY"
    _lauf(go())


def test_speicher_voll_nach_anzahl(tmp_path):
    async def go():
        async with Relay(str(tmp_path), max_stueck=2, pro_tag=99) as r:
            for n in range(2):
                assert (await r.frage(_hoch(rundkurs(5 + n, 4))))["type"] == "TRACK_UPLOAD_OK"
            a = await r.frage(_hoch(rundkurs(9, 4)))
            assert a["type"] == "TRACK_ERROR" and a["code"] == "STORE_FULL"
            assert "voll" in a["reason"]
            # Lesen geht weiter.
            assert (await r.frage({"type": "TRACK_LIST"}))["total"] == 2
    _lauf(go())


def test_speicher_voll_nach_groesse(tmp_path):
    async def go():
        async with Relay(str(tmp_path), max_mb=0.003, pro_tag=99) as r:    # ~3 KB
            assert (await r.frage(_hoch(rundkurs(5, 4))))["type"] == "TRACK_UPLOAD_OK"
            assert (await r.frage(_hoch(rundkurs(6, 4))))["code"] == "STORE_FULL"
    _lauf(go())


def test_drei_verschiedene_melder_verstecken_die_strecke(tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as r:
            tid = (await r.frage(_hoch(rundkurs())))["id"]
            srv.TRUSTED_PROXIES = frozenset({"127.0.0.1"})        # Kennung statt IP
            ids = ["m1m1m1m1m1", "m2m2m2m2m2", "m3m3m3m3m3"]
            a = await r.frage({"type": "TRACK_REPORT", "id": tid, "cid": ids[0]})
            assert a["hidden"] is False
            # Derselbe Melder zaehlt nicht doppelt.
            a = await r.frage({"type": "TRACK_REPORT", "id": tid, "cid": ids[0]})
            assert a["hidden"] is False
            a = await r.frage({"type": "TRACK_REPORT", "id": tid, "cid": ids[1]})
            assert a["hidden"] is False
            assert (await r.frage({"type": "TRACK_LIST"}))["total"] == 1
            a = await r.frage({"type": "TRACK_REPORT", "id": tid, "cid": ids[2]})
            assert a["hidden"] is True
            assert (await r.frage({"type": "TRACK_LIST"}))["total"] == 0
            g = await r.frage({"type": "TRACK_GET", "id": tid})
            assert g["code"] == "NOT_FOUND"
            # Und sie bleibt als Duplikat gesperrt.
            srv.TRUSTED_PROXIES = frozenset()
            assert (await r.frage(_hoch(rundkurs(name="Neu"))))["code"] == "DUPLICATE"
    _lauf(go())


def test_gleiche_ip_meldet_nur_einmal(tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as r:
            tid = (await r.frage(_hoch(rundkurs())))["id"]
            for _ in range(5):
                a = await r.frage({"type": "TRACK_REPORT", "id": tid})
            assert a["hidden"] is False
    _lauf(go())


def test_liste_sortierung_suche_und_seiten(tmp_path):
    async def go():
        async with Relay(str(tmp_path), pro_tag=99) as r:
            namen = ["Alpha", "Beta", "Gamma", "Delta", "Alpine"]
            ids = []
            for n, name in enumerate(namen):
                ids.append((await r.frage(_hoch(rundkurs(5 + n, 4, name=name))))["id"])
                # Erstellzeit pro Strecke unterscheidbar machen.
                srv.strecken_speicher().tracks[ids[-1]]["created"] = 1000 + n
            # Gamma bekommt die meisten Abrufe.
            for _ in range(3):
                await r.frage({"type": "TRACK_GET", "id": ids[2]})
            await r.frage({"type": "TRACK_GET", "id": ids[1]})

            neu = await r.frage({"type": "TRACK_LIST", "sort": "new"})
            assert [e["name"] for e in neu["tracks"]] == ["Alpine", "Delta", "Gamma", "Beta", "Alpha"]
            beliebt = await r.frage({"type": "TRACK_LIST", "sort": "downloads"})
            assert [e["name"] for e in beliebt["tracks"]][:2] == ["Gamma", "Beta"]
            such = await r.frage({"type": "TRACK_LIST", "query": "alp"})
            assert sorted(e["name"] for e in such["tracks"]) == ["Alpha", "Alpine"]
            such = await r.frage({"type": "TRACK_LIST", "query": "anna"})   # Autor
            assert such["total"] == 5
            such = await r.frage({"type": "TRACK_LIST", "query": "zzz"})
            assert such["total"] == 0 and such["tracks"] == [] and such["pages"] == 1

            s0 = await r.frage({"type": "TRACK_LIST", "per_page": 2, "page": 0})
            s2 = await r.frage({"type": "TRACK_LIST", "per_page": 2, "page": 2})
            assert s0["pages"] == 3 and len(s0["tracks"]) == 2 and len(s2["tracks"]) == 1
            weit = await r.frage({"type": "TRACK_LIST", "per_page": 2, "page": 99})
            assert weit["page"] == 2                             # auf die letzte Seite geklemmt
            riesig = await r.frage({"type": "TRACK_LIST", "per_page": 10 ** 9})
            assert len(riesig["tracks"]) == 5
            muell = await r.frage({"type": "TRACK_LIST", "sort": {"x": 1}, "page": "a", "per_page": []})
            assert muell["type"] == "TRACK_LIST"
    _lauf(go())


def test_ablage_ueberlebt_neustart(tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as r:
            tid = (await r.frage(_hoch(rundkurs(name="Bleibt"))))["id"]
            await r.frage({"type": "TRACK_GET", "id": tid})
            await r.frage({"type": "TRACK_REPORT", "id": tid})
        # Neuer Prozess: neuer Speicher auf demselben Verzeichnis.
        async with Relay(str(tmp_path)) as r2:
            liste = await r2.frage({"type": "TRACK_LIST"})
            assert liste["total"] == 1
            e = liste["tracks"][0]
            assert e["id"] == tid and e["name"] == "Bleibt" and e["downloads"] == 1
            assert (await r2.frage({"type": "TRACK_GET", "id": tid}))["track"]["name"] == "Bleibt"
            # Die Duplikatsperre und der Tageszaehler gelten weiter.
            assert (await r2.frage(_hoch(rundkurs(name="Andere"))))["code"] == "DUPLICATE"
            assert srv.strecken_speicher().tracks[tid]["reports"]
    _lauf(go())


def test_kaputter_index_wird_aus_den_dateien_neu_gebaut(tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as r:
            tid = (await r.frage(_hoch(rundkurs(name="Rettung"))))["id"]
        (tmp_path / "index.json").write_text("{kaputt", encoding="utf-8")
        (tmp_path / "zz.tmp").write_text("x")
        (tmp_path / "nichtid.json").write_text("{}")
        async with Relay(str(tmp_path)) as r2:
            liste = await r2.frage({"type": "TRACK_LIST"})
            assert [e["id"] for e in liste["tracks"]] == [tid]
        (tmp_path / "index.json").unlink()
        async with Relay(str(tmp_path)) as r3:
            assert (await r3.frage({"type": "TRACK_LIST"}))["total"] == 1
    _lauf(go())


def test_aenderung_am_index_von_aussen_wird_bemerkt(tmp_path):
    """Das Verwaltungswerkzeug arbeitet auf denselben Dateien wie der Server."""
    async def go():
        async with Relay(str(tmp_path)) as r:
            tid = (await r.frage(_hoch(rundkurs())))["id"]
            index = tmp_path / "index.json"
            d = json.loads(index.read_text(encoding="utf-8"))
            d["tracks"][tid]["hidden"] = True
            index.write_text(json.dumps(d), encoding="utf-8")
            os.utime(index, ns=(10 ** 18, 10 ** 18))
            assert (await r.frage({"type": "TRACK_LIST"}))["total"] == 0
    _lauf(go())


def test_anfragerate(tmp_path):
    async def go():
        async with Relay(str(tmp_path), anfragen=5) as r:
            antworten = [await r.frage({"type": "TRACK_LIST"}) for _ in range(7)]
            assert [a["type"] for a in antworten[:5]] == ["TRACK_LIST"] * 5
            assert antworten[5]["type"] == "TRACK_ERROR" and antworten[5]["code"] == "RATE"
    _lauf(go())


def test_abschaltschalter(tmp_path, monkeypatch):
    async def go():
        async with Relay(str(tmp_path)) as r:
            monkeypatch.setattr(srv, "STRECKEN_AUS", True)
            a = await r.frage({"type": "TRACK_LIST"})
            assert a["type"] == "TRACK_ERROR" and a["code"] == "DISABLED"
    _lauf(go())


# --------------------------------------------------------------------------
# Rueckwaertskompatibilitaet: alte Clients und alte Nachrichten
# --------------------------------------------------------------------------

def test_info_und_lobby_laufen_unveraendert(tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as r:
            info = await r.frage({"type": "INFO", "version": "x"})
            assert info["type"] == "INFO" and "lobby_count" in info
            assert "type" in info and "server_tag" in info
            version = str(srv._load_live_config().get("required_version", ""))
            reader, writer = await asyncio.open_connection("127.0.0.1", r.port)
            await senden(writer, {"type": "HOST", "name": "Alt", "version": version})
            ok = await empfangen(reader)
            assert ok["type"] == "JOIN_OK" and ok["is_host"] is True
            writer.close()
    _lauf(go())


def test_streckennachricht_mitten_in_der_lobby_stoert_nicht(tmp_path):
    """Die Streckentypen gelten nur als erste Nachricht; in einer Lobby
    werden sie wie jede unbekannte Nachricht ignoriert."""
    async def go():
        async with Relay(str(tmp_path)) as r:
            version = str(srv._load_live_config().get("required_version", ""))
            reader, writer = await asyncio.open_connection("127.0.0.1", r.port)
            await senden(writer, {"type": "HOST", "name": "Alt", "version": version})
            await empfangen(reader)
            await senden(writer, {"type": "TRACK_LIST"})
            await senden(writer, {"type": "CHAT", "text": "hallo"})
            await senden(writer, {"type": "SET_SETTINGS", "settings": {"laps": 3}})
            await asyncio.sleep(0.3)
            assert writer.transport.is_closing() is False
            assert srv.strecken_speicher().belegt()[0] == 0
            writer.close()
    _lauf(go())


def test_unbekannter_erster_typ_schliesst_still(tmp_path):
    """Ein Server ohne Streckenfunktion tut dasselbe — der Client liest das als
    „nicht unterstuetzt"."""
    async def go():
        async with Relay(str(tmp_path)) as r:
            reader, writer = await asyncio.open_connection("127.0.0.1", r.port)
            await senden(writer, {"type": "GIBT_ES_NICHT"})
            assert await empfangen(reader, timeout=1.0) is None
            writer.close()
    _lauf(go())
