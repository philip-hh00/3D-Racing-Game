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

from . import begrenzung, grafik, matrix, mesh, schatten, shader, track_mesh, vehicle_node
from .nachbearbeitung import Nachbearbeitung
from .reifenspuren import ERSATZRAEDER, Reifenspuren
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

#: Ein rotes und ein weißes Feld der Randsteine zusammen, Meter.
RANDSTEIN_KACHEL_M = 2.0


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
    #: Wie stark die Reifen rutschen, vorn und hinten, 0..1 (siehe
    #: ``reifenspuren.reifenschlupf``) — daraus werden Spuren und Rauch.
    schlupf_vorn: float = 0.0
    schlupf_hinten: float = 0.0


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
    #: ``<key>_lod1.glb``, wenn es daneben liegt: dieselben Knoten und
    #: Materialien mit halb so vielen Dreiecken, für ferne Autos.
    lod1: mesh.Modell | None = None

    def knoten(self) -> vehicle_node.Fahrzeugknoten | None:
        """Ein frischer Knoten für **ein** Fahrzeug dieses Typs."""
        if self.teile is None or not self.teile.plaetze:
            return None
        return vehicle_node.Fahrzeugknoten(self.teile.plaetze,
                                           self.teile.raddurchmesser_m)


def modell_nach_abstand(fm: Fahrzeugmodell, abstand_m: float,
                        ghost: bool = False) -> mesh.Modell:
    """Volles Modell oder LOD1, je nach Abstand zur Kamera.

    Die Grenze kommt aus ``grafik.fahrzeug_lod_m``. Der Ghost fährt immer
    voll: er ist durchsichtig, und im LOD1 fehlen Teile, durch die man bei
    ihm hindurchsieht.
    """
    if fm.lod1 is None or ghost or abstand_m < grafik.aktuell().fahrzeug_lod_m:
        return fm.modell
    return fm.lod1


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
        lod1_pfad = self.ordner / f"{echter}_lod1.glb"
        schattendaten = daten
        if lod1_pfad.is_file():
            lod1_daten = mesh.laden(lod1_pfad)
            fahrzeugmodell.lod1 = mesh.hochladen(self.ctx, self.programm, lod1_daten)
            # Die Schattenkarte sieht keine Radmuttern: das LOD1 reicht ihr.
            schattendaten = lod1_daten
        if self.tiefenprogramm is not None:
            # Eigene VAOs für die Schattenkarte: eine VAO gehört zu genau
            # einem Programm. Je Teil **ein** Netz aus allen Stücken — der
            # Schattenkarte ist das Material gleich, und 9 statt 38 Aufrufe je
            # Auto sparen bei acht Autos gut eine Millisekunde Python.
            for teil in schattendaten.teile:
                if not teil.stuecke:
                    continue
                vp = self.ctx.buffer(np.ascontiguousarray(teil.positionen, "f4").tobytes())
                vu = self.ctx.buffer(np.ascontiguousarray(teil.uv, "f4").tobytes())
                ib = self.ctx.buffer(np.ascontiguousarray(teil.indizes, "u4").tobytes())
                fahrzeugmodell.modell.puffer += [vp, vu, ib]
                fahrzeugmodell.schatten_vaos[teil.name] = [self.ctx.vertex_array(
                    self.tiefenprogramm, [(vp, "3f", "in_position"), (vu, "2f", "in_uv")], ib)]
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
            if fm.lod1 is not None:
                fm.lod1.freigeben()
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
    makro: float = 0.0
    #: Fahrbahn: Asphaltstufe für den Shader (0 aus, 1 einfach, 2 voll) und
    #: die Gummimaske; siehe den Block "Strang S" in ``shader.py``.
    asphalt: float = 0.0
    maske: object = None


#: Texturplatz der Gummimaske. 0–3 belegen Farbe, Rauheit, Himmel, Schatten.
MASKE_EINHEIT = 5


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


def randstein_bild(farben, laengs: int = 256, quer: int = 64) -> np.ndarray:
    """Rot-weiß im Wechsel, je Farbe eine halbe Kachel, mit Gebrauchsspuren.

    Zeilen laufen entlang der Strecke, Spalten quer von der Fahrbahnkante
    (u = 0) nach innen. Zur Fahrbahn hin liegt Gummi — dort fahren die Autos
    über den Stein —, zwischen den Feldern eine dunkle Fuge, und die Farbe
    ist nicht ganz gleichmäßig.
    """
    rng = np.random.default_rng(7)
    rot, weiss = (np.asarray(f, dtype=np.float64) for f in farben[:2])
    v = (np.arange(laengs) + 0.5) / laengs
    u = (np.arange(quer) + 0.5) / quer
    feld = np.where(v < 0.5, 0.0, 1.0)[:, None, None]
    bild = rot[None, None, :] * (1 - feld) + weiss[None, None, :] * feld
    bild = np.broadcast_to(bild, (laengs, quer, 3)).copy()
    # Fugen quer zur Fahrtrichtung.
    fuge = (np.minimum(np.abs(v - 0.5), np.minimum(v, 1 - v)) < 0.008)[:, None]
    bild[fuge[:, 0]] *= 0.35
    # Gummi innen, fleckig.
    flecken = rng.random((laengs // 8, quer // 8))
    flecken = np.kron(flecken, np.ones((8, 8)))[:laengs, :quer]
    gummi = np.clip((u[None, :] - 0.45) / 0.55, 0, 1) ** 1.5 * (0.35 + 0.4 * flecken)
    bild *= (1.0 - 0.55 * gummi)[:, :, None]
    bild *= (0.93 + 0.07 * rng.random((laengs, quer)))[:, :, None]
    return (np.clip(bild, 0, 1) * 255).astype(np.uint8)


def _randsteintextur(ctx, farben):
    from PIL import Image
    return mesh.textur_hochladen(ctx, Image.fromarray(randstein_bild(farben), "RGB"))


def _maske_hochladen(ctx, maske: np.ndarray):
    """Die Gummimaske (Zeilen längs, Spalten quer) als Einkanaltextur.

    Zeile 0 liegt bei v = 0 — roh hochgeladen, ohne das Spiegeln der Bilder.
    Längs kachelt sie (die Strecke ist geschlossen), quer nicht.
    """
    maske = np.ascontiguousarray(maske, dtype=np.uint8)
    textur = ctx.texture((maske.shape[1], maske.shape[0]), 1, maske.tobytes())
    textur.build_mipmaps()
    textur.repeat_x = False
    textur.repeat_y = True
    try:
        textur.anisotropy = 8.0
    except Exception:                                # pragma: no cover - Treiber
        pass
    return textur


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


def _zeichenplan(modell: mesh.Modell) -> dict:
    """Die Stücke eines Modells nach Material geordnet, einmal je Modell.

    ``{False: [(material, [(teilname, vao), …]), …], True: […]}`` — deckend
    und Glas getrennt. Ein Material wird so je Auto **einmal** gesetzt statt
    je Stück: vier Räder teilen sich Gummi, Felge und Bremse. Das halbiert die
    Materialwechsel, und die waren der größte Posten der Bildzeit.
    """
    plan = getattr(modell, "_zeichenplan", None)
    if plan is not None:
        return plan
    gruppen: dict = {}
    for teil in modell.teile:
        for st in teil.stuecke:
            hm = modell.materialien[st.material] if st.material < len(modell.materialien) else None
            glas = hm is not None and hm.daten.durchsichtig
            gruppen.setdefault((glas, st.material), (hm, []))[1].append((teil.name, st.vao))
    plan = {False: [], True: []}
    for (glas, _mi), eintrag in sorted(gruppen.items(), key=lambda e: e[0]):
        plan[glas].append(eintrag)
    try:
        modell._zeichenplan = plan
    except AttributeError:                           # pragma: no cover - Attrappen
        pass
    return plan


def fahrzeugteile_zeichnen(p, modell: mesh.Modell, matrizen: dict,
                           lack: Lackwerte | None, durchsichtig) -> None:
    """Alle Teile eines Fahrzeugs an ihren Matrizen zeichnen.

    ``durchsichtig``: False = nur Deckendes, True = nur Glas, None = alles.
    Den Mischmodus stellt der Aufrufer ein.

    Die Matrizen eines Fahrzeugs sind **starr** (Drehung und Verschiebung,
    keine Skalierung) — dann ist die Normalmatrix der Drehteil selbst, und die
    Inverse je Teil entfällt.
    """
    plan = _zeichenplan(modell)
    if durchsichtig is None:
        gruppen = plan[False] + plan[True]
    else:
        gruppen = plan[bool(durchsichtig)]
    if not gruppen:
        return
    u_modell = p["modell"]
    u_normale = p.get("normalmatrix", None)
    bytes_je_teil: dict = {}
    zuletzt = None
    for hm, eintraege in gruppen:
        material_gesetzt = False
        for name, vao in eintraege:
            m = matrizen.get(name)
            if m is None:
                continue
            if not material_gesetzt:
                if hm is not None:
                    lack_material_setzen(p, hm, lack)
                material_gesetzt = True
            if name != zuletzt:
                b = bytes_je_teil.get(name)
                if b is None:
                    m4 = np.asarray(m, dtype=np.float32)
                    b = bytes_je_teil[name] = (np.ascontiguousarray(m4.T).tobytes(),
                                               np.ascontiguousarray(m4[:3, :3].T).tobytes())
                u_modell.write(b[0])
                if u_normale is not None:
                    u_normale.write(b[1])
                zuletzt = name
            vao.render()


# ---------------------------------------------------------------------------
# Die Szene
# ---------------------------------------------------------------------------

def _im_bild(mvp: np.ndarray, pos_m, radius_m: float = 3.5) -> bool:
    """Ob eine Kugel um ein Fahrzeug im Sichtkegel liegen kann (großzügig)."""
    p = np.asarray(pos_m, dtype=np.float64)
    c = np.asarray(mvp, dtype=np.float64) @ np.array([p[0], p[1], p[2] + 0.7, 1.0])
    r = radius_m * 2.0
    return bool(c[3] > -r and abs(c[0]) < c[3] + r and abs(c[1]) < c[3] + r)


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
        self.nachbearbeitung: Nachbearbeitung | None = None
        self.reifenspuren: Reifenspuren | None = None
        # Gelände und Gras (Strang W); ohne Thema bleibt der flache Boden.
        self.gelaende = None
        self.gelaendezeichner = None
        self.graszeichner = None
        self.fernwald = None
        self._radplaetze: dict = {}
        #: Belichtung des Themas; angewendet in der Nachbearbeitung.
        self.belichtung = 1.0
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
        self.nachbearbeitung = Nachbearbeitung(ctx)
        self.reifenspuren = Reifenspuren(ctx)
        if self.schattenwurf_an:
            try:
                self.schattenkarte = licht.Schattenkarte(
                    ctx, licht.schattenkarte_groesse(grafik.aktuell().schatten_px))
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

        yield 0.08, "Gelände"
        self._gelaende_bauen()

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
                self.belichtung = float(t.belichtung)
                shader.setzen(p, "nebel_farbe", tuple(t.nebel_farbe))
                shader.setzen(p, "nebel_dichte", float(t.nebel_dichte))
        if self.reifenspuren is not None:
            # Rauch ist hell und matt: grob Sonne von schräg plus Himmel.
            sonne = np.asarray(t.sonne_farbe if t is not None else shader.SONNE_FARBE, dtype=float)
            himmel = np.asarray(t.himmel_horizont if t is not None else shader.HIMMEL_HORIZONT, dtype=float)
            self.reifenspuren.rauch_farbe = tuple(float(c) for c in 0.72 * (sonne * 0.2 + himmel * 0.75))

    def _strecke_hochladen(self) -> None:
        ctx = self.ctx
        t = self.thema
        breite = 2.0 * float(getattr(self.netz, "halbe_breite_m", 0.0) or 0.0)
        for band in self.netz.baender:
            name = band.name
            uv = np.array(band.uv, dtype=np.float32, copy=True)
            textur = mr = None
            kachel = STRECKE_KACHEL_M
            rauheit, farbe = 0.9, BANDFARBEN.get(band.name, (0.5, 0.5, 0.5))
            ton = (1.0, 1.0, 1.0)
            asphalt, maske = 0.0, None
            if band.name == "fahrbahn":
                # uv in Metern: quer ab der linken Kante, längs die Bogenlänge.
                uv[:, 0] *= max(breite, 1.0)
                uv[:, 1] *= STRECKE_KACHEL_M
                if t is not None:
                    textur, mr = _textur_laden(ctx, self.texturordner, t.fahrbahn_textur, self._texturen)
                    kachel = t.fahrbahn_kachel_m
                    ton = tuple(t.fahrbahn_ton)
                farbe = (1.0, 1.0, 1.0) if textur else farbe
                asphalt = 1.0 if grafik.aktuell().strecken_details <= 0 else 2.0
                maske = _maske_hochladen(ctx, track_mesh.gummi_maske(self.netz))
                self._eigene_texturen.append(maske)
            elif band.name.startswith("randstein"):
                # uv: quer 0..1 von der Kante nach innen, längs in Metern. Die
                # Kachel gilt für beide Richtungen — quer deshalb vorab
                # strecken, damit die ganze Breite genau eine Textur ist.
                kachel = RANDSTEIN_KACHEL_M
                uv[:, 0] *= kachel
                if t is not None:
                    textur = _randsteintextur(ctx, t.randstein_farben)
                    self._eigene_texturen.append(textur)
                    rauheit, farbe = 0.55, (1.0, 1.0, 1.0)
            elif band.name == "untergrund":
                if self.gelaendezeichner is not None:
                    continue            # das Gelände ist der Boden (Strang W)
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
            makro = {"untergrund": 0.28, "fahrbahn": 0.08}.get(name, 0.0)
            self.flaechen.append(_Flaeche(band_hochladen(ctx, self.programm, band_neu),
                                          farbe, textur, mr, kachel, 0.0, rauheit, ton, makro,
                                          asphalt, maske))
        self._auslauf_hochladen()
        self._startlinie_hochladen()
        if t is not None:
            for s in begrenzung.bauen(self.netz, t.begrenzung):
                textur, mr = _textur_laden(ctx, self.texturordner, s.textur, self._texturen)
                self.flaechen.append(_Flaeche(
                    band_hochladen(ctx, self.programm, s),
                    (1.0, 1.0, 1.0) if textur else s.farbe, textur, mr, s.kachel_m,
                    s.metallic, s.rauheit))

    def _auslauf_hochladen(self) -> None:
        """Kiesbetten, Sand- oder Asphaltauslauf außen an den Kurven (Strang S)."""
        t = self.thema
        art = getattr(t, "auslauf", None) if t is not None else None
        if art is None or art.breite_m <= 0:
            return
        textur, mr = _textur_laden(self.ctx, self.texturordner, art.textur, self._texturen)
        for band in track_mesh.auslauf_baender(self.netz, art.breite_m):
            self.flaechen.append(_Flaeche(
                band_hochladen(self.ctx, self.programm, band),
                (1.0, 1.0, 1.0) if textur else (0.55, 0.52, 0.47), textur, mr, art.kachel_m,
                0.0, art.rauheit, tuple(art.ton), 0.22))

    def _startlinie_hochladen(self) -> None:
        """Weiße Startplätze, flach einen halben Zentimeter über der Fahrbahn.

        Die karierte Ziellinie über Punkt 0 malt der Asphalt-Shader selbst
        (Block "Strang S" in ``shader.py``) — in der Fahrbahn statt darüber,
        also ohne Z-Fighting in der Ferne.
        """
        linie = np.asarray(self.netz.mittellinie, dtype=np.float64)
        halb = float(getattr(self.netz, "halbe_breite_m", 0.0) or 0.0)
        if len(linie) < 2 or halb <= 0:
            return

        def quad(mitte, vor, quer, laenge, breite, uv_u, uv_v):
            ecken = [mitte - vor * laenge / 2 - quer * breite / 2, mitte + vor * laenge / 2 - quer * breite / 2,
                     mitte + vor * laenge / 2 + quer * breite / 2, mitte - vor * laenge / 2 + quer * breite / 2]
            pos = np.array([[e[0], e[1], 0.006] for e in ecken], dtype=np.float32)
            uv = np.array([[0, 0], [uv_u, 0], [uv_u, uv_v], [0, uv_v]], dtype=np.float32)
            return pos, uv

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

    # -- Gelände (Strang W) ------------------------------------------------
    def _gelaende_bauen(self) -> None:
        """Höhenfeld, Netz und Gras; Deko und Kulisse auf den Boden setzen.

        Ohne Thema (Tests, Werkstatt) bleibt der flache große Boden.
        """
        t = self.thema
        art = getattr(t, "gelaende", None) if t is not None else None
        if art is None:
            return
        from . import gelaende, platzierung
        einstellung = grafik.aktuell()
        name = getattr(self.netz, "name", "") or "strecke"
        auslauf = float(getattr(getattr(t, "auslauf", None), "breite_m", 0.0) or 0.0)
        gel = gelaende.Gelaende(self.netz.mittellinie, self.netz.halbe_breite_m, art, name,
                                rand_arten=t.rand, auslauf_m=auslauf,
                                detail=einstellung.gelaende_detail)
        orte = platzierung.ausduennen(self.platzierungen, t, einstellung.deko_dichte, name)
        self.platzierungen = platzierung.hoehen_setzen(orte, gel, t)
        texturen = {}
        for schluessel, schicht, ersatz in (("gelaende_unten", art.unten, t.boden_farbe),
                                            ("gelaende_hang", art.hang, (0.45, 0.42, 0.36)),
                                            ("gelaende_fels", art.fels, (0.42, 0.40, 0.38))):
            farbe, _mr = _textur_laden(self.ctx, self.texturordner, schicht.textur, self._texturen)
            if farbe is None:
                from PIL import Image
                pixel = np.full((1, 1, 3), np.asarray(ersatz) * 255, dtype=np.uint8)
                farbe = mesh.textur_hochladen(self.ctx, Image.fromarray(pixel, "RGB"))
                self._eigene_texturen.append(farbe)
            texturen[schluessel] = farbe
        schattenprogramm = self.schattenkarte.programm if self.schattenkarte else None
        self.gelaendezeichner = gelaende.Gelaendezeichner(self.ctx, self.programm, schattenprogramm,
                                                          gel, texturen)
        self.gelaende = gel
        if art.wald_farbe is not None and art.fernwald_je_ha > 0:
            # Quadratisch: auf Niedrig (0,4) bleibt ein Sechstel — Kegel sind billig,
            # aber tausende davon nicht für eine Einsteigerkarte.
            wald = gelaende.fernwald_platzieren(gel, name, einstellung.deko_dichte ** 2)
            if len(wald.pos):
                self.fernwald = gelaende.Fernwaldzeichner(self.ctx, self.programm_instanz, wald,
                                                          art.wald_farbe)
        stufe = int(einstellung.gras)
        if t.gras.an and stufe > 0:
            feld = gelaende.gras_platzieren(
                gel, t.gras, stufe, name,
                platzierung.grasfreie_flaechen(self.platzierungen, t, self._modellgrenzen(t)))
            if len(feld.pos):
                boden = None
                if self.texturordner is not None:
                    boden = gelaende.mittlere_farbe(
                        self.texturordner / f"{art.unten.textur}_farbe.jpg", art.unten.ton)
                self.graszeichner = gelaende.Graszeichner(
                    self.ctx, self.programm_instanz, feld, t.gras, gel.keim,
                    gelaende.GRAS_WEITE_M.get(stufe, 60.0), boden)

    def _modellgrenzen(self, t) -> dict:
        """Grundriss der großen Rand- und Hausmodelle, ``(x_min, x_max, y_min, y_max)``.

        Nur für die, die Gras sperren (Platzbedarf ab 4 m); aus dem GLB, weil
        ein Vorplatz nicht im Katalog steht.
        """
        if self.umgebungsordner is None:
            return {}
        namen = {n for a in list(t.rand) + [d for d in t.deko if d.flach] if a.radius_m >= 4.0
                 for n in a.modell.split("|")}
        grenzen = {}
        for n in namen:
            pfad = self.umgebungsordner / f"{n}.glb"
            if not pfad.is_file():
                continue
            daten = mesh.laden(pfad)
            punkte = [s.positionen[:, :2] + np.asarray(teil.versatz)[:2]
                      for teil in daten.teile for s in teil.stuecke]
            if punkte:
                p = np.concatenate(punkte)
                grenzen[n] = (float(p[:, 0].min()), float(p[:, 0].max()),
                              float(p[:, 1].min()), float(p[:, 1].max()))
        return grenzen

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

    def ampel_setzen(self, hell: float) -> None:
        """Startampel an (1) oder aus (0)."""
        if self.deko is not None:
            self.deko.ampel = float(hell)

    def _knoten_bauen(self, schluessel: str):
        fahrzeugmodell = self.speicher.holen(schluessel)
        return fahrzeugmodell.knoten() if fahrzeugmodell else None

    # -- Zeichnen --------------------------------------------------------
    def fortschreiben(self, staende, dt: float | None = None) -> None:
        """Den Radzustand aller Fahrzeuge um ein Bild weiterdrehen.

        Getrennt von :meth:`zeichnen`, weil im Splitscreen zweimal gezeichnet
        wird und trotzdem nur einmal Zeit vergeht. ``dt`` (Sekunden) braucht
        der Reifenrauch; ohne wird die Uhr gelesen.
        """
        self.knotenspeicher.fortschreiben(staende)
        if self.reifenspuren is not None:
            if grafik.aktuell().reifenspuren:
                self.reifenspuren.fortschreiben(staende, self._raeder_von, dt)
            elif self.reifenspuren.belegt or self.reifenspuren.teilchen_aktiv:
                self.reifenspuren.leeren()

    def _raeder_von(self, stand: Fahrzeugstand):
        """Radplätze ``(x, y, hinten)`` eines Fahrzeugs, je Schlüssel gemerkt."""
        plaetze = self._radplaetze.get(stand.schluessel)
        if plaetze is None:
            fm = self.speicher.holen(stand.schluessel)
            teile = fm.teile if fm is not None else None
            if teile is not None and teile.plaetze:
                plaetze = tuple((float(r.nabe[0]), float(r.nabe[1]), float(r.nabe[0]) < 0.0)
                                for r in teile.plaetze)
            else:
                plaetze = ERSATZRAEDER
            self._radplaetze[stand.schluessel] = plaetze
        return plaetze

    def zeichnen(self, mvp: np.ndarray, kamera_position, staende, fokus=None) -> None:
        """Ein Bild der Welt aus einer Kamera. Schreibt nichts fort.

        Ziel ist, was gerade gebunden ist, im gesetzten Ausschnitt: die Welt
        entsteht als lineares HDR im Zwischenpuffer der Nachbearbeitung und
        wird erst am Ende abgebildet und dorthin geschrieben.
        """
        staende = list(staende)
        fokus = kamera_position if fokus is None else fokus
        self._bild_nummer = getattr(self, "_bild_nummer", 0) + 1
        einstellung = grafik.aktuell()

        # Schattenkarte: Größe nach der Grafikstufe, 0 heißt ohne.
        karte = self.schattenkarte if einstellung.schatten_px > 0 else None
        if karte is not None:
            karte.groesse_setzen(einstellung.schatten_px)
        licht_mvp = np.eye(4, dtype=np.float32)
        if karte is not None:
            licht_mvp = karte.matrix(fokus, self.himmel.sonne)
            self._schattenkarte_zeichnen(staende, fokus)

        self.nachbearbeitung.beginnen(mvp, kamera_position, einstellung)

        for p in (self.programm, self.programm_instanz):
            shader.matrix_setzen(p, "mvp", mvp)
            shader.matrix_setzen(p, "licht_mvp", licht_mvp)
            shader.setzen(p, "kamera_position", tuple(float(w) for w in kamera_position))
            shader.setzen(p, "hat_schatten", 1.0 if karte is not None else 0.0)
        self.himmel.binden(2)
        if karte is not None:
            karte.binden(3)
        else:
            self._leere_tiefe.use(3)

        # Deckendes von nah nach fern: was verdeckt ist, verwirft der
        # Tiefentest, bevor der teure Fragment-Shader läuft. In der
        # Startaufstellung füllen acht Autos das halbe Bild — in der alten
        # Reihenfolge (Boden, Umgebung, dann Autos) wurde jedes Pixel dort
        # drei- bis viermal voll schattiert. Himmel ganz zuletzt, nur wo
        # noch nichts steht.
        auge = np.asarray(kamera_position, dtype=np.float64)[:2]
        self._auge = auge            # für die Wahl zwischen vollem Modell und LOD1
        # Nur, was im Bild sein kann: in der Startaufstellung stehen sieben von
        # acht Autos hinter der Kamera, und jedes kostet gut hundert Aufrufe.
        sichtbar = [s for s in staende if _im_bild(mvp, s.pos_m)]
        nach_abstand = sorted(sichtbar, key=lambda s: float(np.linalg.norm(np.asarray(s.pos_m)[:2] - auge)))
        for stand in nach_abstand:
            if not stand.entfaerbt:
                self._fahrzeug_zeichnen(stand, durchsichtig=False)
        if self.graszeichner is not None:
            self.ctx.enable(moderngl.DEPTH_TEST)
            self.ctx.disable(moderngl.BLEND)
            self.graszeichner.zeichnen(mvp, kamera_position)
        if self.deko is not None:
            self.ctx.enable(moderngl.DEPTH_TEST)
            self.ctx.disable(moderngl.BLEND)
            self.deko.zeichnen(mvp, kamera_position, "farbe")
        if self.fernwald is not None:
            self.fernwald.zeichnen()
        self._strecke_zeichnen()
        self.himmel.zeichnen(mvp, kamera_position)
        spuren = self.reifenspuren is not None and einstellung.reifenspuren
        if spuren:
            self.reifenspuren.spuren_zeichnen(mvp)
        self._schatten_zeichnen(mvp, staende)
        # Durchscheinendes zuletzt, von hinten nach vorn.
        reihe = list(reversed(nach_abstand))
        for stand in reihe:
            if stand.entfaerbt:
                self._fahrzeug_zeichnen(stand, durchsichtig=None)
            else:
                self._fahrzeug_zeichnen(stand, durchsichtig=True)
        self.ctx.disable(moderngl.BLEND)
        self.ctx.depth_mask = True
        if spuren and self.reifenspuren.teilchen_aktiv:
            _farbe, tiefe = self.nachbearbeitung.aufloesen()
            self.reifenspuren.rauch_zeichnen(self.nachbearbeitung.vp_relativ, kamera_position,
                                             tiefe, self.nachbearbeitung.groesse)
        self.nachbearbeitung.abschliessen(self.belichtung)

    def _schattenkarte_zeichnen(self, staende, fokus) -> None:
        karte = self.schattenkarte
        if karte.statisch_neu:
            # Was sich nicht bewegt, nur wenn die ruhende Karte neu gemittelt
            # wurde (siehe licht.Schattenkarte).
            vorher = karte.statisch_beginnen()
            try:
                if self.deko is not None:
                    self.deko.zeichnen(None, fokus, "schatten", fokus=fokus)
                if self.gelaendezeichner is not None:
                    self.gelaendezeichner.schatten_zeichnen(karte.programm)
            finally:
                karte.beenden(vorher)
        vorher = karte.beginnen()
        try:
            p = karte.programm
            shader.setzen(p, "alpha_schwelle", 0.0)
            reichweite = karte.halbe_breite * 1.5 + 5.0
            f = np.asarray(fokus, dtype=np.float64)[:2]
            for stand in staende:
                if stand.entfaerbt:
                    continue
                if float(np.hypot(*(np.asarray(stand.pos_m, dtype=np.float64)[:2] - f))) > reichweite:
                    continue
                fm = self.speicher.holen(stand.schluessel)
                if fm is None:
                    continue
                for name, m in self._teilmatrizen(stand, fm).items():
                    vaos = fm.schatten_vaos.get(name)
                    if not vaos:
                        continue
                    shader.matrix_setzen(p, "modell", m)
                    for vao in vaos:
                        vao.render()
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
        shader.setzen(p, "makro", f.makro)
        shader.setzen(p, "emission", (0.0, 0.0, 0.0))
        shader.setzen(p, "klarlack", 0.0)
        shader.setzen(p, "alpha_faktor", 1.0)
        shader.setzen(p, "alpha_schwelle", 0.0)
        shader.setzen(p, "asphalt", float(f.asphalt))
        if f.asphalt > 0 and f.maske is not None:
            self._asphalt_setzen(p)
            f.maske.use(MASKE_EINHEIT)
        if f.textur is not None:
            f.textur.use(0)
        if f.mr is not None:
            f.mr.use(1)

    def _asphalt_setzen(self, p) -> None:
        """Maße und Linien der Fahrbahn für den Asphalt-Block im Shader."""
        t = self.thema
        breite = 2.0 * float(getattr(self.netz, "halbe_breite_m", 0.0) or 0.0)
        shader.setzen(p, "strecken_maske", MASKE_EINHEIT)
        shader.setzen(p, "strecke_mass", (max(breite, 1.0), max(float(self.netz.laenge_m), 1.0)))
        if t is not None:
            linien = (float(t.randlinie_m), float(t.linienbreite_m),
                      1.0 if t.mittellinie else 0.0, float(t.linien_gelb))
        else:
            linien = (1.1, 0.2, 0.0, 0.0)
        shader.setzen(p, "strecke_linien", linien)

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
        if self.gelaendezeichner is not None:
            shader.setzen(p, "asphalt", 0.0)
            self.gelaendezeichner.zeichnen()
        shader.setzen(p, "uv_skala", 1.0)
        shader.setzen(p, "farbton", (1.0, 1.0, 1.0))
        shader.setzen(p, "makro", 0.0)

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
        """Matrizen je Teil — einmal je Bild und Fahrzeug gerechnet.

        Gebraucht werden sie dreimal: Schattenkarte, Deckendes, Glas. Jedes
        Mal neu gerechnet waren das bei acht Autos rund 7 ms je Bild.
        """
        schluessel = (stand.kennung, id(stand))
        vorrat = getattr(self, "_matrizen_vorrat", None)
        if vorrat is None or vorrat[0] != self._bild_nummer:
            vorrat = self._matrizen_vorrat = (self._bild_nummer, {})
        if schluessel not in vorrat[1]:
            vorrat[1][schluessel] = self._teilmatrizen_rechnen(stand, fm)
        return vorrat[1][schluessel]

    def _teilmatrizen_rechnen(self, stand: Fahrzeugstand, fm: Fahrzeugmodell) -> dict:
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
        auge = getattr(self, "_auge", None)
        abstand = 0.0 if auge is None else float(
            np.hypot(*(np.asarray(stand.pos_m, dtype=np.float64)[:2] - auge)))
        modell = modell_nach_abstand(fahrzeugmodell, abstand, ghost=stand.entfaerbt)
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
        for ding in (getattr(self, "gelaendezeichner", None), getattr(self, "graszeichner", None),
                     getattr(self, "fernwald", None)):
            if ding is not None:
                ding.freigeben()
        self.gelaendezeichner = self.graszeichner = self.fernwald = None
        if getattr(self, "speicher", None) is not None:
            self.speicher.freigeben()
        for ding in (getattr(self, "himmel", None), getattr(self, "schattenkarte", None)):
            if ding is not None:
                ding.freigeben()
        if getattr(self, "schattenwerfer", None) is not None:
            self.schattenwerfer.freigeben()
        if getattr(self, "nachbearbeitung", None) is not None:
            self.nachbearbeitung.freigeben()
            self.nachbearbeitung = None
        if getattr(self, "reifenspuren", None) is not None:
            self.reifenspuren.freigeben()
            self.reifenspuren = None
        for ding in (getattr(self, "programm", None), getattr(self, "programm_instanz", None),
                     getattr(self, "_leere_tiefe", None)):
            if ding is not None:
                try:
                    ding.release()
                except Exception:                    # pragma: no cover - Treiber
                    pass
