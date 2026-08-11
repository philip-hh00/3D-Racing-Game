"""Massstab. TRELLIS liefert Modelle in einer willkuerlichen Einheit - meist
in einen Einheitswuerfel normiert. Hier bekommen sie Meter.

Skaliert wird immer gleichmaessig ueber alle drei Achsen. Achsweise auf die
Solltabelle zu ziehen wuerde die Masse zwar exakt treffen, aber das Fahrzeug
verzerren: aus einem 5 Prozent zu schmalen Modell wuerde ein gestauchtes statt
eines etwas zu schmalen. Die Laenge fuehrt, die Abweichung in Breite und Hoehe
meldet der Bericht.
"""
from __future__ import annotations

import trimesh


def _skalieren(mesh: trimesh.Trimesh, faktor: float) -> trimesh.Trimesh:
    if not faktor > 0:
        raise ValueError(f"Skalierungsfaktor muss positiv sein, war {faktor}")
    ergebnis = mesh.copy()
    ergebnis.apply_scale(faktor)
    return ergebnis


def auf_ziellaenge(mesh: trimesh.Trimesh, ziel_m: float) -> trimesh.Trimesh:
    """Gleichmaessig skalieren, bis die X-Ausdehnung der Ziellaenge entspricht."""
    ist = float(mesh.bounding_box.extents[0])
    if ist <= 0:
        raise ValueError("Modell hat keine Ausdehnung in Fahrtrichtung")
    return _skalieren(mesh, ziel_m / ist)


def auf_raddurchmesser(mesh: trimesh.Trimesh, ziel_m: float) -> trimesh.Trimesh:
    """Ein Rad ueber seinen Durchmesser skalieren.

    Der Durchmesser ist das Mittel der beiden Achsen quer zur Drehachse (X und
    Z). Das Mittel und nicht eine der beiden: ein leicht unrundes Mesh wuerde
    sonst je nach gewaehlter Achse unterschiedlich gross herauskommen.
    """
    ext = mesh.bounding_box.extents
    ist = (float(ext[0]) + float(ext[2])) / 2.0
    if ist <= 0:
        raise ValueError("Rad hat keinen messbaren Durchmesser")
    return _skalieren(mesh, ziel_m / ist)
