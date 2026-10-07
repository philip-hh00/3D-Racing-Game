# Plan 1.1.0

Stand 07.10.2026, abgestimmt mit dem Owner. 1.0.1 (Fehlerbehebungen, Fenster
auf dem MacBook) ist davon getrennt und fertig.

## 1. Kameraansichten (Kern von 1.1.0)

Umschaltbar per Taste und Controller, die Wahl bleibt im Profil:

| Ansicht | Inhalt |
|---|---|
| Verfolger fern | heutige Kamera |
| Verfolger nah | zweiter Abstand, tiefer |
| Motorhaube | Kamera auf der Haube, Karosserie sichtbar |
| Cockpit | Sicht vom Fahrersitz, ohne Hände |
| Zurückschauen | eigene Taste, solange gedrückt: Blick nach hinten |

**Cockpit:**
- Das Lenkrad dreht mit dem Lenkeinschlag.
- Echte Instrumente: Tacho und Drehzahl im Armaturenbrett zeigen die
  Fahrzeugwerte. Das HUD blendet im Cockpit dafür seine Rundinstrumente aus.
- Funktionierende Spiegel: Rück- und Außenspiegel zeigen das Feld dahinter
  (zweite Kamera in eine kleine Textur, reduzierte Detailstufe, je nach
  Grafikstufe abschaltbar).

**Assets:** Innenraum, Lenkrad und Armaturen gibt es
(`tools/blender/teile_innen.py`). Nötig sind:
- Augpunkt je Fahrzeug
- Spiegelflächen als eigene Knoten
- Tacho- und Drehzahlnadel als eigene Knoten
- Lenkrad mit Ursprung in der Lenksäulenachse

## 2. Movie-Modus nach der Zieldurchfahrt

- Nach der eigenen Zieldurchfahrt zoomt die Kamera heraus.
- Danach laufen TV-Kameras: feste Punkte an der Strecke, die automatisch
  wechseln und dem nächsten Fahrzeug folgen. Vorbild sind übliche Rennspiele.
- Das läuft, solange die anderen noch fahren. 30 Sekunden, nachdem alle im
  Ziel oder DNF sind, geht es in die Ergebnisübersicht wie bisher.
- Online darf man nicht hängen bleiben: Die Ergebnisse vom Server kommen
  weiter an, der Timer bestimmt nur, wann die Übersicht erscheint.

## 3. Fahrhilfen (ohne Lenkhilfe)

- Ideallinie einblendbar, nach Bremszonen eingefärbt
- ABS
- Traktionskontrolle
- Alle Hilfen sind einzeln in den Einstellungen schaltbar. Die KI ist davon
  unberührt.

## 4. Tageszeit und Wetter

- Tageszeit je Rennen: Tag, Abend, Nacht. Nachts sind die Scheinwerfer und
  Rückleuchten echte Lichtquellen.
- Wetter als zweiter Schritt: Regen mit nasser Fahrbahn (Spiegelung, weniger
  Grip, Gischt).
- Online legt der Gastgeber Tageszeit und Wetter für alle fest.

## 5. Strecken online austauschen

- Spieler laden eigene Strecken aus dem Editor auf den Server hoch.
- Andere durchsuchen die Liste und laden Strecken herunter (Name, Thema,
  Länge, Vorschaubild).
- Offen: Moderation (Namensfilter vorhanden), Speicherplatz auf dem Relais,
  Missbrauchsschutz. Das braucht eine Server-Änderung, also ein Deploy.

## 6. Controller-Vibration

Rumble bei Kontakt, Rutschen, Randstein und Mauer, in der Stärke einstellbar.

## Reihenfolge

1. Kameras und Cockpit (größter Brocken, Blender-Assets)
2. Movie-Modus (nutzt die Kamerainfrastruktur aus 1)
3. Fahrhilfen und Vibration (klein, unabhängig)
4. Tageszeit, danach Wetter
5. Streckenaustausch (Server-Änderung zuletzt, eigenes Deploy)

Online-relevante Änderungen (Tageszeit/Wetter je Lobby, Streckenaustausch)
heben die Version auf 1.1.0 für beide Spiele, wie bei 1.0.1.
