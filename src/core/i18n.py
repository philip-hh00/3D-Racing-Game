"""Lightweight runtime localization.

Design — "German as key": the German source strings ARE the translation keys.
``tr("Zurück")`` returns the string unchanged when the language is German, or its
English counterpart from ``data/i18n/en.json`` when English is active. A missing
entry falls back to the German source, so German can never break and English
degrades gracefully.

Dynamic strings translate the *template*, then format:
    tr("FPS-Limit: {v}").format(v=value)
"""
from __future__ import annotations

import json
import os

LANGUAGES = ["de", "en"]          # internal codes
LANGUAGE_LABELS = {"de": "Deutsch", "en": "English"}

_lang = "de"
_tables: dict[str, dict[str, str]] = {}   # lang -> {german: translated}


def _load_table(lang: str) -> dict[str, str]:
    if lang in _tables:
        return _tables[lang]
    table: dict[str, str] = {}
    path = os.path.join("data", "i18n", f"{lang}.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            table = {str(k): str(v) for k, v in data.items()}
    except Exception:
        table = {}
    _tables[lang] = table
    return table


def set_language(lang: str) -> None:
    global _lang
    _lang = lang if lang in LANGUAGES else "de"
    if _lang != "de":
        _load_table(_lang)


def current() -> str:
    return _lang


def tr(s: str) -> str:
    """Translate *s* into the active language (German passes through)."""
    if _lang == "de" or not s:
        return s
    return _load_table(_lang).get(s, s)
