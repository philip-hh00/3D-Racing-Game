"""Statistik und Erfolge (Releaseplan E1 / E1a).

**Eine** Stelle entscheidet, was zählt. Das ist der Kern: die Regeln aus E1
stehen hier und nirgends sonst — ein abgebrochenes Rennen zählt nicht, ein DNF
zählt nicht, ein Zeitfahren ist kein Rennen, im Splitscreen zählt nur Spieler 1.
Verteilt auf sechs Aufrufstellen wären das sechs Gelegenheiten, eine davon zu
vergessen, und der Fehler fiele erst auf, wenn jemand eine Freischaltung
geschenkt bekommt.

**Erfolge werden nicht gespeichert, sondern gerechnet.** Gespeichert ist allein
``statistik`` im Profil; welche Erfolge offen sind, ist eine reine Funktion
davon (:func:`erreicht`). Damit kann nichts auseinanderlaufen — kein Erfolg, der
gesetzt wurde, obwohl der Zähler ihn nicht hergibt — und jeder einzelne ist ohne
laufendes Spiel prüfbar.
"""
from __future__ import annotations

from typing import Any

#: Vorgabewerte. Ein fehlender Schlüssel ist kein Fehler, sondern eine Null —
#: dieselbe Regel wie bei ``paints`` (Block D).
VORGABE: dict[str, Any] = {
    "rennen": 0, "siege": 0, "podeste": 0,
    "meter": 0.0, "spielzeit_s": 0.0,
    "gp_siege": 0,
    #: Listen statt Zahlen, wo Vielfalt gemeint ist: dreimal dieselbe Strecke
    #: ist nicht dasselbe wie drei Strecken.
    "ghosts_geschlagen": [], "strecken_gefahren": [],
    "fahrzeuge_gefahren": [], "klassen_gewonnen": [],
    "start_ziel_siege": 0, "aufholjagden": 0, "schnellste_runden": 0,
    "online_rennen": 0, "online_siege": 0, "lobbys_gehostet": 0,
    "strecken_geteilt": 0, "fremde_strecken_gefahren": 0,
    "strecken_erstellt": 0, "strecken_veroeffentlicht": 0,
    "eigene_strecke_gefahren": 0, "eigene_strecke_gewonnen": 0,
}

_LISTEN = tuple(k for k, v in VORGABE.items() if isinstance(v, list))


# ---------------------------------------------------------------------------
# Zugriff
# ---------------------------------------------------------------------------
def werte() -> dict[str, Any]:
    """Der ``statistik``-Block des laufenden Profils, fehlende Felder ergänzt."""
    from src.core import profile
    p = profile.current()
    block = getattr(p, "statistik", None)
    if not isinstance(block, dict):
        block = {}
        p.statistik = block
    for k, v in VORGABE.items():
        if k not in block:
            block[k] = list(v) if isinstance(v, list) else v
    return block


def _zaehlen(feld: str, um: float = 1) -> None:
    block = werte()
    if isinstance(VORGABE[feld], float):
        block[feld] = float(block.get(feld, 0.0)) + float(um)
    else:
        block[feld] = int(block.get(feld, 0)) + int(um)


def _merken(feld: str, eintrag: str) -> None:
    """Einen Eintrag in eine Liste aufnehmen, wenn er noch fehlt."""
    if not eintrag:
        return
    block = werte()
    liste = block.setdefault(feld, [])
    if eintrag not in liste:
        liste.append(eintrag)


def sichern() -> None:
    from src.core import profile
    profile.current().save()


# ---------------------------------------------------------------------------
# Die Zählregeln aus E1
# ---------------------------------------------------------------------------
def rennen_zaehlt(*, beendet: bool, dnf: bool, modus: str) -> bool:
    """Ob dieser Lauf als gefahrenes Rennen gilt.

    Die vier Regeln aus E1 an einer Stelle:

    * **abgebrochen** zählt nicht — sonst treibt Starten-und-Abbrechen jeden
      Zähler hoch und die Freischaltung ist keine Leistung mehr,
    * **DNF** zählt nicht — wer ausrollt, war da, aber nicht im Ziel,
    * **Zeitfahren** ist kein Rennen — Runden drehen ist etwas anderes als
      fahren; Bestzeiten und geschlagene Ghosts werden getrennt geführt,
    * **online** zählt mit — ein Rennen gegen echte Leute ist mehr Rennen, nicht
      weniger.
    """
    if not beendet or dnf:
        return False
    return str(modus).strip().lower() not in ("zeitfahren", "time_trial")


def rennen_gewertet(zeile: dict, *, modus: str = "", online: bool = False,
                    beendet: bool = True, strecke: str = "",
                    eigene_strecke: bool = False, teilnehmer: int = 0,
                    startplatz: int | None = None,
                    beste_runde_im_feld: bool = False) -> bool:
    """Ein abgeschlossenes Rennen verbuchen. Gibt zurück, ob es gezählt hat.

    *zeile* ist die Ergebniszeile des **eigenen** Fahrzeugs, so wie
    ``race_state`` sie baut. Im Splitscreen wird nur Spieler 1 übergeben: es
    gibt ein Profil je Rechner, und der Besucher am zweiten Controller sammelt
    keine Freischaltungen, die dem Besitzer gehören.
    """
    dnf = bool(zeile.get("dnf"))
    if not rennen_zaehlt(beendet=beendet, dnf=dnf, modus=modus):
        return False

    platz = int(zeile.get("position") or 0)
    _zaehlen("rennen")
    _merken("strecken_gefahren", strecke)
    _merken("fahrzeuge_gefahren", str(zeile.get("vehicle") or ""))
    if eigene_strecke:
        _zaehlen("eigene_strecke_gefahren")
    if online:
        _zaehlen("online_rennen")

    gewonnen = platz == 1
    if gewonnen:
        _zaehlen("siege")
        _merken("klassen_gewonnen", _klasse(str(zeile.get("vehicle") or "")))
        if online:
            _zaehlen("online_siege")
        if eigene_strecke:
            _zaehlen("eigene_strecke_gewonnen")
        if startplatz == 0:
            # Von ganz vorn gestartet und vorn geblieben.
            _zaehlen("start_ziel_siege")
    if 1 <= platz <= 3:
        _zaehlen("podeste")
        # Aufholjagd nur, wenn es überhaupt jemanden zu überholen gab: vom
        # letzten Platz eines Zweierfeldes aufs Podest ist keine Leistung.
        if (startplatz is not None and teilnehmer >= 4
                and startplatz >= teilnehmer - 1):
            _zaehlen("aufholjagden")
    if beste_runde_im_feld:
        _zaehlen("schnellste_runden")
    sichern()
    return True


def _klasse(fahrzeug: str) -> str:
    from src.core import race_setup
    for klasse, keys in race_setup.CLASSES.items():
        if klasse != "Alle" and fahrzeug in keys:
            return klasse
    return ""


def fahrt_gezaehlt(meter: float, sekunden: float) -> None:
    """Strecke und Zeit hinter dem Steuer. Läuft mit, auch im Zeitfahren —
    gefahren ist gefahren, nur als *Rennen* zählt es dort nicht."""
    if meter > 0:
        _zaehlen("meter", float(meter))
    if sekunden > 0:
        _zaehlen("spielzeit_s", float(sekunden))


def gp_gewonnen() -> None:
    _zaehlen("gp_siege")
    sichern()


def ghost_geschlagen(strecke: str) -> None:
    _merken("ghosts_geschlagen", strecke)
    sichern()


def strecke_erstellt() -> None:
    _zaehlen("strecken_erstellt")
    sichern()


def strecke_veroeffentlicht() -> None:
    _zaehlen("strecken_veroeffentlicht")
    sichern()


def lobby_gehostet() -> None:
    _zaehlen("lobbys_gehostet")
    sichern()


def strecke_geteilt() -> None:
    _zaehlen("strecken_geteilt")
    sichern()


def fremde_strecke_gefahren() -> None:
    _zaehlen("fremde_strecken_gefahren")
    sichern()


# ---------------------------------------------------------------------------
# Erfolge (E1a)
# ---------------------------------------------------------------------------
#: (Schlüssel, Gruppe, Name, Bedingungstext, Zähler, Ziel)
#:
#: *Zähler* ist entweder ein Feldname oder eine Funktion auf der Statistik.
#: Beides ergibt eine Zahl, damit die Anzeige immer „7 / 20" zeigen kann und
#: nicht nur „offen" — ohne Zahl weiß niemand, ob er kurz davor ist.
ERFOLGE: list[tuple[str, str, str, str, Any, int]] = [
    ("rennen_5",       "Menge", "Erste Runden",        "5 Rennen gefahren", "rennen", 5),
    ("rennen_20",      "Menge", "Stammfahrer",         "20 Rennen gefahren", "rennen", 20),
    ("rennen_50",      "Menge", "Dauergast",           "50 Rennen gefahren", "rennen", 50),
    ("sieg_1",         "Menge", "Erster Sieg",         "ein Rennen gewonnen", "siege", 1),
    ("sieg_5",         "Menge", "Seriensieger",        "fünf Rennen gewonnen", "siege", 5),
    ("sieg_20",        "Menge", "Titelsammler",        "20 Rennen gewonnen", "siege", 20),
    ("podest_10",      "Menge", "Podestreif",          "zehnmal auf dem Podest", "podeste", 10),
    ("meter_100k",     "Menge", "Langstrecke",         "100 km gefahren",
     lambda s: int(float(s.get("meter", 0.0)) / 1000.0), 100),
    ("gp_1",           "Menge", "Grand-Prix-Sieger",   "eine Serie gewonnen", "gp_siege", 1),
    ("gp_5",           "Menge", "Meisterschaft",       "fünf Serien gewonnen", "gp_siege", 5),

    ("ghost_1",  "Können", "Schneller als gestern", "eigenen Ghost geschlagen",
     lambda s: len(s.get("ghosts_geschlagen", [])), 1),
    ("ghost_3",  "Können", "Gespensterjäger", "Ghost auf drei Strecken geschlagen",
     lambda s: len(s.get("ghosts_geschlagen", [])), 3),
    ("start_ziel", "Können", "Start-Ziel-Sieg", "von Startplatz 1 gestartet und gewonnen",
     "start_ziel_siege", 1),
    ("aufholjagd", "Können", "Aufholjagd", "vom letzten Startplatz aufs Podest",
     "aufholjagden", 1),
    ("beste_runde", "Können", "Schnellste Runde", "beste Runde des Rennens gefahren",
     "schnellste_runden", 1),

    ("alle_strecken", "Vollständigkeit", "Streckenkunde",
     "jede mitgelieferte Strecke einmal gefahren",
     lambda s: len(s.get("strecken_gefahren", [])), 0),      # Ziel: siehe _ziel()
    ("alle_fahrzeuge", "Vollständigkeit", "Fuhrpark",
     "jedes Fahrzeug einmal gefahren",
     lambda s: len(s.get("fahrzeuge_gefahren", [])), 0),
    ("alle_klassen", "Vollständigkeit", "Alleskönner",
     "mit jeder Fahrzeugklasse einmal gewonnen",
     lambda s: len(s.get("klassen_gewonnen", [])), 0),

    ("baumeister",  "Erkunden", "Baumeister",   "eigene Strecke erstellt",
     "strecken_erstellt", 1),
    ("veroeffentlicht", "Erkunden", "Veröffentlicht", "eigene Strecke veröffentlicht",
     "strecken_veroeffentlicht", 1),
    ("hausstrecke", "Erkunden", "Hausstrecke",  "auf eigener Strecke gefahren",
     "eigene_strecke_gefahren", 1),
    ("heimvorteil", "Erkunden", "Heimvorteil",  "auf eigener Strecke gewonnen",
     "eigene_strecke_gewonnen", 1),

    ("online_1",     "Online", "Erstkontakt",      "erstes Online-Rennen gefahren",
     "online_rennen", 1),
    ("online_sieg",  "Online", "Online-Sieg",      "ein Online-Rennen gewonnen",
     "online_siege", 1),
    ("online_sieg_10", "Online", "Stammgast online", "zehn Online-Rennen gewonnen",
     "online_siege", 10),
    ("gastgeber",    "Online", "Gastgeber",        "eine Lobby gehostet",
     "lobbys_gehostet", 1),
    ("teiler",       "Online", "Streckenteiler",   "eigene Strecke in einer Lobby angeboten",
     "strecken_geteilt", 1),
    ("empfehlung",   "Online", "Auf Empfehlung",   "Strecke eines anderen gefahren",
     "fremde_strecken_gefahren", 1),
]


def _ziel(schluessel: str, vorgabe: int) -> int:
    """Ziel eines Erfolgs. Die Vollständigkeits-Erfolge fragen den Bestand ab,
    statt eine Zahl festzuschreiben — kommt eine Strecke dazu, wandert das Ziel
    mit, und niemand muss daran denken."""
    if schluessel == "alle_strecken":
        return max(1, len(_mitgelieferte_strecken()))
    if schluessel == "alle_fahrzeuge":
        from src.entities.vehicle_factory import VehicleFactory
        if not VehicleFactory.get_all_keys():
            VehicleFactory.load_all_configs("data/vehicles")
        return max(1, len(VehicleFactory.get_all_keys()))
    if schluessel == "alle_klassen":
        from src.core import race_setup
        return max(1, len([k for k in race_setup.CLASSES if k != "Alle"]))
    return vorgabe


def _mitgelieferte_strecken() -> list[str]:
    import glob
    import os
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join("data", "tracks", "*.json")))


def stand(schluessel: str, block: dict | None = None) -> tuple[int, int]:
    """(erreicht, Ziel) eines Erfolgs — die Zahl für „7 / 20"."""
    block = werte() if block is None else block
    for key, _gruppe, _name, _text, quelle, ziel in ERFOLGE:
        if key != schluessel:
            continue
        wert = quelle(block) if callable(quelle) else int(block.get(quelle, 0))
        return int(wert), _ziel(key, ziel)
    return (0, 1)


def erreicht(block: dict | None = None) -> set[str]:
    """Alle offenen Erfolge. Reine Funktion der Statistik."""
    block = werte() if block is None else block
    offen = set()
    for key, _g, _n, _t, _q, _z in ERFOLGE:
        wert, ziel = stand(key, block)
        if wert >= ziel:
            offen.add(key)
    return offen


def alles_frei() -> bool:
    """Aus dem Quelltext gestartet ist alles frei (E1).

    ``IS_RELEASE`` ist falsch, solange das Spiel nicht als gepacktes Bündel
    läuft — beim Entwickeln will niemand erst zwanzig Rennen fahren, um einen
    Lack anzusehen. Im ausgelieferten Build greift das nie.
    """
    from src.core.version import IS_RELEASE
    return not IS_RELEASE
