"""Bäume, Häuser, Banden und Berge zeichnen — instanziert, mit zwei LOD-Stufen.

Die Platzierung rechnet :mod:`src.render3d.platzierung`; hier wird nur
gezeichnet. Je Modell gibt es einen Instanzpuffer mit den Modellmatrizen der
sichtbaren Exemplare, und jedes Material jedes Modells ist **ein**
Zeichenaufruf, egal ob fünf oder fünfhundert Bäume dastehen.

Je Bild wird neu entschieden, was zu sehen ist:

* **Hinter der Kamera** oder deutlich außerhalb des Bildausschnitts: weg.
* **Nah**: volles Modell. **Fern** (ab ``lod_abstand_m`` aus dem Katalog):
  das vereinfachte ``_lod1``.
* **Weiter als die Sichtweite**: weg — der Nebel hat es ohnehin geschluckt.
  Die Kulisse (Berge, Skyline) ist davon ausgenommen.

numpy erledigt das für alle Exemplare auf einmal; bei tausend Objekten sind
das Bruchteile einer Millisekunde.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import grafik, mesh, shader

try:                                             # pragma: no cover - Importpfad
    import moderngl
except ImportError:                              # pragma: no cover
    moderngl = None

#: Ab hier wird gar nicht mehr gezeichnet (außer Kulisse), wenn die
#: Grafikstufe nichts sagt; sonst gilt ``grafik.aktuell().sichtweite_m``.
SICHTWEITE_M = 700.0
#: Schatten werfen nur Objekte in diesem Umkreis um den Blickpunkt.
SCHATTEN_RADIUS_M = 110.0


def katalog_laden(ordner: str | Path) -> dict:
    pfad = Path(ordner) / "katalog.json"
    try:
        with open(pfad, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def instanzmatrizen(pos: np.ndarray, gier: np.ndarray, skala: np.ndarray) -> np.ndarray:
    """(k, 16) float32, spaltenweise — so, wie GLSL ``mat4`` aus vier ``vec4`` baut."""
    k = len(pos)
    c, s = np.cos(gier), np.sin(gier)
    m = np.zeros((k, 4, 4), dtype=np.float32)
    m[:, 0, 0] = c * skala
    m[:, 0, 1] = -s * skala
    m[:, 1, 0] = s * skala
    m[:, 1, 1] = c * skala
    m[:, 2, 2] = skala
    m[:, 0, 3] = pos[:, 0]
    m[:, 1, 3] = pos[:, 1]
    m[:, 2, 3] = pos[:, 2]
    m[:, 3, 3] = 1.0
    return np.ascontiguousarray(m.transpose(0, 2, 1).reshape(k, 16))


@dataclass
class _Stufe:
    """Eine LOD-Stufe eines Modells, hochgeladen für Farbe und Schatten."""

    stuecke: list = field(default_factory=list)       # (vao, vao_schatten, material_index)
    materialien: list = field(default_factory=list)
    puffer: list = field(default_factory=list)
    instanzen: object = None
    #: Eigener Instanzpuffer für die Schattenkarte: so bleibt die Auswahl
    #: beider Durchgänge stehen, und unverändert wird nichts neu geschrieben.
    instanzen_schatten: object = None
    kapazitaet: int = 0
    #: Zuletzt geschriebene Auswahl je Durchgang (Maske) und ihre Anzahl.
    zuletzt: dict = field(default_factory=dict)

    def freigeben(self) -> None:
        for vao, vao_s, _m in self.stuecke:
            vao.release()
            vao_s.release()
        for m in self.materialien:
            for t in (m.basisfarbe, m.metallic_rauheit):
                if t is not None:
                    t.release()
        for p in self.puffer:
            p.release()
        for b in (self.instanzen, self.instanzen_schatten):
            if b is not None:
                b.release()


def _stufe_hochladen(ctx, programm, programm_schatten, daten: mesh.Modelldaten,
                     kapazitaet: int) -> _Stufe:
    stufe = _Stufe(kapazitaet=max(1, kapazitaet))
    stufe.instanzen = ctx.buffer(reserve=stufe.kapazitaet * 64, dynamic=True)
    stufe.instanzen_schatten = ctx.buffer(reserve=stufe.kapazitaet * 64, dynamic=True)
    stufe.materialien = mesh.materialien_hochladen(ctx, daten.materialien)
    inst = (stufe.instanzen, "4f 4f 4f 4f/i", "in_inst0", "in_inst1", "in_inst2", "in_inst3")
    inst_s = (stufe.instanzen_schatten, "4f 4f 4f 4f/i", "in_inst0", "in_inst1", "in_inst2", "in_inst3")
    for teil in daten.teile:
        for s in teil.stuecke:
            # Teile mit Versatz in die Punkte einrechnen: Instanzen kennen
            # nur eine Matrix.
            p = (s.positionen + teil.versatz).astype(np.float32)
            vp = ctx.buffer(np.ascontiguousarray(p).tobytes())
            vn = ctx.buffer(np.ascontiguousarray(s.normalen, dtype=np.float32).tobytes())
            vu = ctx.buffer(np.ascontiguousarray(s.uv, dtype=np.float32).tobytes())
            ib = ctx.buffer(np.ascontiguousarray(s.indizes, dtype=np.uint32).tobytes())
            stufe.puffer += [vp, vn, vu, ib]
            vao = ctx.vertex_array(programm, [(vp, "3f", "in_position"), (vn, "3f", "in_normale"),
                                              (vu, "2f", "in_uv"), inst], ib)
            vao_s = ctx.vertex_array(programm_schatten, [(vp, "3f", "in_position"),
                                                         (vu, "2f", "in_uv"), inst_s], ib)
            stufe.stuecke.append((vao, vao_s, s.material))
    return stufe


@dataclass
class _Dekomodell:
    name: str
    stufen: list
    lod_abstand: float
    #: Kleinteile (Hütchen, Publikum) enden früher als die Sichtweite.
    max_abstand: float
    schatten: bool
    kulisse: bool
    pos: np.ndarray
    matrizen: np.ndarray
    radius: np.ndarray
    #: Vorab gerechnet: (k, 4) mit w = 1 für den Sichttest.
    pos4: np.ndarray = None


def material_setzen(p, hm: mesh.HochgeladenesMaterial) -> None:
    m = hm.daten
    shader.setzen(p, "hat_basisfarbe", 1.0 if hm.basisfarbe is not None else 0.0)
    shader.setzen(p, "hat_metallic_rauheit", 1.0 if hm.metallic_rauheit is not None else 0.0)
    shader.setzen(p, "grundton", tuple(m.farbe))
    shader.setzen(p, "metallic_faktor", float(m.metallic))
    shader.setzen(p, "rauheit_faktor", float(m.rauheit))
    shader.setzen(p, "emission", tuple(m.emission))
    shader.setzen(p, "alpha_faktor", 1.0 if m.modus != "BLEND" else float(m.alpha))
    shader.setzen(p, "alpha_schwelle", float(m.schwelle) if m.modus == "MASK" else 0.0)
    shader.setzen(p, "klarlack", 0.0)
    if hm.basisfarbe is not None:
        hm.basisfarbe.use(0)
    if hm.metallic_rauheit is not None:
        hm.metallic_rauheit.use(1)


class Dekozeichner:
    """Alle platzierten Objekte einer Strecke."""

    def __init__(self, ctx, programm_instanz, schattenprogramm_instanz,
                 ordner: str | Path, platzierungen, kulisse_namen=()) -> None:
        self.ctx = ctx
        self.programm = programm_instanz
        self.schatten = schattenprogramm_instanz
        self.ordner = Path(ordner)
        self.katalog = katalog_laden(ordner)
        self.modelle: list[_Dekomodell] = []
        #: Helligkeit der Startampel, 0..1 — das Rennen schaltet sie im
        #: Countdown an und beim Start aus.
        self.ampel = 1.0
        self._kulisse = set(kulisse_namen)
        self._gruppen: dict[str, list] = {}
        for pl in platzierungen:
            self._gruppen.setdefault(pl.modell, []).append(pl)

    def schritte(self):
        """Modelle eins nach dem anderen laden — für den Ladebalken.

        Liefert je Modell einmal dessen Namen.
        """
        for name, liste in self._gruppen.items():
            yield name
            self._modell_laden(name, liste)

    def _modell_laden(self, name: str, liste) -> None:
        pfad = self.ordner / f"{name}.glb"
        if not pfad.is_file():
            print(f"[deko] Modell fehlt: {pfad}")
            return
        eintrag = self.katalog.get(name, {})
        pos = np.array([[p.x, p.y, p.z] for p in liste], dtype=np.float32)
        gier = np.array([p.gier_rad for p in liste], dtype=np.float32)
        skala = np.array([p.skala for p in liste], dtype=np.float32)
        stufen = [_stufe_hochladen(self.ctx, self.programm, self.schatten, mesh.laden(pfad), len(liste))]
        lod_pfad = self.ordner / f"{name}_lod1.glb"
        if eintrag.get("lod1") and lod_pfad.is_file():
            stufen.append(_stufe_hochladen(self.ctx, self.programm, self.schatten,
                                           mesh.laden(lod_pfad), len(liste)))
        radius = np.maximum(float(eintrag.get("radius_m", 2.0)),
                            float(eintrag.get("hoehe_m", 2.0)) * 0.5) * skala
        self.modelle.append(_Dekomodell(
            name=name, stufen=stufen, lod_abstand=float(eintrag.get("lod_abstand_m", 1e9)),
            max_abstand=float(eintrag.get("max_abstand_m", 1e9)),
            schatten=bool(eintrag.get("schatten", True)),
            kulisse=name in self._kulisse or not eintrag.get("schatten", True),
            pos=pos, matrizen=instanzmatrizen(pos, gier, skala), radius=radius,
            pos4=np.hstack([pos, np.ones((len(pos), 1), np.float32)])))

    def alles_laden(self) -> None:
        for _ in self.schritte():
            pass

    # -- Auswahl --------------------------------------------------------
    @staticmethod
    def _sichtbar(mvp: np.ndarray, pos: np.ndarray, radius: np.ndarray,
                  pos4: np.ndarray | None = None) -> np.ndarray:
        if pos4 is None:
            pos4 = np.hstack([pos, np.ones((len(pos), 1), np.float32)])
        h = pos4 @ np.asarray(mvp, np.float32).T
        # Grob, aber sicher: die Kugel um das Objekt, im Clipraum großzügig.
        r = radius * 2.0
        return (h[:, 3] > -r) & (np.abs(h[:, 0]) < h[:, 3] + r) & (np.abs(h[:, 1]) < h[:, 3] + r)

    def _schreiben(self, stufe: _Stufe, matrizen: np.ndarray, durchgang: str = "farbe",
                   maske: np.ndarray | None = None) -> int:
        """Instanzen hochladen — nur, wenn sich die Auswahl geändert hat.

        Mit ``maske`` sind ``matrizen`` alle Exemplare; ausgewählt wird erst,
        wenn sich die Maske gegenüber dem letzten Bild geändert hat.

        Die Kamera wandert, aber welche Bäume sichtbar sind, ändert sich nur
        alle paar Bilder. Unverändert bleibt der Puffer stehen.
        """
        puffer = stufe.instanzen_schatten if durchgang == "schatten" else stufe.instanzen
        if maske is not None:
            vorher = stufe.zuletzt.get(durchgang)
            if vorher is not None and vorher[0].shape == maske.shape and np.array_equal(vorher[0], maske):
                return vorher[1]
            matrizen = matrizen[maske]
        k = len(matrizen)
        if k == 0:
            return 0
        puffer.orphan(stufe.kapazitaet * 64)
        puffer.write(matrizen[: stufe.kapazitaet].tobytes())
        anzahl = min(k, stufe.kapazitaet)
        if maske is not None:
            stufe.zuletzt[durchgang] = (maske.copy(), anzahl)
        return anzahl

    def _buendeln(self) -> None:
        """Alle Exemplare aller Modelle in einem Feld — einmal nach dem Laden.

        Je Bild wird dann **einmal** für alle Exemplare gerechnet (Abstand,
        Sichtkegel) statt je Modell ein halbes Dutzend numpy-Aufrufe; bei
        zwanzig Modellen war das mehr als eine Millisekunde CPU je Bild.
        """
        if getattr(self, "_buendel_n", -1) == len(self.modelle):
            return
        self._buendel_n = len(self.modelle)
        if not self.modelle:
            self._b_pos4 = np.zeros((0, 4), np.float32)
            return
        self._b_pos4 = np.vstack([m.pos4 for m in self.modelle]).astype(np.float32)
        self._b_xy = np.ascontiguousarray(self._b_pos4[:, :2])
        self._b_radius = np.concatenate([m.radius for m in self.modelle]).astype(np.float32)
        grenzen = []
        self._b_bereich = []
        a = 0
        for m in self.modelle:
            b = a + len(m.pos)
            self._b_bereich.append((a, b))
            grenzen.append(np.full(b - a, np.inf if m.kulisse else m.max_abstand, np.float32))
            a = b
        self._b_max = np.concatenate(grenzen)
        self._b_kulisse = np.isinf(self._b_max)
        self._b_schatten_r2 = (SCHATTEN_RADIUS_M + self._b_radius) ** 2
        self._b_schatten = np.concatenate([np.full(len(m.pos), m.schatten) for m in self.modelle])

    def zeichnen(self, mvp, kamera_position, durchgang: str = "farbe",
                 fokus=None) -> None:
        """``durchgang``: ``"farbe"`` für das Bild, ``"schatten"`` für die Schattenkarte."""
        self._buendeln()
        if len(self._b_pos4) == 0:
            return
        auge = np.asarray(kamera_position, dtype=np.float32)[:2]
        sicht = float(getattr(grafik.aktuell(), "sichtweite_m", SICHTWEITE_M))
        d2_auge = ((self._b_xy - auge) ** 2).sum(axis=1)
        if durchgang == "schatten":
            f = np.asarray(fokus if fokus is not None else auge, dtype=np.float32)[:2]
            alle = self._b_schatten & (((self._b_xy - f) ** 2).sum(axis=1) < self._b_schatten_r2)
        else:
            grenze = np.minimum(self._b_max, sicht)
            alle = self._b_kulisse | (d2_auge < grenze * grenze)
            kandidaten = np.flatnonzero(alle)
            if len(kandidaten):
                alle[kandidaten] = self._sichtbar(mvp, None, self._b_radius[kandidaten],
                                                  self._b_pos4[kandidaten])
        if not alle.any():
            return
        for m, (a, b) in zip(self.modelle, self._b_bereich):
            auswahl = alle[a:b]
            if not auswahl.any():
                for stufe in m.stufen:
                    stufe.zuletzt.pop(durchgang, None)
                continue
            if len(m.stufen) > 1:
                nah = d2_auge[a:b] < m.lod_abstand * m.lod_abstand
                gruppen = ((m.stufen[0], auswahl & nah), (m.stufen[1], auswahl & ~nah))
            else:
                gruppen = ((m.stufen[0], auswahl),)
            if durchgang != "schatten":
                shader.setzen(self.programm, "nebel_faktor", 0.45 if m.kulisse else 1.0)
            for stufe, maske in gruppen:
                if not maske.any():
                    stufe.zuletzt.pop(durchgang, None)
                    continue
                anzahl = self._schreiben(stufe, m.matrizen, durchgang, maske)
                if anzahl == 0:
                    continue
                for vao, vao_s, mi in stufe.stuecke:
                    hm = stufe.materialien[mi] if mi < len(stufe.materialien) else None
                    if durchgang == "schatten":
                        maske_alpha = hm is not None and hm.daten.modus == "MASK" and hm.basisfarbe is not None
                        shader.setzen(self.schatten, "alpha_schwelle",
                                      hm.daten.schwelle if maske_alpha else 0.0)
                        if maske_alpha:
                            hm.basisfarbe.use(0)
                        vao_s.render(instances=anzahl)
                    else:
                        if hm is not None:
                            material_setzen(self.programm, hm)
                            if hm.daten.name == "ampel_rot":
                                shader.setzen(self.programm, "emission",
                                              tuple(c * self.ampel for c in hm.daten.emission))
                        vao.render(instances=anzahl)

    def freigeben(self) -> None:
        for m in self.modelle:
            for s in m.stufen:
                s.freigeben()
        self.modelle = []
