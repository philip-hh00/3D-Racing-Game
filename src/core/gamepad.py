"""Gamepad/Controller support for menu navigation and gameplay.

Provides:
- Controller detection and hot-plug handling
- Button/axis constants (Xbox/PS layout)
- Menu event translation (dpad/buttons -> pygame key events)
- Deadzone handling for analog sticks
"""
from __future__ import annotations

import pygame
from typing import List, Tuple, Optional
from src.core.settings import SCREEN_WIDTH

# Button mapping (Xbox layout)
BTN_A = 0          # Cross / A - Confirm
BTN_B = 1          # Circle / B - Cancel/Back
BTN_X = 2          # Square / X
BTN_Y = 3          # Triangle / Y
BTN_LB = 4         # Left Bumper
BTN_RB = 5         # Right Bumper
BTN_BACK = 6       # Select / View / Back
BTN_START = 7      # Start / Options
BTN_LS = 8         # Left Stick Press
BTN_RS = 9         # Right Stick Press
BTN_DPAD_UP = 11
BTN_DPAD_DOWN = 12
BTN_DPAD_LEFT = 13
BTN_DPAD_RIGHT = 14

# Modern SDL (HIDAPI) exposes Xbox pads with 16 buttons in GameController
# order; the constants above describe the classic XInput layout. This table
# maps the modern raw ids onto the classic semantic ids. Dpad ids 11-14 are
# identical in both layouts.
_MODERN_TO_CLASSIC = {4: BTN_BACK, 5: 15, 6: BTN_START, 7: BTN_LS, 8: BTN_RS, 9: BTN_LB, 10: BTN_RB}


def _is_modern_layout(joy) -> bool:
    try:
        import sys
        if sys.platform == "win32":
            return False
        return joy.get_numbuttons() >= 15
    except Exception:
        return False

# Axis mapping
AXIS_LX = 0        # Left Stick X
AXIS_LY = 1        # Left Stick Y
AXIS_RX = 2        # Right Stick X
AXIS_RY = 3        # Right Stick Y
AXIS_LT = 4        # Left Trigger
AXIS_RT = 5        # Right Trigger

# Aliases used by input_source / mp_car_select
AX_LEFT_X = AXIS_LX
AX_LEFT_Y = AXIS_LY
AX_RT = AXIS_RT
AX_LT = AXIS_LT

# Deadzone for analog sticks (gameplay)
DEADZONE = 0.25

# Repeat delay for menu navigation (ms)
# REPEAT_DELAY: Wartezeit nach der ersten Eingabe bevor Auto-Repeat beginnt.
# REPEAT_INTERVAL: Abstand zwischen weiteren Wiederholungen beim Halten.
REPEAT_DELAY = 500
REPEAT_INTERVAL = 250

# Menu navigation thresholds (analog stick)
# The stick must exceed NAV_DEADZONE to trigger a command ("press").
# It must fall back below RETURN_ZONE before a new command is allowed ("release").
# This hysteresis prevents flickering when the stick hovers near the threshold.
NAV_DEADZONE = 0.40
RETURN_ZONE  = 0.20   # must return here before next command is allowed

# Connect/disconnect toast box: grows with the label, clamped to this range.
NOTIFY_MIN_W = 290
NOTIFY_MAX_W = 620


def _ellipsize(font, text: str, max_px: int) -> str:
    """Shorten *text* with a trailing ellipsis until it fits into *max_px*."""
    if max_px <= 0 or font.size(text)[0] <= max_px:
        return text
    cut = text
    while cut and font.size(cut + "…")[0] > max_px:
        cut = cut[:-1]
    return (cut.rstrip() + "…") if cut else "…"


def short_device_name(name: str, limit: int = 28) -> str:
    """Trim the vendor noise SDL puts into controller names for compact UI."""
    n = (name or "Controller").strip()
    for noise in (" for Windows", " (XInput)", " Controller", " Gamepad"):
        n = n.replace(noise, "")
    n = n.strip() or "Controller"
    return n if len(n) <= limit else n[: limit - 1].rstrip() + "…"


class GamepadManager:
    """Manages connected gamepads and translates input to menu events."""

    def __init__(self) -> None:
        self._joysticks: List[pygame.joystick.Joystick] = []
        self._menu_translation_enabled: bool = True
        self._active_device_filter: str | None = None
        # Per-device state (keyed by joystick instance id) so EVERY connected pad
        # can drive menus independently — not just joystick[0].
        self._btn_state: dict = {}          # iid -> list[bool]
        self._nav_dir: dict = {}            # iid -> (dx, dy)  current repeat direction
        self._nav_next: dict = {}           # iid -> next-repeat ms
        # Per-axis lock state for edge-triggered analog navigation.
        # Key: iid, Value: {"x": int, "y": int} where int is the locked direction
        # (−1/0/+1). A non-zero value means the stick is currently "pressed" in that
        # direction and no new command fires until it returns to RETURN_ZONE.
        self._axis_lock: dict = {}          # iid -> {"x": int, "y": int}
        # Startup guard: ignore joystick events for this many ms after init
        # to prevent queued-up events from firing all at once on first frame.
        self._ready_at: int = 0             # ticks timestamp after which input is accepted
        # Tracks whether the most recent real input came from a controller, so
        # text fields only pop the on-screen keyboard for controller users.
        self._using_pad: bool = False
        self._notifications: List[dict] = []

    # ------------------------------------------------------------------
    # Device queries
    # ------------------------------------------------------------------
    def device_count(self) -> int:
        return len(self._joysticks)

    def device(self, index: int):
        return self._joysticks[index] if 0 <= index < len(self._joysticks) else None

    def device_name(self, index: int) -> str:
        j = self.device(index)
        try:
            return j.get_name() if j is not None else "—"
        except Exception:
            return "Controller"

    def index_of_instance(self, instance_id: int):
        for i, j in enumerate(self._joysticks):
            try:
                if j.get_instance_id() == instance_id:
                    return i
            except Exception:
                pass
        return None

    def observe(self, events: List[pygame.event.Event]) -> None:
        """Note whether the player is currently using a pad or keyboard/mouse."""
        for e in events:
            if e.type == pygame.JOYBUTTONDOWN or e.type == pygame.JOYHATMOTION:
                self._using_pad = True
            elif e.type == pygame.JOYAXISMOTION and abs(getattr(e, "value", 0.0)) > DEADZONE:
                self._using_pad = True
            elif e.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
                self._using_pad = False
            elif e.type == pygame.MOUSEMOTION:
                # Avoid switching due to minor optical mouse drift or vibrations
                rel = getattr(e, "rel", (0, 0))
                if rel[0] * rel[0] + rel[1] * rel[1] > 25: # threshold of 5 pixels
                    self._using_pad = False

    def using_pad(self) -> bool:
        return self._using_pad

    def normalize_button_events(self, events):
        """Rewrite JOYBUTTONDOWN/UP button ids from the modern 16-button layout
        to the classic semantic ids the whole codebase compares against.
        Returns a new list; non-joystick events pass through unchanged."""
        out = []
        for e in events:
            if e.type in (pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP):
                iid = getattr(e, "instance_id", None)
                idx = self.index_of_instance(iid) if iid is not None else None
                joy = self.device(idx) if idx is not None else None
                if joy is not None and _is_modern_layout(joy) and e.button in _MODERN_TO_CLASSIC:
                    attrs = dict(e.__dict__)
                    attrs["button"] = _MODERN_TO_CLASSIC[e.button]
                    e = pygame.event.Event(e.type, attrs)
            out.append(e)
        return out

    # ------------------------------------------------------------------
    # Initialization & Hot-plug
    # ------------------------------------------------------------------
    def init(self) -> None:
        """Initialize joystick subsystem and detect connected controllers."""
        pygame.joystick.init()
        self._scan_joysticks()
        self._ready_at = pygame.time.get_ticks() + 800

    def _scan_joysticks(self) -> None:
        """Scan for connected joysticks and initialize them."""
        # Keep track of existing joysticks by instance ID
        existing = {}
        for j in self._joysticks:
            try:
                if j.get_init():
                    existing[j.get_instance_id()] = j
            except Exception:
                pass

        self._joysticks.clear()
        for i in range(pygame.joystick.get_count()):
            try:
                joy = pygame.joystick.Joystick(i)
                try:
                    instance_id = joy.get_instance_id()
                except Exception:
                    instance_id = None
                
                if instance_id is not None and instance_id in existing:
                    # Reuse existing initialized joystick object
                    self._joysticks.append(existing[instance_id])
                else:
                    joy.init()
                    self._joysticks.append(joy)
                    print(f"[Gamepad] Connected: {joy.get_name()} (ID: {joy.get_instance_id()})")
            except pygame.error as e:
                print(f"[Gamepad] Failed to init joystick {i}: {e}")

        # Reset per-device menu state on any topology change.
        self._nav_dir.clear()
        self._nav_next.clear()
        self._axis_lock.clear()

        # Flush all queued joystick events that built up before/during init,
        # but do NOT set self._ready_at here. That is done only in init() on game start.
        pygame.event.clear([
            pygame.JOYAXISMOTION,
            pygame.JOYBALLMOTION,
            pygame.JOYBUTTONDOWN,
            pygame.JOYBUTTONUP,
            pygame.JOYHATMOTION,
        ])

    def process_system(self, events: List[pygame.event.Event]) -> None:
        """Process system events for hot-plug detection and rumble on plug."""
        for event in events:
            if event.type == pygame.JOYDEVICEADDED:
                iid = None
                try:
                    temp_joy = pygame.joystick.Joystick(event.device_index)
                    temp_joy.init()
                    name = temp_joy.get_name()
                    try:
                        iid = temp_joy.get_instance_id()
                    except Exception:
                        iid = None
                    try:
                        temp_joy.rumble(0.6, 0.6, 250)
                    except Exception:
                        pass
                except Exception:
                    name = "Controller"
                self._scan_joysticks()
                from src.core.i18n import tr
                idx = self.index_of_instance(iid) if iid is not None else None
                slot = (idx if idx is not None else 0) + 1
                self.add_notification(
                    tr("Controller {i} verbunden: {n}").format(i=slot, n=short_device_name(name)),
                    is_connect=True)
            elif event.type == pygame.JOYDEVICEREMOVED:
                self._scan_joysticks()
                from src.core.i18n import tr
                self.add_notification(tr("Controller getrennt"), is_connect=False)

    def rumble(self, index: int, low: float, high: float, duration_ms: int) -> bool:
        """Trigger vibration feedback on a controller."""
        joy = self.device(index)
        if joy:
            try:
                return joy.rumble(low, high, duration_ms)
            except Exception:
                pass
        return False

    def add_notification(self, text: str, is_connect: bool = True) -> None:
        """Add connection notification to the display queue."""
        self._notifications.append({
            "text": text,
            "timer": 4.0,
            "is_connect": is_connect
        })

    def draw_notifications(self, screen: pygame.Surface, dt: float) -> None:
        """Draw active connection notifications stacked in the top-right corner.

        The box grows with the label (controller names are long and vary a lot)
        and the text is ellipsised once it hits NOTIFY_MAX_W, so it can never
        bleed out of the frame.
        """
        if not self._notifications:
            return
        font = pygame.font.SysFont("Arial", 16, bold=True)
        pad_left, pad_right = 45, 20
        y = 30
        for notif in list(self._notifications):
            notif["timer"] -= dt
            if notif["timer"] <= 0:
                self._notifications.remove(notif)
                continue

            text = _ellipsize(font, notif["text"], NOTIFY_MAX_W - pad_left - pad_right)
            box_w = max(NOTIFY_MIN_W,
                        min(NOTIFY_MAX_W, font.size(text)[0] + pad_left + pad_right))
            x = SCREEN_WIDTH - box_w - 30

            opacity = min(1.0, notif["timer"])
            if notif["timer"] > 3.5:
                slide = (notif["timer"] - 3.5) / 0.5
                cx = x + (box_w + 60) * slide
            else:
                cx = x

            rect = pygame.Rect(cx, y, box_w, 60)
            surf = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
            bg_col = (18, 20, 26, int(220 * opacity))
            border_col = (60, 200, 90, int(255 * opacity)) if notif["is_connect"] else (210, 60, 60, int(255 * opacity))

            pygame.draw.rect(surf, bg_col, (0, 0, rect.width, rect.height), border_radius=10)
            pygame.draw.rect(surf, border_col, (0, 0, rect.width, rect.height), 2, border_radius=10)
            pygame.draw.circle(surf, border_col, (25, rect.height // 2), 6)

            screen.blit(surf, (rect.x, rect.y))

            text_surf = font.render(text, True, (255, 255, 255))
            text_surf.set_alpha(int(255 * opacity))
            screen.blit(text_surf, (rect.x + pad_left, rect.y + 19))

            y += 75

    # ------------------------------------------------------------------
    # Menu Translation
    # ------------------------------------------------------------------
    # (NAV_DEADZONE and RETURN_ZONE are module-level constants above.)



    def set_menu_translation(self, enabled: bool) -> None:
        """Legacy toggle (kept for compatibility). Menu translation is now gated
        per-state by the game loop via ``state.raw_gamepad`` — this only clears
        the per-device repeat state so a fresh screen starts clean."""
        self._menu_translation_enabled = enabled
        self._nav_dir.clear()
        self._nav_next.clear()

    def set_device_filter(self, device: str | None) -> None:
        self._active_device_filter = device

    def menu_events(self, events: List[pygame.event.Event]) -> List[pygame.event.Event]:
        """Translate gamepad input to synthetic keyboard events for menu navigation.

        Design principles
        -----------------
        * **D-Pad first**: HAT events are natively digital (−1/0/+1) and need no
          deadzone handling. If a D-Pad input is seen in this frame, analog stick
          events are ignored so the two never interfere.
        * **Edge-triggered analog**: The analog stick fires exactly once when it
          crosses NAV_DEADZONE ("press"). No further command is generated until it
          returns to RETURN_ZONE ("release"). This prevents menu bouncing.
        * **Repeat while held**: After REPEAT_DELAY ms, the held direction auto-
          repeats every REPEAT_INTERVAL ms – just like keyboard typematic.
        * **Per-device isolation**: Every connected pad has its own state, so two
          controllers can navigate independently without interfering.
        """
        if not self._joysticks:
            return []

        if self._active_device_filter == "keyboard":
            return []

        allowed_iid = None
        if self._active_device_filter and self._active_device_filter.startswith("pad"):
            try:
                pad_idx = int(self._active_device_filter[3:])
                if pad_idx < len(self._joysticks):
                    allowed_iid = self._joysticks[pad_idx].get_instance_id()
                else:
                    return []
            except ValueError:
                pass

        synthetic: List[pygame.event.Event] = []
        now = pygame.time.get_ticks()

        # Startup guard: swallow all joystick input until the cooldown expires.
        if now < self._ready_at:
            return []

        by_iid = {}
        for j in self._joysticks:
            try:
                by_iid[j.get_instance_id()] = j
            except Exception:
                pass

        # --- Pass 1: Collect raw events grouped by device ----------------
        # Devices that produced a HAT event this frame suppress analog input.
        hat_devices: set = set()
        # Collect latest axis values per device (many JOYAXISMOTION per frame
        # → only the last one matters for decision-making).
        latest_axis: dict = {}   # iid -> {axis_id: value}

        for e in events:
            iid = getattr(e, "instance_id", None)
            if allowed_iid is not None and iid != allowed_iid:
                continue
            if iid not in by_iid:
                continue

            if e.type == pygame.JOYBUTTONDOWN:
                if e.button in (BTN_DPAD_UP, BTN_DPAD_DOWN, BTN_DPAD_LEFT, BTN_DPAD_RIGHT):
                    hat_devices.add(iid)
                    dx = -1 if e.button == BTN_DPAD_LEFT else (1 if e.button == BTN_DPAD_RIGHT else 0)
                    dy = 1 if e.button == BTN_DPAD_UP else (-1 if e.button == BTN_DPAD_DOWN else 0)
                    self._process_dir_change(iid, dx, dy, now, synthetic)
                else:
                    synthetic.extend(self._button_to_events(e.button))
            elif e.type == pygame.JOYBUTTONUP and e.button in (BTN_DPAD_UP, BTN_DPAD_DOWN, BTN_DPAD_LEFT, BTN_DPAD_RIGHT):
                self._process_dir_change(iid, 0, 0, now, synthetic)

            elif e.type == pygame.JOYHATMOTION:
                hx, hy = e.value
                hat_devices.add(iid)
                self._process_dir_change(iid, hx, hy, now, synthetic)

            elif e.type == pygame.JOYAXISMOTION and e.axis in (AXIS_LX, AXIS_LY):
                if iid not in latest_axis:
                    latest_axis[iid] = {}
                latest_axis[iid][e.axis] = e.value

        # --- Pass 2: Process consolidated analog events ------------------
        for iid, axes in latest_axis.items():
            if iid in hat_devices:
                continue  # D-Pad takes priority this frame

            joy = by_iid.get(iid)
            if joy is None:
                continue

            lx = axes.get(AXIS_LX, joy.get_axis(AXIS_LX))
            ly = axes.get(AXIS_LY, joy.get_axis(AXIS_LY))

            lock = self._axis_lock.setdefault(iid, {"x": 0, "y": 0})

            # --- X axis edge detection -----------------------------------
            if abs(lx) < RETURN_ZONE:
                lock["x"] = 0          # stick returned to center → unlock
            if abs(lx) >= NAV_DEADZONE and lock["x"] == 0:
                lock["x"] = 1 if lx > 0 else -1   # lock & fire
                dx = lock["x"]
            else:
                dx = 0

            # --- Y axis edge detection -----------------------------------
            if abs(ly) < RETURN_ZONE:
                lock["y"] = 0
            if abs(ly) >= NAV_DEADZONE and lock["y"] == 0:
                lock["y"] = 1 if ly > 0 else -1
                dy_raw = lock["y"]
                dy = -dy_raw           # pygame Y is inverted vs screen
            else:
                dy = 0

            if dx != 0 or dy != 0:
                self._process_dir_change(iid, dx, dy, now, synthetic)
            elif abs(lx) < RETURN_ZONE and abs(ly) < RETURN_ZONE:
                # Both axes back to center → clear repeat direction
                self._process_dir_change(iid, 0, 0, now, synthetic)


        # Repeat held directions per device.
        for iid, d in self._nav_dir.items():
            if allowed_iid is not None and iid != allowed_iid:
                continue
            if d != (0, 0) and now >= self._nav_next.get(iid, 0):
                self._nav_next[iid] = now + REPEAT_INTERVAL
                synthetic.extend(self._dir_to_events(d[0], d[1]))

        return synthetic

    def _process_dir_change(self, iid, dx: int, dy: int, now: int,
                            synthetic: List[pygame.event.Event]) -> None:
        cur = (dx, dy)
        prev = self._nav_dir.get(iid, (0, 0))
        if cur == (0, 0):
            self._nav_dir[iid] = (0, 0)
        elif cur != prev:
            self._nav_dir[iid] = cur
            self._nav_next[iid] = now + REPEAT_DELAY
            synthetic.extend(self._dir_to_events(dx, dy))

    def _dir_to_events(self, dx: int, dy: int) -> List[pygame.event.Event]:
        """Convert direction to synthetic key events.

        All synthetic events include ``unicode=''`` so that any code that
        reads ``event.unicode`` (e.g. text-input fields) doesn't raise an
        AttributeError on gamepad-generated events. Directional events also
        carry ``synthetic=True`` so consumers can distinguish them from real
        keyboard input.
        """
        events = []
        if dx == -1:
            events.append(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_LEFT, unicode='', mod=0, synthetic=True))
        elif dx == 1:
            events.append(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT, unicode='', mod=0, synthetic=True))
        if dy == -1:
            events.append(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN, unicode='', mod=0, synthetic=True))
        elif dy == 1:
            events.append(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP, unicode='', mod=0, synthetic=True))
        return events

    def _button_to_events(self, button: int) -> List[pygame.event.Event]:
        """Map gamepad buttons to menu key events.

        All synthetic events include ``unicode=''`` so that any code that
        reads ``event.unicode`` doesn't raise an AttributeError. Button events
        also carry ``synthetic=True`` and ``pad_button`` (the original button id)
        so consumers can distinguish them from real keyboard input.
        """
        events = []
        if button == BTN_A:
            events.append(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode='', mod=0, synthetic=True, pad_button=button))
        elif button == BTN_B:
            events.append(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode='', mod=0, synthetic=True, pad_button=button))
        elif button == BTN_START:
            events.append(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode='', mod=0, synthetic=True, pad_button=button))
        elif button == BTN_BACK:
            events.append(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode='', mod=0, synthetic=True, pad_button=button))
        elif button == BTN_X:
            events.append(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_x, unicode='x', mod=0, synthetic=True, pad_button=button))
        elif button == BTN_Y:
            events.append(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_y, unicode='y', mod=0, synthetic=True, pad_button=button))
        elif button == BTN_LB:
            events.append(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_PAGEUP, unicode='', mod=0, synthetic=True, pad_button=button))
        elif button == BTN_RB:
            events.append(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_PAGEDOWN, unicode='', mod=0, synthetic=True, pad_button=button))
        return events

    # ------------------------------------------------------------------
    # Gameplay Input (for PlayerVehicle)
    # ------------------------------------------------------------------
    def get_gameplay_input(self, player_index: int = 0) -> Tuple[float, float, float, bool]:
        """Get gameplay input from controller.

        Returns:
            (steer, accel, brake, handbrake) - all in range [-1, 1] or [0, 1]
        """
        if player_index >= len(self._joysticks):
            return (0.0, 0.0, 0.0, False)

        joy = self._joysticks[player_index]

        # Steering: Left stick X
        steer = joy.get_axis(AXIS_LX)
        if abs(steer) < DEADZONE:
            steer = 0.0

        # Acceleration: Right trigger (RT)
        accel = joy.get_axis(AXIS_RT)
        if accel < DEADZONE:
            accel = 0.0
        else:
            accel = (accel - DEADZONE) / (1.0 - DEADZONE)  # Normalize

        # Brake: Left trigger (LT)
        brake = joy.get_axis(AXIS_LT)
        if brake < DEADZONE:
            brake = 0.0
        else:
            brake = (brake - DEADZONE) / (1.0 - DEADZONE)

        # Handbrake: A button or RB
        rb_raw = 10 if _is_modern_layout(joy) else BTN_RB
        handbrake = joy.get_button(BTN_A) or joy.get_button(rb_raw)

        return (steer, accel, brake, handbrake)

    def get_num_connected(self) -> int:
        """Return number of connected controllers."""
        return len(self._joysticks)

    def is_connected(self, index: int = 0) -> bool:
        """Check if controller at index is connected."""
        return 0 <= index < len(self._joysticks)


# Global singleton instance
_gamepad_manager: Optional[GamepadManager] = None


def init() -> None:
    """Initialize the global gamepad manager."""
    global _gamepad_manager
    if _gamepad_manager is None:
        _gamepad_manager = GamepadManager()
        _gamepad_manager.init()


def process_system(events: List[pygame.event.Event]) -> None:
    """Process system events (hot-plug)."""
    if _gamepad_manager:
        _gamepad_manager.process_system(events)


def set_menu_translation(enabled: bool) -> None:
    """Enable/disable menu translation globally."""
    if _gamepad_manager:
        _gamepad_manager.set_menu_translation(enabled)


def set_device_filter(device: str | None) -> None:
    """Set active input device filter for menu translation."""
    if _gamepad_manager:
        _gamepad_manager.set_device_filter(device)


def menu_events(events: List[pygame.event.Event]) -> List[pygame.event.Event]:
    """Get synthetic menu events from gamepad."""
    if _gamepad_manager:
        return _gamepad_manager.menu_events(events)
    return []


#: Rohe Controller-Ereignisse. Sobald uebersetzt wird, haben sie ausgedient.
ROH_TYPEN = (pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP, pygame.JOYHATMOTION,
             pygame.JOYAXISMOTION, pygame.JOYBALLMOTION)


def menue_eingaben(events: List[pygame.event.Event]) -> List[pygame.event.Event]:
    """Ein Druck, eine Fassung: rohe Pad-Ereignisse raus, uebersetzte rein.

    Vorher gingen beide an die Zustaende, und wer beide auswertete, machte pro
    Druck zwei Schritte. Ein einziges B liess im Editor die Eigenschaftsspalte
    los, verwarf das Werkzeug UND verliess den Editor; in der Rennpause schloss
    es die Einstellungen und setzte gleich das Rennen fort (gemeldet
    02.08.2026).

    Zustaende, die den Pad direkt lesen wollen, melden das ueber
    ``raw_gamepad`` — dann laeuft diese Funktion gar nicht erst.
    """
    return [e for e in events if e.type not in ROH_TYPEN] + menu_events(events)


def get_gameplay_input(player_index: int = 0) -> Tuple[float, float, float, bool]:
    """Get gameplay input for a player."""
    if _gamepad_manager:
        return _gamepad_manager.get_gameplay_input(player_index)
    return (0.0, 0.0, 0.0, False)


def get_num_connected() -> int:
    """Get number of connected controllers."""
    if _gamepad_manager:
        return _gamepad_manager.get_num_connected()
    return 0


def device_count() -> int:
    return _gamepad_manager.device_count() if _gamepad_manager else 0


def device(index: int = 0):
    return _gamepad_manager.device(index) if _gamepad_manager else None


def device_name(index: int = 0) -> str:
    return _gamepad_manager.device_name(index) if _gamepad_manager else "—"


def index_of_instance(instance_id: int):
    return _gamepad_manager.index_of_instance(instance_id) if _gamepad_manager else None


def observe(events: List[pygame.event.Event]) -> None:
    if _gamepad_manager:
        _gamepad_manager.observe(events)


def using_pad() -> bool:
    return _gamepad_manager.using_pad() if _gamepad_manager else False


def normalize_button_events(events):
    if _gamepad_manager:
        return _gamepad_manager.normalize_button_events(events)
    return events


def rumble(index: int, low: float, high: float, duration_ms: int) -> bool:
    """Trigger vibration on controller globally."""
    if _gamepad_manager:
        return _gamepad_manager.rumble(index, low, high, duration_ms)
    return False


def draw_notifications(screen: pygame.Surface, dt: float) -> None:
    """Render notifications globally."""
    if _gamepad_manager:
        _gamepad_manager.draw_notifications(screen, dt)


def get_stick_axes(index: int = 0) -> Tuple[float, float]:
    """Get left stick X, Y axis values with deadzone applied."""
    if _gamepad_manager and index < _gamepad_manager.device_count():
        joy = _gamepad_manager.device(index)
        try:
            lx = joy.get_axis(AXIS_LX)
            ly = joy.get_axis(AXIS_LY)
            if abs(lx) < DEADZONE: lx = 0.0
            if abs(ly) < DEADZONE: ly = 0.0
            return lx, ly
        except Exception:
            pass
    return 0.0, 0.0


def get_right_stick_axes(index: int = 0) -> Tuple[float, float]:
    """Get right stick X, Y axis values with deadzone applied."""
    if _gamepad_manager and index < _gamepad_manager.device_count():
        joy = _gamepad_manager.device(index)
        try:
            rx = joy.get_axis(AXIS_RX)
            ry = joy.get_axis(AXIS_RY)
            if abs(rx) < DEADZONE: rx = 0.0
            if abs(ry) < DEADZONE: ry = 0.0
            return rx, ry
        except Exception:
            pass
    return 0.0, 0.0


def get_trigger_axis(index: int = 0, is_left: bool = True) -> float:
    """Get trigger axis value, normalized to 0..1 (0 at rest, 1 fully pressed) with 5% deadzone."""
    if _gamepad_manager and index < _gamepad_manager.device_count():
        joy = _gamepad_manager.device(index)
        axis = AXIS_LT if is_left else AXIS_RT
        try:
            val = joy.get_axis(axis)
            norm = (val + 1.0) * 0.5
            if norm < 0.05:
                return 0.0
            return max(0.0, min(1.0, (norm - 0.05) / 0.95))
        except Exception:
            pass
    return 0.0
