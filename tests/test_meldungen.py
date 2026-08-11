"""Eine Meldung ist entweder ein Zustand oder eine Mitteilung — nichts dazwischen.

Gemeldet am 07.08.2026: „Wenn das Fahrzeug gewechselt wird, wird ein roter Text
in der Fußzeile angezeigt, der sich nicht von alleine ausblendet."

Nachgestellt: ein Gast waehlt ein Auto ausserhalb der Fahrzeugklasse der Lobby.
Der Server schickt daraufhin den naechsten Lobbyzustand, ``_enforce_vehicle_class``
zieht das Auto zurueck in die Klasse und meldet das — mit ``self._msg = ...``
statt mit ``self._melde(...)``. Der Unterschied: ``_melde`` setzt ``_msg_until``,
und ``update()`` raeumt die Meldung danach weg. Ohne das steht sie bis zum
naechsten Ereignis, das sie zufaellig ueberschreibt, also praktisch bis zum
Verlassen der Lobby.

**Die Regel dahinter**, und darum geht es hier:

* **Zustand** — „Mindestens 2 Spieler erforderlich", „Nicht alle Spieler sind
  bereit", „Verbindung fehlgeschlagen". Sie beschreiben, warum es gerade nicht
  weitergeht. Sie muessen stehen bleiben, bis sich die Lage aendert; sie von
  selbst ausblenden zu lassen hiesse, den Grund zu verstecken.
* **Mitteilung** — „Fahrzeug an die Klasse angepasst", „Gespeichert als …",
  „Der Gastgeber hat den Grand Prix beendet". Sie beschreiben ein **Ereignis**,
  das vorbei ist. Sie gehoeren nach ein paar Sekunden weg.

Der Test prueft nicht die eine gemeldete Stelle, sondern die Einteilung: jede
Zuweisung an ``_msg`` ohne Ablauf muss unten als Zustand aufgefuehrt sein. Wer
eine neue Meldung einbaut, muss sich also entscheiden — und die Entscheidung
steht danach hier, mit Begruendung.
"""
from __future__ import annotations

import ast
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

_QUELLE = os.path.join(_ROOT, "src", "states", "menu", "online_lobby_page.py")


#: Meldungen, die bewusst stehen bleiben, mit dem Grund dafuer. Der Schluessel
#: ist ein Stueck des Texts, das im Quelltext vorkommt.
_ZUSTAENDE = {
    "Mindestens 2 Spieler":
        "Der Startknopf bleibt gesperrt, solange das gilt. Blendete der Grund "
        "aus, staende da ein toter Knopf ohne Erklaerung",
    "Nicht alle Spieler sind bereit":
        "Dasselbe: die Antwort auf einen Druck auf Start, die gilt, bis "
        "jemand bereit meldet",
    "Verbindung fehlgeschlagen":
        "Der Grund, warum der Beitritt nicht geklappt hat. Er wird beim "
        "naechsten Tippen im Codefeld geleert",
    "Verbindung zum Server getrennt":
        "Wie oben — der Nutzer steht wieder auf der Rollenauswahl und soll "
        "wissen, warum",
    "ist veraltet":
        "Die Versionswarnung. Sie darf nicht weghuschen, sie ist die "
        "Handlungsanweisung",
    "Kein Server verfügbar":
        "Zustand der Serverliste, kein Ereignis",
    "Lobby-Code muss 6 Zeichen":
        "Antwort auf eine Eingabe; wird beim naechsten Tippen geleert",
    "Unbekannter Lobby-Code":
        "Dito",
    "Server nicht erreichbar":
        "Dito",
    "Teams nicht ausgeglichen":
        "Sperrt den Start im Team-Zeitfahren. Der Grund gehoert neben den "
        "gesperrten Knopf",
    "_servertext":
        "Begruendung vom Relay (Rauswurf, geschlossene Lobby). Fremdtext, der "
        "erklaert, warum der Nutzer nicht mehr in der Lobby ist",
    "ohne Aktivität geschlossen":
        "Der Grund, warum die Lobby weg ist. Er steht auf der Rollenauswahl "
        "und soll dort bleiben, bis der Nutzer etwas tut",
}


def _zuweisungen() -> list[tuple[int, str]]:
    """Jede Zuweisung an ``self._msg``, die nicht leert — Zeile und Quelltext."""
    with open(_QUELLE, encoding="utf-8") as fh:
        quelle = fh.read()
    zeilen = quelle.split("\n")
    baum = ast.parse(quelle)

    treffer: list[tuple[int, str]] = []
    for knoten in ast.walk(baum):
        if not isinstance(knoten, ast.Assign):
            continue
        for ziel in knoten.targets:
            if not (isinstance(ziel, ast.Attribute) and ziel.attr == "_msg"
                    and isinstance(ziel.value, ast.Name)
                    and ziel.value.id == "self"):
                continue
            if isinstance(knoten.value, ast.Constant) and knoten.value.value == "":
                continue        # Leeren ist immer erlaubt
            ende = getattr(knoten, "end_lineno", knoten.lineno)
            text = "\n".join(zeilen[knoten.lineno - 1:ende])
            treffer.append((knoten.lineno, text))
    return treffer


def _hat_ablauf(zeile: int) -> bool:
    """Ob in derselben Anweisungsgruppe auch ``_msg_until`` gesetzt wird.

    Gemeint ist der Rumpf von ``_melde`` selbst: dort stehen beide Zeilen
    direkt beieinander. Alle anderen Stellen sollen ``_melde`` benutzen statt
    die Mechanik nachzubauen.
    """
    with open(_QUELLE, encoding="utf-8") as fh:
        zeilen = fh.read().split("\n")
    umgebung = zeilen[max(0, zeile - 2):zeile + 2]
    return any("_msg_until" in z for z in umgebung)


def test_jede_bleibende_meldung_ist_als_zustand_begruendet():
    """Neue Meldung ohne Ablauf? Dann steht sie hier — oder der Test faellt.

    Das ist der Sinn der Sache: die Entscheidung „Zustand oder Mitteilung"
    laesst sich nicht vergessen, weil sie den Test rot macht, bis jemand sie
    trifft.
    """
    unbegruendet = []
    for zeile, text in _zuweisungen():
        if _hat_ablauf(zeile):
            continue
        if any(marke in text for marke in _ZUSTAENDE):
            continue
        unbegruendet.append(f"Zeile {zeile}: {text.strip()}")

    assert unbegruendet == [], (
        "Diese Meldungen bleiben stehen, ohne dass jemand sie als Zustand "
        "eingetragen hat. Entweder ueber _melde() ausblenden lassen oder in "
        "_ZUSTAENDE begruenden:\n" + "\n".join(unbegruendet))


def test_die_liste_der_zustaende_ist_nicht_verwahrlost():
    """Ein Eintrag fuer eine Meldung, die es nicht mehr gibt, taeuscht eine
    Entscheidung vor, die niemand mehr trifft."""
    with open(_QUELLE, encoding="utf-8") as fh:
        quelle = fh.read()
    tot = [m for m in _ZUSTAENDE if m not in quelle]
    assert tot == [], f"steht in _ZUSTAENDE, aber nicht mehr im Quelltext: {tot}"


# ---------------------------------------------------------------------------
# Der gemeldete Fall, ausgefuehrt
# ---------------------------------------------------------------------------

@pytest.fixture
def lobby(monkeypatch):
    from src.entities.vehicle_factory import VehicleFactory
    from src.net import server_probe
    from src.states.menu import online_lobby_page as olp
    from tests import spielhilfe
    from tests.test_layout_regeln import _ShellAttrappe

    spielhilfe.aufbau_bewahren(monkeypatch)
    VehicleFactory.load_all_configs()
    monkeypatch.setattr(server_probe, "start", lambda: None)
    monkeypatch.setattr(server_probe, "statuses", lambda: [])

    seite = olp.OnlineLobbyPage()
    seite.enter(_ShellAttrappe())
    seite._is_host = False
    seite._view = olp._LOBBY
    seite._players = [
        {"slot": 0, "name": "A", "lobby_ready": True, "vehicle": "rookie"},
        {"slot": 1, "name": "B", "lobby_ready": False, "vehicle": "drifter"},
    ]
    return seite


def test_die_klassenanpassung_meldet_sich_und_verschwindet_wieder(lobby):
    """Der gemeldete Fall vom 07.08.2026, von vorn bis hinten.

    Der Gast steht in einer Lobby mit Klassenfilter und bringt aus der
    Fahrzeugauswahl ein Auto mit, das nicht dazu passt. Das Zurueckziehen in
    die Klasse ist richtig — nur die Meldung darueber blieb stehen.
    """
    lobby._selected_class = "Drifter"
    lobby._selected_vehicle = "supercar"        # nicht in der Klasse

    lobby._enforce_vehicle_class()

    assert lobby._msg, "die Anpassung muss ueberhaupt gemeldet werden"
    assert lobby._selected_vehicle.startswith("drifter"), \
        "das Auto muss in die Klasse gezogen werden"
    assert lobby._msg_until > 0, "die Meldung braucht einen Ablauf"

    # Und sie geht auch wirklich weg.
    lobby.update(lobby._msg_until - lobby._time + 0.1)
    assert lobby._msg == "", "die Meldung steht nach ihrer Zeit immer noch da"


def test_ein_passendes_fahrzeug_wird_nicht_kommentiert(lobby):
    """Kein Anlass, keine Meldung — sonst rauscht bei jedem Lobbyzustand eine
    Zeile durch, die nichts sagt."""
    lobby._selected_class = "Drifter"
    lobby._selected_vehicle = "drifter_2"

    lobby._enforce_vehicle_class()

    assert lobby._msg == "", lobby._msg


# ---------------------------------------------------------------------------
# Die Nachfrage: gilt dasselbe im lokalen Mehrspieler und im Einzelspieler?
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seitenname", ["LobbyPage", "MPLobbyPage"])
def test_die_anderen_lobbys_haben_die_meldung_gar_nicht(seitenname):
    """Nachgesehen, weil danach gefragt war — und die Antwort ist: nein.

    Einzelspieler- und lokale Mehrspieler-Lobby haben dieselbe rote Fusszeile,
    aber sie sagen dort etwas anderes. Ihre Meldungen sind **Antworten auf
    einen Druck auf Start** („Beide Spieler brauchen unterschiedliche
    Geraete"), also Zustaende — sie sollen stehen bleiben, bis der Nutzer die
    Lage aendert, und genau das tun sie: geleert wird bei jeder Bedienung
    (``if action: self.msg = ""``) und beim Betreten der Seite.

    Vor allem gibt es dort keine Klassenanpassung: die Klasse filtert die
    Auswahl direkt, statt eine schon getroffene Wahl nachtraeglich zu
    korrigieren. Es kann also gar keine Mitteilung entstehen, die haengen
    bleibt. Der Fund vom 07.08.2026 betrifft nur die Online-Lobby.
    """
    import inspect

    from src.states.menu import lobby_page, mp_lobby_page

    modul = lobby_page if seitenname == "LobbyPage" else mp_lobby_page
    quelle = inspect.getsource(modul)

    assert 'if action:' in quelle and 'self.msg = ""' in quelle, \
        f"{seitenname} leert die Meldung nicht mehr bei jeder Bedienung"
    assert "_enforce_vehicle_class" not in quelle, \
        (f"{seitenname} hat jetzt doch eine Klassenanpassung — dann braucht "
         f"ihre Meldung einen Ablauf wie in der Online-Lobby")


def test_ein_zustand_bleibt_stehen(lobby):
    """Die Gegenprobe zur Regel: was ein Zustand ist, darf nicht ablaufen.

    Ohne diesen Test waere die einfachste Art, den Test oben gruen zu bekommen,
    **jede** Meldung ablaufen zu lassen — und damit die Erklaerung fuer einen
    gesperrten Startknopf nach fuenf Sekunden zu verstecken.
    """
    lobby._players = [{"slot": 0, "name": "A", "lobby_ready": True,
                       "vehicle": "rookie"}]
    lobby.update(0.1)
    assert "2 Spieler" in lobby._msg

    lobby.update(60.0)
    assert "2 Spieler" in lobby._msg, \
        "der Grund fuer den gesperrten Startknopf ist verschwunden"
