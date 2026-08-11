"""Driver names for AI opponents.

A fixed pool of 30 names; each race draws a distinct random subset so the
opponents feel like a real field instead of "AI 1..5".
"""
from __future__ import annotations

import random

NAMES: list[str] = [
    "M. Weber", "A. Klein", "L. Fischer", "J. Becker", "S. Wagner",
    "T. Hoffmann", "N. Schäfer", "P. Koch", "R. Bauer", "K. Richter",
    "D. Wolf", "F. Neumann", "C. Schwarz", "B. Zimmermann", "H. Braun",
    "E. Krüger", "V. Hartmann", "O. Lange", "G. Werner", "I. Krause",
    "Q. Vogel", "Y. Sommer", "Z. Frank", "W. Busch", "X. Roth",
    "U. Seidel", "M. Kaiser", "A. Fuchs", "L. Berg", "J. Winter",
]

# English-locale pool used when the game language is English, so AI opponents
# don't read as German names. Same size as NAMES.
NAMES_EN: list[str] = [
    "M. Carter", "A. Brooks", "L. Fisher", "J. Baker", "S. Wagner",
    "T. Hoffman", "N. Shaw", "P. Cook", "R. Palmer", "K. Rich",
    "D. Wolfe", "F. Newman", "C. Black", "B. Sommers", "H. Brown",
    "E. Kruger", "V. Hartman", "O. Long", "G. Warner", "I. Cross",
    "Q. Vaughn", "Y. Somers", "Z. Frank", "W. Bush", "X. Roth",
    "U. Sadler", "M. Kaiser", "A. Fox", "L. Hill", "J. Winter",
]


def _pool() -> list[str]:
    from src.core.i18n import current
    return NAMES_EN if current() == "en" else NAMES


def pick(n: int) -> list[str]:
    """Return *n* distinct random names (clamped to the pool size)."""
    pool = _pool()
    n = max(0, min(n, len(pool)))
    return random.sample(pool, n)
