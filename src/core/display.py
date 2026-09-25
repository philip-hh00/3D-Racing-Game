"""Display management – resolution, fullscreen, FPS-limit, V-Sync.

Architecture
------------
* The game always renders into a fixed 1920×1080 **virtual surface** so that
  all states, HUDs and menus can use absolute pixel coordinates without change.
* Mouse coordinates from pygame events are in *window* space; ``scale_pos()``
  converts them to *virtual* (1920×1080) space so that all existing
  ``collidepoint`` checks keep working.

Der Weg über OpenGL
-------------------
Seit der Portierung auf 3D wird das Fenster mit ``pygame.OPENGL`` geöffnet.
Damit ist die Fläche aus ``set_mode`` **nicht mehr bemalbar** — alles Gemalte
geht auf die virtuelle Fläche, und die wird am Ende des Bildes als Textur
darübergelegt (:mod:`src.render3d.ansicht`).

Drei Folgen, die den Aufbau hier bestimmen:

1. **Die virtuelle Fläche trägt einen Alphakanal.** Wo niemand zeichnet, bleibt
   sie durchsichtig und die 3D-Welt scheint durch. Ein Menü füllt weiter
   deckend und sieht aus wie immer.
2. **Der Kontext wird nie neu erzeugt.** Ein zweites ``set_mode`` verwirft ihn
   und mit ihm jedes hochgeladene Netz, jede Textur, jeden Shader — bei 600 000
   Dreiecken je Fahrzeug ein Aussetzer von Sekunden. Auflösung und Vollbild
   schalten deshalb über ``pygame.window.Window`` um.
3. **Briefkasten statt Zerren.** ``SCALED`` verträgt sich nicht mit OpenGL und
   ist entfallen. Passt das Fenster nicht zu 16:9, sitzt das Ansichtsfenster
   mittig darin und der Rand bleibt schwarz; ``scale_pos`` rechnet den Versatz
   wieder heraus.

Ohne OpenGL — im Testlauf, wo der SDL-Treiber ``dummy`` ist — liefert
:func:`kontext` ``None``. Dann wird keine Welt gezeichnet. Das ist **kein**
2D-Rückfall: HUD, Menüs und Spiellogik laufen weiter, nur das Bild der Welt
fehlt.

Usage in game.py
----------------
    from src.core import display

    # Once, after pygame.init():
    display.apply()               # creates the window

    # In the render step:
    display.bild_beginnen()
    state_machine.render(display.virtual_surface())
    display.bild_abschliessen()

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
# _current_w/h ist die **eingestellte** Fenstergroesse, nicht die gemessene.
# Daran erkennt handle_window_event, dass jemand am Fensterrand gezogen hat.
_current_w: int | None = None
_current_h: int | None = None
_current_fullscreen: bool | None = None
_current_vsync: bool | None = None

#: Ob ``set_mode`` mit ``pygame.OPENGL`` gelungen ist. Ohne das gibt es keinen
#: Kontext und keine Welt.
_opengl_fenster: bool = False
_kontext = None
_kontext_versucht: bool = False
_ansicht3d = None
_fensterobjekt = None

# Set while handle_window_event() is restoring the configured window size
# after a manual edge-drag resize. Calling the resize itself raises another
# WINDOWRESIZED/WINDOWSIZECHANGED event; without this guard that event would
# trigger another restore, which raises another event, forever.
_suppress_resize: bool = False


def set_window_icon() -> None:
    """Fenstersymbol setzen — aus ``data/icon.png`` ueber ``bundle_dir()``.

    Zwei Wege scheiterten bisher still (Fund 08.08.2026): pygame kann die
    ausgelieferte ``data/icon.ico`` nicht lesen ("Unsupported ICO bitmap
    format"), und ``data/menu/Icon.png`` gab es nicht — der Pfad war ausserdem
    relativ, im gepackten Bundle also falsch. Deshalb ein PNG, das pygame liest,
    ueber den absoluten Bundle-Pfad.
    """
    from src.core.paths import bundle_dir
    pfad = bundle_dir() / "data" / "icon.png"
    try:
        if pfad.is_file():
            pygame.display.set_icon(pygame.image.load(str(pfad)))
    except Exception:
        pass


def virtual_surface() -> pygame.Surface:
    """Die feste Fläche von 1920×1080, auf die jeder Zustand zeichnet.

    **Mit Alphakanal.** Ohne ihn deckte sie die 3D-Szene lückenlos zu; wo
    nichts gezeichnet wird, muss die Welt darunter durchscheinen.
    """
    global _virtual
    if _virtual is None:
        _virtual = pygame.Surface((VIRT_W, VIRT_H), pygame.SRCALPHA)
    return _virtual


# ---------------------------------------------------------------------------
# OpenGL
# ---------------------------------------------------------------------------

def kontext():
    """Der ModernGL-Kontext des Fensters, oder ``None``.

    ``None`` heisst: es wird keine Welt gezeichnet. Kein Fehler und kein
    Rückfall auf einen zweiten Zeichenweg — den gibt es nicht mehr.
    """
    global _kontext, _kontext_versucht
    if _kontext is not None or _kontext_versucht:
        return _kontext
    if not _opengl_fenster:
        return None
    _kontext_versucht = True
    try:
        import moderngl
        _kontext = moderngl.create_context()
    except Exception as fehler:                      # pragma: no cover - Treiber
        print(f"[display] Kein OpenGL-Kontext: {fehler}")
        _kontext = None
    if _kontext is not None:
        grafik_einrichten(_kontext)
    return _kontext


def grafik_einrichten(ctx) -> str:
    """Die Grafikeinstellungen aus dem Profil anwenden; liefert die Stufe.

    Beim **ersten Start** steht im Profil noch nichts. Dann entscheidet der
    Name der Grafikkarte (``GL_RENDERER``): eingebaute Grafik und
    Einsteigerkarten bekommen Niedrig, bekannte Mittelklasse Mittel, alles
    andere Hoch. Die Wahl wird gespeichert, damit sie im Menü steht und beim
    nächsten Start nicht neu geraten wird.
    """
    from src.core import profile
    from src.render3d import grafik
    p = profile.current()
    if isinstance(p.grafik, dict) and p.grafik:
        return grafik.aus_dict(p.grafik).stufe
    try:
        name = str(ctx.info.get("GL_RENDERER", ""))
    except Exception:                                # pragma: no cover - Treiber
        name = ""
    stufe = grafik.stufe_fuer_grafikkarte(name)
    grafik.stufe_setzen(stufe)
    print(f"[display] Grafikkarte '{name}' - Grafikstufe {stufe}")
    p.grafik = grafik.als_dict()
    p.save()
    return stufe


def _ueberlagerung():
    """Die Überlagerung, die die virtuelle Fläche über die Szene legt."""
    global _ansicht3d
    if _ansicht3d is None:
        ctx = kontext()
        if ctx is None:
            return None
        from src.render3d import ansicht
        _ansicht3d = ansicht.Ansicht3D(ctx, (VIRT_W, VIRT_H))
    return _ansicht3d


def ansichtsfenster(fenstergroesse: tuple[int, int]) -> tuple[int, int, int, int]:
    """Der 16:9-Ausschnitt im Fenster, als ``(x, y, breite, hoehe)``.

    Bis zur Portierung erledigte das ``pygame.SCALED``. Mit OpenGL gibt es das
    nicht mehr, also wird gerechnet: das Bild sitzt mittig, der Rest bleibt
    schwarz. Ohne diese Rechnung würde ein Fenster von 16:10 das Bild in die
    Höhe ziehen.

    Nie kleiner als ein Bildpunkt: ein minimiertes Fenster meldet 0×0, und ein
    Ansichtsfenster der Breite 0 ist für OpenGL ein Fehler.
    """
    breite = max(1, int(fenstergroesse[0]))
    hoehe = max(1, int(fenstergroesse[1]))
    if breite * VIRT_H > hoehe * VIRT_W:            # Fenster ist zu breit
        b = max(1, hoehe * VIRT_W // VIRT_H)
        return ((breite - b) // 2, 0, b, hoehe)
    h = max(1, breite * VIRT_H // VIRT_W)           # Fenster ist zu hoch
    return (0, (hoehe - h) // 2, breite, h)


def bild_beginnen(himmel: tuple[float, float, float] | None = None) -> None:
    """Ein neues Bild anfangen: Fläche leeren, Puffer leeren, Tiefentest an.

    Die virtuelle Fläche wird **durchsichtig** geleert, nicht schwarz — sonst
    verdeckt sie die Welt. Der Rand des Briefkastens wird schwarz geleert, der
    Bildbereich mit der Himmelsfarbe.
    """
    virtual_surface().fill((0, 0, 0, 0))
    ctx = kontext()
    if ctx is None:
        return
    bild = _ueberlagerung()
    fw, fh = _fenstergroesse()
    x, y, b, h = ansichtsfenster((fw, fh))
    ctx.screen.use()
    ctx.scissor = None
    ctx.viewport = (0, 0, max(1, fw), max(1, fh))
    ctx.clear(0.0, 0.0, 0.0, 1.0)
    ctx.viewport = (x, y, b, h)
    ctx.scissor = (x, y, b, h)
    if himmel is None:
        from src.render3d import shader
        himmel = shader.HIMMEL_HORIZONT
    bild.neues_bild(himmel=himmel)


def bild_abschliessen() -> None:
    """Die virtuelle Fläche über die Szene legen und das Bild zeigen."""
    bild = _ueberlagerung()
    if bild is not None:
        ctx = kontext()
        # Ansichtsfenster **und** Schere zuruecksetzen: der Splitscreen hat
        # beide auf eine Bildhaelfte verengt, und das HUD gehoert ueber das
        # ganze Bild.
        ausschnitt = ansichtsfenster(_fenstergroesse())
        ctx.viewport = ausschnitt
        ctx.scissor = ausschnitt
        bild.hud_zeichnen(virtual_surface())
    pygame.display.flip()


# ---------------------------------------------------------------------------
# Fenster
# ---------------------------------------------------------------------------

def apply(screen: pygame.Surface | None = None) -> pygame.Surface:
    """Apply current video settings from the player profile.

    Returns the *window* surface.
    """
    from src.core import profile
    p = profile.current()
    return apply_settings(
        resolution=p.resolution,
        fullscreen=p.fullscreen,
        vsync=p.vsync,
    )


def _aufloesung_lesen(resolution: str) -> tuple[int, int]:
    res_str = resolution.replace("×", "x")
    try:
        w, h = (int(v) for v in res_str.split("x"))
        return w, h
    except Exception:
        return VIRT_W, VIRT_H


def apply_settings(*, resolution: str = "1920x1080",
                   fullscreen: bool = False,
                   vsync: bool = False) -> pygame.Surface:
    """Fenster anlegen oder umschalten.

    **Beim ersten Aufruf** entsteht das Fenster mit ``OPENGL | DOUBLEBUF |
    RESIZABLE``. Jeder weitere Aufruf schaltet nur noch Größe und Vollbild um —
    ``set_mode`` würde den OpenGL-Kontext verwerfen und mit ihm alles, was
    hochgeladen wurde.

    Gelingt OpenGL nicht, läuft das Spiel ohne Welt weiter: Menüs und HUD
    zeichnen, die Strecke bleibt leer. Einen Rückfall auf den alten
    2D-Zeichenweg gibt es nicht mehr.
    """
    global _current_w, _current_h, _current_fullscreen, _current_vsync
    global _opengl_fenster

    w, h = _aufloesung_lesen(resolution)

    if _current_w is not None:
        _umschalten(w, h, fullscreen)
        _current_w, _current_h = w, h
        _current_fullscreen, _current_vsync = fullscreen, vsync
        return pygame.display.get_surface()

    pygame.display.set_caption("3D-Racing-Game")
    flags = pygame.OPENGL | pygame.DOUBLEBUF | pygame.RESIZABLE
    schirm = _versuche_modus((w, h), flags, vsync)
    _opengl_fenster = schirm is not None
    if schirm is None:
        print("[display] OpenGL nicht verfuegbar - die Rennwelt bleibt leer.")
        schirm = _versuche_modus((w, h), pygame.RESIZABLE, vsync)
    if schirm is None:                               # pragma: no cover - Treiber
        schirm = pygame.display.set_mode((w, h))
    set_window_icon()

    _current_w, _current_h = w, h
    _current_fullscreen, _current_vsync = fullscreen, vsync
    if fullscreen:
        _umschalten(w, h, True)
    return schirm


def _versuche_modus(size, flags, vsync: bool):
    """set_mode mit V-Sync versuchen, dann ohne. ``None``, wenn beides scheitert."""
    for kwargs in ({"vsync": 1 if vsync else 0}, {}):
        try:
            return pygame.display.set_mode(size, flags, **kwargs)
        except Exception:
            continue
    return None


def _fenster():
    """Das Fensterobjekt hinter der Anzeige, oder ``None``.

    Die Warnung wird unterdrueckt: ``from_display_module`` mahnt zur
    Flaechenzeichnung ueber ``Window.get_surface``, und genau die benutzt
    dieses Spiel nicht mehr — es zeichnet mit OpenGL. Ohne das Unterdruecken
    steht die Mahnung mehrmals je Bild im Protokoll.
    """
    global _fensterobjekt
    if _fensterobjekt is not None:
        return _fensterobjekt
    try:
        import warnings
        from pygame.window import Window
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            _fensterobjekt = Window.from_display_module()
    except Exception:
        return None
    return _fensterobjekt


def _umschalten(w: int, h: int, fullscreen: bool) -> None:
    """Größe und Vollbild ändern, **ohne** ``set_mode``.

    Der OpenGL-Kontext hängt am Fenster. Ein neues ``set_mode`` erzeugt ein
    neues Fenster und wirft den Kontext weg; über die Window-API bleibt beides
    erhalten.
    """
    fenster = _fenster()
    if fenster is None:                              # pragma: no cover - alte pygame
        return
    try:
        if fullscreen:
            fenster.set_fullscreen(desktop=True)
        else:
            fenster.set_windowed()
            fenster.size = (w, h)
    except Exception:                                # pragma: no cover - Treiber
        pass


def _window_size() -> tuple[int, int] | None:
    """Tatsächliche Fenstergröße, oder ``None`` ohne Window-API."""
    fenster = _fenster()
    if fenster is None:
        return None
    try:
        groesse = fenster.size
        return (int(groesse[0]), int(groesse[1]))
    except Exception:
        return None


def _fenstergroesse() -> tuple[int, int]:
    """Fenstergröße in Bildpunkten. Grundlage für Briefkasten und Maus."""
    groesse = _window_size()
    if groesse is not None and groesse[0] > 0 and groesse[1] > 0:
        return groesse
    flaeche = pygame.display.get_surface()
    if flaeche is not None:
        return flaeche.get_size()
    return (VIRT_W, VIRT_H)


def handle_window_event(event) -> bool:
    """React to native window-manager events (maximize / manual resize).

    Das Fenster ist ``RESIZABLE``, damit Windows den Maximieren-Knopf anbietet;
    freies Ziehen am Rand ist keine Funktion des Spiels. Der Knopf führt in
    echtes Vollbild, gezogene Größen schnappen zurück.

    Returns True if the display was reconfigured.
    """
    global _suppress_resize

    if event.type == pygame.WINDOWMAXIMIZED:
        if _current_fullscreen:
            return False
        from src.core import profile
        p = profile.current()
        p.fullscreen = True
        p.save()
        apply_settings(resolution=p.resolution, fullscreen=True, vsync=p.vsync)
        return True

    if event.type in (pygame.WINDOWRESIZED, pygame.WINDOWSIZECHANGED):
        if _current_fullscreen:
            return False
        if _suppress_resize or _current_w is None:
            return False
        if _window_size() == (_current_w, _current_h):
            return False
        _suppress_resize = True
        try:
            _umschalten(_current_w, _current_h, False)
        finally:
            _suppress_resize = False
        return True

    return False


# ---------------------------------------------------------------------------
# Mauskoordinaten
# ---------------------------------------------------------------------------

def _abbildung() -> tuple[int, int, float, float] | None:
    """Versatz und Maßstab vom Fenster in die virtuelle Fläche.

    ``None``, wenn das Fenster genau die virtuelle Auflösung hat — dann ist
    nichts zu rechnen.
    """
    x, y, b, h = ansichtsfenster(_fenstergroesse())
    if (x, y, b, h) == (0, 0, VIRT_W, VIRT_H):
        return None
    return (x, y, VIRT_W / b, VIRT_H / h)


def scale_pos(pos: tuple[int, int]) -> tuple[int, int]:
    """Convert window-space coordinates to virtual (1920×1080) coordinates."""
    abb = _abbildung()
    if abb is None:
        return pos
    x, y, sx, sy = abb
    return (int((pos[0] - x) * sx), int((pos[1] - y) * sy))


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
    abb = _abbildung()
    if abb is None:
        return events
    x, y, sx, sy = abb

    out: list[pygame.event.Event] = []
    for e in events:
        if e.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
            vpos = (int((e.pos[0] - x) * sx), int((e.pos[1] - y) * sy))
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
    return _fenstergroesse()
