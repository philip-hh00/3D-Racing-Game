# Motorklänge aufnehmen (Block C)

Anleitung für Aufnahmen mit dem Engine Simulator. Grundlage der Entscheidung vom
29.07.2026: eigene Sweeps waren mit 0,8 s zu kurz, daraus geschnittene Schleifen
wiederholten sich 9,5-mal pro Sekunde und klangen nach Hubschrauber. Mit
Aufnahmen von 3 s je Drehzahl sind es 0,3 Wiederholungen pro Sekunde — dieselbe
Technik, nur brauchbares Material.

---

## Vorher klären: Lizenz

Die aktuelle Fassung des Engine Simulator ist **closed source und ohne
angegebene Lizenz**. Ob mitgeschnittene Töne in einem veröffentlichten Spiel
verwendet werden dürfen, ist damit offen.

**Vor der Aufnahme prüfen** — in der beiliegenden Lizenz-/Readme-Datei, auf der
itch.io-Seite oder per Rückfrage beim Autor. Ohne klare Antwort landet nichts
davon im Repo.

---

## Was aufgenommen werden soll

Drei Motoren, weil die Fahrzeugklassen sich über die Zylinderzahl unterscheiden:

| Motor | Fahrzeugklassen |
|---|---|
| 4 Zylinder | Hatchback |
| 6 Zylinder | Limousine, Drifter |
| 8 Zylinder | Rennfahrzeug |

**Elektroauto braucht keine Aufnahme.** Ein Elektroantrieb hat keine Zündungen;
der vorhandene synthetische Klang bleibt (Pfeifen proportional zur Drehzahl,
eingestellt an der eigenen Aufnahme `car-electric-reving`).

### Je Motor

**Fünf konstante Drehzahlen, je 3 Sekunden.** Ungefähre Werte, sie müssen nicht
genau getroffen werden — nur ungefähr gleichmäßig verteilt sein:

    Leerlauf (ca.  900)
    2000
    3500
    5000
    6500

Drehzahl einstellen, **eine Sekunde warten**, bis sie steht, dann 3 s aufnehmen.
Gleichmäßig ist wichtiger als exakt.

**Dazu ein langsamer Hochlauf über 10–15 Sekunden**, von Leerlauf bis Anschlag,
möglichst gleichmäßig. Der dient als Rückfall und für die Übergänge.

**Optional, falls es schnell geht:** dieselben fünf Drehzahlen ohne Last
(Schiebebetrieb). Damit ließe sich zwischen „Gas" und „kein Gas" umblenden, so
wie es Rennspiele tun. Kein Muss.

---

## Wie aufnehmen

Audacity oder OBS mit Systemton-Mitschnitt (Windows: „Stereomix" bzw. in OBS
„Desktop-Audio"). Was zählt:

* **Lautstärke zwischen den Aufnahmen NICHT verändern.** Die relativen Pegel der
  Drehzahlen tragen Information — ein Motor unter Volllast ist lauter als im
  Leerlauf, und das soll erhalten bleiben. Pegel angleichen macht das Werkzeug
  später selbst, aber es braucht die Verhältnisse.
* **Nichts anderes darf mitlaufen** — keine Musik, keine Benachrichtigungen.
* WAV, möglichst 48 kHz. 44,1 kHz geht auch, wird umgerechnet.
* Mono oder Stereo, beides in Ordnung.
* Nicht in die Übersteuerung fahren. Etwas Reserve ist besser als ein
  abgeschnittener Pegel.

---

## Wohin und wie benennen

Alles nach `data/audio/sfx/aufnahmen/` legen. Benennung bestimmt, was das
Werkzeug daraus macht:

    4zyl-0900.wav     konstante Drehzahl, Zahl = U/min
    4zyl-2000.wav
    4zyl-3500.wav
    4zyl-5000.wav
    4zyl-6500.wav
    4zyl-rev.wav      langsamer Hochlauf

    6zyl-0900.wav ... 6zyl-rev.wav
    8zyl-0900.wav ... 8zyl-rev.wav

Für den optionalen Schiebebetrieb dasselbe mit `-schub` am Ende:
`4zyl-3500-schub.wav`.

---

## Danach

    py -3.11 tools/motor_import.py            nur messen, schreibt nichts
    py -3.11 tools/motor_import.py --schreiben

Das Werkzeug sucht in jeder Aufnahme die Schleifenlänge mit der **besten Naht**
(geprüft wird, ob der Anfang zu dem passt, was nach dem Ende kommt — genau das
passiert beim Rundlauf), gleicht die Pegel **innerhalb** eines Motors an und
schreibt eine Tabelle mit der Drehzahl je Schicht.

Wichtig zum Pegel: die Verhältnisse zwischen den Drehzahlen bleiben erhalten.
Angehoben wird nur die leiseste Aufnahme auf den Zielwert, alle anderen um
denselben Betrag — sonst wäre Volllast genauso laut wie Leerlauf.

Die Ausgabe nennt je Schicht die Nahtgüte; alles über 0,8 ist eine saubere
Schleife. Im Selbsttest mit erzeugten Aufnahmen liegt sie bei 0,96 bis 0,99.
