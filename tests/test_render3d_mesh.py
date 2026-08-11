"""GLB-Lader für den 3D-Renderer (src/render3d/mesh.py).

Zwei Schichten werden geprüft: das reine Laden (Datenverarbeitung, ohne
OpenGL-Kontext) und das Hochladen an OpenGL (braucht einen
Standalone-Kontext — ohne GPU wird der Test übersprungen statt zu scheitern).

Testmodelle werden synthetisch mit trimesh gebaut: eine Szene mit fünf
benannten Knoten (karosserie + vier Räder), PBR-Material mit
Basisfarbtextur. So hängt die Suite nicht am echten rookie.glb. Der ist
zusätzlich als Realitätscheck eingebunden, aber übersprungen, wenn die Datei
auf dieser Maschine fehlt.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import trimesh
from PIL import Image
from trimesh.visual.material import PBRMaterial
from trimesh.visual.texture import TextureVisuals

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.render3d import mesh  # noqa: E402

#: Das echte Testmodell — 24 MB, liegt nicht im Repo, aber ggf. auf der
#: Entwicklungsmaschine.
ROOKIE_GLB = Path(__file__).resolve().parents[1] / "assets" / "vehicles" / "rookie.glb"

#: Namen und Nabenversätze, wie sie radschnitt.als_szene() erzeugt.
KNOTEN = {
    "karosserie": (0.0, 0.0, 0.0),
    "rad_vl": (1.312, 0.930, 0.325),
    "rad_vr": (1.312, -0.930, 0.325),
    "rad_hl": (-1.312, 0.960, 0.325),
    "rad_hr": (-1.312, -0.940, 0.325),
}


def _box(mit_uv: bool = True, mit_textur: bool = True,
         mit_metallic: bool = True) -> trimesh.Trimesh:
    box = trimesh.creation.box(extents=(0.3, 0.3, 0.3))
    kwargs = {}
    if mit_textur:
        kwargs["baseColorTexture"] = Image.new("RGB", (16, 16), (200, 40, 40))
    if mit_metallic:
        kwargs["metallicRoughnessTexture"] = Image.new("RGB", (16, 16), (0, 128, 0))
    material = PBRMaterial(**kwargs)
    uv = None
    if mit_uv:
        uv = np.zeros((len(box.vertices), 2), dtype=np.float32)
        uv[:, 0] = np.linspace(0.0, 1.0, len(box.vertices))
    box.visual = TextureVisuals(uv=uv, material=material)
    return box


def _szene(mit_uv: bool = True, mit_textur: bool = True,
          mit_metallic: bool = True) -> trimesh.Scene:
    szene = trimesh.Scene()
    for name, versatz in KNOTEN.items():
        szene.add_geometry(
            _box(mit_uv=mit_uv, mit_textur=mit_textur, mit_metallic=mit_metallic),
            node_name=name, geom_name=name,
            transform=trimesh.transformations.translation_matrix(versatz))
    return szene


def _als_glb(szene: trimesh.Scene, ziel: Path, normalen: bool = True) -> Path:
    daten = trimesh.exchange.gltf.export_glb(szene, include_normals=normalen)
    ziel.write_bytes(daten)
    return ziel


@pytest.fixture
def glb_pfad(tmp_path) -> Path:
    return _als_glb(_szene(), tmp_path / "testauto.glb")


def test_fuenf_benannte_knoten_liefern_fuenf_teilnetze(glb_pfad):
    daten = mesh.laden(glb_pfad)
    namen = {t.name for t in daten.teile}
    assert namen == set(KNOTEN)
    assert len(daten.teile) == 5


def test_versatz_entspricht_knotenverschiebung_positionen_bleiben_lokal(glb_pfad):
    daten = mesh.laden(glb_pfad)
    rad_vl = daten.teil("rad_vl")
    assert rad_vl is not None
    np.testing.assert_allclose(rad_vl.versatz, KNOTEN["rad_vl"], atol=1e-5)
    # Die Box hat Kantenlaenge 0.3 m, ihre lokalen Positionen liegen also nahe
    # am eigenen Ursprung und keinesfalls in der Naehe des Versatzes.
    assert np.abs(rad_vl.positionen).max() < 0.2
    assert np.abs(rad_vl.positionen - rad_vl.versatz).max() > 1.0


def test_basisfarbtextur_kommt_an_mit_richtiger_groesse(glb_pfad):
    daten = mesh.laden(glb_pfad)
    assert daten.basisfarbe is not None
    assert daten.basisfarbe.size == (16, 16)


def test_metallic_rauheit_kommt_an(glb_pfad):
    daten = mesh.laden(glb_pfad)
    assert daten.metallic_rauheit is not None
    assert daten.metallic_rauheit.size == (16, 16)


def test_modell_ohne_textur_liefert_none_statt_zu_scheitern(tmp_path):
    pfad = _als_glb(_szene(mit_textur=False, mit_metallic=False),
                    tmp_path / "ohne_textur.glb")
    daten = mesh.laden(pfad)
    assert daten.basisfarbe is None
    assert daten.metallic_rauheit is None
    assert len(daten.teile) == 5


def test_fehlende_uv_werden_zu_nullen_ergaenzt(tmp_path):
    pfad = _als_glb(_szene(mit_uv=False), tmp_path / "ohne_uv.glb")
    daten = mesh.laden(pfad)
    for teil in daten.teile:
        assert teil.uv.shape == (teil.positionen.shape[0], 2)
        np.testing.assert_array_equal(teil.uv, 0.0)


def test_normalen_sind_auf_laenge_1(glb_pfad):
    daten = mesh.laden(glb_pfad)
    for teil in daten.teile:
        laengen = np.linalg.norm(teil.normalen, axis=1)
        np.testing.assert_allclose(laengen, 1.0, atol=1e-4)


def test_fehlende_normalen_werden_berechnet(tmp_path):
    pfad = _als_glb(_szene(), tmp_path / "ohne_normalen.glb", normalen=False)
    daten = mesh.laden(pfad)
    for teil in daten.teile:
        assert teil.normalen.shape == teil.positionen.shape
        laengen = np.linalg.norm(teil.normalen, axis=1)
        np.testing.assert_allclose(laengen, 1.0, atol=1e-4)


def test_indexform_ist_mx3_uint32(glb_pfad):
    daten = mesh.laden(glb_pfad)
    for teil in daten.teile:
        assert teil.indizes.dtype == np.uint32
        assert teil.indizes.ndim == 2
        assert teil.indizes.shape[1] == 3


def test_dreiecksanzahl_bleibt_beim_laden_erhalten(tmp_path):
    box = _box()
    szene = trimesh.Scene()
    szene.add_geometry(box, node_name="karosserie", geom_name="karosserie")
    pfad = _als_glb(szene, tmp_path / "einzelteil.glb")

    daten = mesh.laden(pfad)
    teil = daten.teil("karosserie")
    assert teil is not None
    assert teil.indizes.shape[0] == len(box.faces)


def test_teil_unbekannter_name_liefert_none(glb_pfad):
    daten = mesh.laden(glb_pfad)
    assert daten.teil("gibtsnicht") is None


@pytest.mark.skipif(not ROOKIE_GLB.is_file(),
                    reason="rookie.glb liegt nicht im Repo (grosses Binaerasset)")
def test_echtes_rookie_glb_liefert_fuenf_teile_mit_erwarteten_groessen():
    daten = mesh.laden(ROOKIE_GLB)
    assert len(daten.teile) == 5
    assert {t.name for t in daten.teile} == {
        "karosserie", "rad_vl", "rad_vr", "rad_hl", "rad_hr"}

    karosserie = daten.teil("karosserie")
    assert karosserie.indizes.shape[0] > 100_000

    assert daten.basisfarbe is not None
    assert daten.basisfarbe.size == (2048, 2048)


def _standalone_kontext():
    import moderngl
    try:
        return moderngl.create_standalone_context()
    except Exception:
        return None


def test_hochladen_erzeugt_vaos_und_texturen_im_standalone_kontext(glb_pfad):
    moderngl = pytest.importorskip("moderngl")
    ctx = _standalone_kontext()
    if ctx is None:
        pytest.skip("Kein OpenGL-Standalone-Kontext auf dieser Maschine verfuegbar")
    try:
        programm = ctx.program(
            vertex_shader="""
                #version 330
                in vec3 in_position;
                in vec3 in_normale;
                in vec2 in_uv;
                void main() {
                    gl_Position = vec4(in_position + in_normale, 1.0 + in_uv.x);
                }
            """,
            fragment_shader="""
                #version 330
                out vec4 farbe;
                void main() {
                    farbe = vec4(1.0);
                }
            """,
        )
        daten = mesh.laden(glb_pfad)
        modell = mesh.hochladen(ctx, programm, daten)

        assert len(modell.teile) == 5
        for teil in modell.teile:
            assert isinstance(teil.vao, moderngl.VertexArray)
            assert teil.versatz.shape == (3,)
        assert isinstance(modell.basisfarbe, moderngl.Texture)
        assert isinstance(modell.metallic_rauheit, moderngl.Texture)
        assert modell.teil("rad_hr") is not None
        assert modell.teil("gibtsnicht") is None
    finally:
        ctx.release()


def _bild_oben_blau_unten_rot(groesse: int = 64) -> Image.Image:
    """Testbild mit eindeutiger Ober- und Unterhälfte.

    PIL-Zeile 0 ist die Oberkante: die oberen Zeilen (Index < groesse/2)
    werden blau, die unteren rot.
    """
    daten = np.zeros((groesse, groesse, 3), dtype=np.uint8)
    daten[: groesse // 2, :, 2] = 255       # obere Haelfte: blau
    daten[groesse // 2 :, :, 0] = 255       # untere Haelfte: rot
    return Image.fromarray(daten, mode="RGB")


def test_hochgeladene_textur_zeigt_untere_bildhaelfte_bei_v_zwischen_0_und_04():
    """Regressionstest für den Vertikal-Flip beim Texturupload.

    ``trimesh``/OpenGL-Konvention: ``v = 0`` ist die Unterkante des Bildes.
    Ein Quadrat, dessen UV komplett im Bereich ``v = 0.0 … 0.4`` liegt, muss
    deshalb die **untere** Bildhälfte zeigen (hier rot) — nicht die obere
    (blau). Ohne den Ausgleich in ``mesh._textur_hochladen`` käme blau heraus,
    siehe VEREINBARUNGEN.md, Abschnitt "Texturkoordinaten".
    """
    moderngl = pytest.importorskip("moderngl")
    ctx = _standalone_kontext()
    if ctx is None:
        pytest.skip("Kein OpenGL-Standalone-Kontext auf dieser Maschine verfuegbar")
    try:
        programm = ctx.program(
            vertex_shader="""
                #version 330
                in vec3 in_position;
                in vec3 in_normale;
                in vec2 in_uv;
                out vec2 v_uv;
                out float v_helligkeit;
                void main() {
                    // Haelt in_normale wirksam am Leben (0.0 * n wuerde der
                    // Compiler wegoptimieren, das Attribut verschwaende dann
                    // und ctx.vertex_array wirft KeyError).
                    v_helligkeit = 0.5 + 0.5 * abs(normalize(in_normale).z);
                    v_uv = in_uv;
                    gl_Position = vec4(in_position.xy, 0.0, 1.0);
                }
            """,
            fragment_shader="""
                #version 330
                uniform sampler2D u_textur;
                in vec2 v_uv;
                in float v_helligkeit;
                out vec4 farbe;
                void main() {
                    farbe = texture(u_textur, v_uv) * v_helligkeit;
                }
            """,
        )

        # Ein Quadrat, das den ganzen Viewport fuellt; alle Normalen zeigen
        # nach +Z, also v_helligkeit == 1.0 - beeinflusst die Farbe nicht,
        # haelt aber das Attribut lebendig. UV liegt komplett im Bereich
        # v = 0.0 .. 0.4.
        positionen = np.array([
            [-1.0, -1.0, 0.0],
            [1.0, -1.0, 0.0],
            [1.0, 1.0, 0.0],
            [-1.0, 1.0, 0.0],
        ], dtype=np.float32)
        normalen = np.tile(np.array([0.0, 0.0, 1.0], dtype=np.float32), (4, 1))
        uv = np.array([
            [0.0, 0.2],
            [1.0, 0.2],
            [1.0, 0.2],
            [0.0, 0.2],
        ], dtype=np.float32)
        indizes = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.uint32)
        versatz = np.zeros(3, dtype=np.float32)

        teilnetz = mesh.Teilnetz(
            name="quadrat", positionen=positionen, normalen=normalen, uv=uv,
            indizes=indizes, versatz=versatz)
        daten = mesh.Modelldaten(
            teile=[teilnetz],
            basisfarbe=_bild_oben_blau_unten_rot(),
            metallic_rauheit=None)

        modell = mesh.hochladen(ctx, programm, daten)

        groesse = (8, 8)
        fbo = ctx.framebuffer(color_attachments=[ctx.texture(groesse, 4)])
        fbo.use()
        ctx.clear(0.0, 0.0, 0.0, 1.0)
        modell.basisfarbe.use(location=0)
        programm["u_textur"] = 0
        modell.teil("quadrat").vao.render()

        pixel = np.frombuffer(fbo.read(components=4), dtype=np.uint8)
        pixel = pixel.reshape(groesse[1], groesse[0], 4)
        durchschnitt = pixel[:, :, :3].reshape(-1, 3).mean(axis=0)

        assert durchschnitt[0] > 200, f"erwartet rot, bekommen {durchschnitt}"
        assert durchschnitt[2] < 50, f"erwartet rot, bekommen {durchschnitt}"
    finally:
        ctx.release()
