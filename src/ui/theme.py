"""Central look-and-feel: colours, cached fonts and shared draw helpers.

Every menu screen pulls its palette, fonts and panel/vignette rendering from
here so the whole game shares one visual language.
"""
from __future__ import annotations

import pygame

# --- Palette -------------------------------------------------------------
ACCENT       = (255, 180, 0)     # primary orange
ACCENT_HOT   = (255, 210, 90)    # brighter accent (hover)
ACCENT_DIM   = (150, 120, 45)    # dimmed accent (inactive tab bar)

BG_DARK      = (14, 16, 22)
BG_GRAD_TOP  = (20, 22, 32)
BG_GRAD_BOT  = (10, 11, 18)

PANEL        = (22, 25, 32)
PANEL_LIGHT  = (34, 38, 48)
PANEL_SEL    = (52, 44, 20)       # selected/active card tint
BORDER       = (56, 60, 76)
BORDER_LIGHT = (86, 92, 112)

TEXT         = (232, 233, 238)
TEXT_DIM     = (150, 154, 168)
TEXT_FAINT   = (100, 104, 118)

SUCCESS      = (60, 200, 90)
DANGER       = (220, 70, 70)
DISABLED     = (92, 96, 110)

# --- Font sizes ----------------------------------------------------------
TITLE  = 80
HEADER = 46
BODY   = 32
LABEL  = 28
HINT   = 24
SMALL  = 20

# --- Font paths ---------------------------------------------------------
import os as _os
import sys as _sys
from pathlib import Path as _Path

# Bundled TTF (Segoe UI). Covers – — … ‹ › ← ↑ → ↓ ↔ ■ ▲ ▼ ○ ● ♦ … but NOT
# ✓ (U+2713), √ (U+221A), ★ (U+2605), ▶ (U+25B6), ⚠ (U+26A0), ↕ (U+2195).
# Ein fehlender Glyph zeichnet ein leeres Kaestchen — benutzt werden deshalb nur
# die Zeichen unten, und tests/test_schriftzeichen.py haelt das nach.
# Falls back to a system font and finally to pygame's built-in font.
_base_dir = _Path(_sys._MEIPASS) if getattr(_sys, "frozen", False) else _Path(__file__).parents[2]
_FONT_DIR = _base_dir / "data" / "fonts"
_TTF_PRIMARY  = str(_FONT_DIR / "segoeui.ttf")

#: „Erledigt" — Bereit, gefahren, geschlossen, Version aktuell.
#:
#: Bis zum 04.08.2026 stand hier ``√`` (und an einer Stelle ``✓``), und **beide
#: hat die Schrift nicht**: Segoe UI holt den Haken unter Windows aus Segoe UI
#: Symbol, das nicht mitgeliefert wird. Gezeichnet wurde also an elf Stellen ein
#: leeres Kaestchen — „□ Bereit" in Lobby, Ergebnisliste, Grand Prix und
#: Rennpause, „□ gefahren" in der Streckenwahl, „Version aktuell □",
#: „GESCHLOSSEN □". Das Zeichen steht bewusst **hier** und nicht in den
#: Sprachdateien: eine Verzierung ist nichts zu Uebersetzendes, und an einer
#: Stelle laesst sie sich austauschen.
HAKEN = "▪"

#: Eine Warnung. ``⚠`` fehlt der Schrift.
WARNUNG = "!"

#: Ein Zeiger auf den ausgewaehlten Eintrag. ``▶`` fehlt der Schrift, ``►`` nicht.
ZEIGER = "►"

#: Beide Richtungen einer Achse. ``↕`` fehlt der Schrift, die einzelnen Pfeile nicht.
HOCH_RUNTER = "↑↓"

_font_cache: dict[int, pygame.font.Font] = {}


def _load_font(size: int) -> pygame.font.Font:
    """Load the primary UI font with full Unicode coverage."""
    # Scale down the size slightly (0.81) to match the default pygame font metrics.
    scaled_size = max(10, int(size * 0.81))
    if _os.path.isfile(_TTF_PRIMARY):
        try:
            return pygame.font.Font(_TTF_PRIMARY, scaled_size)
        except Exception:
            pass
    # Fallback 1 – common system fonts with good Unicode coverage
    for name in ("segoeui", "arial", "freesansbold", "dejavusans"):
        path = pygame.font.match_font(name)
        if path:
            try:
                return pygame.font.Font(path, scaled_size)
            except Exception:
                pass
    # Fallback 2 – pygame built-in
    return pygame.font.Font(None, scaled_size)


def font(size: int) -> pygame.font.Font:
    """Cached UI font at *size* px (full Unicode glyph set).

    Wird versehentlich ein fertiges Font-Objekt statt einer Groesse uebergeben,
    wird es einfach durchgereicht. Vorher endete das in
    "unsupported operand type(s) for *: 'pygame.font.Font' and 'float'" —
    und zwar erst dann, wenn die betroffene Stelle tatsaechlich gezeichnet
    wurde. Im Grand Prix war das der Endstand nach dem letzten Lauf: die Serie
    lief komplett durch und das Spiel stuerzte im Moment des Siegerbildes ab.
    Ein solcher Vertipper darf hoechstens falsch aussehen, nicht das Spiel
    beenden.
    """
    # Bewusst per Merkmal geprueft, nicht per isinstance gegen
    # pygame.font.Font: im PyInstaller-Build ist das kein Typ, dort warf
    # isinstance() selbst einen TypeError - und zwar beim ersten gezeichneten
    # Text, also direkt beim Start. hasattr wirft nie.
    if hasattr(size, "render"):
        return size

    f = _font_cache.get(size)
    if f is None:
        f = _load_font(size)
        _font_cache[size] = f
    return f



# --- Draw helpers --------------------------------------------------------
_grad_cache: dict[tuple[int, int], pygame.Surface] = {}
_vignette_cache: dict[tuple[int, int], pygame.Surface] = {}


def draw_background(screen: pygame.Surface) -> None:
    """Fill with the shared vertical gradient."""
    w, h = screen.get_size()
    grad = _grad_cache.get((w, h))
    if grad is None:
        grad = pygame.Surface((1, h))
        for y in range(h):
            t = y / max(1, h - 1)
            grad.set_at((0, y), (
                int(BG_GRAD_TOP[0] + (BG_GRAD_BOT[0] - BG_GRAD_TOP[0]) * t),
                int(BG_GRAD_TOP[1] + (BG_GRAD_BOT[1] - BG_GRAD_TOP[1]) * t),
                int(BG_GRAD_TOP[2] + (BG_GRAD_BOT[2] - BG_GRAD_TOP[2]) * t),
            ))
        grad = pygame.transform.scale(grad, (w, h))
        _grad_cache[(w, h)] = grad
    screen.blit(grad, (0, 0))


def vignette(size: tuple[int, int], strength: int = 150) -> pygame.Surface:
    """A cached darkening vignette overlay for readability over artwork.

    Die Staerke gehoert IN den Schluessel. Ohne sie bekam der zweite Aufrufer
    die Flaeche des ersten: das Menue zeichnet mit 90, der Streckeneditor mit
    120, und je nachdem wer zuerst kam, war eine der beiden falsch abgedunkelt
    (gefunden 04.08.2026 bei der Suche nach der CPU-Last).
    """
    key = (size[0], size[1], int(strength))
    surf = _vignette_cache.get(key)
    if surf is None:
        w, h = size
        surf = pygame.Surface(size, pygame.SRCALPHA)
        cx, cy = w / 2, h / 2
        maxd = (cx ** 2 + cy ** 2) ** 0.5
        # Coarse radial darkening (stepped rings — cheap and cached once).
        step = 8
        for ry in range(0, h, step):
            for rx in range(0, w, step):
                d = (((rx - cx) ** 2 + (ry - cy) ** 2) ** 0.5) / maxd
                a = int(strength * (d ** 2))
                pygame.draw.rect(surf, (0, 0, 0, a), (rx, ry, step, step))
        _vignette_cache[key] = surf
    return surf


def panel(screen: pygame.Surface, rect: pygame.Rect, *, alpha: int = 205,
          border: tuple = BORDER, radius: int = 8, fill: tuple = PANEL) -> None:
    """Semi-transparent card with a border."""
    surf = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    pygame.draw.rect(surf, (*fill, alpha), (0, 0, rect.width, rect.height), border_radius=radius)
    screen.blit(surf, rect.topleft)
    pygame.draw.rect(screen, border, rect, 2, border_radius=radius)


def draw_input_badge(screen: pygame.Surface, topright: tuple[int, int]) -> None:
    """Small keyboard/controller indicator with a brief pulse on mode change."""
    from src.core import input_mode
    pad = input_mode.is_pad()
    pulse = input_mode.pulse()
    from src.core.i18n import tr
    lbl = "CONTROLLER" if pad else tr("TASTATUR")
    surf = font(SMALL).render(lbl, True, TEXT)
    pad_w = 30
    w = pad_w + surf.get_width() + 24
    h = 34
    x = topright[0] - w
    y = topright[1]
    box = pygame.Surface((w, h), pygame.SRCALPHA)
    a = int(150 + 90 * pulse)
    box.fill((18, 20, 26, a))
    screen.blit(box, (x, y))
    border = ACCENT_HOT if pulse > 0.05 else BORDER
    pygame.draw.rect(screen, border, (x, y, w, h), 2, border_radius=6)
    # glyph: keyboard = small rectangle w/ keys; controller = rounded body + sticks
    gx, gy = x + 8, y + h // 2
    col = ACCENT if pad else (150, 200, 255)
    if pad:
        pygame.draw.rect(screen, col, (gx, gy - 5, 18, 11), border_radius=5)
        pygame.draw.circle(screen, (18, 20, 26), (gx + 5, gy), 2)
        pygame.draw.circle(screen, (18, 20, 26), (gx + 13, gy), 2)
    else:
        pygame.draw.rect(screen, col, (gx, gy - 6, 18, 12), 1, border_radius=2)
        for kx in (gx + 3, gx + 8, gx + 13):
            pygame.draw.line(screen, col, (kx, gy - 3), (kx, gy - 3), 1)
    screen.blit(surf, (x + pad_w, y + (h - surf.get_height()) // 2))


def text(screen: pygame.Surface, s: str, size: int, color: tuple,
         pos: tuple[int, int], *, center=False, midtop=False, midright=False,
         midleft=False, topright=False, midbottom=False,
         max_w: int | None = None) -> pygame.Rect:
    """Render *s* and blit with the requested anchor, optionally clamping to max_w."""
    curr_size = size
    if max_w is not None:
        f = font(curr_size)
        w, h = f.size(s)
        # Try scaling down size first
        while w > max_w and curr_size > 14:
            curr_size -= 2
            f = font(curr_size)
            w, h = f.size(s)
        # If still too wide, truncate and add ellipsis
        if w > max_w:
            text_str = s
            while len(text_str) > 0 and w > max_w:
                text_str = text_str[:-1]
                w, h = font(curr_size).size(text_str + "…")
            s = text_str + "…"

    surf = font(curr_size).render(s, True, color)
    if center:
        r = surf.get_rect(center=pos)
    elif midtop:
        r = surf.get_rect(midtop=pos)
    elif midright:
        r = surf.get_rect(midright=pos)
    elif midleft:
        r = surf.get_rect(midleft=pos)
    elif topright:
        r = surf.get_rect(topright=pos)
    elif midbottom:
        r = surf.get_rect(midbottom=pos)
    else:
        r = surf.get_rect(topleft=pos)
    screen.blit(surf, r)
    return r


def text_fit(screen: pygame.Surface, s: str, size: int, color: tuple,
             rect: pygame.Rect, *, center=False) -> pygame.Rect:
    """Render text fitting it within a rect by scaling down size or truncating with '...'."""
    curr_size = size
    f = font(curr_size)
    w, h = f.size(s)
    
    # Try scaling down first
    while w > rect.width and curr_size > 14:
        curr_size -= 2
        f = font(curr_size)
        w, h = f.size(s)
        
    # If still too wide, truncate and add ellipsis
    text_str = s
    if w > rect.width:
        while len(text_str) > 0 and w > rect.width:
            text_str = text_str[:-1]
            w, h = font(curr_size).size(text_str + "…")
        text_str = text_str + "…"
        
    surf = font(curr_size).render(text_str, True, color)
    if center:
        r = surf.get_rect(center=rect.center)
    else:
        r = surf.get_rect(midleft=(rect.x, rect.centery))
        
    screen.blit(surf, r)
    return r


def stack(y: int, *heights: int) -> list[int]:
    """Return a vertical chain of y-positions based on starting y and a list of heights/gaps."""
    positions = []
    curr_y = y
    for h in heights:
        positions.append(curr_y)
        curr_y += h
    return positions


class Column:
    """Helper to position widgets vertically in a column dynamically.
    
    Avoids hardcoding Y coordinates and scales spacing automatically.
    """
    def __init__(self, x: int, y: int, gap: int = 12, align: str = "left") -> None:
        self.x = x
        self.y = y
        self.gap = gap
        self.align = align
        self._current_y = y

    def add(self, widget) -> None:
        """Position the widget at the current column Y, and advance the Y coordinate."""
        if self.align == "center":
            widget.rect.centerx = self.x
        else:
            widget.rect.x = self.x
        widget.rect.y = self._current_y
        self._current_y += widget.rect.height + self.gap

    def skip(self, height: int) -> None:
        """Skip a vertical space of the given height."""
        self._current_y += height

