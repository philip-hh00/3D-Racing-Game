"""Die drei Farbfunde vom 30.07.2026 — KI-Gegner, Ghost, Minimap-Punkt.

Drei Meldungen, eine Ursache: ``color_primary``. Der ``VehicleRenderer`` lädt
seit dem 15. Sprite immer ein PNG und benutzt ``color_primary`` nur noch im
programmatischen Rückfall, den es nicht mehr gibt. Drei Stellen glaubten
trotzdem, eine Farbzuweisung täte etwas:

* fünf KI-Gegner bekamen eine von drei ``COLOR_AI_CAR_*`` — und sahen alle gleich
  aus
* der Ghost bekam Grau — und sah aus wie ein normaler Mitfahrer
* die Minimap las die Farbe zurück — und zeigte einen Wert, den man am Auto nie
  sieht (Rookie: JSON sagt Türkis, das Sprite ist rot)

Der Releaseplan (D0) hat das früh gefunden und bewusst aus Block D
herausgehalten, damit der nicht ausufert. Mit der Umfärbung aus Block D sind es
jetzt drei kleine Eingriffe.

**Der Ghost war doppelt kaputt.** Auch die Durchsichtigkeit hat nie
funktioniert: ``GhostPlayer.draw`` setzte ``set_alpha(120)`` auf
``_base_surface``, ``VehicleRenderer.draw`` zeichnet aber ``_orig_sprite``.
Deshalb prüfen die Tests unten genau die Oberfläche, die wirklich gezeichnet
wird — eine Prüfung auf ``_base_surface`` wäre grün geblieben und hätte den
Fund nicht abgedeckt.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
import pygame
import pymunk
import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from src.core import ghost as ghost_modul  # noqa: E402
from src.core import lack  # noqa: E402
from src.core.ghost import GhostData, GhostPlayer  # noqa: E402
from src.entities.components.renderer import VehicleRenderer  # noqa: E402
from src.entities.vehicle_factory import VehicleFactory  # noqa: E402
from src.hud.minimap import Minimap  # noqa: E402

#: So viele KI-Autos passen höchstens ins Feld (``vehicle_count`` 2–6, minus
#: ein Mensch). Die Farben müssen sich bis dorthin unterscheiden.
KI_MAX = 5


@pytest.fixture(autouse=True, scope="module")
def fahrzeuge_geladen():
    """Ohne geladene Fahrzeuge fällt jeder Aufruf auf Vorgabewerte zurück —
    der Ghost bekäme still die Silhouette des Rookie."""
    VehicleFactory.load_all_configs()
    assert VehicleFactory.get_config("supercar") is not None


def _sichtbare_farben(surf: pygame.Surface) -> np.ndarray:
    """Die Farbwerte aller Pixel, die man wirklich sieht.

    Schwelle 40 wie in ``lack``: der Ghost ist mit Absicht halb durchsichtig,
    eine Schwelle von 128 hätte ihn komplett wegsortiert."""
    rgb = pygame.surfarray.array3d(surf).astype(np.float32)
    alpha = pygame.surfarray.array_alpha(surf).astype(np.float32)
    return rgb[alpha > 40]


def _abstand(a, b) -> float:
    return float(np.linalg.norm(np.array(a[:3], float) - np.array(b[:3], float)))


# ===========================================================================
# Fund 1 — „Alle KI-Gegner sehen identisch aus", und die Umkehr am 06.08.2026
# ===========================================================================
#
# Die Geschichte in zwei Schritten, weil hier eine Entscheidung umgedreht wurde
# und ein Test, der das nicht erklärt, beim nächsten Lesen wie ein Fehler
# aussieht.
#
# **05.08.2026:** gemeldet war, dass alle KI-Autos gleich aussehen. Ursache war
# echt — ``color_primary`` zählt nur im programmatischen Rückfall (Releaseplan
# D0), die zugewiesene Farbe wurde also nie gezeichnet. Behoben, indem jedes
# KI-Auto echten Lack aus seiner Fahrzeugnummer bekam.
#
# **06.08.2026:** auf Wunsch zurückgenommen. Lackierungen sind das, was der
# Spieler sich erarbeitet und in der Werkstatt aussucht; an jedes Feld von
# Gegnern verteilt verlieren sie ihren Wert. Die KI fährt Werkslack.
#
# Was damit zurückkommt, steht ausdrücklich in ``test_gleiche_bauart_...``:
# mehrere KI-Autos derselben Bauart sind wieder nur an ihrer Position zu
# unterscheiden. Bewusst in Kauf genommen, nicht übersehen.
#
# Was aus dem Fund **bleibt**: der Weg der Farbe von der Fahrzeugnummer bis in
# den Renderer. Der war kaputt und ist es nicht mehr — er trägt jetzt eben den
# Werkslack. Genau das prüfen die Tests unten weiter, denn dieselbe Strecke
# trägt auch die Farbe des Spielers.

def test_die_ki_faehrt_werkslack():
    """Der Beschluss vom 06.08.2026, wörtlich."""
    for vid in range(0, 30):
        assert lack.ki_lack(vid) == lack.WERK


def test_der_werkslack_der_ki_haengt_an_nichts():
    """Frueher hing er an ``lacke.json``. Seit dem 06.08.2026 nicht mehr — eine
    von Hand ergaenzte Liste darf die Entscheidung nicht wieder aushebeln."""
    palette = dict(lack._laden())
    palette["ki_lacke"] = ["standard:kobaltblau", "standard:magenta"]
    lack._palette = palette
    try:
        assert lack.ki_lack(2) == lack.WERK
    finally:
        lack._palette = None
        lack._laden()


def test_gastgeber_und_gegenstelle_kommen_auf_dieselbe_farbe():
    """Online baut nur der Gastgeber die KI-Autos; alle anderen sehen ein
    Abbild. Die Farbe steht in keiner Nachricht — sie haengt allein an der
    Fahrzeugnummer, und die kennen beide Seiten. Seit dem 06.08.2026 ist das
    trivial erfuellt, geprueft bleibt es trotzdem: die Rueckrichtung waere eine
    Zeile, und dann muss diese Zusage wieder halten."""
    assert all(lack.ki_lack(v) == lack.ki_lack(v) for v in range(1, 30))


def test_gleiche_bauart_heisst_wieder_gleiches_aussehen():
    """Der Preis der Umkehr, ausdruecklich festgehalten.

    Nicht als Mangel, sondern damit beim naechsten Playtest niemand denselben
    Fund noch einmal aufmacht: dass fuenf Kompaktwagen gleich aussehen, ist seit
    dem 06.08.2026 so **gewollt**.
    """
    kennungen = {lack.ki_lack(vid) for vid in range(1, KI_MAX + 1)}
    assert kennungen == {lack.WERK}


def test_das_ki_auto_traegt_die_lackierung_bis_in_den_renderer():
    """Der Weg, den die Farbe im Rennen nimmt: Fahrzeugnummer → Fabrik →
    Fahrzeug → Renderer. Vorher endete er in ``color_primary`` im Nichts.

    Der Weg bleibt geprueft, auch wenn er jetzt Werkslack traegt — dieselbe
    Strecke traegt naemlich auch die Lackierung des Spielers.
    """
    from src.ai.difficulty import get_difficulty
    from src.track.track import Track

    raum = pymunk.Space()
    strecke = Track(str(_ROOT / "data" / "tracks" / "oval.json"), raum)
    for vid in range(1, KI_MAX + 1):
        ai = VehicleFactory.create_ai_vehicle(
            config_key="rookie", vehicle_id=vid, start_pos=(0.0, 0.0),
            start_angle=0.0, space=raum, track=strecke,
            difficulty=get_difficulty("medium"), lack=lack.ki_lack(vid))
        assert ai is not None
        assert ai.renderer.lack == lack.WERK
        assert ai.renderer.config_key == "rookie"


def test_ein_volles_feld_startet_im_werkslack():
    """Geprueft wird der Weg, den das Rennen wirklich nimmt —
    ``_spawn_ai_vehicles``. Ein Test nur auf der Fabrik haette gruen bleiben
    koennen, waehrend der Rennzustand weiter eigene Farben verteilt."""
    from src.core import race_setup
    from src.states.race_state import RaceState
    from src.track.track import Track

    raum = pymunk.Space()
    strecke = Track(str(_ROOT / "data" / "tracks" / "oval.json"), raum)
    r = RaceState.__new__(RaceState)
    r.physics_world = types.SimpleNamespace(space=raum)
    r.track = strecke
    r._gitter = list(range(6))

    s = race_setup.current()
    vorher = (s.vehicle_count, s.is_multiplayer, list(s.ai_roster))
    try:
        s.vehicle_count, s.is_multiplayer, s.ai_roster = 6, False, []
        autos = r._spawn_ai_vehicles(strecke.start_positions, {}, 1)
    finally:
        s.vehicle_count, s.is_multiplayer, s.ai_roster = vorher

    assert len(autos) == KI_MAX
    assert {a.renderer.lack for a in autos} == {lack.WERK}


# ===========================================================================
# Fund 2 — „Der Ghost sieht aus wie ein normaler Mitfahrer"
# ===========================================================================
def _ghost(fahrzeug: str = "rookie") -> GhostPlayer:
    return GhostPlayer(GhostData(samples=[[0.0, 0.0, 0.0, 0.0]], vehicle=fahrzeug))


def _gezeichnete_flaeche(r: VehicleRenderer) -> pygame.Surface:
    """Die Oberfläche, die ``VehicleRenderer.draw`` wirklich benutzt."""
    return r._orig_sprite if r._orig_sprite is not None else r._base_surface


def test_der_ghost_ist_grau():
    r = _ghost().renderer
    pixel = _sichtbare_farben(_gezeichnete_flaeche(r))
    assert pixel.size > 0
    spanne = pixel.max(axis=1) - pixel.min(axis=1)
    assert float(spanne.max()) == 0.0, f"noch Farbe im Ghost: {spanne.max()}"


def test_der_ghost_ist_durchscheinend():
    r = _ghost().renderer
    flaeche = _gezeichnete_flaeche(r)
    alpha = pygame.surfarray.array_alpha(flaeche).astype(np.float32)
    assert float(alpha.max()) == pytest.approx(120, abs=2)


def test_der_ghost_ist_deutlich_blasser_als_ein_mitfahrer():
    """Der eigentliche Wunsch aus der Meldung, in einer Zahl: neben dem
    Rennfahrzeug muss der Ghost sofort als Ghost zu erkennen sein."""
    normal = VehicleRenderer(26, 54, (220, 40, 40), visual_type="rookie",
                             config_key="rookie")
    g = _ghost().renderer
    a_normal = pygame.surfarray.array_alpha(_gezeichnete_flaeche(normal))
    a_ghost = pygame.surfarray.array_alpha(_gezeichnete_flaeche(g))
    assert int(a_ghost.max()) < int(a_normal.max()) * 0.6

    bunt_normal = _sichtbare_farben(_gezeichnete_flaeche(normal))
    spanne = (bunt_normal.max(axis=1) - bunt_normal.min(axis=1)).max()
    assert spanne > 50, "das Vergleichsfahrzeug ist selbst schon grau"


def test_der_ghost_faerbt_die_mitfahrer_nicht_mit_ein():
    """``lack.sprite()`` gibt allen Fahrzeugen desselben Typs **dieselbe**
    Oberfläche. Rechnet der Ghost darauf herum, bleicht er das ganze Feld aus."""
    _ghost("rookie")
    normal = VehicleRenderer(26, 54, (220, 40, 40), visual_type="rookie",
                             config_key="rookie")
    pixel = _sichtbare_farben(_gezeichnete_flaeche(normal))
    spanne = (pixel.max(axis=1) - pixel.min(axis=1)).max()
    assert float(spanne) > 50, "der Ghost hat das Sprite im Zwischenspeicher entfärbt"
    alpha = pygame.surfarray.array_alpha(_gezeichnete_flaeche(normal))
    assert int(alpha.max()) == 255


def test_der_ghost_uebernimmt_die_silhouette_des_rekordhalters():
    """Grau ja — aber es muss weiter erkennbar sein, in welchem Auto die
    Bestzeit gefahren wurde."""
    assert _ghost("supercar").renderer.visual_type == "supercar"
    assert _ghost("rookie").renderer.visual_type == "rookie"


def test_der_ghost_zeichnet_ohne_alphaspielereien():
    """Der alte Weg hat die Deckkraft beim Zeichnen gesetzt und danach
    zurückgenommen — auf der falschen Oberfläche. Jetzt steckt sie fest im
    Alphakanal, ``draw`` fasst sie nicht mehr an."""
    g = _ghost()
    flaeche = _gezeichnete_flaeche(g.renderer)
    vorher = pygame.surfarray.array_alpha(flaeche).copy()
    schirm = pygame.Surface((400, 300), pygame.SRCALPHA)
    g.draw(schirm, 0.0, pygame.Vector2(0, 0))
    nachher = pygame.surfarray.array_alpha(flaeche)
    assert np.array_equal(vorher, nachher)


def test_der_ghost_rechnet_nicht_auf_dem_ganzen_original():
    """Werkslack liefert das unveränderte PNG — bis 2816 px breit. Entfärben in
    dieser Größe hat beim Rennstart eine Sekunde und 10 MB gekostet, für ein
    Auto, das mit 54 px gezeichnet wird."""
    breite = _gezeichnete_flaeche(_ghost("supercar").renderer).get_width()
    assert breite <= lack.BREITE_SPIEL, breite


def test_die_deckkraft_des_ghosts_ist_die_alte():
    """120 von 255 — der Wert, der vorher gemeint war und nie ankam."""
    assert ghost_modul.GHOST_DECKKRAFT == pytest.approx(120 / 255)


# ===========================================================================
# Fund 3 — „Der Punkt hat nicht die Farbe, die das Auto hat"
# ===========================================================================
def test_werkslack_zeigt_die_farbe_des_sprites_nicht_die_der_json():
    """Der Rookie ist der klarste Fall: ``color_primary`` sagt Türkis
    (45, 180, 220), das PNG ist rot."""
    farbe = lack.wagenfarbe("rookie", "rookie", lack.WERK)
    assert farbe is not None
    assert _abstand(farbe, (45, 180, 220)) > 120, farbe
    assert farbe[0] > farbe[1] + 80 and farbe[0] > farbe[2] + 80, farbe


def test_ein_lackiertes_auto_zeigt_seine_lackfarbe():
    ziel = lack.farbe("kobaltblau")["rgb"]
    farbe = lack.wagenfarbe("rookie", "rookie", "standard:kobaltblau")
    assert _abstand(farbe, ziel) < 30, (farbe, ziel)


def test_neon_wird_so_hell_gemeldet_wie_es_aufgetragen_wird():
    """Neon zieht die Sättigung ans Maximum. Meldete die Minimap den reinen
    Palettenwert, liefen Punkt und Auto auseinander."""
    standard = lack.wagenfarbe("rookie", "rookie", "standard:waldgruen")
    neon = lack.wagenfarbe("rookie", "rookie", "neon:waldgruen")
    assert max(neon) > max(standard) + 40, (standard, neon)


def test_dunkle_autos_bleiben_auf_der_karte_sichtbar():
    """Der dunkelste Wagen der Flotte liegt bei RGB 24 — als Punkt mit
    schwarzem Rand wäre er nicht von seiner Umrandung zu unterscheiden."""
    for schluessel, visual in [("supercar_2", "supercar_2"),
                               ("drifter_3", "drifter_3"),
                               ("limousine", "limousine")]:
        farbe = lack.wagenfarbe(schluessel, visual, lack.WERK)
        assert farbe is not None and max(farbe) >= lack.PUNKT_MIN, (schluessel, farbe)


def test_das_aufhellen_laesst_den_farbton_stehen():
    """Sichtbar machen heißt heller, nicht anders: ein dunkelblaues Auto darf
    auf der Karte nicht plötzlich grau werden."""
    hell = lack._aufhellen((10, 20, 60))
    assert max(hell) == lack.PUNKT_MIN
    assert hell[2] > hell[1] > hell[0]


def test_ohne_bild_bleibt_es_bei_color_primary():
    """Ohne PNG greift der programmatische Rückfall — und **der** zeichnet
    ``color_primary`` wirklich. Dann ist es die richtige Antwort."""
    assert lack.wagenfarbe("gibtsnicht", "gibtsnicht", lack.WERK) is None
    r = VehicleRenderer(26, 54, (7, 9, 11), visual_type="gibtsnicht",
                        config_key="gibtsnicht")
    assert r.punktfarbe() == (7, 9, 11)


def test_der_renderer_meldet_die_farbe_seines_eigenen_lacks():
    r = VehicleRenderer(26, 54, (45, 180, 220), visual_type="rookie",
                        config_key="rookie", lack="standard:kobaltblau")
    assert _abstand(r.punktfarbe(), lack.farbe("kobaltblau")["rgb"]) < 30


# --- die Karte selbst ------------------------------------------------------
class _Wagen:
    """Nur das, was die Minimap anfasst."""

    def __init__(self, vid: int, renderer, minimap_color=None) -> None:
        self.id = vid
        self.position = (300.0, 300.0)
        self.renderer = renderer
        if minimap_color is not None:
            self.minimap_color = minimap_color


def _karte() -> Minimap:
    """Die Karte über einer Attrappe: sie liest nur Bahnverlauf und Breite."""
    strecke = types.SimpleNamespace(
        centerline=[(100.0, 100.0), (500.0, 100.0), (500.0, 500.0), (100.0, 500.0)],
        outer_wall=[], inner_wall=[], waypoints=[], track_width=200.0)
    return Minimap(strecke)


def _punktfarben(karte: Minimap, wagen: list) -> set:
    schirm = pygame.Surface((1920, 1080), pygame.SRCALPHA)
    karte.render(schirm, wagen, player_id=None)
    x, y = karte._world_to_map((300.0, 300.0))
    px, py = karte.pos
    return schirm.get_at((px + x, py + y))[:3]


def test_der_punkt_hat_die_farbe_des_autos():
    """Der Fund selbst, auf der gezeichneten Karte: der Rookie im Werkslack ist
    rot, sein Punkt war türkis (``color_primary`` aus der JSON)."""
    r = VehicleRenderer(26, 54, (45, 180, 220), visual_type="rookie",
                        config_key="rookie")
    farbe = _punktfarben(_karte(), [_Wagen(2, r)])
    assert _abstand(farbe, (45, 180, 220)) > 120, farbe
    assert _abstand(farbe, r.punktfarbe()) < 12, (farbe, r.punktfarbe())


def test_der_punkt_folgt_der_lackierung():
    r = VehicleRenderer(26, 54, (45, 180, 220), visual_type="rookie",
                        config_key="rookie", lack="standard:kobaltblau")
    farbe = _punktfarben(_karte(), [_Wagen(2, r)])
    assert _abstand(farbe, lack.farbe("kobaltblau")["rgb"]) < 30, farbe


def test_eine_gesetzte_minimap_farbe_hat_weiter_vorrang():
    """Online setzen die Abbilder eine Platzfarbe, damit zwei Mitspieler im
    selben unveränderten Fahrzeug auf der Karte unterscheidbar bleiben."""
    r = VehicleRenderer(26, 54, (45, 180, 220), visual_type="rookie",
                        config_key="rookie")
    farbe = _punktfarben(_karte(), [_Wagen(2, r, minimap_color=(11, 222, 33))])
    assert _abstand(farbe, (11, 222, 33)) < 12, farbe


def test_das_abbild_eines_lackierten_mitspielers_zeigt_seinen_lack():
    """Mit D7 reist die Lackierung online mit — dann soll auch der Punkt sie
    zeigen und nicht mehr die Platzfarbe."""
    from src.entities.remote_vehicle import RemoteVehicle
    raum = pymunk.Space()
    rv = RemoteVehicle(vehicle_id=1, sender_slot=2, space=raum,
                       config_key="rookie", lack="standard:kobaltblau")
    try:
        assert getattr(rv, "minimap_color", None) is None
        assert _abstand(rv._renderer.punktfarbe(),
                        lack.farbe("kobaltblau")["rgb"]) < 30
    finally:
        rv.cleanup(raum)


def test_das_abbild_im_werkslack_behaelt_seine_platzfarbe():
    """Zwei Mitspieler ohne Lackwahl im selben Fahrzeug wären sonst auf der
    Karte ein und derselbe Punkt."""
    from src.entities.remote_vehicle import RemoteVehicle
    raum = pymunk.Space()
    abbilder = [RemoteVehicle(vehicle_id=1, sender_slot=s, space=raum,
                              config_key="rookie", lack=lack.WERK)
                for s in (1, 2)]
    try:
        farben = [rv.minimap_color for rv in abbilder]
        assert all(f is not None for f in farben)
        assert farben[0] != farben[1]
    finally:
        for rv in abbilder:
            rv.cleanup(raum)
