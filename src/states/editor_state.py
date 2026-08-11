"""In-game tile track editor — grid + drag-and-drop piece placement.

The player builds a closed loop from straights and curves on a grid, then
publishes it to data/tracks/custom/ where it appears in the track menu next to
the bundled tracks. Work-in-progress is auto-saved to data/tracks/drafts/ — the
player never touches a file dialog.

Layout:
    left    palette (straight, curve r1/r2/r3 thumbnails)
    centre  grid canvas (pan: middle-drag / arrows, zoom: wheel)
    top     status bar (loop open/closed)
    bottom  help line

Controls:
    click palette piece → ghost on cursor → click grid to place
    R                    rotate ghost
    wheel over curve     change radius 1–3   (else wheel = zoom)
    right-click piece    delete
    drag piece           move it
    Ctrl+Z / Ctrl+Y      undo / redo
    TAB                  properties overlay (name, width, background, difficulty)
    S                    save draft   ENTER  publish (needs closed loop)
    ESC                  back to menu (auto-saves draft)
"""
from __future__ import annotations

import glob
import math
import os
from typing import TYPE_CHECKING

import pygame

from src.states.base_state import BaseState
from src.core.settings import (
    SCREEN_WIDTH, SCREEN_HEIGHT,
    COLOR_UI_ACCENT, COLOR_UI_TEXT, COLOR_UI_SUCCESS, COLOR_UI_DANGER,
)
from src.track.tile_track import CELL, Piece, TileTrackDraft
from src.core.i18n import tr

if TYPE_CHECKING:
    from src.core.state_machine import StateMachine

from src.core import gamepad
from src.ui.widgets import OnScreenKeyboard
from src.ui import hints, theme

class DraftNameWrapper:
    """Wrapper to map name changes from OnScreenKeyboard onto draft name."""
    def __init__(self, state: EditorState) -> None:
        self.state = state
    @property
    def text(self) -> str:
        return self.state.draft.name
    def handle_key(self, key: int, unicode: str = "") -> None:
        self.state._dirty = True
        if key == pygame.K_BACKSPACE:
            self.state.draft.name = self.state.draft.name[:-1]
        elif unicode and unicode.isprintable() and len(self.state.draft.name) < 28:
            self.state.draft.name += unicode

# --- Layout constants ---
PALETTE_W = 300
RIGHT_W = 420
TOP_H = 70
BOTTOM_H = 48

# --- Colors ---
_BG = (24, 26, 32)
_GRID_LINE = (40, 44, 54)
_GRID_LINE_MAJOR = (58, 62, 76)
_PANEL = (16, 18, 24)
_PANEL_BORDER = (55, 60, 76)
_ASPHALT = (70, 72, 82)
_ASPHALT_EDGE = (150, 150, 165)
_CENTERLINE = (220, 220, 220)
_GHOST_OK = (60, 200, 90)
_GHOST_BAD = (210, 60, 60)
_OPEN_PORT = (255, 170, 40)

_DIFFICULTIES = ["Einfach", "Mittel", "Schwer"]


def veroeffentlichte_strecken() -> list[str]:
    """Veröffentlichte Strecken über alle Wurzeln, nicht nur relativ zum
    Arbeitsverzeichnis.

    Auf einem gepackten macOS-Build liegen eigene und geschenkte Strecken in
    ``Application Support``, während das Arbeitsverzeichnis ins Bundle zeigt —
    eine heruntergeladene Strecke war dort weder im Editor noch in der
    Streckenauswahl zu sehen (Playtest 29.07.2026).
    """
    from src.core import paths
    return [str(p) for p in paths.track_files("custom")]


def ist_veroeffentlicht(slug: str) -> bool:
    """Gibt es zu diesem Kurznamen eine veröffentlichte Strecke?"""
    ziel = f"{slug}.json".lower()
    return any(os.path.basename(p).lower() == ziel
               for p in veroeffentlichte_strecken())


class EditorState(BaseState):
    """Pygame track editor state."""

    def __init__(self, state_machine: StateMachine) -> None:
        super().__init__(state_machine)
        self.draft = TileTrackDraft.new_with_start()

        # Mode: "browse" (start screen) or "edit" (canvas)
        self._mode = "browse"
        self._dirty = False
        self._dirty_prompt = False
        self.dialog = None
        self._pending_action = None
        self._browse_idx = 0
        self._browse_scroll = 0
        self._projects: list[dict] = []
        #: Der Rueckweg aus der Projektliste als Knopf, oben links unter der
        #: Reiterleiste — auf derselben Hoehe wie in den Menueseiten.
        from src.ui.widgets import ZurueckKnopf
        from src.states.menu_shell_state import TAB_H as _TAB_H
        self._zurueck_knopf = ZurueckKnopf(40, _TAB_H + 16)

        # Camera (world coord at grid-area centre + zoom)
        self._cam_x = 5.5 * CELL
        self._cam_y = 5.5 * CELL
        self._zoom = 0.22

        # Interaction
        self._tool: dict | None = None      # {kind, radius, rotation} or None
        self._moving_idx: int | None = None  # index of piece being dragged
        self._panning = False
        self._pan_last = (0, 0)

        # Undo / redo (snapshots of the piece list + start index)
        self._undo: list[tuple[list[Piece], int]] = []
        self._redo: list[tuple[list[Piece], int]] = []

        # Properties sidebar state
        self._props_focused = False
        self._props_field = 0
        self._backgrounds = self._scan_backgrounds()

        # Cached loop/validation status (recomputed only when geometry changes —
        # validate_game() is O(n²), far too heavy to run every frame).
        self._geo_dirty = True
        self._is_closed = False
        self._open_ports_cache: list = []
        self._status_text = ""
        self._status_color = COLOR_UI_DANGER

        self._gp_cursor = [SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2]
        self.osk: OnScreenKeyboard | None = None

        # Toast
        self._toast = ""
        self._toast_t = 0.0
        self._time = 0.0

        # Fonts (set in enter)
        self.f_title: pygame.font.Font | None = None
        self.f_body: pygame.font.Font | None = None
        self.f_small: pygame.font.Font | None = None

    # ==================================================================
    # Lifecycle
    # ==================================================================
    def enter(self, **kwargs) -> None:
        self.f_title = pygame.font.Font(None, 44)
        self.f_body = pygame.font.Font(None, 30)
        self.f_small = pygame.font.Font(None, 24)

        self._tool = None
        self._moving_idx = None
        self._undo.clear()
        self._redo.clear()
        self._props_focused = False
        self._props_field = 0
        self._dirty_prompt = False
        self._backgrounds = self._scan_backgrounds()
        
        self._video = None
        self._video_stem = None

        draft = kwargs.get("draft")
        if isinstance(draft, TileTrackDraft):
            self.draft = draft
            self._enter_edit()
        else:
            # Start on the browser screen: new / open drafts / re-edit published.
            self._mode = "browse"
            self._browse_idx = 0
            self._browse_scroll = 0
            self._projects = self._scan_projects()

    def exit(self) -> None:
        if getattr(self, "_video", None) is not None:
            self._video.close()
            self._video = None
            self._video_stem = None

    def _enter_edit(self) -> None:
        self._mode = "edit"
        self._dirty = False
        self._tool = None
        self._moving_idx = None
        self._undo.clear()
        self._redo.clear()
        self._geo_dirty = True
        self._gp_cursor = [SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2]
        self.osk = None
        self._center_camera()

    def _exit_edit(self) -> None:
        self._mode = "browse"
        self._projects = self._scan_projects()
        self._browse_ensure_visible()



    def _refresh_status(self) -> None:
        """Recompute the cached loop/validation status (called on geometry change)."""
        self._is_closed = self.draft.is_closed_loop()
        self._open_ports_cache = self.draft.open_ports()
        if self._is_closed:
            errs = self.draft.validate_game()
            if errs:
                self._status_text = f"{theme.WARNUNG} {errs[0].message}"
                self._status_color = COLOR_UI_DANGER
            else:
                self._status_text = (f"{theme.HAKEN} "
                                     + tr("GESCHLOSSEN  —  ENTER zum Veröffentlichen"))
                self._status_color = COLOR_UI_SUCCESS
        else:
            n = len(self._open_ports_cache)
            self._status_text = tr("OFFEN  —  {n} Ende(n) offen").format(n=n)
            self._status_color = COLOR_UI_DANGER
        self._geo_dirty = False

    # ------------------------------------------------------------------
    # Project browser
    # ------------------------------------------------------------------
    def _scan_projects(self) -> list[dict]:
        """Entries for the start screen: new + drafts + re-editable published."""
        import json
        entries: list[dict] = [{"type": "new", "name": tr("Neue Strecke"), "path": None}]
        seen_names = set()
        # Drafts
        for p in sorted(glob.glob(os.path.join("data", "tracks", "drafts", "*.json"))):
            try:
                with open(p, encoding="utf-8") as f:
                    name = json.load(f).get("name") or os.path.splitext(os.path.basename(p))[0]
            except Exception:
                name = os.path.splitext(os.path.basename(p))[0]
            from src.track.tile_track import _slugify
            entries.append({"type": "draft", "name": name, "path": p,
                            "is_published": ist_veroeffentlicht(_slugify(name))})
            seen_names.add(name)
        # Published custom tracks that carry editor_tiles (re-editable)
        for p in veroeffentlichte_strecken():
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
                if "editor_tiles" not in data:
                    continue
                name = data.get("name") or os.path.splitext(os.path.basename(p))[0]
                if name in seen_names:
                    continue
            except Exception:
                continue
            entries.append({"type": "custom", "name": name, "path": p})
        return entries

    def _open_project(self, entry: dict) -> None:
        try:
            if entry["type"] == "new":
                self.draft = TileTrackDraft.new_with_start()
            elif entry["type"] == "draft":
                self.draft = TileTrackDraft.load_draft(entry["path"])
            elif entry["type"] == "custom":
                self.draft = TileTrackDraft.load_from_custom(entry["path"])
            self._enter_edit()
        except Exception as exc:
            self._show_toast(tr("Laden fehlgeschlagen: {exc}").format(exc=exc))

    def _editor_confirm_delete(self) -> None:
        if not self.draft or not self.draft.name:
            return
        if self.draft.is_published:
            self._show_toast(tr("Erst Veröffentlichung aufheben, bevor gelöscht werden kann."))
            return
        from src.ui.widgets import Dialog
        self.dialog = Dialog(
            title=tr("Strecke löschen?"),
            message=tr('"{n}" wird dauerhaft gelöscht.').format(n=self.draft.name),
            buttons=[(tr("Löschen"), "yes"), (tr("Abbrechen"), "cancel")]
        )
        self._pending_action = ("delete_track", self.draft.name)

    def _editor_confirm_unpublish(self) -> None:
        if not self.draft or not self.draft.name:
            return
        from src.ui.widgets import Dialog
        self.dialog = Dialog(
            title=tr("Nicht mehr veröffentlichen?"),
            message=tr('"{n}" wird aus dem Spiel entfernt, der Entwurf bleibt erhalten.').format(n=self.draft.name),
            buttons=[(tr("Entfernen"), "yes"), (tr("Abbrechen"), "cancel")]
        )
        self._pending_action = ("unpublish_track", self.draft.name)

    @staticmethod
    def _scan_backgrounds() -> list[str]:
        paths = sorted(glob.glob(os.path.join("data", "textures", "*.png")))
        return [os.path.splitext(os.path.basename(p))[0] for p in paths] or ["Plains"]

    def _center_camera(self) -> None:
        """Frame all pieces (or the pre-placed start)."""
        cells = self.draft.occupied_cells()
        if not cells:
            self._cam_x = self._cam_y = 5.5 * CELL
            self._zoom = 0.22
            return
        cols = [c for c, _ in cells]
        rows = [r for _, r in cells]
        self._cam_x = (min(cols) + max(cols) + 1) / 2 * CELL
        self._cam_y = (min(rows) + max(rows) + 1) / 2 * CELL

    # ==================================================================
    # Coordinate transforms
    # ==================================================================
    @property
    def _grid_rect(self) -> pygame.Rect:
        return pygame.Rect(PALETTE_W, TOP_H,
                           SCREEN_WIDTH - PALETTE_W - RIGHT_W, SCREEN_HEIGHT - TOP_H - BOTTOM_H)

    def _w2s(self, wx: float, wy: float) -> tuple[int, int]:
        gr = self._grid_rect
        return (int(gr.centerx + (wx - self._cam_x) * self._zoom),
                int(gr.centery - (wy - self._cam_y) * self._zoom))

    def _s2w(self, sx: float, sy: float) -> tuple[float, float]:
        gr = self._grid_rect
        return (self._cam_x + (sx - gr.centerx) / self._zoom,
                self._cam_y - (sy - gr.centery) / self._zoom)

    def _snap_cell(self, sx: float, sy: float) -> tuple[int, int]:
        wx, wy = self._s2w(sx, sy)
        return (math.floor(wx / CELL), math.floor(wy / CELL))

    # ==================================================================
    # Undo / redo
    # ==================================================================
    def _snapshot(self) -> tuple[list[Piece], int]:
        import copy
        return ([copy.copy(p) for p in self.draft.pieces], self.draft.start_piece_idx)

    def _push_undo(self) -> None:
        self._undo.append(self._snapshot())
        if len(self._undo) > 100:
            self._undo.pop(0)
        self._redo.clear()
        self._dirty = True
        self._geo_dirty = True

    def _undo_action(self) -> None:
        if not self._undo:
            return
        self._redo.append(self._snapshot())
        pieces, sidx = self._undo.pop()
        self.draft.pieces = pieces
        self.draft.start_piece_idx = sidx
        self._dirty = True
        self._geo_dirty = True

    def _redo_action(self) -> None:
        if not self._redo:
            return
        self._undo.append(self._snapshot())
        pieces, sidx = self._redo.pop()
        self.draft.pieces = pieces
        self.draft.start_piece_idx = sidx
        self._dirty = True
        self._geo_dirty = True

    # ==================================================================
    # Palette layout / hit test
    # ==================================================================
    def _palette_items(self) -> list[dict]:
        return [
            {"kind": "straight", "radius": 1, "label": "Gerade"},
            {"kind": "curve", "radius": 1, "label": "Kurve R1"},
            {"kind": "curve", "radius": 2, "label": "Kurve R2"},
            {"kind": "curve", "radius": 3, "label": "Kurve R3"},
        ]

    def _palette_layout(self) -> list[tuple[pygame.Rect, dict]]:
        items = self._palette_items()
        out = []
        x, y = 20, TOP_H + 20
        w, h = PALETTE_W - 40, 110
        for it in items:
            out.append((pygame.Rect(x, y, w, h), it))
            y += h + 14
        return out

    # ==================================================================
    # Events
    # ==================================================================
    @property
    def raw_gamepad(self) -> bool:
        """Edit mode reads the pad directly (cursor + buttons); the browser,
        dialogs and the focused props panel use the normal menu translation."""
        return (self._mode == "edit" and not self._dirty_prompt
                and self.dialog is None and getattr(self, "osk", None) is None
                and not getattr(self, "_props_focused", False))

    def handle_events(self, events: list[pygame.event.Event]) -> None:
        for e in events:
            if self.osk:
                if self.osk.handle_event(e):
                    self.osk = None
                continue
            if self.dialog:
                res = self.dialog.handle_event(e)
                if res == "yes":
                    action = self._pending_action
                    self.dialog = None
                    self._pending_action = None
                    if isinstance(action, tuple):
                        kind = action[0]
                        from src.track import tile_track
                        if kind == "delete_track":
                            name = action[1]
                            # Nur bei tatsaechlichem Loeschen Erfolg melden
                            # (08.08.2026): frueher meldete das Spiel Loeschen,
                            # obwohl der geratene Pfad die Datei verfehlte, und
                            # der Nutzer stand vor einer Strecke, die angeblich
                            # weg war.
                            if tile_track.delete_track(name):
                                self._show_toast(tr("Gelöscht: {name}").format(name=name))
                                self._dirty = False
                                self._exit_edit()
                            else:
                                self._show_toast(tr("Löschen fehlgeschlagen: {name}").format(name=name))
                            return
                        elif kind == "unpublish_track":
                            name = action[1]
                            tile_track.unpublish_track(name)
                            self._show_toast(tr("Nicht mehr veröffentlicht: {name}").format(name=name))
                        self._projects = self._scan_projects()
                    elif action == "save":
                        self._do_save_draft(force=True)
                    elif action == "publish":
                        self._do_publish(force=True)
                elif res == "copy":
                    if isinstance(self._pending_action, tuple) and self._pending_action[0] == "edit_published":
                        _, old_name, next_act = self._pending_action
                        self.dialog = None
                        self._pending_action = None
                        self.draft.name = self.draft.name + " Kopie"
                        self._do_save_draft(force=True)
                        if next_act == "publish":
                            self._do_publish(force=True)
                elif res == "unpublish_save":
                    if isinstance(self._pending_action, tuple) and self._pending_action[0] == "edit_published":
                        _, old_name, next_act = self._pending_action
                        self.dialog = None
                        self._pending_action = None
                        from src.track import tile_track
                        tile_track.unpublish_track(old_name)
                        self._do_save_draft(force=True)
                        if next_act == "publish":
                            self._do_publish(force=True)
                elif res in ("cancel", "no"):
                    self.dialog = None
                    self._pending_action = None
                continue
            if self._dirty_prompt:
                self._handle_dirty_event(e)
                continue
            if self._mode == "browse":
                self._handle_browse_event(e)
                continue
            if getattr(self, "_props_focused", False):
                self._handle_props_event(e)
                # Let mouse and gamepad events fall through for canvas clicks/movement
                if e.type not in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEMOTION, pygame.JOYBUTTONDOWN, pygame.JOYHATMOTION):
                    continue

            if e.type == pygame.MOUSEBUTTONDOWN:
                self._process_mouse_down(e)
                continue

            if e.type == pygame.JOYBUTTONDOWN:
                self._handle_joybutton(e)
            elif e.type == pygame.JOYHATMOTION:
                self._handle_joyhat(e)
            elif e.type == pygame.KEYDOWN:
                self._handle_keydown(e)
            elif e.type == pygame.MOUSEBUTTONUP:
                self._handle_mouseup(e)
            elif e.type == pygame.MOUSEWHEEL:
                self._handle_wheel(e)

    def _process_mouse_down(self, e: pygame.event.Event) -> None:
        """Route a (real or gamepad-synthesized) mouse-down click: right-panel
        clicks trigger props actions, everything else goes to the canvas/palette
        handler in `_handle_mousedown`."""
        if e.pos[0] >= 1500:
            # Focus and trigger click action in the right panel
            rects = self._props_layout_rects()
            for idx, r in enumerate(rects):
                if r.collidepoint(e.pos):
                    self._props_focused = True
                    self._props_field = idx
                    self._trigger_props_click(idx, e.pos)
                    break
            return
        # Clicked outside the right panel, lose focus
        self._props_focused = False
        self._handle_mousedown(e)

    def _get_cursor_pos(self) -> tuple[float, float]:
        if gamepad.device_count() > 0 and gamepad.using_pad():
            return self._gp_cursor[0], self._gp_cursor[1]
        from src.core import display
        return display.mouse_pos()

    def _cycle_palette(self, d: int) -> None:
        palette_items = [
            {"kind": "straight", "radius": 0},
            {"kind": "curve", "radius": 1},
            {"kind": "curve", "radius": 2},
            {"kind": "curve", "radius": 3},
        ]
        if self._tool is None:
            idx = 0 if d > 0 else len(palette_items) - 1
        else:
            idx = 0
            for i, it in enumerate(palette_items):
                if it["kind"] == self._tool["kind"] and it["radius"] == self._tool["radius"]:
                    idx = i
                    break
            idx = (idx + d) % len(palette_items)
        self._tool = {"kind": palette_items[idx]["kind"], 
                      "radius": palette_items[idx]["radius"], 
                      "rotation": self._tool["rotation"] if self._tool else 0}

    def _handle_joybutton(self, e: pygame.event.Event) -> None:
        btn = e.button
        cx, cy = self._get_cursor_pos()
        if btn == gamepad.BTN_A:
            if cx < PALETTE_W or cx >= 1500:
                # Palette / right-panel: behave exactly like a real mouse click.
                fake = pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(int(cx), int(cy)), button=1)
                self._process_mouse_down(fake)
            elif self._tool is not None:
                self._try_place(cx, cy)
            else:
                if self._moving_idx is not None:
                    self._drop_moving(cx, cy)
                else:
                    idx = self._piece_at_screen(cx, cy)
                    if idx is not None:
                        self._push_undo()
                        self._moving_idx = idx
        elif btn == gamepad.BTN_B:
            if self._tool is not None:
                self._tool = None
            elif self._moving_idx is not None:
                self._undo_action()
                self._moving_idx = None
        elif btn == gamepad.BTN_X:
            idx = self._piece_at_screen(cx, cy)
            if idx is not None:
                self._push_undo()
                self._delete_piece(idx)
        elif btn == gamepad.BTN_Y:
            if self._tool is not None:
                self._tool["rotation"] = (self._tool["rotation"] + 1) % 4
        elif btn == gamepad.BTN_LB:
            self._cycle_palette(-1)
        elif btn == gamepad.BTN_RB:
            self._cycle_palette(1)
        elif btn == gamepad.BTN_START:
            self._props_focused = not getattr(self, "_props_focused", False)
            self._props_field = 0
        elif btn == gamepad.BTN_LS:
            self._undo_action()
        elif btn == gamepad.BTN_RS:
            self._redo_action()

    def _handle_joyhat(self, e: pygame.event.Event) -> None:
        hx, hy = e.value
        if hx == -1:
            self._undo_action()
        elif hx == 1:
            self._redo_action()
        if hy == 1:
            if self._tool is not None and self._tool["kind"] == "curve":
                self._tool["radius"] = min(3, self._tool["radius"] + 1)
        elif hy == -1:
            if self._tool is not None and self._tool["kind"] == "curve":
                self._tool["radius"] = max(1, self._tool["radius"] - 1)

    def _handle_browse_event(self, e: pygame.event.Event) -> None:
        if (e.type == pygame.MOUSEBUTTONDOWN and e.button == 1
                and self._zurueck_knopf.hit(e.pos)):
            from src.core import sfx as _sfx
            vorher = _sfx.klang_zaehler()
            self._browse_zurueck()
            _sfx.klick_quittieren(e, vorher)
            return
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                self._browse_zurueck()
            elif e.key == pygame.K_PAGEUP:
                self.state_machine.transition("menu", tab_idx=2)
                return
            elif e.key == pygame.K_PAGEDOWN:
                self.state_machine.transition("menu", tab_idx=4)
                return
            elif e.key in (pygame.K_UP, pygame.K_w):
                self._browse_idx = (self._browse_idx - 1) % len(self._projects)
                self._browse_ensure_visible()
            elif e.key in (pygame.K_DOWN, pygame.K_s):
                self._browse_idx = (self._browse_idx + 1) % len(self._projects)
                self._browse_ensure_visible()
            elif e.key == pygame.K_RETURN:
                self._open_project(self._projects[self._browse_idx])
        elif e.type == pygame.MOUSEWHEEL:
            max_scroll = max(0, len(self._projects) - self._BROWSE_VISIBLE)
            self._browse_scroll = max(0, min(max_scroll, self._browse_scroll - e.y))
        elif e.type == pygame.MOUSEMOTION:
            for i, rect in self._browse_layout():
                if rect.collidepoint(e.pos):
                    self._browse_idx = i
                    break
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            from src.core import sfx as _sfx
            from src.states.menu_shell_state import TAB_EDITOR
            for i, rect in enumerate(self._tab_rects()):
                if rect.collidepoint(e.pos):
                    vorher = _sfx.klang_zaehler()
                    if i != TAB_EDITOR:
                        self.state_machine.transition("menu", tab_idx=i)
                    _sfx.klick_quittieren(e, vorher)
                    return
            for i, rect in self._browse_layout():
                if rect.collidepoint(e.pos):
                    self._browse_idx = i
                    vorher = _sfx.klang_zaehler()
                    self._open_project(self._projects[i])
                    _sfx.klick_quittieren(e, vorher)
                    return

    def _handle_dirty_event(self, e: pygame.event.Event) -> None:
        if e.type == pygame.MOUSEMOTION:
            for i, (rect, _, _, _) in enumerate(self._dirty_button_rects()):
                if rect.collidepoint(e.pos):
                    self._dirty_focus = i
            return
            
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            from src.core import sfx as _sfx
            for i, (rect, _, _, _) in enumerate(self._dirty_button_rects()):
                if rect.collidepoint(e.pos):
                    vorher = _sfx.klang_zaehler()
                    self._dirty_execute(i)
                    _sfx.klick_quittieren(e, vorher)
                    return
            return

        if e.type == pygame.KEYDOWN:
            focus = getattr(self, "_dirty_focus", 0)
            if e.key == pygame.K_LEFT:
                self._dirty_focus = (focus - 1) % 3
            elif e.key == pygame.K_RIGHT:
                self._dirty_focus = (focus + 1) % 3
            elif e.key == pygame.K_RETURN:
                self._dirty_execute(focus)
            elif e.key == pygame.K_ESCAPE:
                self._dirty_execute(2)

        if e.type == pygame.JOYBUTTONDOWN:
            focus = getattr(self, "_dirty_focus", 0)
            if e.dict.get("button") == gamepad.BTN_A:
                self._dirty_execute(focus)
            elif e.dict.get("button") == gamepad.BTN_B:
                self._dirty_execute(2)

        if e.type == pygame.JOYHATMOTION:
            focus = getattr(self, "_dirty_focus", 0)
            hx, hy = e.value
            if hx < 0:
                self._dirty_focus = (focus - 1) % 3
            elif hx > 0:
                self._dirty_focus = (focus + 1) % 3

    def _dirty_execute(self, action: int) -> None:
        # Speichern und Verwerfen beenden das Bearbeiten, nicht den Editor:
        # zurueck geht es in die Projektliste, eine Ebene hoch. Vorher sprangen
        # beide ins Hauptmenue, obwohl der Weg dorthin ueber die Liste fuehrt
        # (gemeldet 02.08.2026).
        if action == 0: # Speichern
            self.draft.save_draft()
            self._dirty = False
            self._dirty_prompt = False
            self._exit_edit()
        elif action == 1: # Verwerfen
            self._dirty = False
            self._dirty_prompt = False
            self._exit_edit()
        elif action == 2: # Abbrechen
            self._dirty_prompt = False

    def _handle_keydown(self, e: pygame.event.Event) -> None:
        mods = pygame.key.get_mods()
        if e.key == pygame.K_ESCAPE:
            if self._tool is not None:
                self._tool = None
            elif self._dirty:
                self._dirty_prompt = True         # Ungespeichert — J/N/Abbrechen
            else:
                self._exit_edit()
        elif e.key == pygame.K_r and self._tool is not None:
            self._tool["rotation"] = (self._tool["rotation"] + 1) % 4
        elif e.key == pygame.K_TAB:
            self._props_focused = True
            self._props_field = 0
        elif e.key == pygame.K_z and (mods & pygame.KMOD_CTRL):
            self._undo_action()
        elif e.key == pygame.K_y and (mods & pygame.KMOD_CTRL):
            self._redo_action()

    def _handle_mousedown(self, e: pygame.event.Event) -> None:
        sx, sy = e.pos
        # Palette region
        if sx < PALETTE_W:
            if e.button == 1:
                for rect, it in self._palette_layout():
                    if rect.collidepoint(sx, sy):
                        self._tool = {"kind": it["kind"], "radius": it["radius"],
                                      "rotation": 0}
                        return
            return

        # Grid region
        if e.button == 2:                       # middle → pan
            self._panning = True
            self._pan_last = (sx, sy)
            return

        if e.button == 3:                       # right-click
            if self._tool is not None:
                self._tool = None
                return
            idx = self._piece_at_screen(sx, sy)
            if idx is not None:
                self._push_undo()
                self._delete_piece(idx)
            return

        if e.button == 1:                       # left-click
            if self._tool is not None:
                self._try_place(sx, sy)
            else:
                idx = self._piece_at_screen(sx, sy)
                if idx is not None:
                    self._push_undo()
                    self._moving_idx = idx

    def _handle_mouseup(self, e: pygame.event.Event) -> None:
        if e.button == 2:
            self._panning = False
        elif e.button == 1 and self._moving_idx is not None:
            self._drop_moving(*e.pos)

    def _handle_wheel(self, e: pygame.event.Event) -> None:
        # Wheel over a curve ghost changes radius; otherwise zoom.
        if self._tool is not None and self._tool["kind"] == "curve":
            self._tool["radius"] = max(1, min(3, self._tool["radius"] + (1 if e.y > 0 else -1)))
            return
        mx, my = self._get_cursor_pos()
        wx, wy = self._s2w(mx, my)
        self._zoom = max(0.06, min(0.8, self._zoom * (1.15 if e.y > 0 else 1 / 1.15)))
        # Re-anchor so the point under the cursor stays fixed.
        gr = self._grid_rect
        self._cam_x = wx - (mx - gr.centerx) / self._zoom
        self._cam_y = wy + (my - gr.centery) / self._zoom

    # ==================================================================
    # Placement logic
    # ==================================================================
    def _ghost_piece(self, sx: float, sy: float, kind: str, radius: int,
                     rotation: int) -> Piece:
        col, row = self._snap_cell(sx, sy)
        return Piece(kind=kind, col=col, row=row, rotation=rotation,
                     radius_cells=radius)

    def _is_valid(self, ghost: Piece, ignore_idx: int | None = None) -> bool:
        occupied: set[tuple[int, int]] = set()
        for i, p in enumerate(self.draft.pieces):
            if i == ignore_idx:
                continue
            occupied |= p.occupies()
        return not (ghost.occupies() & occupied)

    def _try_place(self, sx: float, sy: float) -> None:
        ghost = self._ghost_piece(sx, sy, self._tool["kind"], self._tool["radius"],
                                  self._tool["rotation"])
        if self._is_valid(ghost):
            self._push_undo()
            self.draft.pieces.append(ghost)

    def _drop_moving(self, sx: float, sy: float) -> None:
        idx = self._moving_idx
        self._moving_idx = None
        if idx is None:
            return
        orig = self.draft.pieces[idx]
        col, row = self._snap_cell(sx, sy)
        moved = Piece(kind=orig.kind, col=col, row=row, rotation=orig.rotation,
                      radius_cells=orig.radius_cells)
        if self._is_valid(moved, ignore_idx=idx):
            self.draft.pieces[idx] = moved
        else:
            # invalid drop → undo the snapshot we took on pickup
            self._undo_action()
            self._redo.clear()

    def _delete_piece(self, idx: int) -> None:
        del self.draft.pieces[idx]
        # keep start_piece_idx valid
        if self.draft.start_piece_idx >= len(self.draft.pieces):
            self.draft.start_piece_idx = 0
        elif idx < self.draft.start_piece_idx:
            self.draft.start_piece_idx -= 1

    def _piece_at_screen(self, sx: float, sy: float) -> int | None:
        col, row = self._snap_cell(sx, sy)
        return self.draft.piece_at(col, row)

    # ==================================================================
    # Publish / Save with Ghost Warning
    # ==================================================================
    def _check_ghost_warning(self, action: str) -> bool:
        """Check if a ghost exists for this track. If so, show a confirmation dialog.

        Returns True if no warning is needed and we can proceed immediately.
        Returns False if a warning dialog was shown.
        """
        from src.track.tile_track import _slugify
        from src.core import ghost

        slug = _slugify(self.draft.name)
        track_key = f"custom/{slug}"
        if ghost.exists(track_key):
            from src.ui.widgets import Dialog
            self._pending_action = action
            self.dialog = Dialog(
                title=tr("Ghost löschen?"),
                message=tr("Bestzeit (Ghost) existiert. Speichern löscht diesen!"),
                buttons=[(tr("Speichern"), "yes"), (tr("Abbrechen"), "cancel")]
            )
            return False
        return True

    def _do_save_draft(self, force: bool = False, next_action: str = "save") -> None:
        if not force and self.draft and self.draft.is_published and self._dirty:
            from src.ui.widgets import Dialog
            self.dialog = Dialog(
                title=tr("Veröffentlichte Strecke bearbeitet"),
                message=tr('"{n}" ist bereits veröffentlicht. Wie möchtest du die Änderungen verarbeiten?').format(n=self.draft.name),
                buttons=[
                    (tr("Als Kopie speichern"), "copy"),
                    (tr("Unveröffentlichen & Speichern"), "unpublish_save"),
                    (tr("Abbrechen"), "cancel"),
                ]
            )
            self._pending_action = ("edit_published", self.draft.name, next_action)
            return

        if not force and not self._check_ghost_warning("save"):
            return

        from src.track.tile_track import _slugify
        from src.core import ghost
        slug = _slugify(self.draft.name)
        track_key = f"custom/{slug}"
        ghost.delete(track_key)

        self.draft.save_draft()
        self._dirty = False
        from src.core import statistik
        statistik.strecke_erstellt()
        self._show_toast(tr("Entwurf gespeichert: {name}").format(name=self.draft.name))

    def _do_publish(self, force: bool = False) -> None:
        # Der Name wird hier zum ersten Mal oeffentlich: eine veroeffentlichte
        # Strecke reist im Online-Rennen automatisch zu allen Mitspielern.
        # Bis zum 07.08.2026 wurde er nur auf unbedenkliche *Zeichen* geprueft
        # (gegen Pfadangriffe), nie auf seinen Inhalt — damit war der
        # Streckenname der einzige Text, den ein Spieler Fremden ungefiltert
        # vorsetzen konnte. Der Entwurf bleibt davon unberuehrt: solange nichts
        # das Geraet verlaesst, geht der Name niemanden etwas an.
        from src.core import profile
        ok, grund = profile.validate_track_name(self.draft.name)
        if not ok:
            self._show_toast(tr("Name nicht erlaubt: {grund}").format(grund=grund))
            return

        if self._dirty:
            self._do_save_draft(force=force, next_action="publish")
            if self._dirty:  # Pending dialog opened or save cancelled
                return

        if not force and not self._check_ghost_warning("publish"):
            return

        from src.track.tile_track import _slugify
        from src.core import ghost
        slug = _slugify(self.draft.name)
        track_key = f"custom/{slug}"

        path, errs = self.draft.publish()
        if errs:
            self._show_toast(tr("Nicht bereit: {msg}").format(msg=errs[0].message))
        else:
            ghost.delete(track_key)
            self._dirty = False
            from src.core import statistik
            statistik.strecke_veroeffentlicht()
            import os
            _ONLINE_MAX_B = 1024 * 1024
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            if size > _ONLINE_MAX_B:
                self._show_toast(
                    tr("Veröffentlicht: {name} — ACHTUNG: {size:.1f} MB > 1 MB, nicht online spielbar!").format(
                        name=self.draft.name, size=size / 1024 / 1024
                    )
                )
            else:
                self._show_toast(tr("Veröffentlicht: {name} — im Menü wählbar!").format(name=self.draft.name))

    def _publish(self) -> None:
        self._do_publish()

    # ==================================================================
    # Properties overlay events
    # ==================================================================
    def _trigger_props_step(self, idx: int, d: int) -> None:
        if idx == 1: # Width
            self._dirty = True
            self._geo_dirty = True
            self.draft.width = max(250.0, min(300.0, self.draft.width + d * 5))
        elif idx == 2: # Background
            self._dirty = True
            self._geo_dirty = True
            bg_list = self._backgrounds
            if bg_list:
                cur_idx = bg_list.index(self.draft.background_texture) if self.draft.background_texture in bg_list else 0
                next_idx = (cur_idx + d) % len(bg_list)
                self.draft.background_texture = bg_list[next_idx]
        elif idx == 3: # Difficulty
            self._dirty = True
            self._geo_dirty = True
            cur_idx = _DIFFICULTIES.index(self.draft.difficulty) if self.draft.difficulty in _DIFFICULTIES else 0
            next_idx = (cur_idx + d) % len(_DIFFICULTIES)
            self.draft.difficulty = _DIFFICULTIES[next_idx]

    def _handle_props_event(self, e: pygame.event.Event) -> None:
        if e.type == pygame.MOUSEMOTION:
            rects = self._props_layout_rects()
            for idx, r in enumerate(rects):
                if r.collidepoint(e.pos):
                    self._props_field = idx
            return

        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            return

        if e.type == pygame.JOYBUTTONDOWN:
            if e.button == gamepad.BTN_B:
                self._props_focused = False
                return
            return

        if e.type != pygame.KEYDOWN:
            return

        if e.key in (pygame.K_TAB, pygame.K_ESCAPE):
            self._props_focused = False
            return

        if self._props_field == 0:              # name text input
            if e.key == pygame.K_RETURN and gamepad.using_pad():
                self.osk = OnScreenKeyboard(DraftNameWrapper(self))
                return
            self._dirty = True
            if e.key == pygame.K_BACKSPACE:
                self.draft.name = self.draft.name[:-1]
            elif e.unicode and e.unicode.isprintable() and len(self.draft.name) < 28:
                self.draft.name += e.unicode
        elif e.key == pygame.K_RETURN:
            if self._props_field == 4:
                self._do_save_draft()
            elif self._props_field == 5:
                if self.draft and self.draft.is_published:
                    self._editor_confirm_unpublish()
                else:
                    self._do_publish()
            elif self._props_field == 6:
                if self._dirty:
                    self._dirty_prompt = True
                else:
                    self._exit_edit()
            elif self._props_field == 7:
                self._editor_confirm_delete()

    # ==================================================================
    # Update
    # ==================================================================
    def update(self, dt: float) -> None:
        self._time += dt
        if self._toast_t > 0:
            self._toast_t -= dt

        if self._mode == "browse" and getattr(self, "_video", None) is not None:
            self._video.update(dt)

        if self._mode == "edit" and self._geo_dirty:
            self._refresh_status()

        if self._mode != "edit" or self._dirty_prompt:
            return

        # Middle-drag pan
        if self._panning:
            from src.core import display
            mx, my = display.mouse_pos()
            dx = mx - self._pan_last[0]
            dy = my - self._pan_last[1]
            self._pan_last = (mx, my)
            self._cam_x -= dx / self._zoom
            self._cam_y += dy / self._zoom

        # Arrow-key pan (when properties panel is not focused)
        if not getattr(self, "_props_focused", False):
            keys = pygame.key.get_pressed()
            pan = 600 * dt / self._zoom
            if keys[pygame.K_LEFT]:
                self._cam_x -= pan
            if keys[pygame.K_RIGHT]:
                self._cam_x += pan
            if keys[pygame.K_UP]:
                self._cam_y += pan
            if keys[pygame.K_DOWN]:
                self._cam_y -= pan

        # Gamepad-specific cursor movement, panning, and zoom
        if gamepad.device_count() > 0:
            lx, ly = gamepad.get_stick_axes(0)
            self._gp_cursor[0] += lx * 700 * dt
            self._gp_cursor[1] += ly * 700 * dt
            self._gp_cursor[0] = max(0.0, min(float(SCREEN_WIDTH), self._gp_cursor[0]))
            self._gp_cursor[1] = max(0.0, min(float(SCREEN_HEIGHT), self._gp_cursor[1]))

            rx, ry = gamepad.get_right_stick_axes(0)
            self._cam_x += rx * 800 * dt / self._zoom
            self._cam_y -= ry * 800 * dt / self._zoom

            lt = gamepad.get_trigger_axis(0, is_left=True)
            rt = gamepad.get_trigger_axis(0, is_left=False)
            if lt > 0.1:
                self._zoom = max(0.06, self._zoom / (1.0 + lt * 1.5 * dt))
            if rt > 0.1:
                self._zoom = min(0.8, self._zoom * (1.0 + rt * 1.5 * dt))

    def _show_toast(self, text: str) -> None:
        self._toast = text
        self._toast_t = 4.0

    # ==================================================================
    # Render
    # ==================================================================
    def render(self, screen: pygame.Surface) -> None:
        if self._mode == "browse":
            self._draw_browser(screen)
            self._draw_toast(screen)
            return

        screen.fill(_BG)
        gr = self._grid_rect

        screen.set_clip(gr)
        self._draw_grid(screen)
        self._draw_pieces(screen)
        self._draw_start_marker(screen)
        self._draw_open_ports(screen)
        self._draw_ghost(screen)
        screen.set_clip(None)

        self._draw_palette(screen)
        self._draw_status_bar(screen)
        self._draw_right_panel(screen)
        self._draw_toast(screen)

        if gamepad.device_count() > 0 and gamepad.using_pad():
            self._draw_gp_cursor(screen)

        if self.osk:
            self.osk.draw(screen)
        if self._dirty_prompt:
            self._draw_dirty_prompt(screen)
        if self.dialog:
            self.dialog.draw(screen)

    def _draw_grid(self, screen: pygame.Surface) -> None:
        gr = self._grid_rect
        # visible world bounds
        wx0, wy1 = self._s2w(gr.left, gr.top)
        wx1, wy0 = self._s2w(gr.right, gr.bottom)
        c0 = math.floor(wx0 / CELL) - 1
        c1 = math.ceil(wx1 / CELL) + 1
        r0 = math.floor(wy0 / CELL) - 1
        r1 = math.ceil(wy1 / CELL) + 1
        # Don't draw an insane number of lines when zoomed far out.
        if (c1 - c0) < 200 and (r1 - r0) < 200:
            for c in range(c0, c1 + 1):
                sx, _ = self._w2s(c * CELL, 0)
                col = _GRID_LINE_MAJOR if c % 5 == 0 else _GRID_LINE
                pygame.draw.line(screen, col, (sx, gr.top), (sx, gr.bottom), 1)
            for r in range(r0, r1 + 1):
                _, sy = self._w2s(0, r * CELL)
                col = _GRID_LINE_MAJOR if r % 5 == 0 else _GRID_LINE
                pygame.draw.line(screen, col, (gr.left, sy), (gr.right, sy), 1)

    def _piece_polyline(self, piece: Piece) -> list[tuple[float, float]]:
        p0 = piece.ports()[0]
        return [(p0.wx, p0.wy)] + piece.centerline_points(p0)

    def _draw_pieces(self, screen: pygame.Surface) -> None:
        mx, my = self._get_cursor_pos()
        hovered_idx = self._piece_at_screen(mx, my)

        w = max(3, int(self.draft.width * self._zoom))
        for i, piece in enumerate(self.draft.pieces):
            if i == self._moving_idx:
                continue
            pts = [self._w2s(x, y) for x, y in self._piece_polyline(piece)]
            
            # Highlight hovered piece
            if i == hovered_idx:
                # Draw outer glow/border and lighter asphalt
                self._draw_road(screen, pts, w + 4, COLOR_UI_ACCENT)
                self._draw_road(screen, pts, w, (100, 102, 112))
            else:
                self._draw_road(screen, pts, w, _ASPHALT)

            # dashed centreline
            for j in range(0, len(pts) - 1, 2):
                pygame.draw.line(screen, _CENTERLINE, pts[j], pts[j + 1], 1)

    def _draw_road(self, screen, pts, w, color) -> None:
        if len(pts) < 2:
            return
        pygame.draw.lines(screen, color, False, pts, w)
        # Round the joints so curves don't show gaps.
        r = w // 2
        for p in pts:
            pygame.draw.circle(screen, color, p, r)

    def _draw_start_marker(self, screen: pygame.Surface) -> None:
        if not self.draft.pieces:
            return
        sp = self.draft.pieces[self.draft.start_piece_idx % len(self.draft.pieces)]
        p0, p1 = sp.ports()
        # tangent (into the piece) and perpendicular
        tx, ty = p1.wx - p0.wx, p1.wy - p0.wy
        tlen = math.hypot(tx, ty) or 1.0
        tx, ty = tx / tlen, ty / tlen
        px, py = -ty, tx
        half = self.draft.width / 2
        n = 6
        for k in range(n):
            f0 = -half + (2 * half) * k / n
            f1 = -half + (2 * half) * (k + 1) / n
            a = self._w2s(p0.wx + px * f0, p0.wy + py * f0)
            b = self._w2s(p0.wx + px * f1, p0.wy + py * f1)
            c = (240, 240, 240) if k % 2 == 0 else (20, 20, 20)
            pygame.draw.line(screen, c, a, b, max(3, int(0.35 * CELL * self._zoom)))

    def _draw_open_ports(self, screen: pygame.Surface) -> None:
        pulse = 0.5 + 0.5 * math.sin(self._time * 5.0)
        rad = int(6 + 5 * pulse)
        for port in self._open_ports_cache:
            s = self._w2s(port.wx, port.wy)
            pygame.draw.circle(screen, _OPEN_PORT, s, rad, 2)
            # small arrow along the outward face
            ang = math.radians(port.face_dir)
            dx, dy = math.cos(ang), math.sin(ang)
            tip = (int(s[0] + dx * 22), int(s[1] - dy * 22))
            pygame.draw.line(screen, _OPEN_PORT, s, tip, 2)

    def _draw_ghost(self, screen: pygame.Surface) -> None:
        mx, my = self._get_cursor_pos()
        gr = self._grid_rect

        if self._moving_idx is not None:
            orig = self.draft.pieces[self._moving_idx]
            col, row = self._snap_cell(mx, my)
            ghost = Piece(orig.kind, col, row, orig.rotation, orig.radius_cells)
            valid = self._is_valid(ghost, ignore_idx=self._moving_idx)
            self._draw_ghost_piece(screen, ghost, valid)
            return

        if self._tool is None or not gr.collidepoint(mx, my):
            return
        ghost = self._ghost_piece(mx, my, self._tool["kind"], self._tool["radius"],
                                  self._tool["rotation"])
        valid = self._is_valid(ghost)
        self._draw_ghost_piece(screen, ghost, valid)

    def _draw_ghost_piece(self, screen, ghost: Piece, valid: bool) -> None:
        color = _GHOST_OK if valid else _GHOST_BAD
        # footprint cells
        for (c, r) in ghost.occupies():
            a = self._w2s(c * CELL, (r + 1) * CELL)
            b = self._w2s((c + 1) * CELL, r * CELL)
            rect = pygame.Rect(a[0], a[1], b[0] - a[0], b[1] - a[1])
            pygame.draw.rect(screen, color, rect, 2)
        # ghost road
        pts = [self._w2s(x, y) for x, y in self._piece_polyline(ghost)]
        w = max(3, int(self.draft.width * self._zoom))
        self._draw_road(screen, pts, w, color)

    # -- Palette --------------------------------------------------------
    def _draw_palette(self, screen: pygame.Surface) -> None:
        panel = pygame.Rect(0, 0, PALETTE_W, SCREEN_HEIGHT)
        pygame.draw.rect(screen, _PANEL, panel)
        pygame.draw.line(screen, _PANEL_BORDER, (PALETTE_W, 0), (PALETTE_W, SCREEN_HEIGHT), 2)

        title = self.f_body.render(tr("BAUTEILE"), True, COLOR_UI_ACCENT)
        screen.blit(title, (20, 24))

        for rect, it in self._palette_layout():
            selected = (self._tool is not None
                        and self._tool["kind"] == it["kind"]
                        and self._tool["radius"] == it["radius"])
            from src.core import display
            hover = rect.collidepoint(display.mouse_pos())
            
            if selected:
                bg = (48, 42, 20)
                border = COLOR_UI_ACCENT
            elif hover:
                bg = (45, 48, 58)
                border = (120, 125, 145)
            else:
                bg = (30, 33, 42)
                border = (60, 64, 80)
                
            pygame.draw.rect(screen, bg, rect, border_radius=6)
            pygame.draw.rect(screen, border, rect, 2, border_radius=6)

            # thumbnail
            self._draw_thumbnail(screen, rect, it)
            lbl = self.f_small.render(tr(it["label"]), True, COLOR_UI_TEXT)
            screen.blit(lbl, (rect.x + 12, rect.bottom - 30))

    def _draw_thumbnail(self, screen, rect: pygame.Rect, it: dict) -> None:
        # Draw a small schematic of the piece inside the card's right half.
        cx = rect.right - 60
        cy = rect.centery - 6
        L = 40
        col = (120, 200, 255)
        if it["kind"] == "straight":
            pygame.draw.line(screen, col, (cx - L, cy), (cx + L, cy), 8)
        else:
            # quarter-arc schematic (bigger radius index → gentler curve)
            r = 26 + (it["radius"] - 1) * 8
            cxo, cyo = cx - r + 20, cy + r - 10
            pts = []
            for k in range(13):
                a = math.pi / 2 * k / 12
                pts.append((cxo + r * math.cos(a), cyo - r * math.sin(a)))
            if len(pts) >= 2:
                pygame.draw.lines(screen, col, False, [(int(x), int(y)) for x, y in pts], 8)

    # -- Status bar -----------------------------------------------------
    def _draw_status_bar(self, screen: pygame.Surface) -> None:
        bar = pygame.Rect(PALETTE_W, 0, SCREEN_WIDTH - PALETTE_W, TOP_H)
        pygame.draw.rect(screen, _PANEL, bar)
        pygame.draw.line(screen, _PANEL_BORDER, (PALETTE_W, TOP_H), (SCREEN_WIDTH, TOP_H), 2)

        name = self.f_body.render(self.draft.name, True, COLOR_UI_TEXT)
        screen.blit(name, (PALETTE_W + 24, (TOP_H - name.get_height()) // 2))

        # piece count on the right
        cnt = self.f_small.render(tr("{n} Teile").format(n=len(self.draft.pieces)), True, (150, 150, 165))
        screen.blit(cnt, (SCREEN_WIDTH - cnt.get_width() - 24, 24))

    # -- Help line ------------------------------------------------------


    def _draw_toast(self, screen: pygame.Surface) -> None:
        if self._toast_t <= 0 or not self._toast:
            return
        surf = self.f_body.render(self._toast, True, (255, 225, 130))
        pad = 14
        w = surf.get_width() + pad * 2
        h = surf.get_height() + pad
        x = (SCREEN_WIDTH + PALETTE_W) // 2 - w // 2
        y = SCREEN_HEIGHT - BOTTOM_H - h - 20
        box = pygame.Surface((w, h), pygame.SRCALPHA)
        box.fill((20, 20, 30, 230))
        screen.blit(box, (x, y))
        pygame.draw.rect(screen, COLOR_UI_ACCENT, (x, y, w, h), 2, border_radius=6)
        screen.blit(surf, (x + pad, y + pad // 2))

    # -- Sidebar properties layout & rendering --------------------------
    def _props_layout_rects(self) -> list[pygame.Rect]:
        x = 1520
        w = 380
        return [
            pygame.Rect(x, 415, w, 50), # 0: Name
            pygame.Rect(x, 475, w, 50), # 1: Width
            pygame.Rect(x, 535, w, 50), # 2: Background
            pygame.Rect(x, 595, w, 50), # 3: Difficulty
            pygame.Rect(x, 690, w, 50), # 4: Save
            pygame.Rect(x, 750, w, 50), # 5: Publish
            pygame.Rect(x, 810, w, 50), # 6: Cancel
            pygame.Rect(x, 1000, w, 50), # 7: Delete
        ]

    def _trigger_props_click(self, idx: int, pos: tuple[int, int]) -> None:
        if idx == 0:  # Name — controller users get the on-screen keyboard
            if gamepad.using_pad():
                self.osk = OnScreenKeyboard(DraftNameWrapper(self))
            return
        if idx in (1, 2, 3):
            r = self._props_layout_rects()[idx]
            btn_left = pygame.Rect(r.right - 84, r.y + 7, 36, 36)
            btn_right = pygame.Rect(r.right - 42, r.y + 7, 36, 36)
            if btn_left.collidepoint(pos):
                self._trigger_props_step(idx, -1)
            elif btn_right.collidepoint(pos):
                self._trigger_props_step(idx, 1)
            elif pos[0] > 0 and pos[0] < r.x + r.width // 2:
                self._trigger_props_step(idx, -1)
            else:
                self._trigger_props_step(idx, 1)
        elif idx == 4: # Save
            self._do_save_draft()
        elif idx == 5: # Publish/Unpublish
            if self.draft and self.draft.is_published:
                self._editor_confirm_unpublish()
            else:
                self._do_publish()
        elif idx == 6: # Cancel/Exit
            # Mit der Maus geklickt muss derselbe Knopf dasselbe tun wie mit
            # ENTER ausgeloest: eine Ebene hoch in die Projektliste. Vorher
            # sprang der Mausweg ins Hauptmenue (gemeldet 02.08.2026).
            if self._dirty:
                self._dirty_prompt = True
            else:
                self._exit_edit()
        elif idx == 7: # Delete
            self._editor_confirm_delete()

    def _draw_right_panel(self, screen: pygame.Surface) -> None:
        x_start = 1500
        w = 420
        # Draw background panel
        pygame.draw.rect(screen, _PANEL, (x_start, 0, w, SCREEN_HEIGHT))
        pygame.draw.line(screen, _PANEL_BORDER, (x_start, 0), (x_start, SCREEN_HEIGHT), 2)
        
        # --- 1. HELP / BEDIENHILFE ---
        theme.text(screen, tr("BEDIENHILFE"), theme.LABEL, COLOR_UI_ACCENT, (x_start + 20, 20))

        if gamepad.using_pad():
            rows = [
                (tr("Linker Stick"), tr("Cursor bewegen")),
                (tr("Rechter Stick"), tr("Kamera verschieben")),
                (tr("Trigger LT/RT"), tr("Kamera zoomen")),
                (tr("Taste A"), tr("wählen / platzieren / klicken")),
                (tr("Taste X"), tr("löschen")),
                (tr("Taste Y"), tr("Bauteil drehen")),
                (tr("D-Pad L/R"), tr("Undo / Redo")),
                (tr("D-Pad O/U"), tr("Kurvenradius ändern")),
                (tr("LB / RB"), tr("Teil wechseln")),
                (tr("Taste B"), tr("Werkzeug abbrechen")),
            ]
        else:
            rows = [
                (tr("Linksklick"), tr("platzieren / greifen / klicken")),
                (tr("Rechtsklick"), tr("löschen")),
                (tr("Mausrad"), tr("Zoom / Kurvenradius")),
                (tr("Pfeiltasten"), tr("Kamera verschieben")),
                (tr("R"), tr("Bauteil drehen")),
                (tr("Strg+Z / Y"), tr("Undo / Redo")),
                (tr("ESC"), tr("zurück ins Menü")),
            ]
            
        ry = 60
        for keys, desc in rows:
            screen.blit(self.f_small.render(keys, True, (230, 220, 160)), (x_start + 20, ry))
            screen.blit(self.f_small.render(desc, True, (185, 188, 200)), (x_start + 170, ry))
            ry += 24
            
        # Divider 1
        pygame.draw.line(screen, _PANEL_BORDER, (x_start, 350), (SCREEN_WIDTH, 350), 2)
        
        # --- 2. PROPERTIES / OPTIONS ---
        theme.text(screen, tr("EIGENSCHAFTEN"), theme.LABEL, COLOR_UI_ACCENT, (x_start + 20, 375))

        fields = [
            (tr("Name"), self.draft.name + ("_" if (getattr(self, "_props_focused", False) and self._props_field == 0) else "")),
            (tr("Breite"), f"‹ {int(self.draft.width)} px ›"),
            (tr("Hintergrund"), f"‹ {self.draft.background_texture} ›"),
            (tr("Schwierigkeit"), f"‹ {tr(self.draft.difficulty)} ›"),
        ]
        
        rects = self._props_layout_rects()
        mx, my = self._get_cursor_pos()
        
        # Draw fields 0-3
        for i in range(4):
            rect = rects[i]
            label, val_str = fields[i]
            is_active = (getattr(self, "_props_focused", False) and (self._props_field == i)) or rect.collidepoint(mx, my)
            
            # Draw row background
            bg_color = (48, 42, 20) if is_active else (26, 28, 36)
            pygame.draw.rect(screen, bg_color, rect, border_radius=6)
            pygame.draw.rect(screen, COLOR_UI_ACCENT if is_active else (56, 60, 76), rect, 2, border_radius=6)
            
            # Label
            screen.blit(self.f_small.render(label, True, (170, 174, 190)), (rect.x + 16, rect.y + 16))
            
            if i == 0:
                # Name text input
                val_surf = self.f_small.render(val_str, True, COLOR_UI_TEXT)
                screen.blit(val_surf, val_surf.get_rect(midright=(rect.right - 16, rect.centery)))
            else:
                # Fields 1, 2, 3: Width, Background, Difficulty with explicit sub-buttons
                raw_val = val_str.replace("‹ ", "").replace(" ›", "")
                val_surf = self.f_small.render(raw_val, True, COLOR_UI_TEXT)
                
                btn_left = pygame.Rect(rect.right - 84, rect.y + 7, 36, 36)
                btn_right = pygame.Rect(rect.right - 42, rect.y + 7, 36, 36)
                
                hover_left = btn_left.collidepoint(mx, my)
                hover_right = btn_right.collidepoint(mx, my)
                
                # Render value text between label and left button
                screen.blit(val_surf, val_surf.get_rect(midright=(btn_left.x - 12, rect.centery)))
                
                # Render left button `<`
                b_bg_l = (110, 90, 35) if hover_left else ((48, 42, 20) if is_active else (36, 40, 52))
                pygame.draw.rect(screen, b_bg_l, btn_left, border_radius=4)
                pygame.draw.rect(screen, COLOR_UI_ACCENT if hover_left else (70, 75, 95), btn_left, 1, border_radius=4)
                lbl_l = self.f_small.render("‹", True, COLOR_UI_ACCENT if hover_left else COLOR_UI_TEXT)
                screen.blit(lbl_l, lbl_l.get_rect(center=btn_left.center))
                
                # Render right button `>`
                b_bg_r = (110, 90, 35) if hover_right else ((48, 42, 20) if is_active else (36, 40, 52))
                pygame.draw.rect(screen, b_bg_r, btn_right, border_radius=4)
                pygame.draw.rect(screen, COLOR_UI_ACCENT if hover_right else (70, 75, 95), btn_right, 1, border_radius=4)
                lbl_r = self.f_small.render("›", True, COLOR_UI_ACCENT if hover_right else COLOR_UI_TEXT)
                screen.blit(lbl_r, lbl_r.get_rect(center=btn_right.center))
            
        # Divider 2
        pygame.draw.line(screen, _PANEL_BORDER, (x_start, 670), (SCREEN_WIDTH, 670), 2)
        
        # --- 3. BUTTONS (Save, Publish/Unpublish, Cancel, Delete) ---
        if self.draft and self.draft.is_published:
            btn_publish = (5, tr("Veröffentlichung aufheben"), (110, 80, 45), (170, 120, 60))
        else:
            btn_publish = (5, tr("Veröffentlichen"), (30, 80, 150), (45, 120, 220))

        buttons = [
            (4, tr("Entwurf Speichern"), (40, 120, 60), (60, 180, 90)),
            btn_publish,
            (6, tr("Abbrechen / Beenden"), (110, 45, 45), (170, 60, 60)),
            (7, tr("Strecke Löschen"), (150, 45, 45), (200, 60, 60)),
        ]
        
        mx, my = self._get_cursor_pos()
        for idx, text, base_col, active_col in buttons:
            rect = rects[idx]
            is_active = (getattr(self, "_props_focused", False) and self._props_field == idx) or rect.collidepoint(mx, my)
            
            pygame.draw.rect(screen, active_col if is_active else base_col, rect, border_radius=6)
            pygame.draw.rect(screen, (255, 255, 255) if is_active else (80, 100, 120), rect, 2, border_radius=6)
            
            txt_surf = self.f_body.render(text, True, (255, 255, 255))
            screen.blit(txt_surf, txt_surf.get_rect(center=rect.center))

    # -- Browser start screen ------------------------------------------
    _BROWSE_VISIBLE = 8

    def _browse_layout(self) -> list[tuple[int, pygame.Rect]]:
        """Visible rows only, mapped to their project index (scroll-aware)."""
        out = []
        x = SCREEN_WIDTH // 2 - 400
        y = 250
        start = self._browse_scroll
        end = min(len(self._projects), start + self._BROWSE_VISIBLE)
        for row, i in enumerate(range(start, end)):
            out.append((i, pygame.Rect(x, y + row * 88, 800, 74)))
        return out

    def _browse_ensure_visible(self) -> None:
        if self._browse_idx < self._browse_scroll:
            self._browse_scroll = self._browse_idx
        elif self._browse_idx >= self._browse_scroll + self._BROWSE_VISIBLE:
            self._browse_scroll = self._browse_idx - self._BROWSE_VISIBLE + 1

    def _tab_rects(self) -> list[pygame.Rect]:
        """Die Menüleiste der Menüschale — abgefragt, nicht nachgebaut.

        Hier stand bis zum 03.08.2026 eine Kopie mit fünf festen Einträgen und
        300 px Breite. Als Block D und E WERKSTATT und PROFIL ergänzten, zeigte
        der Editor weiter die alte Leiste, und die Kästen lagen nicht mehr dort,
        wo die Schale sie zeichnet.
        """
        from src.states.menu_shell_state import tab_rects
        return tab_rects()

    def _ensure_video(self, stem: str) -> None:
        if stem == self._video_stem:
            return
        if self._video is not None:
            self._video.close()
            self._video = None
        self._video_stem = stem
        path = os.path.join("data", "menu", f"{stem}.mp4")
        if os.path.isfile(path):
            from src.ui.video_player import VideoPlayer
            self._video = VideoPlayer(path, (SCREEN_WIDTH, SCREEN_HEIGHT))
            if not self._video.ok:
                self._video = None

    def _current_frame(self, stem: str) -> pygame.Surface | None:
        if stem == self._video_stem and self._video is not None:
            surf = self._video.get_surface()
            if surf is not None:
                return surf
        path = os.path.join("data", "menu", f"{stem}.png")
        if os.path.isfile(path):
            try:
                return pygame.image.load(path).convert()
            except Exception:
                pass
        return None

    def _draw_tab_bar(self, screen: pygame.Surface) -> None:
        from src.states.menu_shell_state import TAB_EDITOR, tab_leiste_zeichnen
        tab_leiste_zeichnen(screen, TAB_EDITOR)

    def _browse_zurueck(self) -> None:
        """Die Projektliste ist die oberste Ebene des Editors — von hier zurueck
        dorthin, wo er geoeffnet wurde. Taste und Knopf nehmen denselben Weg
        (gemeldet 04.08.2026)."""
        self.state_machine.zurueck()

    def _draw_browser(self, screen: pygame.Surface) -> None:
        # Draw background video/image
        self._ensure_video("Streckeneditor")
        frame = self._current_frame("Streckeneditor")
        if frame is not None:
            screen.blit(frame, (0, 0))
            screen.blit(theme.vignette((SCREEN_WIDTH, SCREEN_HEIGHT), 120), (0, 0))
        else:
            theme.draw_background(screen)

        # Draw main menu shell top tab bar
        self._draw_tab_bar(screen)

        # Translucent overlay to darken background like in other menus
        dark = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        dark.fill((0, 0, 0, 150))
        screen.blit(dark, (0, 0))

        # Title shifted down to avoid overlapping the header tabs
        title = self.f_title.render(tr("STRECKEN-EDITOR"), True, COLOR_UI_ACCENT)
        screen.blit(title, title.get_rect(midtop=(SCREEN_WIDTH // 2, 130)))
        sub = self.f_small.render(tr("Wähle eine Strecke zum Bearbeiten oder starte neu"),
                                  True, (150, 154, 168))
        screen.blit(sub, sub.get_rect(midtop=(SCREEN_WIDTH // 2, 180)))
        self._zurueck_knopf.draw(screen)

        badge = {"new": "", "draft": "Entwurf", "custom": "♦ Veröffentlicht"}
        badge_col = {"new": COLOR_UI_ACCENT, "draft": (150, 154, 168),
                     "custom": (120, 200, 255)}
        for i, rect in self._browse_layout():
            entry = self._projects[i]
            selected = (i == self._browse_idx)
            bg = (48, 42, 20) if selected else (28, 31, 40)
            pygame.draw.rect(screen, bg, rect, border_radius=8)
            pygame.draw.rect(screen, COLOR_UI_ACCENT if selected else (56, 60, 76),
                             rect, 2, border_radius=8)
            prefix = "+ " if entry["type"] == "new" else ""
            name_col = COLOR_UI_ACCENT if entry["type"] == "new" else COLOR_UI_TEXT
            name = self.f_body.render(prefix + entry["name"], True, name_col)
            screen.blit(name, (rect.x + 24, rect.centery - name.get_height() // 2))
            b = badge["custom"] if entry.get("is_published") else badge[entry["type"]]
            if b:
                col = badge_col["custom"] if entry.get("is_published") else badge_col[entry["type"]]
                bs = self.f_small.render(tr(b), True, col)
                screen.blit(bs, bs.get_rect(midright=(rect.right - 24, rect.centery)))

        # Draw vertical scrollbar if list overflows
        total = len(self._projects)
        if total > self._BROWSE_VISIBLE:
            sb_x = SCREEN_WIDTH // 2 + 420
            sb_y = 250
            sb_h = self._BROWSE_VISIBLE * 88 - 14  # 690
            pygame.draw.line(screen, (40, 44, 56), (sb_x, sb_y), (sb_x, sb_y + sb_h), 4)

            handle_h = max(30, int(sb_h * (self._BROWSE_VISIBLE / total)))
            max_scroll = total - self._BROWSE_VISIBLE
            scroll_pct = self._browse_scroll / max_scroll if max_scroll > 0 else 0
            handle_y = sb_y + int(scroll_pct * (sb_h - handle_h))

            pygame.draw.rect(screen, COLOR_UI_ACCENT, (sb_x - 3, handle_y, 6, handle_h), border_radius=3)

        hint_text = hints.bar(("confirm", tr("Öffnen")), ("back", tr("Zurück")))
        hint = self.f_small.render(hint_text, True, (150, 150, 165))
        screen.blit(hint, hint.get_rect(midbottom=(SCREEN_WIDTH // 2, SCREEN_HEIGHT - 40)))

    # -- Dirty prompt ---------------------------------------------------
    def _dirty_button_rects(self) -> list[tuple[pygame.Rect, str, tuple, tuple]]:
        w, h = 560, 220
        x = SCREEN_WIDTH // 2 - w // 2
        y = SCREEN_HEIGHT // 2 - h // 2
        by = y + h - 60
        bw = 160
        gap = 20
        start_x = x + (w - (3*bw + 2*gap)) // 2
        return [
            (pygame.Rect(start_x, by, bw, 40), tr("Speichern"), (40, 120, 60), (60, 180, 90)),
            (pygame.Rect(start_x + bw + gap, by, bw, 40), tr("Verwerfen"), (110, 45, 45), (170, 60, 60)),
            (pygame.Rect(start_x + 2*bw + 2*gap, by, bw, 40), tr("Abbrechen"), (56, 60, 76), (80, 100, 120)),
        ]

    def _draw_dirty_prompt(self, screen: pygame.Surface) -> None:
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        screen.blit(overlay, (0, 0))
        w, h = 560, 220
        x = SCREEN_WIDTH // 2 - w // 2
        y = SCREEN_HEIGHT // 2 - h // 2
        pygame.draw.rect(screen, (26, 28, 36), (x, y, w, h), border_radius=10)
        pygame.draw.rect(screen, COLOR_UI_ACCENT, (x, y, w, h), 2, border_radius=10)
        t1 = self.f_title.render(tr("Ungespeicherte Änderungen"), True, COLOR_UI_TEXT)
        screen.blit(t1, t1.get_rect(midtop=(x + w // 2, y + 34)))
        t2 = self.f_body.render(tr("Entwurf speichern, bevor du gehst?"), True, (180, 184, 198))
        screen.blit(t2, t2.get_rect(midtop=(x + w // 2, y + 92)))
        
        mx, my = self._get_cursor_pos()
        focus = getattr(self, "_dirty_focus", 0)
        for i, (rect, label, base, hot) in enumerate(self._dirty_button_rects()):
            hover = rect.collidepoint(mx, my) or i == focus
            pygame.draw.rect(screen, hot if hover else base, rect, border_radius=6)
            pygame.draw.rect(screen, (255, 255, 255) if hover else (120, 120, 130), rect, 2, border_radius=6)
            txt = self.f_body.render(label, True, (255, 255, 255))
            screen.blit(txt, txt.get_rect(center=rect.center))

    def _draw_gp_cursor(self, screen: pygame.Surface) -> None:
        cx, cy = int(self._gp_cursor[0]), int(self._gp_cursor[1])
        pulse = 0.5 + 0.5 * math.sin(self._time * 8.0)
        color = (0, 180, 255)
        # Draw outer glowing ring
        pygame.draw.circle(screen, color, (cx, cy), int(12 + 4 * pulse), 2)
        # Draw inner dot
        pygame.draw.circle(screen, color, (cx, cy), 3)
