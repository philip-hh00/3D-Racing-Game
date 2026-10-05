# Projekte vom NAS auf den Mac holen

Auf dem NAS liegen unter `freigabe/Repositories`:

| Pfad | Inhalt |
|---|---|
| `3D-Racing-Game.git`, `2D-Racing-Game.git` | Code, dieselbe Historie wie GitHub |
| `3D-Racing-Game-Daten.git`, `2D-Racing-Game-Daten.git` | alles, was nicht auf GitHub liegt (GLBs, Videos, Audio, Rohdaten …) |
| `3D-Racing-Game-Builds/`, `2D-Racing-Game-Builds/` | fertige Installer und Zips (einfache Dateien) |

Erledigt wird alles von `tools/nas_sync.py` (`holen` und `sichern`).

## Einmalig einrichten

**1. Werkzeuge** (git und python3), im Terminal:

```bash
xcode-select --install
```

**2. NAS verbinden:** Im Finder **Gehe zu → Mit Server verbinden …** (⌘K)
wählen, dort `smb://192.168.178.108/NAS-Storage` eingeben und anmelden. Die
Freigabe liegt danach unter `/Volumes/NAS-Storage`.

**3. git den NAS-Repos vertrauen lassen:** Sie gehören dem NAS-Konto, nicht
deinem Mac-Benutzer. Ohne diesen Schritt bricht git mit „dubious ownership“ ab.

```bash
for r in 3D-Racing-Game 3D-Racing-Game-Daten 2D-Racing-Game 2D-Racing-Game-Daten; do
  git config --global --add safe.directory "/Volumes/NAS-Storage/freigabe/Repositories/$r.git"
done
```

**4. 3D-Spiel holen:**

```bash
mkdir -p ~/Projekte && cd ~/Projekte
git clone -o nas /Volumes/NAS-Storage/freigabe/Repositories/3D-Racing-Game.git
cd 3D-Racing-Game
git remote add origin https://github.com/philip-hh00/3D-Racing-Game.git
python3 tools/nas_sync.py holen
```

Der Klon liefert den Code. `holen` packt danach die Daten (rund 1 GB) in
denselben Ordner, das dauert ein paar Minuten.

**5. 2D-Spiel holen:** Das Skript aus dem 3D-Ordner klont den 2D-Code mit.

```bash
python3 ~/Projekte/3D-Racing-Game/tools/nas_sync.py holen \
  --projekt ~/Projekte/2D-Racing-Game --name 2D-Racing-Game
cd ~/Projekte/2D-Racing-Game
git remote add origin https://github.com/philip-hh00/2D-Racing-Game.git
```

## Später: neuen Stand holen

Am PC vorher `sichern` laufen lassen, dann auf dem Mac:

```bash
cd ~/Projekte/3D-Racing-Game && python3 tools/nas_sync.py holen
python3 ~/Projekte/3D-Racing-Game/tools/nas_sync.py holen --projekt ~/Projekte/2D-Racing-Game --name 2D-Racing-Game
```

## Vom Mac zurücksichern

```bash
cd ~/Projekte/3D-Racing-Game && python3 tools/nas_sync.py sichern
```

Das pusht den Code aufs NAS, sichert die Daten und kopiert neue Builds aus
`Release/ausgabe` (also auch einen frisch gebauten Mac-Build) nach
`3D-Racing-Game-Builds`. Code für GitHub weiterhin mit `git push origin main`.

## Mac-Build

```bash
cd ~/Projekte/3D-Racing-Game
./Release/skripte/build_macos.sh
```

Mit dem vollständigen Ordner sind alle Daten da, die der Build braucht. Auf
GitHub fehlen sie: dort fehlen `data/audio`, `data/menu`, `data/textures` und
die Fahrzeugbilder.

## Wichtig

* **Immer erst holen, dann arbeiten, dann sichern.** Ändern Mac und PC
  gleichzeitig dieselben Daten, lässt sich der zweite Stand nicht einfach
  darüberlegen, und `holen` bricht mit einer Meldung ab. Bei Code löst git das
  wie gewohnt per Merge.
* Zugangsdaten (`*token*`, `*.pem`, `id_*`, `.env`) werden bewusst nicht
  gesichert. Sie müssen von Hand auf den Mac.
