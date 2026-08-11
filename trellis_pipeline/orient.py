"""Ausrichtung: aus einer beliebig im Raum liegenden Generierung ein Fahrzeug
in Spielkoordinaten machen.

Vereinbarung im Spiel: **+X ist vorne, +Y ist links, +Z ist oben.**

Drei Fragen sind zu klaeren, und sie sind unterschiedlich gut automatisierbar:

* **Welche Achse ist welche** - sicher. Ueber die orientierte Bounding-Box: das
  laengste Mass eines Autos ist die Laenge, das kuerzeste die Hoehe.
* **Oben oder unten** - ueber die Breite. Ein Auto ist unten breiter als oben:
  unten Schweller, Radhaeuser und Reifen, oben ein schmaleres Dach. Steht die
  Breite unentschieden, entscheidet der Schwerpunkt.
* **Vorne oder hinten** - nicht sicher automatisierbar. Motorhaube und Kofferraum
  sind sich zu aehnlich, und bei einem Mittelmotor stimmt selbst die Faustregel
  nicht. Das entscheidet ``trellis_import.json`` je Modell von Hand.
"""
from __future__ import annotations

import numpy as np
import trimesh

#: Der Schluessel, unter dem die angewandte Matrix am Mesh haengen bleibt.
#: Nachvollziehbarkeit: ohne sie laesst sich hinterher nicht mehr sagen, wie das
#: Modell gedreht wurde.
META_MATRIX = "trellis_ausrichtung"


def schwerpunkt(mesh: trimesh.Trimesh) -> np.ndarray:
    """Massenschwerpunkt, mit Rueckfall fuer offene Meshes.

    TRELLIS liefert regelmaessig nicht wasserdichte Oberflaechen - Loecher unter
    dem Fahrzeugboden, offene Radkaesten. ``center_mass`` setzt ein geschlossenes
    Volumen voraus und liefert dort Unsinn. Der Rueckfall ist der
    flaechengewichtete Schwerpunkt der Dreiecke: nicht dasselbe, aber fuer die
    Frage "wo ist unten" genau so brauchbar.
    """
    if mesh.is_watertight and mesh.volume > 0:
        return np.asarray(mesh.center_mass, dtype=np.float64)
    flaechen = mesh.area_faces
    if flaechen.sum() <= 0:
        return np.asarray(mesh.vertices.mean(axis=0), dtype=np.float64)
    return np.asarray(
        (mesh.triangles_center * flaechen[:, None]).sum(axis=0) / flaechen.sum(),
        dtype=np.float64)


#: Wie dick die verglichenen Scheiben sind, als Anteil der Fahrzeughoehe.
SCHEIBE = 0.25

#: Ab welchem Breitenunterschied die Breite entscheiden darf. Darunter gilt die
#: Frage als unentschieden und der Schwerpunkt uebernimmt.
BREITE_DEUTLICH = 0.05


def steht_auf_dem_dach(mesh: trimesh.Trimesh) -> bool:
    """Ob das Modell auf dem Kopf liegt.

    Erstes Kriterium ist die Breite: unten Schweller, Radhaeuser und Reifen,
    oben ein schmaleres Dach. Das ist deutlich belastbarer als der Schwerpunkt.

    Der Schwerpunkt allein taeuscht bei kantigen Formen: bei einem Kasten auf
    vier Raedern liegt der flaechengewichtete Schwerpunkt **ueber** der
    Bbox-Mitte, weil die grossen Seitenflaechen oben so viel Flaeche haben wie
    unten. "Unten schwerer" gilt fuer die Masse, nicht fuer die Oberflaeche -
    und gerechnet wird hier notgedrungen auf der Oberflaeche, weil TRELLIS
    keine geschlossenen Volumen liefert.

    Bleibt die Breite unentschieden, entscheidet doch der Schwerpunkt.
    """
    v = np.asarray(mesh.vertices)
    unten, oben = float(v[:, 2].min()), float(v[:, 2].max())
    hoehe = oben - unten
    if hoehe <= 0:
        return False

    def breite(auswahl: np.ndarray) -> float:
        if not auswahl.any():
            return 0.0
        y = v[auswahl, 1]
        return float(y.max() - y.min())

    unten_breit = breite(v[:, 2] <= unten + SCHEIBE * hoehe)
    oben_breit = breite(v[:, 2] >= oben - SCHEIBE * hoehe)
    groesser = max(unten_breit, oben_breit)
    if groesser > 0 and abs(unten_breit - oben_breit) / groesser >= BREITE_DEUTLICH:
        return oben_breit > unten_breit

    return float(schwerpunkt(mesh)[2]) > float(mesh.bounding_box.centroid[2])


def letzte_matrix(mesh: trimesh.Trimesh) -> np.ndarray:
    """Die Matrix, die :func:`ausrichten` auf dieses Mesh angewandt hat."""
    m = mesh.metadata.get(META_MATRIX)
    return np.eye(4) if m is None else np.asarray(m, dtype=np.float64)


def _obb_matrix(mesh: trimesh.Trimesh, typ: str) -> np.ndarray:
    """Rotation und Verschiebung, die die OBB-Achsen auf die Weltachsen legt."""
    kasten = mesh.bounding_box_oriented.primitive
    T = np.asarray(kasten.transform, dtype=np.float64)
    achsen = T[:3, :3]                      # Spalten sind die Kastenachsen
    mitte = T[:3, 3]
    laengen = np.asarray(kasten.extents, dtype=np.float64)

    gross_nach_klein = np.argsort(laengen)[::-1]
    if typ == "rad":
        # Ein Rad ist eine Scheibe: zwei etwa gleich grosse Achsen bilden den
        # Durchmesser, die kleinste ist die Reifenbreite. Die gehoert quer zur
        # Fahrtrichtung auf Y - die Drehachse des Rades.
        reihen = [gross_nach_klein[0], gross_nach_klein[2], gross_nach_klein[1]]
    else:
        reihen = list(gross_nach_klein)     # laengste -> X, mittlere -> Y, kuerzeste -> Z

    R = np.stack([achsen[:, i] for i in reihen])   # Zeile i = neue Achse i
    if np.linalg.det(R) < 0:
        # Eine Spiegelung wuerde die Dreiecksorientierung umdrehen und aus einem
        # Rechts- einen Linkslenker machen. Statt zu spiegeln die Querachse
        # umdrehen - das Ergebnis ist eine echte Drehung.
        R[1] = -R[1]

    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = -R @ mitte
    return M


def _drehung(winkel: float, achse) -> np.ndarray:
    return trimesh.transformations.rotation_matrix(winkel, achse)


def ausrichten(mesh: trimesh.Trimesh, flip: bool = False,
               typ: str = "karosserie") -> trimesh.Trimesh:
    """Eine ausgerichtete Kopie des Meshes.

    ``flip`` dreht das Modell um 180 Grad um die Hochachse - fuer den Fall, dass
    TRELLIS Front und Heck vertauscht hat. Oben bleibt dabei oben.
    """
    ergebnis = mesh.copy()
    M = _obb_matrix(ergebnis, typ)
    ergebnis.apply_transform(M)

    if typ != "rad" and steht_auf_dem_dach(ergebnis):
        drehen = _drehung(np.pi, (1, 0, 0))
        ergebnis.apply_transform(drehen)
        M = drehen @ M

    if flip:
        drehen = _drehung(np.pi, (0, 0, 1))
        ergebnis.apply_transform(drehen)
        M = drehen @ M

    ergebnis.metadata[META_MATRIX] = M
    return ergebnis
