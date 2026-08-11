"""Block H, Stufe 1 — die clientseitigen Befunde aus der Sicherheitsanalyse.

Vier Befunde, alle ohne Server-Deploy und ohne Protokolländerung behebbar
(Releaseplan §7a H3 Schritt 1):

* **H2.2** Der Streckenlader stürzte an drei über das Netz erreichbaren Stellen
  ab: ``RecursionError`` bei tief verschachteltem JSON, ``UnicodeDecodeError``
  bei ungültigem UTF-8, ``OverflowError`` bei einer Zahl größer als ``float``.
  Gefangen wurden nur ``OSError`` und ``JSONDecodeError``, und ``race_state``
  fängt nur ``TrackDataError`` — es endete also im ``crash.log``. Über Block G
  (Streckenvorschläge) kann das **jedes Lobbymitglied** auslösen.
* **H2.6** Der Client hatte keine Summengrenze beim Empfang.
* **H2.10** Der vom Host gelieferte Streckenpfad ging ungeprüft in
  ``find_track``, das ihn zuerst **roh** probiert — auch absolut.
* **H2.11** Windows-Gerätenamen passierten den Dateinamenfilter.

Jeder Test hält den Fehler fest, nicht nur die Behebung: fällt eine Prüfung
später wieder heraus, schlägt hier etwas fehl.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pymunk
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core import paths  # noqa: E402
from src.track.track import (MAX_TIEFE, Track, TrackDataError,  # noqa: E402
                             _tiefe_ueberschritten)


def _gueltige_strecke() -> dict:
    return {
        "name": "Testkurs",
        "track_width": 100.0,
        "centerline": [{"x": float(i * 40), "y": 0.0} for i in range(12)],
        "outer_wall": [],
        "inner_wall": [],
        "waypoints": [],
    }


def _schreiben(ordner: Path, inhalt) -> str:
    ziel = ordner / "strecke.json"
    if isinstance(inhalt, bytes):
        ziel.write_bytes(inhalt)
    else:
        ziel.write_text(inhalt if isinstance(inhalt, str) else json.dumps(inhalt),
                        encoding="utf-8")
    return str(ziel)


# ---------------------------------------------------------------------------
# H2.2 — Streckenlader
# ---------------------------------------------------------------------------
def test_gueltige_strecke_laedt_weiterhin(tmp_path):
    """Absicherung der Absicherung: die Härtung darf nichts Gutes abweisen."""
    t = Track(_schreiben(tmp_path, _gueltige_strecke()), pymunk.Space())
    assert len(t.centerline) == 12
    assert t.name == "Testkurs"


def test_tief_verschachteltes_json_stuerzt_nicht_ab(tmp_path):
    """Vorher: RecursionError aus json.load, an jeder Fehlerbehandlung vorbei."""
    pfad = _schreiben(tmp_path, "[" * 100_000 + "]" * 100_000)
    with pytest.raises(TrackDataError):
        Track(pfad, pymunk.Space())


def test_ungueltiges_utf8_stuerzt_nicht_ab(tmp_path):
    """Vorher: UnicodeDecodeError — kein JSONDecodeError, also ungefangen."""
    pfad = _schreiben(tmp_path, b"\xff\xfe{\"name\": \"x\"}")
    with pytest.raises(TrackDataError):
        Track(pfad, pymunk.Space())


def test_zahl_groesser_als_float_stuerzt_nicht_ab(tmp_path):
    """Vorher: OverflowError in float(10**400).

    Erwartet wird **kein** Fehler, sondern der Vorgabewert: eine unbrauchbare
    Streckenbreite darf die Strecke nicht unfahrbar machen.
    """
    daten = _gueltige_strecke()
    daten["track_width"] = 10 ** 400
    t = Track(_schreiben(tmp_path, daten), pymunk.Space())
    assert t.track_width == pytest.approx(100.0)


def test_riesige_zahl_im_punkt_wird_verworfen(tmp_path):
    """Punkte mit unbrauchbaren Zahlen fallen weg; bleibt zu wenig übrig,
    ist es eine TrackDataError und kein Absturz."""
    daten = _gueltige_strecke()
    daten["centerline"] = [{"x": 10 ** 400, "y": 0}] * 5
    with pytest.raises(TrackDataError):
        Track(_schreiben(tmp_path, daten), pymunk.Space())


@pytest.mark.parametrize("inhalt", [
    "",                                   # leer
    "{",                                  # abgeschnitten
    "[1, 2, 3]",                          # kein Objekt
    '{"centerline": "keine Liste"}',      # falscher Typ
    '{"track_width": NaN, "centerline": [{"x": Infinity, "y": 0}]}',
    '{"centerline": [{"x": {"a": 1}, "y": [2]}]}',
])
def test_beschaedigte_dateien_geben_trackdataerror(tmp_path, inhalt):
    with pytest.raises(TrackDataError):
        Track(_schreiben(tmp_path, inhalt), pymunk.Space())


def test_tiefenpruefung_meldet_keine_falschen_treffer():
    """Klammern in Zeichenketten dürfen nicht zählen — sonst löst ein
    Streckenname wie ``[[Oval]]`` die Prüfung aus."""
    assert not _tiefe_ueberschritten(json.dumps(_gueltige_strecke()))
    assert not _tiefe_ueberschritten('{"name": "' + "[" * 500 + '"}')
    assert not _tiefe_ueberschritten('{"name": "\\\\[\\\\[\\\\["}')
    assert _tiefe_ueberschritten("[" * (MAX_TIEFE + 1))
    assert not _tiefe_ueberschritten("[]" * 10_000)      # breit, nicht tief


def test_klammern_im_streckennamen_laden(tmp_path):
    daten = _gueltige_strecke()
    daten["name"] = "[[Oval]] {schnell}"
    t = Track(_schreiben(tmp_path, daten), pymunk.Space())
    assert t.name == "[[Oval]] {schnell}"


# ---------------------------------------------------------------------------
# H2.11 — Windows-Gerätenamen
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("roh", [
    "CON", "CON.json", "con.json", "NUL.json", "PRN", "AUX.json",
    "COM1.json", "COM9", "LPT1.json", "LPT9.json", "clock$.json",
])
def test_windows_geraetenamen_werden_entschaerft(roh):
    """Windows fängt diese Namen in **jedem** Ordner ab: ``C:\\x\\CON.json``
    öffnet die Konsole, nicht eine Datei. Eine geschenkte Strecke mit so einem
    Namen schrieb damit an einen Treiber."""
    erg = paths.safe_track_filename(roh)
    stamm = erg[:-5] if erg.lower().endswith(".json") else erg
    assert stamm.upper() not in paths._WIN_GERAETE, erg
    assert erg.lower().endswith(".json")


def test_geraetename_bleibt_erkennbar():
    """Entschärfen heißt nicht wegwerfen — der Name soll noch lesbar sein."""
    assert paths.safe_track_filename("CON.json") == "_CON.json"


@pytest.mark.parametrize("roh", ["CONTUR.json", "COMET.json", "NULL.json",
                                 "LPT.json", "COM.json", "COM10.json"])
def test_aehnliche_namen_bleiben_unangetastet(roh):
    """Nur die echten Gerätenamen, keine, die nur so anfangen."""
    assert paths.safe_track_filename(roh) == roh


# ---------------------------------------------------------------------------
# H2.10 — fremder Pfad wird zum Dateinamen
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("fremd,erwartet", [
    ("/etc/passwd", "passwd.json"),
    ("C:/Windows/win.ini", "win.ini.json"),
    ("C:\\Windows\\System32\\config\\SAM", "SAM.json"),
    ("../../../../etc/shadow", "shadow.json"),
    ("data/tracks/oval.json", "oval.json"),
    ("/home/jemand/.ssh/id_rsa", "id_rsa.json"),
])
def test_fremder_streckenpfad_wird_auf_dateinamen_reduziert(fremd, erwartet):
    """Der Host bestimmt ``track_path``. Ungeprüft ging der in ``find_track``,
    das ihn zuerst roh probiert — auch absolut. Damit war am Verhalten des
    Gastes ablesbar, ob eine Datei auf dessen Platte existiert.

    Gebraucht wird ohnehin nur der Name: ``find_track`` sucht ihn in allen
    Streckenordnern, und eine eigene Strecke des Hosts kommt über den
    Rennstart-Transfer.
    """
    assert paths.safe_track_filename(fremd, fallback="online_track.json") == erwartet


class _ShellStub:
    """Genug Shell, damit eine Menueseite ihr enter() durchlaufen kann."""

    def __init__(self) -> None:
        self.state_machine = type("SM", (), {"transition": lambda *a, **k: None})()
        self.page_stack: list = []

    def pop_page(self) -> None:
        pass


def test_uebernahme_vom_host_reduziert_den_pfad(monkeypatch):
    """Der eigentliche Fix von H2.10 sitzt an der **Uebernahmestelle**, nicht in
    ``safe_track_filename`` — das gab es vorher schon. Hier laeuft der
    LOBBY_STATE-Zweig eines Gastes wirklich durch.

    Ohne diesen Test hielte die Datei den Befund nur scheinbar fest: die
    Pruefungen darueber testen eine Funktion, die es vorher schon gab.

    Die Seite wird ueber ihren echten Konstruktor und ``enter()`` aufgebaut, nicht
    Attribut fuer Attribut zusammengesteckt — sonst bricht der Test bei jeder
    Aenderung am LOBBY_STATE-Zweig, ohne dass am Befund etwas dran waere.
    """
    from src.net import session as _session
    from src.states.menu.online_lobby_page import OnlineLobbyPage

    monkeypatch.setattr(_session, "get", lambda: None)
    seite = OnlineLobbyPage()
    seite.enter(_ShellStub())
    seite._is_host = False
    seite._srv_track_path = None
    seite._custom_track_local = "alte_kopie.json"

    seite._on_net({"source": "tcp", "data": {
        "type": "LOBBY_STATE",
        "players": [],
        "settings": {"track_path": "/etc/passwd"},
    }})

    pfad = str(seite._selected_track_path or "")
    assert pfad == "passwd.json", f"Fremdpfad nicht reduziert: {pfad!r}"
    assert "/" not in pfad and "\\" not in pfad
    assert not Path(pfad).is_absolute()
    # Rohwert bleibt zur Aenderungserkennung erhalten.
    assert seite._srv_track_path == "/etc/passwd"
    # Eine alte Kopie muss verworfen werden, sonst faehrt man die vorige Strecke.
    assert seite._custom_track_local is None


@pytest.mark.parametrize("fremd", ["C:\\Windows\\win.ini", "../../etc/shadow",
                                   "/proc/self/environ"])
def test_uebernahme_faengt_weitere_fremdpfade(monkeypatch, fremd):
    from src.net import session as _session
    from src.states.menu.online_lobby_page import OnlineLobbyPage

    monkeypatch.setattr(_session, "get", lambda: None)
    seite = OnlineLobbyPage()
    seite.enter(_ShellStub())
    seite._is_host = False
    seite._srv_track_path = None

    seite._on_net({"source": "tcp", "data": {
        "type": "LOBBY_STATE", "players": [], "settings": {"track_path": fremd},
    }})
    pfad = str(seite._selected_track_path or "")
    assert "/" not in pfad and "\\" not in pfad, pfad
    assert not Path(pfad).is_absolute()


def test_eingebaute_strecke_bleibt_auffindbar():
    """Die Reduktion darf den Normalfall nicht brechen: aus dem Pfad einer
    mitgelieferten Strecke muss weiterhin dieselbe Datei gefunden werden."""
    name = paths.safe_track_filename("data/tracks/oval.json")
    assert name == "oval.json"
    assert paths.find_track(name) is not None


# ---------------------------------------------------------------------------
# H2.6 — Summengrenze beim Empfang
# ---------------------------------------------------------------------------
def test_empfang_bricht_ueber_der_grenze_ab():
    """Vorher hing die Grenze nur am Hochladen: MAP_CHUNK und
    OFFER_DATA_CHUNK wurden unbegrenzt angehängt, ein bösartiger Relay konnte
    damit den Arbeitsspeicher füllen."""
    from src.states.menu.online_lobby_page import (OnlineLobbyPage,
                                                   _EMPFANG_MAX_ZEICHEN)
    seite = OnlineLobbyPage.__new__(OnlineLobbyPage)
    seite._msg = ""
    puffer: list[str] = []
    stueck = "A" * 65536

    angenommen = 0
    for _ in range(_EMPFANG_MAX_ZEICHEN // len(stueck) + 5):
        if seite._stueck_anhaengen(puffer, stueck, "Strecke"):
            angenommen += 1
        else:
            break

    assert angenommen > 0, "die Grenze darf nicht schon das erste Stück abweisen"
    assert puffer == [], "der Puffer muss verworfen werden, eine halbe Datei ist nutzlos"
    assert seite._msg, "der Abbruch muss dem Spieler gesagt werden"
    assert angenommen * len(stueck) <= _EMPFANG_MAX_ZEICHEN


def test_empfang_nimmt_normale_uebertragung_an():
    """Eine echte Strecke (~40 KB) muss durchgehen."""
    from src.states.menu.online_lobby_page import OnlineLobbyPage
    seite = OnlineLobbyPage.__new__(OnlineLobbyPage)
    seite._msg = ""
    puffer: list[str] = []
    for _ in range(2):
        assert seite._stueck_anhaengen(puffer, "B" * 32766, "Strecke")
    assert len(puffer) == 2
    assert seite._msg == ""


def test_empfang_ignoriert_falschen_typ():
    """Ein Stück, das kein Text ist, darf nicht in den Puffer und nicht werfen."""
    from src.states.menu.online_lobby_page import OnlineLobbyPage
    seite = OnlineLobbyPage.__new__(OnlineLobbyPage)
    seite._msg = ""
    puffer: list[str] = []
    assert not seite._stueck_anhaengen(puffer, None, "Strecke")
    assert not seite._stueck_anhaengen(puffer, 12345, "Strecke")
    assert puffer == []
