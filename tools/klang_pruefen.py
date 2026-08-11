"""Den Abspielweg des Motorklangs eingrenzen (Block C).

    py -3.11 tools/klang_pruefen.py

Spielt dieselben sechs Sekunden Motorklang auf fünf Wegen nacheinander ab und
sagt jeweils an, welcher gerade läuft. Alle fünf enthalten **dasselbe Signal** —
was sich unterscheidet, ist nur, wie es in den Mixer kommt.

Hintergrund: die gerenderten Dateien blubbern nicht, im Spiel ist das Blubbern
aber da. Der Unterschied zwischen beiden ist ausschließlich dieser Weg — der
Klang wird im Spiel blockweise erzeugt und in die Warteschlange des Kanals
gelegt, statt am Stück abgespielt. Fünf Verdächtige stecken darin, und diese
Reihe trennt sie:

Entscheidend ist die **Abfragerate**. Der alte Weg startete den Kanal neu,
sobald ``get_busy()`` falsch meldete — und das tut es im kurzen Moment zwischen
zwei Blöcken. Je öfter abgefragt wird, desto öfter trifft man diesen Moment, und
jeder Fehlstart schneidet den laufenden Block ab. Gemessen in sechs Sekunden:

| Abfragen/s | Fehlstarts | verbrauchte Blöcke/s (nötig 23,4) |
|---|---|---|
| 60 | 5 | 24,8 |
| 300 | 37 | 30,0 |
| ungebremst | 141 | 47,3 |
| nur ``queue`` | 0 | 21,0 |

Das Spiel läuft mit ``fps_limit: 0``, also ungebremst — deshalb blubberte es dort
und im Werkzeug bei sechzig Abfragen nicht.

Die Reihe: 1 ohne Blockbetrieb, 2 alter Weg langsam abgefragt, 3 alter Weg
ungebremst, 4 neuer Weg ungebremst, 5 alter Weg mit größerem Mixerpuffer,
6 Ringpuffer ganz ohne Warteschlange.
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.core import sfx  # noqa: E402

DAUER = 6.0
#: Leerlauf und eine ruhige Fahrstufe — der Fehler soll bei beiden auffallen.
UPM = 900.0
MOTOR = "4zyl"


def stimme() -> sfx.Motorstimme:
    return sfx.Motorstimme(MOTOR)


def stereo(block: np.ndarray) -> pygame.mixer.Sound:
    daten = np.repeat((block * 32767.0).astype(np.int16)[:, None], 2, axis=1)
    return pygame.sndarray.make_sound(np.ascontiguousarray(daten))


def am_stueck() -> None:
    """Alles vorher rechnen, einmal abspielen."""
    s = stimme()
    n = int(sfx.SR * DAUER / sfx.BLOCK)
    ganz = np.concatenate([s.block(UPM) for _ in range(n)])
    kanal = pygame.mixer.Channel(0)
    kanal.set_volume(0.8, 0.8)
    kanal.play(stereo(ganz))
    while kanal.get_busy():
        time.sleep(0.05)


def blockweise(takt: float, mit_neustart: bool, blocklaenge: int = 2048) -> None:
    """Blockbetrieb wie im Spiel.

    *takt* ist die Pause zwischen zwei Abfragen — 1/60 für sechzig Bilder je
    Sekunde, 0 für ungebremst wie im Spiel mit ``fps_limit: 0``.
    *mit_neustart* schaltet den alten Neustart über ``get_busy()`` zu.
    """
    s = stimme()
    kanal = pygame.mixer.Channel(0)
    kanal.set_volume(0.8, 0.8)
    kanal.play(stereo(s.block(UPM, blocklaenge)))
    kanal.queue(stereo(s.block(UPM, blocklaenge)))

    ende = time.perf_counter() + DAUER
    neustarts, gelegt = 0, 2
    while time.perf_counter() < ende:
        if mit_neustart and not kanal.get_busy():
            neustarts += 1
            gelegt += 1
            kanal.play(stereo(s.block(UPM, blocklaenge)))
        elif kanal.get_queue() is None:
            gelegt += 1
            kanal.queue(stereo(s.block(UPM, blocklaenge)))
        if takt:
            time.sleep(takt)
    kanal.stop()
    noetig = sfx.SR / blocklaenge
    print(f"      {neustarts} Fehlstarts, {gelegt / DAUER:.1f} Bloecke/s "
          f"(noetig {noetig:.1f})")


def ringpuffer() -> None:
    """Ohne Warteschlange: **ein** dauerhaft laufender Klang, in den vor dem
    Abspielkopf hineingeschrieben wird.

    Damit gibt es keine Übergänge mehr und also auch keine Lücken. Der
    Abspielkopf wird aus der Uhr geschätzt — der Mixer läuft mit genau 48000
    Werten je Sekunde, das trägt weit genug.
    """
    s = stimme()
    laenge = sfx.SR // 2                      # halbe Sekunde Ring
    vorlauf = int(sfx.SR * 0.12)              # so weit vor dem Abspielkopf
    leer = np.zeros((laenge, 2), dtype=np.int16)
    klang = pygame.sndarray.make_sound(leer)
    ring = pygame.sndarray.samples(klang)     # zeigt in den Puffer des Klangs

    geschrieben = 0
    while geschrieben < vorlauf:
        block = (s.block(UPM) * 32767.0).astype(np.int16)
        ziel = np.arange(geschrieben, geschrieben + len(block)) % laenge
        ring[ziel, 0] = block
        ring[ziel, 1] = block
        geschrieben += len(block)

    kanal = pygame.mixer.Channel(0)
    kanal.set_volume(0.8, 0.8)
    kanal.play(klang, loops=-1)
    start = time.perf_counter()

    ende = start + DAUER
    while time.perf_counter() < ende:
        kopf = int((time.perf_counter() - start) * sfx.SR)
        while geschrieben - kopf < vorlauf:
            block = (s.block(UPM) * 32767.0).astype(np.int16)
            ziel = np.arange(geschrieben, geschrieben + len(block)) % laenge
            ring[ziel, 0] = block
            ring[ziel, 1] = block
            geschrieben += len(block)
        time.sleep(1 / 60)
    kanal.stop()
    del ring                                   # Verweis lösen, sonst bleibt der
    #                                            Puffer des Klangs gesperrt


def mixer(puffer: int) -> None:
    if pygame.mixer.get_init():
        pygame.mixer.quit()
    pygame.mixer.init(frequency=sfx.SR, size=-16, channels=2, buffer=puffer)
    pygame.mixer.set_num_channels(4)


def main() -> int:
    sfx.mixer_vorbereiten()
    pygame.init()
    if not sfx.schichten(MOTOR):
        print(f"Keine Aufnahmen für {MOTOR} gefunden.")
        return 1

    laeufe = [
        ("1  Fertige Datei, kein Blockbetrieb", 512, lambda: am_stueck()),
        ("2  Alter Weg, 60 Abfragen/s (so lief das Werkzeug)", 512,
         lambda: blockweise(1 / 60, True)),
        ("3  Alter Weg, ungebremst (so laeuft das Spiel)", 512,
         lambda: blockweise(0.0, True)),
        ("4  Neuer Weg, ungebremst (nur queue)", 512,
         lambda: blockweise(0.0, False)),
        ("5  Groesserer Mixerpuffer, alter Weg ungebremst", 2048,
         lambda: blockweise(0.0, True)),
        ("6  Ringpuffer statt Warteschlange", 512, lambda: ringpuffer()),
    ]

    print(f"Motor {MOTOR}, {UPM:.0f} U/min, je {DAUER:.0f} Sekunden.")
    print("Notiere, welche Nummern blubbern.\n")
    for name, puffer, lauf in laeufe:
        mixer(puffer)
        print(f"  {name}")
        lauf()
        time.sleep(0.6)

    print("\nFertig.")
    pygame.mixer.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
