"""Display management – resolution, fullscreen, FPS-limit, V-Sync.

Architecture
------------
* The game always renders into a fixed 1920×1080 **virtual surface** so that
  all states, HUDs and menus can use absolute pixel coordinates without change.
* The virtual surface is then scaled to the real window each frame via
  ``blit_to_window()``.  High-quality smoothscale is used when the target is
  smaller than 1920×1080; regular scale (faster) when it's the same size.
* Mouse coordinates from pygame events are in *window* space; ``scale_pos()``
  converts them to *virtual* (1920×1080) space so that all existing
  ``collidepoint`` checks keep working.

Usage in game.py
----------------
    from src.core import display

    # Once, after pygame.init():
    display.apply(screen)         # creates/resizes the window

    # In the render step, instead of state_machine.render(screen):
    state_machine.render(display.virtual_surface())
    display.blit_to_window(screen)

    # In the event loop, to fix mouse coordinates:
    events = display.remap_mouse_events(events)
"""
from __future__ import annotations

import pygame
from src.core.settings import SCREEN_WIDTH, SCREEN_HEIGHT

# Supported 16:9 resolutions (label → (w, h))
RESOLUTIONS: list[tuple[str, tuple[int, int]]] = [
    ("1280×720",  (1280,  720)),
    ("1600×900",  (1600,  900)),
    ("1920×1080", (1920, 1080)),
    ("2560×1440", (2560, 1440)),
    ("3840×2160", (3840, 2160)),
]
RESOLUTION_LABELS = [r[0] for r in RESOLUTIONS]

# Virtual render dimensions (never change)
VIRT_W = SCREEN_WIDTH   # 1920
VIRT_H = SCREEN_HEIGHT  # 1080

_virtual: pygame.Surface | None = None
_win_w: int = VIRT_W
_win_h: int = VIRT_H
# _current_w/h are the SURFACE (logical) size — the chosen resolution windowed,
# VIRT fullscreen. When it equals VIRT, blit_to_window()/scale_pos()
# short-circuit to a 1:1 blit and identity mouse mapping.
_current_w: int | None = None
_current_h: int | None = None
_current_flags: int | None = None
_current_vsync: bool | None = None

# Set while handle_window_event() is restoring the configured window size
# after a manual edge-drag resize. Calling set_window_size()/apply_settings()
# itself raises another WINDOWRESIZED/WINDOWSIZECHANGED event; without this
# guard that event would trigger another restore, which raises another
# event, forever. It is only read/written from handle_window_event().
_suppress_resize: bool = False


def set_window_icon() -> None:
    """Fenstersymbol setzen — aus ``data/icon.png`` ueber ``bundle_dir()``.

    Zwei Wege scheiterten bisher still (Fund 08.08.2026): pygame kann die
    ausgelieferte ``data/icon.ico`` nicht lesen ("Unsupported ICO bitmap
    format"), und ``data/menu/Icon.png`` gab es nicht — der Pfad war ausserdem
    relativ, im gepackten Bundle also falsch. Deshalb ein PNG, das pygame liest,
    ueber den absoluten Bundle-Pfad.

    Muss nach **jedem** ``set_mode`` neu gesetzt werden: das Neuerstellen des
    Fensters (Aufloesungswechsel) verwirft das Symbol.
    """
    from src.core.paths import bundle_dir
    pfad = bundle_dir() / "data" / "icon.png"
    try:
        if pfad.is_file():
            pygame.display.set_icon(pygame.image.load(str(pfad)))
    except Exception:
        pass


def virtual_surface() -> pygame.Surface:
    """Return the fixed 1920×1080 surface that all states should render into."""
    global _virtual
    if _virtual is None:
        _virtual = pygame.Surface((VIRT_W, VIRT_H))
    return _virtual


def apply(screen: pygame.Surface | None = None) -> pygame.Surface:
    """Apply current video settings from the player profile.

    Returns the *window* surface (same as *screen* if no resolution change is
    needed, or a freshly created one).
    """
    from src.core import profile
    p = profile.current()
    return apply_settings(
        resolution=p.resolution,
        fullscreen=p.fullscreen,
        vsync=p.vsync,
    )


def apply_settings(*, resolution: str = "1920x1080",
                   fullscreen: bool = False,
                   vsync: bool = False) -> pygame.Surface:
    """Create or resize the pygame window to match the requested settings.

    Both modes render through SCALED: SDL2 scales the logical surface to the
    real window on the GPU, replacing the old per-frame CPU smoothscale (10+ ms
    at 1440p). set_mode is given the TARGET size directly (the chosen resolution
    windowed, VIRT fullscreen) so the window starts at the logical size — no
    Window.size fix-up afterwards, which previously left a mis-sized letterbox
    viewport until the next real set_mode.

    When the chosen windowed resolution equals VIRT (1920×1080) the surface is
    logical 1920×1080, so blit_to_window/scale_pos short-circuit to a 1:1 blit
    and identity mouse mapping. Other windowed resolutions fall back to the
    (cheaper, down-scaling) smoothscale path in blit_to_window.
    """
    global _win_w, _win_h, _current_w, _current_h, _current_flags, _current_vsync

    # Parse resolution string "WxH" or "W×H"
    res_str = resolution.replace("×", "x")
    try:
        w, h = (int(v) for v in res_str.split("x"))
    except Exception:
        w, h = 1920, 1080

    if fullscreen:
        w_target, h_target = VIRT_W, VIRT_H
        flags_target = pygame.FULLSCREEN | pygame.SCALED
    else:
        w_target, h_target = w, h
        # RESIZABLE so Windows enables the titlebar maximize button (which
        # handle_window_event routes into real fullscreen); SCALED so SDL2
        # scales the logical surface to the window on the GPU.
        flags_target = pygame.RESIZABLE | pygame.SCALED

    vsync_target = vsync

    # Bypass recreating the window if settings haven't changed. Re-calling
    # set_mode on Windows in fullscreen/vsync can freeze SDL2.
    if (_current_w == w_target and _current_h == h_target and
            _current_flags == flags_target and _current_vsync == vsync_target):
        surf = pygame.display.get_surface()
        if surf is not None:
            return surf

    # Completely tear down the display module before recreating to prevent SDL2 scaling lockups/artifacts.
    if pygame.display.get_init():
        pygame.display.quit()
    pygame.display.init()

    # Restore caption and icon
    pygame.display.set_caption("2D-Racing-Game")
    set_window_icon()

    def _try_modes(size, flags):
        """set_mode with a vsync attempt, then without; return (surface, flags)."""
        try:
            return pygame.display.set_mode(size, flags, vsync=int(vsync)), flags
        except Exception:
            try:
                return pygame.display.set_mode(size, flags), flags
            except Exception:
                return None, flags

    screen, flags_target = _try_modes((w_target, h_target), flags_target)
    if screen is None:
        # SCALED unavailable (old/odd driver): fall back to a plain window /
        # raw fullscreen. blit_to_window/scale_pos handle the non-logical
        # surface via their CPU-scaling path.
        fallback = pygame.FULLSCREEN if fullscreen else pygame.RESIZABLE
        screen, flags_target = _try_modes((w, h), fallback)
        if screen is None:
            screen = pygame.display.set_mode((0, 0), fallback)
            flags_target = fallback

    # Cache the active configuration (surface size drives blit/scale_pos).
    _current_w, _current_h = screen.get_size()
    _current_flags = flags_target
    _current_vsync = vsync_target

    _win_w, _win_h = _current_w, _current_h
    return screen


def _set_window_size(w: int, h: int) -> bool:
    """Resize the OS window in place (logical surface unchanged). True on success.

    Dragging a window edge fires a resize event per mouse move, so this path has
    to be cheap. Recreating the display (pygame.display.quit() + set_mode()) per
    event would flicker and is exactly the call sequence prone to freezing SDL2
    on Windows. The Window object resizes the existing window without a rebuild.
    """
    try:
        from pygame.window import Window
        Window.from_display_module().size = (w, h)
        return True
    except Exception:
        return False


def _window_size() -> tuple[int, int] | None:
    """Actual OS window size, or None if the Window API is unavailable.

    Needed because under SCALED the display surface is always VIRT_W×VIRT_H, so
    the surface size no longer tells us how big the window is on screen."""
    try:
        from pygame.window import Window
        sz = Window.from_display_module().size
        return (int(sz[0]), int(sz[1]))
    except Exception:
        return None


def handle_window_event(event) -> bool:
    """React to native window-manager events (maximize / manual resize).

    The window is created with pygame.RESIZABLE (see apply_settings()) purely
    so Windows enables the titlebar maximize button - free-form resizing
    itself is not a supported feature of this game. This function redirects
    that button into the real fullscreen mode instead of a maximized window,
    and snaps any manual edge-drag resize back to the configured resolution.

    Returns True if the display was reconfigured.
    """
    global _suppress_resize, _current_w, _current_h, _current_flags, _current_vsync

    if event.type == pygame.WINDOWMAXIMIZED:
        # Already fullscreen - e.g. a trailing/duplicate event right after we
        # just switched. Ignore it: re-running apply_settings() here would
        # risk the SDL2 freeze noted above, for no benefit.
        if _current_flags is not None and (_current_flags & pygame.FULLSCREEN):
            return False

        from src.core import profile
        p = profile.current()
        p.fullscreen = True
        p.save()
        apply_settings(resolution=p.resolution, fullscreen=True, vsync=p.vsync)
        return True

    if event.type in (pygame.WINDOWRESIZED, pygame.WINDOWSIZECHANGED):
        # Fullscreen doesn't need snapping back, and re-entering apply_settings
        # here could re-trigger the SDL2 freeze mentioned above.
        if _current_flags is not None and (_current_flags & pygame.FULLSCREEN):
            return False
        # Ignore the event we ourselves caused while restoring the size below.
        if _suppress_resize:
            return False
        if _current_w is None:
            return False

        # Compare the real OS window size (under SCALED the surface stays at the
        # logical size, so it can't tell us the window drifted) against the
        # configured logical size.
        cur = _window_size()
        if cur is None or cur == (_current_w, _current_h):
            return False

        _suppress_resize = True
        try:
            if not _set_window_size(_current_w, _current_h):
                # No Window API: full rebuild at the chosen size. Clear the
                # cache so apply_settings doesn't short-circuit.
                _current_w = _current_h = _current_flags = _current_vsync = None
                from src.core import profile
                p = profile.current()
                apply_settings(resolution=p.resolution, fullscreen=p.fullscreen, vsync=p.vsync)
        finally:
            _suppress_resize = False
        return True

    return False


def blit_to_window(window: pygame.Surface) -> None:
    """Scale the virtual 1920×1080 surface onto the window and flip."""
    act_win = pygame.display.get_surface() or window
    virt = virtual_surface()
    ws, hs = act_win.get_size()
    if ws == VIRT_W and hs == VIRT_H:
        act_win.blit(virt, (0, 0))
        return
    # Texture quality drives the per-frame scaler: "Hoch" = smoothscale
    # (bilinear, 5-10 ms/frame), "Niedrig" = nearest scale (~10x faster).
    from src.core import profile
    if getattr(profile.current(), "texture_quality", "Hoch") == "Hoch":
        pygame.transform.smoothscale(virt, (ws, hs), act_win)
    else:
        pygame.transform.scale(virt, (ws, hs), act_win)


def scale_pos(pos: tuple[int, int]) -> tuple[int, int]:
    """Convert window-space coordinates to virtual (1920×1080) coordinates."""
    act_win = pygame.display.get_surface()
    if act_win is None:
        return pos
    ww, wh = act_win.get_size()
    if ww == VIRT_W and wh == VIRT_H:
        return pos
    sx = VIRT_W / ww
    sy = VIRT_H / wh
    return (int(pos[0] * sx), int(pos[1] * sy))


def mouse_pos() -> tuple[int, int]:
    """Current mouse position in virtual (1920×1080) coordinates.

    Use this instead of pygame.mouse.get_pos() everywhere — raw get_pos()
    returns window coordinates, which are wrong whenever the window is
    scaled (fullscreen on non-1080p displays, smaller windows)."""
    return scale_pos(pygame.mouse.get_pos())


def remap_mouse_events(events: list[pygame.event.Event]) -> list[pygame.event.Event]:
    """Return a new event list where all mouse positions are in virtual coords.

    Only MOUSEBUTTONDOWN, MOUSEBUTTONUP and MOUSEMOTION are remapped; all
    others (e.g. MOUSEWHEEL, which carries no position) are returned unchanged.
    """
    act_win = pygame.display.get_surface()
    if act_win is None:
        return events
    ww, wh = act_win.get_size()
    if ww == VIRT_W and wh == VIRT_H:
        return events   # No remapping needed at native resolution

    out: list[pygame.event.Event] = []
    for e in events:
        if e.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
            # Scale pos
            sx = VIRT_W / ww
            sy = VIRT_H / wh
            vpos = (int(e.pos[0] * sx), int(e.pos[1] * sy))
            
            attrs = {k: getattr(e, k) for k in e.__dict__ if k != "pos"}
            attrs["pos"] = vpos
            if e.type == pygame.MOUSEMOTION:
                rel = e.rel
                attrs["rel"] = (int(rel[0] * sx), int(rel[1] * sy))
            out.append(pygame.event.Event(e.type, attrs))
        else:
            out.append(e)
    return out


def resolution_label_to_str(label: str) -> str:
    """Convert display label (e.g. '1920×1080') to profile string ('1920x1080')."""
    return label.replace("×", "x")


def resolution_str_to_label(res_str: str) -> str:
    """Convert profile string (e.g. '1920x1080') to display label ('1920×1080')."""
    return res_str.replace("x", "×")


def current_win_size() -> tuple[int, int]:
    """Return the current window (physical) size."""
    return _win_w, _win_h
