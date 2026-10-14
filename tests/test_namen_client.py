"""Die Absage ``BAD_NAME`` des Relays im 3D-Spiel (Plan 1.1.0).

Der Relay lehnt verbotene Namen ab (``tests/test_namen_server.py``); hier wird
geprueft, dass das Spiel daraus einen verstaendlichen, uebersetzten Satz macht:

* Lobbyseite: ``JOIN_FAIL`` (Spieler-/Lobbyname beim HOST/JOIN) und ``ERROR``
  (Lobbyname per SET_LOBBY_INFO)
* Streckenclient: ``TRACK_ERROR`` beim Hochladen, Ende zu Ende gegen einen
  echten Relay
"""
from __future__ import annotations

import pytest

from src.core import i18n
from src.net import servertext, strecken_client
from src.net.strecken_client import StreckenFehler
from tests.strecken_hilfe import rundkurs
from tests.test_lobbyliste_client import seite  # noqa: F401  (Fixture)
from tests.test_strecken_client import _RelayImFaden


@pytest.fixture(autouse=True)
def _sprache():
    alt = i18n.current()
    i18n.set_language("de")
    yield
    i18n.set_language(alt)


@pytest.mark.parametrize("feld", ["player", "lobby", ""])
def test_join_fail_bad_name_zeigt_den_uebersetzten_satz(seite, feld):  # noqa: F811
    seite._view = seite.olp._CONNECTING
    seite._return_view = seite.olp._HOST if hasattr(seite.olp, "_HOST") else seite.olp._BROWSER
    seite._on_net({"source": "tcp", "data": {
        "type": "JOIN_FAIL", "code": "BAD_NAME", "field": feld,
        "reason": "Dieser Name ist nicht erlaubt."}})
    assert seite._msg == servertext.name_absage(feld)
    assert "nicht erlaubt" in seite._msg

    i18n.set_language("en")
    seite._on_net({"source": "tcp", "data": {
        "type": "JOIN_FAIL", "code": "BAD_NAME", "field": feld, "reason": "x"}})
    assert "allowed" in seite._msg and "nicht" not in seite._msg


def test_error_bad_name_beim_aendern_des_lobbynamens(seite):  # noqa: F811
    seite._on_net({"source": "tcp", "data": {
        "type": "ERROR", "code": "BAD_NAME", "field": "lobby",
        "reason": "Dieser Name ist nicht erlaubt."}})
    assert seite._msg == servertext.name_absage("lobby")


def test_ein_relay_kann_den_satz_nicht_selbst_vorgeben(seite):  # noqa: F811
    """Bei BAD_NAME zaehlt der Satz des Spiels, nicht der ``reason`` des Relays."""
    seite._on_net({"source": "tcp", "data": {
        "type": "JOIN_FAIL", "code": "BAD_NAME", "field": "player",
        "reason": "Zahle 5 Euro, dann darfst du so heissen."}})
    assert "Euro" not in seite._msg


def test_hochladen_mit_verbotenem_namen_gegen_echten_relay(tmp_path_factory, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    speicher = tmp_path_factory.mktemp("relay_namen")
    with _RelayImFaden(str(speicher), pro_tag=9) as r:
        monkeypatch.setattr(strecken_client.server_probe, "resolve_endpoint",
                            lambda s: ("127.0.0.1", r.port, r.port))
        sd = r.server
        entwurf = rundkurs(8, 6, name="Netzrunde")

        with pytest.raises(StreckenFehler) as f:
            strecken_client.hochladen(sd, entwurf, "Hurensohn Ring", "Anna")
        assert f.value.code == "BAD_NAME"
        assert f.value.text == servertext.name_absage("track")

        with pytest.raises(StreckenFehler) as f:
            strecken_client.hochladen(sd, entwurf, "Netzrunde", "Hitler")
        assert f.value.code == "BAD_NAME"
        assert f.value.text == servertext.name_absage("player")

        # ein erlaubter Name geht danach ohne Umweg durch (nichts blieb haengen)
        assert strecken_client.hochladen(sd, entwurf, "Netzrunde", "Anna")["name"] == "Netzrunde"
        assert strecken_client.liste(sd)["total"] == 1
