"""Spielrelevante Dateien gegen Austausch prüfen.

Die Fahrwerte (``data/vehicles/*.json``) und die Strecken
(``data/tracks/*.json``) liegen im ausgelieferten Paket als offenes JSON. Wer
darin die Motorleistung verdoppelt, fährt online allen davon. Zwei Dinge
passieren deshalb mit diesen Dateien:

1. **Beim Bauen** schreibt ``tools/pruefsummen.py`` eine signierte Liste der
   SHA-256-Werte nach :data:`LISTE`; beim Start vergleicht das Spiel. Eine
   Abweichung sperrt Online (Offline bleibt alles spielbar — eigene Dateien zu
   verändern ist kein Vergehen, nur nicht gegen andere).
2. **Beim Beitritt** schickt das Spiel :attr:`Ergebnis.digest` als ``files`` an
   den Relay (``src/net/client.py``). Der Relay kennt die Summe jedes Releases
   (``server/pruefsummen.json``, ebenfalls von ``tools/pruefsummen.py``) und
   lässt nur Spieler mit genau dieser Summe herein (Fehlercode
   ``MODIFIED_FILES``). Die Liste aus 1. lässt sich lokal umgehen, die Summe
   aus 2. nicht, ohne die Quelle der Wahrheit zu kennen.

**Was in die Summe eingeht** (:data:`MUSTER`): die Fahrzeugdateien (Physik,
Übersetzungen, Drehmomentkurve) und die mitgelieferten Strecken. *Nicht*:
Profil, Einstellungen, eigene Strecken (``data/tracks/custom``, ``online``,
``drafts``), Lackierungen (``lacke.json``), Modelle, Texturen, Klänge.

**Kanonisch.** Die Summe muss auf Windows und macOS, aus dem Quelltext und aus
dem gepackten Spiel dieselbe sein. Deshalb wird nicht der Dateiinhalt gehasht,
sondern der *Inhalt des JSON* in einer festen Schreibweise (sortierte Schlüssel,
keine Leerzeichen, nur ASCII): Zeilenenden (CRLF oder LF), Einrückung, eine
BOM-Markierung und die Reihenfolge der Schlüssel ändern die Summe nicht, jeder
geänderte Wert schon. Dateien, die sich nicht als JSON lesen lassen, gehen mit
vereinheitlichten Zeilenenden als Rohbytes ein. Die Dateipfade gehen mit ``/``
und relativ zur Wurzel ein, sortiert.

Wie bei :mod:`src.core.tresor`: der Schlüssel liegt im Spiel. Das ist eine
Bremsschwelle, kein Schutz gegen jemanden, der den Code liest; wer nur eine
Zahl in einer JSON-Datei ändern will, fällt aber auf.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from src.core import tresor

#: Welches Spiel das ist: ``game`` im ``HOST``/``JOIN`` und Schlüssel in
#: ``server/pruefsummen.json``.
SPIEL = "3d"

#: Wo die Liste im Paket liegt, relativ zur Wurzel.
LISTE = "data/settings/pruefsummen.json"

#: Was geprüft wird: alles, was Fahrverhalten und Rennen bestimmt. Grafik
#: gehört nicht dazu — ein anders gefärbter Baum verschafft keinen Vorteil.
#: Streckendateien nur die mitgelieferten (``paths.MITGELIEFERT``): ein
#: abgelegter Fremdling im Ordner stört nicht, eine geänderte Strecke schon.
MUSTER = (
    "data/vehicles/*.json",
)
STRECKEN = ("oval", "desert", "city", "mountain", "gp")
#: Reine Darstellung (Lackierungen) — kein Fahrvorteil.
AUSGENOMMEN = frozenset({"data/vehicles/lacke.json"})

#: Wird vor die Summe gehasht. Ändert sich die Art zu rechnen, ändert sich das
#: hier, und alte Summen passen nicht mehr.
KENNUNG = "schutz-1"


@dataclass
class Ergebnis:
    ok: bool
    digest: str = ""
    abweichend: list[str] = field(default_factory=list)


def dateien(wurzel: str | Path) -> list[Path]:
    """Alle geprüften Dateien, sortiert nach relativem Pfad (``/``)."""
    wurzel = Path(wurzel)
    gefunden: dict[str, Path] = {}
    for muster in MUSTER:
        for pfad in wurzel.glob(muster):
            if pfad.is_file():
                gefunden[pfad.relative_to(wurzel).as_posix()] = pfad
    for name in STRECKEN:
        pfad = wurzel / "data" / "tracks" / f"{name}.json"
        if pfad.is_file():
            gefunden[pfad.relative_to(wurzel).as_posix()] = pfad
    return [gefunden[k] for k in sorted(gefunden) if k not in AUSGENOMMEN]


def kanonisch(roh: bytes) -> bytes:
    """Der Inhalt einer Datei in der festen Schreibweise (siehe Modulkopf)."""
    try:
        wert = json.loads(roh.decode("utf-8-sig"))
        return json.dumps(wert, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True).encode("ascii")
    except (ValueError, UnicodeDecodeError, RecursionError):
        return b"RAW:" + roh.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def hashes(wurzel: str | Path) -> dict[str, str]:
    """SHA-256 des kanonischen Inhalts je geprüfter Datei, Schlüssel ist der Pfad mit ``/``."""
    wurzel = Path(wurzel)
    ergebnis = {}
    for pfad in dateien(wurzel):
        rel = pfad.relative_to(wurzel).as_posix()
        ergebnis[rel] = hashlib.sha256(kanonisch(pfad.read_bytes())).hexdigest()
    return dict(sorted(ergebnis.items()))


def _digest(dateien_: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps({"v": KENNUNG, "dateien": dateien_},
                                     sort_keys=True).encode("utf-8")).hexdigest()


def digest(wurzel: str | Path) -> str:
    """Die Summe, die das Spiel dem Relay schickt."""
    return _digest(hashes(wurzel))


def schreiben(wurzel: str | Path) -> Path:
    """Die signierte Liste für den jetzigen Stand anlegen (beim Bauen)."""
    wurzel = Path(wurzel)
    dateien_ = hashes(wurzel)
    summe = _digest(dateien_)
    pfad = wurzel / LISTE
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps({"dateien": dateien_, "digest": summe,
                                "sig": tresor.signatur(summe.encode("ascii"))},
                               indent=1), encoding="utf-8")
    return pfad


# -- Was der Relay über dieses Release wissen muss ------------------------------

def _strecken_laenge(pfad: Path) -> float | None:
    """Länge der Mittellinie in px (für die Mindest-Rundenzeit des Relays)."""
    try:
        pts = json.loads(pfad.read_text(encoding="utf-8-sig"))["centerline"]
        xy = [(float(p["x"]), float(p["y"])) for p in pts]
    except Exception:
        return None
    if len(xy) < 8:
        return None
    gesamt = sum(math.hypot(xy[(i + 1) % len(xy)][0] - x, xy[(i + 1) % len(xy)][1] - y)
                 for i, (x, y) in enumerate(xy))
    return round(gesamt, 1) if math.isfinite(gesamt) and gesamt > 0 else None


def server_eintrag(wurzel: str | Path) -> dict:
    """Der Eintrag dieses Releases für ``server/pruefsummen.json``.

    ``summen``: die Summe, die der Relay erwartet. ``fahrzeuge``: Höchsttempo je
    Fahrzeug in px/s und ``strecken``: Länge der Mittellinie je Strecke in px —
    daraus rechnet der Relay, was an Weg und Rundenzeit überhaupt möglich ist.
    """
    wurzel = Path(wurzel)
    fahrzeuge, strecken = {}, {}
    for pfad in dateien(wurzel):
        rel = pfad.relative_to(wurzel).as_posix()
        if rel.startswith("data/vehicles/"):
            try:
                v = float(json.loads(pfad.read_text(encoding="utf-8-sig"))["physics"]["max_speed"])
            except Exception:
                continue
            if math.isfinite(v) and v > 0:
                fahrzeuge[pfad.stem] = round(v, 3)
        elif rel.startswith("data/tracks/"):
            laenge = _strecken_laenge(pfad)
            if laenge:
                strecken[pfad.stem] = laenge
    return {"summen": [digest(wurzel)], "dateien": len(dateien(wurzel)),
            "fahrzeuge": dict(sorted(fahrzeuge.items())),
            "strecken": dict(sorted(strecken.items()))}


def pruefen(wurzel: str | Path, ausgeliefert: bool | None = None) -> Ergebnis:
    """Die Dateien gegen die Liste prüfen.

    ``ausgeliefert``: im gepackten Spiel muss die Liste da sein; aus dem
    Quelltext (Entwicklung) fehlt sie, und dann zählt der Stand als in
    Ordnung. Ohne Angabe entscheidet :data:`src.core.version.IS_RELEASE`.
    """
    wurzel = Path(wurzel)
    if ausgeliefert is None:
        from src.core.version import IS_RELEASE
        ausgeliefert = IS_RELEASE
    jetzt = hashes(wurzel)
    pfad = wurzel / LISTE
    if not pfad.is_file():
        return Ergebnis(ok=not ausgeliefert, digest=_digest(jetzt),
                        abweichend=[] if not ausgeliefert else [LISTE])
    try:
        liste = json.loads(pfad.read_text(encoding="utf-8"))
        soll = dict(liste["dateien"])
        summe = str(liste["digest"])
        echt = (tresor.signatur_pruefen(summe.encode("ascii"), str(liste["sig"]))
                and _digest(soll) == summe)
    except Exception:
        return Ergebnis(ok=False, digest=_digest(jetzt), abweichend=[LISTE])
    abweichend = sorted(k for k in set(soll) | set(jetzt) if soll.get(k) != jetzt.get(k))
    if not echt:
        abweichend = [LISTE] + abweichend
    return Ergebnis(ok=echt and not abweichend, digest=_digest(jetzt), abweichend=abweichend)


_stand: Ergebnis | None = None


def stand() -> Ergebnis:
    """Das Ergebnis für das laufende Spiel, einmal geprüft."""
    global _stand
    if _stand is None:
        from src.core.paths import bundle_dir
        _stand = pruefen(bundle_dir())
    return _stand
