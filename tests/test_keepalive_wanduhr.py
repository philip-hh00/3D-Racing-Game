"""Der Keepalive zaehlt echte Sekunden, nicht Bildzeit.

Playtest 06.10.2026: „In der Online-Lobby ein Auto gewählt, Übernehmen
gedrückt — und raus aus der Lobby, neu verbinden." Derselbe Fund wie am
07.08.2026, obwohl der Keepalive seitdem in jedem Zustand tickt.

Ursache: ``NetworkClient.update`` zaehlte die 20 s bis zum naechsten ``PING``
aus dem ``dt``, das die Hauptschleife hereingibt — und die kappt jedes Bild auf
0,1 s (``GameManager.run``: ``dt = min(raw_dt, 0.1)``). Ein Bild, das eine
Sekunde dauert, zaehlte also als Zehntelsekunde. Genau solche Bilder hat die
Fahrzeugauswahl: die 3D-Vorschau laedt jedes Auto beim ersten Ansehen
(gemessen 0,4-0,8 s je Modell, 1,3 s fuer den Aufbau, auf dem Entwicklungs-
rechner) und rechnet danach jedes Bild mit SSAO, Bloom und MSAA neu. Auf einem
langsameren Rechner verging zwischen zwei PINGs mehr als die 60 s, die der
Server in ``_recv`` wartet — er schloss die Verbindung. Gemerkt hat man es erst
beim Zurueckkehren in die Lobby, wo die Ereignisschlange wieder gelesen wird:
„Verbindung zum Server getrennt".

Der Abstand wird jetzt an der Uhr gemessen; wie lang ein Bild war, spielt keine
Rolle mehr.
"""
from __future__ import annotations

import os
import re
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.net import client as netz_client  # noqa: E402
from src.net.client import NetworkClient  # noqa: E402


class _Uhr:
    def __init__(self) -> None:
        self.jetzt = 1000.0

    def __call__(self) -> float:
        return self.jetzt


@pytest.fixture
def netz(monkeypatch):
    uhr = _Uhr()
    monkeypatch.setattr(netz_client.time, "monotonic", uhr)
    n = NetworkClient()
    n._alive = True
    n._lobby_id = "HABCDE"
    n._slot = 1
    n.gesendet = []
    monkeypatch.setattr(n, "send_tcp", lambda msg: n.gesendet.append(msg))
    monkeypatch.setattr(n, "_udp_send", lambda data: None)
    n.uhr = uhr
    return n


def _pings(n) -> int:
    return sum(1 for m in n.gesendet if m.get("type") == "PING")


def test_lange_bilder_lassen_den_keepalive_nicht_aus(netz):
    """Zwei Bilder pro Sekunde, jedes von der Hauptschleife auf 0,1 s gekappt:
    in 60 echten Sekunden muss trotzdem mehrfach gepingt worden sein."""
    for _ in range(120):
        netz.uhr.jetzt += 0.5
        netz.update(0.1)                    # was GameManager.run hereingibt
    assert _pings(netz) >= 2, (
        f"{_pings(netz)} PING in 60 s — der Server schliesst nach 60 s ohne Nachricht")


def test_schnelle_bilder_pingen_nicht_oefter(netz):
    """Die Uhr statt dt darf nicht heissen: jedes Bild ein PING."""
    for _ in range(60 * 60):
        netz.uhr.jetzt += 1 / 60
        netz.update(1 / 60)
    assert 2 <= _pings(netz) <= 4, f"{_pings(netz)} PING in 60 s"


def test_ohne_lobby_wird_nicht_gepingt(netz):
    netz._lobby_id = ""
    netz.uhr.jetzt += 100.0
    netz.update(0.1)
    assert _pings(netz) == 0


def test_der_abstand_passt_zur_wartezeit_des_servers():
    """Siehe tests/test_verbindung_haltbar.py — hier fuer die Konstante."""
    with open(os.path.join(_ROOT, "server", "server.py"), encoding="utf-8") as fh:
        server_quelle = fh.read()
    kopf = server_quelle.split("async def _recv(", 1)[1].split("\n\n", 1)[0]
    wartezeit = min(float(z) for z in re.findall(r"timeout=([\d.]+)", kopf))
    assert netz_client.TCP_KEEPALIVE_S * 3 <= wartezeit
