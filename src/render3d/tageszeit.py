"""Tageszeit je Rennen: Tag, Abend, Nacht.

Nur Zahlen und numpy — kein OpenGL, kein pygame (siehe ``VEREINBARUNGEN.md``).
Die Rennszene liest hier, wie die Welt zu einer Tageszeit aussieht, und gibt
es an den Shader weiter.

**Tag ist die heutige Welt.** Die Vorgabe ``TAG`` ändert nichts: Sonne,
Himmel, Nebel, Belichtung kommen unverändert aus dem Thema und dem
Himmelsbild, der Shader läuft an allen Tageszeit-Zweigen vorbei. Wer hier
etwas für den Tag „verbessert“, verändert jedes Bild — deshalb prüft
``tests/test_render3d_tageszeit.py`` die Vorgabe gegen die alten Werte.

**Abend.** Tiefe, warme Sonne (Schatten fallen lang), das Himmelsbild des
Themas wird so verbogen, dass seine Sonne am neuen Ort steht, und zum
Horizont hin orange, nach oben blauviolett getönt. Etwas weniger Belichtung.

**Nacht.** Das Himmelsbild bleibt als Wolkenstruktur, aber sehr dunkel und
blau, dazu Sterne und ein Mond. Der Mond ist die „Sonne“ des Schattens:
kühles, schwaches Licht aus mittlerer Höhe, die Schattenkarte folgt ihm.
Dazu kommen lokale Lichter (Scheinwerfer als Kegel, Rücklichter, Lampen),
die der Shader als Feld aus höchstens :data:`shader.MAX_LICHTER` Einträgen
liest. Je Bild wählt :func:`lichter_waehlen` die ``n`` wichtigsten.

Die Rechnungen hier sind rein; die Schalter (``grafik.lichter_max``) und das
Hochladen stehen in ``rennszene.py``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

#: Die Tageszeiten, wie sie in Lobby, Profil und Lobbyeinstellungen heißen
#: (Schlüssel, deutsch — übersetzt wird erst bei der Anzeige).
NAMEN = ("Tag", "Abend", "Nacht")
STANDARD = "Tag"
#: Schlüssel in den Lobbyeinstellungen und im Profil.
SCHLUESSEL = "tageszeit"

_ALIASE = {"tag": "Tag", "day": "Tag", "abend": "Abend", "dusk": "Abend", "evening": "Abend",
           "sunset": "Abend", "nacht": "Nacht", "night": "Nacht"}


def normiere(name) -> str:
    """Eine Tageszeit aus beliebiger Eingabe; unbekannt oder fehlend ist ``"Tag"``.

    Eine Lobby von vor 1.1.0 kennt das Feld nicht, ein Server reicht
    Unbekanntes nie weiter, und ein Profil kann von Hand verbogen sein: in
    allen Fällen kommt der Tag heraus, nie ein Fehler.
    """
    if isinstance(name, str):
        return _ALIASE.get(name.strip().lower(), STANDARD)
    return STANDARD


@dataclass(frozen=True)
class Tageszeit:
    name: str
    #: Höhe der Sonne (des Mondes) über dem Horizont, Grad; ``None``: so, wie
    #: das Himmelsbild sie hat (Tag).
    sonne_hoehe_grad: float | None = None
    #: Faktor auf ``thema.sonne_farbe`` (Farbe und Stärke).
    sonne_faktor: tuple = (1.0, 1.0, 1.0)
    #: Faktor auf ``himmel_helligkeit`` des Themas.
    himmel_helligkeit: float = 1.0
    #: Tönung des Himmels im Zenit und am Horizont zur Sonne hin; ``glut`` =
    #: (Abfall mit der Höhe, Anteil abseits der Sonne).
    tint_oben: tuple = (1.0, 1.0, 1.0)
    tint_horizont: tuple = (1.0, 1.0, 1.0)
    glut: tuple = (1.0, 1.0)
    #: Faktoren auf Nebelfarbe, Bodenfarbe und den Farbverlauf des Themas.
    nebel_faktor: tuple = (1.0, 1.0, 1.0)
    boden_faktor: tuple = (1.0, 1.0, 1.0)
    verlauf_faktor: tuple = (1.0, 1.0, 1.0)
    nebel_dichte: float = 1.0
    #: Faktor auf die Belichtung des Themas (die Kamera gleicht Nacht aus).
    belichtung: float = 1.0
    #: Schattenversatz im Shader: (konstant, je Neigung). Bei tiefer Sonne
    #: kleiner, sonst fehlt der Anfang jedes Schattens.
    schatten_bias: tuple = (0.0006, 0.0025)
    sterne: float = 0.0
    #: Sonnen- oder Mondscheibe im Himmel: rgb und Stärke.
    scheibe: tuple = (1.0, 0.95, 0.85, 1.0)
    #: Scheinwerfer, Rücklichter und Lampen an.
    lichter: bool = False
    #: Wie sehr die Leuchten der Fahrzeuge glühen (Faktor auf deren Emission).
    vorn_leuchten: float = 1.0
    hinten_leuchten: float = 1.0
    #: Lampenköpfe der Straßenlaternen und Masten (Emission); 0 aus.
    lampen_leuchten: float = 0.0

    @property
    def aktiv(self) -> bool:
        """Falsch nur für den Tag: dann bleibt alles beim Alten."""
        return self.name != STANDARD


TAG = Tageszeit(name="Tag")

ABEND = Tageszeit(
    name="Abend",
    sonne_hoehe_grad=9.0,
    sonne_faktor=(1.55, 0.78, 0.36),
    himmel_helligkeit=0.62,
    tint_oben=(0.55, 0.66, 1.05),
    tint_horizont=(2.3, 1.05, 0.5),
    glut=(5.5, 0.35),
    nebel_faktor=(1.25, 0.72, 0.5),
    boden_faktor=(0.8, 0.58, 0.45),
    verlauf_faktor=(1.0, 0.8, 0.7),
    nebel_dichte=1.0,
    belichtung=1.0,
    schatten_bias=(0.00035, 0.0011),
    scheibe=(1.0, 0.62, 0.3, 1.1),
)

NACHT = Tageszeit(
    name="Nacht",
    sonne_hoehe_grad=38.0,
    sonne_faktor=(0.075, 0.115, 0.2),
    himmel_helligkeit=0.05,
    tint_oben=(0.45, 0.66, 1.5),
    tint_horizont=(0.7, 0.85, 1.4),
    glut=(2.5, 0.9),
    nebel_faktor=(0.04, 0.06, 0.11),
    boden_faktor=(0.05, 0.07, 0.11),
    verlauf_faktor=(0.04, 0.07, 0.14),
    nebel_dichte=0.8,
    belichtung=2.4,
    sterne=1.0,
    scheibe=(0.78, 0.86, 1.0, 0.55),
    lichter=True,
    vorn_leuchten=3.0,
    hinten_leuchten=1.6,
    lampen_leuchten=7.0,
)

VORGABEN = {"Tag": TAG, "Abend": ABEND, "Nacht": NACHT}


def vorgabe(name) -> Tageszeit:
    """Die Vorgabe zu einem Namen (mit :func:`normiere`)."""
    return VORGABEN[normiere(name)]


def sonne_richtung(tz: Tageszeit, himmel_sonne) -> np.ndarray:
    """Richtung **zur** Sonne (zum Mond), normiert.

    Der Himmel des Themas gibt die Himmelsrichtung vor (Schatten und
    Himmelsbild sollen zusammenpassen), die Tageszeit die Höhe. Der Tag
    liefert die Richtung des Himmelsbildes unverändert zurück.
    """
    s = np.asarray(himmel_sonne, dtype=np.float64)
    s = s / np.linalg.norm(s)
    if tz.sonne_hoehe_grad is None:
        return s
    az = math.atan2(s[1], s[0])
    h = math.radians(tz.sonne_hoehe_grad)
    return np.array([math.cos(h) * math.cos(az), math.cos(h) * math.sin(az), math.sin(h)])


def himmel_schalter(tz: Tageszeit) -> tuple[float, float, float, float]:
    """``tz_himmel`` für den Shader: (an, -, -, Sterne). Der Tag ist ganz aus."""
    if not tz.aktiv:
        return (0.0, 0.0, 0.0, 0.0)
    return (1.0, 0.0, 0.0, float(tz.sterne))


def _hoehe_der_zeilen(hoehe_px: int) -> np.ndarray:
    """Höhenwinkel (Bogenmaß) der Bildzeilen eines Equirectangular-Bildes, Zeile 0 oben."""
    return (0.5 - (np.arange(hoehe_px) + 0.5) / hoehe_px) * math.pi


def himmel_bild(bild_u8: np.ndarray, tz: Tageszeit, himmel_sonne) -> np.ndarray:
    """Das Himmelsbild für eine Tageszeit: verbogen und getönt, einmal beim Laden.

    ``bild_u8``: ``(h, w, 3)`` sRGB-Bytes eines Equirectangular-Bildes (Zeile 0
    oben, wie PIL sie liefert). Ergebnis: ``(h, w, 3)`` float32 **in derselben
    Kodierung** (linear hoch 1/2,2, Werte über 1 erlaubt) — der Shader liest es
    wie das Original (``nach_linear``) und multipliziert ``himmel_helligkeit``
    darauf. Es kostet damit im Bild nichts, was der Tag nicht auch kostet.

    *Verbogen:* nur der Höhenwinkel, stückweise linear, so dass die Sonne des
    Bildes auf die Höhe der Tageszeit rückt; Horizont und Zenit bleiben. Die
    Wolken werden dabei zum Horizont hin gestaucht, was dem Abend steht.
    *Getönt:* ``tint_oben`` im Zenit, ``tint_horizont`` am Horizont, dort
    stärker zur Sonne hin (``glut``).
    """
    lin = (np.asarray(bild_u8, dtype=np.float32) / 255.0) ** 2.2
    h, w = lin.shape[:2]
    e = _hoehe_der_zeilen(h)
    if tz.sonne_hoehe_grad is not None:
        s = np.asarray(himmel_sonne, dtype=np.float64)
        s = s / np.linalg.norm(s)
        bild = max(math.asin(max(-1.0, min(1.0, float(s[2])))), 0.05)
        ziel = max(math.radians(tz.sonne_hoehe_grad), 0.05)
        halb = math.pi / 2
        e_quelle = np.where(e < ziel, e * bild / ziel,
                            bild + (e - ziel) * (halb - bild) / max(halb - ziel, 1e-3))
        zeile = np.clip((0.5 - e_quelle / math.pi) * h - 0.5, 0.0, h - 1.0)
        z0 = np.floor(zeile).astype(int)
        z1 = np.minimum(z0 + 1, h - 1)
        f = (zeile - z0).astype(np.float32)[:, None, None]
        lin = lin[z0] * (1.0 - f) + lin[z1] * f
    s = np.asarray(himmel_sonne, dtype=np.float64)
    sonne_az = math.atan2(s[1], s[0])
    az = ((np.arange(w) + 0.5) / w - 0.5) * 2.0 * math.pi
    zur_sonne = 0.5 + 0.5 * np.cos(az - sonne_az)
    hoch = np.clip(np.sin(e), 0.0, 1.0)
    gewicht = np.exp(-hoch * tz.glut[0])[:, None] * (tz.glut[1] + (1.0 - tz.glut[1]) * zur_sonne ** 2)[None, :]
    oben = np.asarray(tz.tint_oben, dtype=np.float64)
    horizont = np.asarray(tz.tint_horizont, dtype=np.float64)
    ton = (oben[None, None, :] * (1.0 - gewicht[..., None]) + horizont[None, None, :] * gewicht[..., None])
    return (np.maximum(lin * ton.astype(np.float32), 0.0) ** (1.0 / 2.2)).astype(np.float32)


def _mal(a, b) -> tuple:
    return tuple(float(x) * float(y) for x, y in zip(a, b))


def umgebung_werte(tz: Tageszeit, thema_werte: dict) -> dict:
    """Die vom Thema kommenden Werte nach der Tageszeit umgerechnet.

    ``thema_werte`` hat die Schlüssel ``sonne_farbe``, ``himmel_helligkeit``,
    ``nebel_farbe``, ``nebel_dichte``, ``boden_farbe``, ``himmel_zenit``,
    ``himmel_horizont``, ``belichtung``. Der Tag gibt sie unverändert zurück.
    """
    if not tz.aktiv:
        return dict(thema_werte)
    w = dict(thema_werte)
    w["sonne_farbe"] = _mal(w["sonne_farbe"], tz.sonne_faktor)
    w["himmel_helligkeit"] = float(w["himmel_helligkeit"]) * tz.himmel_helligkeit
    w["nebel_farbe"] = _mal(w["nebel_farbe"], tz.nebel_faktor)
    w["nebel_dichte"] = float(w["nebel_dichte"]) * tz.nebel_dichte
    w["boden_farbe"] = _mal(w["boden_farbe"], tz.boden_faktor)
    w["himmel_zenit"] = _mal(w["himmel_zenit"], tz.verlauf_faktor)
    w["himmel_horizont"] = _mal(w["himmel_horizont"], tz.verlauf_faktor)
    w["belichtung"] = float(w["belichtung"]) * tz.belichtung
    return w


# ---------------------------------------------------------------------------
# Lokale Lichter
# ---------------------------------------------------------------------------

#: Stärken der Lichtquellen (linear, mit der Reichweite abgestimmt; im Shader
#: fällt ein Licht mit 1/(d²+16) und einem Fenster auf der Reichweite ab).
SCHEINWERFER_STAERKE = 520.0
SCHEINWERFER_FARBE = (1.0, 0.93, 0.78)
SCHEINWERFER_REICHWEITE_M = 62.0
#: Kegel: Kosinus des Innen- und Außenwinkels (voll bis ~11°, null bei ~30°).
SCHEINWERFER_INNEN = math.cos(math.radians(9.0))
SCHEINWERFER_AUSSEN = math.cos(math.radians(26.0))
#: Neigung der Strahlen nach unten (Abblendlicht), als Anteil der Länge.
SCHEINWERFER_NEIGUNG = 0.075
RUECKLICHT_STAERKE = 30.0
RUECKLICHT_BREMSE_STAERKE = 110.0
RUECKLICHT_REICHWEITE_M = 9.0
RUECKLICHT_VERSATZ_M = 0.7
LAMPE_STAERKE = 340.0
LAMPE_FARBE = (1.0, 0.80, 0.52)
LAMPE_REICHWEITE_M = 46.0
#: Punktlicht: der Wert ``aussen`` oberhalb von 1 bedeutet „kein Kegel“.
PUNKTLICHT = 2.0

#: Im Umkreis dieses Abstands zum Blickpunkt zählen Lichter überhaupt; ab 60 %
#: davon blenden sie aus (kein Aufpoppen an der Grenze).
LICHT_SICHT_M = 120.0
#: Die so vielen nächsten Autos bekommen beide Scheinwerfer und Rücklichter;
#: ferne eines in der Mitte.
NAHE_AUTOS = 4


@dataclass(frozen=True)
class Licht:
    pos: tuple
    reichweite_m: float
    farbe: tuple                      # linear, mit Stärke
    richtung: tuple | None = None     # None: Punktlicht
    innen: float = 1.0                # cos des Innenkegels
    aussen: float = PUNKTLICHT        # cos des Außenkegels (> 1: Punktlicht)

    def schwerpunkt(self) -> np.ndarray:
        """Wo das Licht wirkt: bei einem Kegel ein Stück davor."""
        p = np.asarray(self.pos, dtype=np.float64)
        if self.richtung is None:
            return p
        return p + np.asarray(self.richtung, dtype=np.float64) * (0.3 * self.reichweite_m)


@dataclass
class Leuchtpunkte:
    """Wo ein Fahrzeug seine Lichter hat, im Fahrzeugsystem (+X vorn, +Y links)."""

    vorn: tuple = ((2.0, 0.65, 0.65), (2.0, -0.65, 0.65))
    hinten: tuple = ((-2.0, 0.65, 0.8), (-2.0, -0.65, 0.8))

    def mitte_vorn(self) -> tuple:
        return tuple(float(c) for c in np.mean(np.asarray(self.vorn, dtype=np.float64), axis=0))

    def mitte_hinten(self) -> tuple:
        return tuple(float(c) for c in np.mean(np.asarray(self.hinten, dtype=np.float64), axis=0))


def _paar(punkte: np.ndarray, rueckfall: tuple) -> tuple:
    """Links und rechts aus einer Punktwolke: je Seite der Schwerpunkt."""
    if len(punkte) == 0:
        return rueckfall
    links = punkte[punkte[:, 1] > 0.05]
    rechts = punkte[punkte[:, 1] < -0.05]
    if len(links) == 0 or len(rechts) == 0:
        m = punkte.mean(axis=0)
        return ((float(m[0]), 0.0, float(m[2])),) * 2 if abs(m[1]) < 0.3 else rueckfall
    a, b = links.mean(axis=0), rechts.mean(axis=0)
    # Leicht nach innen gezogen: der Schwerpunkt der Leuchte liegt außen am Blech.
    return (tuple(float(c) for c in a), tuple(float(c) for c in b))


def leuchtpunkte_aus_modell(daten, laenge_m: float = 4.3, breite_m: float = 2.0) -> Leuchtpunkte:
    """Scheinwerfer und Rücklichter eines Fahrzeugs aus seinen Netzen.

    ``daten`` ist ein ``mesh.Modelldaten``: gesucht sind die Stücke mit den
    Materialien ``licht_vorn`` und ``licht_hinten``/``bremslicht``. Fehlt
    etwas, springen Maße aus Länge und Breite ein.
    """
    rueck = Leuchtpunkte(
        vorn=((laenge_m * 0.46, breite_m * 0.3, 0.65), (laenge_m * 0.46, -breite_m * 0.3, 0.65)),
        hinten=((-laenge_m * 0.46, breite_m * 0.3, 0.8), (-laenge_m * 0.46, -breite_m * 0.3, 0.8)),
    )
    if daten is None:
        return rueck
    vorn, hinten = [], []
    try:
        for teil in daten.teile:
            if teil.name != "karosserie":
                continue
            versatz = np.asarray(teil.versatz, dtype=np.float64)
            for st in teil.stuecke:
                if st.material >= len(daten.materialien):
                    continue
                name = daten.materialien[st.material].name
                p = np.asarray(st.positionen, dtype=np.float64) + versatz
                if len(p) == 0:
                    continue
                if name == "licht_vorn":
                    vorn.append(p)
                elif name in ("licht_hinten", "bremslicht"):
                    hinten.append(p)
    except (AttributeError, TypeError, IndexError):
        return rueck
    v = np.vstack(vorn) if vorn else np.zeros((0, 3))
    h = np.vstack(hinten) if hinten else np.zeros((0, 3))
    # Vorn liegt bei +X, hinten bei -X: was auf der falschen Seite liegt, ist
    # kein Scheinwerfer (ein Stück „licht_vorn“ im Heck, etwa ein Rückfahrlicht).
    v = v[v[:, 0] > 0.0] if len(v) else v
    h = h[h[:, 0] < 0.0] if len(h) else h
    return Leuchtpunkte(vorn=_paar(v, rueck.vorn), hinten=_paar(h, rueck.hinten))


def _in_welt(punkt, pos_m, gier_rad: float) -> tuple:
    c, s = math.cos(gier_rad), math.sin(gier_rad)
    x, y, z = punkt
    return (float(pos_m[0]) + x * c - y * s, float(pos_m[1]) + x * s + y * c, float(pos_m[2]) + z)


def fahrzeug_lichter(stand, punkte: Leuchtpunkte, nah: bool = True,
                     heck: bool = True) -> list[Licht]:
    """Die Lichtquellen eines Fahrzeugs: Scheinwerfer (Kegel) und Rücklicht.

    ``nah``: zwei Scheinwerfer, sonst einer in der Mitte (breiter). ``heck``:
    mit rotem Rücklicht, das beim Bremsen stärker wird.
    """
    pos = np.asarray(stand.pos_m, dtype=np.float64)
    gier = float(stand.gierwinkel_rad)
    richtung = (math.cos(gier), math.sin(gier), -SCHEINWERFER_NEIGUNG)
    n = math.sqrt(richtung[0] ** 2 + richtung[1] ** 2 + richtung[2] ** 2)
    richtung = (richtung[0] / n, richtung[1] / n, richtung[2] / n)
    licht: list[Licht] = []
    if nah:
        quellen = punkte.vorn
        staerke = SCHEINWERFER_STAERKE
        aussen = SCHEINWERFER_AUSSEN
    else:
        quellen = (punkte.mitte_vorn(),)
        staerke = SCHEINWERFER_STAERKE * 1.25
        aussen = math.cos(math.radians(34.0))
    farbe = tuple(c * staerke for c in SCHEINWERFER_FARBE)
    for q in quellen:
        licht.append(Licht(pos=_in_welt(q, pos, gier), reichweite_m=SCHEINWERFER_REICHWEITE_M,
                           farbe=farbe, richtung=richtung, innen=SCHEINWERFER_INNEN, aussen=aussen))
    if heck:
        b = min(1.0, max(0.0, float(getattr(stand, "bremse", 0.0))))
        s = RUECKLICHT_STAERKE + (RUECKLICHT_BREMSE_STAERKE - RUECKLICHT_STAERKE) * b
        # Ein Stück hinter dem Heck: auf dem Blech selbst überstrahlte es das Auto.
        hx, hy, hz = punkte.mitte_hinten()
        licht.append(Licht(pos=_in_welt((hx - RUECKLICHT_VERSATZ_M, hy, hz), pos, gier),
                           reichweite_m=RUECKLICHT_REICHWEITE_M,
                           farbe=(1.0 * s, 0.05 * s, 0.02 * s)))
    return licht


def lampen_licht(pos) -> Licht:
    """Ein Punktlicht für den Kopf einer Straßenlaterne oder eines Flutlichtmastes."""
    return Licht(pos=tuple(float(c) for c in pos), reichweite_m=LAMPE_REICHWEITE_M,
                 farbe=tuple(c * LAMPE_STAERKE for c in LAMPE_FARBE))


def lichter_sammeln(staende, fokus, punkte_von, lampen=(), nahe_autos: int = NAHE_AUTOS) -> list[Licht]:
    """Alle Kandidaten dieses Bildes: Autos nach Abstand zum Blickpunkt, dazu die Lampen.

    ``punkte_von(stand)`` liefert die :class:`Leuchtpunkte` des Fahrzeugs
    (je Schlüssel gemerkt, siehe ``rennszene``). Geister (``entfaerbt``)
    leuchten nicht. Die ``nahe_autos`` nächsten bekommen beide Scheinwerfer
    und das Rücklicht, die übrigen einen mittleren Scheinwerfer.
    """
    f = np.asarray(fokus, dtype=np.float64)[:2]
    autos = [s for s in staende if not getattr(s, "entfaerbt", False)]
    autos.sort(key=lambda s: float(np.hypot(*(np.asarray(s.pos_m, dtype=np.float64)[:2] - f))))
    licht: list[Licht] = []
    for rang, stand in enumerate(autos):
        punkte = punkte_von(stand)
        nah = rang < nahe_autos
        licht += fahrzeug_lichter(stand, punkte, nah=nah, heck=nah)
    licht += list(lampen)
    return licht


def lichter_waehlen(lichter, fokus, n: int, sicht_m: float = LICHT_SICHT_M) -> list[Licht]:
    """Die ``n`` wichtigsten Lichter um den Blickpunkt, mit Ausblenden am Rand.

    Wichtig heißt: nah. Gemessen wird nicht von der Lampe, sondern von dem
    Punkt, wo sie wirkt (ein Scheinwerfer leuchtet vor dem Auto). Ab 60 % der
    Sichtweite wird ein Licht schwächer und bei ``sicht_m`` ganz weggelassen —
    so poppt nichts auf, wenn die Auswahl wechselt.
    """
    if n <= 0:
        return []
    f = np.asarray(fokus, dtype=np.float64)
    bewertet = []
    for l in lichter:
        d = float(np.linalg.norm(l.schwerpunkt() - f))
        if d >= sicht_m:
            continue
        bewertet.append((d, l))
    bewertet.sort(key=lambda e: e[0])
    ergebnis = []
    for d, l in bewertet[:n]:
        t = min(1.0, max(0.0, (d / sicht_m - 0.6) / 0.4))
        faktor = 1.0 - t * t * (3.0 - 2.0 * t)
        if faktor < 1.0:
            l = Licht(l.pos, l.reichweite_m, tuple(c * faktor for c in l.farbe), l.richtung,
                      l.innen, l.aussen)
        ergebnis.append(l)
    return ergebnis


def lichter_packen(lichter, platz: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """Die Felder ``lichter_pos``, ``lichter_farbe``, ``lichter_richtung`` (je ``(platz, 4)``) und die Anzahl."""
    pos = np.zeros((platz, 4), dtype=np.float32)
    farbe = np.zeros((platz, 4), dtype=np.float32)
    richtung = np.zeros((platz, 4), dtype=np.float32)
    richtung[:, 3] = PUNKTLICHT
    n = min(len(lichter), platz)
    for i, l in enumerate(lichter[:n]):
        pos[i] = (*l.pos, l.reichweite_m)
        farbe[i] = (*l.farbe, l.innen)
        if l.richtung is not None:
            richtung[i] = (*l.richtung, l.aussen)
    return pos, farbe, richtung, n


# ---------------------------------------------------------------------------
# Masten und Lampen an der Strecke
# ---------------------------------------------------------------------------

#: Abstand der Flutlichtmasten entlang der Strecke und von der Fahrbahnkante.
MAST_JE_M = 58.0
MAST_ABSTAND_M = 7.5
#: Höhe des Lampenkopfes und wie weit der Arm zur Strecke reicht, Meter.
MAST_HOEHE_M = 10.5
MAST_ARM_M = 2.6
#: So nah (Fahrbahnkante) darf ein Mast an einer anderen Stelle der Strecke stehen.
MAST_FREI_M = 4.5


def mast_orte(netz, platzierungen=(), katalog=None, fb=None, je_m: float = MAST_JE_M,
              abstand_m: float = MAST_ABSTAND_M) -> np.ndarray:
    """Standorte der Flutlichtmasten, ``(k, 3)``: x, y, Gierwinkel des Arms (zur Strecke hin).

    Abwechselnd links und rechts, hinter dem Rand der Fahrbahn. Gemessen wird
    gegen die Fahrbahn der **ganzen** Strecke (``track_mesh.Fahrbahnabstand``),
    nicht nur gegen das nächste Stück: eigene Strecken führen oft nah an sich
    selbst vorbei. Wo schon ein Objekt aus ``platzierungen`` steht, wird
    übersprungen.
    """
    linie = np.asarray(netz.mittellinie, dtype=np.float64)
    links = np.asarray(netz.links, dtype=np.float64)
    bogen = np.asarray(netz.bogen_m, dtype=np.float64)
    if len(linie) < 3 or len(links) != len(linie) or len(bogen) != len(linie):
        return np.zeros((0, 3))
    halb = float(netz.halbe_breite_m)
    if fb is None:
        from . import track_mesh
        fb = track_mesh.Fahrbahnabstand(linie, halb, reichweite_m=halb + MAST_FREI_M + 4.0)
    gesamt = float(getattr(netz, "laenge_m", bogen[-1]))
    orte = []
    k = 0
    s = je_m * 0.5
    belegt = _belegung(platzierungen, katalog)
    while s < gesamt:
        i = int(np.searchsorted(bogen, s, side="right") - 1)
        i = min(max(i, 0), len(linie) - 1)
        seite = 1.0 if k % 2 == 0 else -1.0
        k += 1
        s += je_m
        p = linie[i] + links[i] * seite * (halb + abstand_m)
        if float(fb.kante(p.reshape(1, 2))[0]) < MAST_FREI_M:
            continue
        if belegt is not None and _besetzt(belegt, p):
            continue
        zur_strecke = linie[i] - p
        orte.append((float(p[0]), float(p[1]), math.atan2(zur_strecke[1], zur_strecke[0])))
    return np.asarray(orte, dtype=np.float64).reshape(-1, 3)


def _belegung(platzierungen, katalog):
    """Mittelpunkte und Radien der größeren platzierten Objekte (``None``: keine)."""
    if not platzierungen:
        return None
    katalog = katalog or {}
    xy, r = [], []
    for pl in platzierungen:
        eintrag = katalog.get(pl.modell, {})
        radius = float(eintrag.get("radius_m", 1.0)) * float(getattr(pl, "skala", 1.0))
        if radius >= 0.6:
            xy.append((pl.x, pl.y))
            r.append(radius)
    if not xy:
        return None
    return np.asarray(xy, dtype=np.float64), np.asarray(r, dtype=np.float64)


def _besetzt(belegt, p, frei_m: float = 0.8) -> bool:
    xy, r = belegt
    return bool(np.any(np.hypot(xy[:, 0] - p[0], xy[:, 1] - p[1]) < r + frei_m))


def mast_lichter(orte: np.ndarray, hoehen=None) -> list[Licht]:
    """Das Punktlicht am Kopf jedes Mastes (Arm zur Strecke hin)."""
    licht = []
    for i, (x, y, gier) in enumerate(np.asarray(orte, dtype=np.float64).reshape(-1, 3)):
        z0 = float(hoehen[i]) if hoehen is not None else 0.0
        kopf = (x + math.cos(gier) * (MAST_ARM_M - 0.4), y + math.sin(gier) * (MAST_ARM_M - 0.4),
                z0 + MAST_HOEHE_M - 0.3)
        licht.append(lampen_licht(kopf))
    return licht


def laternen_lichter(platzierungen, modell: str, kopf_lokal, katalog=None) -> list[Licht]:
    """Punktlichter für platzierte Laternen: der Lampenkopf des Modells, in die Welt gesetzt.

    ``kopf_lokal`` ist die Mitte der Birne im Modellraum (Skala 1).
    """
    licht = []
    for pl in platzierungen:
        if pl.modell != modell:
            continue
        s = float(pl.skala)
        c, sn = math.cos(pl.gier_rad), math.sin(pl.gier_rad)
        x, y, z = (float(v) * s for v in kopf_lokal)
        licht.append(lampen_licht((pl.x + x * c - y * sn, pl.y + x * sn + y * c, float(pl.z) + z)))
    return licht


def birne_aus_modell(daten) -> tuple | None:
    """Die Mitte der Lampenbirne (Material ``*_bulb`` oder ``*_birne``) im Modellraum."""
    punkte = []
    try:
        for teil in daten.teile:
            versatz = np.asarray(teil.versatz, dtype=np.float64)
            for st in teil.stuecke:
                if st.material >= len(daten.materialien):
                    continue
                name = daten.materialien[st.material].name
                if name.endswith("_bulb") or name.endswith("_birne"):
                    punkte.append(np.asarray(st.positionen, dtype=np.float64) + versatz)
    except (AttributeError, TypeError):
        return None
    if not punkte:
        return None
    m = np.vstack(punkte).mean(axis=0)
    return (float(m[0]), float(m[1]), float(m[2]))


# ---------------------------------------------------------------------------
# Das Netz eines Flutlichtmastes
# ---------------------------------------------------------------------------

def _quader(mitte, halb) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Ein Quader aus 24 Ecken (je Fläche eigene Normalen), Dreiecke dazu."""
    cx, cy, cz = mitte
    hx, hy, hz = halb
    flaechen = (
        ((1, 0, 0), ((1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1))),
        ((-1, 0, 0), ((-1, 1, -1), (-1, -1, -1), (-1, -1, 1), (-1, 1, 1))),
        ((0, 1, 0), ((1, 1, -1), (-1, 1, -1), (-1, 1, 1), (1, 1, 1))),
        ((0, -1, 0), ((-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1))),
        ((0, 0, 1), ((-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1))),
        ((0, 0, -1), ((-1, 1, -1), (1, 1, -1), (1, -1, -1), (-1, -1, -1))),
    )
    pos, nor, idx = [], [], []
    for n, ecken in flaechen:
        b = len(pos)
        for e in ecken:
            pos.append((cx + e[0] * hx, cy + e[1] * hy, cz + e[2] * hz))
            nor.append(n)
        idx += [(b, b + 1, b + 2), (b, b + 2, b + 3)]
    return (np.asarray(pos, dtype=np.float32), np.asarray(nor, dtype=np.float32),
            np.asarray(idx, dtype=np.uint32))


def _saeule(radius: float, hoehe: float, seiten: int = 10) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    w = np.linspace(0.0, 2.0 * np.pi, seiten, endpoint=False)
    c, s = np.cos(w), np.sin(w)
    pos, nor, idx = [], [], []
    for i in range(seiten):
        j = (i + 1) % seiten
        b = len(pos)
        for (cx, sx, z) in ((c[i], s[i], 0.0), (c[j], s[j], 0.0), (c[j], s[j], hoehe), (c[i], s[i], hoehe)):
            pos.append((cx * radius, sx * radius, z))
        for (cx, sx) in ((c[i], s[i]), (c[j], s[j]), (c[j], s[j]), (c[i], s[i])):
            nor.append((cx, sx, 0.0))
        idx += [(b, b + 1, b + 2), (b, b + 2, b + 3)]
    return (np.asarray(pos, dtype=np.float32), np.asarray(nor, dtype=np.float32),
            np.asarray(idx, dtype=np.uint32))


def _vereinen(teile) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    pos, nor, idx, basis = [], [], [], 0
    for p, n, i in teile:
        pos.append(p)
        nor.append(n)
        idx.append(i + basis)
        basis += len(p)
    return np.vstack(pos), np.vstack(nor), np.vstack(idx).astype(np.uint32)


def mast_netz() -> dict:
    """Mast und Lampenkopf als zwei Netze: ``{"mast": (pos, nor, idx), "kopf": (...)}``.

    Ursprung am Fuß, der Arm zeigt nach +X (die Rennszene dreht ihn zur
    Strecke), Maße nach :data:`MAST_HOEHE_M` und :data:`MAST_ARM_M`.
    """
    h = MAST_HOEHE_M
    mast = _vereinen([
        _saeule(0.16, 0.45, 10),                                      # Fuß, dicker
        _saeule(0.11, h, 10),
        _quader((MAST_ARM_M * 0.5, 0.0, h - 0.15), (MAST_ARM_M * 0.5, 0.045, 0.045)),   # Arm
        _quader((MAST_ARM_M - 0.55, 0.0, h - 0.04), (0.6, 0.26, 0.08)),                # Gehäuse
    ])
    kopf = _vereinen([
        _quader((MAST_ARM_M - 0.55, 0.0, h - 0.135), (0.5, 0.2, 0.012)),               # leuchtende Fläche
    ])
    return {"mast": mast, "kopf": kopf}
