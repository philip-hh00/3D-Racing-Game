"""Entwurfsbilder fuer die Klang-Seite im Fahrzeuglabor (Block C, Motorsound).

Drei Varianten derselben Seite, festgelegt im Gespraech vom 02.08.2026:

* zwei Ebenen -- Werte des Motortyps (4zyl/6zyl/8zyl/elektro) und die zwei
  Werte des einzelnen Fahrzeugs,
* Drehzahl von Hand plus Gangwechsel, bei dem die Drehzahl springt wie im
  Rennen,
* vier Werkzeuge gegen das Knistern: Begrenzer, Hochpass, weichere
  Blockgrenzen, einstellbare Schichtueberblendung,
* angezeigt wird Wellenform und Spektrum -- kein Pegelbalken, kein Zaehler.

Wie beim Lack-Entwurf ist nichts davon gemalt: Wellenform und Spektrum kommen
aus ``src.core.sfx.Motorstimme`` und damit aus den echten Aufnahmen, die
Gangsprünge aus den echten Uebersetzungen der Fahrzeug-JSON. Das ist auch der
Zweck des Skripts ueber die Entwurfsphase hinaus -- eine Aenderung an Blende,
Blocklaenge oder Faerbung laesst sich damit ansehen, ohne das Spiel zu starten.

    python tools/klang_entwurf.py            # nach Documentation/entwurf/
    python tools/klang_entwurf.py /tmp/x     # woanders hin

Braucht numpy, pygame und soundfile; laeuft ohne Bildschirm (SDL-Dummy).
"""
from __future__ import annotations

import math
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import numpy as np
import pygame

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

pygame.init()
pygame.display.set_mode((1920, 1080))

from src.core import sfx  # noqa: E402
from src.ui import theme  # noqa: E402

W, H = 1920, 1080
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join("Documentation", "entwurf")

#: Das Fahrzeug in allen drei Bildern -- ein Achtzylinder, weil dort die
#: meisten Schichten liegen und das Knistern am ehesten auffaellt.
FZG_KEY = "supercar"
FZG_NAME = "Rennwagen"
MOTOR = "8zyl"
UPM = 3200.0
GANG = 3


# ---------------------------------------------------------------------------
# Echter Klang: Block, Wellenform, Spektrum
# ---------------------------------------------------------------------------
def block(upm: float, *, laenge: int = 2048, tonhoehe: float = 0.96,
          faerbung: float = 0.06, vorlauf: int = 6) -> np.ndarray:
    """Ein Block Motorklang, wie ihn das Rennen erzeugen wuerde.

    *vorlauf* Bloecke werden verworfen: die Stimme faengt bei Drehzahl 0 an und
    fuehrt die Drehzahl ueber den Block, der erste Block klingt deshalb nicht
    wie der eingeschwungene Zustand.
    """
    stimme = sfx.Motorstimme(MOTOR, tonhoehe, faerbung)
    for _ in range(vorlauf):
        stimme.block(upm, laenge)
    return stimme.block(upm, laenge)


def spektrum(b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(Frequenzen, Pegel in dB) eines Blocks, gefenstert."""
    fenster = np.hanning(len(b))
    x = np.abs(np.fft.rfft(b * fenster)) / (len(b) / 2)
    f = np.fft.rfftfreq(len(b), 1.0 / sfx.SR)
    db = 20.0 * np.log10(np.maximum(x, 1e-6))
    return f, db


def gangsprung(upm: float, gang: int, d: int) -> tuple[int, float]:
    """Gang wechseln und die Drehzahl mitnehmen -- wie das Getriebe im Rennen.

    Hochschalten faellt die Drehzahl im Verhaeltnis der Uebersetzungen, runter
    steigt sie. Genau dieser Sprung ist der Verdaechtige: die Tonhoehe springt
    mitten in einem Block, und die Schichtmischung wechselt gleich mit.
    """
    from src.entities.vehicle_factory import VehicleFactory
    if not VehicleFactory.get_available_configs():
        VehicleFactory.load_all_configs("data/vehicles")
    cfg = VehicleFactory.get_config(FZG_KEY)
    r = list(getattr(cfg, "gear_ratios", [1.0]))
    neu = max(1, min(len(r), gang + d))
    return neu, upm * (r[neu - 1] / r[gang - 1])


# ---------------------------------------------------------------------------
# Zeichenhelfer -- Optik wie tools/lack_entwurf.py, damit die Entwuerfe
# untereinander vergleichbar bleiben
# ---------------------------------------------------------------------------
_schild: dict[str, tuple[str, str, str]] = {}


def variantenschild(nr, titel, untertitel):
    _schild["aktuell"] = (nr, titel, untertitel)


def mit_band(s: pygame.Surface) -> pygame.Surface:
    nr, titel, untertitel = _schild.get("aktuell", ("?", "", ""))
    band = 104
    out = pygame.Surface((W, H + band))
    out.fill((8, 9, 14))
    out.blit(s, (0, 0))
    pygame.draw.line(out, theme.ACCENT_DIM, (0, H), (W, H), 2)
    theme.text(out, f"VARIANTE {nr}  —  {titel}", theme.HEADER, theme.ACCENT, (40, H + 18))
    theme.text(out, untertitel, theme.BODY, theme.TEXT_DIM, (40, H + 62), max_w=W - 80)
    return out


def laborkopf(s, *, ungespeichert=True):
    """Kopfzeile und Reiter -- dieselbe Leiste wie auf der Lackier-Seite,
    nur um KLANG verlaengert."""
    s.fill((14, 15, 24))
    theme.text(s, f"FAHRZEUG-LABOR — {FZG_NAME}  ({FZG_KEY})", theme.HEADER,
               theme.ACCENT, (40, 24))
    zusatz = "   ·   *ungespeichert*" if ungespeichert else ""
    theme.text(s, f"KLANG   ·   Fahrzeug 4 / 15   ·   Motor {MOTOR}{zusatz}",
               theme.SMALL, theme.TEXT_DIM, (44, 74))
    reiter = ["PHYSIK", "MOTORKURVE", "GETRIEBE", "LACKIERUNG", "KLANG"]
    x = 1074
    for i, r in enumerate(reiter):
        rect = pygame.Rect(x, 28, 158, 42)
        an = (r == "KLANG")
        pygame.draw.rect(s, (58, 48, 20) if an else (24, 27, 36), rect, border_radius=5)
        pygame.draw.rect(s, theme.ACCENT if an else theme.BORDER, rect,
                         2 if an else 1, border_radius=5)
        theme.text_fit(s, r, theme.SMALL, theme.TEXT if an else theme.TEXT_FAINT,
                       rect.inflate(-8, -8), center=True)
        x += 166


def kasten(s, r: pygame.Rect, titel, *, farbe=theme.BORDER, unter=""):
    pygame.draw.rect(s, (10, 12, 20), r, border_radius=6)
    pygame.draw.rect(s, farbe, r, 1, border_radius=6)
    if titel:
        theme.text(s, titel, theme.HINT, theme.TEXT_DIM, (r.x + 12, r.y + 9))
    if unter:
        theme.text(s, unter, theme.SMALL, theme.TEXT_FAINT, (r.x + 12, r.bottom - 24))


def w_stepper(s, r: pygame.Rect, label, value, *, fokus=False, an=True):
    pygame.draw.rect(s, theme.PANEL_SEL if fokus else theme.PANEL_LIGHT, r, border_radius=8)
    pygame.draw.rect(s, theme.ACCENT if fokus else theme.BORDER, r, 2, border_radius=8)
    sz = 46
    if not label:
        links = pygame.Rect(r.x + 6, r.y + 6, sz, r.height - 12)
        rechts = pygame.Rect(r.right - sz - 6, r.y + 6, sz, r.height - 12)
    else:
        sel_w = min(250, r.width // 2)
        links = pygame.Rect(r.right - sel_w, r.y + 6, sz, r.height - 12)
        rechts = pygame.Rect(r.right - sz - 6, r.y + 6, sz, r.height - 12)
        theme.text_fit(s, label, theme.BODY, theme.TEXT if an else theme.DISABLED,
                       pygame.Rect(r.x + 18, r.y, links.left - r.x - 26, r.height))
    acol = theme.ACCENT if an else theme.DISABLED
    theme.text(s, "‹", theme.HEADER, acol, links.center, center=True)
    theme.text(s, "›", theme.HEADER, acol, rechts.center, center=True)
    theme.text_fit(s, value, theme.BODY, theme.TEXT if an else theme.DISABLED,
                   pygame.Rect(links.right + 4, r.y, rechts.left - links.right - 8, r.height),
                   center=True)


def w_button(s, r: pygame.Rect, label, *, stil="primary", an=True, fokus=False):
    if not an:
        fill, border, txt = (26, 28, 36), theme.DISABLED, theme.DISABLED
    elif fokus:
        fill = (70, 56, 22) if stil == "primary" else (46, 50, 62)
        border, txt = theme.ACCENT_HOT, theme.TEXT
    else:
        fill = (44, 38, 18) if stil == "primary" else (32, 36, 46)
        border = theme.ACCENT if stil == "primary" else theme.BORDER_LIGHT
        txt = theme.TEXT
    pygame.draw.rect(s, fill, r, border_radius=8)
    pygame.draw.rect(s, border, r, 2 + (1 if fokus else 0), border_radius=8)
    theme.text_fit(s, label, theme.BODY, txt,
                   pygame.Rect(r.x + 14, r.y, r.width - 28, r.height), center=True)


def w_pfeil(s, r: pygame.Rect, glyph):
    pygame.draw.rect(s, (32, 36, 46), r, border_radius=8)
    pygame.draw.rect(s, theme.BORDER_LIGHT, r, 2, border_radius=8)
    theme.text(s, glyph, theme.HEADER, theme.ACCENT, r.center, center=True)


def regler(s, r: pygame.Rect, label, wert, t, *, aktiv=False, aus=False):
    """Ein Wert mit Pfeilknoepfen links und rechts -- bedient wird mit
    Schaltflaechen, nicht mit gemerkten Tasten (Beschluss vom 30.07.2026)."""
    lc = theme.DISABLED if aus else (theme.TEXT if aktiv else theme.TEXT_DIM)
    theme.text(s, label, theme.HINT, lc, (r.x + 34, r.y))
    theme.text(s, wert, theme.HINT,
               theme.DISABLED if aus else (theme.ACCENT if aktiv else theme.TEXT_DIM),
               (r.right - 34, r.y), topright=True)
    bar = pygame.Rect(r.x + 34, r.y + 24, r.width - 68, 8)
    pygame.draw.rect(s, (30, 33, 44), bar, border_radius=4)
    pygame.draw.rect(s, (52, 56, 70), bar, 1, border_radius=4)
    fw = int(bar.width * max(0.0, min(1.0, t)))
    if fw > 0 and not aus:
        pygame.draw.rect(s, theme.ACCENT if aktiv else theme.ACCENT_DIM,
                         (bar.x, bar.y, fw, bar.height), border_radius=4)
    kn = pygame.Rect(0, 0, 8, 18)
    kn.center = (bar.x + fw, bar.centery)
    pygame.draw.rect(s, theme.DISABLED if aus else (theme.ACCENT_HOT if aktiv else theme.TEXT_DIM),
                     kn, border_radius=3)
    for x, g in ((r.x, "‹"), (r.right - 26, "›")):
        kr = pygame.Rect(x, r.y + 8, 26, 30)
        pygame.draw.rect(s, (28, 31, 40), kr, border_radius=5)
        pygame.draw.rect(s, theme.DISABLED if aus else theme.BORDER_LIGHT, kr, 1,
                         border_radius=5)
        theme.text(s, g, theme.BODY, theme.DISABLED if aus else theme.ACCENT,
                   kr.center, center=True)


def gruppe(s, r: pygame.Rect, titel, zeilen, *, aktiv_idx=-1):
    """Kasten mit Ueberschrift und Reglern. Gibt die Unterkante zurueck."""
    hoehe = 46 + len(zeilen) * 52
    box = pygame.Rect(r.x, r.y, r.width, hoehe)
    kasten(s, box, "")
    theme.text(s, titel, theme.HINT, theme.ACCENT_DIM, (box.x + 14, box.y + 10))
    y = box.y + 40
    for i, (lbl, wert, t, aus) in enumerate(zeilen):
        regler(s, pygame.Rect(box.x + 12, y, box.width - 24, 40), lbl, wert, t,
               aktiv=(i == aktiv_idx), aus=aus)
        y += 52
    return box.bottom


# ---------------------------------------------------------------------------
# Anzeigen
# ---------------------------------------------------------------------------
#: Ausschnitt der Wellenform. Eine Motorstimme steuert mit rund 0,13 aus -- bei
#: voller Skala waere die Kurve ein Strich. Der Ausschnitt steht in der
#: Beschriftung, damit niemand die Aussteuerung falsch abliest.
WELLE_BEREICH = 0.35


def wellenform(s, r: pygame.Rect, b: np.ndarray, *, blockgrenzen=1,
               titel="WELLENFORM", unter=""):
    """Der Klang als Kurve. Die senkrechten Linien sind die Blockgrenzen --
    ein Knacks alle 42 ms sitzt genau dort, und das sieht man nur, wenn die
    Grenzen eingezeichnet sind."""
    kasten(s, r, titel, unter=unter)
    innen = pygame.Rect(r.x + 12, r.y + 34, r.width - 24, r.height - (66 if unter else 46))
    mitte = innen.centery

    def y_von(wert: float) -> int:
        return mitte - int(max(-1.2, min(1.2, wert / WELLE_BEREICH)) * innen.height / 2)

    pygame.draw.line(s, (34, 38, 50), (innen.x, mitte), (innen.right, mitte), 1)
    for anteil in (0.5, -0.5):
        y = mitte - int(anteil * innen.height / 2)
        for x in range(innen.x, innen.right, 8):
            pygame.draw.line(s, (30, 34, 46), (x, y), (x + 4, y), 1)
    theme.text(s, f"Ausschnitt ±{WELLE_BEREICH:.2f}", theme.SMALL, (70, 74, 88),
               (innen.right - 4, innen.y + 2), topright=True)

    for i in range(1, blockgrenzen):
        x = innen.x + int(innen.width * i / blockgrenzen)
        for y in range(innen.y, innen.bottom, 6):
            pygame.draw.line(s, (52, 46, 30), (x, y), (x, y + 3), 1)

    n = len(b)
    punkte = []
    for px in range(innen.width):
        i0 = int(px * n / innen.width)
        i1 = max(i0 + 1, int((px + 1) * n / innen.width))
        stueck = b[i0:i1]
        x = innen.x + px
        pygame.draw.line(s, (40, 90, 70), (x, y_von(float(stueck.max()))),
                         (x, y_von(float(stueck.min()))), 1)
        punkte.append((x, y_von(float(stueck.mean()))))
    if len(punkte) > 1:
        pygame.draw.lines(s, theme.SUCCESS, False, punkte, 1)


def spektrumbild(s, r: pygame.Rect, b: np.ndarray, *, titel="FREQUENZBAND",
                 unter="", marken=()):
    """Logarithmische Frequenzachse -- linear waere die untere Haelfte, in der
    ein Motor lebt, auf zwei Zentimeter zusammengedrueckt."""
    kasten(s, r, titel, unter=unter)
    innen = pygame.Rect(r.x + 12, r.y + 34, r.width - 24, r.height - (74 if unter else 54))
    f, db = spektrum(b)
    f_lo, f_hi = 30.0, 16000.0
    lo, hi = math.log10(f_lo), math.log10(f_hi)

    for hz in (100, 1000, 10000):
        x = innen.x + int(innen.width * (math.log10(hz) - lo) / (hi - lo))
        pygame.draw.line(s, (30, 34, 44), (x, innen.y), (x, innen.bottom), 1)
        theme.text(s, f"{hz//1000}k" if hz >= 1000 else str(hz), theme.SMALL,
                   (74, 78, 92), (x + 4, innen.bottom + 2))
    for pegel in (-20, -40, -60):
        y = innen.bottom - int(innen.height * (pegel + 80) / 80.0)
        pygame.draw.line(s, (26, 30, 40), (innen.x, y), (innen.right, y), 1)
        theme.text(s, f"{pegel}", theme.SMALL, (74, 78, 92), (innen.x + 2, y - 16))

    gueltig = (f >= f_lo) & (f <= f_hi)
    xs = innen.x + (innen.width * (np.log10(np.maximum(f[gueltig], 1.0)) - lo) / (hi - lo))
    ys = innen.bottom - (innen.height * (np.clip(db[gueltig], -80.0, 0.0) + 80.0) / 80.0)
    letzte = None
    for x, y in zip(xs.astype(int), ys.astype(int)):
        if letzte is not None and x == letzte[0]:
            y = min(y, letzte[1])
        pygame.draw.line(s, (36, 82, 62), (x, innen.bottom), (x, y), 1)
        letzte = (x, y)
    punkte = list(zip(xs.astype(int), ys.astype(int)))
    if len(punkte) > 1:
        pygame.draw.lines(s, theme.SUCCESS, False, punkte, 1)

    for hz, name in marken:
        x = innen.x + int(innen.width * (math.log10(hz) - lo) / (hi - lo))
        pygame.draw.line(s, theme.ACCENT, (x, innen.y), (x, innen.bottom), 1)
        theme.text(s, name, theme.SMALL, theme.ACCENT, (x + 5, innen.y + 4))


def drehzahlband(s, r: pygame.Rect, upm: float, *, hoch=True):
    """Das Drehzahlband mit den aufgenommenen Schichten als Marken.

    Der Kern der Seite: man sieht, zwischen welchen zwei Aufnahmen die aktuelle
    Drehzahl haengt und wie weit die Ueberblendung gerade offen ist. Ohne das
    dreht man an der Blende, ohne zu wissen, ob sie gerade ueberhaupt wirkt.
    """
    sch = sfx.schichten(MOTOR)
    lo, hi = sch.bereich
    kasten(s, r, "")
    bahn = pygame.Rect(r.x + 20, r.y + 44, r.width - 40, 16)
    pygame.draw.rect(s, (22, 25, 33), bahn, border_radius=8)
    pygame.draw.rect(s, (48, 52, 66), bahn, 1, border_radius=8)

    gew = sch.gewichte(upm)
    for u, g in zip(sch.drehzahlen, gew):
        x = bahn.x + int(bahn.width * (u - lo) / max(1, hi - lo))
        h = 12 + int(20 * g)
        farbe = theme.ACCENT if g > 0.01 else (60, 64, 80)
        pygame.draw.line(s, farbe, (x, bahn.y - 6), (x, bahn.y - 6 - h), 3 if g > 0.01 else 1)
        theme.text(s, str(u), theme.SMALL,
                   theme.ACCENT_DIM if g > 0.01 else (70, 74, 88),
                   (x, bahn.bottom + 6), center=True)
        if g > 0.01:
            theme.text(s, f"{g:.2f}", theme.SMALL, theme.ACCENT,
                       (x, bahn.y - 30 - h), center=True)

    x = bahn.x + int(bahn.width * (upm - lo) / max(1, hi - lo))
    pygame.draw.rect(s, theme.ACCENT_HOT, (x - 2, bahn.y - 2, 4, bahn.height + 4),
                     border_radius=2)
    theme.text(s, "AUFGENOMMENE SCHICHTEN", theme.SMALL, theme.TEXT_FAINT,
               (r.x + 14, r.y + 10))
    # Der Zeiger steht mitten im Band; seine Beschriftung gehoert deshalb an
    # den Rand, sonst deckt sie die Gewichte der Nachbarschichten zu.
    theme.text(s, f"{int(upm)} UPM", theme.LABEL, theme.ACCENT_HOT,
               (r.right - 14, r.y + 6), topright=True)


def wiedergabeleiste(s, r: pygame.Rect, upm: float, gang: int, *, kompakt=False):
    """Drehzahl von Hand, Gang daneben -- beim Schalten springt die Drehzahl."""
    kasten(s, r, "")
    theme.text(s, "WIEDERGABE", theme.SMALL, theme.TEXT_FAINT, (r.x + 14, r.y + 10))
    y = r.y + 36
    breite = r.width - 28

    dz = pygame.Rect(r.x + 14, y, int(breite * 0.46), 44)
    regler(s, dz, "Drehzahl", f"{int(upm)} UPM", (upm - 1000) / 8030.0, aktiv=True)

    gr = pygame.Rect(dz.right + 16, y - 2, 250, 48)
    w_stepper(s, gr, "", f"Gang {gang} / 6")
    hoch, runter = gangsprung(upm, gang, +1)[1], gangsprung(upm, gang, -1)[1]
    theme.text(s, f"hoch → {int(hoch)}   ·   runter → {int(runter)} UPM",
               theme.SMALL, theme.TEXT_FAINT, (gr.x + 2, gr.bottom + 6))

    px = gr.right + 16
    for glyph, lbl in (("●", "HÖREN"), ("■", "STOPP")):
        b = pygame.Rect(px, y - 2, 108, 48)
        w_button(s, b, f"{glyph} {lbl}", stil="primary" if glyph == "●" else "secondary")
        px += 118

    if not kompakt:
        theme.text(s, "Der Sprung beim Schalten ist der Verdächtige: Tonhöhe und "
                      "Schichtmischung wechseln mitten im Block.",
                   theme.SMALL, theme.TEXT_FAINT, (r.x + 14, r.bottom - 24),
                   max_w=r.width - 28)


def kopfzeile_fahrzeug(s, r: pygame.Rect):
    w_stepper(s, pygame.Rect(r.x, r.y, r.width, 52), "Fahrzeug", FZG_NAME, fokus=True)


# Werte der beiden Ebenen. Zeile: (Beschriftung, Anzeige, Fuellstand, ausgegraut)
FAHRZEUG_WERTE = [
    ("Tonhöhe",     "0.96",  (0.96 - 0.9) / 0.2, False),
    ("Färbung",     "+0.06", (0.06 + 1) / 2.0,   False),
    ("Lautstärke",  "0.60",  0.60,               False),
]
MOTOR_WERTE = [
    ("Schichtüberblendung", "1.00",     1.0,   False),
    ("Grundpegel",          "0.60",     0.60,  False),
    ("Hochpass",            "40 Hz",    0.20,  False),
]
ENTKNISTERN_WERTE = [
    ("Begrenzer Schwelle",  "0.85",     0.85,  False),
    ("Begrenzer Tempo",     "12 ms",    0.30,  False),
    ("Blocklänge",          "2048",     0.50,  False),
    ("Puffer",              "512",      0.33,  False),
    ("Blendkante",          "64 Smp",   0.25,  False),
]


# ===========================================================================
# Variante A — Werkbank: Regler links, Anzeige rechts
# ===========================================================================
def klang_a():
    s = pygame.Surface((W, H))
    laborkopf(s)
    b = block(UPM)

    links = pygame.Rect(40, 100, 620, 0)
    kopfzeile_fahrzeug(s, links)
    y = 100 + 66
    y = gruppe(s, pygame.Rect(40, y, 620, 0), "DIESES FAHRZEUG", FAHRZEUG_WERTE,
               aktiv_idx=0) + 14
    y = gruppe(s, pygame.Rect(40, y, 620, 0), f"MOTORTYP {MOTOR.upper()} — GILT FÜR ALLE",
               MOTOR_WERTE) + 14
    y = gruppe(s, pygame.Rect(40, y, 620, 0), "GEGEN DAS KNISTERN", ENTKNISTERN_WERTE) + 14

    w_button(s, pygame.Rect(40, H - 158, 300, 52), "Speichern")
    w_button(s, pygame.Rect(356, H - 158, 300, 52), "Verwerfen", stil="secondary")
    w_button(s, pygame.Rect(40, H - 96, 300, 52), "Auf Vorgabe", stil="secondary")
    w_button(s, pygame.Rect(356, H - 96, 300, 52), "‹ Zurück", stil="secondary")

    rechts = pygame.Rect(690, 100, W - 730, 0)
    wellenform(s, pygame.Rect(rechts.x, 100, rechts.width, 300), b,
               blockgrenzen=1,
               unter=f"{MOTOR} · {int(UPM)} UPM · Gang {GANG} · 2048 Samples (42,7 ms)")
    spektrumbild(s, pygame.Rect(rechts.x, 416, rechts.width, 300), b,
                 unter="dB über der Frequenz · die Marke sitzt an der Eckfrequenz der Färbung",
                 marken=((1800, "Färbung ab hier"),))
    drehzahlband(s, pygame.Rect(rechts.x, 732, rechts.width, 130), UPM)
    wiedergabeleiste(s, pygame.Rect(rechts.x, 878, rechts.width, 130), UPM, GANG)

    variantenschild(
        "A", "Werkbank — Regler links, Anzeige rechts",
        "Alle Werte in einer Spalte, von oben nach unten: Fahrzeug, Motortyp, Entknistern. "
        "Rechts sieht man, was sie bewirken. Nächste Verwandte der Lackier-Seite, gleicher "
        "Lesefluss — aber die Anzeigen werden schmaler als bei B.")
    return s


# ===========================================================================
# Variante B — Prüfstand: Anzeige oben breit, Bedienung unten in Spalten
# ===========================================================================
def klang_b():
    s = pygame.Surface((W, H))
    laborkopf(s)
    b = block(UPM)

    wellenform(s, pygame.Rect(40, 100, 900, 264), b, blockgrenzen=1,
               unter=f"ein Block · 2048 Samples · 42,7 ms · Spitze {abs(b).max():.2f}")
    spektrumbild(s, pygame.Rect(956, 100, W - 996, 264), b,
                 unter="Motorordnungen bis 16 kHz",
                 marken=((1800, "Färbung ab hier"),))

    drehzahlband(s, pygame.Rect(40, 380, W - 80, 132), UPM)
    wiedergabeleiste(s, pygame.Rect(40, 528, W - 80, 122), UPM, GANG, kompakt=True)

    sp_b = (W - 80 - 2 * 20) // 3
    for i, (titel, werte) in enumerate([
            ("DIESES FAHRZEUG", FAHRZEUG_WERTE),
            (f"MOTORTYP {MOTOR.upper()} — GILT FÜR ALLE", MOTOR_WERTE),
            ("GEGEN DAS KNISTERN", ENTKNISTERN_WERTE)]):
        x = 40 + i * (sp_b + 20)
        gruppe(s, pygame.Rect(x, 668, sp_b, 0), titel, werte,
               aktiv_idx=0 if i == 0 else -1)

    kopfzeile_fahrzeug(s, pygame.Rect(40, H - 96, 620, 0))
    w_button(s, pygame.Rect(690, H - 96, 250, 52), "Speichern")
    w_button(s, pygame.Rect(956, H - 96, 250, 52), "Verwerfen", stil="secondary")
    w_button(s, pygame.Rect(1222, H - 96, 250, 52), "Auf Vorgabe", stil="secondary")
    w_button(s, pygame.Rect(W - 40 - 250, H - 96, 250, 52), "‹ Zurück", stil="secondary")

    variantenschild(
        "B", "Prüfstand — sehen oben, drehen unten",
        "Wellenform und Spektrum bekommen die volle Breite, darunter das Drehzahlband mit den "
        "aufgenommenen Schichten und die Wiedergabe. Die Regler stehen in drei Spalten nach "
        "Reichweite getrennt: dieses Auto, alle Achtzylinder, Entknistern.")
    return s


# ===========================================================================
# Variante C — Signalweg: die Kette von der Aufnahme bis zum Ausgang
# ===========================================================================
def _mini_welle(s, r: pygame.Rect, b: np.ndarray, farbe):
    pygame.draw.rect(s, (10, 12, 20), r, border_radius=4)
    pygame.draw.rect(s, (40, 44, 58), r, 1, border_radius=4)
    n = len(b)
    mitte = r.centery
    pygame.draw.line(s, (28, 32, 42), (r.x + 2, mitte), (r.right - 2, mitte), 1)
    for px in range(2, r.width - 2):
        i0 = int(px * n / r.width)
        i1 = max(i0 + 1, int((px + 1) * n / r.width))
        st = b[i0:i1]
        yo = mitte - int(float(st.max()) / WELLE_BEREICH * (r.height - 8) / 2)
        yu = mitte - int(float(st.min()) / WELLE_BEREICH * (r.height - 8) / 2)
        pygame.draw.line(s, farbe, (r.x + px, yo), (r.x + px, yu), 1)


def klang_c():
    s = pygame.Surface((W, H))
    laborkopf(s)

    # Der Klang an vier Stellen der Kette -- roh, gefaerbt, und dieselben
    # Bloecke eine Drehzahl weiter, damit der Unterschied sichtbar wird.
    roh = block(UPM, faerbung=0.0, tonhoehe=1.0)
    gefaerbt = block(UPM, faerbung=0.06, tonhoehe=0.96)
    hoch = block(UPM * 1.35, faerbung=0.06, tonhoehe=0.96)

    stationen = [
        ("1  AUFNAHMEN", "8 von 10 Schichten stumm", roh,
         [("Schichtüberblendung", "1.00", 1.0, False)]),
        ("2  ÜBERBLENDUNG", "2400 → 3170 UPM, 0.42 / 0.58", roh,
         [("Blocklänge", "2048", 0.5, False), ("Blendkante", "64 Smp", 0.25, False)]),
        ("3  FÄRBUNG", "Tonhöhe 0.96 · Färbung +0.06", gefaerbt,
         [("Tonhöhe", "0.96", 0.3, False), ("Färbung", "+0.06", 0.53, False)]),
        ("4  HOCHPASS", "40 Hz — nimmt den Gleichanteil", gefaerbt,
         [("Hochpass", "40 Hz", 0.2, False)]),
        ("5  BEGRENZER", "ab 0.85, 12 ms", hoch,
         [("Schwelle", "0.85", 0.85, False), ("Tempo", "12 ms", 0.3, False)]),
    ]

    x = 40
    bw = (W - 80 - 4 * 12) // 5
    for titel, unter, welle, werte in stationen:
        r = pygame.Rect(x, 100, bw, 330)
        kasten(s, r, "")
        theme.text(s, titel, theme.HINT, theme.ACCENT_DIM, (r.x + 12, r.y + 10))
        theme.text(s, unter, theme.SMALL, theme.TEXT_FAINT, (r.x + 12, r.y + 36),
                   max_w=r.width - 24)
        _mini_welle(s, pygame.Rect(r.x + 12, r.y + 64, r.width - 24, 96), welle,
                    (40, 110, 80))
        yy = r.y + 176
        for lbl, wert, t, aus in werte:
            regler(s, pygame.Rect(r.x + 10, yy, r.width - 20, 40), lbl, wert, t, aus=aus)
            yy += 52
        if x + bw < W - 60:
            theme.text(s, "›", theme.HEADER, theme.ACCENT_DIM,
                       (x + bw + 6, r.centery), center=True)
        x += bw + 12

    spektrumbild(s, pygame.Rect(40, 448, 1180, 300), gefaerbt,
                 titel="AUSGANG — FREQUENZBAND",
                 unter="was am Ende der Kette herauskommt",
                 marken=((1800, "Färbung"),))
    wellenform(s, pygame.Rect(1236, 448, W - 1276, 300), gefaerbt,
               titel="AUSGANG — WELLENFORM",
               unter="derselbe Block, größer — hier sieht man einzelne Knacks")

    drehzahlband(s, pygame.Rect(40, 766, W - 80, 128), UPM)
    wiedergabeleiste(s, pygame.Rect(40, 910, 1180, 118), UPM, GANG, kompakt=True)
    kopfzeile_fahrzeug(s, pygame.Rect(1236, 910, 400, 0))
    w_button(s, pygame.Rect(1236, 972, 190, 52), "Speichern")
    w_button(s, pygame.Rect(1442, 972, 190, 52), "Verwerfen", stil="secondary")
    w_button(s, pygame.Rect(1648, 910, 232, 52), "‹ Zurück", stil="secondary")

    variantenschild(
        "C", "Signalweg — die Kette von der Aufnahme bis zum Ausgang",
        "Fünf Stationen von links nach rechts, jede mit ihren Reglern und einer kleinen "
        "Wellenform dahinter. Man sieht, an welcher Station der Knacks entsteht, statt ihn am "
        "Ende zu suchen — dafür ist jede einzelne Anzeige klein.")
    return s


# ===========================================================================
if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for name, fn in [("klang_A_werkbank", klang_a),
                     ("klang_B_pruefstand", klang_b),
                     ("klang_C_signalweg", klang_c)]:
        surf = mit_band(fn())
        pfad = os.path.join(OUT, f"{name}.png")
        pygame.image.save(surf, pfad)
        print("geschrieben:", pfad)
