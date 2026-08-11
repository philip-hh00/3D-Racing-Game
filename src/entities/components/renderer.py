"""Vehicle renderer component – programmatic top-down car sprite with rotation."""
from __future__ import annotations

import math

import pygame

from src.utils.math_utils import to_pygame
from src.core.settings import SCREEN_HEIGHT


class VehicleRenderer:
    """Draws a top-down car shape using pygame.draw.

    Creates a polygon-based car shape with body, windshield, and
    rear spoiler detail. Supports rotation and camera offset.
    """

    def __init__(
        self,
        width: int,
        height: int,
        color_primary: tuple[int, int, int],
        color_secondary: tuple[int, int, int] = (40, 40, 40),
        visual_type: str = "supercar",
        lack: str = "werk",
        config_key: str = "",
        entfaerbt: bool = False,
        deckkraft: float = 1.0,
    ) -> None:
        """
        Args:
            width: Car sprite width in pixels (side-to-side).
            height: Car sprite height in pixels (front-to-back).
            color_primary: Main body color.
            color_secondary: Detail color (windshield, accents).
            visual_type: Graphic profile to draw ("rookie", "supercar", "drifter", "limousine", "electric").
            lack: Lackkennung (``"werk"`` oder ``"<finish>:<farbe>"``). Werkslack
                laesst das Sprite unangetastet — Bestandsfahrzeuge sehen damit
                genauso aus wie vor Block D.
            config_key: Fahrzeugschluessel (z.B. ``"rookie_2"``), nur fuer die
                Maskenwerte des Lacks. Leer heisst: aus *visual_type* raten.
            entfaerbt: Das Fahrzeug grau zeichnen (Ghost).
            deckkraft: Deckkraft 0…1 — durchscheinend zeichnen (Ghost).
        """
        self.width = width
        self.height = height
        self.color_primary = color_primary
        self.color_secondary = color_secondary
        self.visual_type = visual_type
        self.lack = lack
        self.config_key = config_key or visual_type
        self.entfaerbt = bool(entfaerbt)
        self.deckkraft = float(deckkraft)
        self._orig_sprite = None
        self._punktfarbe: tuple[int, int, int] | None = None

        # Load image sprite or fall back to procedural drawing
        self._base_surface = self._verschleiern(self._load_car_sprite())
        if self._orig_sprite is not None:
            self._orig_sprite = self._verschleiern(self._orig_sprite)

    def _verschleiern(self, surf: pygame.Surface) -> pygame.Surface:
        """Entfaerben und/oder durchscheinend machen — sonst unveraendert.

        Immer auf einer **eigenen** Kopie: ``lack.sprite()`` haelt sein Ergebnis
        im Zwischenspeicher, und alle Fahrzeuge desselben Typs bekommen dieselbe
        Oberflaeche gereicht. Ein Ghost, der daran herumrechnet, wuerde die
        Mitfahrer gleich mit ausbleichen.
        """
        if surf is None or (not self.entfaerbt and self.deckkraft >= 1.0):
            return surf
        try:
            from src.core import lack
            # Erst verkleinern, dann rechnen. Werkslack liefert das Original
            # (bis 2816 px breit) — entfaerbt haette das eine Sekunde beim
            # Rennstart und 10 MB Arbeitsspeicher gekostet, fuer ein Auto, das
            # mit 54 px gezeichnet wird. Dieselbe Arbeitsbreite wie die
            # Umfaerbung benutzt (lack.BREITE_SPIEL).
            if surf.get_width() > lack.BREITE_SPIEL:
                from src.core import gfx
                hoehe = max(1, int(surf.get_height() * lack.BREITE_SPIEL
                                   / surf.get_width()))
                surf = gfx.scale(surf, (lack.BREITE_SPIEL, hoehe))
            if self.entfaerbt:
                surf = lack.graustufen(surf)
            if self.deckkraft < 1.0:
                surf = lack.durchscheinend(surf, self.deckkraft)
        except Exception as e:
            print(f"[VehicleRenderer] Entfaerben fehlgeschlagen ({self.visual_type}): {e}")
        return surf

    def punktfarbe(self) -> tuple[int, int, int]:
        """Die Farbe, die dieses Auto im Rennen hat — fuer den Minimap-Punkt.

        Ohne Bild bleibt es bei ``color_primary``; genau dann wird das Auto auch
        wirklich in dieser Farbe gezeichnet (siehe :meth:`_create_car_surface`).
        """
        if self._punktfarbe is None:
            from src.core import lack
            self._punktfarbe = (lack.wagenfarbe(self.config_key, self.visual_type,
                                                self.lack)
                                or tuple(self.color_primary[:3]))
        return self._punktfarbe

    def _load_car_sprite(self) -> pygame.Surface:
        """Load, colorkey-detect, crop, recolour and scale a car image.

        Freistellen und Zuschneiden liegen in ``src/core/lack.py``, damit
        Werkstatt und Fahrzeuglabor genau dasselbe Bild sehen wie das Rennen.
        Schlaegt das fehl, bleibt der programmatische Rueckfall.
        """
        try:
            from src.core import lack
            surf = lack.sprite(self.config_key, self.visual_type, self.lack,
                               lack.BREITE_SPIEL)
            if surf is not None and surf.get_width() > 0:
                self._orig_sprite = surf
                from src.core import gfx
                return gfx.scale(surf, (self.height, self.width))
        except Exception as e:
            print(f"[VehicleRenderer] Umfärben/Laden fehlgeschlagen ({self.visual_type}): {e}")

        return self._create_car_surface()

    def _create_car_surface(self) -> pygame.Surface:
        """Create a top-down car polygon on a transparent surface based on visual_type."""
        # Surface is padded to allow for rotation without clipping
        pad = 4
        w, h = self.width + pad * 2, self.height + pad * 2
        surf = pygame.Surface((h, w), pygame.SRCALPHA)
        cx, cy = h // 2, w // 2
        hw, hh = self.height // 2, self.width // 2

        col_primary = self.color_primary
        col_secondary = self.color_secondary
        col_dark = self._darken(col_primary, 0.6)
        col_accent = (255, 160, 0)  # Orange accent lines

        base_type = str(self.visual_type).split("_")[0]

        if base_type == "rookie":
            # --- Hatchback Design (Rounded Rear, Compact) ---
            body_pts = [
                (cx + hw, cy),                      # Nose
                (cx + hw - 4, cy - hh + 1),         # Front-left corner
                (cx + hw - 10, cy - hh + 1),        # Front fender left
                (cx - hw + 8, cy - hh),             # Rear fender left
                (cx - hw + 1, cy - hh + 4),         # Rear-left corner
                (cx - hw, cy - hh + 8),             # Back left
                (cx - hw, cy + hh - 8),             # Back right
                (cx - hw + 1, cy + hh - 4),         # Rear-right corner
                (cx - hw + 8, cy + hh),             # Rear fender right
                (cx + hw - 10, cy + hh - 1),        # Front fender right
                (cx + hw - 4, cy + hh - 1),         # Front-right corner
            ]
            pygame.draw.polygon(surf, col_primary, body_pts)
            pygame.draw.polygon(surf, col_dark, body_pts, 2)

            # Windshield + Roof (Larger glass canopy covering center to rear)
            ws_pts = [
                (cx + hw - 12, cy - hh + 3),
                (cx + hw - 12, cy + hh - 3),
                (cx - hw + 4, cy + hh - 4),
                (cx - hw + 4, cy - hh + 3),
            ]
            pygame.draw.polygon(surf, col_secondary, ws_pts)
            # Roof panel in the center
            pygame.draw.rect(surf, self._darken(col_primary, 0.8), (cx - hw + 10, cy - hh + 4, 15, self.width - 8), border_radius=2)

            # Lights
            pygame.draw.circle(surf, (255, 255, 200), (cx + hw - 2, cy - hh + 3), 2)
            pygame.draw.circle(surf, (255, 255, 200), (cx + hw - 2, cy + hh - 3), 2)
            pygame.draw.circle(surf, (255, 30, 30), (cx - hw + 1, cy - hh + 6), 2)
            pygame.draw.circle(surf, (255, 30, 30), (cx - hw + 1, cy + hh - 6), 2)

        elif base_type == "drifter":
            # --- Drift Machine (Aggressive Spoiler, exposed wheels outline) ---
            # Draw side wheels first so they are under the body
            pygame.draw.rect(surf, (20, 20, 20), (cx + hw - 12, cy - hh - 2, 8, 3), border_radius=1)
            pygame.draw.rect(surf, (20, 20, 20), (cx + hw - 12, cy + hh - 1, 8, 3), border_radius=1)
            pygame.draw.rect(surf, (20, 20, 20), (cx - hw + 6, cy - hh - 2, 8, 3), border_radius=1)
            pygame.draw.rect(surf, (20, 20, 20), (cx - hw + 6, cy + hh - 1, 8, 3), border_radius=1)

            # Body polygon
            body_pts = [
                (cx + hw, cy),                      # Sharp nose
                (cx + hw - 8, cy - hh + 1),         # Front left
                (cx - hw + 6, cy - hh + 1),         # Mid left
                (cx - hw + 2, cy - hh + 3),         # Rear left arch
                (cx - hw, cy - hh + 3),             # Rear left corner
                (cx - hw, cy + hh - 3),             # Rear right corner
                (cx - hw + 2, cy + hh - 3),         # Rear right arch
                (cx - hw + 6, cy + hh - 1),         # Mid right
                (cx + hw - 8, cy + hh - 1),         # Front right
            ]
            pygame.draw.polygon(surf, col_primary, body_pts)
            pygame.draw.polygon(surf, col_dark, body_pts, 2)

            # Sport Windshield
            ws_pts = [
                (cx + hw - 16, cy - hh + 4),
                (cx + hw - 16, cy + hh - 4),
                (cx - 2, cy + hh - 5),
                (cx - 2, cy - hh + 5),
            ]
            pygame.draw.polygon(surf, col_secondary, ws_pts)

            # High GT Spoiler wing
            pygame.draw.line(surf, (15, 15, 15), (cx - hw + 1, cy - hh - 3), (cx - hw + 1, cy + hh + 3), 3)
            # Spoiler mounts
            pygame.draw.rect(surf, col_dark, (cx - hw + 1, cy - hh + 4, 3, 2))
            pygame.draw.rect(surf, col_dark, (cx - hw + 1, cy + hh - 6, 3, 2))

            # Sporty decals (racing stripe)
            pygame.draw.line(surf, col_accent, (cx + hw - 8, cy), (cx - hw + 3, cy), 2)

            # Lights
            pygame.draw.circle(surf, (255, 255, 180), (cx + hw - 3, cy - hh + 4), 2)
            pygame.draw.circle(surf, (255, 255, 180), (cx + hw - 3, cy + hh - 4), 2)
            pygame.draw.circle(surf, (255, 20, 20), (cx - hw + 2, cy - hh + 5), 2)
            pygame.draw.circle(surf, (255, 20, 20), (cx - hw + 2, cy + hh - 5), 2)

        elif base_type == "limousine":
            # --- Luxus-Limousine (Long Sedan, defined Hood, Cabin, Trunk) ---
            body_pts = [
                (cx + hw, cy - hh + 4),             # Front bumper left
                (cx + hw, cy + hh - 4),             # Front bumper right
                (cx + hw - 4, cy + hh),             # Front right corner
                (cx - hw + 3, cy + hh),             # Rear right corner
                (cx - hw, cy + hh - 3),             # Back right
                (cx - hw, cy - hh + 3),             # Back left
                (cx - hw + 3, cy - hh),             # Rear left corner
                (cx + hw - 4, cy - hh),             # Front left corner
            ]
            pygame.draw.polygon(surf, col_primary, body_pts)
            pygame.draw.polygon(surf, col_dark, body_pts, 2)

            # Chrome accents at bumpers
            pygame.draw.line(surf, (220, 220, 230), (cx + hw, cy - hh + 5), (cx + hw, cy + hh - 5), 2)
            pygame.draw.line(surf, (220, 220, 230), (cx - hw, cy - hh + 5), (cx - hw, cy + hh - 5), 2)

            # Long cabin glass layout
            ws_pts = [
                (cx + hw - 20, cy - hh + 4),
                (cx + hw - 20, cy + hh - 4),
                (cx + hw - 26, cy + hh - 4),
                (cx + hw - 26, cy - hh + 4),
            ]
            pygame.draw.polygon(surf, col_secondary, ws_pts)
            pygame.draw.rect(surf, col_secondary, (cx - hw + 10, cy - hh + 3, 20, self.width - 6))
            pygame.draw.rect(surf, col_primary, (cx - hw + 14, cy - hh + 5, 14, self.width - 10))
            pygame.draw.rect(surf, col_dark, (cx - hw + 14, cy - hh + 5, 14, self.width - 10), 1)

            # Headlights (xenon white) & Taillights
            pygame.draw.circle(surf, (220, 240, 255), (cx + hw - 2, cy - hh + 4), 2)
            pygame.draw.circle(surf, (220, 240, 255), (cx + hw - 2, cy + hh - 4), 2)
            pygame.draw.line(surf, (255, 30, 30), (cx - hw + 2, cy - hh + 6), (cx - hw + 2, cy + hh - 6), 2)

        elif base_type == "electric":
            # --- Elektro-Prototyp (Streamlined futuristic sports car) ---
            # Coke-bottle body shape with defined fenders and tapered cockpit waist
            body_pts = [
                (cx + hw, cy - 4),                  # Nose front left
                (cx + hw, cy + 4),                  # Nose front right
                (cx + hw - 4, cy + hh - 3),         # Front-right wheel arch
                (cx + hw - 10, cy + hh - 1),        # Front-right fender
                (cx, cy + hh - 4),                  # Aerodynamic waist right
                (cx - hw + 10, cy + hh - 1),        # Rear-right fender
                (cx - hw + 4, cy + hh - 3),         # Rear-right corner
                (cx - hw, cy + 4),                  # Rear bumper right
                (cx - hw, cy - 4),                  # Rear bumper left
                (cx - hw + 4, cy - hh + 3),         # Rear-left corner
                (cx - hw + 10, cy - hh + 1),        # Rear-left fender
                (cx, cy - hh + 4),                  # Aerodynamic waist left
                (cx + hw - 10, cy - hh + 1),        # Front-left fender
                (cx + hw - 4, cy - hh + 3),         # Front-left wheel arch
            ]
            pygame.draw.polygon(surf, col_primary, body_pts)
            pygame.draw.polygon(surf, col_dark, body_pts, 2)

            # Translucent glass canopy (Teardrop capsule)
            canopy_pts = [
                (cx + hw - 12, cy - 3),
                (cx + hw - 16, cy + hh - 5),
                (cx - hw + 12, cy + hh - 5),
                (cx - hw + 8, cy),
                (cx - hw + 12, cy - hh + 5),
                (cx + hw - 16, cy - hh + 5),
            ]
            pygame.draw.polygon(surf, (15, 30, 45), canopy_pts)
            pygame.draw.polygon(surf, (0, 200, 255), canopy_pts, 1)

            # Aero winglet camera stalks (instead of mirrors)
            pygame.draw.line(surf, col_dark, (cx + 4, cy - hh + 1), (cx + 6, cy - hh - 3), 2)
            pygame.draw.circle(surf, (0, 255, 255), (cx + 6, cy - hh - 3), 1)
            pygame.draw.line(surf, col_dark, (cx + 4, cy + hh - 1), (cx + 6, cy + hh + 3), 2)
            pygame.draw.circle(surf, (0, 255, 255), (cx + 6, cy + hh + 3), 1)

            # Futuristic LED signature light bands
            # Front: Cyan headlights and central light band
            pygame.draw.line(surf, (0, 255, 255), (cx + hw - 1, cy - 5), (cx + hw - 1, cy + 5), 2)
            pygame.draw.circle(surf, (150, 255, 255), (cx + hw - 2, cy - hh + 4), 2)
            pygame.draw.circle(surf, (150, 255, 255), (cx + hw - 2, cy + hh - 4), 2)
            # Rear: Continuous cyan light strip
            pygame.draw.line(surf, (0, 255, 255), (cx - hw + 1, cy - hh + 6), (cx - hw + 1, cy + hh - 6), 2)

        else:
            # --- Supercar (Default Sleek Race Car) ---
            body_pts = [
                (cx + hw, cy),                      # Nose
                (cx + hw - 6, cy - hh + 2),         # Front-left
                (cx - hw + 4, cy - hh),             # Rear-left
                (cx - hw, cy - hh + 3),             # Rear corner left
                (cx - hw, cy + hh - 3),             # Rear corner right
                (cx - hw + 4, cy + hh),             # Rear-right
                (cx + hw - 6, cy + hh - 2),         # Front-right
            ]
            pygame.draw.polygon(surf, col_primary, body_pts)
            pygame.draw.polygon(surf, col_dark, body_pts, 2)

            # Windshield
            ws_pts = [
                (cx + hw - 10, cy - hh + 5),
                (cx + hw - 10, cy + hh - 5),
                (cx + 2, cy + hh - 6),
                (cx + 2, cy - hh + 6),
            ]
            pygame.draw.polygon(surf, col_secondary, ws_pts)

            # Rear spoiler
            spoiler_pts = [
                (cx - hw + 2, cy - hh + 2),
                (cx - hw + 2, cy + hh - 2),
                (cx - hw + 6, cy + hh - 4),
                (cx - hw + 6, cy - hh + 4),
            ]
            pygame.draw.polygon(surf, self._darken(col_primary, 0.4), spoiler_pts)

            # Lights
            pygame.draw.circle(surf, (255, 255, 200), (cx + hw - 3, cy - hh + 5), 2)
            pygame.draw.circle(surf, (255, 255, 200), (cx + hw - 3, cy + hh - 5), 2)
            pygame.draw.circle(surf, (255, 30, 30), (cx - hw + 2, cy - hh + 4), 2)
            pygame.draw.circle(surf, (255, 30, 30), (cx - hw + 2, cy + hh - 4), 2)

        return surf

    def draw(
        self,
        screen: pygame.Surface,
        world_pos: tuple[float, float],
        angle: float,
        camera_offset: pygame.Vector2,
        scale: float = 1.0,
    ) -> None:
        """Render the car at the given world position and rotation.

        Args:
            screen: Target pygame surface.
            world_pos: Position in pymunk coordinates (Y-up).
            angle: Rotation angle in radians (pymunk convention).
            camera_offset: Camera offset vector for viewport.
            scale: Optional scale factor to render the car larger.
        """
        # Convert pymunk position to pygame screen position
        screen_pos = to_pygame(world_pos, SCREEN_HEIGHT)
        screen_x = screen_pos[0] + camera_offset.x
        screen_y = screen_pos[1] + camera_offset.y

        # Scale surface if needed
        from src.core import gfx
        if self._orig_sprite is not None:
            target_w = int(self.height * scale)
            target_h = int(self.width * scale)
            surf = gfx.scale(self._orig_sprite, (target_w, target_h))
        else:
            surf = self._base_surface
            if scale != 1.0:
                w, h = surf.get_size()
                surf = gfx.scale(surf, (int(w * scale), int(h * scale)))

        # Rotate: pymunk angle is counter-clockwise radians
        # pygame rotation is counter-clockwise degrees
        angle_deg = math.degrees(angle)
        rotated = pygame.transform.rotate(surf, angle_deg)
        rect = rotated.get_rect(center=(int(screen_x), int(screen_y)))
        screen.blit(rotated, rect)

    @staticmethod
    def _darken(color: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
        """Darken a color by a factor (0.0 = black, 1.0 = unchanged)."""
        return (
            int(color[0] * factor),
            int(color[1] * factor),
            int(color[2] * factor),
        )
