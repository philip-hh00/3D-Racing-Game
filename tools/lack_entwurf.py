"""Entwurfsbilder fuer Block D -- Werkstatt und Lackier-Seite im Fahrzeuglabor.

Zeichnet je drei Varianten beider Seiten nach Documentation/entwurf/ und
release_1_0_plan.md D4 / D3. Gewaehlt ist beide Male Variante B (30.07.2026);
die verworfenen bleiben drin, damit man den Vergleich nachstellen kann.

Nutzt das echte src/ui/theme.py, die echten Sprites und den in D2 beschriebenen
Umfaerbe-Weg -- die Autos in den Bildern sind also wirklich umgefaerbt, keine
Platzhalter. Das ist auch der Grund, warum das Skript hier liegt: es ist der
schnellste Weg, eine Aenderung an Palette, Finish oder Maskenparametern an allen
15 Fahrzeugen anzusehen, ohne das Spiel zu starten.

    python tools/lack_entwurf.py            # nach Documentation/entwurf/
    python tools/lack_entwurf.py /tmp/x     # woanders hin

Braucht numpy und pygame; laeuft ohne Bildschirm (SDL-Dummy-Treiber).
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pygame

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

pygame.init()
pygame.display.set_mode((1920, 1080))

from src.ui import theme  # noqa: E402

W, H = 1920, 1080
TAB_H = 108
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join("Documentation", "entwurf")

# ---------------------------------------------------------------------------
# Lackpalette und Finishes (Entwurf aus D1)
# ---------------------------------------------------------------------------
FARBEN = [
    ("rubinrot",     "Rubinrot",     (200,  30,  40)),
    ("signalorange", "Signalorange", (240, 110,  20)),
    ("sonnengelb",   "Sonnengelb",   (240, 200,  40)),
    ("limettengruen","Limettengrün", (140, 200,  50)),
    ("waldgruen",    "Waldgrün",     ( 30, 130,  70)),
    ("tuerkis",      "Türkis",       ( 20, 180, 180)),
    ("eisblau",      "Eisblau",      ( 90, 170, 230)),
    ("kobaltblau",   "Kobaltblau",   ( 30,  70, 190)),
    ("violett",      "Violett",      (120,  60, 190)),
    ("magenta",      "Magenta",      (210,  50, 150)),
    ("anthrazit",    "Anthrazit",    ( 55,  58,  65)),
    ("perlweiss",    "Perlweiß",     (235, 238, 240)),
]
FINISHES = [
    ("standard",   "Standard",   None),
    ("metallic",   "Metallic",   "10 Rennen gefahren"),
    ("neon",       "Neon",       "10 Siege"),
    ("zweifarbig", "Zweifarbig", "Ghost auf 3 Strecken geschlagen"),
]


# ---------------------------------------------------------------------------
# Sprite laden und freistellen -- gleiche Logik wie renderer.py:45
# ---------------------------------------------------------------------------
_sprite_cache: dict[str, pygame.Surface] = {}


def sprite(visual_type: str) -> pygame.Surface:
    if visual_type in _sprite_cache:
        return _sprite_cache[visual_type]
    path = os.path.join("data", "vehicles", f"{visual_type.capitalize()}.png")
    surf = pygame.image.load(path).convert_alpha()
    tl = surf.get_at((0, 0))
    if tl.a == 255:
        surf.set_colorkey(tl)
        tmp = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        tmp.blit(surf, (0, 0))
        surf = tmp
    m = pygame.mask.from_surface(surf, threshold=50)
    rects = m.get_bounding_rects()
    if rects:
        r = sorted(rects, key=lambda q: q.width * q.height, reverse=True)[0]
        crop = pygame.Surface(r.size, pygame.SRCALPHA)
        crop.blit(surf, (0, 0), r)
        surf = crop
    # Auf Arbeitsgroesse runter -- fuer Mockups voellig ausreichend und schnell.
    scale = min(1.0, 620 / surf.get_width())
    if scale < 1.0:
        surf = pygame.transform.smoothscale(
            surf, (int(surf.get_width() * scale), int(surf.get_height() * scale)))
    _sprite_cache[visual_type] = surf
    return surf


def as_arrays(surf: pygame.Surface):
    rgb = pygame.surfarray.array3d(surf).astype(np.float32)      # (w,h,3)
    a = pygame.surfarray.array_alpha(surf).astype(np.float32)    # (w,h)
    return rgb, a


def from_arrays(rgb: np.ndarray, a: np.ndarray) -> pygame.Surface:
    out = pygame.Surface(rgb.shape[:2], pygame.SRCALPHA)
    pygame.surfarray.blit_array(out, np.clip(rgb, 0, 255).astype(np.uint8))
    alpha = pygame.surfarray.pixels_alpha(out)
    alpha[:, :] = np.clip(a, 0, 255).astype(np.uint8)
    del alpha
    return out


# ---------------------------------------------------------------------------
# Maskenfindung (D2) -- zwei Verfahren, gemeinsames Helligkeitsfenster
# ---------------------------------------------------------------------------
def maske(rgb, alpha, *, verfahren="dominant", schwelle=0.25, referenz=None,
          toleranz=0.18, hell_min=0.05, hell_max=0.95, weichheit=1.5):
    sichtbar = alpha > 40
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    lum = (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]) / 255.0

    if verfahren == "saettigung":
        m = sat >= schwelle
    elif verfahren == "dominant":
        if referenz is None:
            referenz = dominante_farbe(rgb, alpha)
        d = np.linalg.norm(rgb - np.array(referenz, dtype=np.float32), axis=2)
        m = d <= toleranz * 441.67
    else:
        m = np.zeros(sichtbar.shape, dtype=bool)

    m &= sichtbar & (lum >= hell_min) & (lum <= hell_max)
    w = m.astype(np.float32)
    if weichheit > 0:      # billiger Kastenfilter fuer weiche Kanten
        k = max(1, int(round(weichheit)))
        pad = np.pad(w, k, mode="edge")
        acc = np.zeros_like(w)
        n = 0
        for dx in range(-k, k + 1):
            for dy in range(-k, k + 1):
                acc += pad[k + dx:k + dx + w.shape[0], k + dy:k + dy + w.shape[1]]
                n += 1
        w = acc / n
    return w, lum


def randband(b: np.ndarray, breite=3) -> np.ndarray:
    """Schmales Band innen an der Grenze von *b* (Erosion abziehen)."""
    e = b.copy()
    for _ in range(breite):
        pad = np.pad(e, 1, mode="constant", constant_values=True)
        e = (e & pad[:-2, 1:-1] & pad[2:, 1:-1]
               & pad[1:-1, :-2] & pad[1:-1, 2:])
    return b & ~e


def dominante_farbe(rgb, alpha):
    sel = rgb[alpha > 40]
    if sel.size == 0:
        return (128, 128, 128)
    q = (sel // 16).astype(np.int32)
    key = q[:, 0] * 1024 + q[:, 1] * 32 + q[:, 2]
    vals, counts = np.unique(key, return_counts=True)
    top = vals[counts.argmax()]
    return (int((top // 1024) * 16 + 8), int(((top // 32) % 32) * 16 + 8),
            int((top % 32) * 16 + 8))


# ---------------------------------------------------------------------------
# Farbauftrag (D2) -- fuer alle Verfahren identisch
# ---------------------------------------------------------------------------
def umfaerben(surf: pygame.Surface, ziel, finish="standard", *, deckkraft=1.0,
              **maske_kw):
    rgb, alpha = as_arrays(surf)
    w, lum = maske(rgb, alpha, **maske_kw)
    if w.max() <= 0:
        return surf, w

    innen = w > 0.5
    if innen.sum() < 20:
        return surf, w
    lo, hi = np.percentile(lum[innen], [5, 95])
    ln = np.clip((lum - lo) / max(1e-6, hi - lo), 0.0, 1.0)

    if finish == "metallic":
        ln = np.clip(0.5 + (ln - 0.5) * 1.6, 0.0, 1.0)

    z = np.array(ziel, dtype=np.float32)
    if finish == "neon":
        mx = z.max()
        if mx > 0:                       # Saettigung ans Maximum
            z = np.clip(z * (255.0 / mx) * 0.92 + 12.0, 0, 255)

    neu = z[None, None, :] * (0.45 + 1.1 * ln)[..., None]

    if finish == "zweifarbig":
        # Mittleres Band der Bild-Y-Achse = Rallye-Streifen entlang der Laengsachse.
        hgt = rgb.shape[1]
        band = np.zeros(rgb.shape[:2], dtype=bool)
        b0, b1 = int(hgt * 0.39), int(hgt * 0.61)
        band[:, b0:b1] = True
        kontrast_hell = abs(np.mean(ziel) - 240) > abs(np.mean(ziel) - 55)
        zwei = np.array((235, 238, 240) if kontrast_hell else (55, 58, 65), dtype=np.float32)
        neu = np.where(band[..., None], zwei[None, None, :] * (0.45 + 1.1 * ln)[..., None], neu)

    if finish == "neon":
        # Saum: schmales Band innen an der Maskengrenze, nicht jeder
        # halbdurchsichtige Pixel -- sonst rauscht die ganze Flaeche.
        rand = randband(w > 0.4, breite=3)
        neu = np.where(rand[..., None], np.clip(neu * 1.5 + 26.0, 0, 255), neu)

    wf = (w * deckkraft)[..., None]
    erg = wf * neu + (1.0 - wf) * rgb
    return from_arrays(erg, alpha), w


def maskenbild(surf: pygame.Surface, w: np.ndarray) -> pygame.Surface:
    """Maske als Schwarzweissbild, Silhouette schwach angedeutet."""
    _, alpha = as_arrays(surf)
    g = w * 255.0
    rgbm = np.repeat(g[..., None], 3, axis=2)
    body = (alpha > 40) & (w <= 0.02)
    rgbm[body] = np.array((34, 38, 48), dtype=np.float32)
    return from_arrays(rgbm, np.where(alpha > 40, 255.0, 0.0))


def kanten_overlay(surf: pygame.Surface, w: np.ndarray,
                   farbe=(255, 60, 200)) -> pygame.Surface:
    """Original mit der Maskenkante als farbige Linie darueber."""
    rgb, alpha = as_arrays(surf)
    b = (w > 0.5).astype(np.float32)
    gx = np.abs(np.diff(b, axis=0, prepend=b[:1]))
    gy = np.abs(np.diff(b, axis=1, prepend=b[:, :1]))
    kante = (gx + gy) > 0
    out = rgb.copy()
    out[kante] = np.array(farbe, dtype=np.float32)
    return from_arrays(out, alpha)


# ---------------------------------------------------------------------------
# Zeichenhelfer
# ---------------------------------------------------------------------------
def hintergrund(s):
    theme.draw_background(s)
    s.blit(theme.vignette((W, H), 110), (0, 0))


def tableiste(s, aktiv=4):
    labels = ["EINZELSPIELER", "MEHRSPIELER LOKAL", "MEHRSPIELER ONLINE",
              "STRECKENEDITOR", "WERKSTATT", "EINSTELLUNGEN"]
    tw, th, gap = 288, 60, 8
    total = len(labels) * tw + (len(labels) - 1) * gap
    x0 = W // 2 - total // 2
    for i, lbl in enumerate(labels):
        r = pygame.Rect(x0 + i * (tw + gap), 28, tw, th)
        an = (i == aktiv)
        fill = (44, 40, 24, 200) if an else (28, 30, 40, 180)
        surf = pygame.Surface(r.size, pygame.SRCALPHA)
        surf.fill(fill)
        s.blit(surf, r.topleft)
        pygame.draw.rect(s, theme.ACCENT_DIM if an else theme.BORDER, r, 2, border_radius=6)
        theme.text_fit(s, lbl, theme.LABEL,
                       theme.TEXT_DIM if an else theme.TEXT_FAINT,
                       r.inflate(-16, 0), center=True)


def hinweisleiste(s, txt):
    theme.text(s, txt, theme.HINT, theme.TEXT_DIM, (W // 2, H - 34), center=True)


_schild: dict[str, tuple[str, str, str]] = {}


def variantenschild(s, nr, titel, untertitel):
    """Beschriftung nicht ins Bild zeichnen -- sie kommt in ein eigenes Band
    unter dem Mockup, damit die 1920x1080 pixelgenau das bleiben, was das Spiel
    tatsaechlich anzeigt."""
    _schild["aktuell"] = (nr, titel, untertitel)


def mit_band(s: pygame.Surface) -> pygame.Surface:
    nr, titel, untertitel = _schild.get("aktuell", ("?", "", ""))
    band = 104
    out = pygame.Surface((W, H + band))
    out.fill((8, 9, 14))
    out.blit(s, (0, 0))
    pygame.draw.line(out, theme.ACCENT_DIM, (0, H), (W, H), 2)
    theme.text(out, f"VARIANTE {nr}  —  {titel}", theme.HEADER, theme.ACCENT,
               (40, H + 18))
    theme.text(out, untertitel, theme.BODY, theme.TEXT_DIM, (40, H + 62),
               max_w=W - 80)
    return out


def auto_zeichnen(s, surf, box: pygame.Rect, *, drehung=0, schatten=True):
    sc = min(box.width / surf.get_width(), box.height / surf.get_height())
    img = pygame.transform.smoothscale(
        surf, (max(1, int(surf.get_width() * sc)), max(1, int(surf.get_height() * sc))))
    if drehung:
        img = pygame.transform.rotate(img, drehung)
    if schatten:
        sh = pygame.Surface(img.get_size(), pygame.SRCALPHA)
        pygame.draw.ellipse(sh, (0, 0, 0, 70),
                            (0, int(img.get_height() * 0.18),
                             img.get_width(), int(img.get_height() * 0.7)))
        s.blit(sh, img.get_rect(center=(box.centerx - 8, box.centery + 14)))
    s.blit(img, img.get_rect(center=box.center))


def farbfeld(s, r: pygame.Rect, rgb, *, gewaehlt=False, gesperrt=False, rund=6):
    surf = pygame.Surface(r.size, pygame.SRCALPHA)
    a = 90 if gesperrt else 255
    pygame.draw.rect(surf, (*rgb, a), (0, 0, r.width, r.height), border_radius=rund)
    s.blit(surf, r.topleft)
    if gewaehlt:
        pygame.draw.rect(s, theme.ACCENT_HOT, r.inflate(6, 6), 3, border_radius=rund + 2)
    else:
        pygame.draw.rect(s, theme.BORDER if not gesperrt else (60, 62, 74), r, 1, border_radius=rund)
    if gesperrt:
        schloss(s, (r.centerx, r.centery), 9, theme.TEXT_FAINT)


def schloss(s, mitte, h, col):
    cx, cy = mitte
    b = pygame.Rect(0, 0, int(h * 1.15), h)
    b.center = (cx, cy + h // 4)
    pygame.draw.rect(s, col, b, border_radius=2)
    pygame.draw.arc(s, col, pygame.Rect(cx - h // 2 + 1, cy - h + 2, h - 2, h), 0, 3.15, 2)


def w_stepper(s, r: pygame.Rect, label, value, *, fokus=False, an=True,
              hover_links=False, hover_rechts=False):
    """Stepper wie widgets.py:169 -- ‹ Wert ›, anklickbar."""
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
                       pygame.Rect(r.x + 20, r.y, links.left - r.x - 30, r.height))
    acol = theme.ACCENT if an else theme.DISABLED
    theme.text(s, "‹", theme.HEADER, theme.ACCENT_HOT if hover_links else acol,
               links.center, center=True)
    theme.text(s, "›", theme.HEADER, theme.ACCENT_HOT if hover_rechts else acol,
               rechts.center, center=True)
    theme.text_fit(s, value, theme.BODY, theme.TEXT if an else theme.DISABLED,
                   pygame.Rect(links.right + 4, r.y, rechts.left - links.right - 8, r.height),
                   center=True)


def w_button(s, r: pygame.Rect, label, *, stil="primary", an=True, hover=False,
             fokus=False):
    """Button wie widgets.py:82."""
    if not an:
        fill, border, txt = (26, 28, 36), theme.DISABLED, theme.DISABLED
    elif fokus or hover:
        fill = (70, 56, 22) if stil == "primary" else (46, 50, 62)
        border, txt = theme.ACCENT_HOT, theme.TEXT
    else:
        fill = (44, 38, 18) if stil == "primary" else (32, 36, 46)
        border = theme.ACCENT if stil == "primary" else theme.BORDER_LIGHT
        txt = theme.TEXT
    pygame.draw.rect(s, fill, r, border_radius=8)
    pygame.draw.rect(s, border, r, 2 + (1 if fokus else 0), border_radius=8)
    theme.text_fit(s, label, theme.BODY, txt,
                   pygame.Rect(r.x + 16, r.y, r.width - 32, r.height), center=True)


def w_pfeilknopf(s, r: pygame.Rect, glyph, *, hover=False):
    """Kleiner runder Pfeilknopf -- Stepper-Optik ohne Wertfeld."""
    pygame.draw.rect(s, (46, 50, 62) if hover else (32, 36, 46), r, border_radius=8)
    pygame.draw.rect(s, theme.ACCENT_HOT if hover else theme.BORDER_LIGHT, r, 2,
                     border_radius=8)
    theme.text(s, glyph, theme.HEADER, theme.ACCENT_HOT if hover else theme.ACCENT,
               r.center, center=True)


def regler(s, r: pygame.Rect, label, wert, t, *, aktiv=False, einheit=""):
    theme.text(s, label, theme.HINT, theme.TEXT if aktiv else theme.TEXT_DIM, (r.x, r.y))
    theme.text(s, f"{wert}{einheit}", theme.HINT,
               theme.ACCENT if aktiv else theme.TEXT_DIM, (r.right, r.y), topright=True)
    bar = pygame.Rect(r.x, r.y + 26, r.width, 8)
    pygame.draw.rect(s, (30, 33, 44), bar, border_radius=4)
    pygame.draw.rect(s, (52, 56, 70), bar, 1, border_radius=4)
    fw = int(bar.width * t)
    if fw > 0:
        pygame.draw.rect(s, theme.ACCENT if aktiv else theme.ACCENT_DIM,
                         (bar.x, bar.y, fw, bar.height), border_radius=4)
    kn = pygame.Rect(0, 0, 8, 18)
    kn.center = (bar.x + fw, bar.centery)
    pygame.draw.rect(s, theme.ACCENT_HOT if aktiv else theme.TEXT_DIM, kn, border_radius=3)
    if aktiv:
        pygame.draw.polygon(s, theme.ACCENT, [(r.x - 18, r.y + 4), (r.x - 8, r.y + 11),
                                              (r.x - 18, r.y + 18)])


def kachel_fahrzeug(s, r: pygame.Rect, name, klasse, lackname, rgb, *,
                    gewaehlt=False, werk=False):
    card = pygame.Surface(r.size, pygame.SRCALPHA)
    if gewaehlt:
        card.fill((60, 45, 20, 220))
        pygame.draw.rect(card, theme.ACCENT, (0, 0, r.width, r.height), 2, border_radius=4)
    else:
        card.fill((25, 25, 35, 180))
        pygame.draw.rect(card, (50, 50, 65), (0, 0, r.width, r.height), 1, border_radius=4)
    s.blit(card, r.topleft)
    strip = pygame.Rect(r.x, r.y + 1, 7, r.height - 2)
    if werk:
        for i in range(0, strip.height, 8):     # gestreift = Werkslack
            pygame.draw.rect(s, theme.TEXT_FAINT if (i // 8) % 2 == 0 else (40, 42, 52),
                             (strip.x, strip.y + i, strip.width, 4))
    else:
        pygame.draw.rect(s, rgb, strip)
    theme.text_fit(s, name, theme.BODY, theme.ACCENT if gewaehlt else theme.TEXT,
                   pygame.Rect(r.x + 20, r.y + 12, r.width - 40, 30))
    theme.text(s, klasse, theme.SMALL, theme.TEXT_FAINT, (r.x + 20, r.y + 44))
    theme.text(s, lackname, theme.SMALL,
               theme.TEXT_DIM if gewaehlt else theme.TEXT_FAINT, (r.x + 20, r.y + 68))


def platzhalter_titel(s, r: pygame.Rect):
    theme.panel(s, r, alpha=120, border=(46, 50, 62))
    theme.text(s, "TITEL", theme.LABEL, theme.TEXT_FAINT, (r.x + 18, r.y + 14))
    if r.height >= 100:
        theme.text(s, "Kommt mit den Freischaltungen", theme.SMALL, (74, 78, 92),
                   (r.x + 18, r.y + 48))
        theme.text(s, "(Block E)", theme.SMALL, (74, 78, 92), (r.x + 18, r.y + 72))
    else:
        theme.text(s, "Kommt mit den Freischaltungen (Block E)", theme.SMALL,
                   (74, 78, 92), (r.x + 18, r.y + 50), max_w=r.width - 36)


FLOTTE = [
    ("Kompaktwagen",     "rookie",      "HATCHBACK"),
    ("Stadtfloh GT",     "rookie_2",    "HATCHBACK"),
    ("Kompakt Sport",    "rookie_3",    "HATCHBACK"),
    ("Rennwagen",        "supercar",    "RENNFAHRZEUG"),
    ("Supersport S2",    "supercar_2",  "RENNFAHRZEUG"),
    ("Supersport S3",    "supercar_3",  "RENNFAHRZEUG"),
    ("Drift Machine",    "drifter",     "DRIFTER"),
    ("Drifter MK2",      "drifter_2",   "DRIFTER"),
]


# ===========================================================================
# WERKSTATT — Variante A: Liste | Vorschau | Lacke  (Entwurf aus dem Plan)
# ===========================================================================
def werkstatt_a():
    s = pygame.Surface((W, H))
    hintergrund(s)
    tableiste(s)

    theme.text(s, "WERKSTATT", theme.HEADER, theme.ACCENT, (40, TAB_H + 18))
    theme.text(s, "Lackierung je Fahrzeug", theme.HINT, theme.TEXT_DIM, (40, TAB_H + 66))

    links = pygame.Rect(40, TAB_H + 104, 470, 820)
    mitte = pygame.Rect(susp := 530, TAB_H + 104, 840, 820)
    rechts = pygame.Rect(1390, TAB_H + 104, 490, 820)
    for r in (links, mitte, rechts):
        theme.panel(s, r, alpha=205)

    # links: Fahrzeugliste
    theme.text(s, "FAHRZEUGE", theme.LABEL, theme.TEXT_DIM, (links.x + 18, links.y + 14))
    y = links.y + 54
    for i, (name, key, klasse) in enumerate(FLOTTE[:5]):
        sel = (i == 3)
        lack = "Metallic · Kobaltblau" if sel else ("Werkslack" if i % 2 else "Standard · Rubinrot")
        kachel_fahrzeug(s, pygame.Rect(links.x + 16, y, links.width - 46, 118),
                        name, klasse, lack,
                        (30, 70, 190) if sel else (200, 30, 40),
                        gewaehlt=sel, werk=(not sel and i % 2 == 1))
        y += 130
    pygame.draw.line(s, (40, 44, 56), (links.right - 16, links.y + 54),
                     (links.right - 16, links.bottom - 20), 4)
    pygame.draw.rect(s, theme.ACCENT, (links.right - 19, links.y + 250, 6, 260), border_radius=3)

    # mitte: Vorschau
    theme.text(s, "Rennwagen", theme.HEADER, theme.TEXT, (mitte.centerx, mitte.y + 18), center=True)
    box = pygame.Rect(mitte.x + 40, mitte.y + 80, mitte.width - 80, 560)
    grund = sprite("supercar")
    lack, _ = umfaerben(grund, (30, 70, 190), "metallic", verfahren="dominant")
    pygame.draw.rect(s, (16, 18, 26), box, border_radius=6)
    pygame.draw.rect(s, (38, 42, 54), box, 1, border_radius=6)
    for gx in range(box.x + 40, box.right, 60):
        pygame.draw.line(s, (22, 25, 34), (gx, box.y + 8), (gx, box.bottom - 8), 1)
    auto_zeichnen(s, lack, box.inflate(-70, -70))
    theme.text(s, "Metallic · Kobaltblau", theme.BODY, theme.ACCENT,
               (mitte.centerx, box.bottom + 26), center=True)
    theme.text(s, "‹ ›  drehen      Maus: ziehen", theme.HINT, theme.TEXT_FAINT,
               (mitte.centerx, box.bottom + 70), center=True)

    # rechts: Finishes + Farben + Titel
    theme.text(s, "LACKIERUNG", theme.LABEL, theme.TEXT_DIM, (rechts.x + 18, rechts.y + 14))
    fy = rechts.y + 52
    wr = pygame.Rect(rechts.x + 16, fy, rechts.width - 32, 46)
    surf = pygame.Surface(wr.size, pygame.SRCALPHA)
    surf.fill((26, 29, 38, 200))
    s.blit(surf, wr.topleft)
    pygame.draw.rect(s, theme.BORDER_LIGHT, wr, 2, border_radius=6)
    for i in range(0, 34, 8):
        pygame.draw.rect(s, theme.TEXT_FAINT, (wr.x + 14 + i, wr.y + 13, 4, 20))
    theme.text(s, "Werkslack", theme.BODY, theme.TEXT_DIM, (wr.x + 64, wr.centery - 16))
    theme.text(s, "immer", theme.SMALL, theme.TEXT_FAINT,
               (wr.right - 14, wr.centery - 10), topright=True)
    fy += 62
    for i, (fk, fname, bed) in enumerate(FINISHES):
        r = pygame.Rect(rechts.x + 16, fy, rechts.width - 32, 46)
        an = (fk == "metallic")
        gesperrt = fk in ("neon", "zweifarbig")
        surf = pygame.Surface(r.size, pygame.SRCALPHA)
        surf.fill((58, 48, 20, 235) if an else (26, 29, 38, 200))
        s.blit(surf, r.topleft)
        pygame.draw.rect(s, theme.ACCENT if an else theme.BORDER, r, 2, border_radius=6)
        col = theme.TEXT if an else (theme.TEXT_FAINT if gesperrt else theme.TEXT_DIM)
        theme.text(s, fname, theme.BODY, col, (r.x + 46, r.centery - 16))
        if gesperrt:
            schloss(s, (r.x + 24, r.centery), 11, theme.TEXT_FAINT)
            theme.text(s, bed, theme.SMALL, (86, 90, 104), (r.x + 46, r.bottom + 4))
            fy += 78
        else:
            fy += 56
    fy += 10

    theme.text(s, "GRUNDFARBE", theme.LABEL, theme.TEXT_DIM, (rechts.x + 18, fy))
    fy += 38
    cols, cw, ch, gap = 4, 100, 62, 12
    for i, (fk, fname, rgb) in enumerate(FARBEN):
        cx = rechts.x + 18 + (i % cols) * (cw + gap)
        cy = fy + (i // cols) * (ch + gap)
        farbfeld(s, pygame.Rect(cx, cy, cw, ch), rgb, gewaehlt=(fk == "kobaltblau"))
    fy += 3 * (ch + gap) + 10
    theme.text(s, "Kobaltblau", theme.HINT, theme.TEXT, (rechts.x + 18, fy))

    platzhalter_titel(s, pygame.Rect(rechts.x + 16, rechts.bottom - 122,
                                     rechts.width - 32, 106))

    hinweisleiste(s, "↑↓  Fahrzeug        ←→  drehen        TAB  Finish        1-9  Farbe        ESC  Zurück")
    variantenschild(s, "A", "Liste | Vorschau | Lacke",
                    "Der Entwurf aus dem Plan. Gleiche Aufteilung wie die Fahrzeugauswahl — nichts Neues zu lernen.")
    return s


# ===========================================================================
# WERKSTATT — Variante B: Auto zuerst, Fahrzeuge als Streifen unten
# ===========================================================================
def werkstatt_b():
    s = pygame.Surface((W, H))
    hintergrund(s)
    tableiste(s)

    # Zurueck als Schaltflaeche, nicht als ESC-Hinweis in der Fusszeile.
    w_button(s, pygame.Rect(40, TAB_H + 16, 190, 52), "‹ Zurück", stil="secondary")

    buehne = pygame.Rect(40, TAB_H + 84, 1380, 636)
    theme.panel(s, buehne, alpha=215)
    pygame.draw.rect(s, (15, 17, 24), buehne.inflate(-4, -4), border_radius=8)
    for i in range(14):
        tt = i / 13
        yy = int(buehne.y + 230 + tt * tt * 390)
        pygame.draw.line(s, (26, 29, 38), (buehne.x + 20, yy), (buehne.right - 20, yy), 1)
    pygame.draw.ellipse(s, (20, 23, 31), (buehne.centerx - 520, buehne.y + 160, 1040, 400))
    pygame.draw.ellipse(s, (30, 34, 44), (buehne.centerx - 520, buehne.y + 160, 1040, 400), 2)

    grund = sprite("drifter")
    lack, _ = umfaerben(grund, (210, 50, 150), "neon", verfahren="dominant")
    auto_zeichnen(s, lack, pygame.Rect(buehne.centerx - 460, buehne.y + 92, 920, 440),
                  drehung=-14)

    theme.text(s, "Drift Machine", theme.TITLE, theme.TEXT, (buehne.x + 44, buehne.y + 26))
    theme.text(s, "NEON · MAGENTA", theme.HEADER, (255, 120, 210),
               (buehne.x + 46, buehne.y + 104))

    # Drehen als Knoepfe statt Tastenhinweis. ↺/↻ gehen nicht -- die gebuendelte
    # Schrift kennt U+21BA/BB nicht und zeichnet ein leeres Kaestchen.
    dy = buehne.bottom - 74
    theme.text(s, "DREHEN", theme.SMALL, theme.TEXT_FAINT, (buehne.x + 46, dy - 24))
    w_pfeilknopf(s, pygame.Rect(buehne.x + 44, dy, 58, 54), "‹")
    w_pfeilknopf(s, pygame.Rect(buehne.x + 110, dy, 58, 54), "›", hover=True)
    w_button(s, pygame.Rect(buehne.x + 182, dy, 200, 54), "Ansicht zurück",
             stil="secondary")
    w_button(s, pygame.Rect(buehne.x + 394, dy, 230, 54), "Werkslack",
             stil="secondary")

    # Rechte Schiene
    rail = pygame.Rect(1440, TAB_H + 84, 440, 636)
    theme.panel(s, rail, alpha=210)

    w_stepper(s, pygame.Rect(rail.x + 16, rail.y + 18, rail.width - 32, 58),
              "", "Neon", fokus=True, hover_rechts=True)
    theme.text(s, "FINISH", theme.SMALL, theme.TEXT_FAINT, (rail.x + 20, rail.y + 86))
    theme.text(s, "frei ab 10 Siegen", theme.SMALL, theme.TEXT_FAINT,
               (rail.right - 20, rail.y + 86), topright=True)

    theme.text(s, "GRUNDFARBE", theme.LABEL, theme.TEXT_DIM, (rail.x + 20, rail.y + 120))
    cw, ch, gap = 118, 72, 14
    for i, (fk, fname, rgb) in enumerate(FARBEN):
        cx = rail.x + 20 + (i % 3) * (cw + gap)
        cy = rail.y + 158 + (i // 3) * (ch + gap)
        farbfeld(s, pygame.Rect(cx, cy, cw, ch), rgb, gewaehlt=(fk == "magenta"), rund=8)
    theme.text(s, "Magenta", theme.BODY, theme.TEXT, (rail.x + 20, rail.y + 502))
    platzhalter_titel(s, pygame.Rect(rail.x + 16, rail.bottom - 104, rail.width - 32, 88))

    # Flotte: blaettern ueber Knoepfe an den Enden, Auswahl per Klick auf die Kachel.
    strip = pygame.Rect(40, TAB_H + 736, 1840, 190)
    theme.panel(s, strip, alpha=200)
    w_pfeilknopf(s, pygame.Rect(strip.x + 14, strip.y + 50, 52, 96), "‹")
    w_pfeilknopf(s, pygame.Rect(strip.right - 66, strip.y + 50, 52, 96), "›", hover=True)
    tw2 = 220
    for i, (name, key, klasse) in enumerate(FLOTTE[:7]):
        r = pygame.Rect(strip.x + 92 + i * (tw2 + 14), strip.y + 18, tw2, 154)
        sel = (i == 6)
        card = pygame.Surface(r.size, pygame.SRCALPHA)
        card.fill((60, 45, 20, 225) if sel else (24, 27, 36, 190))
        s.blit(card, r.topleft)
        pygame.draw.rect(s, theme.ACCENT if sel else (46, 50, 62), r, 2 if sel else 1,
                         border_radius=6)
        mini = sprite(key)
        if sel:
            mini, _ = umfaerben(mini, (210, 50, 150), "neon", verfahren="dominant")
        auto_zeichnen(s, mini, pygame.Rect(r.x + 8, r.y + 6, r.width - 16, 96),
                      schatten=False)
        theme.text_fit(s, name, theme.SMALL, theme.TEXT if sel else theme.TEXT_DIM,
                       pygame.Rect(r.x + 8, r.bottom - 44, r.width - 16, 22), center=True)
        lack_lbl = "Neon · Magenta" if sel else ("Werkslack" if i % 3 else "Standard · Rubinrot")
        theme.text_fit(s, lack_lbl, theme.SMALL,
                       theme.ACCENT if sel else theme.TEXT_FAINT,
                       pygame.Rect(r.x + 8, r.bottom - 22, r.width - 16, 18), center=True)

    variantenschild(s, "B", "Auto zuerst  —  Schaltflächen statt Tastenhinweisen",
                    "Werkstatt links neben Einstellungen. Finish als Stepper, Drehen und Blättern "
                    "als Knöpfe, Farben per Klick, Zurück als Knopf. Fußzeile leer — "
                    "jede Bedienung ist sichtbar.")
    return s

# ===========================================================================
# WERKSTATT — Variante C: Lackregal, alle 48 Kombinationen auf einmal
# ===========================================================================
def werkstatt_c():
    s = pygame.Surface((W, H))
    hintergrund(s)
    tableiste(s)

    links = pygame.Rect(40, TAB_H + 20, 780, 906)
    rechts = pygame.Rect(840, TAB_H + 20, 1040, 906)
    theme.panel(s, links, alpha=210)
    theme.panel(s, rechts, alpha=210)

    # links: Fahrzeugwahl als Stepper + große Vorschau
    theme.text(s, "FAHRZEUG  8 / 15", theme.LABEL, theme.TEXT_DIM, (links.x + 20, links.y + 14))
    kopf = pygame.Rect(links.x + 16, links.y + 48, links.width - 32, 64)
    pygame.draw.rect(s, (26, 29, 38), kopf, border_radius=6)
    pygame.draw.rect(s, theme.BORDER, kopf, 1, border_radius=6)
    theme.text(s, "‹", theme.HEADER, theme.ACCENT, (kopf.x + 22, kopf.centery), center=True)
    theme.text(s, "›", theme.HEADER, theme.ACCENT, (kopf.right - 22, kopf.centery), center=True)
    theme.text(s, "Drifter MK2", theme.BODY, theme.TEXT, (kopf.centerx, kopf.centery), center=True)

    box = pygame.Rect(links.x + 24, links.y + 132, links.width - 48, 560)
    pygame.draw.rect(s, (15, 17, 24), box, border_radius=6)
    pygame.draw.rect(s, (36, 40, 52), box, 1, border_radius=6)
    for gy in range(box.y + 40, box.bottom, 56):
        pygame.draw.line(s, (22, 25, 34), (box.x + 8, gy), (box.right - 8, gy), 1)
    grund = sprite("drifter_2")
    lack, _ = umfaerben(grund, (240, 200, 40), "zweifarbig", verfahren="dominant",
                        hell_min=0.10)
    auto_zeichnen(s, lack, box.inflate(-50, -60))
    theme.text(s, "Zweifarbig · Sonnengelb", theme.BODY, theme.ACCENT,
               (box.centerx, box.bottom + 26), center=True)
    theme.text(s, "‹ ›  drehen", theme.HINT, theme.TEXT_FAINT,
               (box.centerx, box.bottom + 62), center=True)

    werkr = pygame.Rect(links.x + 24, links.bottom - 110, links.width - 48, 54)
    pygame.draw.rect(s, (26, 29, 38), werkr, border_radius=6)
    pygame.draw.rect(s, theme.BORDER_LIGHT, werkr, 1, border_radius=6)
    for i in range(0, 40, 8):
        pygame.draw.rect(s, theme.TEXT_FAINT, (werkr.x + 10 + i, werkr.y + 14, 4, 26))
    theme.text(s, "Werkslack zurücksetzen", theme.HINT, theme.TEXT_DIM,
               (werkr.x + 62, werkr.centery - 9))

    # rechts: das Regal, 12 x 4
    theme.text(s, "LACKREGAL", theme.LABEL, theme.TEXT_DIM, (rechts.x + 20, rechts.y + 14))
    theme.text(s, "48 Lackierungen am eigenen Fahrzeug  —  in Block D alle offen; "
               "Block E graut die drei rechten Spalten aus", theme.SMALL,
               theme.TEXT_FAINT, (rechts.x + 20, rechts.y + 48))

    gx0, gy0 = rechts.x + 176, rechts.y + 142
    cw, ch, gap = 190, 150, 14
    for c, (fk, fname, bed) in enumerate(FINISHES):
        hx = gx0 + c * (cw + gap)
        spaeter = fk != "standard"
        theme.text_fit(s, fname.upper(), theme.HINT, theme.TEXT,
                       pygame.Rect(hx, gy0 - 52, cw, 24), center=True)
        theme.text_fit(s, bed if spaeter else "von Anfang an", theme.SMALL,
                       (78, 82, 96), pygame.Rect(hx - 10, gy0 - 26, cw + 20, 18),
                       center=True)

    zeilen = [FARBEN[0], FARBEN[3], FARBEN[7], FARBEN[11]]
    for r_i, (fk, fname, rgb) in enumerate(zeilen):
        ry = gy0 + r_i * (ch + gap)
        theme.text(s, fname, theme.HINT, theme.TEXT_DIM, (rechts.x + 20, ry + ch // 2 - 10))
        for c, (fink, finname, bed) in enumerate(FINISHES):
            cell = pygame.Rect(gx0 + c * (cw + gap), ry, cw, ch)
            gewaehlt = (fk == "sonnengelb" and fink == "zweifarbig")
            pygame.draw.rect(s, (18, 20, 28), cell, border_radius=6)
            mini2, _ = umfaerben(sprite("drifter_2"), rgb, fink,
                                 verfahren="dominant", hell_min=0.10)
            auto_zeichnen(s, mini2, cell.inflate(-16, -24), schatten=False)
            if gewaehlt:
                pygame.draw.rect(s, theme.ACCENT_HOT, cell, 3, border_radius=6)
            else:
                pygame.draw.rect(s, (40, 44, 56), cell, 1, border_radius=6)
    theme.text(s, "↓  8 weitere Farben", theme.SMALL, theme.TEXT_FAINT,
               (rechts.x + 20, gy0 + 4 * (ch + gap) + 10))
    platzhalter_titel(s, pygame.Rect(gx0 + 2 * (cw + gap), gy0 + 4 * (ch + gap) - 4,
                                     2 * cw + gap, 84))

    hinweisleiste(s, "‹ ›  Fahrzeug        Pfeile  Lack im Regal        ENTER  Übernehmen        ESC  Zurück")
    variantenschild(s, "C", "Lackregal",
                    "Alle Kombinationen gleichzeitig sichtbar, jede am eigenen Fahrzeug. Zeigt am deutlichsten, was noch fehlt — kostet Vorschaugröße.")
    return s


# ===========================================================================
# LABOR — Variante A: Original | Maske | Ergebnis, Regler darunter
# ===========================================================================
LAB_KEY = "rookie_2"
LAB_KW = dict(verfahren="dominant", referenz=(90, 90, 89), toleranz=0.20,
              hell_min=0.05, hell_max=0.95, weichheit=1.5)


def laborkopf(s, nr, extra=""):
    s.fill((14, 15, 24))
    theme.text(s, "FAHRZEUG-LABOR — Stadtfloh GT  (rookie_2)", theme.HEADER,
               theme.ACCENT, (40, 24))
    theme.text(s, f"LACKIERUNG   ·   Fahrzeug 2 / 15   ·   *ungespeichert*{extra}",
               theme.SMALL, theme.TEXT_DIM, (44, 74))
    reiter = ["PHYSIK", "MOTORKURVE", "GETRIEBE", "LACKIERUNG"]
    x = 1240
    for i, r in enumerate(reiter):
        rect = pygame.Rect(x, 28, 158, 42)
        an = (i == 3)
        pygame.draw.rect(s, (58, 48, 20) if an else (24, 27, 36), rect, border_radius=5)
        pygame.draw.rect(s, theme.ACCENT if an else theme.BORDER, rect, 2 if an else 1,
                         border_radius=5)
        theme.text_fit(s, r, theme.SMALL, theme.TEXT if an else theme.TEXT_FAINT,
                       rect.inflate(-8, -8), center=True)
        x += 166


def bildkasten(s, r: pygame.Rect, titel, surf, *, farbe=theme.BORDER, unter=""):
    pygame.draw.rect(s, (10, 12, 20), r, border_radius=6)
    pygame.draw.rect(s, farbe, r, 1, border_radius=6)
    theme.text(s, titel, theme.HINT, theme.TEXT_DIM, (r.x + 12, r.y + 10))
    auto_zeichnen(s, surf, pygame.Rect(r.x + 10, r.y + 44, r.width - 20, r.height - 76),
                  schatten=False)
    if unter:
        theme.text(s, unter, theme.SMALL, theme.TEXT_FAINT, (r.x + 12, r.bottom - 26))


REGLER_A = [
    ("Verfahren", "dominant", 0.5, ""),
    ("Sättigungsschwelle", "0.25", 0.25, ""),
    ("Referenzfarbe R", "90", 0.35, ""),
    ("Referenzfarbe G", "90", 0.35, ""),
    ("Referenzfarbe B", "89", 0.35, ""),
    ("Farbtoleranz", "0.20", 0.20, ""),
    ("Helligkeit min", "0.05", 0.05, ""),
    ("Helligkeit max", "0.95", 0.95, ""),
    ("Kantenweichheit", "1.5", 0.38, " px"),
    ("Deckkraft", "1.00", 1.0, ""),
]


def labor_a():
    s = pygame.Surface((W, H))
    laborkopf(s, "A")

    grund = sprite(LAB_KEY)
    erg, w = umfaerben(grund, (30, 70, 190), "standard", **LAB_KW)
    mb = maskenbild(grund, w)
    deckung = float((w > 0.5).sum()) / max(1.0, float((pygame.surfarray.array_alpha(grund) > 40).sum()))

    bw, bh = 590, 460
    y = 110
    bildkasten(s, pygame.Rect(40, y, bw, bh), "ORIGINAL", grund)
    bildkasten(s, pygame.Rect(40 + bw + 25, y, bw, bh), "MASKE", mb,
               farbe=(120, 80, 160),
               unter=f"weiß = Lackfläche   ·   Abdeckung {deckung*100:.1f} %   ·   über 90 % ist ein Warnzeichen")
    bildkasten(s, pygame.Rect(40 + 2 * (bw + 25), y, bw, bh), "ERGEBNIS", erg,
               farbe=theme.ACCENT_DIM, unter="Standard · Kobaltblau")

    panel = pygame.Rect(40, y + bh + 30, 1200, 512)
    theme.panel(s, panel, alpha=190)
    theme.text(s, "REGLER", theme.LABEL, theme.TEXT_DIM, (panel.x + 20, panel.y + 12))
    ry = panel.y + 56
    for i, (lbl, val, t, unit) in enumerate(REGLER_A):
        col = panel.x + 40 + (i // 5) * 570
        rr = pygame.Rect(col, ry + (i % 5) * 72, 500, 40)
        regler(s, rr, lbl, val, t, aktiv=(i == 6), einheit=unit)

    seite = pygame.Rect(1265, y + bh + 30, 615, 512)
    theme.panel(s, seite, alpha=190)
    theme.text(s, "BEFUND", theme.LABEL, theme.TEXT_DIM, (seite.x + 20, seite.y + 12))
    zeilen = [
        ("dominante Farbe", "(90, 90, 89) grau"),
        ("Maskenabdeckung", f"{deckung*100:.1f} %"),
        ("Pixel in der Maske", f"{int((w > 0.5).sum()):,}".replace(",", ".")),
        ("Helligkeit 5. / 95. Perzentil", "0.21 / 0.72"),
        ("Befund", "in Ordnung — unter 90 %"),
    ]
    yy = seite.y + 58
    for k, v in zeilen:
        theme.text(s, k, theme.HINT, theme.TEXT_DIM, (seite.x + 20, yy))
        theme.text(s, v, theme.HINT,
                   theme.SUCCESS if k == "Befund" else theme.TEXT,
                   (seite.right - 20, yy), topright=True)
        yy += 46
    theme.text(s, "Bei Abdeckung über 90 % zählt die Maske vermutlich", theme.SMALL,
               theme.TEXT_FAINT, (seite.x + 20, yy + 14))
    theme.text(s, "Scheiben und Reifen mit — Helligkeitsfenster enger stellen.",
               theme.SMALL, theme.TEXT_FAINT, (seite.x + 20, yy + 40))
    theme.text(s, ",  .  Zielfarbe        ;  '  Finish        S  Speichern",
               theme.SMALL, theme.TEXT_FAINT, (seite.x + 20, seite.bottom - 34))

    variantenschild(s, "A", "Original | Maske | Ergebnis",
                    "Der Entwurf aus dem Plan. Drei gleich große Bilder oben, alle Regler auf einen Blick darunter.")
    return s


# ===========================================================================
# LABOR — Variante B: Regler links, 2x2 rechts, mit Helligkeits-Histogramm
# ===========================================================================
def histogramm(s, r: pygame.Rect, lum, alpha, w, hmin, hmax):
    pygame.draw.rect(s, (10, 12, 20), r, border_radius=6)
    pygame.draw.rect(s, (70, 90, 130), r, 1, border_radius=6)
    theme.text(s, "HELLIGKEIT DER SICHTBAREN PIXEL", theme.HINT, theme.TEXT_DIM,
               (r.x + 12, r.y + 10))
    sicht = alpha > 40
    hist_all, _ = np.histogram(lum[sicht], bins=64, range=(0, 1))
    hist_msk, _ = np.histogram(lum[sicht & (w > 0.5)], bins=64, range=(0, 1))
    # Wurzelskala: der graue Wagen haeuft fast alle Pixel auf einer Helligkeit,
    # linear waere alles ausser einem Balken unsichtbar.
    ha_s, hm_s = np.sqrt(hist_all), np.sqrt(hist_msk)
    mx = max(1e-6, ha_s.max())
    gx, gy = r.x + 16, r.y + 52
    gw, gh = r.width - 32, r.height - 100
    schraff = pygame.Surface((max(1, int((hmax - hmin) * gw)), gh), pygame.SRCALPHA)
    schraff.fill((255, 180, 0, 22))
    s.blit(schraff, (gx + int(hmin * gw), gy))
    for i in range(64):
        bx = gx + int(i * gw / 64)
        bwd = max(1, int(gw / 64) - 1)
        h1 = int(gh * ha_s[i] / mx)
        h2 = int(gh * hm_s[i] / mx)
        if h1:
            pygame.draw.rect(s, (52, 56, 72), (bx, gy + gh - h1, bwd, h1))
        if h2:
            pygame.draw.rect(s, (150, 100, 235), (bx, gy + gh - h2, bwd, h2))
    pygame.draw.line(s, (60, 64, 80), (gx, gy + gh), (gx + gw, gy + gh), 1)
    for val, lbl in ((hmin, f"min {hmin:.2f}"), (hmax, f"max {hmax:.2f}")):
        lx = gx + int(val * gw)
        pygame.draw.line(s, theme.ACCENT, (lx, gy - 8), (lx, gy + gh + 4), 2)
        theme.text(s, lbl, theme.SMALL, theme.ACCENT, (lx, gy + gh + 8), center=True)
    theme.text(s, "grau = alle Pixel      violett = in der Maske      "
               "(Wurzelskala)", theme.SMALL, theme.TEXT_FAINT,
               (r.x + 12, r.bottom - 26))


def labor_b():
    s = pygame.Surface((W, H))
    laborkopf(s, "B")

    grund = sprite(LAB_KEY)
    kw = dict(LAB_KW); kw["hell_min"] = 0.14; kw["hell_max"] = 0.86
    erg, w = umfaerben(grund, (30, 70, 190), "standard", **kw)
    mb = maskenbild(grund, w)
    rgb, alpha = as_arrays(grund)
    lum = (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]) / 255.0
    deckung = float((w > 0.5).sum()) / max(1.0, float((alpha > 40).sum()))

    links = pygame.Rect(40, 110, 560, 940)
    theme.panel(s, links, alpha=195)

    # Durchblaettern als Stepper -- keine Tastenkuerzel zu merken.
    for i, (lbl, val) in enumerate([("Fahrzeug", "Stadtfloh GT  2/15"),
                                    ("Zielfarbe", "Kobaltblau"),
                                    ("Finish", "Standard")]):
        w_stepper(s, pygame.Rect(links.x + 16, links.y + 16 + i * 66, links.width - 32, 58),
                  lbl, val, hover_rechts=(i == 0))

    pygame.draw.line(s, (46, 50, 62), (links.x + 16, links.y + 228),
                     (links.right - 16, links.y + 228), 1)

    werte = [
        ("Verfahren", "dominant", 0.5, ""),
        ("Sättigungsschwelle", "0.25", 0.25, ""),
        ("Referenzfarbe", "(90, 90, 89)", 0.35, ""),
        ("Farbtoleranz", "0.20", 0.20, ""),
        ("Helligkeit min", "0.14", 0.14, ""),
        ("Helligkeit max", "0.86", 0.86, ""),
        ("Kantenweichheit", "1.5", 0.38, " px"),
        ("Deckkraft", "1.00", 1.0, ""),
    ]
    ry = links.y + 250
    for i, (lbl, val, tv, unit) in enumerate(werte):
        regler(s, pygame.Rect(links.x + 24, ry, links.width - 168, 40), lbl, val, tv,
               aktiv=(i == 4), einheit=unit)
        # Zwei Pfeilknoepfe je Zeile, damit niemand auf Pfeiltasten angewiesen ist.
        w_pfeilknopf(s, pygame.Rect(links.right - 122, ry + 2, 44, 40), "‹")
        w_pfeilknopf(s, pygame.Rect(links.right - 70, ry + 2, 44, 40), "›",
                     hover=(i == 4))
        ry += 74

    w_button(s, pygame.Rect(links.x + 16, links.bottom - 72, 252, 54), "Speichern")
    w_button(s, pygame.Rect(links.x + 284, links.bottom - 72, 244, 54), "Verwerfen",
             stil="secondary")

    gx, gy = 630, 110
    bw, bh = 615, 455
    bildkasten(s, pygame.Rect(gx, gy, bw, bh), "ORIGINAL", grund)
    bildkasten(s, pygame.Rect(gx + bw + 20, gy, bw, bh), "MASKE", mb,
               farbe=(120, 80, 160),
               unter=f"weiß = Lackfläche   ·   Abdeckung {deckung*100:.1f} %   (ohne Helligkeitsfenster: 94,3 %)")
    bildkasten(s, pygame.Rect(gx, gy + bh + 20, bw, bh), "ERGEBNIS", erg,
               farbe=theme.ACCENT_DIM, unter="Standard · Kobaltblau")
    histogramm(s, pygame.Rect(gx + bw + 20, gy + bh + 20, bw, bh), lum, alpha, w,
               0.14, 0.86)

    variantenschild(s, "B", "Regler links, vier Felder rechts  —  mit Helligkeits-Histogramm",
                    "Durchblättern als Stepper, jeder Regler mit eigenen Pfeilknöpfen, "
                    "Speichern und Verwerfen als Schaltflächen. Das Histogramm zeigt, wo das "
                    "Helligkeitsfenster sitzt und was es fasst.")
    return s

# ===========================================================================
# LABOR — Variante C: ein großes Bild, Maskenkante als Überlagerung
# ===========================================================================
def labor_c():
    s = pygame.Surface((W, H))
    laborkopf(s, "C")

    grund = sprite(LAB_KEY)
    kw = dict(LAB_KW); kw["hell_min"] = 0.14; kw["hell_max"] = 0.86
    erg, w = umfaerben(grund, (30, 70, 190), "standard", **kw)
    ov = kanten_overlay(grund, w)
    rgb, alpha = as_arrays(grund)
    deckung = float((w > 0.5).sum()) / max(1.0, float((alpha > 40).sum()))

    gross = pygame.Rect(40, 110, 1280, 700)
    pygame.draw.rect(s, (10, 12, 20), gross, border_radius=8)
    pygame.draw.rect(s, theme.BORDER, gross, 1, border_radius=8)
    theme.text(s, "ORIGINAL MIT MASKENKANTE", theme.LABEL, theme.TEXT_DIM,
               (gross.x + 20, gross.y + 14))
    theme.text(s, "M  umschalten:  Kante / Maske / Ergebnis / Original", theme.SMALL,
               theme.TEXT_FAINT, (gross.right - 20, gross.y + 18), topright=True)
    auto_zeichnen(s, ov, gross.inflate(-90, -140), schatten=False)
    theme.text(s, "magenta = Grenze der Lackfläche", theme.HINT, (255, 60, 200),
               (gross.x + 20, gross.bottom - 34))
    theme.text(s, f"Abdeckung {deckung*100:.1f} %", theme.HINT, theme.TEXT,
               (gross.right - 20, gross.bottom - 34), topright=True)

    # rechte Spalte: kleine Referenzen
    rx = 1340
    for i, (titel, surf, farbe) in enumerate([
            ("ERGEBNIS", erg, theme.ACCENT_DIM),
            ("MASKE", maskenbild(grund, w), (120, 80, 160)),
            ("ORIGINAL", grund, theme.BORDER)]):
        bildkasten(s, pygame.Rect(rx, 110 + i * 236, 540, 216), titel, surf, farbe=farbe)

    # untere Leiste: Regler kompakt
    leiste = pygame.Rect(40, 830, 1280, 190)
    theme.panel(s, leiste, alpha=195)
    werte = [
        ("Verfahren", "dominant", 0.5, ""),
        ("Farbtoleranz", "0.20", 0.20, ""),
        ("Helligkeit min", "0.14", 0.14, ""),
        ("Helligkeit max", "0.86", 0.86, ""),
        ("Kantenweichheit", "1.5", 0.38, " px"),
        ("Deckkraft", "1.00", 1.0, ""),
    ]
    for i, (lbl, val, t, unit) in enumerate(werte):
        col = leiste.x + 40 + (i % 3) * 410
        rr = pygame.Rect(col, leiste.y + 26 + (i // 3) * 82, 350, 40)
        regler(s, rr, lbl, val, t, aktiv=(i == 2), einheit=unit)

    ecke = pygame.Rect(1340, 830, 540, 190)
    theme.panel(s, ecke, alpha=195)
    theme.text(s, "DURCHBLÄTTERN", theme.LABEL, theme.TEXT_DIM, (ecke.x + 20, ecke.y + 12))
    for i, (k, v) in enumerate([("TAB  /  [ ]", "Fahrzeug  2/15"),
                                (",  /  .", "Farbe  Kobaltblau"),
                                (";  /  '", "Finish  Standard"),
                                ("S", "Speichern")]):
        theme.text(s, k, theme.HINT, theme.ACCENT_DIM, (ecke.x + 20, ecke.y + 52 + i * 32))
        theme.text(s, v, theme.HINT, theme.TEXT_DIM, (ecke.x + 190, ecke.y + 52 + i * 32))

    variantenschild(s, "C", "Ein großes Bild, Maskenkante darüber",
                    "Die Maskengrenze liegt als Linie im Originalbild — man sieht im Zusammenhang, wo sie falsch läuft, statt drei Bilder zu vergleichen.")
    return s


# ===========================================================================
if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for name, fn in [
            ("werkstatt", werkstatt_b),                 # gewaehlt
            ("lackier_labor", labor_b),                 # gewaehlt
            ("verworfen_werkstatt_A_drei_spalten", werkstatt_a),
            ("verworfen_werkstatt_C_lackregal", werkstatt_c),
            ("verworfen_labor_A_dreifach", labor_a),
            ("verworfen_labor_C_maskenkante", labor_c)]:
        surf = mit_band(fn())
        path = os.path.join(OUT, f"{name}.png")
        pygame.image.save(surf, path)
        print("geschrieben:", path)
