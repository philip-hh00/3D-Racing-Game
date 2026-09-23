"""Streckenthemen: was um eine Strecke herum steht und wie der Himmel aussieht.

Je Thema liegt eine Beschreibung in ``data/themen/<name>.json`` — von Hand
änderbar, ohne Code anzufassen. Welches Thema eine Strecke hat, steht in ihrer
Streckendatei als ``background_texture`` (``"Desert"``, ``"City"`` …), dem
Feld, das im 2D-Spiel die Hintergrundtextur wählte.

Dieses Modul liest nur. Es kennt weder OpenGL noch pygame.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

#: Thema, wenn eine Strecke keins nennt oder das genannte fehlt.
ERSATZTHEMA = "Plains"


@dataclass
class Dekoart:
    """Eine Sorte Objekt, die verstreut wird — Bäume, Felsen, Häuser."""

    modell: str
    #: Exemplare je Hektar im erlaubten Band.
    dichte_je_ha: float = 1.0
    #: Abstand zur Fahrbahnkante, von–bis, in Metern.
    abstand_m: tuple[float, float] = (12.0, 150.0)
    skala: tuple[float, float] = (0.85, 1.2)
    #: Platzbedarf in Metern (bei Skala 1). Zwei Objekte rücken sich nicht
    #: näher als die Summe ihrer Radien.
    radius_m: float = 1.5
    #: Zufällig um die Hochachse drehen; sonst zur Strecke ausrichten.
    drehen: bool = True
    #: Nur außerhalb (``"aussen"``) oder im Innenfeld (``"innen"``) oder beides.
    seite: str = "beide"


@dataclass
class Randart:
    """Etwas, das der Strecke folgt: Banden, Reifenstapel, Laternen."""

    modell: str
    #: ``"reihe"``: in festem Abstand entlang der Strecke. ``"kurven"``: nur
    #: an der Außenseite enger Kurven. ``"start"``: einmal an der Startlinie.
    art: str = "reihe"
    abstand_m: float = 3.0
    je_m: float = 30.0
    seite: str = "aussen"
    skala: float = 1.0
    radius_m: float = 1.0
    #: Drehung um die Hochachse zusätzlich zur Streckenrichtung, in Grad.
    drehung_grad: float = 0.0


@dataclass
class Kulisse:
    """Ferne Objekte im Ring um die Strecke: Berge, Skyline, Dünen."""

    modell: str
    anzahl: int = 12
    radius_m: tuple[float, float] = (600.0, 900.0)
    skala: tuple[float, float] = (0.8, 1.3)


@dataclass
class Thema:
    name: str
    himmel: str = ""
    himmel_zenit: tuple = (0.28, 0.44, 0.78)
    himmel_horizont: tuple = (0.72, 0.80, 0.92)
    boden_farbe: tuple = (0.30, 0.34, 0.22)
    sonne_farbe: tuple = (3.0, 2.85, 2.6)
    himmel_helligkeit: float = 1.0
    belichtung: float = 1.0
    nebel_farbe: tuple = (0.72, 0.78, 0.86)
    nebel_dichte: float = 0.0018
    boden_textur: str = "gras"
    boden_kachel_m: float = 8.0
    boden_ton: tuple = (1.0, 1.0, 1.0)
    fahrbahn_textur: str = "asphalt"
    fahrbahn_kachel_m: float = 10.0
    randstein_farben: tuple = ((0.78, 0.12, 0.1), (0.92, 0.92, 0.9))
    begrenzung: str = "leitplanke"
    deko: list[Dekoart] = field(default_factory=list)
    rand: list[Randart] = field(default_factory=list)
    kulisse: list[Kulisse] = field(default_factory=list)

    def modelle(self) -> list[str]:
        """Alle Modellnamen, die dieses Thema braucht."""
        namen = [d.modell for d in self.deko] + [r.modell for r in self.rand] \
            + [k.modell for k in self.kulisse]
        # "a|b|c" ist eine Auswahl — gebraucht werden alle drei.
        return list(dict.fromkeys(n for gruppe in namen for n in gruppe.split("|")))


def _tupel(wert, laenge: int | None = None):
    if wert is None:
        return None
    t = tuple(float(w) for w in wert)
    if laenge is not None and len(t) != laenge:
        raise ValueError(f"{wert!r} hat nicht {laenge} Werte")
    return t


def aus_daten(daten: dict) -> Thema:
    h = daten.get("himmel_farben", {})
    nebel = daten.get("nebel", {})
    boden = daten.get("boden", {})
    bahn = daten.get("fahrbahn", {})
    t = Thema(name=str(daten.get("name", ERSATZTHEMA)))
    t.himmel = str(daten.get("himmel", ""))
    t.himmel_zenit = _tupel(h.get("zenit"), 3) or t.himmel_zenit
    t.himmel_horizont = _tupel(h.get("horizont"), 3) or t.himmel_horizont
    t.boden_farbe = _tupel(boden.get("farbe"), 3) or t.boden_farbe
    t.sonne_farbe = _tupel(daten.get("sonne_farbe"), 3) or t.sonne_farbe
    t.himmel_helligkeit = float(daten.get("himmel_helligkeit", t.himmel_helligkeit))
    t.belichtung = float(daten.get("belichtung", t.belichtung))
    t.nebel_farbe = _tupel(nebel.get("farbe"), 3) or t.nebel_farbe
    t.nebel_dichte = float(nebel.get("dichte", t.nebel_dichte))
    t.boden_textur = str(boden.get("textur", t.boden_textur))
    t.boden_kachel_m = float(boden.get("kachel_m", t.boden_kachel_m))
    t.boden_ton = _tupel(boden.get("ton"), 3) or t.boden_ton
    t.fahrbahn_textur = str(bahn.get("textur", t.fahrbahn_textur))
    t.fahrbahn_kachel_m = float(bahn.get("kachel_m", t.fahrbahn_kachel_m))
    if "randstein_farben" in daten:
        t.randstein_farben = tuple(_tupel(f, 3) for f in daten["randstein_farben"])
    t.begrenzung = str(daten.get("begrenzung", t.begrenzung))
    for d in daten.get("deko", []):
        t.deko.append(Dekoart(
            modell=d["modell"], dichte_je_ha=float(d.get("dichte_je_ha", 1.0)),
            abstand_m=_tupel(d.get("abstand_m", (12, 150)), 2),
            skala=_tupel(d.get("skala", (0.85, 1.2)), 2),
            radius_m=float(d.get("radius_m", 1.5)), drehen=bool(d.get("drehen", True)),
            seite=str(d.get("seite", "beide"))))
    for r in daten.get("rand", []):
        t.rand.append(Randart(
            modell=r["modell"], art=str(r.get("art", "reihe")),
            abstand_m=float(r.get("abstand_m", 3.0)), je_m=float(r.get("je_m", 30.0)),
            seite=str(r.get("seite", "aussen")), skala=float(r.get("skala", 1.0)),
            radius_m=float(r.get("radius_m", 1.0)),
            drehung_grad=float(r.get("drehung_grad", 0.0))))
    for k in daten.get("kulisse", []):
        t.kulisse.append(Kulisse(
            modell=k["modell"], anzahl=int(k.get("anzahl", 12)),
            radius_m=_tupel(k.get("radius_m", (600, 900)), 2),
            skala=_tupel(k.get("skala", (0.8, 1.3)), 2)))
    return t


def laden(ordner: str | Path, name: str | None) -> Thema:
    """Das Thema ``name`` aus ``ordner`` — notfalls das Ersatzthema.

    Groß- und Kleinschreibung zählen nicht: die Streckendateien schreiben
    ``"Desert"``, die Dateien heißen ``desert.json``.
    """
    ordner = Path(ordner)
    for kandidat in (name, ERSATZTHEMA):
        if not kandidat:
            continue
        pfad = ordner / f"{str(kandidat).lower()}.json"
        if pfad.is_file():
            with open(pfad, encoding="utf-8") as fh:
                return aus_daten(json.load(fh))
    return Thema(name=ERSATZTHEMA)


def thema_der_strecke(strecke: dict) -> str:
    return str(strecke.get("theme") or strecke.get("background_texture") or ERSATZTHEMA)
