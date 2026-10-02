"""Die Fahrzeuglänge wird einmal je Form gelesen, nicht je Kraftaufruf.

``shape.get_vertices()`` baut bei jedem Aufruf eine Liste von Vektoren; drei
Kraftberechnungen je Fahrzeug und Bild riefen es auf (gemessen: 27 Aufrufe je
Bild, 0,2 ms bei acht Autos).
"""
import pymunk

from src.entities.components.physics_body import PhysicsBody


def _koerper(vertices=None, **kw):
    raum = pymunk.Space()
    return PhysicsBody(1000.0, 30.0, 80.0, (0.0, 0.0), 0.0, raum, vertices=vertices, **kw), raum


def test_laenge_aus_dem_kasten():
    pb, _ = _koerper()
    assert pb.laenge_px() == 80.0


def test_laenge_aus_eigenen_ecken():
    pb, _ = _koerper(vertices=[(-40.0, -10.0), (50.0, -10.0), (50.0, 10.0), (-40.0, 10.0)])
    assert pb.laenge_px() == 90.0


def test_laenge_wird_nur_einmal_gelesen():
    pb, _ = _koerper()
    zaehler = []

    class Spion:
        def __init__(self, form):
            self._form = form

        def get_vertices(self):
            zaehler.append(1)
            return self._form.get_vertices()

        def __getattr__(self, name):
            return getattr(self._form, name)

    echte = pb.shape
    pb.shape = Spion(echte)
    for _ in range(5):
        pb.laenge_px()
    assert len(zaehler) == 1


def test_laenge_folgt_einer_ausgetauschten_form():
    pb, raum = _koerper()
    assert pb.laenge_px() == 80.0
    pb.shape = pymunk.Poly(pb.body, [(-100.0, -5.0), (100.0, -5.0), (100.0, 5.0), (-100.0, 5.0)])
    assert pb.laenge_px() == 200.0
