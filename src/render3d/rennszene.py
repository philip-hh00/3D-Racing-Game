"""Die Rennwelt in 3D: Strecke, Fahrzeuge, Schattenflecke.

Dieses Modul kennt **kein pygame und keine Spielklassen** — siehe
``VEREINBARUNGEN.md``. Es bekommt eine Liste von :class:`Fahrzeugstand`
und zeichnet, was darin steht. Wer die Stände füllt, weiß, was ein
``PlayerVehicle`` ist; die Szene muss es nicht wissen.

Zwei Dinge, die den Aufbau bestimmen:

**Modelle werden geteilt, Zustände nicht.** Acht Fahrzeuge auf dem Rookie-Netz
laden das GLB genau einmal; achtmal 600 000 Dreiecke hochzuladen wäre eine
halbe Sekunde Ladezeit und 200 MB Grafikspeicher für dasselbe Auto. Der
Rollwinkel eines Rades ist dagegen Zustand je Fahrzeug — er wächst mit dem
gefahrenen Weg — und braucht je Fahrzeug einen eigenen
:class:`~src.render3d.vehicle_node.Fahrzeugknoten`.

**Fehlt ein Modell, wird der Ersatz genommen.** Im Repo liegt bisher nur
``rookie.glb``. Ein Rennen mit acht Fahrzeugen soll deswegen nicht scheitern;
kommt ``limousine.glb`` dazu, greift sie ohne Codeänderung.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import matrix, mesh, schatten, shader, vehicle_node

try:                                             # pragma: no cover - Importpfad
    import moderngl
except ImportError:                              # pragma: no cover
    moderngl = None


#: Grundtöne der Streckenbänder, solange es keine Straßentextur gibt.
BANDFARBEN = {
    "fahrbahn": (0.24, 0.24, 0.26),
    "randstein_links": (0.72, 0.20, 0.20),
    "randstein_rechts": (0.72, 0.20, 0.20),
    "untergrund": (0.34, 0.45, 0.24),
}

#: Fahrzeugschlüssel, der einspringt, wenn ein Modell fehlt.
ERSATZFAHRZEUG = "rookie"

#: Maße, mit denen der Schattenfleck gebaut wird, wenn keine ``_teile.json``
#: danebenliegt. Grob ein Mittelklassewagen — besser als gar kein Fleck.
ERSATZMASSE_M = (4.3, 2.0)


def band_hochladen(ctx, programm, band):
    """Ein Streckenband an OpenGL geben."""
    puffer = [
        (ctx.buffer(np.ascontiguousarray(band.positionen, "f4")), "3f", "in_position"),
        (ctx.buffer(np.ascontiguousarray(band.normalen, "f4")), "3f", "in_normale"),
        (ctx.buffer(np.ascontiguousarray(band.uv, "f4")), "2f", "in_uv"),
    ]
    ibo = ctx.buffer(np.ascontiguousarray(band.indizes, "u4"))
    return ctx.vertex_array(programm, puffer, ibo)


# ---------------------------------------------------------------------------
# Was gezeichnet werden soll
# ---------------------------------------------------------------------------

@dataclass
class Fahrzeugstand:
    """Ein Fahrzeug, wie die Szene es sieht.

    Bewusst nur Zahlen: die Szene soll nicht an den Spielklassen hängen, und
    ein Ghost, ein ferngesteuertes Fahrzeug und ein KI-Wagen unterscheiden
    sich hier durch nichts als ihre Werte.
    """

    kennung: int
    schluessel: str
    pos_m: np.ndarray
    gierwinkel_rad: float
    #: In **diesem Bild** zurückgelegter Weg, mit Vorzeichen. Daraus wächst
    #: der Rollwinkel der Räder; rückwärts drehen sie rückwärts.
    weg_m: float = 0.0
    lenkwinkel_rad: float = 0.0
    #: Ghosts werden entfärbt und durchscheinend gezeichnet.
    entfaerbt: bool = False


# ---------------------------------------------------------------------------
# Modelle
# ---------------------------------------------------------------------------

def modelldatei(ordner: str | Path, schluessel: str,
                ersatz: str = ERSATZFAHRZEUG) -> tuple[Path | None, str]:
    """Welche GLB-Datei zu einem Fahrzeugschlüssel gehört.

    Liefert ``(pfad, tatsaechlicher_schluessel)``. Fehlt das Modell, springt
    ``ersatz`` ein — und der zurückgegebene Schlüssel ist dann dessen, damit
    auch die passende ``_teile.json`` gefunden wird. Ein Rookie-Netz mit den
    Nabenpositionen einer Limousine hätte die Räder neben dem Auto.
    """
    ordner = Path(ordner)
    for kandidat in (schluessel, ersatz):
        if not kandidat:
            continue
        pfad = ordner / f"{kandidat}.glb"
        if pfad.is_file():
            return pfad, kandidat
    return None, ""


@dataclass
class Teiledaten:
    """Was ``<key>_teile.json`` über ein Fahrzeug sagt."""

    plaetze: list[vehicle_node.Radplatz]
    raddurchmesser_m: float
    laenge_m: float
    breite_m: float


def teile_laden(ordner: str | Path, schluessel: str,
                korrektur_datei: str | Path | None = None) -> Teiledaten | None:
    """``<key>_teile.json`` einlesen, mit den Nabenkorrekturen aus
    ``trellis_import.json``.

    ``None``, wenn die Datei fehlt: dann hat das Modell keine trennbaren Räder
    und wird als ein Stück gezeichnet. Das kostet drehende Räder, aber kein
    Rennen.
    """
    pfad = Path(ordner) / f"{schluessel}_teile.json"
    if not pfad.is_file():
        return None
    korrekturen = (vehicle_node.korrekturen_lesen(korrektur_datei, schluessel)
                   if korrektur_datei else {})
    plaetze, durchmesser = vehicle_node.teile_lesen(pfad, korrekturen)
    with open(pfad, encoding="utf-8") as fh:
        daten = json.load(fh)
    return Teiledaten(
        plaetze=plaetze,
        raddurchmesser_m=durchmesser,
        laenge_m=float(daten.get("laenge_m", ERSATZMASSE_M[0])),
        breite_m=float(daten.get("breite_m", ERSATZMASSE_M[1])),
    )


@dataclass
class Fahrzeugmodell:
    """Ein hochgeladenes Fahrzeug, geteilt von allen, die es fahren."""

    schluessel: str
    modell: mesh.Modell
    teile: Teiledaten | None
    schatten_vao: object = None

    def knoten(self) -> vehicle_node.Fahrzeugknoten | None:
        """Ein frischer Knoten für **ein** Fahrzeug dieses Typs."""
        if self.teile is None or not self.teile.plaetze:
            return None
        return vehicle_node.Fahrzeugknoten(self.teile.plaetze,
                                           self.teile.raddurchmesser_m)


class Modellspeicher:
    """Fahrzeugmodelle einmal laden und an alle weiterreichen."""

    def __init__(self, ctx, programm, ordner: str | Path,
                 korrektur_datei: str | Path | None = None,
                 schattenprogramm=None) -> None:
        self.ctx = ctx
        self.programm = programm
        self.ordner = Path(ordner)
        self.korrektur_datei = korrektur_datei
        self.schattenprogramm = schattenprogramm
        self._geladen: dict[str, Fahrzeugmodell | None] = {}
        self._gemeldet: set[str] = set()

    def holen(self, schluessel: str) -> Fahrzeugmodell | None:
        """Das Modell zu einem Schlüssel, notfalls das Ersatzmodell."""
        if schluessel in self._geladen:
            return self._geladen[schluessel]

        pfad, echter = modelldatei(self.ordner, schluessel)
        if pfad is None:
            if schluessel not in self._gemeldet:
                self._gemeldet.add(schluessel)
                print(f"[rennszene] Kein Modell fuer '{schluessel}' und kein "
                      f"Ersatz in {self.ordner} - dieses Fahrzeug bleibt unsichtbar.")
            self._geladen[schluessel] = None
            return None
        if echter != schluessel and schluessel not in self._gemeldet:
            self._gemeldet.add(schluessel)
            print(f"[rennszene] Kein Modell fuer '{schluessel}' - "
                  f"es faehrt mit '{echter}'.")

        # Zweimal denselben Ersatz laden waere Verschwendung: der echte
        # Schluessel ist der Schluessel des Speichers.
        if echter in self._geladen:
            self._geladen[schluessel] = self._geladen[echter]
            return self._geladen[echter]

        teile = teile_laden(self.ordner, echter, self.korrektur_datei)
        fahrzeugmodell = Fahrzeugmodell(
            schluessel=echter,
            modell=mesh.hochladen(self.ctx, self.programm, mesh.laden(pfad)),
            teile=teile,
        )
        if self.schattenprogramm is not None:
            laenge = teile.laenge_m if teile else ERSATZMASSE_M[0]
            breite = teile.breite_m if teile else ERSATZMASSE_M[1]
            fahrzeugmodell.schatten_vao = schatten.flaeche_hochladen(
                self.ctx, self.schattenprogramm, laenge, breite)
        self._geladen[echter] = fahrzeugmodell
        self._geladen[schluessel] = fahrzeugmodell
        return fahrzeugmodell


# ---------------------------------------------------------------------------
# Radzustand je Fahrzeug
# ---------------------------------------------------------------------------

class Knotenspeicher:
    """Je Fahrzeug ein :class:`Fahrzeugknoten`, über die Kennung gefunden.

    Der Rollwinkel wächst mit dem gefahrenen Weg — er ist Zustand. Ein Knoten,
    je Bild neu gebaut, setzte ihn jedes Mal auf null zurück und die Räder
    stünden bei voller Fahrt still.
    """

    def __init__(self, bauen) -> None:
        #: ``bauen(schluessel)`` liefert einen Knoten oder ``None``.
        self._bauen = bauen
        self._knoten: dict[int, object | None] = {}

    def knoten(self, kennung: int):
        return self._knoten.get(kennung)

    def fortschreiben(self, staende) -> None:
        """Alle Knoten um den Weg dieses Bildes weiterdrehen.

        Fahrzeuge, die nicht mehr vorkommen, werden vergessen — sonst wächst
        der Speicher über ein Grand-Prix-Wochenende mit jedem Lauf.
        """
        gesehen = set()
        for stand in staende:
            gesehen.add(stand.kennung)
            if stand.kennung not in self._knoten:
                self._knoten[stand.kennung] = self._bauen(stand.schluessel)
            knoten = self._knoten[stand.kennung]
            if knoten is None:
                continue
            knoten.weg_zuruecklegen(stand.weg_m)
            knoten.lenken(stand.lenkwinkel_rad)
        for kennung in list(self._knoten):
            if kennung not in gesehen:
                del self._knoten[kennung]


# ---------------------------------------------------------------------------
# Die Szene
# ---------------------------------------------------------------------------

#: Wie stark ein Ghost entfärbt und wie durchscheinend er gezeichnet wird.
GHOST_ENTFAERBUNG = 0.85
GHOST_DECKKRAFT = 0.55


class Rennszene:
    """Strecke und Fahrzeuge, gezeichnet in dieser Reihenfolge.

    Die Reihenfolge ist nicht beliebig: erst die undurchsichtige Welt, dann
    die Schattenflecke (die mischen und in die Tiefe schauen, aber nicht
    hineinschreiben), dann die Fahrzeuge, zuletzt die durchscheinenden Ghosts.
    """

    def __init__(self, ctx, streckennetz, modellordner: str | Path,
                 korrektur_datei: str | Path | None = None) -> None:
        self.ctx = ctx
        self.programm = shader.programm(ctx)
        self.schattenwerfer = schatten.Schattenwerfer(ctx)
        self.speicher = Modellspeicher(
            ctx, self.programm, modellordner,
            korrektur_datei=korrektur_datei,
            schattenprogramm=self.schattenwerfer.programm)
        self.baender = [(band, band_hochladen(ctx, self.programm, band))
                        for band in streckennetz.baender]
        self.knotenspeicher = Knotenspeicher(self._knoten_bauen)

    def _knoten_bauen(self, schluessel: str):
        fahrzeugmodell = self.speicher.holen(schluessel)
        return fahrzeugmodell.knoten() if fahrzeugmodell else None

    # -- Zeichnen --------------------------------------------------------
    def zeichnen(self, mvp: np.ndarray, kamera_position, staende) -> None:
        """Ein Bild der Welt aus einer Kamera."""
        staende = list(staende)
        self.knotenspeicher.fortschreiben(staende)

        self.programm["mvp"].write(np.asarray(mvp, dtype="f4").T.tobytes())
        self.programm["kamera_position"].value = tuple(
            float(w) for w in kamera_position)

        self._strecke_zeichnen()
        self._schatten_zeichnen(mvp, staende)
        for stand in staende:
            if not stand.entfaerbt:
                self._fahrzeug_zeichnen(stand)
        # Ghosts zuletzt: sie mischen, und was durchscheinend gezeichnet wird,
        # muss hinter sich schon etwas vorfinden.
        for stand in staende:
            if stand.entfaerbt:
                self._fahrzeug_zeichnen(stand)

    def _strecke_zeichnen(self) -> None:
        self.ctx.enable(moderngl.DEPTH_TEST)
        self.ctx.disable(moderngl.BLEND)
        self.programm["hat_basisfarbe"].value = 0.0
        self.programm["hat_metallic_rauheit"].value = 0.0
        self.programm["metallic_faktor"].value = 0.0
        self.programm["rauheit_faktor"].value = 0.92
        self.programm["entfaerbung"].value = 0.0
        self.programm["deckkraft"].value = 1.0
        shader.modell_setzen(self.programm, matrix.einheit())
        for band, vao in self.baender:
            self.programm["grundton"].value = BANDFARBEN.get(band.name, (0.5, 0.5, 0.5))
            vao.render()

    def _schatten_zeichnen(self, mvp: np.ndarray, staende) -> None:
        self.schattenwerfer.beginnen(mvp)
        for stand in staende:
            fahrzeugmodell = self.speicher.holen(stand.schluessel)
            if fahrzeugmodell is None or fahrzeugmodell.schatten_vao is None:
                continue
            self.schattenwerfer.zeichnen(
                fahrzeugmodell.schatten_vao,
                matrix.fahrzeug(stand.pos_m, stand.gierwinkel_rad))
        self.schattenwerfer.beenden()

    def _fahrzeug_zeichnen(self, stand: Fahrzeugstand) -> None:
        fahrzeugmodell = self.speicher.holen(stand.schluessel)
        if fahrzeugmodell is None:
            return
        modell = fahrzeugmodell.modell

        self.ctx.enable(moderngl.DEPTH_TEST)
        if stand.entfaerbt:
            self.ctx.enable(moderngl.BLEND)
            self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
            self.programm["entfaerbung"].value = GHOST_ENTFAERBUNG
            self.programm["deckkraft"].value = GHOST_DECKKRAFT
        else:
            self.ctx.disable(moderngl.BLEND)
            self.programm["entfaerbung"].value = 0.0
            self.programm["deckkraft"].value = 1.0

        self.programm["hat_basisfarbe"].value = 1.0 if modell.basisfarbe else 0.0
        self.programm["hat_metallic_rauheit"].value = (
            1.0 if modell.metallic_rauheit else 0.0)
        self.programm["metallic_faktor"].value = 1.0
        self.programm["rauheit_faktor"].value = 1.0
        if modell.basisfarbe:
            modell.basisfarbe.use(0)
        if modell.metallic_rauheit:
            modell.metallic_rauheit.use(1)

        knoten = self.knotenspeicher.knoten(stand.kennung)
        if knoten is not None:
            for name, m in knoten.matrizen(stand.pos_m, stand.gierwinkel_rad).items():
                teil = modell.teil(name)
                if teil is not None:
                    shader.modell_setzen(self.programm, m)
                    teil.vao.render()
        else:
            # Ohne Radplätze bleibt das Fahrzeug ein Stück. Die Teile sitzen
            # dann an ihrem Versatz aus der GLB-Szene.
            grund = matrix.fahrzeug(stand.pos_m, stand.gierwinkel_rad)
            for teil in modell.teile:
                shader.modell_setzen(
                    self.programm, grund @ matrix.verschiebung(teil.versatz))
                teil.vao.render()

        if stand.entfaerbt:
            self.ctx.disable(moderngl.BLEND)
            self.programm["entfaerbung"].value = 0.0
            self.programm["deckkraft"].value = 1.0
