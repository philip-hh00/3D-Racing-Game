"""Umgebung auf eigenen Strecken: nie etwas auf oder zu nah an der Fahrbahn.

Eigene Strecken baut der Spieler im Editor aus Kacheln (``tile_track``):
Geraden und Viertelkreise auf einem Raster von 32 m. Zwei Geraden in
Nachbarzellen liegen nur 32 m auseinander — zwischen ihren Kanten bleiben
bei 24 m Breite acht Meter. Haarnadeln, Schlangen, lange schmale Kurse weit
vom Ursprung: all das ist erlaubt, und überall muss die Umgebung außerhalb
der Fahrbahn bleiben.

Die Strecken entstehen hier wie im Editor: Bauteile auf dem Raster, zu einer
Schleife verbunden, geprüft mit ``validate_game`` (also veröffentlichbar),
ausgegeben mit ``to_game_json``. Geprüft wird unabhängig von der
Platzierung: Grundrisse werden abgetastet und gegen die ganze Mittellinie
gemessen, mit :func:`platzierung.abstand_zur_linie` (alle Abschnitte, ohne
Raster). Nur numpy, kein OpenGL.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest

from src.render3d import gelaende, platzierung, thema, track_mesh
from src.track.tile_track import Piece, TileTrackDraft
from src.track.track_builder import validate

WURZEL = Path(__file__).resolve().parents[1]
THEMEN = ["City", "Desert", "Forest", "Mountain", "Plains"]
KATALOG = json.loads((WURZEL / "assets" / "umgebung" / "katalog.json").read_text(encoding="utf-8"))

#: Randstreifen samt Begrenzung: bis hierher ist das Gelände exakt flach.
RANDSTREIFEN_M = 3.0
#: Toleranz der Abtastung eines Grundrisses (Punkte alle 0,2 m).
TOLERANZ_M = 0.12


# ---------------------------------------------------------------------------
# Kachelstrecken wie im Editor
# ---------------------------------------------------------------------------

def _kacheln(befehle: str, start=(0, 0), breite: float = 300.0, name: str = "Test") -> TileTrackDraft:
    """Eine Schleife aus Bauteilen, wie sie der Editor legt.

    Beginnt mit einer Geraden nach Osten; dann je Befehl ein Bauteil:
    ``S`` Gerade, ``L``/``R`` Viertelkreis nach links/rechts, eine Ziffer
    dahinter ist der Radius in Zellen (1–3). Jedes Bauteil wird wie im
    Editor an den offenen Anschluss gesetzt, auf freie Zellen.
    """
    teile = [Piece("straight", start[0], start[1], 0)]
    belegt = set(teile[0].occupies())
    ausgang = teile[0].ports()[1]
    for befehl in befehle.split():
        art, r = befehl[0], int(befehl[1:] or 1)
        gesucht = (ausgang.face_dir + 180) % 360
        ziel = {"S": ausgang.face_dir, "L": (ausgang.face_dir + 90) % 360,
                "R": (ausgang.face_dir - 90) % 360}[art]
        cx, cy = int(ausgang.wx // 400), int(ausgang.wy // 400)
        gefunden = None
        for col in range(cx - 4, cx + 5):
            for row in range(cy - 4, cy + 5):
                for rot in range(4):
                    p = Piece("straight" if art == "S" else "curve", col, row, rot,
                              1 if art == "S" else r)
                    for k in (0, 1):
                        a, b = p.ports()[k], p.ports()[1 - k]
                        if (abs(a.wx - ausgang.wx) < 0.5 and abs(a.wy - ausgang.wy) < 0.5
                                and a.face_dir == gesucht and b.face_dir == ziel
                                and not (p.occupies() & belegt)):
                            gefunden = (p, b)
        assert gefunden is not None, f"{befehl}: kein freier Platz"
        teile.append(gefunden[0])
        belegt |= gefunden[0].occupies()
        ausgang = gefunden[1]
    entwurf = TileTrackDraft(name=name, width=breite, background_texture="Plains", pieces=teile)
    assert entwurf.is_closed_loop(), name
    for i in range(len(teile)):
        entwurf.start_piece_idx = i
        if entwurf.start_straight_ok():
            break
    fehler = entwurf.validate_game()
    assert not fehler, [f.message for f in fehler]
    return entwurf


#: Name → (Befehle, Start-Zelle, Breite in px).
STRECKEN = {
    # Haarnadel-Schlange: vier Reihen je 32 m auseinander, Kehren mit r = 1.
    "schlange": ("S S S S S R R S S S S S L L S S S S S R R S S S S S S R S S R", (0, 0), 300.0),
    # Zwei eng parallele Geraden: 8 m Luft zwischen den Kanten.
    "parallel": ("S S S S S S S S S R R S S S S S S S S S S R R", (0, 0), 300.0),
    # Kleines Oval mit r = 2.
    "oval_klein": ("S S R2 R2 S S S R2 R2", (0, 0), 250.0),
    # Großer Kurs: weite Kurven, eine Haarnadel ins große Innenfeld.
    "gross": ("S S S S S S S S S S R3 S S S S S S R3 S S S R S S S L L S S S R "
              "S S S S S S R3 S S S S S S R3", (0, 0), 280.0),
    # Lang und schmal, zehn Kilometer vom Ursprung.
    "lang_weit": (" ".join(["S"] * 39 + ["R", "R"] + ["S"] * 40 + ["R", "R"]), (300, 200), 260.0),
}


@lru_cache(maxsize=None)
def _strecke(name: str) -> dict:
    befehle, start, breite = STRECKEN[name]
    return _kacheln(befehle, start, breite, name=f"eigen_{name}").to_game_json()


@lru_cache(maxsize=None)
def _netz(name: str):
    return track_mesh.bauen(_strecke(name))


@lru_cache(maxsize=None)
def _thema(name: str):
    return thema.laden(WURZEL / "data" / "themen", name)


@lru_cache(maxsize=None)
def _orte(strecke: str, themenname: str, details: int):
    netz = _netz(strecke)
    return tuple(platzierung.platzieren(netz.mittellinie, netz.halbe_breite_m, _thema(themenname),
                                        netz.name, details=details))


def _grundriss(modell: str):
    eintrag = KATALOG[modell]
    if "grundriss_m" in eintrag:
        return tuple(eintrag["grundriss_m"])
    r = eintrag["radius_m"]
    return (-r, r, -r, r)


def _grundriss_punkte(pl, x0, x1, y0, y1, schritt=0.2) -> np.ndarray:
    """Rand und Inneres eines gedrehten Rechtecks als Punkte (Welt)."""
    s = pl.skala
    x0, x1, y0, y1 = x0 * s, x1 * s, y0 * s, y1 * s
    u = np.linspace(x0, x1, max(2, int(math.ceil((x1 - x0) / schritt)) + 1))
    v = np.linspace(y0, y1, max(2, int(math.ceil((y1 - y0) / schritt)) + 1))
    rand = np.concatenate([np.column_stack([u, np.full_like(u, y0)]), np.column_stack([u, np.full_like(u, y1)]),
                           np.column_stack([np.full_like(v, x0), v]), np.column_stack([np.full_like(v, x1), v])])
    gu, gv = np.meshgrid(np.linspace(x0, x1, 5), np.linspace(y0, y1, 5))
    lokal = np.concatenate([rand, np.column_stack([gu.ravel(), gv.ravel()])])
    c, sn = math.cos(pl.gier_rad), math.sin(pl.gier_rad)
    return np.column_stack([pl.x + c * lokal[:, 0] - sn * lokal[:, 1],
                            pl.y + sn * lokal[:, 0] + c * lokal[:, 1]])


def _pflicht(pl, th) -> float:
    """Was der Test verlangt — unabhängig von der Platzierung formuliert."""
    deko = {m for d in th.deko for m in d.modell.split("|")}
    kulisse = {m for k in th.kulisse for m in k.modell.split("|")}
    gross = {"strecke/tribuene", "strecke/boxengebaeude", "strecke/tribuene_klein"}
    if pl.modell in kulisse:
        return platzierung.KULISSE_FREI_M
    if pl.modell in deko or pl.modell in gross:
        return platzierung.ABSTAND_M
    return platzierung.KANTE_FREI_M


def _abstand_zu_abschnitten(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Kürzester Abstand jedes Punkts zu den Abschnitten ``a``–``b`` (rohe Gewalt)."""
    ab = b - a
    t = np.clip(((p[:, None] - a) * ab).sum(axis=2) / np.maximum((ab * ab).sum(axis=1), 1e-12), 0, 1)
    return np.linalg.norm(p[:, None] - a - t[..., None] * ab, axis=2).min(axis=1)


def _verstoesse(netz, orte, th) -> list[str]:
    linie, hb = netz.mittellinie, netz.halbe_breite_m
    a, b = linie, np.roll(linie, -1, axis=0)
    mitte = platzierung.abstand_zur_linie(np.array([[p.x, p.y] for p in orte]), linie) - hb
    fehler = []
    for pl, m in zip(orte, mitte):
        if pl.modell == platzierung.STARTBRUECKE:
            continue
        x0, x1, y0, y1 = _grundriss(pl.modell)
        umkreis = math.hypot(max(abs(x0), abs(x1)), max(abs(y0), abs(y1))) * pl.skala
        pflicht = _pflicht(pl, th)
        if m - umkreis >= pflicht + 0.5:
            continue                               # der ganze Umkreis ist weit genug weg
        # Nur die Abschnitte in Reichweite; die übrigen sind weiter weg als die Mitte.
        nah = np.linalg.norm(a - (pl.x, pl.y), axis=1) < m + hb + 2 * umkreis + 10.0
        punkte = _grundriss_punkte(pl, x0, x1, y0, y1)
        d = float(_abstand_zu_abschnitten(punkte, a[nah], b[nah]).min()) - hb
        if d < pflicht - TOLERANZ_M:
            fehler.append(f"{pl.modell} bei ({pl.x:.1f}, {pl.y:.1f}): {d:.2f} m < {pflicht} m")
    return fehler


# ---------------------------------------------------------------------------
# Die Strecken selbst
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", list(STRECKEN))
def test_strecken_sind_echte_editorstrecken(name):
    strecke = _strecke(name)
    assert strecke["editor_tiles"]["pieces"]
    netz = _netz(name)
    assert len(netz.mittellinie) > 100


def test_die_engen_stellen_sind_wirklich_eng():
    """Die Schlange hat Stücke, deren Kanten sich auf acht Meter nahekommen."""
    netz = _netz("schlange")
    linie, hb = netz.mittellinie, netz.halbe_breite_m
    n = len(linie)
    # Abstand jedes Punkts zu den Stücken, die entlang der Strecke weit weg sind.
    d = np.full(n, np.inf)
    for i in range(0, n, 5):
        weit = np.abs((np.arange(n) - i + n // 2) % n - n // 2) > 60
        d[i] = np.linalg.norm(linie[weit] - linie[i], axis=1).min()
    assert d.min() - 2 * hb < 9.0


def test_der_editor_erlaubt_keine_kreuzung():
    """Kreuzungen und Brücken gibt es im Editor nicht: Zellen sind exklusiv, jede
    Kachel wird einmal durchfahren, und eine Mittellinie, die sich schneidet,
    besteht die Prüfung nicht. Die Umgebung muss also keine Brücke kennen."""
    w = np.linspace(0, 2 * math.pi, 200, endpoint=False)
    liegende_acht = [(3000 * math.sin(a), 1500 * math.sin(2 * a)) for a in w]
    assert "self_intersect" in {f.code for f in validate(liegende_acht, 260.0)}
    # Zwei Kacheln in derselben Zelle (eine Kreuzung) verbinden sich nicht.
    kreuz = TileTrackDraft(pieces=[Piece("straight", 0, 0, 0), Piece("straight", 0, 0, 1)])
    assert not kreuz.is_closed_loop()


# ---------------------------------------------------------------------------
# Grundrisse
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("details", [0, 2])
@pytest.mark.parametrize("themenname", THEMEN)
@pytest.mark.parametrize("strecke", list(STRECKEN))
def test_kein_grundriss_auf_der_fahrbahn(strecke, themenname, details):
    netz = _netz(strecke)
    orte = _orte(strecke, themenname, details)
    assert len(orte) > 20
    fehler = _verstoesse(netz, orte, _thema(themenname))
    assert not fehler, fehler[:10]


@pytest.mark.parametrize("strecke", list(STRECKEN))
def test_startbruecke_steht_nur_auf_der_eigenen_fahrbahn(strecke):
    """Die Pfeiler der Brücke stehen neben der Fahrbahn, nicht auf einem anderen Stück."""
    netz = _netz(strecke)
    b = next(p for p in _orte(strecke, "Plains", 2) if p.modell == platzierung.STARTBRUECKE)
    x0, x1, y0, y1 = _grundriss(platzierung.STARTBRUECKE)
    for pfeiler in ((x0, x0 + 1.2), (x1 - 1.2, x1)):
        punkte = _grundriss_punkte(b, pfeiler[0], pfeiler[1], y0, y1)
        d = platzierung.abstand_zur_linie(punkte, netz.mittellinie) - netz.halbe_breite_m
        assert d.min() > 0.5


@pytest.mark.parametrize("strecke", list(STRECKEN))
def test_tribuene_und_boxen_erscheinen(strecke):
    """Wo der Platz an der Linie fehlt, rücken sie an eine andere gerade Stelle."""
    orte = _orte(strecke, "Plains", 2)
    modelle = {p.modell for p in orte}
    assert "strecke/tribuene" in modelle
    assert "strecke/boxengebaeude" in modelle


def test_tribuene_weicht_einem_nahen_stueck_aus():
    """Auf der Parallelstrecke läge die Tribüne außen auf der Gegengeraden
    (8 m Luft, sie braucht 16 m) — sie muss woanders stehen, und zwar ganz."""
    netz = _netz("parallel")
    orte = _orte("parallel", "Plains", 2)
    tribuene = next(p for p in orte if p.modell == "strecke/tribuene")
    punkte = _grundriss_punkte(tribuene, *_grundriss("strecke/tribuene"))
    d = platzierung.abstand_zur_linie(punkte, netz.mittellinie) - netz.halbe_breite_m
    assert d.min() >= platzierung.ABSTAND_M - TOLERANZ_M


# ---------------------------------------------------------------------------
# Kulisse
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("strecke", list(STRECKEN))
@pytest.mark.parametrize("themenname", ["City", "Plains"])
def test_kulisse_liegt_ausserhalb(strecke, themenname):
    netz = _netz(strecke)
    th = _thema(themenname)
    kulisse = {m for k in th.kulisse for m in k.modell.split("|")}
    orte = [p for p in _orte(strecke, themenname, 0) if p.modell in kulisse]
    assert len(orte) >= min(k.anzahl for k in th.kulisse)
    lo, hi = netz.mittellinie.min(axis=0), netz.mittellinie.max(axis=0)
    for pl in orte:
        punkte = _grundriss_punkte(pl, *_grundriss(pl.modell), schritt=2.0)
        d = platzierung.abstand_zur_linie(punkte, netz.mittellinie) - netz.halbe_breite_m
        assert d.min() >= platzierung.KULISSE_FREI_M - 1.0, pl
        # Und nicht über einen Kilometer weg an den Längsseiten einer schmalen Strecke.
        rechteck = np.hypot(np.maximum(np.abs(pl.x - (lo[0] + hi[0]) / 2) - (hi[0] - lo[0]) / 2, 0),
                            np.maximum(np.abs(pl.y - (lo[1] + hi[1]) / 2) - (hi[1] - lo[1]) / 2, 0))
        assert rechteck < max(k.radius_m[1] for k in th.kulisse) + 8 * 40.0 + 1.0


# ---------------------------------------------------------------------------
# Gelände, Gras, ferner Wald, Kiesbetten, Randsteine
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _gelaende(strecke: str, themenname: str, detail: int):
    netz = _netz(strecke)
    th = _thema(themenname)
    auslauf = float(th.auslauf.breite_m)
    gel = gelaende.Gelaende(netz.mittellinie, netz.halbe_breite_m, th.gelaende, netz.name,
                            rand_arten=th.rand, auslauf_m=auslauf, detail=detail)
    # Wie im Spiel: erst die Objekte auf den Boden (ebnet unter Häusern).
    orte = platzierung.hoehen_setzen(list(_orte(strecke, themenname, 2)), gel, th)
    return gel, orte


def _streifen(netz, bis_m: float, schritt: float = 0.7) -> np.ndarray:
    """Punkte auf der Fahrbahn und bis ``bis_m`` hinter der Kante, beidseitig."""
    linie, links, hb = netz.mittellinie, netz.links, netz.halbe_breite_m
    quer = np.arange(-hb - bis_m, hb + bis_m + 1e-9, schritt)
    return (linie[:, None, :] + links[:, None, :] * quer[None, :, None]).reshape(-1, 2)


@pytest.mark.parametrize("detail", [0, 2])
@pytest.mark.parametrize("themenname", THEMEN)
@pytest.mark.parametrize("strecke", list(STRECKEN))
def test_gelaende_ist_auf_fahrbahn_und_randstreifen_null(strecke, themenname, detail):
    netz = _netz(strecke)
    gel, _orte_ = _gelaende(strecke, themenname, detail)
    th = _thema(themenname)
    kies = th.auslauf.breite_m + 1.0
    p = _streifen(netz, max(RANDSTREIFEN_M, kies))
    # Gemessen zur ganzen Strecke (die Querlinien einer engen Kurve reichen
    # innen über die Mitte hinaus, neben einem anderen Stück auf dessen Bahn).
    fb = track_mesh.Fahrbahnabstand(netz.mittellinie, netz.halbe_breite_m)
    k = fb.kante(p)
    rand = p[k <= RANDSTREIFEN_M]
    assert np.all(gel.feld(rand[:, 0], rand[:, 1]) == 0.0)
    # Und der gezeichnete Boden: jedes Dreieck darunter hat Ecken auf 0.
    assert np.all(gel.hoehe(rand[:, 0], rand[:, 1]) == 0.0)
    # Unter dem Kies (4 cm über der Fahrbahn) bleibt der Boden darunter.
    kiesbett = p[k <= kies]
    assert np.all(gel.feld(kiesbett[:, 0], kiesbett[:, 1]) == 0.0)
    assert gel.hoehe(kiesbett[:, 0], kiesbett[:, 1]).max() < track_mesh.AUSLAUF_HOEHE_M / 2


@pytest.mark.parametrize("themenname", ["Forest", "Mountain"])
def test_kein_huegel_im_engen_innenfeld(themenname):
    """Zwischen zwei Geraden mit 8 m Luft (Parallelstrecke) und im Innenfeld der
    Schlange bleibt das Gelände unten — nichts verdeckt das Nachbarstück."""
    for strecke in ("parallel", "schlange"):
        netz = _netz(strecke)
        gel, _ = _gelaende(strecke, themenname, 0)
        lo, hi = netz.mittellinie.min(axis=0), netz.mittellinie.max(axis=0)
        gx, gy = np.meshgrid(np.arange(lo[0], hi[0], 2.0), np.arange(lo[1], hi[1], 2.0))
        p = np.column_stack([gx.ravel(), gy.ravel()])
        innen = platzierung.innerhalb(p, netz.mittellinie)
        h = gel.hoehe(p[innen, 0], p[innen, 1])
        assert np.abs(h).max() < 1.5, (strecke, float(np.abs(h).max()))


@pytest.mark.parametrize("themenname", THEMEN)
@pytest.mark.parametrize("strecke", list(STRECKEN))
def test_hoehen_steigen_nah_an_der_strecke_sanft(strecke, themenname):
    """Hügel dürfen ins große Innenfeld, aber nicht an die Fahrbahn: näher als
    der Korridor ist alles flach, danach steigt es nie steiler als 45 Grad
    über dem Korridorrand an — auch zwischen zwei nahen Stücken. Das kleine
    Oval (72 m Innenfeld) trägt so höchstens einen flachen Buckel."""
    netz = _netz(strecke)
    gel, _ = _gelaende(strecke, themenname, 0)
    lo, hi = netz.mittellinie.min(axis=0) - 120, netz.mittellinie.max(axis=0) + 120
    rng = np.random.default_rng(3)
    p = rng.uniform(lo, hi, size=(15000, 2))
    k = platzierung.abstand_zur_linie(p, netz.mittellinie) - netz.halbe_breite_m
    h = gel.feld(p[:, 0], p[:, 1], ebnen=False)
    assert np.all(h[k < gel.korridor - 2.0] == 0.0)
    assert np.all(np.abs(h) <= np.maximum(k - gel.korridor, 0.0) + 2.0)


@pytest.mark.parametrize("strecke", list(STRECKEN))
def test_bergkette_und_ferne_zonen_liegen_ausserhalb(strecke):
    """Die Bergkette (``horizont``) und die fernen Hügel wachsen erst weit vor
    dem Streckenrechteck — für jede Form, auch weit vom Ursprung."""
    netz = _netz(strecke)
    for themenname in ("Mountain", "Desert"):
        gel, _ = _gelaende(strecke, themenname, 0)
        a = gel.art
        # Auf dem Rand des Rechtecks samt 100 m: nur die nahe Zone, gedeckelt.
        lo, hi = netz.mittellinie.min(axis=0), netz.mittellinie.max(axis=0)
        t = np.linspace(0, 1, 400)
        rand = np.concatenate([np.column_stack([lo[0] + t * (hi[0] - lo[0]), np.full_like(t, lo[1] - 100)]),
                               np.column_stack([lo[0] + t * (hi[0] - lo[0]), np.full_like(t, hi[1] + 100)])])
        h = gel.feld(rand[:, 0], rand[:, 1], ebnen=False)
        assert h.max() <= a.nah_hoehe_m * 1.5 + 1.0


def test_sehr_grosse_strecke_hat_ein_geschlossenes_netz():
    """Sind die Ringe innen, weil die Strecke größer ist als der Horizont?"""
    w = np.linspace(0, 2 * math.pi, 3000, endpoint=False)
    linie = np.column_stack([3200 * np.cos(w), 300 * np.sin(w)])
    art = _thema("Plains").gelaende
    gel = gelaende.Gelaende(linie, 12.0, art, "riesig", detail=0)
    netz = gel.netz()
    xs, ys, _z = gel._gitter_bauen()
    ringe = netz.positionen[len(xs) * len(ys):, :2]
    assert len(ringe)
    ausserhalb = (np.abs(ringe[:, 0]) > xs[-1] - 1) | (np.abs(ringe[:, 1]) > ys[-1] - 1)
    assert ausserhalb.all()


@pytest.mark.parametrize("themenname", [t for t in THEMEN if t != "City"])
@pytest.mark.parametrize("strecke", list(STRECKEN))
def test_kein_gras_auf_der_fahrbahn(strecke, themenname):
    netz = _netz(strecke)
    th = _thema(themenname)
    gel, orte = _gelaende(strecke, themenname, 0)
    feld = gelaende.gras_platzieren(gel, th.gras, 2, netz.name,
                                    platzierung.grasfreie_flaechen(orte, th))
    assert len(feld.pos) > 1000
    d = platzierung.abstand_zur_linie(feld.pos[:, :2], netz.mittellinie) - netz.halbe_breite_m
    assert d.min() >= gelaende.GRAS_INNEN_M - 1e-6


@pytest.mark.parametrize("themenname", ["Forest", "Mountain", "Plains"])
@pytest.mark.parametrize("strecke", list(STRECKEN))
def test_ferner_wald_steht_weit_weg(strecke, themenname):
    netz = _netz(strecke)
    gel, _ = _gelaende(strecke, themenname, 0)
    wald = gelaende.fernwald_platzieren(gel, netz.name, 1.0)
    assert len(wald.pos)
    probe = wald.pos[:: max(1, len(wald.pos) // 3000), :2]
    d = platzierung.abstand_zur_linie(probe, netz.mittellinie) - netz.halbe_breite_m
    assert d.min() > 100.0


@pytest.mark.parametrize("themenname", ["Desert", "Forest", "Plains"])
@pytest.mark.parametrize("strecke", list(STRECKEN))
def test_kiesbett_nie_auf_einem_anderen_stueck(strecke, themenname):
    """Jeder Punkt eines Kiesbetts: auf keiner Fahrbahn, und ein anderes Stück
    ist mindestens ``KIES_FREI_M`` weg (der Abstand zur ganzen Strecke ist nie
    kleiner als der zur eigenen Kante, außer ein anderes Stück liegt näher)."""
    netz = _netz(strecke)
    breite = _thema(themenname).auslauf.breite_m
    baender = track_mesh.auslauf_baender(netz, breite)
    assert baender
    for band in baender:
        p = band.positionen.reshape(-1, 4, 3)          # je Punkt: Kante, 0,4 m, Rand innen, Rand
        sichtbar = p[:, :, 2] > 0.0
        kante = p[:, 0, :2]
        eigen = np.linalg.norm(p[:, :, :2] - kante[:, None, :], axis=2)
        ganz = (platzierung.abstand_zur_linie(p[:, :, :2].reshape(-1, 2), netz.mittellinie)
                - netz.halbe_breite_m).reshape(eigen.shape)
        assert ganz[sichtbar].min() >= -0.02
        assert np.all(ganz[sichtbar] >= np.minimum(eigen[sichtbar], track_mesh.KIES_FREI_M) - 0.1)


@pytest.mark.parametrize("strecke", list(STRECKEN))
def test_randsteine_liegen_auf_der_eigenen_fahrbahn(strecke):
    netz = _netz(strecke)
    for band in netz.baender:
        if not band.name.startswith("randstein"):
            continue
        d = platzierung.abstand_zur_linie(band.positionen[:, :2], netz.mittellinie) - netz.halbe_breite_m
        assert d.max() <= 0.01


# ---------------------------------------------------------------------------
# Werkzeuge
# ---------------------------------------------------------------------------

def test_fahrbahnabstand_ist_exakt():
    netz = _netz("schlange")
    fb = track_mesh.Fahrbahnabstand(netz.mittellinie, netz.halbe_breite_m)
    rng = np.random.default_rng(5)
    p = rng.uniform(netz.mittellinie.min(axis=0) - 20, netz.mittellinie.max(axis=0) + 20, size=(20000, 2))
    genau = platzierung.abstand_zur_linie(p, netz.mittellinie) - netz.halbe_breite_m
    schnell = fb.kante(p)
    nah = genau < fb.reichweite - fb.halbbreite
    assert np.allclose(schnell[nah], genau[nah], atol=1e-9)
    assert np.all(schnell[~nah] >= fb.reichweite - fb.halbbreite - 1e-9)
    for _ in range(200):
        x, y = rng.uniform(netz.mittellinie.min(axis=0), netz.mittellinie.max(axis=0))
        pl = platzierung.Platzierung("x", float(x), float(y), float(rng.uniform(0, 6.3)), 1.0)
        x0, x1 = sorted(rng.uniform(-15, 15, 2))
        y0, y1 = sorted(rng.uniform(-6, 6, 2))
        d = fb.rechteck(pl.x, pl.y, pl.gier_rad, x0, x1, y0, y1)
        abgetastet = (platzierung.abstand_zur_linie(_grundriss_punkte(pl, x0, x1, y0, y1, 0.1),
                                                    netz.mittellinie) - netz.halbe_breite_m).min()
        if abgetastet < fb.reichweite - fb.halbbreite - 1.0 and abgetastet > -netz.halbe_breite_m + 0.1:
            assert d <= abgetastet + 1e-6
            assert d >= abgetastet - 0.1


def test_katalog_hat_grundrisse():
    for name, eintrag in KATALOG.items():
        assert "grundriss_m" in eintrag, name
        x0, x1, y0, y1 = eintrag["grundriss_m"]
        assert x0 < x1 and y0 < y1, name
