"""B3: PBR-Beleuchtung.

Geprüft wird an gerenderten Flächen: eine Ebene mit bekannter Normale, bekannte
Materialwerte, und dann die Frage, ob das Ergebnis physikalisch stimmt — ist
Metall vor einem Himmel hell, wird ein rauer Lack matt, färbt Metall seine
Spiegelung ein.
"""
import numpy as np
import pytest

from src.render3d import shader

moderngl = pytest.importorskip("moderngl")


@pytest.fixture(scope="module")
def ctx():
    try:
        kontext = moderngl.create_standalone_context()
    except Exception as fehler:                       # pragma: no cover
        pytest.skip(f"kein OpenGL-Kontext zu bekommen: {fehler}")
    yield kontext
    kontext.release()


def _flaeche(ctx, programm):
    """Ein Quadrat in der x-y-Ebene, Normale nach +Z, füllt das Bild."""
    daten = np.array([
        # position           normale        uv
        [-1, -1, 0, 0, 0, 1, 0, 0],
        [+1, -1, 0, 0, 0, 1, 1, 0],
        [-1, +1, 0, 0, 0, 1, 0, 1],
        [+1, +1, 0, 0, 0, 1, 1, 1],
    ], dtype="f4")
    vbo = ctx.buffer(daten.tobytes())
    return ctx.vertex_array(programm, [
        (vbo, "3f 3f 2f", "in_position", "in_normale", "in_uv")])


def _rendern(ctx, programm, vao, groesse=(32, 32)):
    ziel = ctx.simple_framebuffer(groesse)
    ziel.use()
    ziel.clear(0.0, 0.0, 0.0, 1.0)
    vao.render(moderngl.TRIANGLE_STRIP)
    roh = np.frombuffer(ziel.read(components=3), dtype=np.uint8)
    return roh.reshape(groesse[1], groesse[0], 3).astype(np.float64) / 255.0


def _aufbauen(ctx, *, grundton=(0.8, 0.1, 0.1), metallic=0.0, rauheit=0.5,
              kamera=(0.0, 0.0, 3.0)):
    p = shader.programm(ctx)
    p["grundton"].value = grundton
    p["hat_basisfarbe"].value = 0.0
    p["hat_metallic_rauheit"].value = 0.0
    p["metallic_faktor"].value = metallic
    p["rauheit_faktor"].value = rauheit
    p["kamera_position"].value = kamera
    p["mvp"].write(np.eye(4, dtype="f4").tobytes())
    shader.modell_setzen(p, np.eye(4))
    return p, _flaeche(ctx, p)


def test_das_programm_baut_sich(ctx):
    p = shader.programm(ctx)
    assert "mvp" in p and "sonne_richtung" in p


def test_normalmatrix_ist_bei_reiner_drehung_die_drehung_selbst():
    winkel = 0.7
    c, s = np.cos(winkel), np.sin(winkel)
    m = np.eye(4)
    m[0, 0], m[0, 1], m[1, 0], m[1, 1] = c, -s, s, c
    assert shader.normalmatrix(m) == pytest.approx(m[:3, :3], abs=1e-6)


def test_normalmatrix_ignoriert_die_verschiebung():
    m = np.eye(4)
    m[:3, 3] = (17.0, -4.0, 2.0)
    assert shader.normalmatrix(m) == pytest.approx(np.eye(3), abs=1e-6)


def test_eine_rote_flaeche_bleibt_rot(ctx):
    p, vao = _aufbauen(ctx, grundton=(0.8, 0.05, 0.05))
    bild = _rendern(ctx, p, vao)
    mittel = bild.reshape(-1, 3).mean(axis=0)
    assert mittel[0] > mittel[1] * 1.8 and mittel[0] > mittel[2] * 1.8


def test_metall_vor_einem_himmel_ist_nicht_schwarz(ctx):
    """Der Grund, warum ein Himmel im Shader steht.

    Eine metallische Flaeche streut nicht, sie zeigt nur ihre Umgebung. Vor
    einem schwarzen Nichts zeigt sie nichts - und genau so sah das Fahrzeug
    ohne diesen Shader aus.
    """
    p, vao = _aufbauen(ctx, grundton=(0.9, 0.9, 0.9), metallic=1.0, rauheit=0.25)
    hell = _rendern(ctx, p, vao).mean()
    assert hell > 0.25, f"Metall ist zu dunkel: {hell:.3f}"


def test_metall_faerbt_seine_spiegelung_ein(ctx):
    """Kupfer spiegelt kupfern, Chrom neutral - das unterscheidet Metalle."""
    p, vao = _aufbauen(ctx, grundton=(0.95, 0.4, 0.15), metallic=1.0, rauheit=0.2)
    bild = _rendern(ctx, p, vao).reshape(-1, 3).mean(axis=0)
    assert bild[0] > bild[2] * 1.4, "die Spiegelung muss die Metallfarbe tragen"


def _kugel(ctx, programm):
    """Eine Kugel — auf einer ebenen Flaeche ist ein Glanzlicht nicht zu sehen.

    Die Normale ist dort ueberall dieselbe, das Glanzlicht also entweder auf
    der ganzen Flaeche oder nirgends. Erst gekruemmte Geometrie zeigt, wie
    gross und wie hell es ist.
    """
    import trimesh

    k = trimesh.creation.uv_sphere(radius=1.0, count=(64, 64))
    daten = np.hstack([
        np.asarray(k.vertices, dtype="f4"),
        np.asarray(k.vertex_normals, dtype="f4"),
        np.zeros((len(k.vertices), 2), dtype="f4"),
    ])
    vbo = ctx.buffer(np.ascontiguousarray(daten).tobytes())
    ibo = ctx.buffer(np.asarray(k.faces, dtype="u4").tobytes())
    return ctx.vertex_array(programm, [
        (vbo, "3f 3f 2f", "in_position", "in_normale", "in_uv")], ibo)


def _kugel_rendern(ctx, rauheit, metallic=0.0):
    from src.render3d import camera

    p = shader.programm(ctx)
    p["grundton"].value = (0.6, 0.6, 0.6)
    p["hat_basisfarbe"].value = 0.0
    p["hat_metallic_rauheit"].value = 0.0
    p["metallic_faktor"].value = metallic
    p["rauheit_faktor"].value = rauheit
    auge = (0.0, -4.0, 1.5)
    p["kamera_position"].value = auge
    mvp = camera.perspektive(40.0, 1.0, 0.1, 50.0) @ camera.blick(auge, (0, 0, 0))
    p["mvp"].write(mvp.T.astype("f4").tobytes())
    shader.modell_setzen(p, np.eye(4))

    vao = _kugel(ctx, p)
    ziel = ctx.simple_framebuffer((96, 96))
    ziel.use()
    ziel.clear(0.0, 0.0, 0.0, 1.0)
    ctx.enable(moderngl.DEPTH_TEST)
    vao.render()
    ctx.disable(moderngl.DEPTH_TEST)
    roh = np.frombuffer(ziel.read(components=3), dtype=np.uint8)
    return roh.reshape(96, 96, 3).astype(np.float64) / 255.0


def test_rauer_lack_glaenzt_weniger_als_glatter(ctx):
    """Die Rauheit muss ankommen, sonst ist metallicRoughness wirkungslos."""
    glatt = _kugel_rendern(ctx, rauheit=0.06)
    rau = _kugel_rendern(ctx, rauheit=0.95)
    assert glatt.max() > rau.max() + 0.02, \
        "eine glatte Kugel muss ein helleres Glanzlicht haben"


def test_das_glanzlicht_einer_glatten_kugel_ist_kleiner(ctx):
    """Glatt heisst konzentriert, rau heisst verteilt - dieselbe Energie."""
    glatt = _kugel_rendern(ctx, rauheit=0.06).max(axis=2)
    rau = _kugel_rendern(ctx, rauheit=0.95).max(axis=2)
    hell_glatt = float((glatt > 0.85 * glatt.max()).mean())
    hell_rau = float((rau > 0.85 * rau.max()).mean())
    assert hell_glatt < hell_rau, \
        f"glatt {hell_glatt:.3f} sollte kleiner sein als rau {hell_rau:.3f}"


def test_eine_abgewandte_flaeche_bekommt_noch_umgebungslicht(ctx):
    """Kein Schwarz im Schatten: der Himmel leuchtet von allen Seiten.

    Ohne Umgebungsanteil waeren alle sonnenabgewandten Flaechen des Fahrzeugs
    tiefschwarz - technisch richtig fuer eine einzelne Lichtquelle im leeren
    Raum, aber kein Bild, das jemand sehen will.
    """
    p = shader.programm(ctx)
    p["grundton"].value = (0.6, 0.6, 0.6)
    p["hat_basisfarbe"].value = 0.0
    p["hat_metallic_rauheit"].value = 0.0
    p["metallic_faktor"].value = 0.0
    p["rauheit_faktor"].value = 0.6
    p["kamera_position"].value = (0.0, 0.0, -3.0)
    p["sonne_richtung"].value = (0.0, 0.0, 1.0)        # Sonne genau dahinter
    p["mvp"].write(np.eye(4, dtype="f4").tobytes())
    shader.modell_setzen(p, np.eye(4))
    bild = _rendern(ctx, p, _flaeche(ctx, p))
    assert bild.mean() > 0.05, "die abgewandte Seite darf nicht schwarz sein"


def test_das_ergebnis_bleibt_im_darstellbaren_bereich(ctx):
    """Reinhard und Gamma: eine PBR-Rechnung liefert lineare Energie, die weit
    ueber 1 gehen kann. Ohne Abbildung brennen die Glanzlichter aus."""
    p, vao = _aufbauen(ctx, grundton=(1.0, 1.0, 1.0), metallic=1.0, rauheit=0.03)
    bild = _rendern(ctx, p, vao)
    assert bild.max() <= 1.0
    ausgebrannt = float((bild >= 0.999).mean())
    assert ausgebrannt < 0.5, f"{ausgebrannt:.0%} der Flaeche ist ausgebrannt"
