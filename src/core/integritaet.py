"""Spielrelevante Dateien gegen Austausch prüfen.

Die Fahrwerte (``data/vehicles/*.json``), die Strecken und die Einstellungen
der KI liegen im ausgelieferten Paket als offenes JSON. Wer darin die
Motorleistung verdoppelt, fährt online allen davon. Beim Bauen schreibt
``tools/pruefsummen.py`` deshalb eine signierte Liste der SHA-256-Werte
dieser Dateien nach :data:`LISTE`; beim Start vergleicht das Spiel.

**Folge einer Abweichung:** Online ist gesperrt, und der Online-Server lässt
nur Spieler mit gleichem :attr:`Ergebnis.digest` zusammen fahren (siehe
``server/server.py``). Offline bleibt alles spielbar — eigene Dateien zu
verändern ist kein Vergehen, nur nicht gegen andere.

Wie bei :mod:`src.core.tresor`: der Schlüssel liegt im Spiel. Das ist eine
Bremsschwelle, kein Schutz gegen jemanden, der den Code liest; wer nur eine
Zahl in einer JSON-Datei ändern will, fällt aber auf.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from src.core import tresor

#: Wo die Liste im Paket liegt, relativ zur Wurzel.
LISTE = "data/settings/pruefsummen.json"

#: Was geprüft wird: alles, was Fahrverhalten und Rennen bestimmt. Grafik
#: gehört nicht dazu — ein anders gefärbter Baum verschafft keinen Vorteil.
MUSTER = (
    "data/vehicles/*.json",
    "data/tracks/*.json",
)


@dataclass
class Ergebnis:
    ok: bool
    digest: str = ""
    abweichend: list[str] = field(default_factory=list)


def hashes(wurzel: str | Path) -> dict[str, str]:
    """SHA-256 je geprüfter Datei, Schlüssel ist der Pfad mit ``/``."""
    wurzel = Path(wurzel)
    ergebnis = {}
    for muster in MUSTER:
        for pfad in sorted(wurzel.glob(muster)):
            if pfad.is_file():
                rel = pfad.relative_to(wurzel).as_posix()
                ergebnis[rel] = hashlib.sha256(pfad.read_bytes()).hexdigest()
    return dict(sorted(ergebnis.items()))


def _digest(dateien: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(dateien, sort_keys=True).encode("utf-8")).hexdigest()


def schreiben(wurzel: str | Path) -> Path:
    """Die signierte Liste für den jetzigen Stand anlegen (beim Bauen)."""
    wurzel = Path(wurzel)
    dateien = hashes(wurzel)
    digest = _digest(dateien)
    pfad = wurzel / LISTE
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps({"dateien": dateien, "digest": digest,
                                "sig": tresor.signatur(digest.encode("ascii"))},
                               indent=1), encoding="utf-8")
    return pfad


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
        digest = str(liste["digest"])
        echt = (tresor.signatur_pruefen(digest.encode("ascii"), str(liste["sig"]))
                and _digest(soll) == digest)
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
