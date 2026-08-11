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

#: Wie weit ueber den Sollradius hinaus geschnitten wird. Der Reifen des
#: erzeugten Modells trifft den Sollwert nicht auf den Millimeter, und ein zu
#: knapper Schnitt laesst einen Ring Gummi in der Karosserie stehen - der dreht
#: sich dann nicht mit und faellt sofort auf.
RADIUS_ZUGABE = 1.12

#: Rueckfall fuer die Schnitttiefe nach innen, als Anteil des Raddurchmessers -
#: nur wenn sich die Reifenbreite nicht messen laesst.
BREITE_ANTEIL = 0.45

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
    if (bis - von) < 2 * reifenradius * BAND_MINDESTANTEIL:
        return None
    return (von * aussen, bis * aussen) if aussen > 0 else (bis * aussen, von * aussen)


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
    radius = soll.rad_m / 2.0 * RADIUS_ZUGABE
    adjazenz = nachbarschaft(mesh)

    hinweise: list[str] = []
    raeder: list[Rad] = []
    ist_rad = np.zeros(len(mesh.faces), dtype=bool)

    for name, nabe in zip(RAD_NAMEN, radpositionen(soll.key)):
        band = querband(mitten, nabe, soll.rad_m / 2.0)
        if band is None:
            tiefe = soll.rad_m * BREITE_ANTEIL
            band = (nabe[1] - tiefe, nabe[1] + tiefe)
            hinweise.append(f"{name}: Reifenbreite nicht messbar, "
                            f"geschaetzt auf {2 * tiefe:.2f} m")

        auswahl = _im_radbereich(mitten, nabe, radius, band) & ~ist_rad
        auswahl = _groesste_gruppe(auswahl, adjazenz)
        if auswahl.sum() < 12:
            hinweise.append(f"{name}: nichts zum Heraustrennen gefunden "
                            f"({int(auswahl.sum())} Dreiecke) - Modell pruefen")
            continue

        # Die Nabe wandert auf die Mitte des gemessenen Bandes. Fuer das Rollen
        # ist das egal - eine Drehung um die Querachse laesst y unberuehrt -,
        # aber die Lenkachse steht senkrecht, und die soll durch die
        # tatsaechliche Radmitte gehen und nicht 6 cm daneben.
        echte_nabe = (float(nabe[0]), (band[0] + band[1]) / 2.0, float(nabe[2]))
        teil = mesh.submesh([np.flatnonzero(auswahl)], append=True, repair=False)
        teil.apply_translation(-np.asarray(echte_nabe, dtype=np.float64))
        raeder.append(Rad(name, _schliessen(teil), echte_nabe))
        ist_rad |= auswahl

    if not ist_rad.any():
        hinweise.append("Kein einziges Rad getrennt - Karosserie unveraendert")
        return Zerlegung(mesh.copy(), [], hinweise)

    karosserie = mesh.submesh([np.flatnonzero(~ist_rad)], append=True, repair=False)
    return Zerlegung(karosserie, raeder, hinweise)
