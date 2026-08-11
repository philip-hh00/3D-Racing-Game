"""Shared UI toolkit for the game's menus.

A small, self-contained widget kit used by every menu screen so they share one
look and one input model (arrow keys + mouse, hover and keyboard focus kept in
sync). Pure Pygame, no game-logic dependencies.
"""
from src.ui import theme
from src.ui.widgets import Button, Stepper, TextInput, Dialog, Label
from src.ui.tile_grid import TileGrid
from src.ui.focus import FocusGroup

__all__ = [
    "theme", "Button", "Stepper", "TextInput", "Dialog", "Label",
    "TileGrid", "FocusGroup",
]
