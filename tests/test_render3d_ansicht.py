"""Die Überlagerung: pygame-Fläche als Textur über die 3D-Szene.

Läuft gegen einen Standalone-Kontext, also ohne Fenster. Ist keiner zu
bekommen, werden die Tests übersprungen statt fehlzuschlagen — auf einem
Bauknecht ohne Grafiktreiber ist das kein Fehler des Codes.
"""
import numpy as np
import pygame
import pytest

from src.render3d import ansicht

moderngl = pytest.importorskip("moderngl")


@pytest.fixture(scope="module")
def ctx():
    try:
        kontext = moderngl.create_standalone_context()
    except Exception as fehler:                      # pragma: no cover
        pytest.skip(f"kein OpenGL-Kontext zu bekommen: {fehler}")
    yield kontext
    kontext.release()


def _flaeche(groesse, farbe, alpha=255):
    f = pygame.Surface(groesse, pygame.SRCALPHA)
    f.fill((*farbe, alpha))
    return f


def _gerendert(ctx, ueberlagerung, hintergrund=(0.0, 0.0, 0.0)):
    ziel = ctx.simple_framebuffer(ueberlagerung.groesse)
    ziel.use()
    ziel.clear(*hintergrund, 1.0)
    ueberlagerung.zeichnen()
    roh = np.frombuffer(ziel.read(components=3), dtype=np.uint8)
    breite, hoehe = ueberlagerung.groesse
    # framebuffer.read liefert Zeilen von unten nach oben.
    return roh.reshape(hoehe, breite, 3)[::-1]


def test_flaeche_als_bytes_hat_die_richtige_laenge():
    daten = ansicht.flaeche_als_bytes(_flaeche((8, 4), (10, 20, 30)))
    assert len(daten) == 8 * 4 * 4


def test_undurchsichtige_flaeche_deckt_den_hintergrund_zu(ctx):
    u = ansicht.Ueberlagerung(ctx, (16, 16))
    u.aktualisieren(_flaeche((16, 16), (255, 0, 0)))
    bild = _gerendert(ctx, u, hintergrund=(0.0, 0.0, 1.0))
    assert bild[..., 0].min() > 200, "Rot muss durchkommen"
    assert bild[..., 2].max() < 60, "Blau darf nicht durchscheinen"
    u.freigeben()


def test_vollstaendig_durchsichtige_flaeche_laesst_die_szene_stehen(ctx):
    u = ansicht.Ueberlagerung(ctx, (16, 16))
    u.aktualisieren(_flaeche((16, 16), (255, 0, 0), alpha=0))
    bild = _gerendert(ctx, u, hintergrund=(0.0, 0.0, 1.0))
    assert bild[..., 2].min() > 200, "der Hintergrund muss unveraendert bleiben"
    assert bild[..., 0].max() < 60
    u.freigeben()


def test_halbdurchsichtige_flaeche_mischt(ctx):
    u = ansicht.Ueberlagerung(ctx, (16, 16))
    u.aktualisieren(_flaeche((16, 16), (255, 0, 0), alpha=128))
    bild = _gerendert(ctx, u, hintergrund=(0.0, 0.0, 1.0))
    assert 90 < bild[..., 0].mean() < 165, "etwa halb Rot"
    assert 90 < bild[..., 2].mean() < 165, "etwa halb Blau"
    u.freigeben()


def test_das_hud_steht_nicht_auf_dem_kopf(ctx):
    """Die Falle, in die schon die Modelltexturen gelaufen sind.

    pygame legt Zeile 0 nach oben, OpenGL erwartet sie unten. Ohne Ausgleich
    erscheint das HUD gespiegelt - und weil ein Tachometer symmetrisch aussieht,
    faellt das erst auf, wenn Text darin steht.
    """
    f = pygame.Surface((16, 16), pygame.SRCALPHA)
    f.fill((255, 0, 0, 255))
    f.fill((0, 255, 0, 255), pygame.Rect(0, 0, 16, 4))    # oberer Streifen gruen

    u = ansicht.Ueberlagerung(ctx, (16, 16))
    u.aktualisieren(f)
    bild = _gerendert(ctx, u)
    oben = bild[:4].reshape(-1, 3).mean(axis=0)
    unten = bild[-4:].reshape(-1, 3).mean(axis=0)
    assert oben[1] > 200 and oben[0] < 60, "oben muss gruen sein"
    assert unten[0] > 200 and unten[1] < 60, "unten muss rot sein"
    u.freigeben()


def test_kanalreihenfolge_wird_gelesen_und_nicht_geraten():
    """Gegen die tatsaechlichen Bytes im Speicher geprueft.

    Eine Flaeche mit bekannten Farbwerten fuellen und nachsehen, welches Byte
    zuerst kommt. Stimmt die Erkennung nicht, waeren Rot und Blau im HUD
    vertauscht - ein Fehler, den man in der Farbwahl sucht und nicht in der
    Kanalreihenfolge.
    """
    f = pygame.Surface((4, 4), pygame.SRCALPHA)
    f.fill((10, 20, 30, 40))
    erstes_byte = bytes(memoryview(f.get_view("0"))[:1])[0]
    assert ansicht._ist_bgra(f) == (erstes_byte == 30)


def test_beide_wege_liefern_dasselbe_bild(ctx):
    """Der schnelle Weg ueber den Speicher und der langsame ueber tobytes.

    Sie duerfen sich nicht unterscheiden - sonst haengt das Aussehen davon ab,
    welches Flaechenformat gerade vorliegt.
    """
    f = pygame.Surface((16, 16), pygame.SRCALPHA)
    f.fill((200, 40, 10, 255))
    f.fill((10, 200, 40, 255), pygame.Rect(0, 0, 16, 5))
    assert ansicht.direkt_lesbar(f), "Vorbedingung: der schnelle Weg greift"

    u = ansicht.Ueberlagerung(ctx, (16, 16))
    u.aktualisieren(f)
    schnell = _gerendert(ctx, u)

    # Denselben Inhalt ueber den Rueckfallweg schicken.
    u._programm["bgra"].value = False
    u._textur.write(ansicht.flaeche_als_bytes(f))
    langsam = _gerendert(ctx, u)

    assert np.array_equal(schnell, langsam)
    u.freigeben()


def test_falsche_flaechengroesse_wird_gemeldet(ctx):
    u = ansicht.Ueberlagerung(ctx, (16, 16))
    with pytest.raises(ValueError, match="virtuelle"):
        u.aktualisieren(_flaeche((32, 32), (255, 0, 0)))
    u.freigeben()


def test_ueberlagerung_liegt_ueber_allem_unabhaengig_von_der_tiefe(ctx):
    """Ohne Tiefentest - sonst verschwindet das HUD hinter einem nahen Auto."""
    u = ansicht.Ueberlagerung(ctx, (16, 16))
    u.aktualisieren(_flaeche((16, 16), (255, 0, 0)))
    ziel = ctx.simple_framebuffer((16, 16))
    ziel.use()
    ziel.clear(0.0, 0.0, 1.0, 1.0)
    ctx.enable(moderngl.DEPTH_TEST)          # bewusst an, die Ueberlagerung
    u.zeichnen()                             # muss ihn selbst abschalten
    roh = np.frombuffer(ziel.read(components=3), dtype=np.uint8).reshape(16, 16, 3)
    assert roh[..., 0].min() > 200
    u.freigeben()


def test_ansicht_leert_und_setzt_die_himmelfarbe(ctx):
    a = ansicht.Ansicht3D(ctx, (16, 16))
    ziel = ctx.simple_framebuffer((16, 16))
    ziel.use()
    a.neues_bild(himmel=(0.0, 1.0, 0.0))
    roh = np.frombuffer(ziel.read(components=3), dtype=np.uint8).reshape(16, 16, 3)
    assert roh[..., 1].min() > 200 and roh[..., 0].max() < 60
    a.ueberlagerung.freigeben()


def test_hud_ohne_aenderung_zeichnet_die_alte_textur(ctx):
    """Spart den Upload von 8,3 MB je Bild, wenn sich am HUD nichts tut."""
    a = ansicht.Ansicht3D(ctx, (16, 16))
    ziel = ctx.simple_framebuffer((16, 16))
    ziel.use()
    ziel.clear(0.0, 0.0, 1.0, 1.0)
    a.hud_zeichnen(_flaeche((16, 16), (255, 0, 0)))
    ziel.clear(0.0, 0.0, 1.0, 1.0)
    a.hud_zeichnen(None, geaendert=False)          # None ist zulaessig, wenn nichts hochgeladen wird
    roh = np.frombuffer(ziel.read(components=3), dtype=np.uint8).reshape(16, 16, 3)
    assert roh[..., 0].min() > 200, "die vorhandene Textur muss erneut gezeichnet werden"
    a.ueberlagerung.freigeben()
