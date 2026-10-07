"""Das Fenster passt auf den Bildschirm (gemeldet 07.10.2026, MacBook).

Bis 1.0.0 ging die eingestellte Groesse unveraendert an das Fenster: auf
einem MacBook mit 1440×900 Punkten war das Vorgabefenster 1920×1080 groesser
als der Bildschirm und wurde abgeschnitten.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core import display  # noqa: E402

MACBOOK = (1440, 900)
FULL_HD = (1920, 1080)
UHD = (3840, 2160)


def _passt(groesse, schirm):
    return (groesse[0] <= schirm[0] * display.FENSTER_ANTEIL_B
            and groesse[1] <= schirm[1] * display.FENSTER_ANTEIL_H)


def test_vorgabefenster_wird_auf_dem_macbook_verkleinert():
    b, h = display.passende_fenstergroesse(1920, 1080, MACBOOK)
    assert _passt((b, h), MACBOOK)
    assert abs(b / h - 16 / 9) < 0.01           # Seitenverhaeltnis bleibt


def test_was_passt_bleibt_unveraendert():
    assert display.passende_fenstergroesse(1600, 900, FULL_HD) == (1600, 900)
    assert display.passende_fenstergroesse(1920, 1080, UHD) == (1920, 1080)


def test_auswahl_zeigt_nur_was_als_fenster_passt():
    auf_macbook = display.verfuegbare_aufloesungen(MACBOOK)
    assert auf_macbook == ["1280×720"]
    auf_uhd = display.verfuegbare_aufloesungen(UHD)
    assert "2560×1440" in auf_uhd and "3840×2160" not in auf_uhd


def test_auf_winzigem_schirm_bleibt_die_kleinste():
    assert display.verfuegbare_aufloesungen((800, 600)) == ["1280×720"]


def test_ohne_bekannten_bildschirm_alles_wie_bisher(monkeypatch):
    monkeypatch.setattr(display, "_desktop_groesse", lambda: None)
    assert display.passende_fenstergroesse(1920, 1080) == (1920, 1080)
    assert display.verfuegbare_aufloesungen() == display.RESOLUTION_LABELS
