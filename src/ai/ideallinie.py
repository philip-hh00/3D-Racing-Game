"""Die Ideallinie der KI als Anzeige für den Menschen (Plan 1.1.0, Fahrhilfen).

Gezeigt wird dieselbe Linie, die ein KI-Auto fährt: der ``Fahrplan`` aus
``fahrplan.py`` (Versatz zur Mittellinie ``d_ideal`` und Zieltempo ``v_ziel``).
Gefärbt wird nach der **Tempoänderung** entlang der Linie:

* **grün** — Gas: das Tempo steigt oder die Stelle wird voll gefahren,
* **gelb** — Gas weg, rollen lassen: Tempo hält sich unter dem Höchsttempo,
  also Kurvengrenze,
* **rot** — Bremsen: das Zieltempo fällt spürbar.

Ein Mensch sieht die Farben weit voraus; Gelb und Rot beginnen deshalb nur
wenig (``VORLAUF_S`` Sekunden bei dem Tempo dort) *vor* der Stelle, an der das
Zieltempo wirklich fällt. Das Zieltempo ist das der KI, begrenzt durch das,
was Motor und Traktion des Autos hergeben (``antriebsprofil``). Als Stufe dient *Profi* statt *Meister*: etwas
Reserve in den Bremspunkten, sonst fährt der Hilfsbedürftige am Limit eines
Meisters.

Rein Zahlen (numpy), kein OpenGL — gezeichnet wird in ``render3d/ideallinie.py``.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.core.settings import M_PER_PX

GRUEN, GELB, ROT = 0, 1, 2
FARBEN = np.array([(0.06, 0.80, 0.18), (1.0, 0.68, 0.0), (1.0, 0.03, 0.02)], dtype=np.float32)

#: Abstand der Stützpunkte der Anzeige (m).
ABSTAND_M = 1.0
#: Wie viel der Bremsfähigkeit die Verzögerung des Profils mindestens haben muss,
#: damit die Stelle rot ist; und ab welchem Anstieg sie grün ist.
ROT_AB = 0.30
GRUEN_AB = 0.02
#: Anteil des Höchsttempos der Linie, ab dem eine Stelle als Vollgas gilt.
VOLLGAS_AB = 0.965
#: Vorlauf (s) und Grenzen (m) für Gelb und Rot vor der Stelle.
VORLAUF_S = 0.12
VORLAUF_MIN_M = 3.0
VORLAUF_MAX_M = 10.0


@dataclass
class Ideallinie:
    xy_m: np.ndarray        # (n, 2) Punkte der Linie, Meter
    bogen_m: np.ndarray     # (n,) Weg entlang der Linie
    tempo_ms: np.ndarray    # (n,) Zieltempo, m/s
    klasse: np.ndarray      # (n,) GRUEN / GELB / ROT
    laenge_m: float

    @property
    def farben(self) -> np.ndarray:
        return FARBEN[self.klasse]

    def klasse_bei(self, bogen_m: float) -> int:
        i = int(np.searchsorted(self.bogen_m, bogen_m % self.laenge_m)) % len(self.klasse)
        return int(self.klasse[i])


def klassen_aus_profil(v_pxs: np.ndarray, schritt_px: float, a_brems_pxs2: float) -> np.ndarray:
    """Grün, Gelb, Rot je Punkt aus dem Zieltempo (px/s) einer geschlossenen Linie."""
    v = np.asarray(v_pxs, dtype=np.float64)
    n = len(v)
    a_ref = max(float(a_brems_pxs2), 1e-6)
    # Beschleunigung an der Stelle k (zum nächsten Punkt), als Anteil der Bremsfähigkeit.
    a_lok = (np.roll(v, -1) ** 2 - v ** 2) / (2.0 * schritt_px) / a_ref
    # Das Profil ist an Kanten geglättet; ein Fenster von 3 Punkten beruhigt Ausreißer.
    a_lok = np.convolve(np.concatenate([a_lok[-1:], a_lok, a_lok[:1]]), np.ones(3) / 3.0, mode="valid")
    v_max = float(np.max(v)) if n else 1.0
    klasse = np.full(n, GELB, dtype=np.int8)
    klasse[(a_lok > GRUEN_AB) | (v >= VOLLGAS_AB * v_max)] = GRUEN
    klasse[a_lok < -ROT_AB] = ROT

    # Vorlauf: die Warnung kommt eher, je nach Tempo dort.
    schritt_m = schritt_px * M_PER_PX
    aus = klasse.copy()
    for k in np.nonzero(klasse != GRUEN)[0]:
        lauf_m = float(np.clip(VORLAUF_S * v[k] * M_PER_PX, VORLAUF_MIN_M, VORLAUF_MAX_M))
        zurueck = int(round(lauf_m / schritt_m))
        idx = (k - np.arange(1, zurueck + 1)) % n
        aus[idx] = np.maximum(aus[idx], klasse[k])      # Rot vor Gelb vor Grün
    # Einzelne Ausreißer (1-2 Punkte) glätten: Mehrheit im Fenster von 5.
    fenster = np.stack([np.roll(aus, s) for s in (-2, -1, 0, 1, 2)])
    mehr = np.stack([(fenster == c).sum(axis=0) for c in (GRUEN, GELB, ROT)])
    mehrheit = np.argmax(mehr, axis=0).astype(np.int8)
    st = mehr.max(axis=0) >= 3
    return np.where(st, mehrheit, aus).astype(np.int8)


def antriebsprofil(v_grenze: np.ndarray, schritt_px: float, grenzen) -> np.ndarray:
    """Das Tempo, das das Auto auf der Linie wirklich erreicht (px/s).

    ``Fahrplan.v_ziel`` ist die Obergrenze aus Kurven und Bremsen; hinter einer
    Kehre springt sie sofort hoch. Ein Auto beschleunigt aber nur so schnell,
    wie Motor und Traktion es zulassen (``VehicleLimits.beschleunigung``) —
    sonst wäre jede Gerade eine einzige Bremszone. Das Ergebnis liegt nie über
    der Grenze, also bleibt jede Bremsung machbar.
    """
    v = np.asarray(v_grenze, dtype=np.float64).copy()
    n = len(v)
    for _ in range(3):                       # geschlossene Strecke: Start/Ziel einschwingen
        for k in range(2 * n):
            i, j = k % n, (k + 1) % n
            grenze = np.sqrt(v[i] * v[i] + 2.0 * grenzen.beschleunigung(v[i]) * schritt_px)
            if v[j] > grenze:
                v[j] = grenze
    return v


def aus_fahrplan(plan, abstand_m: float = ABSTAND_M, config=None, stufe=None) -> Ideallinie:
    """Die Anzeigelinie zu einem ``Fahrplan`` (siehe ``fahrplan.fahrplan_bauen``).

    Mit ``config`` wird das Tempo durch die Antriebsgrenzen des Autos begrenzt
    (siehe :func:`antriebsprofil`); ohne bleibt es die reine Obergrenze.
    """
    st = plan.strecke
    schritt_px = abstand_m / M_PER_PX
    n = max(8, int(np.ceil(st.laenge / schritt_px)))
    schritt_px = st.laenge / n
    s = np.arange(n, dtype=np.float64) * schritt_px
    d = plan.d_viele(s)
    xy_px = st.xy_viele(s, d)
    v = plan.v_viele(s)
    if config is not None:
        from src.ai.speed_profile import limits_from_config
        kw = {} if stufe is None else dict(grip_usage=stufe.haftung, brake_confidence=stufe.bremsen)
        v = antriebsprofil(v, schritt_px, limits_from_config(config, mit_antriebstabelle=True, **kw))
    klasse = klassen_aus_profil(v, schritt_px, float(plan.a_brems))
    return Ideallinie(xy_m=xy_px * M_PER_PX, bogen_m=s * M_PER_PX, tempo_ms=v * M_PER_PX,
                      klasse=klasse, laenge_m=st.laenge * M_PER_PX)


def fuer_fahrzeug(strecke, config, stufe=None) -> Ideallinie:
    """Anzeigelinie dieses Fahrzeugs auf dieser Strecke (nutzt den Zwischenspeicher der KI)."""
    from src.ai.fahrplan import fahrplan_bauen
    from src.ai.stufen import STUFEN
    stufe = stufe or STUFEN["hard"]
    return aus_fahrplan(fahrplan_bauen(strecke, config, stufe), config=config, stufe=stufe)
