"""Klangwerte je Motortyp — laden, sichern, Vorgaben (Releaseplan C8).

Zwei Ebenen, wie am 02.08.2026 festgelegt:

* **hier**: was für jeden Motor einer Bauart gilt — Überblendung der
  Drehzahlschichten, Grundpegel, Hochpass, Begrenzer, Blockgrenzen.
* **in der Fahrzeug-JSON**: die zwei Werte, die *ein* Fahrzeug ausmachen
  (``klang_tonhoehe``, ``klang_faerbung``). Die stehen dort seit §C5 und bleiben
  dort — was ein Auto ausmacht, gehört zum Auto.

Die Vorgaben sind mit Bedacht die **bisherige Wirkung**: Überblendung 1,0 wie
die alte Konstante ``sfx.BLENDE``, Hochpass und Begrenzer aus, Blocklänge 2048.
Eine Datei, die es noch nicht gibt, ändert damit nichts am Klang — abgestimmt
wird bewusst, nicht durch das Einführen dieses Moduls.
"""
from __future__ import annotations

import json
import os
from typing import Any

#: Grenzen und Schrittweite je Wert: (min, max, Schritt, Nachkommastellen).
#: Steht hier und nicht in der Bedienseite, damit ein aus der Datei gelesener
#: Unsinn dieselben Grenzen sieht wie ein Reglerklick.
GRENZEN: dict[str, tuple[float, float, float, int]] = {
    "schichtblende":      (0.0, 1.0, 0.05, 2),
    "grundpegel":         (0.0, 1.5, 0.05, 2),
    "hochpass_hz":        (0.0, 400.0, 5.0, 0),
    "begrenzer_schwelle": (0.1, 1.0, 0.05, 2),
    "begrenzer_tempo_ms": (1.0, 200.0, 1.0, 0),
    "blocklaenge":        (512.0, 8192.0, 512.0, 0),
    "drehzahlglaettung":  (0.0, 300.0, 5.0, 0),
    "zyklusstreuung":     (0.0, 0.05, 0.001, 3),
    "streuung_hz":        (0.5, 12.0, 0.5, 1),
    "knie_upm":           (0.0, 20000.0, 500.0, 0),
    "kompression":        (0.05, 1.0, 0.05, 2),
}

#: Vorgabe je Motortyp = das Verhalten von vor der Abstimmung.
VORGABE: dict[str, float] = {
    "schichtblende":      1.0,     # wie die frühere Konstante sfx.BLENDE
    "grundpegel":         1.0,
    "hochpass_hz":        0.0,     # aus
    "begrenzer_schwelle": 1.0,     # aus: unter 1,0 greift nichts
    "begrenzer_tempo_ms": 12.0,
    #: Angehoben am 05.08.2026 von 2048 auf 4096, wegen der Meldung „kleine
    #: Störgeräusche ca. 2 mal pro Runde".
    #:
    #: Nicht die Rechenlast — ein Block kostet 0,27 ms, sechs Stimmen zusammen
    #: 1,6 ms je Bild. Die Enge liegt in der **Frist**: eine Stimme hält genau
    #: einen Block vor, weil pygame nur einen Klang in der Warteschlange annimmt,
    #: nachgelegt wird einmal je Bild, und die Frist dafür ist die Spieldauer
    #: eines Blocks. Bei 2048 sind das 42,67 ms — also 2,56 Bilder Reserve bei
    #: 60 Bildern und nur 1,28 bei 30. Jedes einzelne Bild über 43 ms riss die
    #: Lücke, und eine Lücke klingt genau wie das gemeldete Knacksen: selten,
    #: unregelmäßig, ohne erkennbaren Anlass.
    #:
    #: 4096 verdoppelt die Frist auf 85,3 ms. Der Preis ist Nachlauf: die
    #: Drehzahl folgt dem Bild um bis zu 85 ms verzögert. Im Fahrzeuglabor
    #: einstellbar, gilt nach einem Neustart.
    "blocklaenge":        4096.0,
    "drehzahlglaettung":  0.0,     # aus: die Drehzahl folgt sofort
    #: Ausnahme von „Vorgabe = bisherige Wirkung": hier greift ab dem
    #: 03.08.2026 etwas ein, weil die bisherige Wirkung der Fehler war. Eine
    #: Schleife ist streng periodisch, zwei streng periodische Motoren schweben
    #: sauber gegeneinander — siehe sfx.Zyklusstreuung. 0,8 % gemessen an zwei
    #: Rennfahrzeugen bei 5000/5300 UPM: Schärfe der Schwebungslinie 95,2 → 5,3,
    #: also auf den Wert, den eine Stimme allein mitbringt. Eine Stimme allein
    #: ändert sich davon nicht, bis 3 % nicht.
    "zyklusstreuung":     0.008,
    #: Ab welcher Drehzahl der Ton nur noch gebremst weitersteigt, und wie
    #: stark. 0 heisst aus — so laufen die Verbrenner, deren Getriebe sie
    #: ohnehin unter der Drehzahlgrenze haelt. Siehe
    #: ``sfx.Motorstimme.akustische_drehzahl``; gesetzt wird es fuer den
    #: Elektro in ``motor_kennwerte.json``.
    "knie_upm":           0.0,
    "kompression":        1.0,
    #: Langsam, nicht schnell. Bei 1 Hz „atmet" der Motor; bei 5 Hz klingt die
    #: Schwankung selbst wie ein Effekt. Gemessen ist 1 Hz auch der beste Wert:
    #: die Schwebungslinie zweier Drifter bei 4200/4400 UPM fällt von 12,7 auf
    #: 4,4 (Schärfe 120 → 3,6), beim Rennfahrzeug von 6,6 auf 2,3 (85 → 3,4).
    "streuung_hz":        1.0,
}

#: Was für alle Motoren zusammen gilt. Die Puffergröße gehört dem Mixer und
#: kann nur beim Start gesetzt werden — sie steht deshalb getrennt.
GLOBAL_VORGABE: dict[str, float] = {
    #: 2048 Samples = 42,7 ms Vorlauf für den Mixer (vorher 512 = 10,7 ms).
    #:
    #: Geändert am 04.08.2026 nach dem Mitschnitt aus einem echten Rennen: das
    #: Signal, das wir dem Mixer vorlegen, ist einwandfrei — kein Sprung über
    #: dem 8-fachen des Üblichen, Blockgrenzen ununterscheidbar vom Inneren,
    #: Spitze 0,22 ohne Übersteuerung, kein Kanal leergelaufen, Bildzeit im
    #: Mittel 12,6 ms. Trotzdem knistert es, und zwar auch allein auf der
    #: Strecke. Was danach kommt, ist die Ausgabe selbst, und 10,7 ms sind ein
    #: sehr knapper Termin für den Audio-Rückruf: wird er einmal verpasst,
    #: klingt genau das nach Knistern. Ein Motorklang braucht keine 10 ms
    #: Latenz — die Blöcke sind ohnehin 42,7 ms lang.
    #:
    #: Zurückdrehen geht ohne Codeänderung: Fahrzeuglabor, Reiter KLANG,
    #: Station 2, Regler „Puffer" (wirkt nach einem Neustart).
    "puffer": 2048.0,
}
GLOBAL_GRENZEN: dict[str, tuple[float, float, float, int]] = {
    "puffer": (128.0, 4096.0, 128.0, 0),
}

_DATEI = os.path.join("data", "audio", "motor_klang.json")

_cache: dict[str, Any] | None = None


def _pfad() -> str:
    """Die Datei über alle Wurzeln suchen — gepackte Builds legen die
    mitgelieferten Daten woanders ab als das Arbeitsverzeichnis."""
    if os.path.isfile(_DATEI):
        return _DATEI
    from src.core import paths
    for wurzel in paths.track_roots():
        p = os.path.join(str(wurzel), _DATEI)
        if os.path.isfile(p):
            return p
    return _DATEI


def _begrenzen(schluessel: str, wert: Any, grenzen=GRENZEN,
               vorgabe=VORGABE) -> float:
    """Einen gelesenen Wert auf seine Grenzen bringen.

    Die Datei ist von Hand editierbar und wird von der Laborseite geschrieben —
    ein Tippfehler darf keinen stummen oder übersteuerten Motor ergeben.
    """
    lo, hi, _schritt, _dez = grenzen[schluessel]
    try:
        z = float(wert)
    except (TypeError, ValueError):
        return float(vorgabe[schluessel])
    if z != z or z in (float("inf"), float("-inf")):   # NaN oder unendlich
        return float(vorgabe[schluessel])
    return max(lo, min(hi, z))


def _laden() -> dict[str, Any]:
    global _cache
    if _cache is not None:
        return _cache
    roh: dict[str, Any] = {}
    pfad = _pfad()
    if os.path.isfile(pfad):
        try:
            with open(pfad, encoding="utf-8") as fh:
                gelesen = json.load(fh)
            if isinstance(gelesen, dict):
                roh = gelesen
        except (OSError, ValueError):
            roh = {}
    motoren = roh.get("motoren")
    _cache = {
        "motoren": motoren if isinstance(motoren, dict) else {},
        "global": roh.get("global") if isinstance(roh.get("global"), dict) else {},
    }
    return _cache


def neu_laden() -> None:
    """Cache verwerfen — nach dem Speichern und beim Verwerfen im Labor."""
    global _cache
    _cache = None


def werte(motor: str) -> dict[str, float]:
    """Alle Werte eines Motortyps, Vorgaben für alles, was fehlt."""
    eintrag = _laden()["motoren"].get(motor)
    eintrag = eintrag if isinstance(eintrag, dict) else {}
    return {k: _begrenzen(k, eintrag.get(k, v)) for k, v in VORGABE.items()}


def global_werte() -> dict[str, float]:
    eintrag = _laden()["global"]
    return {k: _begrenzen(k, eintrag.get(k, v), GLOBAL_GRENZEN, GLOBAL_VORGABE)
            for k, v in GLOBAL_VORGABE.items()}


def puffer() -> int:
    """Puffergröße für den Mixer. Wirkt erst beim nächsten Start."""
    return int(global_werte()["puffer"])


def setzen(motor: str, schluessel: str, wert: float) -> float:
    """Einen Wert im Cache ändern und zurückgeben, was daraus wurde.

    Geschrieben wird erst beim Speichern: wer im Labor dreht und dann verwirft,
    soll die Datei unverändert vorfinden.
    """
    daten = _laden()
    eintrag = daten["motoren"].setdefault(motor, {})
    eintrag[schluessel] = _begrenzen(schluessel, wert)
    return float(eintrag[schluessel])


def global_setzen(schluessel: str, wert: float) -> float:
    daten = _laden()
    daten["global"][schluessel] = _begrenzen(
        schluessel, wert, GLOBAL_GRENZEN, GLOBAL_VORGABE)
    return float(daten["global"][schluessel])


def auf_vorgabe(motor: str) -> None:
    _laden()["motoren"][motor] = dict(VORGABE)


def speichern() -> str:
    """Alles in die Datei schreiben. Gibt den Pfad zurück.

    Geschrieben werden **alle** Werte, auch die, die der Vorgabe entsprechen:
    die Datei ist die Abstimmung, und eine halb gefüllte Datei liest sich später
    wie eine unfertige.
    """
    daten = _laden()
    aus = {
        "hinweis": ("Klangwerte je Motortyp, abgestimmt im Fahrzeuglabor "
                    "(Reiter KLANG). Die zwei Werte eines einzelnen Fahrzeugs "
                    "stehen in dessen data/vehicles/<key>.json unter "
                    "klang_tonhoehe und klang_faerbung."),
        "global": {k: round(v, 3) for k, v in global_werte().items()},
        "motoren": {motor: {k: round(v, 4) for k, v in werte(motor).items()}
                    for motor in sorted(daten["motoren"])},
    }
    ziel = _DATEI
    os.makedirs(os.path.dirname(ziel), exist_ok=True)
    with open(ziel, "w", encoding="utf-8") as fh:
        json.dump(aus, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    neu_laden()
    return ziel
