"""Die Seite „Fahrhilfen“ der Einstellungen (Plan 1.1.0).

ABS, Traktionskontrolle und Ideallinie lassen sich einzeln schalten; dazu die
Stärke der Controller-Vibration. Alles liegt im Profil (``profile.fahrhilfen``)
und gilt als lokale Sache des eigenen Rechners — online geht dafür nichts übers
Netz. Die Seite ist bewusst klein und gekapselt: ``settings_page.py`` ruft nur
``bauen``, ``aendern``, ``uebernehmen`` und ``zeichnen``.
"""
from __future__ import annotations

import pygame

from src.core import profile
from src.core.i18n import tr
from src.core.profile import VIBRATION_STUFEN
from src.ui import theme
from src.ui.focus import FocusGroup
from src.ui.widgets import Stepper

#: Aktion des Steppers -> Schlüssel im Profil.
AKTIONEN = {"fh_abs": "abs", "fh_tc": "tc", "fh_linie": "linie", "fh_vibration": "vibration"}


def _an_aus() -> list[str]:
    return [tr("Aus"), tr("An")]


def _stufen() -> list[str]:
    return [tr("Aus"), tr("Schwach"), tr("Mittel"), tr("Stark")]


def _aktuell(seite, name: str):
    """Wert, wie er mit dem Ungespeicherten gelten würde."""
    return seite._pending.get("fahrhilfen", {}).get(name, profile.current().fahrhilfe(name))


def bauen(seite) -> FocusGroup:
    """Die Regler der Seite; setzt ``seite._werte`` für die Rohwerte."""
    seite._werte["fh_abs"] = seite._werte["fh_tc"] = seite._werte["fh_linie"] = [False, True]
    seite._werte["fh_vibration"] = list(range(VIBRATION_STUFEN))
    col = theme.Column(560, 250, gap=12)
    widgets = [
        Stepper(pygame.Rect(0, 0, 500, 60), tr("ABS"), _an_aus(),
                int(bool(_aktuell(seite, "abs"))), action="fh_abs"),
        Stepper(pygame.Rect(0, 0, 500, 60), tr("Traktionskontrolle"), _an_aus(),
                int(bool(_aktuell(seite, "tc"))), action="fh_tc"),
        Stepper(pygame.Rect(0, 0, 500, 60), tr("Ideallinie"), _an_aus(),
                int(bool(_aktuell(seite, "linie"))), action="fh_linie"),
        Stepper(pygame.Rect(0, 0, 500, 60), tr("Controller-Vibration"), _stufen(),
                int(_aktuell(seite, "vibration")), action="fh_vibration"),
    ]
    for w in widgets:
        col.add(w)
    return FocusGroup(widgets)


def aendern(seite, aktion: str) -> None:
    """Ein Regler wurde bewegt: puffern (gilt erst mit SPEICHERN); Vibration vorspüren."""
    name = AKTIONEN.get(aktion)
    if name is None:
        return
    widgets = seite._content_group.widgets if seite._content_group else []
    w = next((w for w in widgets if getattr(w, "action", None) == aktion), None)
    roh = seite._werte.get(aktion) or []
    if w is None or not roh:
        return
    wert = roh[max(0, min(int(w.index), len(roh) - 1))]
    seite._pending.setdefault("fahrhilfen", {})[name] = wert
    seite.msg = ""
    if name == "vibration":
        _vorspueren(int(wert))


def _vorspueren(stufe: int) -> None:
    """Die gewählte Stärke einmal kurz auf Controller 1 und 2 geben."""
    from src.core import gamepad, vibration
    faktor = vibration.stufe_faktor(stufe)
    if faktor <= 0.0:
        return
    for i in range(min(2, gamepad.device_count())):
        gamepad.rumble(i, 0.7 * faktor, 0.5 * faktor, 350)


def uebernehmen(profil, geaendert: dict) -> None:
    """Gepufferte Werte ins Profil schreiben (der Aufrufer speichert danach)."""
    for name, wert in geaendert.items():
        if name in profile.FAHRHILFEN_STANDARD:
            profil.fahrhilfen[name] = wert


def zeichnen(seite, screen: pygame.Surface) -> None:
    from src.states.menu.settings_page import _umbrechen
    theme.text(screen, tr("Fahrhilfen"), theme.BODY, theme.TEXT_DIM, (560, 190))
    if seite._content_group:
        seite._content_group.draw(screen, focused=seite._focus_content)
        unten = max(w.rect.bottom for w in seite._content_group.widgets)
    else:
        unten = 250
    y = unten + 24
    for hinweis in (
            tr("Die Hilfen gelten nur für dich. Die KI fährt ohne, und online ändert sich für niemand anders etwas."),
            tr("ABS nimmt Bremsdruck weg, wenn ein Reifen rutscht. Die Traktionskontrolle nimmt Gas weg, bis die Räder greifen."),
            tr("Die Ideallinie zeigt die Linie der KI: grün Gas, gelb Gas weg, rot Bremsen."),
            tr("Vibration: Treffer, Wand, Rutschen und Randsteine; je Controller, auch im Splitscreen."),
            tr("Änderungen werden erst mit SPEICHERN übernommen.")):
        for zeile in _umbrechen(hinweis, theme.HINT, 640):
            theme.text(screen, zeile, theme.HINT, theme.TEXT_FAINT, (560, y))
            y += 28
        y += 8
