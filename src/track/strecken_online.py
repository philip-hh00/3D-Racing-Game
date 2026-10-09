"""Strecken online tauschen — die lokale Seite (Plan 1.1.0 §5).

Was hier steht, braucht weder Netz noch Fenster:

* welche eigenen Strecken sich hochladen lassen,
* ein heruntergeladener Entwurf wird geprueft und als Spielstrecke abgelegt,
* der Umriss fuer die Vorschau.

**Was ueber das Netz geht.** Nicht die fertige Spielstrecke (Mittellinie, Waende
und Wegpunkte, 100 bis 200 KB), sondern der Entwurf des Editors
(``editor_tiles``: die Liste der Bauteile, wenige KB). Der Empfaenger baut die
Spielstrecke selbst daraus und prueft sie dabei mit denselben Regeln wie der
Editor beim Veroeffentlichen. Ein veraenderter Client kann dem Spiel damit keine
Zahlen unterschieben, die es in die Physik fuettert.

Eine geladene Strecke traegt den Eintrag ``online`` (Kennung, Autor, Server).
Daran erkennt das Spiel zwei Dinge: sie wird nicht erneut hochgeladen (sie
gehoert dem Spieler nicht), und ein zweiter Abruf derselben Strecke legt keine
Kopie an.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

from src.core import paths
from src.core.i18n import tr


class EntwurfFehler(Exception):
    """Ein heruntergeladener Entwurf ist nicht brauchbar; Text fuer den Spieler."""


# -- Vorschau ------------------------------------------------------------------

def umriss_aus_punkten(punkte: list[tuple[float, float]], hoechstens: int = 48) -> list[list[int]]:
    """Punkte auf 0..255 bringen und ausduennen — wie der Server es fuer die
    Liste tut (``server.py:_umriss``). Fuer eigene Strecken, die nicht vom
    Server kommen. Das Seitenverhaeltnis bleibt erhalten."""
    if not punkte:
        return []
    schritt = max(1, math.ceil(len(punkte) / hoechstens))
    xs = [p[0] for p in punkte]
    ys = [p[1] for p in punkte]
    x0, y0 = min(xs), min(ys)
    mass = max(max(xs) - x0, max(ys) - y0) or 1.0
    return [[int(round((x - x0) / mass * 255)), int(round((y - y0) / mass * 255))]
            for x, y in punkte[::schritt]]


def umriss_in_rechteck(umriss, rect, rand: int = 8) -> list[tuple[int, int]]:
    """Die Umrisspunkte (0..255, y nach oben) in Bildschirmpunkte innerhalb von *rect*.

    Zentriert, Seitenverhaeltnis erhalten, y gespiegelt (die Welt zaehlt nach
    oben, der Bildschirm nach unten). Unbrauchbare Eintraege werden
    uebersprungen — die Liste kommt von einem fremden Rechner.
    """
    if not isinstance(umriss, (list, tuple)):
        return []
    gut = []
    for p in umriss[:200]:                 # mehr schickt kein Relay; der Rest waere Muell
        try:
            x, y = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            continue
        if math.isfinite(x) and math.isfinite(y):
            gut.append((max(0.0, min(255.0, x)), max(0.0, min(255.0, y))))
    if not gut:
        return []
    xs = [p[0] for p in gut]
    ys = [p[1] for p in gut]
    breite = max(xs) - min(xs) or 1.0
    hoehe = max(ys) - min(ys) or 1.0
    innen_b = max(1, rect.width - 2 * rand)
    innen_h = max(1, rect.height - 2 * rand)
    f = min(innen_b / breite, innen_h / hoehe)
    ox = rect.centerx - (min(xs) + max(xs)) / 2 * f
    oy = rect.centery + (min(ys) + max(ys)) / 2 * f
    return [(int(round(ox + x * f)), int(round(oy - y * f))) for x, y in gut]


# -- Eigene Strecken -----------------------------------------------------------

@dataclass
class EigeneStrecke:
    """Eine veroeffentlichte eigene Strecke, die sich hochladen laesst."""
    name: str
    pfad: str
    entwurf: dict
    umriss: list
    schwierigkeit: str = "Mittel"
    thema: str = "Plains"
    laenge_px: int = 0


def _laenge(punkte) -> float:
    n = len(punkte)
    return sum(math.dist(punkte[i], punkte[(i + 1) % n]) for i in range(n)) if n > 1 else 0.0


def eigene_strecken() -> list[EigeneStrecke]:
    """Alle Strecken in ``data/tracks/custom``, die der Spieler selbst gebaut hat.

    Ausgenommen: Strecken ohne Entwurf (``editor_tiles`` fehlt — aus einer
    Datei von Hand, nicht aus dem Editor) und alle, die selbst aus dem Netz
    stammen (Eintrag ``online``): fremde Strecken werden nicht unter dem Namen
    des Spielers noch einmal angeboten.
    """
    aus: list[EigeneStrecke] = []
    for pfad in paths.track_files("custom"):
        try:
            with open(pfad, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict) or d.get("online") or not isinstance(d.get("editor_tiles"), dict):
            continue
        mitte = [(float(p["x"]), float(p["y"])) for p in d.get("centerline", [])
                 if isinstance(p, dict) and "x" in p and "y" in p]
        aus.append(EigeneStrecke(
            name=str(d.get("name") or Path(pfad).stem),
            pfad=str(pfad), entwurf=d["editor_tiles"],
            umriss=umriss_aus_punkten(mitte),
            schwierigkeit=str(d.get("difficulty", "Mittel")),
            thema=str(d.get("background_texture", "Plains")),
            laenge_px=int(_laenge(mitte)),
        ))
    return aus


def hochladbar(s: EigeneStrecke) -> tuple[bool, str]:
    """Ob *s* hochgeladen werden darf, sonst warum nicht (fuer den Spieler).

    Dieselben Pruefungen wie beim Veroeffentlichen: wer die Strecke nicht
    veroeffentlichen koennte, soll sie auch nicht anbieten.
    """
    from src.core import profile
    from src.track.tile_track import TileTrackDraft
    ok, grund = profile.validate_track_name(s.name)
    if not ok:
        return False, tr("Name nicht erlaubt: {grund}").format(grund=grund)
    try:
        draft = TileTrackDraft.from_draft_dict(s.entwurf)
        fehler = draft.validate_game()
    except Exception:
        return False, tr("Die Strecke lässt sich nicht lesen.")
    if fehler:
        return False, tr("Nicht bereit: {msg}").format(msg=fehler[0].message)
    return True, ""


# -- Anzeige und Sperrliste ----------------------------------------------------

def anzeigbar(eintrag: dict) -> bool:
    """Ob ein Listeneintrag gezeigt werden darf.

    Der Server prueft nur die Zeichen, nicht die Woerter — die Sperrliste liegt
    im Spiel (``name_blacklist.json``). Ein Eintrag, dessen Name oder Autor darauf
    trifft, wird ausgeblendet, als gaebe es ihn nicht. Gleichzeitig verhindert
    das, dass ein veraenderter Client Fremden Beleidigungen in die Liste setzt.
    """
    from src.core import profile
    return not (profile._ist_gesperrt(str(eintrag.get("name", "")))
                or profile._ist_gesperrt(str(eintrag.get("author", ""))))


def eintrag_ok(e) -> bool:
    """Grundform eines Listeneintrags aus dem Netz (alles Fremde wird geprueft)."""
    return (isinstance(e, dict) and isinstance(e.get("id"), str) and len(e["id"]) == 8
            and isinstance(e.get("name"), str) and isinstance(e.get("author"), str))


# -- Heruntergeladene Strecken -------------------------------------------------

def _eigene_namen() -> set[str]:
    namen: set[str] = set()
    for pfad in paths.track_files("custom"):
        try:
            with open(pfad, encoding="utf-8") as f:
                n = json.load(f).get("name")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(n, str):
            namen.add(n)
    return namen


def bereits_geladen(tid: str) -> str | None:
    """Pfad der Datei, die zu Online-Kennung *tid* gehoert, oder None."""
    for pfad in paths.track_files("custom"):
        try:
            with open(pfad, encoding="utf-8") as f:
                o = json.load(f).get("online")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(o, dict) and o.get("id") == tid:
            return str(pfad)
    return None


def geladene_kennungen() -> set[str]:
    """Kennungen aller schon geladenen Online-Strecken (fuer die Markierung in der Liste)."""
    aus: set[str] = set()
    for pfad in paths.track_files("custom"):
        try:
            with open(pfad, encoding="utf-8") as f:
                o = json.load(f).get("online")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(o, dict) and isinstance(o.get("id"), str):
            aus.add(o["id"])
    return aus


def speichern(daten: dict, server_id: str = "") -> tuple[str, bool]:
    """Eine ``TRACK_DATA``-Antwort pruefen und als Spielstrecke ablegen.

    Gibt ``(Pfad, neu)`` zurueck; ``neu`` ist False, wenn diese Strecke schon da
    war (dann wird nichts geschrieben). Wirft :class:`EntwurfFehler`.

    Der Name wird eindeutig gemacht: ``delete_track`` sucht Strecken nach ihrem
    *Namen* im Inhalt, und eine geladene Strecke mit dem Namen einer eigenen
    wuerde beim Loeschen der einen die andere gleich mit entfernen.
    """
    from src.core import profile
    from src.track.tile_track import TileTrackDraft

    tid = str(daten.get("id", ""))
    schon = bereits_geladen(tid) if tid else None
    if schon:
        return schon, False
    name = str(daten.get("name", ""))
    autor = str(daten.get("author", ""))
    ok, grund = profile.validate_track_name(name)
    if not ok or profile._ist_gesperrt(autor):
        raise EntwurfFehler(tr("Diese Strecke wurde wegen ihres Namens nicht geladen."))
    try:
        draft = TileTrackDraft.from_draft_dict(daten["track"])
        fehler = draft.validate_game()
    except Exception:
        raise EntwurfFehler(tr("Die Strecke ist beschädigt und wurde nicht geladen."))
    if fehler:
        raise EntwurfFehler(tr("Die Strecke ist nicht fahrbar: {msg}").format(msg=fehler[0].message))

    vergeben = _eigene_namen()
    titel, n = name, 2
    while titel in vergeben:
        titel = f"{name[:34]} ({n})"
        n += 1
    draft.name = titel
    spiel = draft.to_game_json()
    spiel["online"] = {"id": tid, "author": autor, "server": server_id}
    pfad = paths.freier_streckenpfad("data/tracks/custom", f"{titel}.json")
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    with open(pfad, "w", encoding="utf-8") as f:
        json.dump(spiel, f, indent=2, ensure_ascii=False)
    return pfad, True
