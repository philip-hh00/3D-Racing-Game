"""Die Rennwelt in 3D: Himmel, Strecke, Begrenzung, Umgebung, Fahrzeuge.

Dieses Modul kennt **kein pygame und keine Spielklassen** — siehe
``VEREINBARUNGEN.md``. Es bekommt eine Liste von :class:`Fahrzeugstand`
und zeichnet, was darin steht. Wer die Stände füllt, weiß, was ein
``PlayerVehicle`` ist; die Szene muss es nicht wissen.

Was den Aufbau bestimmt:

**Modelle werden geteilt, Zustände nicht.** Acht Fahrzeuge auf demselben Netz
laden das GLB genau einmal. Der Rollwinkel eines Rades ist dagegen Zustand je
Fahrzeug und braucht je Fahrzeug einen eigenen
:class:`~src.render3d.vehicle_node.Fahrzeugknoten`.

**Fehlt ein Modell, wird der Ersatz genommen.** Ein Rennen soll nicht an
einer fehlenden Datei scheitern.

**Lack ist ein Material, keine Textur.** Die Fahrzeuge aus
``tools/blender/fahrzeug_bauen.py`` tragen ihren Lack im Material ``lack``
(und ``lack2`` für Zweitfarbe und Livree). Eine Lackierung aus der Werkstatt
ersetzt beim Zeichnen nur dessen Farbe, Metallic und Rauheit — jedes Auto im
Feld kann so anders aussehen, ohne ein zweites Netz.

**Laden in Schritten.** :meth:`Rennszene.aufbauen` ist ein Generator: je
geladenem Stück liefert er den Fortschritt, damit der Ladebildschirm des
Rennens einen Balken zeigen kann. Wer keinen Balken braucht (die Tests),
lässt :class:`Rennszene` alles auf einmal laden.

Die Zeichenreihenfolge ist nicht beliebig: Schattenkarte, Himmel, Strecke und
Begrenzung, Umgebung, Kontaktschatten, Fahrzeuge, zuletzt alles
Durchscheinende (Scheiben, Ghosts).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import begrenzung, matrix, mesh, schatten, shader, vehicle_node
from .deko import Dekozeichner, material_setzen

try:                                             # pragma: no cover - Importpfad
    import moderngl
except ImportError:                              # pragma: no cover
    moderngl = None


#: Grundtöne der Streckenbänder, wenn keine Textur da ist.
BANDFARBEN = {
    "fahrbahn": (0.24, 0.24, 0.26),
    "randstein_links": (0.72, 0.20, 0.20),
    "randstein_rechts": (0.72, 0.20, 0.20),
    "untergrund": (0.34, 0.45, 0.24),
}

#: Fahrzeugschlüssel, der einspringt, wenn ein Modell fehlt.
ERSATZFAHRZEUG = "rookie"

#: Maße, mit denen der Schattenfleck gebaut wird, wenn keine ``_teile.json``
#: danebenliegt.
ERSATZMASSE_M = (4.3, 2.0)

#: Wie weit der Boden um die Strecke reicht. Hinter der Kulisse und im
#: Nebel — die Kante sieht niemand.
BODEN_RAND_M = 2500.0

#: Kachellänge der Streckenbänder in ``track_mesh`` (v-Koordinate).
STRECKE_KACHEL_M = 8.0


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
class Lackwerte:
    """Eine Lackierung als Zahlen — die Szene weiß nichts von ``lacke.json``.

    ``farbe`` und ``zweitfarbe`` sind sRGB 0..1. Ohne ``zweitfarbe`` behält
    ``lack2`` seine Werksfarbe.
    """

    farbe: tuple[float, float, float]
    metallic: float = 0.0
    rauheit: float = 0.32
    klarlack: float = 1.0
    zweitfarbe: tuple[float, float, float] | None = None
    leuchten: float = 0.0


@dataclass
class Fahrzeugstand:
    """Ein Fahrzeug, wie die Szene es sieht."""

    kennung: int
    schluessel: str
    pos_m: np.ndarray
    gierwinkel_rad: float
    #: In **diesem Bild** zurückgelegter Weg, mit Vorzeichen.
    weg_m: float = 0.0
    lenkwinkel_rad: float = 0.0
    #: Ghosts werden entfärbt und durchscheinend gezeichnet.
    entfaerbt: bool = False
    #: ``None``: Werkslack aus dem Modell.
    lack: Lackwerte | None = None
    #: Neigung des Aufbaus (siehe ``federung.py``), rein optisch.
    nick_rad: float = 0.0
    wank_rad: float = 0.0


# ---------------------------------------------------------------------------
# Modelle
# ---------------------------------------------------------------------------

def modelldatei(ordner: str | Path, schluessel: str,
                ersatz: str = ERSATZFAHRZEUG) -> tuple[Path | None, str]:
    """Welche GLB-Datei zu einem Fahrzeugschlüssel gehört: ``(pfad, schlüssel)``.

    Fehlt das Modell, springt ``ersatz`` ein — und der zurückgegebene
    Schlüssel ist dann dessen, damit auch die passende ``_teile.json``
    gefunden wird.
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


def teile_laden(ordner: str | Path, schluessel: str) -> Teiledaten | None:
    """``<key>_teile.json`` einlesen; ``None``, wenn die Datei fehlt."""
    pfad = Path(ordner) / f"{schluessel}_teile.json"
    if not pfad.is_file():
        return None
    plaetze, durchmesser = vehicle_node.teile_lesen(pfad)
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
    schatten_vaos: dict = field(default_factory=dict)

    def knoten(self) -> vehicle_node.Fahrzeugknoten | None:
        """Ein frischer Knoten für **ein** Fahrzeug dieses Typs."""
        if self.teile is None or not self.teile.plaetze:
            return None
        return vehicle_node.Fahrzeugknoten(self.teile.plaetze,
                                           self.teile.raddurchmesser_m)


class Modellspeicher:
    """Fahrzeugmodelle einmal laden und an alle weiterreichen."""

    def __init__(self, ctx, programm, ordner: str | Path,
                 schattenprogramm=None, tiefenprogramm=None) -> None:
        self.ctx = ctx
        self.programm = programm
        self.ordner = Path(ordner)
        self.schattenprogramm = schattenprogramm
        self.tiefenprogramm = tiefenprogramm
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
        if echter in self._geladen:
            self._geladen[schluessel] = self._geladen[echter]
            return self._geladen[echter]

        daten = mesh.laden(pfad)
        teile = teile_laden(self.ordner, echter)
        fahrzeugmodell = Fahrzeugmodell(
            schluessel=echter,
            modell=mesh.hochladen(self.ctx, self.programm, daten),
            teile=teile,
        )
        if self.tiefenprogramm is not None:
            # Eigene VAOs für die Schattenkarte: eine VAO gehört zu genau
            # einem Programm.
            for teil in daten.teile:
                vaos = []
                for s in teil.stuecke:
                    vp = self.ctx.buffer(np.ascontiguousarray(s.positionen, "f4").tobytes())
                    vu = self.ctx.buffer(np.ascontiguousarray(s.uv, "f4").tobytes())
                    ib = self.ctx.buffer(np.ascontiguousarray(s.indizes, "u4").tobytes())
                    fahrzeugmodell.modell.puffer += [vp, vu, ib]
                    vaos.append(self.ctx.vertex_array(
                        self.tiefenprogramm, [(vp, "3f", "in_position"), (vu, "2f", "in_uv")], ib))
                fahrzeugmodell.schatten_vaos[teil.name] = vaos
        if self.schattenprogramm is not None:
            laenge = teile.laenge_m if teile else ERSATZMASSE_M[0]
            breite = teile.breite_m if teile else ERSATZMASSE_M[1]
            fahrzeugmodell.schatten_vao = schatten.flaeche_hochladen(
                self.ctx, self.schattenprogramm, laenge, breite)
        self._geladen[echter] = fahrzeugmodell
        self._geladen[schluessel] = fahrzeugmodell
        return fahrzeugmodell

    def freigeben(self) -> None:
        gesehen = set()
        for fm in self._geladen.values():
            if fm is None or id(fm) in gesehen:
                continue
            gesehen.add(id(fm))
            for vaos in fm.schatten_vaos.values():
                for v in vaos:
                    v.release()
            if fm.schatten_vao is not None:
                fm.schatten_vao.release()
            fm.modell.freigeben()
        self._geladen = {}


# ---------------------------------------------------------------------------
# Radzustand je Fahrzeug
# ---------------------------------------------------------------------------

class Knotenspeicher:
    """Je Fahrzeug ein :class:`Fahrzeugknoten`, über die Kennung gefunden."""

    def __init__(self, bauen) -> None:
        self._bauen = bauen
        self._knoten: dict[int, object | None] = {}

    def knoten(self, kennung: int):
        return self._knoten.get(kennung)

    def fortschreiben(self, staende) -> None:
        """Alle Knoten um den Weg dieses Bildes weiterdrehen."""
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
            knoten.neigen(stand.nick_rad, stand.wank_rad)
        for kennung in list(self._knoten):
            if kennung not in gesehen:
                del self._knoten[kennung]


# ---------------------------------------------------------------------------
# Streckenmaterial
# ---------------------------------------------------------------------------

@dataclass
class _Flaeche:
    """Ein Band oder Streifen der Strecke, hochgeladen, mit Material."""

    vao: object
    farbe: tuple
    textur: object = None
    mr: object = None
    kachel_m: float = 8.0
    metallic: float = 0.0
    rauheit: float = 0.9
    ton: tuple = (1.0, 1.0, 1.0)


def _textur_laden(ctx, ordner: Path | None, name: str, cache: dict):
    if not name or ordner is None:
        return None, None
    if name in cache:
        return cache[name]
    from PIL import Image
    farbe, mr = ordner / f"{name}_farbe.jpg", ordner / f"{name}_mr.png"
    ergebnis = (None, None)
    if farbe.is_file():
        ergebnis = (mesh.textur_hochladen(ctx, Image.open(farbe)),
                    mesh.textur_hochladen(ctx, Image.open(mr)) if mr.is_file() else None)
    cache[name] = ergebnis
    return ergebnis


def _randsteintextur(ctx, farben):
    """Rot-weiß im Wechsel entlang der Strecke, je Farbe eine halbe Kachel."""
    from PIL import Image
    a = np.zeros((16, 4, 3), dtype=np.uint8)
    rot, weiss = (np.asarray(f) * 255 for f in farben[:2])
    a[:8] = rot
    a[8:] = weiss
    t = mesh.textur_hochladen(ctx, Image.fromarray(a, "RGB"))
    t.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.NEAREST)
    return t


# ---------------------------------------------------------------------------
# Ein Fahrzeug zeichnen — geteilt von Rennszene und Werkstattvorschau
# ---------------------------------------------------------------------------

def lack_material_setzen(p, hm: mesh.HochgeladenesMaterial, lack: Lackwerte | None) -> None:
    """Material setzen; ``lack`` und ``lack2`` bekommen die Lackierung."""
    material_setzen(p, hm)
    name = hm.daten.name
    if name in ("lack", "lack2"):
        shader.setzen(p, "klarlack", 1.0)
        if lack is not None:
            farbe = lack.farbe if name == "lack" else lack.zweitfarbe
            if farbe is not None:
                shader.setzen(p, "grundton", tuple(float(c) for c in farbe))
                shader.setzen(p, "hat_basisfarbe", 0.0)
                shader.setzen(p, "metallic_faktor", float(lack.metallic))
                shader.setzen(p, "rauheit_faktor", float(lack.rauheit))
                shader.setzen(p, "klarlack", float(lack.klarlack))
                if lack.leuchten and name == "lack":
                    lin = [float(c) ** 2.2 * lack.leuchten for c in farbe]
                    shader.setzen(p, "emission", tuple(lin))


def fahrzeugteile_zeichnen(p, modell: mesh.Modell, matrizen: dict,
                           lack: Lackwerte | None, durchsichtig) -> None:
    """Alle Teile eines Fahrzeugs an ihren Matrizen zeichnen.

    ``durchsichtig``: False = nur Deckendes, True = nur Glas, None = alles.
    Den Mischmodus stellt der Aufrufer ein.
    """
    for name, m in matrizen.items():
        teil = modell.teil(name)
        if teil is None:
            continue
        gesetzt = False
        for st in teil.stuecke:
            hm = modell.materialien[st.material] if st.material < len(modell.materialien) else None
            glas = hm is not None and hm.daten.durchsichtig
            if durchsichtig is not None and glas != durchsichtig:
                continue
            if not gesetzt:
                shader.modell_setzen(p, m)
                gesetzt = True
            if hm is not None:
                lack_material_setzen(p, hm, lack)
            st.vao.render()


# ---------------------------------------------------------------------------
# Die Szene
# ---------------------------------------------------------------------------

#: Wie stark ein Ghost entfärbt und wie durchscheinend er gezeichnet wird.
GHOST_ENTFAERBUNG = 0.85
GHOST_DECKKRAFT = 0.55


class Rennszene:
    """Die ganze Welt eines Rennens."""

    def __init__(self, ctx, streckennetz, modellordner: str | Path, *,
                 thema=None, texturordner: str | Path | None = None,
                 himmelordner: str | Path | None = None,
                 umgebungsordner: str | Path | None = None,
                 platzierungen=None, fahrzeuge=(), schattenwurf: bool = True,
                 sofort: bool = True) -> None:
        self.ctx = ctx
        self.netz = streckennetz
        self.modellordner = Path(modellordner)
        self.thema = thema
        self.texturordner = Path(texturordner) if texturordner else None
        self.himmelordner = Path(himmelordner) if himmelordner else None
        self.umgebungsordner = Path(umgebungsordner) if umgebungsordner else None
        self.platzierungen = list(platzierungen or [])
        self.vorab_fahrzeuge = list(dict.fromkeys(fahrzeuge))
        self.schattenwurf_an = schattenwurf
        self.flaechen: list[_Flaeche] = []
        self.deko: Dekozeichner | None = None
        self.himmel = None
        self.schattenkarte = None
        self._texturen: dict = {}
        self._eigene_texturen: list = []
        self.fertig = False
        if sofort:
            for _ in self.aufbauen():
                pass

    # -- Laden -----------------------------------------------------------
    def aufbauen(self):
        """Generator: lädt Stück für Stück und liefert ``(anteil, text)``."""
        ctx = self.ctx
        yield 0.02, "Shader"
        self.programm = shader.programm(ctx)
        self.programm_instanz = shader.programm_instanz(ctx)
        self.schattenwerfer = schatten.Schattenwerfer(ctx)
        from . import licht
        if self.schattenwurf_an:
            try:
                self.schattenkarte = licht.Schattenkarte(ctx)
            except Exception as fehler:              # pragma: no cover - Treiber
                print(f"[rennszene] Keine Schattenkarte: {fehler}")
                self.schattenkarte = None
        # Ein Platzhalter für die Schattenkarte, wenn es keine gibt: ein
        # sampler2DShadow ohne Tiefentextur ist auf manchen Treibern ein Fehler.
        self._leere_tiefe = ctx.depth_texture((1, 1))
        self._leere_tiefe.compare_func = "<="
        tiefenprogramm = self.schattenkarte.programm if self.schattenkarte else None
        self.speicher = Modellspeicher(ctx, self.programm, self.modellordner,
                                       schattenprogramm=self.schattenwerfer.programm,
                                       tiefenprogramm=tiefenprogramm)
        self.knotenspeicher = Knotenspeicher(self._knoten_bauen)

        yield 0.06, "Himmel"
        name = getattr(self.thema, "himmel", "") if self.thema else ""
        self.himmel = licht.Himmel(ctx, self.himmelordner or ".", name)
        self._umgebung_setzen()

        yield 0.1, "Strecke"
        self._strecke_hochladen()

        gesamt = max(1, len(self.vorab_fahrzeuge))
        for i, schluessel in enumerate(self.vorab_fahrzeuge):
            yield 0.15 + 0.35 * i / gesamt, f"Fahrzeug {schluessel}"
            self.speicher.holen(schluessel)

        if self.umgebungsordner is not None and self.platzierungen:
            kulisse = {k.modell for k in getattr(self.thema, "kulisse", [])}
            self.deko = Dekozeichner(ctx, self.programm_instanz,
                                     self.schattenkarte.programm_instanz if self.schattenkarte
                                     else shader.schattenprogramm(ctx, instanz=True),
                                     self.umgebungsordner, self.platzierungen, kulisse)
            anzahl = max(1, len(self.deko._gruppen))
            for i, modell in enumerate(self.deko.schritte()):
                yield 0.5 + 0.48 * i / anzahl, f"Umgebung {modell}"
        self.fertig = True
        yield 1.0, "Fertig"

    def _umgebung_setzen(self) -> None:
        t = self.thema
        for p in (self.programm, self.programm_instanz, self.himmel.programm):
            sonne = tuple(float(c) for c in self.himmel.sonne)
            shader.setzen(p, "sonne_richtung", sonne)
            shader.setzen(p, "hat_himmel", 1.0 if self.himmel.textur is not None else 0.0)
            shader.setzen(p, "himmel_mips", max(1.0, self.himmel.mips - 1.0))
            if t is not None:
                shader.setzen(p, "himmel_zenit", tuple(t.himmel_zenit))
                shader.setzen(p, "himmel_horizont", tuple(t.himmel_horizont))
                shader.setzen(p, "boden_farbe", tuple(t.boden_farbe))
                shader.setzen(p, "sonne_farbe", tuple(t.sonne_farbe))
                shader.setzen(p, "himmel_helligkeit", float(t.himmel_helligkeit))
                shader.setzen(p, "belichtung", float(t.belichtung))
                shader.setzen(p, "nebel_farbe", tuple(t.nebel_farbe))
                shader.setzen(p, "nebel_dichte", float(t.nebel_dichte))

    def _strecke_hochladen(self) -> None:
        ctx = self.ctx
        t = self.thema
        breite = 2.0 * float(getattr(self.netz, "halbe_breite_m", 0.0) or 0.0)
        for band in self.netz.baender:
            uv = np.array(band.uv, dtype=np.float32, copy=True)
            textur = mr = None
            kachel = STRECKE_KACHEL_M
            rauheit, farbe = 0.9, BANDFARBEN.get(band.name, (0.5, 0.5, 0.5))
            ton = (1.0, 1.0, 1.0)
            if band.name == "fahrbahn":
                uv[:, 0] *= max(breite, 1.0)
                uv[:, 1] *= STRECKE_KACHEL_M
                if t is not None:
                    textur, mr = _textur_laden(ctx, self.texturordner, t.fahrbahn_textur, self._texturen)
                    kachel = t.fahrbahn_kachel_m
                farbe = (1.0, 1.0, 1.0) if textur else farbe
            elif band.name.startswith("randstein"):
                uv[:, 1] *= STRECKE_KACHEL_M
                if t is not None:
                    textur = _randsteintextur(ctx, t.randstein_farben)
                    self._eigene_texturen.append(textur)
                    kachel, rauheit, farbe = 4.0, 0.55, (1.0, 1.0, 1.0)
            elif band.name == "untergrund":
                band = self._grosser_boden()
                uv = band.uv
                if t is not None:
                    textur, mr = _textur_laden(ctx, self.texturordner, t.boden_textur, self._texturen)
                    kachel = t.boden_kachel_m
                    farbe = (1.0, 1.0, 1.0) if textur else t.boden_farbe
                    ton = tuple(t.boden_ton) if textur else (1.0, 1.0, 1.0)
            band_neu = type("B", (), {})()
            band_neu.positionen, band_neu.normalen = band.positionen, band.normalen
            band_neu.uv, band_neu.indizes = uv, band.indizes
            self.flaechen.append(_Flaeche(band_hochladen(ctx, self.programm, band_neu),
                                          farbe, textur, mr, kachel, 0.0, rauheit, ton))
        self._startlinie_hochladen()
        if t is not None:
            for s in begrenzung.bauen(self.netz, t.begrenzung):
                textur, mr = _textur_laden(ctx, self.texturordner, s.textur, self._texturen)
                self.flaechen.append(_Flaeche(
                    band_hochladen(ctx, self.programm, s),
                    (1.0, 1.0, 1.0) if textur else s.farbe, textur, mr, s.kachel_m,
                    s.metallic, s.rauheit))

    def _startlinie_hochladen(self) -> None:
        """Karierte Ziellinie über Punkt 0 und weiße Startplätze.

        Beides flach auf der Fahrbahn, einen halben Zentimeter darüber gegen
        Z-Fighting. Die Karos sind eine kleine Textur, die Startplätze ein
        einfarbiges Band.
        """
        from PIL import Image
        linie = np.asarray(self.netz.mittellinie, dtype=np.float64)
        halb = float(getattr(self.netz, "halbe_breite_m", 0.0) or 0.0)
        if len(linie) < 2 or halb <= 0:
            return
        t = linie[1] - linie[0]
        t /= max(np.linalg.norm(t), 1e-9)
        links = np.array([-t[1], t[0]])

        def quad(mitte, vor, quer, laenge, breite, uv_u, uv_v):
            ecken = [mitte - vor * laenge / 2 - quer * breite / 2, mitte + vor * laenge / 2 - quer * breite / 2,
                     mitte + vor * laenge / 2 + quer * breite / 2, mitte - vor * laenge / 2 + quer * breite / 2]
            pos = np.array([[e[0], e[1], 0.006] for e in ecken], dtype=np.float32)
            uv = np.array([[0, 0], [uv_u, 0], [uv_u, uv_v], [0, uv_v]], dtype=np.float32)
            return pos, uv

        b = type("B", (), {})()
        b.positionen, b.uv = quad(linie[0], t, links, 1.6, 2 * halb, 2.0, 2 * halb / 0.8)
        b.normalen = np.tile(np.array([[0, 0, 1]], dtype=np.float32), (4, 1))
        b.indizes = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.uint32)
        karo = np.zeros((2, 2, 3), dtype=np.uint8)
        karo[0, 0] = karo[1, 1] = 240
        karo[0, 1] = karo[1, 0] = 18
        textur = mesh.textur_hochladen(self.ctx, Image.fromarray(karo, "RGB"))
        textur.filter = (moderngl.NEAREST_MIPMAP_LINEAR, moderngl.NEAREST)
        self._eigene_texturen.append(textur)
        self.flaechen.append(_Flaeche(band_hochladen(self.ctx, self.programm, b),
                                      (1, 1, 1), textur, None, 1.0, 0.0, 0.6))

        # Startplätze: ein weißer Balken quer vor jedem Startplatz.
        pos_alle, idx_alle = [], []
        for (x, y, winkel) in getattr(self.netz, "start_positionen", []) or []:
            vor = np.array([np.cos(winkel), np.sin(winkel)])
            quer = np.array([-vor[1], vor[0]])
            mitte = np.array([x, y]) + vor * 2.9
            p, _uv = quad(mitte, vor, quer, 0.25, 2.6, 1, 1)
            basis = len(pos_alle) * 4
            pos_alle.append(p)
            idx_alle += [[basis, basis + 1, basis + 2], [basis, basis + 2, basis + 3]]
        if pos_alle:
            s = type("B", (), {})()
            s.positionen = np.vstack(pos_alle)
            s.uv = np.zeros((len(s.positionen), 2), dtype=np.float32)
            s.normalen = np.tile(np.array([[0, 0, 1]], dtype=np.float32), (len(s.positionen), 1))
            s.indizes = np.array(idx_alle, dtype=np.uint32)
            self.flaechen.append(_Flaeche(band_hochladen(self.ctx, self.programm, s),
                                          (0.92, 0.92, 0.9), None, None, 1.0, 0.0, 0.6))

    def _grosser_boden(self):
        """Ein Boden bis weit hinter die Kulisse, in Metern kachelnd."""
        linie = np.asarray(self.netz.mittellinie, dtype=np.float64)
        mitte = (linie.min(axis=0) + linie.max(axis=0)) / 2 if len(linie) else np.zeros(2)
        r = BODEN_RAND_M
        pos = np.array([[mitte[0] - r, mitte[1] - r, -0.01], [mitte[0] + r, mitte[1] - r, -0.01],
                        [mitte[0] + r, mitte[1] + r, -0.01], [mitte[0] - r, mitte[1] + r, -0.01]],
                       dtype=np.float32)
        b = type("B", (), {})()
        b.positionen = pos
        b.normalen = np.tile(np.array([[0, 0, 1]], dtype=np.float32), (4, 1))
        b.uv = pos[:, :2].copy()
        b.indizes = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.uint32)
        return b

    def _knoten_bauen(self, schluessel: str):
        fahrzeugmodell = self.speicher.holen(schluessel)
        return fahrzeugmodell.knoten() if fahrzeugmodell else None

    # -- Zeichnen --------------------------------------------------------
    def fortschreiben(self, staende) -> None:
        """Den Radzustand aller Fahrzeuge um ein Bild weiterdrehen.

        Getrennt von :meth:`zeichnen`, weil im Splitscreen zweimal gezeichnet
        wird und trotzdem nur einmal Zeit vergeht.
        """
        self.knotenspeicher.fortschreiben(staende)

    def zeichnen(self, mvp: np.ndarray, kamera_position, staende, fokus=None) -> None:
        """Ein Bild der Welt aus einer Kamera. Schreibt nichts fort."""
        staende = list(staende)
        fokus = kamera_position if fokus is None else fokus

        licht_mvp = np.eye(4, dtype=np.float32)
        if self.schattenkarte is not None:
            licht_mvp = self.schattenkarte.matrix(fokus, self.himmel.sonne)
            self._schattenkarte_zeichnen(staende, fokus)

        for p in (self.programm, self.programm_instanz):
            shader.matrix_setzen(p, "mvp", mvp)
            shader.matrix_setzen(p, "licht_mvp", licht_mvp)
            shader.setzen(p, "kamera_position", tuple(float(w) for w in kamera_position))
            shader.setzen(p, "hat_schatten", 1.0 if self.schattenkarte is not None else 0.0)
        self.himmel.binden(2)
        if self.schattenkarte is not None:
            self.schattenkarte.binden(3)
        else:
            self._leere_tiefe.use(3)

        self.himmel.zeichnen(mvp, kamera_position)
        self._strecke_zeichnen()
        if self.deko is not None:
            self.ctx.enable(moderngl.DEPTH_TEST)
            self.ctx.disable(moderngl.BLEND)
            self.deko.zeichnen(mvp, kamera_position, "farbe")
        self._schatten_zeichnen(mvp, staende)
        for stand in staende:
            if not stand.entfaerbt:
                self._fahrzeug_zeichnen(stand, durchsichtig=False)
        # Durchscheinendes zuletzt, von hinten nach vorn.
        auge = np.asarray(kamera_position, dtype=np.float64)[:2]
        reihe = sorted(staende, key=lambda s: -float(np.linalg.norm(np.asarray(s.pos_m)[:2] - auge)))
        for stand in reihe:
            if stand.entfaerbt:
                self._fahrzeug_zeichnen(stand, durchsichtig=None)
            else:
                self._fahrzeug_zeichnen(stand, durchsichtig=True)
        self.ctx.disable(moderngl.BLEND)
        self.ctx.depth_mask = True

    def _schattenkarte_zeichnen(self, staende, fokus) -> None:
        karte = self.schattenkarte
        vorher = karte.beginnen()
        try:
            p = karte.programm
            shader.setzen(p, "alpha_schwelle", 0.0)
            for stand in staende:
                if stand.entfaerbt:
                    continue
                fm = self.speicher.holen(stand.schluessel)
                if fm is None:
                    continue
                for name, m in self._teilmatrizen(stand, fm).items():
                    for vao in fm.schatten_vaos.get(name, ()):
                        shader.matrix_setzen(p, "modell", m)
                        vao.render()
            if self.deko is not None:
                self.deko.zeichnen(None, fokus, "schatten", fokus=fokus)
        finally:
            karte.beenden(vorher)

    def _flaeche_setzen(self, f: _Flaeche) -> None:
        p = self.programm
        shader.setzen(p, "grundton", tuple(f.farbe))
        shader.setzen(p, "hat_basisfarbe", 1.0 if f.textur is not None else 0.0)
        shader.setzen(p, "hat_metallic_rauheit", 1.0 if f.mr is not None else 0.0)
        shader.setzen(p, "metallic_faktor", f.metallic)
        shader.setzen(p, "rauheit_faktor", f.rauheit if f.mr is None else 1.0)
        shader.setzen(p, "uv_skala", 1.0 / max(f.kachel_m, 1e-3))
        shader.setzen(p, "farbton", tuple(f.ton))
        shader.setzen(p, "emission", (0.0, 0.0, 0.0))
        shader.setzen(p, "klarlack", 0.0)
        shader.setzen(p, "alpha_faktor", 1.0)
        shader.setzen(p, "alpha_schwelle", 0.0)
        if f.textur is not None:
            f.textur.use(0)
        if f.mr is not None:
            f.mr.use(1)

    def _strecke_zeichnen(self) -> None:
        self.ctx.enable(moderngl.DEPTH_TEST)
        self.ctx.disable(moderngl.BLEND)
        p = self.programm
        shader.setzen(p, "entfaerbung", 0.0)
        shader.setzen(p, "deckkraft", 1.0)
        shader.modell_setzen(p, matrix.einheit())
        for f in self.flaechen:
            self._flaeche_setzen(f)
            f.vao.render()
        shader.setzen(p, "uv_skala", 1.0)
        shader.setzen(p, "farbton", (1.0, 1.0, 1.0))

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

    def _teilmatrizen(self, stand: Fahrzeugstand, fm: Fahrzeugmodell) -> dict:
        knoten = self.knotenspeicher.knoten(stand.kennung)
        if knoten is not None:
            return knoten.matrizen(stand.pos_m, stand.gierwinkel_rad)
        # Ohne Radplätze bleibt das Fahrzeug ein Stück.
        grund = matrix.fahrzeug(stand.pos_m, stand.gierwinkel_rad)
        return {t.name: grund @ matrix.verschiebung(t.versatz) for t in fm.modell.teile}

    def _material_setzen(self, hm: mesh.HochgeladenesMaterial, lack: Lackwerte | None) -> None:
        lack_material_setzen(self.programm, hm, lack)

    def _fahrzeug_zeichnen(self, stand: Fahrzeugstand, durchsichtig) -> None:
        """``durchsichtig``: False = nur Deckendes, True = nur Glas, None = alles (Ghost)."""
        fahrzeugmodell = self.speicher.holen(stand.schluessel)
        if fahrzeugmodell is None:
            return
        modell = fahrzeugmodell.modell
        p = self.programm
        self.ctx.enable(moderngl.DEPTH_TEST)
        if stand.entfaerbt:
            self.ctx.enable(moderngl.BLEND)
            self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
            shader.setzen(p, "entfaerbung", GHOST_ENTFAERBUNG)
            shader.setzen(p, "deckkraft", GHOST_DECKKRAFT)
        elif durchsichtig:
            self.ctx.enable(moderngl.BLEND)
            self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
            self.ctx.depth_mask = False
            shader.setzen(p, "entfaerbung", 0.0)
            shader.setzen(p, "deckkraft", 1.0)
        else:
            self.ctx.disable(moderngl.BLEND)
            shader.setzen(p, "entfaerbung", 0.0)
            shader.setzen(p, "deckkraft", 1.0)
        shader.setzen(p, "uv_skala", 1.0)

        fahrzeugteile_zeichnen(p, modell, self._teilmatrizen(stand, fahrzeugmodell),
                               stand.lack, durchsichtig)

        self.ctx.depth_mask = True
        if stand.entfaerbt or durchsichtig:
            self.ctx.disable(moderngl.BLEND)
            shader.setzen(p, "entfaerbung", 0.0)
            shader.setzen(p, "deckkraft", 1.0)

    def freigeben(self) -> None:
        """Alle Puffer und Texturen zurückgeben."""
        dinge = [f.vao for f in self.flaechen]
        for textur, mr in self._texturen.values():
            dinge += [textur, mr]
        dinge += self._eigene_texturen
        for ding in dinge:
            if ding is None:
                continue
            try:
                ding.release()
            except Exception:                        # pragma: no cover - Treiber
                pass
        self.flaechen = []
        self._texturen = {}
        self._eigene_texturen = []
        if getattr(self, "deko", None) is not None:
            self.deko.freigeben()
        if getattr(self, "speicher", None) is not None:
            self.speicher.freigeben()
        for ding in (getattr(self, "himmel", None), getattr(self, "schattenkarte", None)):
            if ding is not None:
                ding.freigeben()
        if getattr(self, "schattenwerfer", None) is not None:
            self.schattenwerfer.freigeben()
        for ding in (getattr(self, "programm", None), getattr(self, "programm_instanz", None),
                     getattr(self, "_leere_tiefe", None)):
            if ding is not None:
                try:
                    ding.release()
                except Exception:                    # pragma: no cover - Treiber
                    pass
