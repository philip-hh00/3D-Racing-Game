# Release — Bauanleitung und Gebautes

Alles, was zum Ausliefern gehört, liegt hier. Der Ordner ist bewusst **beides**:
die Anleitung (versioniert) und das Ergebnis (nicht versioniert).

```
Release/
  skripte/       build_windows.bat, build_macos.sh  — bauen auf diesem Rechner
                 release_starten.bat, .sh           — bauen lassen auf GitHub
  pyinstaller/   game.spec, game_macos.spec         — was ins Bündel gehört
  installer/     installer.iss                      — Inno Setup, Windows
  ausgabe/       ← .exe und .dmg, nicht versioniert
  hoerproben/    ← Klangproben der Werkzeuge, nicht versioniert
```

`.gitignore` ignoriert deshalb nur `ausgabe/` und `hoerproben/`, nicht den ganzen
Ordner. Wird das je wieder auf `/Release/` verkürzt, verschwinden die Skripte
lautlos aus dem Repo — `tests/test_release_pipeline.py` schlägt dann an.

---

## Der übliche Weg: bauen lassen

```
Release\skripte\release_starten.bat
```

macOS und Linux: `./Release/skripte/release_starten.sh`.

Das Skript **fragt zuerst**, was gebaut werden soll:

```
 Was soll gebaut werden?

   [1]  Testbuild    — Pakete zum Ausprobieren, kein Release,
                       verbraucht KEINE Versionsnummer
   [2]  Release      — offizielle Fassung v0.7.1-beta als Entwurf

Auswahl [1/2, Enter = 1]:
```

Die harmlosere Antwort liegt auf der Eingabetaste. Vorher entschied das ein
Argument beim Aufruf — und ein vergessenes Argument hiess: aus Versehen eine
Versionsnummer verbraucht, die sich nicht zurückholen lässt. Wer es eilig hat,
kann weiterhin `test` oder `release` direkt mitgeben.

Das Skript liest die Version aus `src/core/version.py`, zeigt Branch und Zustand
des Arbeitsbaums, fragt einmal nach und setzt dann einen Tag. **Mehr braucht es
nicht** — kein zusätzliches Werkzeug, keine Anmeldung, nur `git`. Der Tag ist der
Auslöser; GitHub übernimmt ab da.

| Aufruf | Tag | Was passiert |
|---|---|---|
| ohne Argument | `v0.7.0-beta` | Tests, beide Builds, **Release-Entwurf** mit `.exe` und `.dmg` |
| `test` | `test-0.7.0-beta-0806-1432` | Tests, beide Builds, Pakete als **Artefakt am Lauf** — kein Release |

Ein Testbuild trägt dieselbe Versionsnummer wie ein echtes Release. Auseinander
zu halten sind sie an der **Bauzeit**, und genau deshalb veröffentlicht ein
Testbuild nichts: sonst wäre er mit dem echten zu verwechseln.

Das Release entsteht als **Entwurf**. Du siehst die Pakete also, bevor es
irgendwer sonst tut, und veröffentlichst von Hand.

### Die Bauzeit

`tools/baustempel.py` schreibt vor dem Packen `data/settings/build_stamp.json`
(Datum, Uhrzeit UTC, Commit, auslösender Tag). Die Datei wandert ins Bündel, und
die Info-Seite zeigt sie.

Das war bis zum 06.08.2026 kaputt: `version.BUILD_DATE` stand auf
`date.today()` und wurde beim **Start** ausgerechnet — ein Spieler sah sein
eigenes Tagesdatum als Build-Datum. Aus dem Quelltext gestartet fällt es weiter
auf heute zurück, und dort ist das richtig: gebaut und gestartet sind derselbe
Moment.

### Wenn etwas schiefgeht

* **„Tag gibt es schon"** — beim Testbuild eine Minute warten, der Zeitstempel
  ändert sich. Beim Release `VERSION` in `src/core/version.py` erhöhen.
* **„Tag passt nicht zu VERSION"** — der Ablauf bricht ab, bevor gebaut wird.
  Entweder die Version erhöhen oder den richtigen Tag nehmen. Ohne diese Prüfung
  entstünde `v1.0.1` aus einem Stand, der sich intern `1.0.0` nennt.
* **Arbeitsbaum nicht sauber** — das Skript warnt. Ein Tag zeigt auf den letzten
  Commit; alles Ungespeicherte fehlt im Paket.
* **Push schlägt fehl** — der Tag wird örtlich wieder zurückgenommen, sonst
  meldet der nächste Lauf „gibt es schon", ohne dass je etwas gebaut wurde.

---

## Abhängigkeiten

Zwei Dateien, und die Trennung ist nicht kosmetisch:

| Datei | Wofür | Landet im Bündel |
|---|---|---|
| `requirements.txt` | was das **Spiel** braucht | ja |
| `requirements-dev.txt` | was **Werkzeuge und Tests** brauchen (scipy, pytest) | nein |

Die Bauskripte installieren nur aus der ersten. Wer die Suite von Hand laufen
lässt, will beide — sonst überspringen sich die Tests der Klangwerkzeuge, statt
zu laufen.

Ein Test hält die Regel in beide Richtungen fest: jede Fremdbibliothek muss in
einer der beiden Dateien stehen, und `scipy` darf **nicht** in der ersten
stehen. Angelegt wurde die Trennung am 06.08.2026, weil die Pipeline beim
allerersten Lauf über genau diese Lücke gestolpert ist.

---

## Vorher: die 3D-Assets

Fahrzeuge, Umgebung, Texturen und Himmel liegen **nicht** im Repo, sie
entstehen aus Skripten (`tools/blender/`). Lokal einmal:

```
toolslenderauen.bat
```

`build_windows.bat` prüft, dass sie da sind, und bricht sonst mit genau diesem
Hinweis ab — ohne die Prüfung entstünde klaglos ein Spiel mit unsichtbaren
Autos. Auf GitHub baut der Auftrag `assets` in `release.yml` sie auf Linux mit
Blender und reicht sie als Artefakt an Windows und macOS weiter.

## Der andere Weg: hier bauen

```
Release\skripte\build_windows.bat
./Release/skripte/build_macos.sh
```

`build_windows.bat` nimmt das Python der Projekt-venv (`.venv`) — nur dort
liegen moderngl und die übrigen Laufzeitpakete des 3D-Spiels — und installiert
PyInstaller dort nach, falls es fehlt. Ergebnis: `3D-Racing-Game_Setup_v….exe`
(Installation je Benutzer, ohne Adminrechte, neben einem installierten
2D-Spiel möglich) und ein portables ZIP.

Beide wechseln zuerst ins Wurzelverzeichnis — sie liegen zwei Ebenen tief,
arbeiten aber mit Pfaden ab der Wurzel. Das Ergebnis liegt in `Release/ausgabe/`,
benannt nach Version und Bauzeit.

Der Windows-Build erwartet Python 3.11 und Inno Setup an den Pfaden, die oben im
Skript stehen; über die Umgebung (`PY`, `ISCC`) sind sie überschreibbar, und ist
dort nichts, wird das Python vom Suchpfad genommen.

---

## Was die Pipeline nicht kann

**Signieren.** Windows und macOS melden beim ersten Start einen unbekannten
Autor. Das ist so entschieden (keine Zertifikate) und kein Fehler im Ablauf.

**Auf itch.io hochladen.** Die Pakete hängen am Release; das Hochladen bleibt
Handarbeit.
