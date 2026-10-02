"""``StreckeFrenet.sd`` rechnet schneller, aber mit demselben Ergebnis wie vorher."""
import numpy as np

from src.ai.strecke_frenet import StreckeFrenet


def _strecke():
    w = np.linspace(0, 2 * np.pi, 200, endpoint=False)
    return StreckeFrenet(np.stack([900 * np.cos(w), 500 * np.sin(w) + 30 * np.sin(5 * w)], axis=1), 300.0)


def _alt(self, x, y, hinweis=None):
    if hinweis is None:
        idx = np.arange(self.n)
    else:
        idx = (int(hinweis) + np.arange(-40, 41)) % self.n
    a = self.punkte[idx]
    r = np.array([x, y], dtype=np.float64) - a
    u = np.clip(np.einsum("ij,ij->i", r, self.seg_dir[idx]), 0.0, self.seg_len[idx])
    naechst = a + self.seg_dir[idx] * u[:, None]
    abst = np.sum((np.array([x, y]) - naechst) ** 2, axis=1)
    k = int(np.argmin(abst))
    i = int(idx[k])
    rel = r[k]
    richt = self.seg_dir[i]
    d = float(richt[0] * rel[1] - richt[1] * rel[0])
    return self.wrap(self.s[i] + u[k]), d, i


def test_sd_wie_vorher_mit_und_ohne_hinweis():
    st = _strecke()
    zufall = np.random.default_rng(3)
    pts = st.xy_viele(zufall.uniform(0, st.laenge, 600), zufall.uniform(-120, 120, 600))
    hinweis = None
    for x, y in pts:
        assert st.sd(x, y) == _alt(st, x, y)
        neu = st.sd(x, y, hinweis if hinweis is not None else 7)
        assert neu == _alt(st, x, y, hinweis if hinweis is not None else 7)
        hinweis = neu[2]


def test_hinweis_ausserhalb_wird_umgebrochen():
    st = _strecke()
    assert st.sd(900.0, 0.0, st.n + 5) == _alt(st, 900.0, 0.0, 5)
