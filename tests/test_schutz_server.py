"""Online-Schutz auf dem Relay (Plan 1.1.0): Dateipruefsumme, Plausibilitaet,
Rauswurf, Meldungen.

Teils gegen einen echten Relay auf einem freien Port (TCP), teils gegen
``schutz.LobbySchutz`` allein mit eigener Uhr: Zeitverhalten laesst sich so ohne
Warten und ohne Zufall pruefen, vor allem die Frage, ob verzoegerte, geballte
oder verlorene Pakete faelschlich als Schummeln gelten (Tests ``test_jitter_*``).
"""
from __future__ import annotations

import asyncio
import json
import math
import random
import struct

import pytest

from tests.strecken_hilfe import Relay, empfangen, senden, srv

schutz = srv.schutz

SUMME = "a" * 64
FALSCH = "b" * 64


def _lauf(coro):
    return asyncio.run(coro)


def _version() -> str:
    return str(srv._load_live_config().get("required_version", ""))


@pytest.fixture(autouse=True)
def _frisch(monkeypatch, tmp_path):
    """Frische Zaehler, eigene Pruefsummen- und Meldedatei, Pruefung an."""
    monkeypatch.setattr(srv, "_wache", srv._Wache())
    monkeypatch.setattr(srv, "_pw_wache", srv._PwWache())
    monkeypatch.setattr(srv, "MAX_LOBBIES_PER_IP", 50)
    monkeypatch.setattr(srv, "MAX_CONN_PER_IP", 50)
    datei = tmp_path / "pruefsummen.json"
    datei.write_text(json.dumps({"format": 1, "spiele": {
        "2d": {_version(): {"summen": [SUMME], "fahrzeuge": {"rookie": 886.0, "supercar": 984.0},
                            "strecken": {"oval": 6597.0}}},
        "3d": {_version(): {"summen": ["c" * 64]}},
    }}), encoding="utf-8")
    monkeypatch.setenv("RACE_PRUEFSUMMEN_DATEI", str(datei))
    monkeypatch.setenv("RACE_FILES_CHECK", "enforce")
    monkeypatch.setattr(srv, "_meldungen", schutz.MeldungsSpeicher(str(tmp_path / "meldungen")))
    yield


# ── Netzhilfen ────────────────────────────────────────────────────────────────

async def _verbinden(relay, art, name="Anna", lobby=None, **extra):
    r, w = await asyncio.open_connection("127.0.0.1", relay.port)
    msg = {"type": art, "name": name, "version": _version(), "game": "2d", "files": SUMME}
    if lobby:
        msg["lobby_id"] = lobby
    msg.update(extra)
    msg = {k: v for k, v in msg.items() if v is not None}
    await senden(w, msg)
    return r, w, await empfangen(r)


async def _bis(reader, typ, versuche=12):
    for _ in range(versuche):
        m = await empfangen(reader)
        if m is None:
            return None
        if m.get("type") == typ:
            return m
    return None


async def _lobby(relay, namen=("Anna", "Ben"), **extra):
    """Host + Gaeste; Rueckgabe: Liste (Name, reader, writer, JOIN_OK)."""
    sp = []
    r, w, ok = await _verbinden(relay, "HOST", namen[0], cid="cid-" + namen[0] + "-0000", **extra)
    assert ok["type"] == "JOIN_OK", ok
    sp.append((namen[0], r, w, ok))
    if len(namen) > 4:                        # Standardgroesse sind vier Plaetze
        await senden(w, {"type": "SET_SETTINGS", "settings": {"roster_size": 6}})
    for n in namen[1:]:
        r2, w2, ok2 = await _verbinden(relay, "JOIN", n, lobby=ok["lobby_id"],
                                       cid="cid-" + n + "-0000", **extra)
        assert ok2["type"] == "JOIN_OK", ok2
        sp.append((n, r2, w2, ok2))
    return sp


def _schliessen(sp):
    for _n, _r, w, _ok in sp:
        w.close()


# ══ 1. Dateipruefsumme ═══════════════════════════════════════════════════════

def test_passende_summe_kommt_herein(tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            sp = await _lobby(relay)
            assert [x[3]["type"] for x in sp] == ["JOIN_OK", "JOIN_OK"]
            _schliessen(sp)
    _lauf(go())


@pytest.mark.parametrize("extra", [
    {"files": FALSCH},                  # veraenderte Dateien
    {"files": None},                    # kein Feld
    {"files": "nichthex"},              # kein SHA-256
    {"game": None},                     # kein Spiel
    {"game": "4d"},                     # unbekanntes Spiel
    {"game": "3d"},                     # Summe des anderen Spiels gilt hier nicht
])
def test_falsche_summe_wird_beim_host_abgewiesen(tmp_path, extra):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            _r, w, antwort = await _verbinden(relay, "HOST", **extra)
            assert antwort["type"] == "JOIN_FAIL" and antwort["code"] == "MODIFIED_FILES"
            assert antwort["reason"]
            assert srv._registry.lobbies == {}          # keine Lobby entstanden
            w.close()
    _lauf(go())


def test_falsche_summe_wird_beim_gast_abgewiesen(tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            sp = await _lobby(relay, namen=("Anna",))
            _r, w, antwort = await _verbinden(relay, "JOIN", "Ben",
                                              lobby=sp[0][3]["lobby_id"], files=FALSCH)
            assert antwort["code"] == "MODIFIED_FILES"
            assert len(srv._registry.lobbies) == 1
            assert len(next(iter(srv._registry.lobbies.values())).clients) == 1
            w.close(); _schliessen(sp)
    _lauf(go())


def test_unbekannte_version_gilt_als_nicht_freigegeben(monkeypatch, tmp_path):
    """Steht fuer (Spiel, Version) nichts in der Datei, kommt niemand herein."""
    monkeypatch.setattr(srv, "_load_live_config", lambda: {"required_version": ""})

    async def go():
        async with Relay(str(tmp_path)) as relay:
            _r, w, antwort = await _verbinden(relay, "HOST", version="9.9.9")
            assert antwort["code"] == "MODIFIED_FILES"
            w.close()
    _lauf(go())


def test_fehlt_die_datei_wird_abgewiesen_nicht_durchgewunken(monkeypatch, tmp_path):
    monkeypatch.setenv("RACE_PRUEFSUMMEN_DATEI", str(tmp_path / "gibt-es-nicht.json"))

    async def go():
        async with Relay(str(tmp_path)) as relay:
            _r, w, antwort = await _verbinden(relay, "HOST")
            assert antwort["code"] == "MODIFIED_FILES"
            w.close()
    _lauf(go())


def test_modus_protokoll_laesst_herein_und_meldet(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("RACE_FILES_CHECK", "log")

    async def go():
        async with Relay(str(tmp_path)) as relay:
            _r, w, antwort = await _verbinden(relay, "HOST", files=FALSCH)
            assert antwort["type"] == "JOIN_OK"
            w.close()
    with caplog.at_level("WARNING"):
        _lauf(go())
    assert any("Dateipruefung" in r.getMessage() for r in caplog.records)


def test_modus_aus_prueft_nicht(monkeypatch, tmp_path):
    monkeypatch.setenv("RACE_FILES_CHECK", "off")

    async def go():
        async with Relay(str(tmp_path)) as relay:
            _r, w, antwort = await _verbinden(relay, "HOST", files=None, game=None)
            assert antwort["type"] == "JOIN_OK"
            w.close()
    _lauf(go())


def test_vorgabe_ist_durchsetzen(monkeypatch):
    monkeypatch.delenv("RACE_FILES_CHECK", raising=False)
    assert schutz.dateien_modus() == "enforce"
    for roh, soll in (("OFF", "off"), ("aus", "off"), ("Log", "log"), ("quatsch", "enforce")):
        monkeypatch.setenv("RACE_FILES_CHECK", roh)
        assert schutz.dateien_modus() == soll


def test_pruefsummen_datei_wird_bei_aenderung_neu_gelesen(tmp_path):
    pfad = tmp_path / "pruefsummen.json"
    assert schutz.dateien_pruefen({"game": "2d", "files": SUMME}, _version()) is None
    d = json.loads(pfad.read_text(encoding="utf-8"))
    d["spiele"]["2d"][_version()]["summen"] = [FALSCH]
    pfad.write_text(json.dumps(d, indent=3), encoding="utf-8")         # andere Groesse
    assert schutz.dateien_pruefen({"game": "2d", "files": SUMME}, _version())["code"] == "MODIFIED_FILES"
    assert schutz.dateien_pruefen({"game": "2d", "files": FALSCH}, _version()) is None


def test_gast_aus_dem_anderen_spiel_wird_abgewiesen(monkeypatch, tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            sp = await _lobby(relay, namen=("Anna",))
            # Eine 3D-Summe ist gueltig - aber nicht fuer eine 2D-Lobby.
            _r, w, antwort = await _verbinden(relay, "JOIN", "Ben",
                                              lobby=sp[0][3]["lobby_id"],
                                              game="3d", files="c" * 64)
            assert antwort["code"] == "WRONG_GAME"
            w.close(); _schliessen(sp)
    _lauf(go())


def test_die_pruefsummen_des_repos_stehen_in_der_datei():
    """Die mitgelieferte Datei kennt dieses Spiel in der aktuellen Version."""
    import os
    pfad = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "server", "pruefsummen.json")
    d = json.load(open(pfad, encoding="utf-8"))
    assert d["format"] == 1
    for spiel in d["spiele"].values():
        for e in spiel.values():
            assert all(len(s) == 64 for s in e["summen"])


# ══ 2. Plausibilitaet: Positionsstrom ═══════════════════════════════════════

def paket(slot, fahrzeuge, send, lid="H1AAAA"):
    """Ein UDP_STATE wie ``protocol.pack_state``; Fahrzeug = (id, typ, x, y, vx, vy, lap)."""
    kopf = struct.pack("!B 6s B B d", 0x01, lid.encode().ljust(6, b"\0"), slot,
                       len(fahrzeuge), send)
    rumpf = b"".join(struct.pack("!BB ffffff B H", vid, typ, x, y, 0.0, vx, vy, 0.0, lap, 0)
                     for (vid, typ, x, y, vx, vy, lap) in fahrzeuge)
    return kopf + rumpf


def _wache(laps=3, strecke=6597.0):
    s = schutz.LobbySchutz("H1AAAA", "2d", _version())
    s.namen[1] = "Ben"
    s.rennen_neu({"laps": laps}, b"", "oval")
    s.go(0.0, 0.0)
    return s


def _fahre(s, ereignisse, slot=1, typ=0):
    """``ereignisse``: Liste (Ankunft, Sendezeit, x) fuer ein Auto, das auf x entlang faehrt."""
    for ankunft, send, x in sorted(ereignisse):
        s.paket(slot, paket(slot, [(1, typ, x, 0.0, 0.0, 0.0, 1)], send), ankunft)


def _strom(tempo, dauer=30.0, hz=20.0, start=0.0):
    t, aus = 0.0, []
    while t <= dauer:
        aus.append((start + t, start + t, tempo * t))
        t += 1.0 / hz
    return aus


def test_normale_fahrt_ist_unverdaechtig():
    s = _wache()
    _fahre(s, _strom(850.0))               # knapp unter dem Hoechsttempo des rookie
    assert not s.verdaechtig(1) and not s.punkte


def test_jitter_verzoegerung_verlust_und_bursts_sind_kein_schummeln():
    """Wackelnde Leitung: Verzoegerung 20-400 ms, 25 % Verlust, 1,5 s Stau mit
    geballter Auslieferung, 2 s Funkstille, vertauschte Reihenfolge."""
    for seed in range(20):
        rnd = random.Random(seed)
        s = _wache()
        ev = []
        for _ankunft, send, x in _strom(880.0, dauer=30.0):
            if rnd.random() < 0.25:
                continue                                      # verloren
            if 8.0 <= send < 10.0:
                continue                                      # Funkstille
            if 12.0 <= send < 13.5:
                ankunft = 13.5 + rnd.random() * 0.002         # Stau, dann alles auf einmal
            else:
                ankunft = send + 0.02 + rnd.random() * 0.38   # Schwankung, vertauscht
            ev.append((ankunft, send, 880.0 * send))
        _fahre(s, ev)
        assert not s.verdaechtig(1), (seed, s.gruende)
        assert not s.punkte, (seed, s.punkte)


def test_jitter_langer_stau_von_zweieinhalb_sekunden():
    s = _wache()
    ev = []
    for _a, send, _x in _strom(880.0, dauer=20.0):
        ankunft = 12.5 + 0.001 * send if 10.0 <= send < 12.5 else send + 0.1
        ev.append((ankunft, send, 880.0 * send))
    _fahre(s, ev)
    assert not s.punkte


def test_kleiner_sprung_innerhalb_der_luft_bleibt_unbehelligt():
    """Dokumentierte Grenze: wer lange steht und dann ein Stueck springt, das
    kleiner ist als das angesparte Guthaben, faellt nicht auf."""
    s = _wache()
    ev = _strom(0.0, dauer=5.0)
    ev.append((5.05, 5.05, 2500.0))
    _fahre(s, ev)
    assert not s.verdaechtig(1)


def test_jitter_auch_mit_dem_schnellsten_auto_am_limit():
    rnd = random.Random(7)
    s = _wache()
    ev = [(send + 0.05 + rnd.random() * 0.3, send, 980.0 * send)
          for _a, send, _x in _strom(980.0) if rnd.random() > 0.1]
    _fahre(s, ev, typ=1)                                      # supercar, 984 px/s
    assert not s.punkte


def test_lange_stille_mit_weiter_gefahrener_strecke_ist_erlaubt():
    """6 s kein Paket (alle verloren), dann steht das Auto 6 s weiter vorn."""
    s = _wache()
    ev = [(t, t, 800.0 * t) for t in [i * 0.05 for i in range(0, 40)]]
    ev += [(8.0 + i * 0.05, 8.0 + i * 0.05, 800.0 * (8.0 + i * 0.05)) for i in range(20)]
    _fahre(s, ev)
    assert not s.punkte


def test_sprung_wird_erkannt():
    s = _wache()
    ev = _strom(700.0, dauer=3.0)
    ev.append((3.05, 3.05, 700.0 * 3.05 + 9000.0))            # 9000 px in 50 ms
    _fahre(s, ev)
    assert s.verdaechtig(1) and "SPRUNG" in s.gruende[1]


def test_zu_hohes_tempo_ueber_die_zeit_wird_erkannt():
    s = _wache()
    _fahre(s, _strom(2600.0, dauer=6.0))                      # gut das Dreifache
    assert s.verdaechtig(1) and "TEMPO_WEG" in s.gruende[1]


def test_gemeldetes_tempo_wird_nur_dauerhaft_gezaehlt():
    s = _wache()
    for i in range(100):                                      # 5 s mit 3000 px/s gemeldet
        t = i * 0.05
        s.paket(1, paket(1, [(1, 0, 600.0 * t, 0.0, 3000.0, 0.0, 1)], t), t)
    assert "TEMPO_MELDUNG" in s.gruende[1]
    s2 = _wache()                                             # kurzer Ausschlag (Stoss)
    for i in range(100):
        t = i * 0.05
        vx = 3000.0 if 20 <= i < 24 else 600.0
        s2.paket(1, paket(1, [(1, 0, 600.0 * t, 0.0, vx, 0.0, 1)], t), t)
    assert not s2.punkte


def test_ein_stehengebliebenes_ki_auto_das_zurueckgesetzt_wird_ist_in_ordnung():
    """Die KI setzt ein festgefahrenes Auto bis zu ~300 px weiter."""
    s = _wache()
    ev = [(i * 0.05, i * 0.05, 100.0) for i in range(60)]      # steht an der Wand
    ev.append((3.05, 3.05, 400.0))                             # Neusetzen um 300 px
    _fahre(s, ev)
    assert not s.punkte


def test_verspaetetes_altes_paket_zaehlt_nicht():
    s = _wache()
    ev = _strom(500.0, dauer=2.0)
    _fahre(s, ev)
    s.paket(1, paket(1, [(1, 0, 0.0, 0.0, 0, 0, 1)], 0.5), 2.1)   # uralt, weit zurueck
    s.paket(1, paket(1, [(1, 0, 1050.0, 0.0, 0, 0, 1)], 2.05), 2.1)
    assert not s.punkte


def test_unbrauchbare_zahlen_sind_verdaechtig():
    s = _wache()
    s.paket(1, paket(1, [(1, 0, float("nan"), 0.0, 0, 0, 1)], 1.0), 1.0)
    assert s.verdaechtig(1)


def test_kaputte_pakete_werfen_nicht():
    s = _wache()
    for roh in (b"", b"\x01", b"\x01" + b"\0" * 40, paket(1, [(1, 0, 0, 0, 0, 0, 1)], 1.0)[:-5]):
        s.paket(1, roh, 1.0)


def test_fahrzeugnummern_stimmen_mit_dem_protokoll_der_clients_ueberein():
    """``VEHICLE_TYPES`` hier muss zu ``src/net/protocol.py`` passen."""
    from src.net import protocol
    assert schutz.VEHICLE_TYPES == protocol.VEHICLE_TYPES
    assert schutz._STATE_KOPF.size == protocol.STATE_HEADER.size
    assert schutz._STATE_FAHRZEUG.size == protocol.VEHICLE_FMT.size


def test_zusammenspiel_mit_dem_echten_protokoll():
    """Pakete aus ``protocol.pack_state`` lesen sich im Relay richtig."""
    from src.net import protocol
    s = _wache()
    for i in range(40):
        t = i * 0.05
        daten = protocol.pack_state("H1AAAA", 1, [
            {"id": 1, "x": 700.0 * t, "y": 5.0, "angle": 0.0, "vx": 700.0, "vy": 0.0,
             "omega": 0.0, "cfg": "supercar", "lap": 1, "wp": 3}], t)
        s.paket(1, daten, t)
    assert (1, 1) in s.stroeme and not s.punkte


# ══ 2b. Plausibilitaet: Ergebnisse ═══════════════════════════════════════════

def _zeile(slot=1, name="Ben", ft=70.0, bl=22.0, dnf=False, **extra):
    return dict({"slot": slot, "name": name, "vehicle": "rookie", "finish_time": ft,
                 "best_lap": bl, "dnf": dnf, "team": "A", "ai_takeover": False}, **extra)


def test_zeilen_werden_auf_bekannte_felder_gebracht():
    s = _wache()
    z = s.zeilen_aufnehmen(1, False, [_zeile(boese="x" * 5000, invalid=False,
                                            position=1, name="A\nB" + "x" * 90)], 50.0)
    assert len(z) == 1 and set(z[0]) <= {"slot", "name", "vehicle", "finish_time", "best_lap",
                                         "dnf", "team", "ai_takeover", "_von", "_grund"}
    assert "\n" not in z[0]["name"] and len(z[0]["name"]) <= 40
    assert s.zeilen_aufnehmen(1, False, "kein Liste", 50.0) == []
    assert s.zeilen_aufnehmen(1, False, [1, None, "x"], 50.0) == []


def test_unmoegliche_rundenzeit_wird_ungueltig():
    s = _wache()                              # Oval 6597 px, 3 Runden: Runde >= ~4,7 s
    z = s.zeilen_aufnehmen(1, False, [_zeile(ft=9.0, bl=3.0)], 50.0)
    assert z[0]["_grund"] in ("ZEIT_ZU_KURZ", "RUNDE_ZU_KURZ")
    aus = s.bewerten(z)
    assert aus[0]["invalid"] is True and aus[0]["finish_time"] is None and aus[0]["dnf"]
    assert "_grund" not in aus[0] and "_von" not in aus[0]
    assert s.verdaechtig(1)


def test_gute_aber_moegliche_zeit_bleibt_gueltig():
    s = _wache()
    z = s.zeilen_aufnehmen(1, False, [_zeile(ft=36.0, bl=11.5)], 50.0)   # sehr schnell, aber moeglich
    assert "_grund" not in z[0]
    assert "invalid" not in s.bewerten(z)[0] and not s.punkte


def test_widerspruechliche_zeiten_werden_erkannt():
    s = _wache()
    z = s.zeilen_aufnehmen(1, False, [_zeile(ft=40.0, bl=30.0)], 50.0)   # 3 x 30 s > 40 s
    assert z[0]["_grund"] == "ZEIT_WIDERSPRUCH"


def test_dnf_zeilen_werden_nicht_zeitgeprueft():
    s = _wache()
    z = s.zeilen_aufnehmen(1, False, [_zeile(ft=None, bl=None, dnf=True)], 50.0)
    assert "_grund" not in z[0] and not s.punkte


def test_zeile_fuer_einen_anderen_platz_wird_verworfen_und_verdaechtigt():
    s = _wache()
    assert s.zeilen_aufnehmen(1, False, [_zeile(slot=0)], 50.0) == []
    assert s.punkte[1] >= schutz.SCHWELLE
    s2 = _wache()
    assert s2.zeilen_aufnehmen(1, False, [_zeile(slot=-1, name="KI 2")], 50.0) == []   # Gast faehrt keine KI
    assert s2.verdaechtig(1)


def test_host_darf_ki_zeilen_melden_und_doppelte_zaehlen_nicht():
    s = _wache()
    z = s.zeilen_aufnehmen(0, True, [_zeile(slot=0, name="Anna"), _zeile(slot=-1, name="KI 2"),
                                     _zeile(slot=-1, name="KI 3")], 50.0)
    assert len(z) == 3 and not s.punkte
    assert s.zeilen_aufnehmen(0, True, [_zeile(slot=0, name="Anna")], 51.0) == []   # doppelt


def test_beobachtete_zielzeit_widerspricht_der_angabe():
    """Der Relay sah die dritte Runde bei 80 s enden - die Angabe 50 s stimmt nicht."""
    s = _wache()
    for lap, t in ((1, 0.0), (2, 28.0), (3, 55.0), (4, 80.0)):
        s.paket(1, paket(1, [(1, 0, 10.0 * t, 0, 0, 0, lap)], t), t + 0.1)
    z = s.zeilen_aufnehmen(1, False, [_zeile(ft=50.0, bl=16.0)], 85.0)
    assert z[0]["_grund"] == "ZEIT_BEOBACHTET"


def test_beobachtete_zeit_mit_laufzeitschwankung_ist_kein_widerspruch():
    s = _wache()
    for lap, t in ((1, 0.0), (2, 28.0), (3, 55.0), (4, 80.0)):
        s.paket(1, paket(1, [(1, 0, 10.0 * t, 0, 0, 0, lap)], t), t + 1.4)   # 1,4 s Laufzeit
    z = s.zeilen_aufnehmen(1, False, [_zeile(ft=79.0, bl=24.5)], 85.0)
    assert "_grund" not in z[0]


def test_beste_runde_gegen_beobachtete_runden():
    s = _wache()
    for lap, t in ((1, 0.0), (2, 30.0), (3, 62.0), (4, 95.0)):
        s.paket(1, paket(1, [(1, 0, 10.0 * t, 0, 0, 0, lap)], t), t)
    z = s.zeilen_aufnehmen(1, False, [_zeile(ft=95.0, bl=12.0)], 99.0)   # beobachtet >= 30 s je Runde
    assert z[0]["_grund"] == "RUNDE_BEOBACHTET"


def test_pause_zaehlt_nicht_zur_rennzeit():
    s = _wache()
    s.pause(10.0, True)
    s.pause(40.0, False)                                      # 30 s Pause
    for lap, t in ((1, 0.0), (2, 50.0), (3, 90.0), (4, 130.0)):
        s.paket(1, paket(1, [(1, 0, 10.0 * t, 0, 0, 0, lap)], t), t)
    # Beobachtet: Ziel nach 100 s Rennzeit (130 - 30 Pause). Angabe 98 s ist ehrlich.
    z = s.zeilen_aufnehmen(1, False, [_zeile(ft=98.0, bl=30.0)], 131.0)
    assert "_grund" not in z[0], z[0]


def test_countdown_verschiebt_die_rennuhr():
    s = schutz.LobbySchutz("H1AAAA", "2d", _version())
    s.go(100.0, 3500)
    assert s.rennzeit(101.0) == 0.0
    assert s.rennzeit(110.0) == pytest.approx(6.5)


def test_erfundenes_first_finish_wird_ignoriert():
    s = _wache()
    ok, _g = s.erster_im_ziel(1, 1.0, 3.0)                    # 3 s nach dem Start
    assert not ok and s.verdaechtig(1)
    s2 = _wache()
    ok, grace = s2.erster_im_ziel(1, 1.0, 60.0)               # echtes Ziel, Frist 1 s ist zu kurz
    assert ok and grace >= s2.min_runde > 1.0


def test_streckenlaenge_aus_der_karte():
    import os
    pfad = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "tracks", "oval.json")
    laenge = schutz.strecke_laenge(open(pfad, "rb").read())
    assert 6000 < laenge < 7500
    assert schutz.strecke_laenge(b"kein json") is None
    assert schutz.strecke_laenge(json.dumps({"centerline": [{"x": 0, "y": 0}] * 3}).encode()) is None


# ══ 2c. Ergebnisse ueber den echten Relay ═══════════════════════════════════

async def _rennen_starten(relay, laps=3):
    sp = await _lobby(relay)
    (_, rh, wh, ok), (_, rg, wg, _ok2) = sp
    await senden(wh, {"type": "SET_SETTINGS", "settings": {"laps": laps, "mode": "Rennen"}})
    await senden(wh, {"type": "START_REQUEST", "is_custom": False, "track_name": "oval"})
    await _bis(rg, "MAP_META")
    await senden(wg, {"type": "READY"})
    await _bis(rh, "START")
    await _bis(rg, "START")
    await senden(wh, {"type": "LOADED"})
    await senden(wg, {"type": "LOADED"})
    await _bis(rh, "RACE_GO")
    return sp


def test_ergebnisse_ungueltige_zeile_wird_ans_ende_gestellt(tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            sp = await _rennen_starten(relay)
            (_, rh, wh, _a), (_, rg, wg, _b) = sp
            # Der Gast behauptet 5 s fuer drei Runden auf dem Oval - das schafft kein Auto.
            await senden(wg, {"type": "RACE_RESULT", "rows": [_zeile(slot=1, name="Ben", ft=5.0, bl=1.6)]})
            await senden(wh, {"type": "RACE_RESULT", "rows": [
                _zeile(slot=0, name="Anna", ft=70.0, bl=22.0),
                _zeile(slot=-1, name="KI 2", ft=75.0, bl=24.0, dnf=False),
                _zeile(slot=-1, name="KI 3", ft=None, bl=None, dnf=True)]})
            res = await _bis(rh, "RACE_RESULTS")
            assert res is not None
            reihe = [(r["name"], r.get("invalid", False), r["dnf"]) for r in res["rows"]]
            assert reihe == [("Anna", False, False), ("KI 2", False, False),
                             ("KI 3", False, True), ("Ben", True, True)], reihe
            ben = res["rows"][-1]
            assert ben["finish_time"] is None and ben["position"] == 4
            assert [r["position"] for r in res["rows"]] == [1, 2, 3, 4]
            _schliessen(sp)
    _lauf(go())


def test_ergebnisse_fremde_zeile_ist_nicht_in_der_wertung(tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            sp = await _rennen_starten(relay)
            (_, rh, wh, _a), (_, rg, wg, _b) = sp
            # Ben schickt eine Zeile im Namen von Anna (Slot 0) und eine eigene.
            await senden(wg, {"type": "RACE_RESULT", "rows": [
                _zeile(slot=0, name="Anna", ft=40.0, bl=13.0), _zeile(slot=1, name="Ben", ft=80.0, bl=26.0)]})
            await senden(wh, {"type": "RACE_RESULT", "rows": [_zeile(slot=0, name="Anna", ft=70.0, bl=22.0)]})
            res = await _bis(rh, "RACE_RESULTS")
            zeilen = {r["name"]: r for r in res["rows"]}
            assert len(res["rows"]) == 2
            assert zeilen["Anna"]["finish_time"] == 70.0
            # Ben hat gefaelscht: auch seine eigene Zeile gilt nicht mehr.
            assert zeilen["Ben"]["invalid"] is True
            _schliessen(sp)
    _lauf(go())


def test_ehrliche_ergebnisse_bleiben_unveraendert(tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            sp = await _rennen_starten(relay)
            (_, rh, wh, _a), (_, rg, wg, _b) = sp
            await senden(wg, {"type": "RACE_RESULT", "rows": [_zeile(slot=1, name="Ben", ft=64.5, bl=20.9)]})
            await senden(wh, {"type": "RACE_RESULT", "rows": [_zeile(slot=0, name="Anna", ft=61.2, bl=19.8)]})
            res = await _bis(rg, "RACE_RESULTS")
            assert [(r["name"], r["finish_time"], r.get("invalid")) for r in res["rows"]] == [
                ("Anna", 61.2, None), ("Ben", 64.5, None)]
            _schliessen(sp)
    _lauf(go())


def test_erfundenes_first_finish_loest_kein_force_finish_aus(tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            sp = await _rennen_starten(relay)
            (_, rh, wh, _a), (_, rg, wg, _b) = sp
            lobby = next(iter(srv._registry.lobbies.values()))
            await senden(wg, {"type": "FIRST_FINISH", "slowest_lap": 1.0})
            await asyncio.sleep(1.4)           # laenger als die behauptete Frist
            assert lobby.finish_timer is None and not lobby.first_finish_seen
            _schliessen(sp)
    _lauf(go())


# ══ 3. Rauswurf ══════════════════════════════════════════════════════════════

def _tunnel(monkeypatch):
    """Alle Spieler kommen mit derselben Adresse an (wie hinter dem Tunnel)."""
    monkeypatch.setattr(srv, "TRUSTED_PROXIES", frozenset({"127.0.0.1"}))


def test_host_entfernt_spieler(monkeypatch, tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            _tunnel(monkeypatch)
            sp = await _lobby(relay, namen=("Anna", "Ben", "Cleo"))
            (_, rh, wh, ok), (_, rb, wb, _), (_, rc, wc, _) = sp
            await senden(wh, {"type": "KICK", "slot": 1})
            k = await _bis(rb, "KICKED")
            assert k and k["by"] == "Anna"
            assert await empfangen(rb) is None                    # Verbindung zu
            links = await _bis(rc, "PLAYER_LEFT")
            assert links["slot"] == 1 and links["name"] == "Ben"
            ls = await _bis(rc, "LOBBY_STATE")
            assert [p["name"] for p in ls["players"]] == ["Anna", "Cleo"]
            _schliessen(sp)
    _lauf(go())


def test_entfernter_spieler_kommt_nicht_wieder_aber_andere_schon(monkeypatch, tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            _tunnel(monkeypatch)
            sp = await _lobby(relay)
            lid = sp[0][3]["lobby_id"]
            await senden(sp[0][2], {"type": "KICK", "slot": 1})
            await _bis(sp[1][1], "KICKED")
            # gleiche Kennung: abgewiesen
            _r, w, a = await _verbinden(relay, "JOIN", "Ben", lobby=lid, cid="cid-Ben-0000")
            assert a["type"] == "JOIN_FAIL" and a["code"] == "KICKED" and a["reason"]
            w.close()
            # anderer Name, gleiche Kennung: ebenfalls
            _r, w, a = await _verbinden(relay, "JOIN", "Benny", lobby=lid, cid="cid-Ben-0000")
            assert a["code"] == "KICKED"
            w.close()
            # ein anderer Spieler (andere Kennung) darf
            _r, w, a = await _verbinden(relay, "JOIN", "Dora", lobby=lid, cid="cid-Dora-0000")
            assert a["type"] == "JOIN_OK"
            w.close(); _schliessen(sp)
    _lauf(go())


def test_entfernter_spieler_mit_neuer_kennung_wird_an_der_adresse_erkannt(tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as relay:            # 127.0.0.1 ist hier eine echte Adresse
            sp = await _lobby(relay)
            lid = sp[0][3]["lobby_id"]
            await senden(sp[0][2], {"type": "KICK", "slot": 1})
            await _bis(sp[1][1], "KICKED")
            _r, w, a = await _verbinden(relay, "JOIN", "Ben", lobby=lid, cid="ganz-neue-kennung-1")
            assert a["code"] == "KICKED"
            w.close(); _schliessen(sp)
    _lauf(go())


def test_ohne_kennung_und_hinter_dem_tunnel_zaehlt_der_name(monkeypatch, tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            _tunnel(monkeypatch)
            r, w, ok = await _verbinden(relay, "HOST", "Anna")
            r2, w2, ok2 = await _verbinden(relay, "JOIN", "Ben", lobby=ok["lobby_id"])
            await senden(w, {"type": "KICK", "slot": 1})
            await _bis(r2, "KICKED")
            _r, w3, a = await _verbinden(relay, "JOIN", "ben", lobby=ok["lobby_id"])
            assert a["code"] == "KICKED"
            _r, w4, a = await _verbinden(relay, "JOIN", "Dora", lobby=ok["lobby_id"])
            assert a["type"] == "JOIN_OK"
            for x in (w, w2, w3, w4):
                x.close()
    _lauf(go())


def test_sperre_gilt_nur_bis_die_lobby_geschlossen_wird(monkeypatch, tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            _tunnel(monkeypatch)
            sp = await _lobby(relay)
            await senden(sp[0][2], {"type": "KICK", "slot": 1})
            await _bis(sp[1][1], "KICKED")
            sp[0][2].close()                                  # Host geht, Lobby ist weg
            await asyncio.sleep(0.2)
            assert srv._registry.lobbies == {}
            sp2 = await _lobby(relay)                         # neue Lobby, Ben darf wieder
            assert sp2[1][3]["type"] == "JOIN_OK"
            _schliessen(sp2)
    _lauf(go())


def test_nur_der_host_darf_entfernen(monkeypatch, tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            _tunnel(monkeypatch)
            sp = await _lobby(relay, namen=("Anna", "Ben", "Cleo"))
            await senden(sp[1][2], {"type": "KICK", "slot": 2})
            await asyncio.sleep(0.3)
            lobby = next(iter(srv._registry.lobbies.values()))
            assert sorted(lobby.clients) == [0, 1, 2]
            _schliessen(sp)
    _lauf(go())


def test_entfernen_fehlerfaelle(monkeypatch, tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            _tunnel(monkeypatch)
            sp = await _lobby(relay)
            rh, wh = sp[0][1], sp[0][2]
            for slot, code in ((0, "KICK_SELF"), (5, "KICK_UNKNOWN"), ("x", "KICK_UNKNOWN"),
                               (True, "KICK_UNKNOWN")):
                await senden(wh, {"type": "KICK", "slot": slot})
                assert (await _bis(rh, "ERROR"))["code"] == code
            _schliessen(sp)
    _lauf(go())


def test_waehrend_des_rennens_wird_nicht_entfernt(monkeypatch, tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            _tunnel(monkeypatch)
            sp = await _rennen_starten(relay)
            await senden(sp[0][2], {"type": "KICK", "slot": 1})
            assert (await _bis(sp[0][1], "ERROR"))["code"] == "KICK_BUSY"
            lobby = next(iter(srv._registry.lobbies.values()))
            assert sorted(lobby.clients) == [0, 1]
            _schliessen(sp)
    _lauf(go())


def test_zwischen_den_rennen_wird_wieder_entfernt(monkeypatch, tmp_path):
    """Nach den Ergebnissen steht die Lobby wieder auf ``lobby`` - Entfernen geht."""
    async def go():
        async with Relay(str(tmp_path)) as relay:
            _tunnel(monkeypatch)
            sp = await _rennen_starten(relay)
            await senden(sp[1][2], {"type": "RACE_RESULT", "rows": [_zeile(slot=1, ft=70.0, bl=22.0)]})
            await senden(sp[0][2], {"type": "RACE_RESULT", "rows": [_zeile(slot=0, name="Anna")]})
            await _bis(sp[0][1], "RACE_RESULTS")
            await senden(sp[0][2], {"type": "KICK", "slot": 1})
            assert await _bis(sp[1][1], "KICKED")
            _schliessen(sp)
    _lauf(go())


# ══ 4. Meldungen ═════════════════════════════════════════════════════════════

def test_spieler_meldet_spieler(monkeypatch, tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            _tunnel(monkeypatch)
            sp = await _lobby(relay)
            lid = sp[0][3]["lobby_id"]
            await senden(sp[1][2], {"type": "REPORT_PLAYER", "slot": 0, "name": "Anna",
                                    "reason": "cheating"})
            ok = await _bis(sp[1][1], "REPORT_OK")
            assert ok and ok["name"] == "Anna"
            m = srv.meldungen_speicher().liste
            assert len(m) == 1
            e = m[0]
            assert e["melder"] == {"name": "Ben", "cid": "cidBen0000"}   # Bindestriche fallen weg
            assert e["ziel"]["name"] == "Anna" and e["ziel"]["cid"] == "cidAnna0000"
            assert e["lobby"] == lid and e["grund"] == "cheating" and e["spiel"] == "2d"
            assert e["zeit"] > 1.7e9 and e["marken"] == [] and not e["erledigt"]
            _schliessen(sp)
    _lauf(go())


def test_meldung_traegt_die_verdachtsmarken_mit(monkeypatch, tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            _tunnel(monkeypatch)
            sp = await _lobby(relay)
            lobby = next(iter(srv._registry.lobbies.values()))
            lobby.schutz._verdacht(0, "SPRUNG", 3.0)
            await senden(sp[1][2], {"type": "REPORT_PLAYER", "slot": 0, "name": "Anna", "reason": "cheating"})
            await _bis(sp[1][1], "REPORT_OK")
            assert srv.meldungen_speicher().liste[0]["marken"] == ["SPRUNG"]
            _schliessen(sp)
    _lauf(go())


def test_meldung_fehlerfaelle(monkeypatch, tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            _tunnel(monkeypatch)
            sp = await _lobby(relay)
            rb, wb = sp[1][1], sp[1][2]
            for msg, code in (
                ({"slot": 1, "name": "Ben", "reason": "cheating"}, "REPORT_SELF"),
                ({"slot": 4, "name": "Niemand", "reason": "cheating"}, "REPORT_UNKNOWN"),
                ({"slot": -1, "name": "KI 2", "reason": "cheating"}, "REPORT_UNKNOWN"),
                ({"slot": 0, "name": "Anna", "reason": "weil ich will"}, "REPORT_REASON"),
            ):
                await senden(wb, dict(msg, type="REPORT_PLAYER"))
                assert (await _bis(rb, "ERROR"))["code"] == code
            assert srv.meldungen_speicher().liste == []
            _schliessen(sp)
    _lauf(go())


def test_doppelte_meldung_wird_nicht_doppelt_abgelegt(monkeypatch, tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            _tunnel(monkeypatch)
            sp = await _lobby(relay)
            for _ in range(3):
                await senden(sp[1][2], {"type": "REPORT_PLAYER", "slot": 0, "name": "Anna", "reason": "cheating"})
                assert await _bis(sp[1][1], "REPORT_OK")
            assert len(srv.meldungen_speicher().liste) == 1
            _schliessen(sp)
    _lauf(go())


def test_meldungen_sind_begrenzt(monkeypatch, tmp_path):
    spei = schutz.MeldungsSpeicher(str(tmp_path / "m2"), pro_stunde=3, pro_tag=10)
    monkeypatch.setattr(srv, "_meldungen", spei)

    def melden(i):
        return spei.melden(melder_schluessel="ip:1.2.3.4", melder_name="Ben", melder_cid="",
                           ziel_name=f"Z{i}", ziel_cid="", ziel_ip_kurz="", lobby="H1AAAA",
                           spiel="2d", version="1.1.0", grund="name", marken=[])
    for i in range(3):
        melden(i)
    with pytest.raises(schutz.MeldungsFehler) as e:
        melden(99)
    assert e.value.code == "REPORT_RATE"
    # ein anderer Melder ist davon nicht betroffen
    spei.melden(melder_schluessel="ip:9.9.9.9", melder_name="Cleo", melder_cid="", ziel_name="Z0",
                ziel_cid="", ziel_ip_kurz="", lobby="H1AAAA", spiel="2d", version="1.1.0",
                grund="name", marken=[])


def test_je_lobby_hoechstens_fuenf_verschiedene_ziele(monkeypatch, tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            _tunnel(monkeypatch)
            namen = ("Anna", "Ben", "Cleo", "Dora", "Emil", "Fritz")
            sp = await _lobby(relay, namen=namen)
            for i in range(5):
                await senden(sp[0][2], {"type": "REPORT_PLAYER", "slot": i + 1,
                                        "name": namen[i + 1], "reason": "griefing"})
                assert await _bis(sp[0][1], "REPORT_OK")
            await senden(sp[0][2], {"type": "REPORT_PLAYER", "slot": 1, "name": "Ben", "reason": "name"})
            assert await _bis(sp[0][1], "REPORT_OK")                # schon gemeldet: kein Fehler
            _schliessen(sp)
    _lauf(go())


def test_meldung_ueberlebt_neustart_und_werkzeug_liest_sie(monkeypatch, tmp_path, capsys):
    spei = schutz.MeldungsSpeicher(str(tmp_path / "mm"))
    e = spei.melden(melder_schluessel="ip:1.1.1.1", melder_name="Ben", melder_cid="cidBen00",
                    ziel_name="Anna", ziel_cid="cidAnna0", ziel_ip_kurz="abc", lobby="H1AAAA",
                    spiel="3d", version="1.1.0", grund="cheating", marken=["SPRUNG"])
    spei2 = schutz.MeldungsSpeicher(str(tmp_path / "mm"))
    assert [m["id"] for m in spei2.liste] == [e["id"]]

    import importlib.util, os
    pfad = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "tools", "meldungen_verwalten.py")
    spec = importlib.util.spec_from_file_location("meldungen_verwalten", pfad)
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)

    d = str(tmp_path / "mm")
    assert w.main(["--dir", d, "list"]) == 0
    aus = capsys.readouterr().out
    assert e["id"] in aus and "Anna" in aus and "SPRUNG" in aus and "1 angezeigt" in aus
    assert w.main(["--dir", d, "list", "--spiel", "2d"]) == 0
    assert "0 angezeigt" in capsys.readouterr().out
    assert w.main(["--dir", d, "top"]) == 0
    assert "Anna" in capsys.readouterr().out
    assert w.main(["--dir", d, "zeige", e["id"]]) == 0
    assert "cheating" in capsys.readouterr().out
    assert w.main(["--dir", d, "erledigt", e["id"]]) == 0
    assert w.main(["--dir", d, "list", "--offen"]) == 0
    assert "0 angezeigt" in capsys.readouterr().out
    # der laufende Server sieht die Aenderung von selbst
    assert schutz.MeldungsSpeicher(d).liste[0]["erledigt"] is True
    assert w.main(["--dir", d, "loeschen", e["id"]]) == 0
    assert schutz.MeldungsSpeicher(d).liste == []
    assert w.main(["--dir", d, "loeschen", "00000000"]) == 1
    assert w.main(["--dir", d, "loeschen"]) == 2
    assert w.main(["--dir", str(tmp_path / "gibt-es-nicht"), "list"]) == 2
