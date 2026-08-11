"""Main entry point for the 2D Racing Game."""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path


def _fix_cwd() -> None:
    """In a PyInstaller bundle, switch the working directory to the folder that
    holds the bundled ``data/`` (``sys._MEIPASS``). This makes every relative
    ``data/...`` path resolve exactly like a source run from the repo root."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        os.chdir(base)


def _patch_pygame_font() -> None:
    """Patch pygame.font.Font to load the bundled Segoe UI font by default.
    This ensures that all UI states instantiating default pygame fonts (via None)
    correctly render special Unicode glyphs (stars, arrows) on all platforms.
    """
    try:
        import pygame
        pygame.font.init()
        
        base = getattr(sys, "_MEIPASS", None)
        if base:
            base_path = Path(base)
        else:
            base_path = Path(__file__).parent
            
        segoe_path = base_path / "data" / "fonts" / "segoeui.ttf"
        if not segoe_path.exists():
            return
            
        _orig_font = pygame.font.Font
        
        def _safe_font(*args, **kwargs):
            file_arg = None
            has_file = False
            if len(args) > 0:
                file_arg = args[0]
                has_file = True
            elif 'file' in kwargs:
                file_arg = kwargs['file']
                has_file = True
                
            if not has_file or file_arg is None:
                try:
                    if len(args) > 0:
                        new_args = (str(segoe_path),) + args[1:]
                        return _orig_font(*new_args, **kwargs)
                    else:
                        new_kwargs = kwargs.copy()
                        new_kwargs['file'] = str(segoe_path)
                        return _orig_font(*args, **new_kwargs)
                except Exception:
                    pass
            return _orig_font(*args, **kwargs)
            
        pygame.font.Font = _safe_font
    except Exception:
        pass


def _set_dpi_aware() -> None:
    """Set process DPI awareness on Windows to prevent resolution virtualisation
    and fuzzy scaling, which frequently causes fullscreen windows to lose focus and minimize.
    Also disable automatic fullscreen minimization on focus loss.
    """
    os.environ['SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS'] = '0'
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _melde_laeuft_bereits() -> None:
    """Sagen, warum nichts passiert — sonst startet das Spiel scheinbar nicht.

    Ein Fenster und nicht nur eine Zeile auf der Konsole: wer doppelt geklickt
    hat, sieht keine Konsole. Bewusst ohne die Menuegrafik — an dieser Stelle
    ist noch nichts geladen, und geladen werden soll hier auch nichts mehr.
    """
    text = ["Das Spiel läuft bereits.",
            "",
            "Es kann nur einmal gleichzeitig geöffnet sein — sonst",
            "schreiben beide Fenster dasselbe Profil und Fortschritt,",
            "Freischaltungen und Bestzeiten gehen verloren.",
            "",
            "Fenster schließen mit ESC."]
    print("\n".join(text), file=sys.stderr)
    try:
        import pygame
        pygame.init()
        schirm = pygame.display.set_mode((760, 300))
        pygame.display.set_caption("2D Racing Game")
        schrift = pygame.font.Font(None, 30)
        schirm.fill((14, 16, 22))
        for i, zeile in enumerate(text):
            farbe = (255, 180, 0) if i == 0 else (200, 202, 210)
            schirm.blit(schrift.render(zeile, True, farbe), (40, 40 + i * 34))
        pygame.display.flip()
        laeuft = True
        while laeuft:
            for e in pygame.event.get():
                if e.type == pygame.QUIT or (
                        e.type == pygame.KEYDOWN and e.key in (
                            pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_SPACE)):
                    laeuft = False
            pygame.time.wait(30)
        pygame.quit()
    except Exception:
        pass


def main() -> None:
    """Parse command line arguments and launch the game."""
    _set_dpi_aware()
    _fix_cwd()
    _patch_pygame_font()

    # Vor allem anderen: laeuft schon eine Instanz? Zwei Fenster schreiben
    # dasselbe verschluesselte Profil, und ein Schreibkonflikt macht daraus
    # keine veraltete, sondern eine unlesbare Datei (A2 / Block E4).
    from src.core import einzelinstanz
    if not einzelinstanz.beanspruchen():
        _melde_laeuft_bereits()
        sys.exit(1)

    parser = argparse.ArgumentParser(description="2D Racing Game with Pymunk Physics")
    parser.add_argument(
        "--debug", "-d",
        action="store_true",
        help="Enable physics debug visualization",
    )
    args = parser.parse_args()

    from src.core.game import GameManager
    from src.core import settings

    settings.DEBUG = args.debug

    game = GameManager(debug=args.debug)
    try:
        game.run()
    except Exception:
        tb = traceback.format_exc()
        # Pfad und Schreiben liegen in src/core/absturz.py — dieselbe Stelle,
        # die die Einstellungen unter "Info" verlinken. Sechs Sekunden Anzeige
        # sind zu kurz, um einen Pfad abzuschreiben (Block F2).
        from src.core import absturz
        log_path = absturz.schreiben(tb)
        try:
            import pygame
            if pygame.get_init():
                screen = pygame.display.get_surface()
                if screen:
                    pygame.font.init()
                    font = pygame.font.SysFont("consolas", 18)
                    screen.fill((20, 0, 0))
                    lines = ["ABSTURZ — Bitte melde diesen Fehler!", "",
                             f"Log gespeichert: {log_path}",
                             "Auch zu finden unter Einstellungen → Info.",
                             ""] + tb.splitlines()[-12:]
                    for i, line in enumerate(lines):
                        surf = font.render(line, True, (220, 80, 80) if i == 0 else (200, 200, 200))
                        screen.blit(surf, (30, 30 + i * 24))
                    pygame.display.flip()
                    pygame.time.wait(6000)
        except Exception:
            pass
        raise
    finally:
        # Ensure pygame is properly cleaned up even on unexpected exceptions
        try:
            game.quit()
        except Exception:
            pass
        # Das System loeste die Sperre beim Prozessende ohnehin; hier steht sie
        # fuer den geordneten Fall, damit ein sofortiger Neustart nicht auf
        # einen noch nicht aufgeraeumten Prozess trifft.
        try:
            einzelinstanz.freigeben()
        except Exception:
            pass


if __name__ == "__main__":
    main()
