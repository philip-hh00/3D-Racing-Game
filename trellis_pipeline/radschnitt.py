"""Raeder aus dem verschmolzenen Mesh heraustrennen.

TRELLIS liefert Karosserie und Raeder als **ein** Netz. Vorderraeder lenken
nicht, Raeder drehen sich nicht. Der urspruengliche Plan war, Rad und Karosserie
getrennt zu generieren; dieses Modul geht den anderen Weg und zerlegt das
fertige Modell.

Der Grund ist das Aussehen: ein getrennt generiertes Rad hat weder das
Felgendesign noch die Reifenbreite des jeweiligen Fahrzeugs. Bei 15
Konfigurationen mit Raddurchmessern von 0,64 bis 0,73 m faellt das auf. Ein
herausgeschnittenes Rad ist dagegen genau das Rad dieses Autos.

**Wo geschnitten wird, ist gerechnet und nicht gesucht.** Die vier
Nabenpositionen ergeben sich aus Radstand, Breite und Raddurchmesser
(:func:`vehicle_specs.radpositionen`). Im Mesh nach Raedern zu suchen waere
unzuverlaessig - Radlauf und Reifen sind eine durchgehende Flaeche ohne
Trennkante.

Was der Schnitt nicht leisten kann:

* Er ist nicht chirurgisch. Ein Stueck Radlauf wandert mit dem Rad mit.
* Die Innenseite des Rades hat TRELLIS nie gesehen und daher nicht modelliert.
  Die Schnittflaeche wird geschlossen, damit man beim Lenken nicht hineinsieht.
* In der Karosserie bleibt ein Loch, verdeckt vom Rad selbst.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import trimesh

from .vehicle_specs import Fahrzeugmasse, radpositionen

#: Namen der vier Raeder in der Reihenfolge von :func:`radpositionen`.
RAD_NAMEN = ("rad_vl", "rad_vr", "rad_hl", "rad_hr")

#: Wie weit ueber den gemessenen Reifenradius hinaus geschnitten wird.
#:
#: Frueher lag der Wert bei 1,12 auf den **Sollradius** aus der Tabelle. Beide
#: Entscheidungen waren falsch. Der Sollradius ist eine Vorgabe, kein Mass am
#: Modell; und 12 Prozent Zugabe sind bei 0,325 m fast 4 cm, in denen der
#: Radlauf sitzt. Herausgetrennt wurde damit ein Rad mitsamt einem Bogen
#: Karosserie darueber, der sich beim Rollen mitdrehte.
#:
#: Der Reifenradius wird stattdessen gemessen: das Rad steht auf der Strasse,
#: seine Nabe liegt also genau einen Radius ueber z = 0. Drei Prozent Zugabe
#: fangen die Unebenheit des erzeugten Netzes ab, ohne den Radlauf zu fassen.
RADIUS_ZUGABE = 1.03


#: Ab welchem Anteil der staerksten Klasse eine Querschnittsklasse noch zum
#: Reifen gezaehlt wird. Am rookie liegt der Reifen zwischen den Klassen mit
#: 2000 und 12691 Dreiecken, waehrend der Unterboden auf rund 200 kommt - der
#: Abstand zwischen beidem ist gross genug, dass der genaue Wert nicht
#: kitzlig ist.
BAND_SCHWELLE = 0.10

#: Klassenbreite der Quervermessung.
BAND_SCHRITT = 0.02

#: Schmalstes Band, das noch als Reifen durchgeht, als Anteil des
#: Raddurchmessers. Kein Reifen an einem 65-cm-Rad ist 6 cm breit. Faellt die
#: Messung darunter, hat sie sich an einer einzelnen Flaeche festgebissen
#: statt am Reifenkoerper - dann ist die Schaetzung ehrlicher.
BAND_MINDESTANTEIL = 0.15

#: Breitestes Band, das noch als Reifen durchgeht, ebenfalls als Anteil des
#: Raddurchmessers. Ein Pkw-Reifen misst je nach Format 25 bis 45 Prozent
#: seines Durchmessers in der Breite; darueber ist es kein Reifen mehr,
#: sondern Radkasten.
#:
#: Noetig geworden am dichteren Modell aus zwei Ansichten: dort steckt mehr
#: Geometrie im Radhaus, die Messung lief von der Lauflaeche nach innen weiter
#: und lieferte Baender von 44 bis 60 cm. Gekappt wird nach **innen** - die
#: Aussenkante des Reifens ist die verlaessliche Kante, innen geht er ohne
#: sichtbaren Absatz in den Radkasten ueber.
BAND_HOECHSTANTEIL = 0.45


@dataclass
class Rad:
    name: str
    mesh: trimesh.Trimesh
    #: Nabenmittelpunkt im Fahrzeugkoordinatensystem. Das Mesh selbst ist um
    #: seinen eigenen Ursprung zentriert, damit es sich drehen laesst.
    nabe: tuple[float, float, float]


@dataclass
class Zerlegung:
    karosserie: trimesh.Trimesh
    raeder: list[Rad] = field(default_factory=list)
    hinweise: list[str] = field(default_factory=list)

    def als_szene(self) -> trimesh.Scene:
        """Als GLB-Szene mit benannten Knoten.

        Engine-neutral: jeder Renderer, der GLB laedt, bekommt eine
        Karosserie und vier Raeder, die um ihre eigene Nabe drehbar sind.
        """
        szene = trimesh.Scene()
        szene.add_geometry(self.karosserie, node_name="karosserie",
                           geom_name="karosserie")
        for rad in self.raeder:
            szene.add_geometry(
                rad.mesh, node_name=rad.name, geom_name=rad.name,
                transform=trimesh.transformations.translation_matrix(rad.nabe))
        return szene

    def text(self) -> str:
        zeilen = [f"Karosserie      {len(self.karosserie.faces):,} Dreiecke".replace(",", ".")]
        for rad in self.raeder:
            x, y, z = rad.nabe
            zeilen.append(
                f"{rad.name:15} {len(rad.mesh.faces):,} Dreiecke".replace(",", ".")
                + f"   Nabe ({x:+.3f}, {y:+.3f}, {z:.3f})")
        for h in self.hinweise:
            zeilen.append(f"HINWEIS         {h}")
        return "\n".join(zeilen)


def querband(mitten: np.ndarray, nabe, reifenradius: float) -> tuple[float, float] | None:
    """Wie breit der Reifen wirklich ist, gemessen statt geschaetzt.

    Die Sollmasse kennen den Raddurchmesser, aber nicht die Reifenbreite - die
    steht in keiner Fahrzeug-JSON, weil sie in einem 2D-Spiel nie gebraucht
    wurde. Geschaetzt hat der erste Lauf am rookie 0,536 m herausgeschnitten,
    also ein gutes Stueck Kotfluegel mit.

    Gemessen wird innerhalb des reinen Reifenradius auf der Fahrzeugaussenseite:
    dort sitzt der Reifen als dichter Block von Dreiecken, waehrend Unterboden
    und Achse nur vereinzelt hineinragen. Ausgehend von der **staerksten**
    Klasse wird nach beiden Seiten erweitert, solange die Nachbarklassen ueber
    der Schwelle bleiben.

    Nicht der laengste Lauf ueber der Schwelle: bei duenn besetzten
    Histogrammen kann das ein langer flacher Ausleufer sein, der den Reifen gar
    nicht enthaelt. Der Reifen ist dort, wo die Masse ihr Maximum hat.

    ``None`` heisst: kein klarer Block gefunden, der Aufrufer soll schaetzen.
    """
    hx, hy, hz = nabe
    aussen = np.sign(hy)
    radial = np.hypot(mitten[:, 0] - hx, mitten[:, 2] - hz)
    ys = mitten[radial <= reifenradius, 1] * aussen
    ys = ys[ys > 0]
    if ys.size < 100:
        return None

    kanten = np.arange(ys.min(), ys.max() + BAND_SCHRITT, BAND_SCHRITT)
    if kanten.size < 3:
        return None
    zahl, _ = np.histogram(ys, bins=kanten)
    schwelle = max(zahl.max() * BAND_SCHWELLE, 1)
    spitze = int(zahl.argmax())

    links = spitze
    while links > 0 and zahl[links - 1] >= schwelle:
        links -= 1
    rechts = spitze
    while rechts < len(zahl) - 1 and zahl[rechts + 1] >= schwelle:
        rechts += 1

    von, bis = float(kanten[links]), float(kanten[rechts + 1])
    breite = bis - von
    if breite < 2 * reifenradius * BAND_MINDESTANTEIL:
        return None

    # Nach innen kappen. "bis" ist die Aussenkante (gemessen wird auf der
    # Aussenseite, dort ist y*aussen am groessten), und die ist die
    # verlaessliche: aussen endet der Reifen sichtbar, innen laeuft er ohne
    # Absatz in den Radkasten.
    hoechstens = 2 * reifenradius * BAND_HOECHSTANTEIL
    if breite > hoechstens:
        von = bis - hoechstens

    return (von * aussen, bis * aussen) if aussen > 0 else (bis * aussen, von * aussen)


def symmetrisch(baender: dict[str, tuple[float, float]]) -> dict[str, tuple[float, float]]:
    """Die vier gemessenen Baender auf ein symmetrisches Fahrzeug bringen.

    Ein Auto ist symmetrisch, seine vier Reifen sind gleich breit und die
    Spurweite je Achse ist links wie rechts dieselbe. Die Messung weiss das
    nicht und liefert je Rad einen eigenen Wert - am Modell aus zwei Ansichten
    lagen die Nabenmitten zwischen 0,56 und 0,74 m, also 18 cm auseinander.
    Sichtbar waere das als Rad, das beim Lenken um eine andere Achse schwenkt
    als sein Gegenueber.

    Gemittelt wird je Achse ueber den Betrag der Aussenkante, die Breite ueber
    alle vier.
    """
    if not baender:
        return {}
    breite = float(np.mean([abs(b[1] - b[0]) for b in baender.values()]))

    ergebnis: dict[str, tuple[float, float]] = {}
    for achse in ("v", "h"):
        namen = [n for n in baender if n.startswith(f"rad_{achse}")]
        if not namen:
            continue
        aussen = float(np.mean([max(abs(baender[n][0]), abs(baender[n][1]))
                                for n in namen]))
        for name in namen:
            links_seite = np.mean(baender[name]) > 0
            ergebnis[name] = ((aussen - breite, aussen) if links_seite
                              else (-aussen, -aussen + breite))
    return ergebnis


def _im_radbereich(mitten: np.ndarray, nabe, radius: float,
                   quer: tuple[float, float]) -> np.ndarray:
    """Dreiecke innerhalb des Schnittzylinders um eine Nabe.

    Der Zylinder liegt auf der Querachse: radial wird in der X-Z-Ebene gemessen,
    ``quer`` begrenzt ihn entlang Y auf die gemessene Reifenbreite.
    """
    hx, _, hz = nabe
    radial = np.hypot(mitten[:, 0] - hx, mitten[:, 2] - hz)
    return (radial <= radius) & (mitten[:, 1] >= quer[0]) & (mitten[:, 1] <= quer[1])


def nachbarschaft(mesh: trimesh.Trimesh) -> np.ndarray:
    """Welche Dreiecke aneinandergrenzen - ueber Vertex-**Positionen**.

    Nicht ueber die Vertex-Indizes: die GLB-Dateien werden mit ``process=False``
    geladen, damit die UV-Naehte erhalten bleiben. An einer UV-Naht liegen zwei
    Vertices absichtlich an derselben Stelle mit verschiedenen
    Texturkoordinaten. Auf den Indizes gerechnet zerfaellt eine
    zusammenhaengende Flaeche dadurch in hunderte Fetzen - der erste Lauf am
    echten rookie.glb hat aus einem Rad ganze 1042 von 459.268 Dreiecken
    herausgetrennt, einen Splitter von 8 cm Hoehe statt eines Rades von 65 cm.

    ``merge_vertices`` auf einer nackten Kopie loest das: die Dreiecksliste
    bleibt unveraendert, nur die Indizes werden zusammengefuehrt.
    """
    nackt = trimesh.Trimesh(vertices=np.asarray(mesh.vertices).copy(),
                            faces=np.asarray(mesh.faces).copy(), process=False)
    nackt.merge_vertices()
    return nackt.face_adjacency


def _groesste_gruppe(auswahl: np.ndarray, adjazenz: np.ndarray) -> np.ndarray:
    """Auf den zusammenhaengenden Teil mit den meisten Dreiecken eindampfen.

    Ohne das nimmt der Zylinder auch Karosserieteile mit, die zufaellig in
    seinem Bereich liegen aber nicht mit dem Rad verbunden sind - etwa ein
    Stueck Schweller hinter dem Radkasten.
    """
    indizes = np.flatnonzero(auswahl)
    if indizes.size == 0 or adjazenz.size == 0:
        return auswahl
    innen = auswahl[adjazenz[:, 0]] & auswahl[adjazenz[:, 1]]
    gruppen = trimesh.graph.connected_components(adjazenz[innen], nodes=indizes)
    if len(gruppen) <= 1:
        return auswahl
    verkleinert = np.zeros_like(auswahl)
    verkleinert[max(gruppen, key=len)] = True
    return verkleinert


#: Wie hoch ueber dem tiefsten Punkt noch als Aufstandsflaeche zaehlt, in
#: Anteilen des Radradius. Schmal genug, dass nur der Reifen unten drin liegt.
AUFSTAND_ANTEIL = 0.30


def nabe_aus_bodenkontakt(punkte: np.ndarray, nabe, radius: float) -> np.ndarray:
    """Den tatsaechlichen Radmittelpunkt ueber die Aufstandsflaeche bestimmen.

    Die gerechnete Nabe kommt aus der Sollmasstabelle: x aus dem halben
    Radstand, z aus dem halben Raddurchmesser. Das erzeugte Modell haelt sich
    daran nicht auf den Zentimeter — beim Fahrzeug aus zwei Ansichten ist es
    1,55 m hoch statt 1,40.

    Sitzt die Drehachse neben der Radmitte, **kreist** das Rad beim Rollen,
    statt sich zu drehen: es wandert sichtbar auf und ab.

    Der Anker ist der Boden. Ein Reifen steht darauf, sein tiefster Punkt ist
    die Aufstandsflaeche, und die Nabe liegt genau einen Radius darueber. Das
    gilt unabhaengig davon, wieviel Radlauf beim Schnitt mitgekommen ist.

    Ein Mittelwert ueber die Reifenflanke waere naheliegender gewesen und ist
    genau daran gescheitert: der mitgeschnittene Kotfluegel liegt **oberhalb**
    des Rades und zieht jeden Mittelwert nach oben. Am echten Modell kamen so
    Nabenhoehen von 0,34 bis 0,51 m heraus — bei einem Rad von 0,65 m
    Durchmesser, das auf der Strasse steht.

    Die Querrichtung (y) bleibt unberuehrt, die kommt aus der Bandmessung.
    """
    mitte = np.asarray(nabe, dtype=np.float64).copy()
    punkte = np.asarray(punkte, dtype=np.float64)
    if len(punkte) < 12:
        return mitte

    unten = punkte[:, 2].min()
    aufstand = punkte[:, 2] <= unten + AUFSTAND_ANTEIL * radius
    if aufstand.sum() < 8:
        return mitte

    x = punkte[aufstand, 0]
    mitte[0] = float(x.min() + x.max()) / 2.0
    mitte[2] = float(unten) + radius
    return mitte


def naben_angleichen(naben: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Alle vier Raeder auf dieselbe Hoehe bringen.

    Ein Auto steht waagerecht. Weichen die gemessenen Hoehen voneinander ab,
    liegt das an unterschiedlich sauber getrennten Raedern und nicht am
    Fahrzeug. Der Mittelwert ist robuster als jeder Einzelwert.
    """
    if not naben:
        return {}
    hoehe = float(np.median([n[2] for n in naben.values()]))
    return {name: np.array([n[0], n[1], hoehe]) for name, n in naben.items()}


def _schliessen(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Die Schnittflaeche zur Fahrzeugmitte hin zuziehen.

    Ohne das sieht man beim Lenken in ein offenes Rad hinein. ``fill_holes``
    schafft das nicht immer - misslingt es, bleibt das Mesh wie es ist und der
    Aufrufer bekommt einen Hinweis.
    """
    try:
        mesh.fill_holes()
    except Exception:
        pass
    return mesh


def schneiden(mesh: trimesh.Trimesh, soll: Fahrzeugmasse) -> Zerlegung:
    """Ein ausgerichtetes, skaliertes Fahrzeugmesh in Karosserie und vier Raeder
    zerlegen.

    Erwartet das Modell in Spielkoordinaten: +X vorne, +Y links, +Z oben, der
    Ursprung mittig auf dem Boden. Also genau das, was ``orient``, ``scale`` und
    ``origin`` liefern.
    """
    mitten = mesh.triangles_center
    adjazenz = nachbarschaft(mesh)

    hinweise: list[str] = []
    raeder: list[Rad] = []
    ist_rad = np.zeros(len(mesh.faces), dtype=bool)

    # Erst alle vier messen, dann symmetrisch machen, dann schneiden. Einzeln
    # gemessen weichen die Naben um bis zu 18 cm voneinander ab, und ein Rad
    # schwenkte beim Lenken um eine andere Achse als sein Gegenueber.
    gemessen: dict[str, tuple[float, float]] = {}
    for name, nabe in zip(RAD_NAMEN, radpositionen(soll.key)):
        band = querband(mitten, nabe, soll.rad_m / 2.0)
        if band is not None:
            gemessen[name] = band
    baender = symmetrisch(gemessen)

    gefunden: dict[str, np.ndarray] = {}
    gerechnete: dict[str, np.ndarray] = {}
    teile: dict[str, trimesh.Trimesh] = {}

    for name, nabe in zip(RAD_NAMEN, radpositionen(soll.key)):
        band = baender.get(name)
        if band is None:
            # Dieselbe Obergrenze wie beim Kappen, um die gerechnete Nabe
            # gelegt. Zwei verschiedene Vorstellungen davon, wie breit ein
            # Reifen hoechstens ist, waeren eine Falle: der eine Weg schnitte
            # doppelt so viel heraus wie der andere.
            tiefe = soll.rad_m * BAND_HOECHSTANTEIL / 2.0
            band = (nabe[1] - tiefe, nabe[1] + tiefe)
            hinweise.append(f"{name}: Reifenbreite nicht messbar, "
                            f"geschaetzt auf {2 * tiefe:.2f} m")

        # Zwei Durchgaenge. Der erste sucht grob um die gerechnete Lage, damit
        # ueberhaupt etwas zum Vermessen da ist; der zweite schneidet um die
        # **gemessene** Nabe und mit dem daraus folgenden Reifenradius.
        #
        # Der erste Durchgang allein greift daneben, weil die gerechnete Lage
        # aus Radstand und Sollradius stammt: am Modell aus zwei Ansichten liegt
        # die tatsaechliche Nabe bis zu 7 cm daneben. Der Zylinder sitzt dann
        # schief ueber dem Rad - auf der einen Seite fehlt Reifen, auf der
        # anderen kommt Karosserie mit.
        gerechnet = np.array([float(nabe[0]), (band[0] + band[1]) / 2.0,
                              float(nabe[2])])
        grob = _im_radbereich(mitten, gerechnet,
                              soll.rad_m / 2.0 * 1.15, band) & ~ist_rad
        grob = _groesste_gruppe(grob, adjazenz)
        if grob.sum() < 12:
            hinweise.append(f"{name}: nichts zum Heraustrennen gefunden "
                            f"({int(grob.sum())} Dreiecke) - Modell pruefen")
            continue

        vorlaeufig = mesh.submesh([np.flatnonzero(grob)], append=True, repair=False)
        echte_nabe = nabe_aus_bodenkontakt(
            vorlaeufig.vertices, gerechnet, soll.rad_m / 2.0)

        # Das Rad steht auf der Strasse: sein Radius ist die Nabenhoehe.
        reifenradius = float(echte_nabe[2])
        auswahl = _im_radbereich(mitten, echte_nabe,
                                 reifenradius * RADIUS_ZUGABE, band) & ~ist_rad
        auswahl = _groesste_gruppe(auswahl, adjazenz)
        if auswahl.sum() < 12:
            auswahl = grob

        teile[name] = mesh.submesh([np.flatnonzero(auswahl)], append=True,
                                   repair=False)
        gefunden[name] = echte_nabe
        gerechnete[name] = gerechnet
        ist_rad |= auswahl

    # Erst wenn alle vier vermessen sind, auf eine gemeinsame Hoehe bringen -
    # ein Auto steht waagerecht.
    for name, echte_nabe in naben_angleichen(gefunden).items():
        abweichung = float(np.linalg.norm(gerechnete[name] - echte_nabe))
        if abweichung > 0.05:
            hinweise.append(
                f"{name}: Nabe {abweichung * 100:.0f} cm neben der gerechneten "
                f"Lage (z {gerechnete[name][2]:.3f} -> {echte_nabe[2]:.3f})")
        teil = teile[name]
        teil.apply_translation(-echte_nabe)
        raeder.append(Rad(name, _schliessen(teil),
                          tuple(float(w) for w in echte_nabe)))

    if not ist_rad.any():
        hinweise.append("Kein einziges Rad getrennt - Karosserie unveraendert")
        return Zerlegung(mesh.copy(), [], hinweise)

    karosserie = mesh.submesh([np.flatnonzero(~ist_rad)], append=True, repair=False)
    return Zerlegung(karosserie, raeder, hinweise)
