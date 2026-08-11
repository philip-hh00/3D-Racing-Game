# GitHub Backup-Anleitung

Diese Anleitung beschreibt, wie du den aktuellen Stand deines Projekts auf GitHub sicherst (Backup), nachdem du Änderungen am Code oder den Konfigurationsdateien vorgenommen hast.

---

## 1. Laufende Backups erstellen (Standard-Workflow)

Wann immer du das Spiel erweitert oder Fehler behoben hast, kannst du die Änderungen mit folgenden drei Befehlen in der Konsole hochladen:

### Schritt 1: Änderungen überprüfen
Zeigt dir an, welche Dateien geändert, gelöscht oder neu erstellt wurden:
```bash
git status
```

### Schritt 2: Dateien für das Backup vormerken
Fügt alle geänderten und neuen Dateien dem nächsten Backup hinzu:
```bash
git add .
```

### Schritt 3: Snapshot beschreiben und speichern
Erstellt einen lokalen Speicherpunkt mit einer kurzen Beschreibung deiner Änderungen:
```bash
git commit -m "Hier beschreiben, was du geändert hast (z. B. Fahrphysik verbessert)"
```

### Schritt 4: Auf GitHub hochladen
Lädt die lokalen Änderungen in dein GitHub-Repository hoch:
```bash
git push
```

---

## 2. Nützliche Befehle

### Letzte Commits (Backup-Historie) ansehen
Zeigt dir eine Liste der letzten Speicherpunkte an:
```bash
git log --oneline -n 10
```

### Änderungen verwerfen (Zurücksetzen)
Falls du dich verbaut hast und zum Zustand des letzten erfolgreichen Commits zurückkehren möchtest:
> [!WARNING]
> Dieser Befehl überschreibt alle ungesicherten lokalen Änderungen unwiderruflich!
```bash
git checkout .
```

---

## 3. Fehlerbehebung

### Fehler: "Updates were rejected because the remote contains work..."
Dieser Fehler tritt auf, wenn du auf der GitHub-Weboberfläche (z. B. direkt in der README) Änderungen vorgenommen hast, die lokal noch nicht vorhanden sind.
* **Lösung:** Hole zuerst die Online-Änderungen ab und lade sie herunter:
  ```bash
  git pull
  ```
  Danach kannst du wieder normal mit `git push` hochladen.
