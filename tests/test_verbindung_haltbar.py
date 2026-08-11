"""Die Verbindung darf nicht abreissen, nur weil man sich ein Auto aussucht.

Gemeldet am 07.08.2026: „Nach der Fahrzeugauswahl ist der User aus der Lobby
geflogen und musste neu joinen, wieso? Keine Ahnung, es gab auch keine
Fehlermeldung; dem Host wurde aber weiterhin angezeigt, dass der User sich noch
in der Lobby befindet." Vom Melder als „kein Muss-Fix" eingestuft.

**Es ist einer.** Die Ursache ist kein Zufall und kein Randfall:

``NetworkClient.update(dt)`` schickt alle 20 Sekunden ein ``PING`` ueber TCP.
Der Server wartet in ``_recv`` hoechstens **60 Sekunden** auf den naechsten
Nachrichtenkopf und schliesst danach die Verbindung. Der Keepalive ist also die
einzige Sache, die eine stille Lobby am Leben haelt.

Gerufen wurde ``update`` an **zwei** Stellen: in ``OnlineLobbyPage.update`` und
in ``RaceState``. Die Fahrzeugauswahl ist ein eigener Zustand — dort laeuft
keine von beiden. Wer laenger als eine Minute durch fuenfzehn Autos blaettert,
faellt heraus. Dasselbe gilt fuer Streckenauswahl, Werkstatt und Ladebildschirm.

Dass dabei nichts zu sehen war, passt genau ins Bild: die Trennung faellt in
eine Zeit, in der niemand die Ereignisschlange liest. Und dass der Host den
Gast weiter sah, auch: er stand noch in seiner zuletzt empfangenen Spielerliste.

Der Keepalive gehoert deshalb dorthin, wo jeder Bildschritt vorbeikommt — in
die Zustandsmaschine.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.core.state_machine import StateMachine  # noqa: E402


class _ZustandsAttrappe:
    """Ein Zustand, der nichts tut — es geht nur um den Rahmen darum herum."""

    def __init__(self) -> None:
        self.bilder = 0

    def enter(self, **kwargs) -> None:
        pass

    def exit(self) -> None:
        pass

    def handle_events(self, events) -> None:
        pass

    def update(self, dt: float) -> None:
        self.bilder += 1

    def render(self, screen) -> None:
        pass


class _NetzAttrappe:
    """Zaehlt, wie oft und mit wie viel Zeit sie getickt wurde."""

    def __init__(self) -> None:
        self.ticks = 0
        self.zeit = 0.0

    def update(self, dt: float) -> None:
        self.ticks += 1
        self.zeit += dt

    def poll(self):
        return iter(())

    def disconnect(self) -> None:
        pass


@pytest.fixture
def netz(monkeypatch):
    from src.net import session
    attrappe = _NetzAttrappe()
    monkeypatch.setattr(session, "_client", attrappe, raising=False)
    return attrappe


@pytest.mark.parametrize("zustand", [
    "car_select", "track_select", "menu", "race", "vehicle_lab", "editor",
])
def test_die_verbindung_wird_in_jedem_zustand_am_leben_gehalten(netz, zustand):
    """Der Kern des Funds: es darf keinen Zustand geben, der sie verhungern laesst.

    Geprueft wird nicht die Fahrzeugauswahl allein — die war nur die, in der es
    aufgefallen ist. Streckenauswahl, Werkstatt und Ladebildschirm haetten
    dasselbe getan.
    """
    sm = StateMachine()
    sm.register(zustand, _ZustandsAttrappe())
    sm.transition(zustand)

    sm.update(1 / 60)

    assert netz.ticks == 1, (
        f"im Zustand {zustand!r} wurde die Verbindung nicht getickt — nach "
        f"60 s ohne PING schliesst der Server sie")


def test_die_verbindung_wird_genau_einmal_je_bild_getickt(netz):
    """Zweimal ticken hiesse doppelt so haeufig pingen.

    Nicht schaedlich, aber falsch: die Abstaende im Client sind gegen die
    Wartezeit des Servers abgestimmt, und wer sie verdoppelt, misst am Ende
    etwas anderes als er glaubt.
    """
    from src.states.menu_shell_state import MenuShellState

    sm = StateMachine()
    sm.register("menu", MenuShellState(sm))
    sm.transition("menu")

    sm.update(1 / 60)

    assert netz.ticks == 1, f"{netz.ticks} Ticks fuer ein Bild"
    assert netz.zeit == pytest.approx(1 / 60), netz.zeit


def test_ohne_sitzung_passiert_nichts(monkeypatch):
    """Der Normalfall ist ein Spiel ohne Netz — das darf nichts kosten."""
    from src.net import session
    monkeypatch.setattr(session, "_client", None, raising=False)

    sm = StateMachine()
    zustand = _ZustandsAttrappe()
    sm.register("menu", zustand)
    sm.transition("menu")
    sm.update(1 / 60)

    assert zustand.bilder == 1


def test_ein_stolpernder_keepalive_haelt_das_spiel_nicht_an(monkeypatch):
    """Ein Netzfehler darf den Bildlauf nicht mitreissen.

    Der Keepalive sitzt jetzt vor **jedem** Zustandsupdate. Wuerde eine
    Ausnahme von dort durchschlagen, stuende bei einem Netzproblem das ganze
    Spiel — auch das Rennen, das gerade laeuft.
    """
    from src.net import session

    class _Kaputt(_NetzAttrappe):
        def update(self, dt: float) -> None:
            raise OSError("Leitung weg")

    monkeypatch.setattr(session, "_client", _Kaputt(), raising=False)

    sm = StateMachine()
    zustand = _ZustandsAttrappe()
    sm.register("race", zustand)
    sm.transition("race")
    sm.update(1 / 60)

    assert zustand.bilder == 1, "der Zustand wurde wegen des Netzfehlers uebersprungen"


def test_der_ping_abstand_passt_zur_wartezeit_des_servers():
    """Client und Server muessen sich ueber diese Zahl einig sein.

    20 Sekunden Abstand gegen 60 Sekunden Wartezeit: es duerfen zwei PINGs
    hintereinander verlorengehen, bevor es eng wird. Wer eine der beiden Zahlen
    aendert, ohne die andere anzusehen, baut genau den Fund vom 07.08.2026
    wieder ein — deshalb stehen sie hier nebeneinander.
    """
    import inspect
    import re

    from src.net import client as netz_client

    quelle = inspect.getsource(netz_client.NetworkClient.update)
    treffer = re.search(r"_tcp_ping_accum\s*>=\s*([\d.]+)", quelle)
    assert treffer, "der TCP-Keepalive ist nicht mehr zu finden"
    abstand = float(treffer.group(1))

    with open(os.path.join(_ROOT, "server", "server.py"), encoding="utf-8") as fh:
        server_quelle = fh.read()
    kopf = server_quelle.split("async def _recv(", 1)[1].split("\n\n", 1)[0]
    wartezeit = min(float(z) for z in re.findall(r"timeout=([\d.]+)", kopf))

    assert abstand * 3 <= wartezeit, (
        f"PING alle {abstand} s gegen {wartezeit} s Wartezeit des Servers — "
        f"ein einziger verlorener PING wirft den Spieler dann heraus")
