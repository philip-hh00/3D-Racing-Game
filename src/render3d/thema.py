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
    #: Gelände (Strang W): steilster Hang, an dem das Objekt noch steht, in
    #: Grad; ``None``: ``gelaende.baum_hang_max_grad`` des Themas.
    hang_max_grad: float | None = None
    #: Braucht ebenen Boden (Häuser): das Gelände wird darunter geebnet.
    flach: bool = False


@dataclass
class Randart:
    """Etwas, das der Strecke folgt: Banden, Reifenstapel, Laternen."""

    modell: str
    #: ``"reihe"``: in festem Abstand entlang der Strecke. ``"kurven"``: nur
    #: an der Außenseite enger Kurven. ``"start"``: einmal an der Startlinie.
    #: ``"kette"``: lückenlos aneinander, je ``je_m`` ein Glied (Fangzäune).
    #: ``"scheitel"``: innen am Scheitel enger Kurven (Hütchen, Posten).
    art: str = "reihe"
    abstand_m: float = 3.0
    je_m: float = 30.0
    seite: str = "aussen"
    skala: float = 1.0
    radius_m: float = 1.0
    #: Drehung um die Hochachse zusätzlich zur Streckenrichtung, in Grad.
    drehung_grad: float = 0.0
    # --- Streckenobjekte (Strang S) ---
    #: Ab welcher Stufe ``grafik.strecken_details`` es steht: 0 immer,
    #: 1 ab Mittel, 2 nur Hoch/Ultra.
    detail: int = 0
    #: > 0: nur so weit vor und hinter der Startlinie (Meter entlang der Strecke).
    bereich_m: float = 0.0
    #: Bei ``"start"``: so weit entlang der Strecke verschoben (Meter,
    #: negativ: vor der Linie).
    versatz_m: float = 0.0


@dataclass
class Auslaufart:
    """Auslaufzonen außen an Kurven (Strang S): Kies, Sand oder Asphalt."""

    #: Breite am breitesten Punkt, Meter; 0 schaltet sie ab.
    breite_m: float = 0.0
    textur: str = "kies"
    kachel_m: float = 3.0
    ton: tuple = (1.0, 1.0, 1.0)
    rauheit: float = 0.95


@dataclass
class Kulisse:
    """Ferne Objekte im Ring um die Strecke: Berge, Skyline, Dünen."""

    modell: str
    anzahl: int = 12
    radius_m: tuple[float, float] = (600.0, 900.0)
    skala: tuple[float, float] = (0.8, 1.3)


# --- Gelände und Gras (Strang W) -------------------------------------------

@dataclass
class Bodenschicht:
    """Eine Bodentextur im Gelände: Gras/Sand unten, Fels am Hang."""

    textur: str = ""
    kachel_m: float = 10.0
    #: Färbt die Textur ein (Gras grüner, Sand wärmer), wie ``boden.ton``.
    ton: tuple = (1.0, 1.0, 1.0)


@dataclass
class Gelaendeart:
    """Wie der Boden um eine Strecke aussieht: Charakter, Höhen, Texturen.

    Die Höhen wachsen in drei Zonen: ``nah`` gleich hinter dem flachen
    Korridor, ``fern`` ab ``fern_ab_m`` Metern vom Rand des Streckenrechtecks,
    ``horizont`` als Bergkette ab ``horizont_ab_m``. Jede Zone hat eine Art
    (``flach``, ``wellen``, ``huegel``, ``duenen``, ``tafelberge``,
    ``berge``), eine Höhe und eine Wellenlänge.
    """

    nah_art: str = "wellen"
    nah_hoehe_m: float = 4.0
    nah_wellenlaenge_m: float = 200.0
    fern_art: str = "huegel"
    fern_hoehe_m: float = 0.0
    fern_wellenlaenge_m: float = 400.0
    fern_ab_m: float = 150.0
    horizont_art: str = "huegel"
    horizont_hoehe_m: float = 0.0
    horizont_wellenlaenge_m: float = 900.0
    horizont_ab_m: float = 700.0
    #: Flach ab der Fahrbahnkante (Randstreifen, Begrenzung, Banden). Die
    #: Randobjekte des Themas verbreitern ihn bei Bedarf.
    korridor_m: float = 14.0
    #: Über diese Strecke steigt das Gelände weich an.
    anstieg_m: float = 45.0
    unten: Bodenschicht = field(default_factory=Bodenschicht)
    hang: Bodenschicht = field(default_factory=lambda: Bodenschicht("fels_gras", 16.0))
    fels: Bodenschicht = field(default_factory=lambda: Bodenschicht("felswand", 20.0))
    #: Ab dieser Neigung (1 − Normale.z) beginnt die Hangtextur, ab
    #: ``fels_ab`` der nackte Fels.
    hang_ab: float = 0.10
    fels_ab: float = 0.32
    #: Ab dieser Höhe liegt die Hangtextur auch flach (Tafelberg-Kappen).
    hang_hoehe_m: float = 1e6
    #: Schnee ab dieser Höhe; ``None``: nie.
    schnee_ab_m: float | None = None
    #: Waldbedeckung als Farbe in der Ferne (sRGB), ab ``wald_ab_m`` vom
    #: Streckenrechteck; ``None``: kein Wald.
    wald_farbe: tuple | None = None
    wald_ab_m: float = 300.0
    #: Ferner Wald aus einfachen Baumkegeln ab ``wald_ab_m`` bis
    #: ``fernwald_bis_m``, Kegel je Hektar dort, wo Wald ist; 0: keiner.
    fernwald_je_ha: float = 0.0
    fernwald_bis_m: float = 1500.0
    #: Über dieser Höhe wächst kein Baum mehr; ``None``: überall.
    baumgrenze_m: float | None = None
    #: Bäume stehen nur bis zu dieser Neigung, in Grad.
    baum_hang_max_grad: float = 28.0


@dataclass
class Grasart:
    """Grasbüschel nah an der Strecke."""

    an: bool = False
    #: Farbe am Fuß und an der Spitze der Halme, sRGB.
    farbe: tuple = (0.24, 0.36, 0.12)
    spitze: tuple = (0.52, 0.60, 0.26)
    hoehe_m: tuple = (0.25, 0.55)
    #: Büschel je Quadratmeter direkt am Rand; nach außen hin weniger.
    dichte_je_m2: float = 0.9
    #: Bis zu diesem Abstand von der Fahrbahnkante.
    bis_m: float = 28.0
    #: Halme je Büschel.
    halme: int = 12
    #: Weit gespreizt und niedrig (trockene Steppe) statt aufrecht.
    trocken: bool = False


def _schicht(daten: dict | None, vorgabe: Bodenschicht) -> Bodenschicht:
    if not daten:
        return vorgabe
    return Bodenschicht(textur=str(daten.get("textur", vorgabe.textur)),
                        kachel_m=float(daten.get("kachel_m", vorgabe.kachel_m)),
                        ton=_tupel(daten.get("ton"), 3) or vorgabe.ton)


def gelaende_aus_daten(daten: dict | None, boden: Bodenschicht) -> Gelaendeart:
    """Der Block ``"gelaende"`` eines Themas; ``boden`` ist die untere Schicht."""
    daten = dict(daten or {})
    g = Gelaendeart(unten=boden)
    for zone in ("nah", "fern", "horizont"):
        z = daten.get(zone) or {}
        setattr(g, f"{zone}_art", str(z.get("art", getattr(g, f"{zone}_art"))))
        setattr(g, f"{zone}_hoehe_m", float(z.get("hoehe_m", getattr(g, f"{zone}_hoehe_m"))))
        setattr(g, f"{zone}_wellenlaenge_m",
                float(z.get("wellenlaenge_m", getattr(g, f"{zone}_wellenlaenge_m"))))
        if zone != "nah":
            setattr(g, f"{zone}_ab_m", float(z.get("ab_m", getattr(g, f"{zone}_ab_m"))))
    for name in ("korridor_m", "anstieg_m", "hang_ab", "fels_ab", "hang_hoehe_m",
                 "wald_ab_m", "baum_hang_max_grad", "fernwald_je_ha", "fernwald_bis_m"):
        if name in daten:
            setattr(g, name, float(daten[name]))
    if daten.get("schnee_ab_m") is not None:
        g.schnee_ab_m = float(daten["schnee_ab_m"])
    if daten.get("baumgrenze_m") is not None:
        g.baumgrenze_m = float(daten["baumgrenze_m"])
    if daten.get("wald_farbe") is not None:
        g.wald_farbe = _tupel(daten["wald_farbe"], 3)
    schichten = daten.get("schichten") or {}
    g.unten = _schicht(schichten.get("unten"), g.unten)
    g.hang = _schicht(schichten.get("hang"), g.hang)
    g.fels = _schicht(schichten.get("fels"), g.fels)
    return g


def gras_aus_daten(daten: dict | None) -> Grasart:
    daten = dict(daten or {})
    g = Grasart(an=bool(daten.get("an", False)))
    g.farbe = _tupel(daten.get("farbe"), 3) or g.farbe
    g.spitze = _tupel(daten.get("spitze"), 3) or g.spitze
    g.hoehe_m = _tupel(daten.get("hoehe_m"), 2) or g.hoehe_m
    g.dichte_je_m2 = float(daten.get("dichte_je_m2", g.dichte_je_m2))
    g.bis_m = float(daten.get("bis_m", g.bis_m))
    g.halme = int(daten.get("halme", g.halme))
    g.trocken = bool(daten.get("trocken", g.trocken))
    return g


# --- Ende Gelände und Gras --------------------------------------------------


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
    # --- Streckendetails (Strang S) ---
    #: Färbt den Asphalt ein (heller, wärmer).
    fahrbahn_ton: tuple = (1.0, 1.0, 1.0)
    #: Weiße Randlinie so weit innen von der Fahrbahnkante; 0: keine.
    randlinie_m: float = 1.1
    linienbreite_m: float = 0.2
    #: Gestrichelte Mittellinie wie auf einer Straße (Stadtkurs).
    mittellinie: bool = False
    #: 0 weiße, 1 gelbe Linien.
    linien_gelb: float = 0.0
    auslauf: Auslaufart = field(default_factory=Auslaufart)
    deko: list[Dekoart] = field(default_factory=list)
    rand: list[Randart] = field(default_factory=list)
    kulisse: list[Kulisse] = field(default_factory=list)
    #: Gelände und Gras (Strang W).
    gelaende: Gelaendeart = field(default_factory=Gelaendeart)
    gras: Grasart = field(default_factory=Grasart)

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
    t.fahrbahn_ton = _tupel(bahn.get("ton"), 3) or t.fahrbahn_ton
    t.randlinie_m = float(bahn.get("randlinie_m", t.randlinie_m))
    t.linienbreite_m = float(bahn.get("linienbreite_m", t.linienbreite_m))
    t.mittellinie = bool(bahn.get("mittellinie", t.mittellinie))
    t.linien_gelb = float(bahn.get("linien_gelb", t.linien_gelb))
    aus = daten.get("auslauf") or {}
    t.auslauf = Auslaufart(
        breite_m=float(aus.get("breite_m", 0.0)), textur=str(aus.get("textur", "kies")),
        kachel_m=float(aus.get("kachel_m", 3.0)), ton=_tupel(aus.get("ton"), 3) or (1.0, 1.0, 1.0),
        rauheit=float(aus.get("rauheit", 0.95)))
    if "randstein_farben" in daten:
        t.randstein_farben = tuple(_tupel(f, 3) for f in daten["randstein_farben"])
    t.begrenzung = str(daten.get("begrenzung", t.begrenzung))
    for d in daten.get("deko", []):
        t.deko.append(Dekoart(
            modell=d["modell"], dichte_je_ha=float(d.get("dichte_je_ha", 1.0)),
            abstand_m=_tupel(d.get("abstand_m", (12, 150)), 2),
            skala=_tupel(d.get("skala", (0.85, 1.2)), 2),
            radius_m=float(d.get("radius_m", 1.5)), drehen=bool(d.get("drehen", True)),
            seite=str(d.get("seite", "beide")),
            hang_max_grad=float(d["hang_max_grad"]) if d.get("hang_max_grad") is not None else None,
            flach=bool(d.get("flach", False))))
    for r in daten.get("rand", []):
        t.rand.append(Randart(
            modell=r["modell"], art=str(r.get("art", "reihe")),
            abstand_m=float(r.get("abstand_m", 3.0)), je_m=float(r.get("je_m", 30.0)),
            seite=str(r.get("seite", "aussen")), skala=float(r.get("skala", 1.0)),
            radius_m=float(r.get("radius_m", 1.0)),
            drehung_grad=float(r.get("drehung_grad", 0.0)),
            detail=int(r.get("detail", 0)), bereich_m=float(r.get("bereich_m", 0.0)),
            versatz_m=float(r.get("versatz_m", 0.0))))
    for k in daten.get("kulisse", []):
        t.kulisse.append(Kulisse(
            modell=k["modell"], anzahl=int(k.get("anzahl", 12)),
            radius_m=_tupel(k.get("radius_m", (600, 900)), 2),
            skala=_tupel(k.get("skala", (0.8, 1.3)), 2)))
    # Gelände und Gras (Strang W): die untere Bodenschicht ist der alte Boden.
    t.gelaende = gelaende_aus_daten(
        daten.get("gelaende"), Bodenschicht(t.boden_textur, t.boden_kachel_m, t.boden_ton))
    t.gras = gras_aus_daten(daten.get("gras"))
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
