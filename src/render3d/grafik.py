"""Grafik-Stufen: was die 3D-Welt kosten darf.

Eine Stelle, aus der alle Teile der Rennwelt lesen, wie viel sie zeichnen
dürfen — Schatten, Nachbearbeitung, Gelände, Gras, Deko, Streckendetails.
Die Einstellungsseite schreibt hierher, das Profil speichert es.

Vier Stufen als Schnellwahl, jede Einzelgröße lässt sich danach verstellen.
**Niedrig** ist die Stufe für eine Einsteiger-Grafikkarte (GTX 1050 /
RX 560): 1080p mit 60 Bildern. Wer ein neues Merkmal baut, trägt hier ein
Feld ein und legt für jede Stufe fest, was es dort darf — ein Merkmal ohne
Eintrag hier läuft auf jedem Rechner in voller Stärke und reißt Niedrig.

Gelesen wird über :func:`aktuell`; die Werte sind nur zum Lesen gedacht.
Geändert wird über :func:`setzen` oder :func:`stufe_setzen`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace

STUFEN_NAMEN = ("niedrig", "mittel", "hoch", "ultra")


@dataclass(frozen=True)
class Grafik:
    #: Name der Stufe, aus der die Werte stammen; "eigen", sobald ein
    #: Einzelwert davon abweicht.
    stufe: str = "hoch"
    #: Anteil der Fensterauflösung, in der die 3D-Welt gerechnet wird
    #: (0.5 … 1.0). Das HUD bleibt immer scharf.
    aufloesung_skala: float = 1.0
    #: Kantenlänge der Sonnen-Schattenkarte; 0 schaltet den Schattenwurf ab
    #: (dann bleiben nur die Klecksschatten unter den Autos).
    schatten_px: int = 4096
    #: Umgebungsverdeckung im Bildraum: 0 aus, 1 halbe Auflösung, 2 voll.
    ssao: int = 1
    #: Leuchten um helle Stellen (Rückleuchten, Sonne im Lack).
    bloom: bool = True
    #: "aus", "fxaa" oder "msaa4".
    kantenglaettung: str = "msaa4"
    #: Anteil der Deko am Streckenrand und im Hintergrund (0.3 … 1.0).
    deko_dichte: float = 1.0
    #: Wie weit gezeichnet wird, Meter (Deko, Gras, Details dahinter entfallen).
    sichtweite_m: float = 1600.0
    #: Gras und Bodenbewuchs nah an der Strecke: 0 aus, 1 dünn, 2 dicht.
    gras: int = 2
    #: Auflösung des Geländes um die Strecke: 0 grob, 1 mittel, 2 fein.
    gelaende_detail: int = 2
    #: Kleinteile an der Strecke (Hütchen, Posten, Publikum): 0, 1, 2.
    strecken_details: int = 2
    #: Reifenspuren und Reifenrauch.
    reifenspuren: bool = True


STUFEN: dict[str, Grafik] = {
    "niedrig": Grafik(stufe="niedrig", aufloesung_skala=0.75, schatten_px=1024, ssao=0,
                      bloom=False, kantenglaettung="fxaa", deko_dichte=0.4,
                      sichtweite_m=700.0, gras=0, gelaende_detail=0,
                      strecken_details=0, reifenspuren=False),
    "mittel": Grafik(stufe="mittel", aufloesung_skala=1.0, schatten_px=2048, ssao=0,
                     bloom=True, kantenglaettung="fxaa", deko_dichte=0.7,
                     sichtweite_m=1100.0, gras=1, gelaende_detail=1,
                     strecken_details=1, reifenspuren=True),
    "hoch": Grafik(),
    "ultra": Grafik(stufe="ultra", ssao=2, deko_dichte=1.0, sichtweite_m=2400.0),
}

_aktuell: Grafik = STUFEN["hoch"]


def aktuell() -> Grafik:
    return _aktuell


def stufe_setzen(name: str) -> Grafik:
    global _aktuell
    _aktuell = STUFEN.get(name, STUFEN["hoch"])
    return _aktuell


def setzen(**werte) -> Grafik:
    """Einzelwerte ändern; die Stufe heißt danach "eigen"."""
    global _aktuell
    bekannt = {f.name for f in fields(Grafik)} - {"stufe"}
    werte = {k: v for k, v in werte.items() if k in bekannt}
    if werte:
        _aktuell = replace(_aktuell, stufe="eigen", **werte)
    return _aktuell


def als_dict(g: Grafik | None = None) -> dict:
    return asdict(g or _aktuell)


def aus_dict(daten: dict | None) -> Grafik:
    """Aus dem Profil; Unbekanntes wird übergangen, Fehlendes kommt aus der Stufe."""
    global _aktuell
    daten = dict(daten or {})
    grund = STUFEN.get(daten.get("stufe", "hoch"), STUFEN["hoch"])
    bekannt = {f.name for f in fields(Grafik)}
    _aktuell = replace(grund, **{k: v for k, v in daten.items() if k in bekannt})
    return _aktuell
