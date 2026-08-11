"""Mitschnitt des Rennklangs, um die Störgeräusche zu finden (05.08.2026).

Gemeldet und bis heute ungeklärt: „Es gibt immer mal wieder im Rennen kleine
Störgeräusche … ca. 2 mal pro Runde." Drei Verdachtsmomente sind am 05.08.2026
**ausgemessen und ausgeschlossen** worden:

* die Blockgrenzen des erzeugten Signals (Nähte kleiner als die übliche
  Bewegung im Block, Faktor 0,7–0,8 — auch mit Schaltvorgängen),
* die Lautstärkestufen je Bild (höchstens 0,022 bei einem Überholvorgang mit
  400 px/s Relativtempo, viel zu klein für ein Knacken),
* Einzelklänge, die einer Motorstimme den Kanal wegnehmen (sie liegen auf
  getrennten Kanalbereichen, das kann gar nicht passieren).

Damit bleibt der Weg **nach** unserer Rechnung: die Ausgabe selbst. Und die
hängt am Rechner, nicht am Spielstand — genau deshalb ist sie hier nicht
nachstellbar und muss dort aufgezeichnet werden, wo sie auftritt.

**Was hier mitgeschrieben wird, und warum es entscheidet.** Zwei Dinge
gleichzeitig:

1. Das Signal, das wir dem Mixer vorlegen (alle Stimmen summiert), als WAV.
2. Je Bild eine Zeile: Zeitpunkt, Bildzeit, und ob eine Stimme beim Nachlegen
   eine **leere** Warteschlange vorgefunden hat.

Punkt 2 ist der eigentliche Zweck. Eine Stimme hält genau einen Block vor; lief
der ab, bevor das nächste Bild nachlegen konnte, fehlt Ton — und eine Lücke
klingt wie ein Knacksen. Wer die Störungen zählt und die Zahl mit den hier
gezählten Aussetzern vergleicht, weiß danach, woran es liegt:

* **gleich viele, zu denselben Zeiten** → es sind Aussetzer, und die Blocklänge
  bzw. der Mixerpuffer ist die Stellschraube.
* **null Aussetzer, trotzdem Störungen** → wir liefern sauber ab, und es liegt
  an der Ausgabe (Treiber, Puffer der Soundkarte, Abtastratenwandlung). Dann ist
  im Spiel nichts zu reparieren, und die Suche geht dort weiter.

**Das Ergebnis, 05.08.2026.** Der zweite Fall. Bei **2 gehörten** Störungen im
Rennen zählt der Bericht **1** Aussetzer, und der fällt auf den ersten Block
einer Stimme — da *kann* der Kanal noch nicht laufen, das ist kein Loch,
sondern der Anfang. Dazu 0 Bilder über der Frist und eine Spitzenbildzeit von
22,98 ms gegen 85,33 ms Frist, also Faktor 3,7 Reserve. Der Ton selbst war
sauber: kein NaN, Spitze 0,4912, und **innerhalb** der Blöcke kein einziger
Sprung über dem 8-fachen des üblichen. Damit entsteht die Störung nach unserer
Rechnung, in der Ausgabe.

**Was dieses Werkzeug nicht kann.** Die WAV-Datei hängt die Blöcke *aller*
Stimmen hintereinander, statt sie zu summieren. Zum Abhören taugt sie deshalb
nicht, und die Sprünge an ihren Nahtstellen bedeuten nichts — sie sind Schnitte
zwischen verschiedenen Motoren. Was zählt, ist die Statistik im Bericht und das
Blockinnere. Wer hier je eine echte Abhörspur braucht, muss die Summe an einer
Stelle abgreifen, an der es sie gibt: im Mixer, nicht beim Nachlegen.

Der Mitschnitt ist absichtlich ein Werkzeug auf Zeit: er kostet Speicher und
Rechenzeit, solange er läuft, und kann nach der Untersuchung wieder ausgebaut
werden, so wie die Werkzeuge nach C9c auch. Ausgeschaltet kostet er nichts —
die Rennschleife fragt vorher `laeuft()`, und ein Test hält das fest.
"""
from __future__ import annotations

import json
import os
import time

import numpy as np

#: Läuft gerade ein Mitschnitt?
_aktiv = False
_stuecke: list[np.ndarray] = []
_zeilen: list[dict] = []
_beginn = 0.0
_letztes_bild = 0.0
#: Aussetzer seit dem Start des Mitschnitts, je Stimme gezählt.
_aussetzer = 0
_bloecke = 0


def laeuft() -> bool:
    return _aktiv


def starten() -> None:
    global _aktiv, _stuecke, _zeilen, _beginn, _letztes_bild, _aussetzer, _bloecke
    _stuecke, _zeilen = [], []
    _aussetzer, _bloecke = 0, 0
    _beginn = time.perf_counter()
    _letztes_bild = _beginn
    _aktiv = True


def block_gemerkt(block: np.ndarray, leer_vorgefunden: bool) -> None:
    """Eine Motorstimme hat einen Block nachgelegt.

    *leer_vorgefunden* heißt: der Kanal stand still, es lag also nichts mehr in
    der Warteschlange — das ist ein Aussetzer und damit eine hörbare Lücke.
    """
    global _aussetzer, _bloecke
    if not _aktiv:
        return
    _bloecke += 1
    if leer_vorgefunden:
        _aussetzer += 1
    if len(_stuecke) < 4000:            # rund 5 Minuten bei 4096er Blöcken
        _stuecke.append(np.asarray(block, dtype=np.float32).copy())


def bild(dt: float) -> None:
    """Einmal je Bild aus der Rennschleife."""
    global _letztes_bild
    if not _aktiv:
        return
    jetzt = time.perf_counter()
    _zeilen.append({
        "t": round(jetzt - _beginn, 4),
        "bildzeit_ms": round((jetzt - _letztes_bild) * 1000.0, 2),
        "aussetzer": _aussetzer,
    })
    _letztes_bild = jetzt


def beenden() -> str | None:
    """Mitschnitt abschließen und ablegen. Gibt den Pfad des Berichts zurück."""
    global _aktiv
    if not _aktiv:
        return None
    _aktiv = False
    from src.core import paths, sfx

    ordner = paths.user_path("data", "settings", "klangmitschnitt")
    os.makedirs(ordner, exist_ok=True)
    stempel = time.strftime("%Y-%m-%d_%H%M%S")

    if _stuecke:
        import wave
        welle = np.concatenate(_stuecke)
        spitze = float(np.max(np.abs(welle))) or 1.0
        if spitze > 1.0:
            welle = welle / spitze
        with wave.open(os.path.join(ordner, f"{stempel}.wav"), "wb") as fh:
            fh.setnchannels(1)
            fh.setsampwidth(2)
            fh.setframerate(sfx.SR)
            fh.writeframes((np.clip(welle, -1, 1) * 32767).astype("<i2").tobytes())

    bildzeiten = [z["bildzeit_ms"] for z in _zeilen] or [0.0]
    blocklaenge_ms = 1000.0 * sfx.BLOCK / sfx.SR
    bericht = {
        "dauer_s": round(_zeilen[-1]["t"], 2) if _zeilen else 0.0,
        "bilder": len(_zeilen),
        "bloecke_nachgelegt": _bloecke,
        "aussetzer": _aussetzer,
        "bildzeit_ms": {
            "median": round(float(np.median(bildzeiten)), 2),
            "p99": round(float(np.percentile(bildzeiten, 99)), 2),
            "max": round(float(np.max(bildzeiten)), 2),
        },
        # Die Frist, in der das naechste Bild nachlegen muss. Bilder darueber
        # sind die Kandidaten fuer eine Luecke.
        "frist_ms": round(blocklaenge_ms, 2),
        "bilder_ueber_frist": int(sum(1 for b in bildzeiten if b > blocklaenge_ms)),
        "mixerpuffer": _puffer(),
        "blocklaenge": sfx.BLOCK,
        # Seit dem Umbau auf den Audiofaden (06.08.2026) ist **das** die
        # entscheidende Zeile: welcher Weg lief, auf welchem Geraet, mit welcher
        # Rate, und wie oft der Ring leer war. Ohne sie wuerde bei der naechsten
        # Meldung wieder geraten.
        "audiofaden": _audiofaden(),
        "hinweis": ("Zaehle beim Abspielen die Stoergeraeusche. Stimmt die Zahl "
                    "mit 'aussetzer' ueberein, sind es Luecken beim Nachlegen. "
                    "Ist 'aussetzer' null, liefert das Spiel sauber ab und die "
                    "Stoerung entsteht erst in der Ausgabe."),
        "bilder_einzeln": _zeilen[-3000:],
    }
    pfad = os.path.join(ordner, f"{stempel}.json")
    with open(pfad, "w", encoding="utf-8") as fh:
        json.dump(bericht, fh, ensure_ascii=False, indent=1)
    return pfad


def _audiofaden() -> dict:
    """Zustand des Audiofadens, oder warum er nicht läuft."""
    try:
        from src.core import tonausgabe
        return tonausgabe.zustand()
    except Exception as exc:
        return {"laeuft": False, "grund": f"nicht lesbar: {exc}"}


def _puffer() -> int:
    try:
        from src.core import motorklang
        return int(motorklang.puffer())
    except Exception:
        return 0
