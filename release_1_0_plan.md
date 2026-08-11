# Releaseplan bis 1.0

Ziel: **kostenloses 1.0 auf itch.io**. Zwischenschritt **0.6-beta**, sobald
Fehlerbereinigung und Grand Prix stehen — damit echte Spieler testen, bevor
Sound, Werkstatt und Fortschritt dazukommen.

Stand bei Planerstellung: **0.5.0-beta**, 25.500 Zeilen, 96 Module,
16 Testdateien mit 202 Tests, alle Module importieren fehlerfrei, keine
TODO/FIXME-Marker im Code.

---

## 0. Ausgangslage — was gemessen wurde

> Diese Tabelle ist der Stand bei **Planerstellung (0.5.0-beta)** und bleibt als
> Ausgangspunkt stehen, damit man den Weg noch nachvollziehen kann. Stand
> **31.07.2026** dagegen: 4 Spielmodi auswählbar (Grand Prix inklusive),
> 15 Fahrzeuge, 5 eingebaute Strecken, 2 Musikstücke, **47 Effektdateien**,
> 843 Tests. Was hier als fehlend steht, ist überwiegend erledigt.

| Bereich | Befund |
|---|---|
| Inhalte | 5 Strecken, **15 Fahrzeuge** (5 Klassen × 3 Modelle), Streckeneditor |
| Spielmodi | 3 auswählbar. **Grand Prix ist gebaut, aber nicht in `MODES`** |
| Audio | 2 Musikstücke, **kein einziger Soundeffekt** |
| Profil | nur Benutzername — keine Statistik, kein Fortschritt |
| Übersetzung | 25 `tr()`-Strings ohne englische Fassung |
| Netzwerk | Online-MP läuft, zwei Relays (Helsinki `H`, Hamburg `D`) |
| Absturz | Handler schreibt `crash.log` |
| Auslieferung | Windows-Installer gebaut, macOS-Skript vorhanden (ungetestet) |

### Zwei Falschaussagen auf der itch.io-Seite

`Documentation/ITCHIO_RELEASE.md` beschreibt unter „Game Modes" als Punkt 4
**Grand Prix** — der Modus ist im Spiel nicht auswählbar. Und unter Features
stehen **„5 Unique Vehicles"**, tatsächlich sind es 15. Das erste ist ein
Versprechen, das das Spiel bricht; das zweite verkauft es unter Wert. Beides
gehört korrigiert, sobald die jeweiligen Blöcke fertig sind.

---

## 1. Etappen

Entschieden am **31.07.2026**: **1.0.0 ist die einzige Veröffentlichung.** Alles
davor sind Testbauten für mich und die Bug-Tester, keine Releases. 0.6-beta ist
in diesem Sinn heraus — mit Grand Prix drin — und war nie für die Öffentlichkeit
gedacht.

Das ändert, wie der Plan zu lesen ist: es gibt keine Frist, hinter der etwas
„zu spät" wäre, und keinen Grund, einen Block halbfertig auszuliefern. Was in
einem Testbau noch fehlt, sieht ein Tester und kein Kunde.

### Auf dem Weg zu 1.0.0

| Block | Inhalt | Zustand (05.08.2026, abends) |
|---|---|---|
| B | Grand Prix in allen drei Spielformen | **fertig** |
| G | Streckenvorschläge in der Lobby | **fertig** — Schalter am 05.08. in die GP-Übersicht gezogen (§3a G7) |
| C | Soundeffekte | **fertig** — C7 ist abgearbeitet. Offen ist nur noch die Blocklänge, und die entscheidet das Ohr (§2 A5) |
| D | Werkstatt und Lackierungen | **fertig** — D7 am 05.08.2026 nachgezogen; braucht noch einen Server-Deploy, aber **kein** neues Pflicht-Update |
| E | Statistik und Freischaltungen | **fertig** — E1 bis E5 samt Verschlüsselung (§6) |
| H | Sicherheit von Relay und Netzcode | **fertig** — Stufen 1–5 (§7a); Deploy und Abnahme stehen aus |
| F | Politur und Auslieferung | **fast fertig** (§7) — der Installer ist am 07.08.2026 geprüft; es fehlen nur noch Screenshots und Trailer sowie die itch.io-Seite selbst |

### Was 1.0.0 noch trennt

1. **Server-Deploy und Abnahme** (§7a H9). Block H, D7 (`paint` im Roster) und
   das Leeren der Vorschlagsablage (G7) fahren in **einem** Deploy. Danach
   `python tools/relais_pruefen.py` gegen Helsinki und Hamburg, dann der
   Zwei-Rechner-Test
2. ✅ **Installer geprüft** (07.08.2026). Ein Update über eine bestehende
   Installation lässt Profil und Einstellungen unangetastet — mit E4 der
   wichtigste der drei Fälle, weil ein verschlüsseltes Profil auch unlesbar
   werden könnte statt nur verloren zu gehen
3. **Screenshots und Trailer** (Werkstatt, Grand Prix) und die itch.io-Seite.
   Der **Text** für die Seite steht fertig in `Documentation/ITCHIO_RELEASE.md`,
   deutsch und englisch; einzustellen ist er von Hand
4. ✅ **Menülast am Zielrechner nachgemessen** (07.08.2026): **15 %**, nicht die
   gemeldeten 40–50 %. Die Differenz war der Taskmanager, nicht das Spiel — die
   ~19 %, die die Hintergrundvideos erklären, waren die ganze Zeit die Antwort
   (§2 A5)

Die Hintergrundvideos sind seit dem 05.08.2026 **vollzählig** — `Werkstatt.mp4`
und `Profil.mp4` sind da, und der Test prüft jetzt die Regel statt der Lücke.

**Die Release-Pipeline steht** (06.08.2026). Bis dahin gab es **keine CI** — die
1835 Tests liefen nur, wenn jemand sie startete, und gebaut wurde von Hand.
Jetzt läuft die Suite bei jedem Push, und gebaut wird erst danach:

* `Release/skripte/release_starten.bat` (bzw. `.sh`) setzt einen Tag und pusht
  ihn. Mehr braucht es nicht — kein zusätzliches Werkzeug, nur `git`.
* `v<Version>` → Tests, Windows- und macOS-Build, **Release-Entwurf** mit beiden
  Paketen. `test-<Version>-<Zeit>` → dasselbe, aber die Pakete hängen nur als
  Artefakt am Lauf. Ein Testbuild trägt dieselbe Versionsnummer und darf
  deshalb nichts veröffentlichen, was mit einem echten Release zu verwechseln
  wäre.
* Der Tag wird gegen `src/core/version.py` geprüft. Ohne das entstünde `v1.0.1`
  aus einem Stand, der sich intern `1.0.0` nennt.

Alles Release-Bezogene liegt jetzt in `Release/` mit Unterordnern
(`skripte/`, `pyinstaller/`, `installer/`, dazu die nicht versionierte
`ausgabe/`); Anleitung in `Release/README.md`.

**Dabei zwei Fehler gefunden, die nichts mit dem Umzug zu tun hatten.**
`version.BUILD_DATE` stand auf `date.today()` und wurde beim **Start**
ausgerechnet — ein Spieler sah sein eigenes Tagesdatum als Build-Datum. Jetzt
brennt `tools/baustempel.py` die Bauzeit vor dem Packen ein. Und ein Test fiel
sprunghaft aus, weil die Relay-Hilfe der Netztests beim Herunterfahren offene
Verbindungen mitten in der Arbeit stehenließ, die dann in die Globalen des
nächsten Tests schrieben (siehe `playtest_findings.md`). Für eine Suite, die ab
jetzt Releases freigibt, wäre genau das das Schlimmste gewesen.

**Nach dem Release, nicht davor: der Entwicklungsserver.** Ab dem öffentlichen
Release ist jeder Neustart des Live-Servers ein Eingriff in fremde Rennen. Eine
zweite Instanz trennt „ich probiere etwas aus" von „ich werfe gerade Spieler
heraus". Sie läuft in **Helsinki** (Hetzner-VPS), nicht auf dem Hamburger
Heimserver: Helsinki ist direkt erreichbar und hat freie Ports, Hamburg hängt
hinter playit.gg-Tunneln und bräuchte dort eigene — der einzige nennenswerte
Aufwand an der Sache, und er fällt damit weg. Der Code kann das seit dem
06.08.2026 vollständig
— alle Grenzen und Ports kommen aus der Umgebung, und der Client übernimmt das
Serverkennzeichen jetzt aus `RACE_SERVER_TAG` statt es auf „H" festzunageln.
**Eingerichtet und abgenommen am 07.08.2026** — Rauchtest 9 ok / 0 Fehler, `server_tag = T`, Lobbycode `T9O33L`, UDP-Ping 45 ms. Er liegt als `racing-server-dev` neben dem
Live-Server im Heimatverzeichnis von `gameuser`. Alles Nötige steht fertig in
`Release/dev-server/`: ein `einrichten.sh`, das Klon, Umgebung, Dienst,
sudo-Regel und Firewall in einem Lauf anlegt, und ein Aktualisierer, der nach
`/usr/local/bin/` installiert wird. Vom eigenen Rechner genügt danach ein
Doppelklick auf `Release/skripte/devserver_aktualisieren.bat`.

Drei Entscheidungen dabei, die den Ausschlag geben:

* **Der Aktualisierer liegt außerhalb des Klons.** bash liest ein Skript
  *während* es läuft — läge es im Klon, tauschte ein Pull es mitten im Lauf
  unter dem Interpreter aus.
* **Er setzt hart zurück** und weigert sich, wenn der Zielordner nicht auf
  `-dev` endet. Der Dev-Server soll den Zweig abbilden, nicht einen eigenen
  Zustand pflegen; dasselbe im Live-Ordner wäre ein laufendes Rennen weniger.
* **Die sudo-Regel erlaubt genau einen Befehl**, den Neustart dieser einen Unit.

Betriebsanleitung in `Documentation/DEV_SERVER.md`.

Das Kennzeichen des Dev-Servers ist **T** (H = Helsinki live, D = Hamburg live). Es
steht bewusst nicht im ausgelieferten Katalog: ein Spieler mit einem `T`-Code
liest „Unbekannter Lobby-Code" statt in der Baustelle zu landen. Zwei Tests
halten das fest, dazu einer, der prüft, dass Server und Client dasselbe Zeichen
meinen.

### Laufend, ohne Etappe

* **Block A — Fehlerbereinigung** (§2). Entschieden: **kein Block, sondern
  Dauerzustand.** Fehlerbereinigung hört nicht auf, also gibt es dafür kein
  „fertig" und keinen Platz in einer Etappenliste
* **Playtest-Funde** in `playtest_findings.md` — dieselbe Begründung

---

## 2. Block A — Fehlerbereinigung (laufend)

Entschieden am **31.07.2026**: **kein Block mit Ende, sondern Dauerzustand.**
Fehlerbereinigung hört nicht auf, also steht Block A nicht mehr in der
Etappenliste und blockiert 1.0.0 nicht. A1 und A2 unten sind Zugänge, keine
Lieferung — sie werden benutzt, wenn ein Fund dorthin zeigt.

Stand **05.08.2026 (abends)**: **50 Funde erledigt, 2 offen, 1 bewusst
abgelehnt** (`playtest_findings.md`). Die elf Funde vom 05.08. sind abgearbeitet
— darunter zwei Abstürze, die beide Rückstände derselben Woche waren: eine
querschnittliche Änderung hat je eine Stelle nicht erreicht (`theme` im Editor,
`zurueck_gehen` in der Schale des Rennens). Beides fällt nur auf, wenn man den
Weg wirklich geht; ein Importtest findet keinen davon.

Die Frage, woher der nicht erklärte Teil der Menülast kommt (A5), ist am
07.08.2026 beantwortet: **es gab ihn nicht.** Am Zielrechner gemessen sind es
15 %; die gemeldeten 40–50 % kamen aus dem Taskmanager selbst. Die beiden Hintergrundvideos
sind inzwischen da. Die Installationswarnung ist **bewusst abgelehnt**:
Signaturzertifikate werden nicht gekauft, und damit bleibt die Warnung. Das ist
eine Entscheidung, keine offene Aufgabe.

> **Erledigt am 05.08.2026:** der A2-Punkt „zwei Instanzen gleichzeitig
> starten". Gesperrt wird über das Betriebssystem (`flock`/`msvcrt`) und nicht
> über „Datei vorhanden" — eine solche Sperre hängt am offenen Dateihandle, und
> das schließt das System beim Prozessende selbst, auch nach einem Absturz. Eine
> Existenzprüfung hätte das Spiel nach dem ersten Absturz dauerhaft blockiert,
> ohne dass jemand wüsste, was zu löschen ist. Wo sich nicht sperren lässt,
> startet das Spiel: ein Spiel, das wegen einer Dateisystemeigenheit nicht mehr
> aufgeht, ist schlimmer als der Schreibkonflikt, gegen den gesperrt wird.

Vier Zugänge parallel, wie besprochen.

### A1 Systematischer Code-Audit

Reihenfolge nach Risiko, nicht nach Dateigröße:

1. `race_state.py` (2109 Zeilen) — Zustandswechsel, Rundenzählung,
   Zielerkennung, Splitscreen, Pause, Rückkehr ins Menü
2. `online_lobby_page.py` (1603) — Lobbywechsel, Rollenwechsel,
   Verbindungsabbruch in jeder Phase
3. `editor_state.py` (1590) — Speichern, Laden, ungültige Geometrie,
   Streckenvalidierung
4. `race_manager.py` + `server.py` — Rennablauf, DNF-Fristen, Ergebnisse
5. `car_select_state.py` / `track_select_state.py` — Zustandsrückkehr

Für jede gefundene Lücke ein Test, der sie festhält, bevor sie behoben wird.

### A2 Robustheitstests

Die hässlichen Fälle, die Spieler zuerst finden:

* Controller mitten im Rennen abziehen und wieder einstecken
* Alt-Tab, Fenster minimieren, Auflösung im laufenden Rennen ändern
* Netzwerkkabel im Online-Rennen ziehen (Host und Gast getrennt testen)
* Kaputte, leere und fremde JSON-Dateien in `data/tracks/custom` legen
* Profil mit fehlenden Feldern, `settings.json` gelöscht, Ghost-Datei defekt
* Spiel während des Ladens beenden
* ~~Zwei Instanzen gleichzeitig starten~~ — **erledigt 05.08.2026**, siehe oben

### A5 Zwei Messungen, die eine Entscheidung brauchen

Beide Funde sind bis auf die Wahl durchgearbeitet. Sie stehen hier und nicht in
einem Block, weil sie nichts mit einer Etappe zu tun haben.

**Motorklang, Reststörung „ca. 2× pro Runde" — ✅ behoben am 05.08.2026.** Nicht
die Rechenlast: ein Block kostet 0,27 ms, sechs Stimmen zusammen 1,6 ms je Bild.
Die Enge lag in der Frist. Eine Stimme hält genau **einen** Block vor, weil
pygame nur einen Klang in der Warteschlange annimmt; nachgelegt wird einmal je
Bild, und die Frist ist die Spieldauer eines Blocks — **42,67 ms** bei den
früheren 2048. Das sind bei 60 Bildern 2,56 Bilder Reserve und bei 30 Bildern
nur **1,28**: jedes einzelne Bild über 43 ms riss die Lücke, und eine Lücke
klingt genau wie das gemeldete Knacksen.

`blocklaenge` steht jetzt auf **4096**, die Frist damit auf 85,3 ms — 5,1 Bilder
Reserve bei 60, 2,56 bei 30. Der Preis ist Nachlauf: die Drehzahl folgt dem Bild
um bis zu 85 ms verzögert. Im Fahrzeuglabor gegenzuhören und dort auch
zurückzudrehen; das entscheidet das Ohr, wie schon in C7 festgehalten.

> **Beim Anheben aufgefallen:** `test_tonhoehenversatz_verschiebt_den_klang` fiel
> um. Nicht der Klang — die Zyklusstreuung verschiebt den Schwerpunkt um
> ±30–40 Hz, zwischen Tonhöhe 1,0 und 1,06 liegen aber nur rund 60 Hz. Drei
> Einzelmessungen zu vergleichen war damit ein Münzwurf, der bis dahin nur
> deshalb meist gut ausging, weil die kürzeren Blöcke weniger von der Schwankung
> erfassten. Der Test mittelt jetzt über fünf Ziehungen und prüft den
> Zusammenhang statt einer davon.

**Menü-CPU.** Der Deckel liegt jetzt bei 60 und wirkt nach oben (§7 F2), aber er
ist nicht die Ursache — das sagte die Meldung selbst („selbst wenn ich auf 30FPS
begrenze"). Die Hintergrundvideos sind 1920×1080 mit 30 Bildern und laufen
unabhängig von der Bildrate des Spiels; genau deshalb half die 30er-Grenze nicht.

> **Zahl korrigiert.** Die erste Messung ergab 11,13 ms je Videobild und damit
> 33 % eines Kerns. Sie ist ein **Einzelwert ohne Wiederholung** gewesen und hat
> ihr nicht standgehalten: fünf Läufe zu je 120 Bildern liegen zwischen 3,90 und
> 4,20 ms, Median **3,97 ms**. Die 11,13 waren Messrauschen, kein Befund. Wer
> einmal misst, misst die Maschine mit.

Stand nach der Korrektur und nach dem Sparen der Zwischenkopie:

| Posten | je Bild | je Sekunde |
|---|---|---|
| Dekodieren, Farbumwandlung, Oberfläche | 3,97 ms | 30× → **11,9 %** eines Kerns |
| Zeichnen | 1,14 ms | 60× → **6,8 %** eines Kerns |
| zusammen | | **~19 %** eines Kerns |

Das ist **weniger als die Hälfte** der gemeldeten 40–50 %, das Video erklärt die
Meldung also nicht allein. Was der Rest ist, wäre am laufenden Spiel zu messen
und nicht hier — auf dem Zielrechner, mit derselben Anzeige. Die verbleibenden
Hebel am Video (Auflösung, Bildrate der Clips) ändern das Aussehen und lohnen
bei 12 % nicht, solange der eigentliche Anteil unbekannt ist.

**Umgesetzt wurde nur das Unsichtbare:** die 6,2-MB-Kopie je Bild
(`rgb.tobytes()`) ist weg, pygame liest jetzt direkt aus dem Ergebnis der
Farbumwandlung. Bringt gemessen 0,5–1,5 ms je Bild (11–24 % des Schritts) und
sieht identisch aus. **Auf der GPU läuft nichts** und lässt sich hier auch nicht
erzwingen: `opencv-python` dekodiert über FFMPEG in Software, und eine
angeforderte Beschleunigung (`CAP_PROP_HW_ACCELERATION`) meldet zurück, dass
keine benutzt wird. Selbst wenn sie liefe, müsste das Bild für pygame wieder in
den Hauptspeicher — der Rückweg bliebe.

### A3 Playtest-Meldungen

Du spielst, meldest was auffällt, ich arbeite die Liste ab. Beobachtungen
gehören in `playtest_findings.md` im Repo-Root — kurze Zeile je Fund, Datum,
Modus, was passiert ist. Das ist wertvoller als Chat-Nachrichten, weil es
zwischen den Sitzungen erhalten bleibt.

### A4 Delegation

Kleine, klar umrissene Fixes gehen an `cavecrew-builder`, Hauptthread reviewt
und verifiziert. Alles was mehrere Dateien berührt oder Designentscheidungen
enthält, bleibt im Hauptthread.

---

## 3. Block B — Grand Prix

Der Code steht größtenteils: `grand_prix.py` (127 Zeilen) mit Punktetabelle,
GP-Stepper in Einzelspieler- und Lokal-Lobby, GP-Buttons im Ergebnisscreen.
Es fehlt die Freischaltung und der Online-Teil.

### B0 Bereits behoben

Beim Lesen von `grand_prix.py` gefunden und mit Test behoben: bei
Punktgleichstand brachte ein **Ausfall den Fahrer nach vorn**. Sechster Platz
und DNF teilten sich einen Zähler, und weil alle Zähler absteigend sortiert
werden, gewann bei gleichen Punkten und Siegen, wer häufiger ausgefallen war.
Jetzt getrennt gezählt; Nicht-Teilnahme gilt weder als Platz noch als Ausfall.
`add_race_results` überspringt außerdem beschädigte Ergebniszeilen, weil die
online über das Netz kommen.

### B1 Einzelspieler und lokaler Mehrspieler

* `"Grand Prix"` in `MODES` und `MODES_ENABLED` aufnehmen
* **Streckenwahl vor jedem Lauf einzeln.** Nach jedem Rennen geht es zurück in
  die Streckenauswahl, dort sind die bereits gefahrenen Strecken **markiert** —
  Wiederholungen sind erlaubt, aber nicht versehentlich
* **Eigene Strecken zählen mit**, dadurch reicht der Vorrat meist auch für
  längere Serien. Reicht er nicht, sind Wiederholungen zulässig
* Ergebnisscreen: Zwischenstand nach jedem Lauf, Endstand mit Meister
* Gleichstand: **mehr Siege**, dann mehr zweite Plätze und so weiter
* Sonderfälle: Abbruch mitten in der Serie, Rückkehr ins Menü

### B2 Online — eigene Ebene „Grand-Prix-Übersicht"

**Warum der erste Anlauf nicht trug.** Nach jedem Lauf kehrten alle in die
Lobby zurück. Das war ein Flicken, kein Entwurf: die Lobby ist gebaut, um eine
Runde *einzurichten*, nicht um zwischen Rennen zu stehen. Die Folgen im
Playtest waren keine Einzelfehler, sondern Symptome davon —

* der Serienlängen-Stepper verschwand nach dem ersten Lauf (er wird gesperrt,
  sobald die Serie läuft — richtig für die Lobby, falsch als Zwischenstation)
* die Wertung stand unten rechts, wo gerade Platz war
* der Gast blieb im Renn-Modus, weil sein Ergebnisscreen `grand_prix.is_active()`
  prüft — und nur der Host führt die Serie
* nach „Nächstes Rennen" landeten alle wieder in der Lobby statt im nächsten Lauf

Deshalb bekommt Grand Prix eine **eigene Ebene**.

#### Ablauf

```
Lobby            alle wählen Fahrzeug; Host wählt Anzahl Strecken und Runden
   ↓ Weiter (alle bereit)
GP-Übersicht  ←──────────────────────────────┐
   ↓ Host wählt Strecke, alle bereit         │
Rennen                                        │
   ↓                                          │
Rennergebnis   30 s Countdown im Weiter-Knopf │
   └──────────────────────────────────────────┘
                    nach dem letzten Lauf:
GP-Übersicht → Siegerehrung → Lobby
```

Die Lobby richtet die Serie ein, die Übersicht führt sie. Nach dem Start ist
die Übersicht der Aufenthaltsort bis zum Ende.

#### Aufteilung des Bildschirms

**Links: Strecken.** Scrollbare Kachelliste wie in der bekannten
Streckenauswahl. Jede Kachel zeigt den Streckennamen und darunter den Verlauf
als Umriss. Links neben der Kachel stehen die Daten der angewählten Strecke —
Länge, Schwierigkeit, Checkpoints, Fahrbahnbreite.

**Rechts: Fahrer.** Tabelle mit aktuellem Gesamtstand: Rang, Name, Fahrzeug,
Punkte, Bereit-Zeichen. Darunter der Bereich für den **Streckenaustausch**
(Block G) — vorerst nur reserviert und ausgegraut.

#### Wer darf was

* **Auswählen darf nur der Host.** Gäste dürfen frei blättern und sich Strecken
  ansehen; die tatsächlich gewählte ist getrennt markiert. Angeschaut und
  gewählt müssen optisch klar unterscheidbar sein, sonst hält ein Gast seine
  Ansicht für die Entscheidung
* **Bereit vor jedem Lauf.** Der Host kann nicht allein starten — auch nicht
  nach Ablauf einer Frist
* **Keine Einstellungen aus der Übersicht** (29.07.2026 gestrichen). Video,
  Audio und Steuerung sind vor der Serie und im Renn-Pausemenü erreichbar; ein
  dritter Zugang wäre Aufwand für einen Weg, den in der Übersicht niemand geht
* **Ohne Tab-Leiste.** Die Übersicht ist eine eigene Ebene, keine Menüseite —
  ein Tabwechsel würde die Netzsitzung verwerfen und die Serie beenden. Die
  Shell fragt dafür `Page.hides_tab_bar()`, Zeichnen und Klicks gemeinsam

#### Verlassen

Beide Seiten bekommen vorher eine Warnung:

| Wer | Meldung | Folge |
|---|---|---|
| Host | „Grand Prix wird beendet." | Endstand für alle, danach Lobby |
| Gast | „Deine Wertung geht verloren." | nur er verlässt die Serie |

#### Wiedereinstieg

Wer mitten im Rennen aussteigt, kommt **direkt in die Übersicht** zurück und
sieht den Stand, während die anderen noch fahren; ab dem nächsten Lauf ist er
wieder dabei. Neue Spieler bleiben ausgesperrt (`gp_locked`).

> Das ist die **einzige Serveränderung**: `JOIN` wird heute abgelehnt, solange
> `lobby.state == "racing"`. Für frühere Mitglieder muss das erlaubt werden —
> sie belegen ihren alten Slot wieder und warten in der Übersicht.

#### Rennergebnis

Zusätzlich zu Zeiten und Positionen:

* **Punkte für diesen Lauf** je Fahrer neben der Platzierung
* **Gesamtstand** nach dem Lauf mit Rangänderung
* **Verbleibende Rennen** („Lauf 2 von 5 gefahren")

Der Weiter-Knopf trägt einen **30-Sekunden-Countdown**; wer früher drückt,
wechselt sofort. Das gilt für Host und Gäste gleichermaßen — dadurch bleibt
niemand hängen, weil ein anderer den Bildschirm nicht wegklickt.

Wichtig: dieser Bildschirm muss den Serienzustand aus dem **verteilten** Stand
lesen, nicht aus `grand_prix.current()`. Sonst sieht der Gast weiterhin ein
normales Rennergebnis — genau der Fehler aus dem Playtest.

#### Serienende

Siegerehrung auf der Übersicht, ein Knopf führt alle zurück in die Lobby. Dort
fällt die Sperre weg und die Gruppe kann neu starten.

#### Datenübertragung

Der Serienzustand reist weiter im **vorhandenen Einstellungsblock**
(`SET_SETTINGS` → `lobby.settings` → `LOBBY_STATE`) — Rennnummer, Punkte,
Wertung, gewählte Strecke. Der Bereit-Zustand steckt bereits in `LOBBY_STATE`
(`lobby_ready`). Damit braucht die Übersicht **keine neue Protokollnachricht**;
der Relay bleibt der dumme Relay.


### B3 Was danach stimmen muss

* Online-Lobby zeigt bei GP den Zwischenstand statt der reinen Rundenzahl
* `race_setup` und `grand_prix` dürfen sich beim Moduswechsel nicht in die Quere
  kommen (`grand_prix.cancel()` wird heute an mehreren Stellen gerufen)
* Test: vollständige 3-Rennen-Serie über zwei echte Clients

---

## 3a. Block G — Streckenvorschläge in der Lobby

Bisher kann nur der Host bestimmen, was gefahren wird, und nur seine Strecken
gehen an alle. Künftig darf jeder Spieler eine eigene Strecke in die Lobby
legen; wer will, lädt sie herunter und behält sie.

### G1 Ablauf

1. Der Host schaltet **Streckenvorschläge** frei — **standardmäßig aus**
2. Jeder Spieler kann **eine** Strecke hochladen. Ein neuer Vorschlag ersetzt
   den eigenen alten; fremde bleiben unberührt
3. Vorschläge **bleiben über mehrere Rennen** in der Lobby bestehen
4. In der Vorschlagsliste steht neben jeder Strecke ein **Herunterladen-Knopf**.
   Es gibt **keine Ja/Nein-Freigabe** durch den Host — jeder bedient sich selbst
5. Der Host lädt die Strecke, die er fahren will, herunter und wählt sie danach
   wie jede eigene Strecke aus
6. Beim Rennstart geht sie über den **bestehenden** Übertragungsweg an alle

Wichtig an Punkt 4: nichts landet ungefragt auf einer fremden Platte. Der
Download ist immer ein bewusster Klick.

### G2 Serverseite

Der Relay **hält die Vorschläge für die Lebensdauer der Lobby** vor, damit auch
später Beitretende sie noch bekommen. Genau **ein Platz je Spieler**, ein neuer
Vorschlag überschreibt den alten — dadurch liegt die Obergrenze fest bei
6 Spielern × 1 MB = **6 MB je Lobby**, mehr kann gar nicht entstehen. Beim
Auflösen der Lobby wird alles verworfen.

Das ist die erste Stelle, an der der Relay etwas *behält* statt nur
weiterzureichen. Auf dem Heimserver (5,7 GB RAM) ist das unkritisch, gehört
aber überwacht — die Statusseite zeigt Lobby-Anzahl und Speicherverbrauch
bereits an.

### G3 Ablage beim Empfänger

Empfangene Strecken landen **dauerhaft bei den eigenen Strecken**. Trägt eine
denselben Dateinamen wie eine vorhandene, wird sie **umbenannt** —
`Rundkurs (von Ann).json` — statt zu überschreiben. Nichts Eigenes geht
verloren.

Der Name des Teilenden ist **nur in der Lobby** sichtbar, nicht in der
gespeicherten Datei. Damit bleibt keine dauerhafte Datenspur über andere
Spieler auf fremden Rechnern.

### G4 Sicherheit

Bereits behoben, weil es die Voraussetzung für dieses Feature ist: der
Dateiname empfangener Strecken kam ungeprüft aus dem Netz, ein Name wie
`../../../Startup/x.json` schrieb außerhalb des Streckenordners. Prüfung sitzt
jetzt in `paths.safe_track_filename`.

Damit wächst die Angriffsfläche trotzdem: bisher konnte nur der Host Dateien
verteilen, künftig jeder Spieler. Die drei Schutzlagen:

* **Dateiname** — nur reiner Name, unbedenkliche Zeichen, immer `.json`
* **Größe** — bestehende 1-MB-Grenze gilt auch für Vorschläge
* **Inhalt** — der Streckenlader ist seit Block A robust gegen beschädigte und
  bösartig geformte Dateien; er verwirft, was er nicht lesen kann

### G5 Entschieden am 29.07.2026

* **Ort:** die Liste sitzt im dafür reservierten Feld der Grand-Prix-Übersicht
  (unten rechts). In der Lobby ist neben dem Roster kein Platz, und die
  Übersicht ist ohnehin die Ebene, auf der der Host vor jedem Lauf die Strecke
  wählt. In normalen Online-Rennen gibt es damit keine Vorschläge
* **Quelle:** eigene und geschenkte Strecken (`data/tracks/custom` und
  `data/tracks/online`). Eingebaute bleiben draußen — die hat jeder schon
* **Umbenennen bei Namensgleichheit:** Nummer statt Absendername,
  `Rundkurs (2).json`. So landet kein fremder Spielername dauerhaft im
  Dateisystem; in der Lobby steht weiter, von wem die Strecke kam
* Verhalten, wenn der Host eine Strecke auswählt, die ein Gast **nicht**
  heruntergeladen hat: der bestehende Rennstart-Transfer deckt das ab, der Gast
  bekommt sie dann automatisch

### G6 Umsetzung und Nachweis

Protokoll (getrennt vom Rennstart-Transfer, der nichts davon merkt):

| Nachricht | Richtung | Zweck |
|---|---|---|
| `OFFER_META` / `OFFER_CHUNK` / `OFFER_DONE` | Client → Relay | eigene Strecke anbieten |
| `OFFER_LIST` | Relay → alle | was gerade in der Lobby liegt |
| `OFFER_REQUEST` | Client → Relay | eine davon anfordern |
| `OFFER_DATA_META` / `-CHUNK` / `-DONE` | Relay → Anfragender | die Datei, nur an ihn |

Nachgewiesen in `tests/test_block_g_online.py`: echter Relay auf einem freien
Port, zwei `NetworkClient`-Verbindungen mit je einer Lobbyseite. Geprüft werden
der ganze Weg (freischalten → anbieten → Liste → herunterladen → auswählen →
Rennen fahren) und die Regeln aus G1–G3: ohne Freischaltung kein Vorschlag, ein
neuer ersetzt den eigenen alten, Nachzügler bekommen die Liste, gleicher
Dateiname überschreibt nichts.

### G7 Der Schalter wandert in die Übersicht (05.08.2026)

Gemeldet: der Schalter gehört „eine Seite später", damit der Gastgeber auch
**während** der Serie umlegen kann. In der Lobby war er vor dem Serienstart
einmalig zu entscheiden — G1 Punkt 1 gilt weiter, nur an anderer Stelle.

Er sitzt jetzt oben rechts in der Vorschlagstafel der Grand-Prix-Übersicht,
also dort, wo auch die Liste steht, auf die er sich bezieht. Nach der
Siegerehrung verschwindet er wie Bereit und Start: dort gibt es nichts mehr
vorzuschlagen.

**Ausschalten leert die Ablage.** Das ändert G2: der Relay hält die Vorschläge
nicht mehr bedingungslos „für die Lebensdauer der Lobby" vor, sondern nur
solange der Schalter an ist. Wer wieder einschaltet, fängt bei null an. Der
Grund ist nicht Sparsamkeit allein — eine Liste, die unsichtbar weiterlebt und
beim Wiedereinschalten zurückkommt, wäre eine Überraschung, und die 6 MB je
Lobby lägen sonst für etwas herum, das niemand mehr sehen soll.

Geleert wird dort, wo die Ablage liegt: im Relay, sobald das Flag in
`SET_SETTINGS` fällt. **Braucht einen Server-Deploy** — fährt mit dem für
Block H und D7 mit, ohne eigenen Versionsschnitt.

---

## 4. Block C — Soundeffekte

> **Stand 31.07.2026:** der Weg hat sich geändert. Statt zwei Schleifen zu
> überblenden (C4) laufen jetzt **echte Drehzahlaufnahmen als Schichten** je
> Zylinderzahl — 47 Dateien statt 14, `motor-4zyl-*`, `-6zyl-*`, `-8zyl-*`,
> `-elektro-*`, gebaut in `src/core/sfx.py` und `src/core/sfx_rennen.py`. Die
> Tabelle in C1 und das Verfahren in C4 beschreiben deshalb den **verworfenen**
> Ansatz und bleiben nur als Historie stehen. Was jetzt noch offen ist, steht in
> **C7** am Ende dieses Abschnitts.

Die Sounds sind **selbst erstellt und liegen bereits** in `data/audio/sfx/`
(14 Dateien). Keine Lizenzfrage, kein CC0-Bezug nötig. Die frühere Idee, den
Motor zu synthetisieren, ist damit vom Tisch.

### C1 Bestand und Messung

| Datei | Länge | RMS | Rolle |
|---|---|---|---|
| `car-engine-idle-normal` | 4,35 s | 198 | Leerlauf normal, schleifentauglich |
| `car-engine-max-normal` | 0,38 s | 7679 | Volllast normal, schleifentauglich |
| `car-engine-idle-sport` | 2,32 s | 2629 | Leerlauf sportlich, schleifentauglich |
| `car-engine-reving-sport` | 0,83 s | 4750 | **ansteigender Sweep, keine Schleife** |
| `car-electric-reving` | 3,73 s | 694 | Elektro, schleifentauglich |
| `tire-screeching-1/2` | 1,17 / 1,53 s | 5205 / 1741 | Querschlupf |
| `car-crash-big/small` | 0,94 / 0,34 s | 6934 / 3295 | Fahrzeugtreffer |
| `car-wall` | 0,51 s | 5691 | Wandtreffer |
| `race-start` | 4,05 s | 14563 | Startcountdown |
| `click`, `ui-back`, `fehler` | 0,5–1,0 s | 450–2753 | Menü |

**Zieldurchfahrt und Rundensignal sind bewusst nicht vorgesehen.**

### C2 Pegelangleichung

Zwischen leisestem und lautestem Sound liegt Faktor **74** (Leerlauf normal
RMS 198 gegen Startcountdown RMS 14563). Ohne Angleichung ist der Leerlauf
unhörbar und der Start übersteuert.

Entschieden: **Dateien einmalig neu schreiben** mit angeglichenem Pegel,
Originale wandern vorher nach `data/audio/sfx/original/`. Zielpegel je
Kategorie, nicht global — Motorgeräusche leiser als Aufpralleffekte, weil sie
dauerhaft laufen.

### C3 Zuordnung Motor zu Fahrzeugklasse

| Klasse | Motorsound |
|---|---|
| Kompaktwagen | normal |
| Luxus-Limousine | normal |
| Super Car | sport |
| Drifter | sport |
| Elektro-Prototyp | electric |

### C4 Motorwiedergabe

Grundprinzip: **Leerlauf- und Volllastschleife übereinanderblenden**, Mischung
und Tonhöhe folgen der Drehzahl.

* `car-engine-reving-sport` ist ein Sweep und wird **nicht** geschleift —
  daraus schneide ich das gleichmäßige Mittelstück als Volllastschleife heraus
* Elektro hat keinen eigenen Leerlauf: dort wird die Schleife bei niedriger
  Drehzahl heruntergestimmt und leiser gefahren
* Tonhöhe über Neuabtastung mit `numpy` (bereits Abhängigkeit), Varianten
  werden beim Laden vorberechnet und zwischengespeichert — nicht je Bild

### C5 Fahrzeugindividuelle Färbung — umgesetzt

Zwei Werte je Fahrzeug unter `klang` in der Fahrzeug-JSON, gelesen als
`VehicleConfig.klang_tonhoehe` und `.klang_faerbung`:

* **Tonhöhenversatz** 0,94 bis 1,06, gestaffelt innerhalb der Klasse. Er greift
  auf die Phase, also auf Tonhöhe **und** Wiederholrate — das klingt nach einem
  anders übersetzten Motor, nicht nach langsamer abgespieltem Band. Die
  Schichtwahl bleibt bei der echten Drehzahl, sonst würde ein höher klingendes
  Fahrzeug früher auf die nächste Aufnahme wechseln.
* **Klangfärbung**: gefensterter Tiefpass bei 1800 Hz, dazugemischt (dunkler)
  oder abgezogen (heller). Darunter bleibt der Klang wie aufgenommen, denn der
  Grundcharakter sitzt in den unteren Ordnungen. Bei den Verbrennern trägt sie
  nur die Streuung innerhalb einer Klasse (−0,24 bis +0,45); die Elektros haben
  seit dem 05.08.2026 zusätzlich eine gemeinsame Verschiebung nach dunkel, siehe
  §C5b.

Limousine und Drifter sind gegeneinander versetzt, weil beide aus denselben
Sechszylinder-Aufnahmen kommen — sechs identische Autos wären zu viel.

Zwei Fallen im Filter, beide gemessen abgesichert: der trockene Anteil muss um
die halbe Filterlänge verzögert werden, sonst kämmt die Summe; und die Reste des
letzten Blocks müssen mit, sonst fängt der Filter alle 2048 Samples bei null an.
Der Pegel wird über die wirksame Impulsantwort ausgeglichen, damit aus einer
Klangfarbe keine Bevorzugung wird.

### C5a Elektro-Schichten

`tools/elektro_import.py` baut den Satz `elektro` aus
`car-electric-reving.wav`. Die Datei heißt „reving", ist aber keiner: über ihre
3,7 s bleibt der stärkste Ton bei 867 Hz und wandert nur von 890 auf 850 Hz — was
ansteigt, ist der Pegel. Es gibt also keine Drehzahlleiter zum Schneiden.

Aus der Aufnahme kommt deshalb das Klangbild — die Pegel der Harmonischen
(1× 0 dB, 2× −12,5, 3× −9,0, 4× −15,0) und die Rauschbank darunter, gemessener
Rauschanteil 66 % — die Leiter selbst wird gerechnet: zehn Schichten von 800 bis
16000 U/min, Sirren bei 0,2 × Drehzahl (160 bis 3200 Hz), Pegel −32 bis −17 dB.

Bei einem Verbrenner wäre das falsch; sein Klang lebt von Zündimpulsen, die sich
nicht als saubere Obertonreihe schreiben lassen. Ein E-Antrieb ist genau das.
Die Rauschbank bleibt bewusst in Hertz stehen — mitgezogenes Rauschen klingt oben
nach Zischen statt nach Fahrtwind. Nahtgüte aller zehn Schichten +1,00, weil jede
Teilschwingung eine ganze Zahl Perioden in die Schleifenlänge bekommt.

### C5b Der Elektro fiepte — drei Eingriffe, am Ohr abgenommen (05.08.2026)

Gemeldet: „Motorsound elektrische Fahrzeuge hören sich wie ein Summen und Fiepen
an, ganz unangenehm", nachgeschoben „in den Sounddateien beginnt ab ca. 4 sec der
unrealistische Bereich". Der Zeiger auf die vierte Sekunde war der Schlüssel —
das waren in der Hörprobe genau 6000 UPM.

**1. Akustische Drehzahl** (`sfx.Motorstimme.akustische_drehzahl`). Der Grundton
der Schichten steigt streng mit UPM/5. Ein Verbrenner bleibt durch sein Getriebe
unter der Drehzahlgrenze; der Elektro hat keine Gänge und dreht bis 16000, dort
wären das 3200 Hz — reines Pfeifen. Die Stimme rechnet deshalb mit einer
gebremsten Drehzahl: bis `knie_upm` unverändert, darüber mit `kompression`
gestaucht. Sie greift auf **beides**, Schichtwahl und Abspielrate, sonst liefe
die Aufnahme gegen die Tonhöhe. Der Ton steigt weiter — ein Motor, dessen Ton bei
Vollgas stehen bliebe, klänge tot; er steigt nur nicht mehr ins Pfeifen.

Die Werte stehen in `data/audio/motor_klang.json` und gelten **nur** für den
Elektro (5000 / 0,18). Bei den Verbrennern ist `knie_upm` null, die Formel also
wirkungslos — nicht im Code verdrahtet, sondern aus der Einstellungsdatei
gelesen, und ein Test hält fest, dass es dabei bleibt.

**2. Entrauschen** (`tools/motor_entrauschen.py`). „Hört sich ein wenig so an,
als würden die Sounds in einem Windkanal aufgenommen" — zutreffend und messbar:
der tonale Anteil der Elektro-Schleifen lag bei 20 %. Das Werkzeug schätzt den
Rauschboden als gleitenden Median über einen **vollen periodischen Umlauf** und
zieht ihn spektral ab; danach 87 %. Die Verbrenner lagen schon bei 78–98 % und
blieben unangetastet — dort säße die Zündung selbst im Abzug.

Gelesen wird immer aus `data/audio/sfx/original/`, geschrieben in den Spielsatz.
Ein zweiter Lauf rechnet damit nicht auf einem schon entrauschten Signal weiter,
sondern liefert dasselbe Ergebnis.

**3. Färbung, als Obergrenze übernommen.** Aus drei Hörproben
(`tools/elektro_hoerproben.py`) gewählt: „etwas-dunkler", Färbung +0,30,
spektraler Schwerpunkt 2207 Hz. Entscheidend ist, **wie** die Probe übernommen
wurde: als Deckel, nicht als Mittelwert. Beanstandet war „viel zu hoch und
fiepsig", und ein Fahrzeug heller als das abgenommene Muster fiele wieder in
genau diese Beanstandung. Die Streuung zwischen den drei Elektros geht deshalb
nur nach unten:

| Fahrzeug | Färbung | Schwerpunkt |
|---|---|---|
| electric_3 | +0,30 | 2212 Hz (die abgenommene Probe) |
| electric | +0,45 | 2062 Hz |
| electric_2 | +0,60 | 1911 Hz |

Die Reihenfolge ist dieselbe wie vorher, nur verschoben. Nach unten begrenzt das
die Bauart: der Sechszylinder liegt bei rund 1000 Hz, ein Elektro, der dorthin
rutscht, klingt nach Diesel. Drei Tests halten die drei Bedingungen einzeln fest
— keiner heller als die Probe, alle untereinander unterscheidbar, alle über
1500 Hz.

Was das für §C5 heißt: der frühere Deckel „Färbung im Betrag unter 0,5" ist weg
und durch eine Prüfung der **Spanne innerhalb einer Klasse** ersetzt. Sonst
würde eine gewollte Verschiebung der ganzen Klasse mit der Streuung zwischen
ihren Fahrzeugen verwechselt.

### C6 Ansteuerung — umgesetzt

`src/core/sfx.py` (Bausteine), `src/core/sfx_rennen.py` (Rechnung und
Wiedergabe), Verkabelung in `src/states/race_state.py`.

* Regler „Effekte" in den Audio-Einstellungen, gespeichert im Profil
  (`sfx_volume`), mit hörbarer Vorschau beim Verstellen
* ein Kanal je Fahrzeug, Lautstärke quadratisch abfallend (halb bei 700 px,
  still ab 2600 px), Panorama aus dem x-Abstand; im Splitscreen gewinnt die
  **nähere** Hörposition — addieren würde ein Fahrzeug zwischen beiden Spielern
  lauter machen als eines direkt daneben
* Kanalverwaltung: der leiseste Klang weicht, ein leiserer neuer verdrängt
  nichts; unhörbare Fahrzeuge halten ihren Kanal an, verschwundene geben ihn
  zurück
* Reifenquietschen als Schleife, nur fürs eigene Fahrzeug — als Einzelklang je
  Fahrzeug wird es bei sechs driftenden Autos zum Maschinengewehr
* Aufprall gegen Wand und Fahrzeug, Startsignal am Ende des Countdowns

Drei Funde, die nur beim Verkabeln auffielen:

1. **Der Mixer lief mit 44,1 kHz.** `pygame.init()` startet ihn selbst mit
   Standardwerten; das spätere `mixer.init(48000)` war wirkungslos, und
   `set_num_channels` erreichte nur acht Kanäle — es hätte also gar keinen Kanal
   für einen Motor gegeben. Behoben mit `sfx.mixer_vorbereiten()`
   (`pre_init`) vor `pygame.init()`, plus Neustart als Rückfall.
2. **Ferne Fahrzeuge tragen die `vehicle_id` ihres Absenders** — also 1, wie das
   eigene Auto. Die Kanalzuordnung braucht den Absender im Schlüssel
   (`sfx_rennen.kennung`), sonst übernimmt ein Mitspieler den eigenen Motor.
3. **Nach dem Pausenmenü blieben Fahrzeuge stumm.** Es wird nicht nachgeschoben,
   der Kanal läuft leer und hält an. Die Stimme prüft jetzt `get_busy()` und
   startet neu.

Ein vierter Fund kam aus dem Spiel selbst: der Aufbau stand vor
`self._humans = ...` und lief in jedem Rennen auf einen AttributeError. Er wurde
abgefangen, es blieb also still, und im Terminal stand eine Zeile. Der Aufbau
sitzt jetzt hinter dem Kameraaufbau, und ein Test prüft die Reihenfolge im
Quelltext — eine Prüfung zur Laufzeit hätte genau das nicht bemerkt.

### C7 Was noch offen ist

Stand 31.07.2026, gegen den Code geprüft:

| Offen | Befund |
|---|---|
| **Abstimmung der Motorklänge** | läuft bei dir. Bewusst ohne Kriterium im Plan — das entscheidet das Ohr, nicht eine Zahl. Bekommt mit C8 eine eigene Seite |
| Achtzylinder-Pegel | die Aufnahmen ändern ihren Pegel über die Drehzahl kaum (−19,2 bis −23,4 dB), der Motor wird beim Hochdrehen also nicht lauter |
| ~~`ui-back` unverdrahtet~~ | **erledigt 02.08.2026** — siehe C8, Menügeräusche |
| ~~`tire-screeching-2` unverdrahtet~~ | **erledigt 05.08.2026** — beide Klänge stehen als `REIFENKLAENGE` und wechseln sich ab. Gewechselt wird bei **jeder neuen Drift**, nicht innerhalb einer: mitten im Quietschen zu tauschen wäre ein hörbarer Schnitt |
| ~~`car-electric-reving` unbenutzt~~ | **Befund war falsch** (geprüft 05.08.2026). Die Datei ist im Spiel unbenutzt, aber sie ist die **Quelle**, aus der `tools/elektro_import.py` und `tools/motor_schichten.py` die `motor-elektro-*`-Schichten bauen; die Elektro-Kennwerte in `motor_kennwerte.json` sind ebenfalls an ihr gemessen. Sie bleibt liegen, wo sie liegt — nach `original/` verschoben wären die Werkzeuge kaputt |
| Zieldurchfahrt, Rundensignal | in C1 ausdrücklich **nicht** vorgesehen. Steht hier nur, damit es nicht als Lücke gilt |

### C8 Klang-Seite im Fahrzeuglabor und getrennte Effektregler

Festgelegt im Gespräch vom **02.08.2026**. Anlass: der Motorklang knistert, und
ohne eine Seite zum Hören und Drehen lässt sich nicht herausfinden, woher.

**Woher Knistern kommen kann** — die Seite muss diese fünf unterscheidbar
machen, sonst dreht man am falschen Regler:

1. Übersteuern: die Summe aller Stimmen geht über die Vollaussteuerung, der
   Mixer schneidet ab.
2. Sprünge an den Blockgrenzen alle 2048 Samples (42,7 ms).
3. Leerer Puffer — der Klang reißt kurz ab.
4. Die Aufnahme selbst.
5. Die Überblendung zwischen zwei Drehzahlschichten.

**Entschieden:**

| Punkt | Entscheidung |
|---|---|
| Ort | Eigener Reiter **KLANG** im Fahrzeuglabor, neben LACKIERUNG |
| Umfang | Zwei Ebenen: Werte des **Motortyps** (`4zyl`/`6zyl`/`8zyl`/`elektro`) gelten für alle Fahrzeuge dieser Klasse, darunter die Werte des **einzelnen Fahrzeugs** |
| Wiedergabe | Drehzahlregler von Hand **plus Gangwechsel** — beim Schalten springt die Drehzahl über die echte Übersetzung, wie im Rennen. Kein Sweep, kein Gas-Halten |
| Werkzeuge | Begrenzer (Schwelle, Tempo), Hochpass, Blockgrenzen (Blocklänge, Puffer, Drehzahlglättung), einstellbare Schichtüberblendung |
| Anzeige | Wellenform und Frequenzband. **Kein** Pegelbalken, **kein** Knacks-Zähler |
| Speichern | Motortyp-Werte nach `data/audio/motor_klang.json`; die zwei Fahrzeugwerte bleiben in der Fahrzeug-JSON (`klang_tonhoehe`, `klang_faerbung` stehen dort schon) |

Drei Entwürfe unter `Documentation/entwurf/klang_[ABC]_*.png`, gezeichnet von
`tools/klang_entwurf.py`. Wellenform, Spektrum und Gangsprünge darin sind
**echt** — aus `sfx.Motorstimme` und den Übersetzungen der Fahrzeug-JSON, nicht
gemalt. Das Skript bleibt danach nützlich: eine Änderung an Blende, Blocklänge
oder Färbung lässt sich damit ansehen, ohne das Spiel zu starten.

**Gewählt: Variante C, Signalweg** — umgesetzt am 02.08.2026 als Reiter
`KLANG` (`src/states/klang_labor.py`, Werte in `src/core/motorklang.py`).

Beim Bauen gemessen und daraufhin geändert:

* **Die geplante „Blendkante" ist gestrichen.** Eine Überblendung an jeder
  Blockgrenze verbessert die Naht nicht — sie ist schon glatt, weil Drehzahl
  *und* Schichtgewichte über den Block geführt werden. Gemessen über
  Drehzahlrampe und Gangsprung: Naht 0,0029–0,0039 gegen 0,0053–0,0058
  Bewegung *innerhalb* des Blocks, mit Kante keine Verbesserung, in einem Fall
  minimal schlechter (0,0029 → 0,0032). An ihrer Stelle steht die
  **Drehzahlglättung**: die geführte Drehzahl läuft der gemeldeten über eine
  einstellbare Zeit hinterher, gegen den Gangwechsel.
* Eine „Reserve" von mehr als einem Block in der Warteschlange gibt es nicht —
  pygame nimmt genau einen an, der zweite ersetzt den ersten. Gegen Aussetzer
  bleiben deshalb Blocklänge und Puffergröße.
* **Gefunden: die Färbung knackte bei jedem Motorstart.** Ihr Filterspeicher
  begann mit Nullen; die ersten 16 Ausgaben lagen bei null, dann sprang das
  Signal auf seinen Wert — 0,109 gegen 0,0054 übliche Bewegung, ein Faktor 20.
  Hörbar einmal je Fahrzeug bei jedem Rennstart. Jetzt wird der Speicher mit
  dem ersten Abtastwert gefüllt; der Sprung liegt bei 0,0059 und damit im
  Rauschen. Derselbe Griff beim Hochpass.

**Getrennte Effektregler — umgesetzt am 02.08.2026.** Statt einem Regler
„Effekte" gibt es vier: Musik (Menü), Musik (Rennen), Effekte (Menü), Effekte
(Rennen). Ein Profil von vorher erbt seinen `sfx_volume` in beide neuen Werte.

**Menügeräusche — umgesetzt am 02.08.2026.** Es klingt, was etwas *bewirkt*;
bloßes Bewegen des Fokus bleibt still. Alle Anlässe stehen in
`sfx.MENUE_KLAENGE` an einer Stelle, die Seiten rufen den Anlass, nicht den
Dateinamen:

| Anlass | Datei | wann |
|---|---|---|
| `verstellt` | `click` leise | ein `‹ ›` hat einen Wert geändert |
| `ausgeloest` | `click` | ein Knopf wurde gedrückt (Start, Weiter, OK) |
| `zurueck` | `ui-back` | eine Ebene hoch — Seitenstapel oder `state_machine.zurueck()` |
| `gesperrt` | `fehler` | Klick auf einen gesperrten Knopf |

Dabei gefunden und behoben: `sfx.spielen` fragte Kanal 8–15 an, auch wenn der
Mixer nur acht hat — `pygame.mixer.Channel(8)` wirft dann `IndexError` mitten
im Menü. Vorher fiel das nicht auf, weil nur die Einstellungsseite Klänge
abspielte.


### C9 Störfrequenzen bei mehreren Fahrzeugen — gefunden und behoben

Gemeldet am 02.08.2026: *„die Motoren für sich klingen alle gut, aber immer wenn
ein weiteres Fahrzeug auf dem Bildschirm zu sehen ist, sind die Störfrequenzen
da. Wenn ich ganz alleine fahre, hört sich der Motor gut an."*

**Ursache.** Alle Fahrzeuge einer Klasse spielen dieselbe Aufnahme. Jedes bekam
nach §C5 zusätzlich einen festen Tonhöhenversatz (0,94–1,06) als Charakter. Zwei
Kopien desselben, streng periodischen Signals mit dauerhaft 4 % Unterschied
schweben aber auf **jeder** Ordnung: Ordnung n mit n·Δf. Bei 4000 UPM landen die
Ordnungen 3 bis 17 im Bereich 5–30 Hz — genau dort hört man Schweben als
Flattern. Der Versatz ist fest, also verschwindet die Schwebung auch dann nicht,
wenn zwei Autos exakt gleich schnell fahren.

Gemessen als Hüllkurvenenergie im Band 5–30 Hz, in Prozent des Mittelpegels:

| Fall | Flattern |
|---|---|
| ein Auto allein | 0,9 |
| zwei Autos, Tonhöhenversatz 4 % | **9,1** |
| zwei Autos, gleiche Tonhöhe | 0,9 |

**Was nicht geholfen hat** (alles gemessen, nichts vermutet): das Nachbarauto
leiser stellen (8,8 bei 80 %), ein Tiefpass darauf (9,1 — unverändert, die
Schwebung sitzt in den tiefen Ordnungen), ein anderer Startpunkt in der Aufnahme
(9,0 — Schwebung ist eine Frequenz-, keine Phasenfrage), eine langsam wandernde
Verstimmung (8,9 — verschiebt die Spitze, nicht die Energie) und verschiedene
Ausgangsschichten je Fahrzeug (8,0).

**Behoben** durch die Verlagerung des Charakters von der Tonhöhe in die
Klangfarbe: die Färbung verschiebt keine Frequenzen und kann deshalb nicht
schweben. Alle 15 Fahrzeuge laufen auf `tonhoehe = 1.0`; die Färbung spannt
jetzt −0,45 bis +0,45 statt −0,24 bis +0,22, die bisherige Reihenfolge innerhalb
jeder Klasse bleibt. Ergebnis: zwei Autos flattern so wenig wie eines (0,9), das
ganze Feld aus sechs Fahrzeugen liegt bei 0,75.

Dabei mitgefunden: der Pegelausgleich der Färbung rechnete mit der Filterenergie
und traf damit ein Signal, das über das ganze Band verteilt ist. Ein Motor ist
das nicht — mit der breiteren Färbung unterschieden sich drei Fahrzeuge
derselben Klasse um **Faktor 2,3** in der Lautstärke. Jetzt wird zusätzlich am
laufenden Signal gemessen und langsam nachgeregelt; die Spanne liegt bei 1,00.

Wer den Tonhöhenversatz zurückhaben will, kann ihn im Fahrzeuglabor je Fahrzeug
wieder eintragen — `tests/test_motorklang_ueberlagerung.py` sagt dann mit einer
Zahl, was das kostet.

### C9a Dasselbe noch einmal, diesmal richtig (03.08.2026)

**Im Playtest war nichts besser.** C9 ist damit nicht die Ursache gewesen,
sondern eine richtige Beobachtung am falschen Fall.

**Was der Messung gefehlt hat.** Jede Zahl oben ist mit **derselben Drehzahl**
für beide Fahrzeuge entstanden, 4000 gegen 4000. Genau dort gibt es das Problem
nicht. Im Rennen fährt kein Auto exakt so schnell wie das andere; sobald sich
die Drehzahlen um 200 UPM unterscheiden, schweben die Motoren wieder — ganz ohne
Tonhöhenversatz. Ein Test, der den Betriebsfall nicht nachstellt, kann eine
Behebung bestätigen, die keine ist. Das ist die Lehre, nicht die Zahl.

**Die Ursache.** Jede Schicht ist eine Aufnahme, die als **Schleife** läuft. Eine
Stimme wiederholt sich damit nach einer Schleifenlänge *exakt*: die Ähnlichkeit
mit sich selbst beträgt 1,0000. Kein Motor tut das. Diese Perfektion ergibt ein
Linienspektrum mit messerscharfen Oberwellen, und zwei davon erzeugen eine
saubere, laute Schwebung — bei 4500/4680 UPM auf genau 12,1 Hz, der zweiten
Oberwelle der Zündfrequenzdifferenz. Deshalb hat auch nichts anderes geholfen:
es ist nicht die *gleiche* Aufnahme, es ist die *perfekte*. 4zyl gegen 8zyl
schwebt genauso.

**Die richtige Kennzahl.** Nicht die Energie im Band 5–30 Hz. Die zählt
Schwebungston und breitbandige Rauheit zusammen, und der Eingriff tauscht genau
das eine gegen das andere — zweimal hat diese Zahl deshalb einen richtigen
Eingriff als wirkungslos aussehen lassen. Was zählt, ist die **Höhe der höchsten
Einzellinie** im Hüllkurvenspektrum und ihre **Schärfe** (Linie durch
Bandmittel). Eine Schwebung ist ein Ton: schmal und hoch. Rauheit ist flach.

Zwei Rennfahrzeuge bei 5000/5300 UPM:

| Fall | Linie | Schärfe |
|---|---|---|
| eine Stimme allein | 0,20 | 5,3 |
| zwei Stimmen, ohne Zyklusstreuung | 9,41 | **95,2** |
| zwei Stimmen, mit 0,8 % Streuung | 3,00 | 12,3 |

**Behoben** mit `sfx.Zyklusstreuung`: 0,8 % langsame (1 Hz) Zufallsschwankung
der Rate, je Stimme mit **eigener** Zufallsfolge — zwei Motoren, die identisch
schwanken, wären so streng gekoppelt wie ohne. Damit ist keine Stimme mehr
streng periodisch (Selbstähnlichkeit 1,0000 → unter 0,1), und aus dem Ton wird
die Rauheit, die zwei Motoren nebeneinander eben haben. Über alle Klassen fällt
die Schärfe um Faktor 2,3 bis 22. Gerechnet wird je Block, nicht je Sample: ein
Wert alle 42 ms, linear dazwischen — bei 1 Hz reichlich, und es kostet nichts.

Zwei Regler im Fahrzeuglabor (Station 2, Blockgrenzen): **Zyklusstreuung** und
**Streuungstempo**. Allein zu hören ist davon fast nichts; der Regler zeigt seine
Wirkung erst, wenn ein zweites Auto daneben fährt.

**Der bewusst hingenommene Preis.** Bei *exakt* gleicher Drehzahl schwanken die
beiden unabhängigen Streuungen gegeneinander, die Linie steigt dort von 0,36 auf
2,95. Gemessen und gewollt: der Fall kommt im Rennen praktisch nicht vor, und
3 % breitbandige Rauheit ist harmlos gegen 13 % als Ton bei 20 Hz.

**Ausnahme von „Vorgabe = bisherige Wirkung"** (§C8): hier greift die Vorgabe
ein, weil die bisherige Wirkung der Fehler war.

### C9b Auch das war es nicht — und was der Ausschluss wert ist

**Im Playtest war wieder nichts besser.** Dazu ein Befund, der mehr sagt als
alles vorher: eine Hörprobe mit **vier** Motoren, offline zusammengerechnet,
klingt für den Spieler *sauber*. Zusammen mit „ein Auto allein im Spiel klingt
gut" heißt das:

> Die Überlagerung der Motorklänge ist **nicht** die Ursache. Bewiesen war nie
> mehr als die Gleichzeitigkeit — die Geräusche kommen, sobald ein zweites
> Fahrzeug hörbar wird. Das ist eine Korrelation mit „mehr als eine Stimme
> spielt", nicht mit „die Wellenformen addieren sich".

Am 03.08.2026 gemessen und damit ausgeschlossen:

| Verdacht | Messung | Ergebnis |
|---|---|---|
| Übersteuerung beim Mischen | Summenspitze bei 1–6 Fahrzeugen | 0,23–0,62, nie über 1,0 |
| Schwebung zwischen zwei Stimmen | Linie und Schärfe im Hüllkurvenband | behoben (C9a), Geräusch bleibt |
| Treppe der Lautstärke je Bild | größter Sprung gegen Signalsteilheit | 0,035 gegen 0,024 üblich, keine Linie bei 60 Hz |
| Rechenzeit der Blöcke | `block()` + `make_sound` je Stimme | 0,34 ms je 42,7 ms Audio, 5 % bei sechs Fahrzeugen |
| Pegelsprung der Färbung an Blockgrenzen | Naht gegen Signalsteilheit | Verhältnis 0,71–1,01, kein Ausreißer |

**Zwei echte Unstetigkeiten** sind dabei aufgefallen und behoben — nicht als
Behauptung, sie seien der gemeldete Fehler, sondern weil ein Sprung im Pegel
immer ein Knacks ist:

* `daempfung` sprang an der Hörweite von **0,063 auf 0** — und ein Fahrzeug
  pendelt in einem Rennen dauernd um diese Grenze. Das letzte Viertel wird jetzt
  ausgeblendet. Das eigene Auto hat Entfernung null und kennt den Fall nicht,
  was genau zu „allein klingt es gut" passt.
* `stille()` hielt den Kanal mit `stop()` an, also mitten in der Welle. Jetzt
  eine 60-ms-Blende.

**Was bleibt, ist am Schreibtisch prinzipiell nicht messbar:** die Wiedergabe
selbst. Der Mixer läuft auf einem 512-Sample-Puffer (10,7 ms), die
Warteschlange hält genau einen Block vor, und ob sie rechtzeitig gefüllt wird,
entscheidet die Bildrate auf dem Rechner des Spielers. Nichts davon existiert in
einer Offline-Rechnung.

Deshalb steht dort jetzt ein Messgerät statt einer weiteren Vermutung:
`src/core/klangmitschnitt.py`, **F9 im Rennen** (nur aus dem Quelltext
gestartet). Er schreibt mit, was das Spiel dem Mixer vorlegt, und rekonstruiert
daraus eine WAV — plus einen Bericht mit der einen Zahl, die keine Rechnung
liefern kann: **wie oft ein Kanal leergelaufen ist**, dazu die Bildzeiten.

* klingt der Mitschnitt sauber und das Rennen nicht, liegt es an der Wiedergabe —
  Puffergröße, Blocklänge, Kanalzahl
* klingt er genauso falsch, liegt es im Signal, und dann liegen die Daten vor

**Die Lehre für den Plan.** Zwei Runden sind an derselben Stelle verlorengegangen:
gemessen wurde, was sich leicht messen ließ, nicht der Betriebsfall. Beim ersten
Mal war es die gleiche Drehzahl, beim zweiten Mal die feste Lautstärke und die
Färbung auf null. Eine Messung, die den Betriebsfall nicht nachstellt, kann jede
Behebung bestätigen.

### C9c Gefunden: der Mixerpuffer war zu klein

**Behoben am 04.08.2026.** Puffer 512 → 2048 Samples, und die Störgeräusche sind
weg. Es war nie eine Frage des Signals.

Der Weg dorthin, weil daran mehr hängt als die eine Zeile:

**Der Mitschnitt aus einem echten Rennen** (20 s, vier Stimmen) hat bewiesen,
dass das Spiel dem Mixer ein einwandfreies Signal vorlegt — auf dem Rechner des
Spielers, in seinem Rennen:

| Messung | Wert |
|---|---|
| leergelaufene Kanäle | **0** |
| Bildzeit, Mittel / schlechteste | 12,6 / 21,0 ms, keine über 42,7 |
| Summenspitze | 0,2242, **0** übersteuerte Samples |
| Sprünge über 8× dem Üblichen | **0** |
| Blockgrenzen gegen Blockinneres | Faktor 0,99 — nicht auffindbar |
| Linie bei Block-/Bild-/Pufferrate | ≤ 2,6×, absolut 0,2–0,65 % |

Dazu die Korrektur des Spielers, die die ganze Annahme kippte: *„auch wenn keine
weiteren Fahrzeuge neben mir waren"*. Damit war die Beobachtung vom 02.08. („nur
wenn ein zweites Fahrzeug zu sehen ist") widerlegt — und drei Untersuchungen
waren ihr gefolgt.

Übrig blieb die Ausgabe selbst: 512 Samples sind bei 48 kHz ein Termin von
10,7 ms für den Audio-Rückruf. Wird er verpasst, klingt genau das nach Knistern,
und zwar unabhängig davon, wie viele Fahrzeuge fahren. Ein Motorklang braucht
keine 10 ms Latenz — die Blöcke sind ohnehin 42,7 ms lang. Verstellbar bleibt der
Wert im Fahrzeuglabor (Reiter KLANG, Station 2, „Puffer"; wirkt nach einem
Neustart).

**Die Lehre, drei Runden teuer.** Gemessen wurde jedes Mal, was sich leicht
messen ließ, nicht der Betriebsfall — erst gleiche Drehzahl für beide Autos, dann
feste Lautstärke und Färbung auf null. Und die erste Frage hätte lauten müssen:
*passiert es auch allein?* Eine gemeldete Korrelation ist eine Vermutung des
Melders, keine Messung; sie gehört als erstes geprüft, nicht als Voraussetzung
übernommen.

**Was aus C9 und C9a bleibt.** Beide Eingriffe waren gemessen richtig und bleiben
drin, auch wenn sie den gemeldeten Fehler nicht waren:

* die **Zyklusstreuung** (0,8 %) gegen die Schwebung zweier Motoren bei
  unterschiedlicher Drehzahl — Schärfe der Schwebungslinie 95,2 → 5,3. Wem der
  Motor ohne besser gefällt: Regler im Labor auf 0, dann ist der Stand von vor
  dem 03.08. wieder da
* das **Ausblenden an der Hörgrenze** statt eines Sprungs von 0,063 auf null, und
  die **Blende statt `stop()`** beim Verlassen der Hörweite

**Die Diagnosewerkzeuge sind wieder ausgebaut** (`klangmitschnitt`, Klangprobe
F9/F10). Sie haben ihre Frage beantwortet; im Spiel haben sie danach nichts mehr
zu suchen, und ein Werkzeug, das niemand mehr benutzt, veraltet still. Was sie
gemessen haben, steht hier.

### C9e Der Motorklang läuft auf einem Audiofaden (06.08.2026)

C9d endete mit „das Spiel liefert sauber ab, es liegt an der Ausgabe". Das
stimmte gemessen und war trotzdem die falsche Schlussfolgerung. Die Beobachtung,
die es gedreht hat: **über Monitorlautsprecher jede Sekunde ein Aussetzer**,
über Kopfhörer zwei je Runde. *Regelmäßig* heißt, dass zwei Uhren gegeneinander
laufen und ein Vorrat regelmäßig aufgebraucht wird — und der Vorrat war unserer.

**Was falsch gebaut war.** Der Motorklang wurde **geschoben**: einmal je Bild
ein Block, und `pygame.mixer` nimmt genau einen in die Warteschlange. Damit hing
der Ton am Bildtakt, und der Vorsprung war ein einziger Block. Auf dem
Entwicklungsrechner reichte das knapp, auf fremder Hardware nicht.

So baut das kein Spiel, das überall laufen soll. Der übliche Aufbau ist
umgekehrt: der Treiber **ruft ab**, wenn er Ton braucht, auf seinem eigenen
hochpriorisierten Faden, und dazwischen liegt ein Ringpuffer mit Vorrat. Frame
drops, Ladepausen, Garbage-Collector — nichts davon erreicht dann den Ton.

**Warum nicht mit pygame.** `pygame.mixer` hat keinen Rückruf für selbst
erzeugten Ton. Nachgesehen an pygame-ce 2.5.7: es gibt dort schlicht keine
solche Funktion. Deshalb PortAudio über `sounddevice`.

**Der Aufbau, in zwei Teilen.**

| Modul | Aufgabe | Prüfbar ohne Gerät |
|---|---|---|
| `src/core/tonmischer.py` | Ringpuffer, Stimmen, Lautstärkeverläufe, Unterlauf | **ja**, vollständig |
| `src/core/tonausgabe.py` | Gerät öffnen, Erzeugerfaden, Rückfall | die Hälfte, die entscheidet |

Die Trennung ist der Kern: der heikle Teil ist der Ring, nicht die Soundkarte —
und der ist so vollständig nachstellbar. 20 Tests decken ihn ab, darunter der
Fall, um den es geht: ein Unterlauf darf **nicht knacken**. Statt auf null zu
springen läuft der letzte Wert über 64 Abtastwerte aus, gemessen bleibt der
größte Sprung unter 0,02.

**Drei Fäden, klar getrennt.** Der Spielfaden setzt Werte und wartet nie. Der
Erzeugerfaden füllt den Ring. Der Audiofaden kopiert — und **nur** das: keine
Synthese, keine Sperre, kein Warten. Was dort hängt, hört man sofort. Zwei Tests
halten die Regel fest, einer davon, indem er die Sperre des Mischers hält,
während abgerufen wird.

**Der Vorrat ist ein Abwägen** und steht auf 4096 Abtastwerten = 85 ms: fünf
Bilder Reserve bei 60 Bildern je Sekunde. Weniger reisst Löcher, mehr lässt den
Motor hinter dem Gaspedal herhinken.

**Der Rückfall ist kein Beiwerk.** `sounddevice` braucht PortAudio; unter Windows
und macOS liegt es im Rad bei, sonst nicht immer. Lässt sich kein Faden öffnen,
meldet `starten()` schlicht `False` und `sfx_rennen` benutzt weiter den alten
Weg über pygame — lieber der bisherige Klang als gar keiner. Beide Wege haben
dieselbe Schnittstelle, und ein Test hält das fest. Der Rechner der Testsuite
hat kein PortAudio, der Rückfall ist dort also der Normalfall und damit die
ehrlichste Prüfung, die es dafür gibt. Der echte Weg wird mit einem
eingeschobenen Gerät geprüft, vom Erzeuger bis in den Puffer des Treibers.

**Was bleibt wie es war.** Menüklänge, Reifen und Aufpralle laufen weiter über
`pygame.mixer` — sie werden als fertige Klänge abgespielt und haben das Problem
nie gehabt. Nur der Motorklang wird Block für Block erzeugt, nur er brauchte den
Umbau. Die Ringstimmen belegen dabei **keinen** Mixerkanal mehr, die bleiben
jetzt ganz für die übrigen Klänge frei.

**Im Mitschnitt steht jetzt, welcher Weg lief** — Gerät, Rate, Vorrat,
Unterläufe. Ohne das wäre bei der nächsten Meldung nicht zu unterscheiden, ob
der Faden lief und trotzdem gestört hat oder ob er gar nicht zustande kam. Zwei
völlig verschiedene Ursachen.

### C9f Gerätewechsel im Betrieb (06.08.2026)

Der Umbau auf den Audiofaden hat eine Lücke aufgemacht, die pygame vorher
zugedeckt hatte: wird das Ausgabegerät im Betrieb umgestellt, zog der Menüklang
mit, der Rennklang blieb zurück.

Der Grund liegt in den Wegen, nicht in einem Fehler. SDL öffnet das
**Standardgerät als solches**, und Windows verschiebt so einen Strom beim
Umschalten von selbst mit. PortAudio löst beim Öffnen auf einen **konkreten**
Endpunkt auf und bleibt dort.

Behoben mit einer Wache: einmal je Sekunde wird nachgesehen, wie das
Standardgerät gerade heisst; ändert sich der Name, wird der Strom neu geöffnet.
Gefragt wird SDL, das ohnehin läuft — `SDL_GetDefaultAudioInfo` über `ctypes`,
weil pygame die Funktion nicht durchreicht.

**Das Angenehme kommt aus dem Aufbau von C9e.** Der Mischer besitzt die
Stimmen, nicht das Gerät. Das Gerät lässt sich deshalb *unter* ihnen
austauschen: keine Stimme wird neu angelegt, keine Drehzahl geht verloren, nur
der Ton setzt für den Moment des Umschaltens aus. Genau dafür war die Trennung
gedacht, auch wenn dieser Fall beim Entwurf noch nicht auf dem Tisch lag.

Zwei Vorsichtsmaßnahmen: die Wache läuft im schon vorhandenen Erzeugerfaden mit
(ein zweiter Faden wäre ein zweiter Ort zum Aufräumen), und wenn SDL die
Auskunft auf einem Rechner nicht gibt, hält sie **still** statt zu raten — dann
bleibt es beim bisherigen Verhalten, aber nichts geht kaputt. Im Mitschnitt
stehen das erkannte Standardgerät und die Zahl der Wechsel.

### C9d Der Rest der Störgeräusche liegt nicht mehr bei uns (05.08.2026)

Der Puffer von C9c hat den größten Teil beseitigt, nicht alles: *„die anderen
Störsounds während des Rennens sind noch unverändert da"*, gezählt etwa zweimal
je Runde. Diese Zeile hält fest, wie die Suche geendet hat — und was daran
**meine** Fehldiagnose war.

**Die Blocklänge war es nicht.** Am 04.08. stand hier die Erklärung, eine Stimme
halte nur einen Block vor, und bei 2048 Samples (42,67 ms Frist) reiße jedes Bild
über 43 ms eine Lücke. Die Rechnung stimmt, sie beschreibt nur nicht diesen Fall:
gemessen sind **0** Bilder über der Frist, bei einer schlechtesten Bildzeit von
22,98 ms. Die Frist war nie eng. Die Umstellung auf 4096 bleibt trotzdem stehen —
mehr Reserve schadet nicht, und der Nachlauf von bis zu 85 ms ist beim
Gegenhören nicht aufgefallen.

**Drei weitere Verdachte, ausgemessen und ausgeschlossen:**

| Verdacht | Messung | Ergebnis |
|---|---|---|
| Nähte an den Blockgrenzen | Sprung an der Naht gegen übliche Bewegung im Block | Faktor 0,7–0,8, auch mit Schaltvorgängen — die Naht ist *ruhiger* als das Blockinnere |
| Lautstärkestufen je Bild | Überholvorgang mit 400 px/s Relativtempo | höchstens 0,022 je Bild, für ein Knacken um Größenordnungen zu klein |
| Kanaldiebstahl durch Einzelklänge | Kanalbereiche von Stimmen und Einzelklängen | getrennt, kann konstruktiv nicht passieren |

**Der Mitschnitt hat es entschieden.** `src/core/klangmitschnitt.py` wurde für
diese eine Frage wieder eingebaut (F9 im Rennen) und zählt genau den Wert, den
keine Rechnung liefern kann: wie oft eine Stimme beim Nachlegen einen
**stehenden** Kanal vorgefunden hat. Aus einem Rennen mit **2 gehörten**
Störungen:

| Messung | Wert |
|---|---|
| gehörte Störungen | 2 |
| gezählte Aussetzer | **1** — und der auf dem ersten Block einer Stimme, wo der Kanal noch nicht laufen *kann* |
| Bilder über der Nachlegefrist | **0** |
| Bildzeit, schlechteste / Frist | 22,98 ms / 85,33 ms — Faktor 3,7 Reserve |
| Summenspitze | 0,4912, kein NaN, keine Übersteuerung |
| Sprünge über 8× dem Üblichen, **im Block** | **0** (Median 0,0237, Maximum 0,0439) |

Damit gilt der zweite der beiden Fälle, die vor der Messung aufgeschrieben
waren: **null echte Aussetzer, trotzdem Störungen** → das Spiel liefert sauber
ab, und die Störung entsteht erst in der Ausgabe (Treiber, Puffer der
Soundkarte, Abtastratenwandlung). Im Spiel ist an dieser Stelle nichts mehr zu
reparieren. Die einzige verbliebene Stellschraube ist der Mixerpuffer, und der
steht seit C9c auf 2048; er lässt sich im Fahrzeuglabor weiter anheben, wenn es
auf einem Rechner nötig sein sollte.

**Eine Grenze des Werkzeugs, damit sie niemand übersieht:** die mitgeschriebene
WAV hängt die Blöcke *aller* Stimmen hintereinander, statt sie zu summieren. Zum
Abhören taugt sie nicht, und die 802 großen Sprünge an ihren Nahtstellen sind
Schnitte zwischen verschiedenen Motoren, keine Fehler im Signal. Aussagekräftig
sind der Bericht und das Blockinnere. Der Mitschnitt bleibt vorerst liegen —
ausgeschaltet kostet er nichts, die Rennschleife fragt vorher `laeuft()`, und ein
Test hält das fest. Ausgebaut wird er auf Zuruf, so wie die Werkzeuge nach C9c.

---


## 5. Block D — Werkstatt und Lackierungen

Entschieden: **Grundfarben frei, Speziallacke freischaltbar.** Werkstatt kann
nur die Lackierung wählen.

Der Entwurf unten ist am **30.07.2026** im Gespräch festgelegt worden. Wo eine
Entscheidung eine frühere Annahme dieses Plans umstößt, steht das ausdrücklich
dabei — sonst liest sich in drei Wochen niemand mehr zusammen, warum es anders
gekommen ist.

### D0 Was beim Lesen des Codes vorher gefunden wurde

**`color_primary` ist bei allen 15 Fahrzeugen wirkungslos.** `VehicleRenderer`
(`renderer.py:45`) lädt zuerst `data/vehicles/<Visual_Type>.png`; nur wenn keine
Datei da ist, fällt er auf das programmatische Zeichnen zurück — und *nur* dort
wird `color_primary` überhaupt benutzt. Seit alle 15 PNGs existieren, läuft jede
Farbzuweisung ins Leere. Drei Stellen glauben trotzdem, sie täte etwas:

| Stelle | Absicht | tatsächliche Wirkung |
|---|---|---|
| `race_state.py:706` / `:1956` | KI-Gegner in drei Farben unterscheidbar machen | keine — alle KI-Autos sehen identisch aus |
| `ghost.py:129` | Ghost grau abheben | keine — der Ghost sieht aus wie ein Mitfahrer |
| `minimap.py:134` | Punktfarbe = Fahrzeugfarbe | Punkt zeigt den JSON-Vorgabewert, nicht das, was man sieht |

Das ist ein echter Fehler und ein wirklich verlockender Beifang: sobald die
Umfärbung steht, wären alle drei mit wenigen Zeilen behoben. **Entschieden:
gehört trotzdem nicht in Block D.** Block D liefert die Spielerlackierung, sonst
wächst er unkontrolliert. Die drei Punkte wandern als Funde nach
`playtest_findings.md` und werden dort einzeln entschieden.

Weiter gemessen: die Sprites sind **2760×1504 bis 2816×1536 px** (die
`_2`/`_3`-Modelle rund 1700×920) und werden zur Laufzeit auf ~26×54 px
skaliert. Der Drehteller der Fahrzeugauswahl rechnet dagegen mit dem
ungeskalierten Original. Beides gilt auch für die Umfärbung — sie muss am
Original passieren, nicht am Rennsprite, sonst ist die Vorschau matschig.

### D1 Aufbau einer Lackierung

Entschieden: **Grundfarbe × Finish**, nicht eine flache Liste fertiger Lacke.
Freigeschaltet wird das **Finish**, die Farben sind alle von Anfang an frei.

| Eintrag | Anzahl | Freischaltung |
|---|---|---|
| **Werkslack** | 1 | immer, Vorbelegung |
| Standard × 12 Farben | 12 | immer |
| Metallic × 12 Farben | 12 | Block E: 10 Rennen gefahren |
| Neon × 12 Farben | 12 | Block E: 10 Siege |
| Zweifarbig × 12 Farben | 12 | Block E: eigenen Ghost auf 3 Strecken geschlagen |

49 Einträge, davon 13 sofort verfügbar — bei nur **drei** Freischaltbedingungen.
Genau das war der Grund für dieses Modell: viel Auswahl, wenig Buchhaltung.

**Werkslack ist ein eigener Eintrag, keine Kombination.** Es ist das
unveränderte PNG, wird nie umgefärbt und bleibt Vorbelegung für jedes Fahrzeug.
Zwei Gründe: niemand sieht sein Auto nach dem Update plötzlich anders, und es
gibt immer einen sauberen Rückfall für ein Fahrzeug, dessen Umfärbung noch nicht
abgestimmt ist.

#### Kennung einer Lackierung

Ein Text, weil er im Profil und über das Netz reisen muss und dabei lesbar
bleiben soll:

```
"werk"                    Werkslack
"standard:kobaltblau"     Finish : Farbschlüssel
"metallic:rubinrot"
"neon:limettengruen"
"zweifarbig:perlweiss"
```

Unbekannte Kennung — alter Build, verstümmelte Netznachricht, von Hand
verbogenes Profil — wird zu `"werk"`. Nie ein Absturz, nie ein leeres Auto.

#### Die zwölf Grundfarben

Liegen in einer eigenen Datei `data/vehicles/lacke.json`, nicht im Code, damit
du sie ohne mich ändern kannst:

| Schlüssel | Name | RGB |
|---|---|---|
| `rubinrot` | Rubinrot | 200, 30, 40 |
| `signalorange` | Signalorange | 240, 110, 20 |
| `sonnengelb` | Sonnengelb | 240, 200, 40 |
| `limettengruen` | Limettengrün | 140, 200, 50 |
| `waldgruen` | Waldgrün | 30, 130, 70 |
| `tuerkis` | Türkis | 20, 180, 180 |
| `eisblau` | Eisblau | 90, 170, 230 |
| `kobaltblau` | Kobaltblau | 30, 70, 190 |
| `violett` | Violett | 120, 60, 190 |
| `magenta` | Magenta | 210, 50, 150 |
| `anthrazit` | Anthrazit | 55, 58, 65 |
| `perlweiss` | Perlweiß | 235, 238, 240 |

Zwölf sind so gewählt, dass sie ohne Scrollen in eine Spalte passen und
paarweise klar unterscheidbar bleiben. Anthrazit und Perlweiß sind absichtlich
unbunt dabei — sie sind die beliebtesten Autofarben und der Grund für die
Trennung im nächsten Abschnitt.

#### Was die vier Finishes rechnen

Die Zahlen dahinter stehen ebenfalls in `lacke.json` und sind von Hand
nachjustierbar. Kein Bildmaterial, keine zusätzlichen Dateien.

| Finish | Rechnung |
|---|---|
| **Standard** | nur der Farbauftrag aus D2, sonst nichts |
| **Metallic** | die Helligkeit innerhalb der Lackfläche wird um den Mittelwert gespreizt (`L' = 0,5 + (L − 0,5) · k`, `k ≈ 1,6`). Reflexe treten härter, Kanten setzen sich ab — der Lack wirkt hart und glänzend statt flach |
| **Neon** | Sättigung der Zielfarbe auf Maximum, dazu ein **Saum**: Lackpixel, die an einen Nicht-Lackpixel grenzen (2–3 px am Originalmaßstab), werden um Faktor ≈ 1,4 aufgehellt. Das Auto bekommt eine leuchtende Kante |
| **Zweifarbig** | **geometrischer Streifen entlang der Längsachse.** Innerhalb der Lackfläche bekommt ein Band von ≈ 22 % der Fahrzeugbreite (in `lacke.json` einstellbar) die Zweitfarbe |

Zur Achse: die PNGs liegen im Querformat, und `renderer.py:85` skaliert auf
`(height_px, width_px)` — also ist Bild-**X** die Fahrzeuglänge und Bild-**Y**
die Fahrzeugbreite. Ein Rallye-Streifen von der Nase zum Heck läuft damit entlang
X und sitzt mittig in Y. Dieselbe Regel gilt für alle 15 Fahrzeuge; es braucht
keine Handarbeit je Fahrzeug.

Ein Detail, das die Entwurfsbilder gezeigt haben: das Band muss auf dem
**Schwerpunkt der Maske** sitzen, nicht auf der halben Bildhöhe. Bei Fahrzeugen
mit hohem Heckflügel — Drifter MK2 — verschiebt der Flügel den Zuschnitt, und
ein auf die Bildmitte gerechneter Streifen läuft dann sichtbar neben der
Karosseriemitte.

Woher die **Zweitfarbe** kommt, war nicht Teil der Entscheidung — im Modell
„Farbe × Finish" wählt man nur eine Farbe. Meine Festlegung, überstimmbar: der
Streifen ist automatisch **Perlweiß oder Anthrazit**, je nachdem was mehr
Kontrast zur gewählten Grundfarbe hat. Damit bleibt die Auswahl einfach und der
Streifen immer sichtbar.

Verworfen: Metallic mit überlagerter Flitter-Textur. Bei 26×54 px im Rennen ist
davon nichts zu sehen, und für die Werkstattvorschau allein rechtfertigt es keine
zusätzliche Textur.

### D2 Umfärbung — zwei erprobte Verfahren

#### Klarstellung, die den Rest erst zusammenhält

Der frühere Wortlaut dieses Abschnitts hat zwei Dinge in einen Topf geworfen.
Getrennt sind sie:

* **Maske finden** — welche Pixel sind Lack? *Hier* unterscheiden sich die
  beiden Verfahren.
* **Farbe auftragen** — was passiert mit diesen Pixeln? Das ist **immer
  dasselbe**, unabhängig vom Verfahren.

Warum das wichtig ist: „Farbtondrehung" (Verfahren 1 im alten Wortlaut) kann
Sättigung nicht erzeugen. Anthrazit und Perlweiß wären damit unerreichbar — eine
Farbtondrehung an einem roten Auto ergibt nie Grau. Sobald man das Auftragen vom
Finden trennt, spielt das keine Rolle mehr: die Zielfarbe wird immer auf die
vorhandene Helligkeitsverteilung gelegt, und unbunte Zielfarben funktionieren
genauso wie bunte.

**Der Farbauftrag, für alle Verfahren und alle Fahrzeuge gleich.** Je Pixel mit
Maskengewicht `w` (0…1):

1. `L` = Helligkeit des Originalpixels, normalisiert am 5.- und 95.-Perzentil
   *der Maskenfläche* — nicht des ganzen Bildes, sonst verschiebt der
   Hintergrund die Skala
2. `neu = Zielfarbe · (0,45 + 1,1 · L)`, kanalweise auf 0…255 begrenzt.
   Damit bleiben Reflexe hell und Schattenkanten dunkel; die Form des Autos
   überlebt die Umfärbung
3. Finish-Nachbearbeitung aus D1 anwenden
4. `ergebnis = w · neu + (1 − w) · original` — weiche Maskenränder gehen
   dadurch fließend über, statt zu treppen

**Maskenfindung, Verfahren 1: Sättigungsschwelle.** Pixel unter einer Schwelle
(Ausgangswert 25 %) gelten als „nicht Lack". Gemessenes Ergebnis über alle 15:

| Ergebnis | Fahrzeuge |
|---|---|
| **funktioniert** | Rookie, Supercar, Supercar_2, Supercar_3, Drifter |
| **Schwelle je Fahrzeug nötig** | Drifter_2, Drifter_3, Electric, Electric_2, Limousine, Limousine_2, Limousine_3 |
| **scheitert** | Rookie_2, Rookie_3, Electric_3 |

**Maskenfindung, Verfahren 2: dominante Farbe plus Toleranz.** Die häufigste
Farbe im Bild ist die Karosserie; alles farblich Nahe gehört zur Maske. Das
greift auch bei unbunten Karosserien, wo eine Sättigungsschwelle nichts findet.

Die Messung zeigt, woran Verfahren 1 scheitert — die dominanten Farben sind
unbunt:

| Fahrzeug | dominante Farbe | Maskenabdeckung |
|---|---|---|
| Rookie | (247,37,40) rot | 64,7 % |
| Rookie_2 | (90,90,89) **grau** | 94,3 % |
| Rookie_3 | (222,224,225) **weiß** | 98,5 % |
| Electric_3 | (40,43,52) **fast schwarz** | 98,6 % |
| Drifter_2/_3 | (38,37,37) **fast schwarz** | 87,6 / 91,4 % |

Abdeckungen über 90 % sind ein Warnzeichen: bei einem grauen Auto zählt die
Maske die grauen Scheiben und Reifen mit. Ein grauer Wagen mit grauen Scheiben
lässt sich durch **keine** Farbschwelle von seinen eigenen Fenstern trennen —
identische Farben sind identisch. Was dort hilft, ist das
**Helligkeitsfenster**: Scheiben sind meist deutlich dunkler oder heller als das
Blech.

#### Nachmessung am 30.07.2026 — das Helligkeitsfenster trägt weiter als gedacht

Beim Zeichnen der Entwurfsbilder ist das Verfahren an echten Sprites gelaufen.
Ergebnis für **Rookie_2**, den Wagen, den die Tabelle oben mit 94,3 % als
Problemfall führt: mit Referenzfarbe (90, 90, 89), Toleranz 0,20 und
Helligkeitsfenster 0,14 … 0,86 fällt die Abdeckung auf **72,4 %**. Die Scheiben
bleiben dunkel, die Rückleuchten bleiben rot, umgefärbt wird nur das Blech.

Die gemessenen 94,3 % kamen offenbar **ohne** Helligkeitsfenster zustande. Damit
ist „drei Fahrzeuge scheitern" keine gesicherte Erwartung mehr, sondern eine
offene Frage für Rookie_3 (weiß) und Electric_3 (fast schwarz) — bei denen das
Fenster weniger hergibt, weil Blech und Glas näher zusammenliegen. Die
Entscheidung fällt weiter an der Sichtprüfung (D6), aber der Ausgangspunkt ist
deutlich besser als der ursprüngliche Wortlaut behauptet.

#### Was bei mehrfarbig beklebten Fahrzeugen passiert

Ebenfalls an den Entwurfsbildern aufgefallen und keine Fehlfunktion, aber eine
Erwartung, die festgehalten gehört: bei Fahrzeugen mit aufgedruckter Grafik —
Drifter MK2 hat violette Streifen, die `_2`/`_3`-Modelle generell mehr Livery —
fasst die Maske nur die **Grundfläche**. Das Auto wird also nicht einfarbig, es
bekommt eine neue Grundfarbe **unter** seiner Grafik. Bei Perlweiß fällt das am
stärksten auf.

Das sieht meist gut aus und ist billiger als jede Alternative. Es heißt aber:
die Lackierung ist bei diesen Fahrzeugen ein Farbwechsel, keine Neulackierung.
Wenn dir das an einem bestimmten Fahrzeug nicht gefällt, ist die Livery über die
Farbtoleranz mit einzufangen — dann verliert sie ihre eigene Farbe.

#### Zwischenspeicher und Arbeitsbreite

Entschieden: **nur im Arbeitsspeicher**, gerechnet beim Laden. Kein Ablegen auf
der Platte.

* Umgefärbte Fassungen entstehen beim Betreten der Werkstatt bzw. beim Rennstart,
  liegen unter Schlüssel `<visual_type>|<lackkennung>|<breite>` und verschwinden
  mit dem Prozess
* **nie je Bild** — bei 2816×1536 px wäre das ein sofortiger Einbruch der
  Bildrate

**Gemessen am 30.07.2026, und es korrigiert diesen Plan an einer Stelle.** Eine
Umfärbung in **Originalauflösung kostet 3,9 s** für den Supercar (2319×1037 px
freigestellt). Bei sechs Fahrzeugen wären das 23 s Rennstart — ausgeschlossen.
Die Aussage „Vorschau in Originalauflösung des Sprites" in D4 ist damit
gestrichen. Gerechnet wird auf einer verkleinerten Arbeitskopie, deren Breite der
Verwendungszweck bestimmt:

| Zweck | Breite | Kosten je Fahrzeug | gezeichnet wird mit |
|---|---|---|---|
| Rennen, Fahrzeugauswahl, Kacheln | 512 px | ~16 ms | ≤ 90 px |
| Werkstattvorschau | 1024 px | ~115 ms | ~900 px |
| Laborvorschau | 640 px | ~50 ms | ~590 px |

Das Labor rechnet absichtlich schmaler als die Werkstatt: dort bewegt man Regler,
und 115 ms je Bewegung fühlen sich zäh an. Die Maskenkriterien sind Farb- und
Helligkeitsschwellen und damit unabhängig von der Größe; nur die
**Kantenweichheit wirkt in Pixeln** und fällt in der Werkstatt entsprechend
schmaler aus als im Labor eingestellt.

Zwei Dinge in der Rechnung waren nach der ersten Messung die Bremse und sind
behoben: der Kastenfilter für weiche Kanten legte 25 Vollbild-Arrays an
(jetzt separabel über Teilsummen, `O(n)` statt `O(n·k²)`), und `umfaerben` las
die Oberfläche **viermal** aus — zweimal selbst, zweimal über `maske`. Beides
zusammen war ein Drittel bis Neunzehntel der Zeit.
* Kein Ungültigwerden, kein Aufräumen, keine verwaisten Dateien nach einer
  Laboränderung. Der Preis ist eine kurze Rechenzeit beim Öffnen der Werkstatt;
  das ist an dieser Stelle vertretbar, weil niemand mitten im Rennen lackiert

Verworfen: Plattencache im Benutzerordner. Er hätte eine Kennung aus Fahrzeug,
Lack *und* Laborparametern gebraucht, sonst hängt nach jeder Abstimmung ein
alter Sprite fest — Aufwand und Fehlerquelle für einen Ladevorgang, der ohnehin
nur einmal je Sitzung anfällt.

### D3 Lackier-Seite im Fahrzeuglabor

Entschieden: die Abstimmung passiert **im Spiel**, nicht in einem
Bildbearbeitungsprogramm. Das Fahrzeuglabor
(Einstellungen → Dev-Mode → Fahrzeug-Labor, `vehicle_lab_state.py`) bekommt eine
zweite Seite. Es ist der richtige Ort: es lädt schon alle 15 Fahrzeuge, blättert
mit `TAB` / `[` `]` durch, speichert mit `S` nach `data/vehicles/<key>.json` und
kennt das Muster „Regler links, Auswirkung rechts" bereits von der Motorkurve.

#### Was einstellbar ist

Verfahrenswahl und Zahlenregler — kein Pinsel, keine Maus-Pipette, keine
Sperrflächen. Bewusst der kleinste Satz, der die beiden gemessenen Verfahren
vollständig bedient:

| Regler | Bereich | Wirkung |
|---|---|---|
| **Verfahren** | `saettigung` / `dominant` / `aus` | welche Maskenfindung gilt; `aus` heißt: nur Werkslack |
| Sättigungsschwelle | 0,00 – 1,00 | Verfahren 1: ab wann ein Pixel als Lack gilt |
| Referenzfarbe | aus dem Bild ermittelt, per Regler je Kanal korrigierbar | Verfahren 2: welche Farbe die Karosserie ist |
| Farbtoleranz | 0,00 – 1,00 | Verfahren 2: wie weit von der Referenz noch dazugehört |
| Helligkeit min / max | 0,00 – 1,00 | **beide Verfahren**: schließt zu dunkle und zu helle Pixel aus — der Hebel gegen mitgezählte Scheiben und Reifen |
| Kantenweichheit | 0 – 4 px | weicher Maskenrand, gegen Treppenstufen an der Karosseriekante |
| Deckkraft | 0,00 – 1,00 | wie stark der neue Lack das Original überdeckt |

#### Vorschau

Entschieden am **30.07.2026** anhand von drei gezeichneten Varianten. Gewählt ist
**Variante B**: **Regler links, vier Felder rechts** —
**Original | Maske | Ergebnis | Helligkeits-Histogramm**.

Die Maske als Schwarzweißbild sichtbar zu machen ist der eigentliche Grund für
diese Seite. Am Ergebnis allein sieht man, *dass* etwas falsch ist; an der Maske
sieht man *warum* — dass die Scheiben mitgezählt werden, dass die Kotflügel
fehlen, dass ein Reflex ein Loch reißt. Ohne diese Mitte rät man.

Das vierte Feld ist der Zusatz gegenüber dem ursprünglichen Entwurf und der
Grund für die Wahl: ein **Histogramm der Helligkeit aller sichtbaren Pixel**, in
dem farblich hervorgehoben ist, welche davon in der Maske landen, mit den zwei
Fenstergrenzen als senkrechte Linien. Damit wird das Helligkeitsfenster —
derjenige Regler, an dem die unbunten Fahrzeuge hängen — **steuerbar statt
geraten**: man sieht, wo die Scheiben als eigener Berg liegen und wohin die
Grenze gehört. Wegen der starken Häufung bei einfarbigen Autos wird die Höhe als
**Wurzel** aufgetragen, sonst ist außer einem Balken nichts zu erkennen.

Verworfen: die reine Dreiteilung ohne Histogramm (der Entwurf; man stellt das
Helligkeitsfenster blind ein) und ein großes Einzelbild mit der Maskengrenze als
farbige Linie darüber (sehr gut ablesbar, wo die Grenze falsch läuft — aber ohne
Anhaltspunkt, wohin der Regler soll).

#### Bedienung

Auch hier **Stepper und Schaltflächen statt Tastenkürzel**, aus demselben Grund
wie in der Werkstatt:

* drei Stepper oben in der linken Spalte: **Fahrzeug**, **Zielfarbe**, **Finish**
  — damit ist die vollständige Sichtprüfung aus D6 ohne gemerkte Tasten möglich
* je Reglerzeile **zwei eigene Pfeilknöpfe** rechts, zum Feinstellen mit der Maus
* **„Speichern"** (primär) und **„Verwerfen"** (sekundär) als Knöpfe am Fuß der
  Spalte, statt `S` und einem Hinweis darauf

Die vorhandenen Tastenwege des Labors (`TAB`, `[` `]`, `S`, `F1`) bleiben
funktionsfähig — sie werden nur nicht mehr als einzige Bedienung vorausgesetzt
und nicht mehr in der Kopfzeile erklärt.

#### Wo die Werte landen

Entschieden: **in der bestehenden Fahrzeug-JSON**, in einem neuen Block `paint`.
Eine Datei je Fahrzeug, gespeichert mit `S` wie alles andere im Labor.

```json
"paint": {
  "verfahren": "dominant",
  "saettigungsschwelle": 0.25,
  "referenzfarbe": [247, 37, 40],
  "farbtoleranz": 0.18,
  "helligkeit_min": 0.05,
  "helligkeit_max": 0.95,
  "kantenweichheit": 1.5,
  "deckkraft": 1.0
}
```

**Fehlt der Block, gilt `verfahren: "aus"`** — das Fahrzeug bietet nur Werkslack.
Damit ist der heutige Stand (kein Fahrzeug hat den Block) automatisch der
unkritische Ausgangszustand, und die Werkstatt lässt sich schon bauen und
ansehen, bevor ein einziges Fahrzeug abgestimmt ist.

### D4 Werkstatt-Seite

#### Ort im Menü

Entschieden: **sechster Tab „WERKSTATT", links neben „EINSTELLUNGEN"**, plus ein
Kurzweg aus der Fahrzeugauswahl. Reihenfolge damit:

```
EINZELSPIELER | MEHRSPIELER LOKAL | MEHRSPIELER ONLINE | STRECKENEDITOR | WERKSTATT | EINSTELLUNGEN
```

Der Tab muss sichtbar sein, sonst wirkt die Freischaltung nicht als Anreiz — ein
gesperrter Lack, den niemand findet, motiviert niemanden. Eine Unterseite der
Einstellungen wäre dafür zu tief versteckt. „Einstellungen" bleibt der letzte
Eintrag, weil dort niemand die Werkstatt sucht und die Leiste sonst ihre
gewohnte Endposition verliert.

Zur Geometrie: `_tab_rects` rechnet heute mit `tw=300, gap=8`, also
5 × 300 + 4 × 8 = **1532 px**. Sechs Tabs ergeben 6 × 300 + 5 × 8 = **1840 px**
und passen bei `SCREEN_WIDTH = 1920` noch mit 40 px Rand. Das ist knapp,
besonders für längere englische Beschriftungen — deshalb geht `tw` auf **288 px**
(6 × 288 + 5 × 8 = 1768 px, 76 px Rand). `theme.text_fit` fängt zu lange Texte
ohnehin ab. Dazu kommt ein Hintergrund `data/menu/Werkstatt.png`; fehlt er,
zeichnet die Shell schon heute einen Verlauf, es bricht also nichts.

**Kurzweg:** Knopf „Lackieren" in der Fahrzeugauswahl, der die Werkstatt mit dem
gerade angewählten Fahrzeug öffnet und danach **dorthin zurückkehrt, wo er
hergekommen ist** — Einzelspieler-Lobby, lokale Lobby oder Online-Lobby, jeweils
mit unveränderter Fahrzeug- und Streckenwahl. Das ist der fummelige Teil: die
Rückkehr läuft über `state_machine.transition("menu", reopen=...)`, und die
Fahrzeugauswahl kennt drei verschiedene Rückwege (`car_select_state.py:173`).
Der Kurzweg merkt sich seinen Ursprung und gibt ihn unverändert zurück.

#### Aufteilung — „Auto zuerst"

Entschieden am **30.07.2026** anhand von drei gezeichneten Varianten. Gewählt ist
**Variante B**: das Fahrzeug nimmt zwei Drittel der Fläche, die Flotte läuft als
Streifen darunter. Verworfen wurden die Dreispalten-Aufteilung des früheren
Entwurfs (Liste | Vorschau | Lacke — vertraut, aber die Vorschau bleibt klein)
und ein „Lackregal", das alle 48 Kombinationen gleichzeitig am eigenen Fahrzeug
zeigt (bester Überblick, kostet aber genau die Vorschaugröße, um die es hier
geht).

* **Bühne, links oben.** Fahrzeugname groß, darunter die aktuelle Lackierung.
  Die Vorschau ist **groß, stehend, von oben** (1024-px-Arbeitskopie, siehe D2).
  Kein selbstlaufender Drehteller — bei Metallic und beim Streifen will
  man ein stehendes Bild betrachten können, und ein Auto, das sich gerade
  wegdreht, wenn man hinsehen will, ist ärgerlich
* **Bedienleiste am Fuß der Bühne**, weil das alles Aktionen am *gezeigten* Auto
  sind: zwei Drehknöpfe unter der Beschriftung „DREHEN", „Ansicht zurück",
  „Werkslack"
* **Schiene rechts.** Finish als **Stepper** (`‹ Neon ›`) mit der
  Freischaltbedingung als Zeile darunter, dann die zwölf Grundfarben als
  Klickfelder, darunter der Name der gewählten Farbe
* ~~**Schiene unten** ein reservierter, ausgegrauter Abschnitt „Titel"~~ —
  **gestrichen am 31.07.2026**, weil E3 (Titel) aus Block E herausgefallen ist.
  Der Kasten ist gebaut und wird wieder entfernt; der Platz geht an die
  Farbfelder. Ein Platzhalter für etwas, das nie kommt, ist genau die Art
  Versprechen, die §0 dem itch.io-Text vorwirft
* **Flottenstreifen unten.** Je Fahrzeug eine Kachel mit echtem Sprite in der
  *gewählten* Lackierung und deren Namen darunter — damit sieht man den eigenen
  Bestand auf einen Blick. Geblättert wird über zwei Knöpfe an den Enden,
  gewählt per Klick auf die Kachel

Bietet ein Fahrzeug nur Werkslack (`verfahren: "aus"`), steht anstelle der
Farbfelder ein Satz dazu. Nach D6 soll dieser Fall am Ende nicht mehr auftreten
— aber solange abgestimmt wird, ist er der Normalzustand und darf nicht wie ein
Fehler aussehen.

#### Bedienung: Schaltflächen, keine Tastenhinweise

Entschieden: **jede Bedienung ist sichtbar und anklickbar.** Die Fußzeile mit
Tastenhinweisen (`↑↓ Fahrzeug   TAB Finish   ESC Zurück` …) entfällt in der
Werkstatt **ganz**.

| Was | Bedienelement |
|---|---|
| Finish wechseln | `Stepper` (`widgets.py:109`) — `‹ Neon ›` |
| Grundfarbe | Klick auf das Farbfeld |
| Fahrzeug wechseln | Klick auf die Kachel; Blättern über zwei Pfeilknöpfe an den Enden des Streifens |
| Auto drehen | zwei Pfeilknöpfe, darüber die Beschriftung „DREHEN" |
| Ansicht zurücksetzen | `Button`, sekundär |
| Auf Werkslack zurück | `Button`, sekundär |
| Zurück | `Button` „‹ Zurück" oben links |

Tastatur und Controller funktionieren weiter über die vorhandene
Fokus-Verwaltung (`src/ui/focus.py`) — es gibt nur keinen Text mehr, der sie
erklären muss. Das ist derselbe Ansatz wie in den Lobbys, wo Stepper und Knöpfe
sich selbst erklären.

> **Fallstrick, gemessen:** die gebündelte Schrift (`data/fonts/segoeui.ttf`)
> kennt **`↺ ↻ ⟲ ⭯ ◀ ▶ ✓`** nicht und zeichnet dafür ein leeres Kästchen. Der
> Kommentar in `theme.py` nennt nur `★` und `✓` als Lücke; `◀ ▶` und die
> Drehpfeile fehlen ebenfalls. Vorhanden und benutzbar sind
> **`‹ › « » ● ▲ ▼ ♦ √`**. Die Drehknöpfe tragen deshalb `‹ ›` mit der
> Beschriftung „DREHEN" darüber, nicht die naheliegenden Drehpfeile.

#### Wo die Lackierung sonst sichtbar wird

Entschieden: **nur in der Fahrzeugauswahl** — der Farbstreifen an der Kachel und
das Auto auf dem Drehteller zeigen die gewählte Lackierung statt der JSON-Farbe.
Plus natürlich das Auto im Rennen selbst.

Ausdrücklich **nicht**: Minimap-Punkt, Farbfeld in Lobby und Ergebnisliste,
HUD-Akzente. Der Rennbildschirm ist gerade aufgeräumt worden (drei Funde vom
29.07.), da kommt jetzt keine neue Farbe hinein.

### D5 Profil

`Profile` bekommt ein Feld `paints`: Fahrzeugschlüssel → Lackkennung.

```json
"paints": {
  "rookie": "werk",
  "supercar": "metallic:kobaltblau",
  "drifter_2": "neon:limettengruen"
}
```

* fehlender Eintrag → `"werk"`. Ein Profil ohne den Block — also jedes heute
  existierende — lädt damit unverändert und steht auf Werkslack
* die Auswahl gilt **je Fahrzeug**, nicht global: wer den Drifter neongrün mag
  und die Limousine anthrazit, bekommt beides
* gespeichert wird sofort bei der Wahl, wie bei allen anderen Profilfeldern
  (`save()` nach jeder Änderung)
* `Profile.load` liest über `data.get(...)` mit Vorgabewert und ist in
  `try/except` gewickelt — die Migration braucht deshalb keinen eigenen Code,
  nur einen Test, der sie festhält (D7)

Für Block E ist eine Funktion `ist_freigeschaltet(lackkennung) -> bool`
vorgesehen, die in Block D **immer `True`** liefert. Block D liefert die
Werkstatt mit allen Finishes offen; Block E füllt genau diese eine Funktion und
schaltet damit die Ausgrauung scharf. Damit kannst du die Werkstatt vollständig
sehen und beurteilen, bevor die Statistik existiert.

### D6 Sichtprüfung

Entschieden: **kein Kontrollblatt.** Die Sichtprüfung läuft vollständig auf der
Lackier-Seite im Labor — Fahrzeug, Farbe und Finish über die drei Stepper
durchblättern (D3). Verworfen: ein Skript in `tools/`, das PNG-Bögen erzeugt, und
eine HTML-Seite.

Das hat eine Folge, die ich benennen muss: es gibt damit **nichts, was ich dir
zum Kommentieren hinlegen kann.** Die Abnahme der Umfärbung passiert an deinem
Rechner, im laufenden Spiel, von dir. Ich kann Zahlen melden
(Maskenabdeckung je Fahrzeug), aber kein Bild.

Genau hier fällt auch die **offene Entscheidung** aus D2: reichen die Regler für
Rookie_3 und Electric_3? Rookie_2 ist nach der Nachmessung vom 30.07. keiner
mehr. Der Ablauf ist festgelegt, das Ergebnis nicht:

1. Ich baue Verfahrenswahl und Regler, einschließlich Helligkeitsfenster
2. Du gehst im Labor alle 15 Fahrzeuge durch und stimmst sie ab
3. **Erst wenn dort eines wirklich durchfällt**, kommt ein weiteres Werkzeug
   dazu — kein Pinsel auf Vorrat

Die beiden Wege für diesen Fall, damit die Entscheidung dann schnell geht:

| Weg | Aufwand | Was er löst |
|---|---|---|
| **Ausschlussrechtecke** — 2–3 rechteckige Sperrflächen je Fahrzeug, als Zahlen in der `paint`-Block | klein, keine neuen Dateien | Scheiben sitzen bei einer Draufsicht zusammenhängend in der Mitte; ein Rechteck darüber genügt meist |
| **Pinsel und Radierer** — Maskenkorrektur mit der Maus, Ergebnis als Graustufen-PNG je Fahrzeug | groß, 15 zusätzliche Dateien möglich | löst jeden Fall, auch unzusammenhängende Flächen |

Mein Rat, wenn es dazu kommt: erst Rechtecke. Sie sind bei Draufsichten fast
immer genug, und ein Pinsel, den man einmal hat, wird für jedes Fahrzeug benutzt,
auch wo Regler gereicht hätten.

### D7 Online

Entschieden: die Lackierung reist **im TCP-Roster**. **Keine Änderung am
UDP-Format.**

Das stellt den früheren Wortlaut dieses Abschnitts richtig. Dort stand ein
zusätzliches Byte in `VEHICLE_FMT` — 29 → 30 Byte je Fahrzeug, eine echte
Protokolländerung mit angehobener `required_version`. Das war falsch gedacht:
**die Lackierung ändert sich während eines Rennens nie.** Sie in 60 Positions-
paketen pro Sekunde mitzuschicken wäre Verschwendung und würde Kompatibilität
kosten, ohne etwas dafür zu bekommen. Sie gehört zum Spieler, nicht zur Position
— also dorthin, wo Name, Fahrzeug und Team schon stehen.

Der Weg ist kurz. Heute schickt der Client `PICK` mit `vehicle` und `team`; der
Server legt das unter `lobby.settings["picks"][slot]` ab und kopiert es in jeden
`LOBBY_STATE`. Es kommt ein Feld dazu:

| Stelle | Änderung |
|---|---|
| Client, `PICK` | zusätzliches Feld `paint` mit der Lackkennung |
| `server.py:590` | `"paint": msg.get("paint")` in den `picks`-Eintrag |
| `server.py:390` | `"paint": picks.get(str(c.slot), {}).get("paint", "")` in den Spielereintrag |
| Client, `LOBBY_STATE` | Lackkennung je Slot lesen und beim Rennstart auf das Fernfahrzeug anwenden |

Zwei Zeilen im Relay, und ein **Server-Deploy** ist damit nötig — §8 hat den für
Block D ohnehin vorgesehen. Aber `required_version` bleibt, wo sie ist, weil es
in beide Richtungen sanft ausgeht:

* **alter Server, neuer Client:** das `paint`-Feld fällt weg, alle sehen
  einander im Werkslack. Kein Absturz, kein Fehler, nur weniger Farbe
* **neuer Server, alter Client:** ein unbekanntes Feld mehr im `LOBBY_STATE`,
  das er nicht liest. `payload.py` verwirft ohnehin nur Unbrauchbares und gibt
  nie auf
* **unbekannte Lackkennung** (Peer mit anderer `lacke.json`): fällt nach D1 auf
  `"werk"` zurück

Verworfen: die oberen vier Bit des vorhandenen Fahrzeugtyp-Bytes für eine
KI-Lackierung mitzubenutzen (15 Typen brauchen nur 4 Bit). Da die KI beim
Werkslack bleibt (D0), gäbe es dort heute nichts zu übertragen — reservierte
Bits ohne Inhalt sind ein Rätsel für den, der das in zwei Jahren liest. Sollte
die KI später Farben bekommen, wird das dann entschieden.

> **Nachtrag 05.08.2026.** Die KI hat Farben bekommen (Fund vom 30.07.), und es
> ist trotzdem kein Feld im Protokoll geworden: die Lackierung hängt allein an
> der **Fahrzeugnummer** (`lack.ki_lack`), und die ist auf beiden Seiten
> dieselbe. Gastgeber und Gegenstelle rechnen unabhängig und kommen auf dasselbe
> Ergebnis. Ein übernommenes Auto (`TAKEOVER_ID_BASE + Platz`) behält die
> Lackierung seines ausgestiegenen Fahrers — auch die steht schon im
> Lobbyzustand. Übertragen wird also weiterhin nur, was ein *Mensch* gewählt
> hat.

> **Nachtrag 06.08.2026 — zurückgenommen.** Die KI fährt wieder Werkslack, auf
> Wunsch. Lackierungen sind das, was der Spieler sich erarbeitet und in der
> Werkstatt aussucht; an jedes Feld von Gegnern verteilt verlieren sie ihren
> Wert. Für das Protokoll ändert das **nichts**: es gab nie ein Feld dafür, und
> die Zusage „beide Seiten rechnen dasselbe aus" hält weiterhin, jetzt eben
> trivialerweise. Der Absatz darüber gilt damit wieder wie ursprünglich
> geschrieben. Bewusst in Kauf genommen ist, dass mehrere KI-Autos derselben
> Bauart wieder gleich aussehen — ein Test hält genau das fest, damit beim
> nächsten Playtest niemand denselben Fund noch einmal aufmacht.

### D8 Was Block D ausdrücklich nicht enthält

Damit später nicht die Frage aufkommt, ob es vergessen wurde:

| Nicht enthalten | Warum |
|---|---|
| KI-Gegner in Farbe | D0 — echter Fehler, ging als eigener Fund nach `playtest_findings.md`; **dort am 05.08.2026 behoben** |
| Ghost entfärben oder durchscheinend machen | ebenso |
| Minimap-Punkt in Lackfarbe | ebenso |
| Farbfeld in Lobby, Ergebnisliste, HUD | D4 — der Rennbildschirm bleibt, wie er gerade aufgeräumt wurde |
| Splitscreen: zwei gleiche Autos auseinanderhalten | getrennte Bildhälften zeigen jedem sein eigenes Auto mittig; Verwechslung ist selten genug |
| Freischaltbedingungen, Statistik, Zähler | Block E. `ist_freigeschaltet()` liefert vorerst immer `True` |
| Titelauswahl | **entfällt ganz** — E3 ist am 31.07.2026 gestrichen worden. Der reservierte Platz wird zurückgebaut |
| Kontrollblatt als Datei | D6 — Sichtprüfung läuft im Labor |
| Plattencache für umgefärbte Sprites | D2 — Arbeitsspeicher genügt |
| Flitter-Textur für Metallic | D1 — bei 26×54 px nicht sichtbar |
| Felgen, Startnummern, Aufkleber | Werkstatt kann nur die Lackierung wählen, so entschieden |

### D9 Reihenfolge der Arbeit

Stand **30.07.2026**: Schritte 1–3 und 6–10 sowie 12–13 sind gebaut, alle 630
Tests laufen. Schritt 4 wartet auf dich, Schritt 11 (online) ist noch offen.

1. ✅ `data/vehicles/lacke.json` — zwölf Farben, vier Finishes samt Kennzahlen
2. ✅ Umfärbe-Kern (`src/core/lack.py`): Maskenfindung (beide Verfahren), Farbauftrag, die vier
   Finishes, `ResourceManager`-Zwischenspeicher. Ohne Anzeige, rein rechnend
3. ✅ Lackier-Seite im Fahrzeuglabor (`src/states/lack_labor.py`) mit vier
   Feldern und Speichern in den `paint`-Block
4. ⏳ **Abstimmung durch dich** über alle 15 Fahrzeuge (D6). Hier hält die Arbeit
   an, bis das Ergebnis steht
5. ⏳ Falls nötig: das zusätzliche Werkzeug aus D6
6. ✅ Profilfeld `paints`, `ist_freigeschaltet()` als Platzhalter
7. ✅ Werkstatt-Seite in der Aufteilung „Auto zuerst"; sechster Tab **links
   neben Einstellungen**, `_tab_rects` auf 288 px; Bedienung ausschließlich
   über Stepper und Knöpfe, keine Fußzeile
8. ✅ Kurzweg aus der Fahrzeugauswahl samt Rückkehr über alle drei Wege
9. ✅ Lackierung in der Fahrzeugauswahl anwenden (Kachelstreifen, Drehteller)
10. ✅ Lackierung im Rennen anwenden — einzelner Spieler, Splitscreen
11. ✅ Online: `PICK`-Feld, zwei Zeilen im Relay, Fernfahrzeug einfärben
    (05.08.2026). Die Kennung reist über TCP, nicht über UDP: der Positionsstrom
    trägt je Fahrzeug 26 feste Bytes und geht dreißigmal in der Sekunde hinaus,
    eine Lackierung ändert sich während eines Rennens nie. Der Weg ist
    Werkstatt → Profil → `PICK` → `settings["picks"]` → `LOBBY_STATE` →
    `online_players` → `RemoteVehicle`. Der Relay reicht die Kennung durch, ohne
    zu wissen, was eine Lackierung ist, und deckelt sie auf 64 Zeichen; was nicht
    in der Palette steht, wird beim Anzeigen zum Werkslack. Belegt in
    `tests/test_lack_online.py` — 18 Prüfungen über die **ganze** Kette, weil an
    jedem Übergang schon einmal ein Feldname nur auf einer Seite stimmte
12. ✅ Englische Strings ergänzen — 38 Einträge in `data/i18n/en.json`
13. ✅ Tests (D10) und vollständiger Testlauf (Stand 05.08.2026: 1552 grün).
    Schritt 11 steht; **Server-Deploy** für das `paint`-Feld steht noch aus

Schritt 4 ist die einzige Stelle, an der ich auf dich warte. Alles davor und
alles danach läuft ohne dich.

#### Beim Bauen aufgefallen

**`lacke.json` wurde als 16. Fahrzeug geladen.** `VehicleFactory.load_all_configs`
nahm jede `*.json` im Ordner `data/vehicles`, also auch die neue Lackpalette. Im
Fahrzeuglabor stand daraufhin „Fahrzeug 11 / 16", und `get_all_keys()` gab einen
Schlüssel zurück, hinter dem kein Fahrzeug steht. Die Fabrik prüft jetzt auf
`visual_type` und überspringt alles andere — das trägt auch, wenn irgendwann eine
Sicherungskopie oder eine README in dem Ordner landet.

### D10 Nachweis

Gefordert: **Profil überlebt Neustart, Altprofile laufen weiter.**

`tests/test_lackierung_profil.py` — die Lackwahl wird je Fahrzeug gespeichert und
wieder geladen; ein Profil ohne `paints` (der heutige Stand) lädt fehlerfrei und
steht auf Werkslack; eine unbekannte Kennung im Profil fällt auf Werkslack
zurück statt zu werfen.

Nicht gefordert, bewusst weggelassen — hier festgehalten, damit später klar ist,
dass es eine Entscheidung war und kein Versäumnis:

* **Umfärbung deterministisch je Fahrzeug** (Maskenabdeckung plausibel,
  Zielfarbe kommt an, Pixel außerhalb der Maske unverändert). Ohne diesen Test
  fängt nichts eine verrutschte Labor-Einstellung, außer deinem Auge
* **Online mit zwei echten Clients**, wie `test_block_g_online.py` es für Block G
  macht. Der Netzweg aus D7 ist damit nur von Hand geprüft
* **Werkstatt-Bedienung** — Sperren, ESC, Tabwechsel, Rückkehr des Kurzwegs

Der Kurzweg aus D4 hat drei Rückwege und keinen Test; das ist die Stelle, an der
ich am ehesten etwas übersehe. Sag Bescheid, wenn du das anders haben willst —
die drei kosten zusammen weniger als ein Abend.

---

## 6. Block E — Statistik und Freischaltungen

Entschieden am **31.07.2026**. Gegenüber dem ursprünglichen Entwurf ist ein
Thema weggefallen und drei sind konkret geworden.

> **Titel sind gestrichen.** E3 sah Titel neben dem Namen vor („Meister",
> Klassentitel), sichtbar in Lobby und Ergebnisliste. Fällt weg. Folge für schon
> gebauten Code: der reservierte, ausgegraute **„TITEL"-Abschnitt in der
> Werkstatt wird entfernt** und der Platz geht an die Farbfelder. Ein
> Platzhalter für etwas, das nie kommt, ist genau die Art Versprechen, die §0
> dem itch.io-Text vorwirft — der darf nicht im eigenen Spiel stehen bleiben.

### E1 Statistik im Profil

Gezählt wird: gefahrene Rennen, Siege, Podestplätze, gefahrene Kilometer,
Spielzeit, Bestzeiten je Strecke, gewonnene Grand-Prix-Serien. Sichtbar auf einer
Profilseite, kein Grinding-Zwang.

#### Wann etwas zählt

Das ist die Entscheidung, ohne die E1 nicht baubar ist — und ohne die E2 keine
verlässliche Grundlage hat:

| Regel | Entschieden | Begründung |
|---|---|---|
| Abgebrochene Rennen | zählen **nicht** | Nur wer die Ziellinie erreicht, hat ein Rennen gefahren. Sonst treibt Starten-und-Abbrechen jeden Zähler hoch, und die Freischaltung ist keine Leistung mehr |
| DNF (Frist abgelaufen) | zählt **nicht** | Weder als Rennen noch als Niederlage. Wer ausrollt, war da, aber nicht im Ziel |
| Online-Rennen | zählen **mit** | Ein Rennen gegen echte Leute ist mehr Rennen als eines gegen die KI, nicht weniger. Das ist etwas anderes als E2s Regel, Online-*Erfolge* nicht als Bedingung zu nehmen — die wären unerreichbar, wenn niemand online ist |
| Zeitfahren | zählt **nicht** als Rennen | Eine Runde gegen den Ghost ist kein Rennen. Für Metallic muss man wirklich fahren, nicht Runden drehen. Bestzeiten und geschlagene Ghosts werden trotzdem getrennt geführt — die Ghost-Bedingung für Zweifarbig hängt daran |
| Splitscreen | nur **Spieler 1** zählt | Es gibt ein Profil je Rechner. Sonst sammelt der Besucher am zweiten Controller Freischaltungen, die dir gehören |
| Grand Prix | jeder Lauf zählt als Rennen, die Serie zusätzlich als Serie | Ein Lauf ist ein Rennen; der Titel ist die Serie |

#### Ablage

Ein Block `statistik` im Profil, flach und mit Vorgabewerten — dieselbe Regel wie
bei `paints`: ein fehlender Schlüssel ist kein Fehler, sondern eine Null.

```json
"statistik": {
  "rennen": 0, "siege": 0, "podeste": 0,
  "meter": 0.0, "spielzeit_s": 0.0,
  "gp_siege": 0, "ghosts_geschlagen": []
}
```

`ghosts_geschlagen` ist eine Liste von Streckenschlüsseln, nicht eine Zahl —
dreimal dieselbe Strecke ist nicht dasselbe wie drei Strecken.

Ergänzt am **02.08.2026** um das, was die Erfolge aus E1a brauchen — durchweg
Zähler und Listen, **keine** neuen Messungen im Rennen:

```json
"statistik": {
  "rennen": 0, "siege": 0, "podeste": 0,
  "meter": 0.0, "spielzeit_s": 0.0,
  "gp_siege": 0, "ghosts_geschlagen": [],
  "strecken_gefahren": [], "fahrzeuge_gefahren": [], "klassen_gewonnen": [],
  "start_ziel_siege": 0, "aufholjagden": 0, "schnellste_runden": 0,
  "online_rennen": 0, "online_siege": 0, "lobbys_gehostet": 0,
  "strecken_geteilt": 0, "fremde_strecken_gefahren": 0,
  "strecken_erstellt": 0, "strecken_veroeffentlicht": 0,
  "eigene_strecke_gefahren": 0, "eigene_strecke_gewonnen": 0
}
```

#### Bestehende Profile und Dev-Modus

Entschieden: **alles fängt bei null an**, die gefahrenen Bestzeiten bleiben.
Niemand bekommt Zähler geschenkt, die nie gezählt wurden.

Ausnahme: **aus dem Quelltext gestartet ist alles frei.** `IS_RELEASE` ist
falsch, sobald das Spiel nicht als gepacktes Bündel läuft (`version.py:12`) —
genau daran hängen schon heute die Entwicklerwerkzeuge. Beim Entwickeln und
Testen will niemand erst zwanzig Rennen fahren, um einen Lack anzusehen. Im
ausgelieferten Build greift die Ausnahme nie, weil dort `sys.frozen` gesetzt
ist. Die Statistik wird trotzdem normal geführt — frei ist nur, was *gesperrt*
wäre.

### E1a Erfolge

Neu am **02.08.2026**. Entschieden: **rund 24 Erfolge, davon schaltet keiner
etwas frei.** Die Lacke hängen weiter allein an den drei Staffeln aus E2.

> **Verhältnis zu den gestrichenen Titeln (E3).** Titel standen neben dem Namen
> in Lobby und Ergebnisliste — ein Statussymbol gegenüber anderen. Erfolge
> stehen **nur im eigenen Profil**. Das ist bewusst dieselbe Linie: nach außen
> gibt es nichts zu tragen.

Genau weil sie nichts freischalten, dürfen Erfolge an Dingen hängen, die als
Bedingung unfair wären: **Online** braucht Mitspieler, der **Editor** ist
optional. Als Hürde vor einem Lack wären beide falsch, als Erfolg richtig.

**Bewusst nicht dabei: Fahrweise.** Ein Rennen ohne Wandberührung, ein langer
Drift, X Überholmanöver — jedes davon bräuchte einen neuen Zähler *im* Rennen,
also eine neue Stelle, die richtig auslösen muss. Alle Erfolge unten kommen
ohne aus: sie lesen die Ergebniszeile, die es schon gibt (Position, Zielzeit,
beste Runde, DNF, Fahrzeug, Strecke).

| # | Erfolg | Bedingung |
|---|---|---|
| **Menge** | | |
| 1 | Erste Runden | 5 Rennen gefahren |
| 2 | Stammfahrer | 20 Rennen |
| 3 | Dauergast | 50 Rennen |
| 4 | Erster Sieg | 1 Sieg |
| 5 | Seriensieger | 5 Siege |
| 6 | Titelsammler | 20 Siege |
| 7 | Podestreif | 10 Podestplätze |
| 8 | Langstrecke | 100 km gefahren |
| 9 | Grand-Prix-Sieger | eine Serie gewonnen |
| 10 | Meisterschaft | fünf Serien |
| **Können** | | |
| 11 | Schneller als gestern | eigenen Ghost geschlagen |
| 12 | Gespensterjäger | Ghost auf drei Strecken geschlagen |
| 13 | Start-Ziel-Sieg | von Startplatz 1 gestartet und gewonnen |
| 14 | Aufholjagd | vom letzten Startplatz aufs Podest |
| 15 | Schnellste Runde | beste Runde des Rennens gefahren |
| **Vollständigkeit** | | |
| 16 | Streckenkunde | jede mitgelieferte Strecke einmal gefahren |
| 17 | Fuhrpark | jedes Fahrzeug einmal gefahren |
| 18 | Alleskönner | mit jeder Fahrzeugklasse einmal gewonnen |
| **Erkunden** | | |
| 19 | Baumeister | eigene Strecke erstellt |
| 20 | Veröffentlicht | eigene Strecke veröffentlicht |
| 21 | Hausstrecke | auf eigener Strecke gefahren |
| 22 | Heimvorteil | auf eigener Strecke gewonnen |
| **Online** | | |
| 23 | Erstkontakt | erstes Online-Rennen gefahren |
| 24 | Online-Sieg | ein Online-Rennen gewonnen |
| 25 | Stammgast online | zehn Online-Siege |
| 26 | Gastgeber | eine Lobby gehostet, in die jemand kam |
| 27 | Streckenteiler | eigene Strecke in einer Lobby angeboten |
| 28 | Auf Empfehlung | Strecke eines anderen gefahren |

**Nicht dabei, obwohl naheliegend:** ein Erfolg fürs Lackieren oder fürs
Fahrzeuglabor. Das Labor ist ein Entwicklerwerkzeug und im Release gar nicht
sichtbar; ein Erfolg dafür ginge im ausgelieferten Spiel nie auf.

**Erfolge werden nicht gespeichert, sondern gerechnet.** Gespeichert ist allein
`statistik`; welche Erfolge offen sind, ist eine reine Funktion davon. Damit
kann nichts auseinanderlaufen, und jeder Erfolg ist ohne Spiel prüfbar.

### E2 Freischaltbedingungen

Entschieden: **Rennen und Siege**, **geschlagene Ghosts**. Online-*Erfolge*
bewusst nicht — sie hängen daran, dass überhaupt jemand online ist.

Entschieden: **gestaffelt.** Ein Finish wird nicht auf einmal frei, sondern in
zwei Stufen. Grund: die erste Belohnung soll früh kommen, damit man merkt, dass
es etwas zu holen gibt; das vollständige Set soll etwas bedeuten.

| Belohnung | erste drei Farben | alle zwölf Farben |
|---|---|---|
| **Grundfarben (Standard)** | von Anfang an | von Anfang an |
| **Metallic** | 5 gefahrene Rennen | 20 gefahrene Rennen |
| **Neon** | 5 Siege | 20 Siege |
| **Zweifarbig** | eigener Ghost auf 1 Strecke geschlagen | auf 3 Strecken |

Welche drei Farben zuerst: **Rubinrot, Kobaltblau, Perlweiß** — warm, kalt,
unbunt. Ein erster Vorgeschmack, der die Bandbreite zeigt, statt dreimal etwas
Ähnliches. Steht in `lacke.json`, nicht im Code.

Das kostet nichts an Bauaufwand: `ist_freigeschaltet(kennung)` bekommt die
**vollständige** Kennung, also Finish *und* Farbe — die Staffelung ist damit
schon in der Schnittstelle vorgesehen, die Block D angelegt hat.

**Werkstatt-Anzeige.** Ein gesperrter Lack bleibt sichtbar und ausgegraut; die
Bedingung darunter nennt den **Fortschritt**, nicht nur die Hürde: „Metallic —
7 / 20 Rennen". Ohne Zahl weiß niemand, ob er kurz davor ist oder weit weg.

✅ **umgesetzt 02.08.2026.** Die Zeile neben „FINISH" zeigt die Zahl der
*gewählten* Farbe (`lack.fortschritt_text()`) — nicht die des Finishs, denn
gestaffelt heißt: dieselbe Metallic-Zeile ist bei Rubinrot „5", bei Türkis
„20". Freigeschaltet steht dort „frei", ohne Bedingung „immer verfügbar".
Ausgegraut wird **Feld für Feld**, mit einem von Hand gezeichneten Schloss in
der Ecke (die gebündelte Schrift kennt kein Schloss-Zeichen, genau wie sie
keinen Haken kennt). Ein Rest Farbe bleibt stehen: zwölf graue Kästen sagen
niemandem mehr, worauf er hinarbeitet. Die Bühne führt Gesperrtes weiter vor —
blass und mit Schloss, damit es nicht wie „schon deins" aussieht —, der
**Flottenstreifen zeigt es nicht**: der ist der eigene Bestand.

### E4 Manipulationsschutz

Entschieden: **Bremsschwelle**, mit offenem Visier. Das Profil wird
**verschlüsselt und signiert** abgelegt.

> Das ist keine Sicherheitsmaßnahme, sondern eine Bequemlichkeitshürde. Der
> Schlüssel muss mitgeliefert werden, weil das Spiel die Datei ohne Rückfrage
> lesen können muss — und was mitgeliefert wird, lässt sich herausholen. Echter
> Schutz ginge nur serverseitig mit Benutzerkonten. Bei kosmetischen Belohnungen
> in einem kostenlosen Spiel ist der Aufwand nicht gerechtfertigt.

**Sicherung der letzten heilen Fassung.** Verschlüsselt heißt: niemand kann die
Datei retten, wenn das Format klemmt — und darin stehen auch Bestzeiten, die
jemand über Wochen gefahren hat. Deshalb wird vor jedem Schreiben die vorherige
Datei als `profile.bak` behalten. Lässt sich die Hauptdatei nicht entschlüsseln,
wird still die Sicherung genommen; verloren ist dann höchstens die letzte
Änderung statt allem.

Migration: vorhandene Klartextprofile werden beim ersten Start übernommen und
danach verschlüsselt geschrieben.

✅ **umgesetzt 02.08.2026** in `src/core/tresor.py`; `profile.load/save` gehen
nur noch durch ihn. Ohne neue Abhängigkeit: XOR gegen einen SHA-256-Strom,
darüber HMAC-SHA256 über den **Geheimtext** (encrypt-then-MAC, sonst müsste zum
Prüfen erst entschlüsselt werden). Ein Nonce je Schreibvorgang, damit zwei
gleiche Profile nicht gleich aussehen.

Drei Entscheidungen, die im Plan noch nicht standen:

* **Der Behälter bleibt Text.** Die Datei ist weiter JSON mit lesbaren
  Feldnamen (`format`, `hinweis`, `nonce`, `sig`, `data`), nur der Inhalt ist
  Base64. Eine plötzlich binäre Datei ließe sich weder in einem Fehlerbericht
  zeigen noch in der Versionsverwaltung ansehen — und `data/settings/profile.json`
  liegt im Repo.
* **Offenes Visier wörtlich genommen.** Im Klartext steht in jeder Datei, dass
  das eine Bremsschwelle ist und der Schlüssel im Spiel liegt. Der Schlüssel
  selbst ist der Satz `"…Bremsschwelle, kein Schutz"`.
* **Die Sicherung wird nur aus einer heilen Datei erneuert.** Sonst
  überschreibt genau der Schreibvorgang die Rettung, den sie retten soll.
  Geschrieben wird daneben und dann `os.replace` — ein Absturz mitten im
  Speichern hinterlässt keine halbe Datei.

Was die Verschlüsselung beim Entwickeln kostet, gibt `tools/profil_werkzeug.py`
zurück: Profil im Klartext ausgeben, bearbeiten, zurückschreiben.

### E5 Reihenfolge und Nachweis

1. `statistik`-Block im Profil samt Zählregeln aus E1 — ohne Anzeige
   ✅ **umgesetzt 02.08.2026** (`src/core/statistik.py`, `profile.statistik`)
2. Zähler an den richtigen Stellen auslösen (Zieldurchfahrt, Serienende,
   Ghost geschlagen). Das ist der fehleranfällige Teil: die Regeln aus E1 müssen
   an *einer* Stelle entschieden werden, nicht an sechs
   ✅ **umgesetzt 02.08.2026.** Verdrahtet sind: Zieldurchfahrt und Ghost
   (`race_state._statistik_buchen`), Serienende offline
   (`race_state`, nach `add_race_results`), Editor (Entwurf gespeichert,
   veröffentlicht), Online (Lobby gehostet, Strecke angeboten). Die Herkunft
   einer Strecke kommt aus ihrem Ablageort: `custom/` = eigene, `online/` =
   fremde.
   Nachgetragen am **02.08.2026:** ein online gewonnener Grand Prix zählt
   jetzt auch. Die Zahlen fehlten nie — der Host verteilt `gp_standings` und
   `gp_finished` mit jeder `LOBBY_STATE`, jeder Gast sieht die Wertung in der
   Übersicht. Falsch war nur der *Ort*: gebucht wurde im `race_state` aus dem
   lokalen `grand_prix`, und den führt online allein der Gastgeber; beim Gast
   ist er leer, und im Augenblick der Zieldurchfahrt steht der Endstand noch
   nirgends. Jetzt bucht `online_lobby_page._gp_sieg_pruefen()` aus dem
   verteilten Zustand, für Host und Gast über denselben Weg — einmal je Serie,
   nur wenn diese Seite die Serie hat **laufen** sehen (wer sich in eine fertige
   Wertung einklinkt, hat sie nicht gefahren), und nur wenn der eigene Name
   oben steht.
3. Profilseite mit Zahlen und Erfolgsliste — **eigener Tab in der Menüleiste**
   neben WERKSTATT. Sieben Tabs passen nicht mehr bei 288 px Breite; die Leiste
   rechnet ihre Breite künftig aus der Anzahl statt aus einer Konstante
   ✅ **umgesetzt 02.08.2026** als **Variante B, Kennzahlenband**
   (`src/states/menu/profil_page.py`, Entwürfe unter
   `Documentation/entwurf/profil_[ABC]_*.png`, gezeichnet von
   `tools/profil_entwurf.py`). Die Leiste rechnet
   `min(288, (Breite − Rand − Lücken) // Anzahl)`, mit sieben Tabs also 256 px;
   `TAB_WERKSTATT` bleibt bei 4, weil PROFIL dahinter eingefügt ist.
   Die Bestzeiten stehen als weitere Karte auf derselben Seite — im Entwurf
   waren sie auf den Einzelspieler-Reiter verwiesen, wo sie gar nicht stehen.
4. `ist_freigeschaltet()` füllen, Staffelung aus `lacke.json` lesen
   ✅ **umgesetzt 02.08.2026.** Die Staffelung steht als `freischaltung`-Block
   je Finish in `lacke.json` (`zaehler`, `erste`, `alle`), die drei frühen
   Farben als `erste_farben`. `lack.fortschritt()` liefert `(erreicht, nötig)`,
   `ist_freigeschaltet()` vergleicht nur noch. Welcher Profil-Zähler hinter
   einem Stichwort steckt, steht in `lack._ZAEHLER` — in der Datei stehen
   Wörter, keine Feldnamen. Aus dem Quelltext gestartet ist alles frei; der
   Fortschritt bleibt trotzdem ehrlich, es fällt nur die Sperre weg.
5. Werkstatt zeigt Fortschritt statt nur der Bedingung; **Titel-Abschnitt
   entfernen**
   ✅ **umgesetzt 02.08.2026** — siehe §E2, „Werkstatt-Anzeige". Der
   Titel-Kasten war schon am 31.07.2026 aus der Seite geflogen; jetzt sind auch
   seine beiden Einträge aus `data/i18n/en.json` verschwunden.
6. Verschlüsselung, Signatur, `profile.bak`, Migration
   ✅ **umgesetzt 02.08.2026** — siehe §E4. Eine eigene Migration braucht es
   nicht: `tresor.lesen()` nimmt beides an, `tresor.schreiben()` legt nur noch
   das eine ab, also stellt der erste Speichervorgang um.
7. Tests
   Für Schritt 6 erledigt: `tests/test_profil_tresor.py` (33) prüft vor allem
   den Weg zurück — verbogener Geheimtext, verbogener Nonce, fremde Unterschrift
   und sieben Sorten Müll geben `None` statt eines Absturzes; eine kaputte
   Hauptdatei wird still aus `profile.bak` ersetzt und überschreibt die gute
   Sicherung nicht; ein Klartextprofil von vorher behält beim Umstellen jeden
   Wert. Zwei ältere Tests lasen die Profildatei roh und gehen jetzt durch den
   Tresor — geprüft wird der Inhalt, die Ablage prüft der neue Test.
   Für Schritt 4 und 5 erledigt: `tests/test_freischaltung.py` (32) prüft jede
   Staffelgrenze (0/4/5/19/20 Rennen, 4/5/20 Siege, 0/1/3 Ghosts), dass ein
   verbogenes Profil auf Werkslack fällt statt abzustürzen, dass die Werkstatt
   je Farbe fragt und nichts Gesperrtes ins Profil schreibt, und dass jeder
   Zähler eine deutsche wie englische Textvorlage hat.

> **Tests fassen das echte Profil nicht an.** Der Testlauf hat
> `data/settings/profile.json` zweimal überschrieben: einmal landete eine
> Lackierung darin (30.07.2026), einmal wurde es auf Vorgaben zurückgesetzt und
> Benutzername samt fünf Bestzeiten waren weg (02.08.2026) — ausgelöst von der
> neuen Statistik, die nach jedem Zielankommen sichert. Einzelne Tests
> abzusichern hilft nicht, der Aufruf steckt tief im Spielcode. Seit dem
> 02.08.2026 lenkt `tests/conftest.py` deshalb das **ganze Verzeichnis für
> beschreibbare Nutzerdaten** für den gesamten Lauf um; Ghosts und übernommene
> Strecken sind damit gleich mit geschützt.

Nachweis, in derselben Art wie `tests/test_lackierung_profil.py`:

* jede Zählregel aus E1 einzeln — Abbruch, DNF, Zeitfahren, Splitscreen-Spieler 2
  erhöhen **nichts**; Online und GP-Lauf erhöhen
* `ist_freigeschaltet()` an jeder Staffelgrenze (4/5/19/20 Rennen)
* Migration: Klartextprofil wird übernommen, danach verschlüsselt gelesen
* beschädigte Hauptdatei → `profile.bak` greift; beide beschädigt → leeres
  Profil, kein Absturz
* ein Profil mit von Hand erhöhten Zählern verliert die Freischaltungen

---

## 7. Block F — Politur und Auslieferung

### F1 Noch offen, kommt mit dem nächsten großen Release

Ursprünglich als Vorbereitung für 0.6-beta gedacht. Weil 0.6-beta ein Testbau
war und keine Veröffentlichung (§1), sind das keine verpassten Vorbereitungen,
sondern offene Punkte auf dem Weg zu 1.0.0. Entschieden am 31.07.2026:
**gemeinsam mit Block D und H ausliefern**, nicht als eigener Zwischenrelease.

| Punkt | Stand 31.07.2026 |
|---|---|
| Fehlende englische Strings | ✅ **erledigt 05.08.2026 — es waren 104, nicht 19.** Die alte Messung hat nur `tr("…")` im Quelltext gezählt. Der größte Teil der Lücke stand aber gar nicht dort: **61 Erfolge** aus `statistik.ERFOLGE` (Block E, nach der Messung dazugekommen), dazu Bedienhinweise und Streckennamen — alles Werte, die erst zur Laufzeit durch `tr()` gehen. `data/i18n/en.json` hat jetzt 751 Einträge. `tests/test_uebersetzung.py` prüft nicht die Datei, sondern **jede Quelle**, aus der ein sichtbarer Text stammt: Aufrufe im Syntaxbaum, Erfolge, Modi, Schwierigkeiten, Eingabegeräte, Fahrzeugklassen, Lackfarben, Finishes, Fahrzeug- und Streckendateien. Was in beiden Sprachen gleich heißt (`ENTER`, `LB / RB`, „GP Arena"), steht mit sich selbst in der Datei — eine Ausnahmeliste im Test wächst still mit, ein Eintrag in der Sprachdatei ist eine Aussage, die jemand getroffen hat |
| itch.io-Text: „5 Unique Vehicles" | ✅ **erledigt 05.08.2026** — `Documentation/ITCHIO_RELEASE.md` nennt jetzt „15 Unique Vehicles — five classes, three distinct models each". Damit ist die zweite der beiden Falschaussagen aus §0 weg. Die Seite selbst muss noch nachgezogen werden, das braucht keinen Build |
| itch.io-Text: Grand Prix | **stimmt jetzt** — der Modus ist auswählbar, das Versprechen ist eingelöst |
| Startbildschirm zeigt Version | **fertig** — `version_string()` steht im Willkommensbildschirm, im Ladebildschirm und unter Einstellungen → Info |

### F2 Vor 1.0.0

* **macOS-Build.** Entschieden am 31.07.2026: **du hast einen Mac und prüfst den
  Release selbst.** Damit fällt die Überlegung weg, ihn ungetestet anzubieten
  oder ganz zu streichen — er wird gebaut, von dir gestartet und erst dann
  angeboten

  ✅ **geprüft am 04.08.2026** nach der Meldung „line 47:
  .venv-build/bin/activate: No such file or directory". Fünf Funde, alle behoben,
  belegt in `tests/test_auslieferung.py`:

  | Fund | Warum es niemandem auffiel |
  |---|---|
  | `source .venv-build/bin/activate` schlug fehl | Geprüft wurde nur, ob das *Verzeichnis* existiert. Eine halb angelegte Umgebung — abgebrochener Lauf, gelöschtes Python nach `brew upgrade` — übersprang damit die Erzeugung. Das Skript benutzt jetzt `$VENV/bin/python` direkt, prüft den Interpreter und legt eine unvollständige Umgebung neu an |
  | **`soundfile` fehlte in `requirements.txt`** | Der macOS-Build legt eine frische Umgebung an und installiert **nur** daraus. Im Bündel gab es die Bibliothek nicht, und der erste Rennstart wäre mit einem `ImportError` abgebrochen — nachgestellt und bestätigt. Auf dem Entwicklungsrechner ist sie ohnehin installiert |
  | Ghost-Runden wurden im Bündel **nie** gespeichert | `ghost._ghost_path` schrieb relativ, und ein gepacktes `.app` setzt das Arbeitsverzeichnis auf `sys._MEIPASS` — also ins schreibgeschützte Bündel. `save` verschluckte den Fehler. Jetzt über `paths.user_path` |
  | Der **Streckeneditor** konnte im Bündel nicht speichern | Dieselbe Ursache: `DRAFT_DIR`/`CUSTOM_DIR` waren relative Konstanten. Jetzt `draft_dir()`/`custom_dir()` über `paths.user_path`; gelesen wird weiter über alle Wurzeln, mitgelieferte Strecken bleiben auffindbar |
  | `CFBundleShortVersionString` stand auf `0.1.0` | Das Spiel meldete 0.6.0-beta. macOS zeigt den Plist-Wert im Finder — zwei Versionen sind schlimmer als eine. Kommt jetzt aus `version.py` |

  Der Bau selbst ist mit echtem PyInstaller gegengeprüft (Linux, `game_macos.spec`):
  `libsndfile` landet über den `hook-soundfile.py` aus *pyinstaller-hooks-contrib*
  im Bündel. Von Hand `collect_data_files('soundfile')` aufzurufen bringt
  **nichts** — soundfile ist eine einzelne Moduldatei und kein Paket.

* **Was nicht mehr mit ausgeliefert wird** (entschieden 04.08.2026): die drei
  eigenen Strecken aus `data/tracks/custom`, die Entwürfe aus
  `data/tracks/drafts` und die eigenen Ghost-Runden aus `data/ghosts`.
  „Mitgeliefert" soll heißen, dass eine Strecke abgestimmt ist; und ein neuer
  Spieler soll im Zeitfahren nicht gegen eine fremde Zeit mit fremdem Namen
  fahren — der Erfolg „eigenen Ghost geschlagen" wäre sonst falsch, und die
  Zweifarbig-Freischaltung hängt daran
* ✅ **Installer geprüft** (07.08.2026). Ein Update über eine bestehende
  Installation behält das Profil: die Einstellungen stehen danach auf dem
  letzten Stand. **Mit E4 war das der kritische Fall** — ein Update darf ein
  verschlüsseltes Profil nicht unlesbar machen, und ein unlesbares Profil wäre
  schlimmer als ein fehlendes, weil der Weg zurück fehlt
* ✅ **`crash.log` verlinkt** (05.08.2026). Unter „Info", direkt unter „Bugs
  melden": ein Klick öffnet den Bericht im Standardprogramm des Systems. Gibt es
  keinen, steht dort der **Pfad** statt eines toten Links — dann weiß man
  wenigstens, wo er auftauchen wird. Pfad und Schreiben liegen jetzt zusammen in
  `src/core/absturz.py`; `main.py` baut ihn nicht mehr selbst. Der Grund für den
  Punkt: nach einem Absturz steht der Pfad sechs Sekunden auf dem roten
  Bildschirm — lesbar, aber nicht abschreibbar, und im gepackten macOS-Bündel
  liegt die Datei ohnehin unter `~/Library/Application Support`
* Screenshots und Trailer aktualisieren (Werkstatt, Grand Prix)
* ✅ **Seitentext für itch.io neu geschrieben** (07.08.2026). Für Spieler, nicht
  für Entwickler: Modi, Klassen, Werkstatt, Editor, Zusammenspiel, Steuerung,
  Installation, Systemvoraussetzungen. Kein Wort über Bibliotheken, Server,
  Protokolle oder Dateiformate — das interessiert niemanden, der ein Rennspiel
  sucht, und es veraltet schneller als der Rest. Deutsch **und** englisch, weil
  itch.io nur ein Beschreibungsfeld hat und die Wahl damit eine Entscheidung
  ist. **Der Verweis auf GitHub ist heraus:** er zeigte auf
  `philip1307/Fahr-Rennspiel-2D`, ein Pfad, den es nicht gibt, und das echte
  Repo ist privat — ein toter Link auf der Verkaufsseite ist schlechter als
  keiner. Rückmeldungen laufen jetzt über die itch.io-Kommentare.
  `tests/test_itchio_text.py` hält jede Zahl im Text gegen den Code (Fahrzeuge,
  Klassen, Modi, Farben, Lackarten, Strecken, Spielerzahl) und beide
  Sprachfassungen gegeneinander — genau die Sorte Fehler, die §0 zweimal
  gefunden hat und die beim Programmieren niemandem auffällt, weil die Datei
  kein Code ist
* ✅ **Kurzes „So spielst du" beim ersten Start** (05.08.2026). Zwischen
  Fahrername und Hauptmenü, sechs Zeilen: Fahren, Ziel, Zeitfahren, Werkstatt,
  Profil, Pause. Als zweiter Schritt **im** Willkommensbildschirm und nicht als
  eigener Zustand — die Karte gehört zum ersten Start und soll auch nur dann
  erscheinen. Der Name ist vorher gespeichert, wer das Fenster auf der Karte
  schließt, steht beim nächsten Mal nicht wieder bei der Namenseingabe. Die
  Tastenzeile kommt aus `keybindings`: wer Gas auf W gelegt hat, liest W. Jede
  Bestätigung führt weiter, auch ESC — es ist kein Dialog mit einer Wahl
* ❌ **Hinweis auf den unverschlüsselten Verkehr: wieder entfernt** (05.08.2026).
  Er stand einen Tag lang unter „Info" (Block H1) und ist auf Wunsch heraus; in
  die itch.io-Beschreibung kommt er auch nicht. Am Verkehr ändert das nichts —
  er ist unverändert im Klartext, und das bleibt in H1 und §9 festgehalten. Der
  Test dazu steht in der **Gegenrichtung**: er schlägt an, wenn der Satz wieder
  auftaucht. Das ist eine Entscheidung, keine Lücke, und bei der nächsten
  Durchsicht von Block H soll sie nicht versehentlich zurückgedreht werden
* ❌ **Signaturzertifikat: wird nicht gekauft** (05.08.2026). Damit bleibt beim
  ersten Start die Warnung „unbekannter Autor". Bewusst getragen; kein Code
  ändert daran etwas
* ✅ **Menü-Bildrate gedeckelt** (05.08.2026). `MENUE_GRENZE` steht auf 60 und
  wirkt jetzt als echte Obergrenze statt nur „Unbegrenzt" umzudeuten — eine
  kleinere Einstellung bleibt kleiner, im Rennen gilt sie unverändert. Die
  eigentliche Last liegt woanders, siehe A5

---

## 7a. Block H — Sicherheit von Relay und Netzcode

Anlass: mit Block G kann **jedes Lobbymitglied Dateien an andere Spieler
schicken**. Das ist die erste Stelle, an der fremde Daten auf fremden Platten
landen — und ein guter Zeitpunkt, den ganzen Netzweg einmal durchzusehen statt
nur diesen einen Pfad.

Grundlage ist eine Analyse vom **31.07.2026** über `server/server.py`,
`src/net/*`, den Dateiempfang in `online_lobby_page.py`, `src/core/paths.py` und
den Streckenlader. Wo unten eine Zahl steht, ist sie gemessen, nicht geschätzt.

### H0 Was bereits trägt

Zuerst das, was **nicht** angefasst werden muss — sonst wird dieselbe Arbeit
zweimal gemacht:

| Geprüft | Ergebnis |
|---|---|
| `paths.safe_track_filename` | hält gegen jeden Traversal-Versuch: `../`, `..\`, absolute Pfade, `%2e%2e`, Null-Bytes, Zeilenumbrüche, Unicode-Tricks. 38 Eingaben durchprobiert, kein Ausbruch |
| UDP-Weiterleitung von `STATE`/`BUMP` | traut der für die Quelladresse **registrierten** Lobby, nicht der ID im Paket — ein Client kann nicht in fremde Lobbys hineinfunken |
| `_recv` | begrenzt eine Einzelnachricht auf 1,06 MB |
| `_handle_tcp` | hat `except Exception` — ein Absturz beendet nur diese Verbindung, nie den Server |
| Host-Trennung | räumt die Lobby ab, verwaiste Lobbys bleiben nicht liegen |
| Streckenkomplexität | **kein** DoS: die 1-MB-Grenze begrenzt die Komplexität mit. Gemessen — 8000 Punkte ≈ 0,5 s Ladezeit, 16 000 Physikformen, 60 MB. Eine echte Strecke hat 330 Punkte |
| Deserialisierung | nirgends `eval`, `exec` oder `pickle` im Netzpfad — ausschließlich `json` |
| Repo | keine Zugangsdaten, Schlüssel oder Zertifikate eingecheckt |
| `load_track_infos` | fängt breit ab, eine beschädigte Datei sprengt die Streckenliste nicht |

### H1 Wogegen verteidigt wird

Entschieden am 31.07.2026. **Zwei** Angreifer, nicht vier:

* **Der gelangweilte Spieler mit verändertem Client.** Er hat die Lobby-ID
  sowieso, braucht keine besonderen Fähigkeiten und kann heute fremde Rennen
  abschießen. Das ist der wahrscheinlichste Fall.
* **Jemand, der den Heimserver selbst ins Visier nimmt.** Speicher erschöpfen,
  Verbindungen fluten. Hier geht es um deinen Rechner, nicht um das Spiel.

**Ausdrücklich nicht** im Bedrohungsmodell: der Mitleser im selben Netz und der
Tunnelbetreiber. Das ist eine bewusste Entscheidung mit einer Folge, die
schriftlich festgehalten gehört:

> Ohne Transportverschlüsselung bleibt **aller** Verkehr im Klartext und
> veränderbar. Für Hamburg heißt das konkret: **playit.gg sieht und kann alles
> ändern** — Chat, Namen, Lobby-Zustand und den Inhalt übertragener
> Streckendateien. Das ist kein Angriff, das ist die normale Betriebsart eines
> Tunnels. Wer im WLAN mitliest, kann dasselbe. Das ist ab jetzt eine
> akzeptierte Eigenschaft, keine offene Lücke.

### H2 Befunde und was dagegen getan wird

Schwere ist danach bemessen, was ein Angreifer aus dem Bedrohungsmodell
**tatsächlich** erreicht — nicht danach, wie es klingt.

#### Hoch

**H2.1 Slot-Übernahme ohne Authentisierung.** `UDP_REGISTER` setzt
`lobby.clients[slot].udp_addr = addr` allein aufgrund des Paketinhalts
(`server.py:1030`). Wer die Lobby-ID kennt und einen belegten Slot nennt,
leitet den Positionsstrom eines fremden Spielers auf sich um; der Betroffene
sieht die anderen einfrieren und fliegt nach 15 s per Watchdog raus. Kein Token,
keine Bindung an die TCP-Verbindung.

✅ **behoben am 04.08.2026, beide Stufen.**

*Gegenmaßnahme, zweistufig:*
1. **Quell-IP prüfen.** Der Server kennt zu jedem Slot die IP seiner
   TCP-Verbindung. `UDP_REGISTER` wird nur angenommen, wenn sie passt. Das ist
   eine **reine Serveränderung** — kein Protokollschnitt, keine
   `required_version`, nur Deploy. Greift nicht, wenn zwei Spieler hinter
   derselben IP sitzen, wird dort aber auch nicht schlechter als heute.
2. **Sitzungstoken.** `JOIN_OK` liefert ein Zufallstoken aus `secrets`;
   `UDP_REGISTER` muss es tragen. Deckt auch den Fall gemeinsamer IP.
   Protokolländerung — `required_version` muss hoch.

**H2.2 Streckenlader stürzt an drei über das Netz erreichbaren Stellen ab.**
✅ **behoben am 31.07.2026.**
`Track.load_from_json` fängt nur `(OSError, json.JSONDecodeError)`, `race_state`
nur `TrackDataError`. Gemessen, alle drei reproduzierbar:

| Eingabe | Ausnahme |
|---|---|
| tief verschachteltes JSON (`[` ×100 000) | `RecursionError` |
| ungültiges UTF-8 | `UnicodeDecodeError` |
| Zahl größer als `float` (z.B. `1e400` als Ganzzahl) | `OverflowError` |

Alle drei enden im Absturz mit `crash.log`. Über Block G kann das **jedes
Lobbymitglied** auslösen: Strecke anbieten, ein anderer lädt sie herunter und
fährt sie. Das widerlegt die Aussage in G4, der Streckenlader „verwirft, was er
nicht lesen kann" — er verwirft, was er als *Struktur* nicht versteht, nicht
das, woran der *Parser* scheitert.

*Umgesetzt so:* die Datei wird erst als Text gelesen, dann auf
Verschachtelungstiefe geprüft (`MAX_TIEFE = 40`, eine echte Strecke kommt auf 3),
dann geparst. Die Ausnahmeliste umfasst jetzt `OSError, ValueError,
RecursionError, MemoryError` — `ValueError` deckt `JSONDecodeError` *und*
`UnicodeDecodeError`, weil beide davon erben. `_as_float` fängt zusätzlich
`OverflowError`, gibt dort aber den **Vorgabewert** zurück statt zu werfen: eine
unbrauchbare Streckenbreite darf die Strecke nicht unfahrbar machen.

Die Tiefenprüfung überspringt Klammern in Zeichenketten — sonst löst ein
Streckenname wie `[[Oval]]` sie aus. Ein eigener Test hält das fest.

**Rein clientseitig**, kein Deploy, kein Protokollschnitt — deshalb der erste
Schritt.

#### Mittel

| # | Befund | Gegenmaßnahme |
|---|---|---|
| H2.3 ✅ | Keine Ratenbegrenzung, kein Verbindungslimit, keine Lobby-Obergrenze. Ein Byte alle 59 s hält eine Lobby offen | **behoben 04.08.2026**: `_Wache` zählt Verbindungen und Lobbys je IP, die Anfragerate läuft über einen Eimer (40/s im Mittel, 120 Vorrat — eine Streckenübertragung sind 34 Nachrichten am Stück und muss durchgehen). Hält eine Flut an, wird nach 300 verworfenen Nachrichten getrennt. Alle Grenzen kommen aus der Umgebung, damit Helsinki und Hamburg verschieden eingestellt werden können |
| H2.4 | `lobby.settings.update(payload)` (`server.py:565`) nimmt vom Host **beliebige Schlüssel unbegrenzt** an und verteilt jeden davon in jedem `LOBBY_STATE` an alle | Nur bekannte Schlüssel übernehmen, Gesamtgröße je Lobby deckeln |
| H2.5 ✅ | `addr_map` wächst unbegrenzt; `remove()` löscht nur die Adressen eingetragener Clients, nicht die per gefälschter Quelladresse hinzugekommenen | **behoben 04.08.2026**: die Tabelle bildet jetzt `addr → (lobby, slot)` ab, `unbind_slot` trägt **jede** Adresse eines Slots aus — auch die, die er zwischenzeitlich hatte. Vorher hing das Aufräumen an `conn.udp_addr`, also nur an der letzten |
| H2.6 ✅ | Client hat **keine Summengrenze** beim Empfang: `MAP_CHUNK` und `OFFER_DATA_CHUNK` werden unbegrenzt angehängt. `_OFFER_MAX_B` gilt nur beim Hochladen | **behoben 31.07.2026**: `_stueck_anhaengen` zählt die Summe mit, verwirft bei Überschreitung den ganzen Puffer und sagt es dem Spieler — eine halbe Datei ist nutzlos |
| H2.7 ✅ | Verstärkung ×5 innerhalb der Lobby: einer flutet UDP, der Relay fächert an bis zu fünf Peers aus | **behoben 04.08.2026** (aus H7 mitgenommen): `ClientConn.udp_erlaubt` zählt je Slot in einem Sekundenfenster, Vorgabe 120 Pakete/s. Das Spiel sendet ~30/s. Zusätzlich muss der Absenderslot zu der Adresse passen, die für ihn eingetragen ist — sonst konnte ein Lobbymitglied unter fremder Slotnummer senden |

#### Niedrig

| # | Befund | Gegenmaßnahme |
|---|---|---|
| H2.8 ✅ | `base64.b64decode` in `OFFER_CHUNK` ungeschützt (`binascii.Error`), `json.loads` in `_recv` fängt `UnicodeDecodeError` nicht | **behoben 04.08.2026**: `OFFER_CHUNK` und `MAP_CHUNK` fangen `ValueError`/`TypeError` und verwerfen die Übertragung mit einer Meldung statt die Verbindung zu beenden (beim Gastgeber riß das die ganze Lobby mit). `_recv` fängt `ValueError` (deckt `JSONDecodeError` **und** `UnicodeDecodeError`), `struct.error` und `RecursionError` — und nimmt nur noch JSON-**Objekte** an: `json.loads(b"5")` ergibt eine Zahl, und der ganze Nachrichtenweg ruft danach `msg.get(...)` |
| H2.9 ✅ | Lobby-Codes aus `random.choices` — vorhersagbar, und der Code ist die **einzige** Zugangskontrolle | **behoben 04.08.2026**: `secrets.choice`; `random` ist aus dem Server verschwunden |
| H2.10 ✅ | `find_track` probiert den vom Host gelieferten Pfad **roh**, auch absolut → Existenz-Orakel für Dateipfade auf dem Gast-Rechner | **behoben 31.07.2026**: der Pfad wird bei der Übernahme aus `LOBBY_STATE` auf einen sicheren Dateinamen reduziert (`online_lobby_page.py`, LOBBY_STATE-Zweig). `find_track` bleibt unangetastet — sein Rohpfad-Versuch ist für eigene absolute Pfade nötig |
| H2.11 ✅ | Windows-Gerätenamen passieren `safe_track_filename`: `CON.json`, `NUL.json`, `COM1.json`, `LPT1.json`, `AUX.json`, `PRN.json`. Auf Windows landet das Schreiben am Geräte­treiber statt in einer Datei | **behoben 31.07.2026**: Gerätenamen bekommen einen Unterstrich davor (`_CON.json`) — entschärft, aber noch lesbar. Geprüft wird der Stamm, denn `CON.json` spricht dasselbe Gerät an wie `CON` |
| H2.12 ✅ | Ankündigungen vom Relay werden ungeprüft im Menü angezeigt → ein bösartiger Relay kann jeden Text einblenden (Phishing) | **behoben 04.08.2026**: `src/net/servertext.py` begrenzt Länge (600 Zeichen, 12 Zeilen, Titel 80) und entfernt Steuerzeichen sowie die unsichtbaren Richtungszeichen aus dem Rechts-nach-links-Bereich — mit denen lässt sich die Leserichtung eines Satzes umdrehen, ohne dass man es sieht. Der Kasten trägt jetzt „ANKÜNDIGUNG · Servernachricht". **Beim Bauen erweitert**: `reason` ist genauso Fremdtext und wird an allen vier Anzeigestellen durch dieselbe Säuberung geschickt |
| H2.13 ✅ | Namensfilter (`name_blacklist.json`) gilt nur clientseitig; der Server nimmt `str(msg["name"])[:20]` ungeprüft und zeigt ihn allen | **behoben 04.08.2026**: `saeubere_name` lässt Buchstaben und Ziffern **jeder** Sprache durch (`isalnum`, also auch Umlaute und kyrillisch) plus `` _-.'`` und wirft alles andere weg; leer wird zu „Spieler". Keine Wortliste — die bleibt Sache des Clients, hier geht es nur um die Zeichen |

#### Neu gefordert

**H2.14 Aufnahmesperre bei hoher Auslastung, im Spiel sichtbar.** Entschieden am
31.07.2026, über die Analyse hinaus: der Relay soll bei hoher Last **keine neuen
Lobbys mehr annehmen**, und der Spieler soll das **sehen**, statt auf einen
Fehler zu laufen, den er nicht einordnen kann.

Der Heimserver hat 5,7 GB RAM und einen Anschluss, den sich das Spiel mit deinem
Haushalt teilt. Grenzen je IP (H2.3) helfen gegen *einen* Angreifer, nicht gegen
zwanzig echte Spieler zur selben Zeit. Das ist kein Sicherheitsbefund, sondern
die Nachbarschaft davon — dieselben Zähler, andere Absicht.

*Was gemessen wird:* offene Lobbys, gleichzeitige Verbindungen, UDP-Pakete je
Sekunde. Daraus eine Stufe: **frei / gut besucht / ausgelastet**.

*Wer abgewiesen wird:* **`HOST` ja, `JOIN` nein.** Eine neue Lobby ist der
teure Vorgang; einem Freund den Beitritt in eine schon laufende Lobby zu
verweigern wäre die falsche Sparsamkeit — der Slot ist ohnehin reserviert.
Abweisung als `JOIN_FAIL` mit eigenem Code `SERVER_BUSY` und einem Satz, der
sagt was zu tun ist („Server ist gerade ausgelastet — versuch es in ein paar
Minuten noch einmal oder wähle den anderen Server.").

*Wo es sichtbar wird:* die `INFO`-Antwort trägt heute schon `lobby_count`; dazu
kommen `lobby_max` und die Stufe. Angezeigt in der **Serverauswahl**, die dafür
nichts Neues braucht:

* die rechte Spalte zeigt statt „8 Lobbys" künftig „8 / 50 Lobbys"
* bei *ausgelastet* steht dort **„Ausgelastet"** in Warnfarbe, und die Zeile
  wird ausgegraut wie bei „Version veraltet" — sichtbar, aber nicht wählbar.
  Das Muster gibt es in `ServerRow` bereits (`status_text`, `enabled`)
* wer trotzdem hostet (Zeile war beim Anzeigen noch frei), bekommt die Meldung
  aus `SERVER_BUSY` in der Online-Lobby zu sehen

Damit ist die Auslastung an genau der Stelle sichtbar, an der man den Server
wählt — und nicht erst, wenn es nicht klappt.

### H3 Reihenfolge der Arbeit

Entschieden: **alles zusammen in einem Block**, ein Deploy, eine Abnahme.
Innerhalb des Blocks aber nach Abhängigkeit sortiert — was ohne Protokollschnitt
geht, kommt zuerst, damit es notfalls einzeln ausgeliefert werden kann.

1. ✅ **Clientseitig, kein Deploy** (31.07.2026): H2.2 (Absturzstellen),
   H2.6 (Summengrenze), H2.10, H2.11 — belegt in
   `tests/test_sicherheit_stufe1.py`, 45 Prüfungen. Jede wurde gegengeprobt:
   mit zurückgenommener Behebung schlägt sie fehl
2. ✅ **Nur Server, kein Protokollschnitt** (04.08.2026): H2.1 Stufe 1
   (IP-Prüfung), H2.3 (Grenzen je IP), H2.5, H2.8, H2.9, H2.13, H2.14 Serverteil
   (Laststufe messen, `SERVER_BUSY`, `INFO` erweitern). Dazu **H2.4 und H2.7 aus
   H7 mitgenommen** — H2.4 war eher Aufräumen als Härtung, und H2.7 brauchte
   denselben Zähler wie die Lastmessung
3. ✅ **Beide Seiten, aber verträglich** (04.08.2026): H2.14 Anzeigeteil. Ein
   alter Client liest die neuen `INFO`-Felder nicht und zeigt weiter „8 Lobbys" —
   er sieht die Auslastung nicht, läuft aber normal. Brauchte deshalb **keinen**
   Versionsschnitt
4. ✅ **Protokolländerung, Versionsschnitt** (04.08.2026): H2.1 Stufe 2
   (Sitzungstoken), H2.12
5. ✅ Angriffstests (H4) in `tests/test_relais_absicherung.py`, 59 Prüfungen,
   vollständiger Testlauf (1531 grün). **`VERSION` und `required_version` stehen
   auf 0.7.0-beta** — ohne den Schnitt stünde ein alter Client nach dem Deploy
   bewegungslos im Rennen, weil seine `UDP_REGISTER` kein Token trägt. Server-Deploy
   und Abnahme stehen aus

### H4 Nachweis

Vorbild ist `tests/test_block_g_online.py`: echter Relay auf einem freien Port,
echte `NetworkClient`-Verbindungen. Der Unterschied ist die Absicht — hier wird
der Relay **angegriffen**, nicht bedient. Je Befund ein Test, der ihn
**vorher** festhält:

* fremden Slot per `UDP_REGISTER` übernehmen → muss abgewiesen werden
* Strecke mit tief verschachteltem JSON, ungültigem UTF-8, `1e400` anbieten →
  Empfänger lehnt ab und **läuft weiter**
* `OFFER_CHUNK` mit kaputtem base64, `_recv` mit ungültigem UTF-8
* mehr Verbindungen und Lobbys öffnen als erlaubt
* `SET_SETTINGS` mit 500 unbekannten Schlüsseln → Lobby wächst nicht
* Empfang von mehr als 1 MB in Stücken → Client bricht ab statt zu wachsen
* Dateinamen `CON`, `NUL`, `COM1` → landen nicht als Gerätename auf der Platte
* Aufnahmesperre (H2.14): über die Lobbygrenze hinaus hosten → `SERVER_BUSY`,
  **aber ein `JOIN` in eine bestehende Lobby geht weiter durch**
* `INFO` liefert Laststufe und `lobby_max`; ein Client, der die Felder nicht
  kennt, verhält sich unverändert

### H5 Was Block H nicht enthält

| Nicht enthalten | Warum |
|---|---|
| TLS auf TCP, HMAC auf UDP | H1 — Mitleser und Tunnelbetreiber sind nicht im Bedrohungsmodell. Bleibt als eigener Punkt für später, wenn sich das ändert |
| Benutzerkonten, serverseitige Freischaltungen | E4 hat das bereits abgewogen und verworfen: bei kosmetischen Belohnungen in einem kostenlosen Spiel nicht gerechtfertigt |
| Schutz gegen Cheating im Rennen (Positionen fälschen) | Jeder Peer simuliert sich selbst — das ist eine Architekturentscheidung, keine Lücke. Gehörte in eine autoritative Server-Simulation und ist ein eigenes Projekt |
| Automatisches Sperren von IPs | H6 — entschieden: nur protokollieren. Ein Fehlalarm hinter geteilter IP schließt einen echten Mitspieler aus, und die Pflege lohnt bei dieser Spielerzahl nicht |
| UDP-Rate je Slot, Größengrenze für `lobby.settings` | H7 — von der gewählten Grenzenauswahl nicht abgedeckt, mit Empfehlung dort festgehalten |

### H6 Entschieden am 31.07.2026

| Frage | Entscheidung |
|---|---|
| H2.1: IP-Prüfung oder Token? | **Beides.** Stufe 1 sofort und ohne Versionsschnitt, Stufe 2 mit dem nächsten Pflicht-Update |
| Welche Grenzen? | **Je IP-Adresse**: gleichzeitige Verbindungen, offene Lobbys, Anfragerate. Dazu eine Gesamtobergrenze und die Aufnahmesperre aus H2.14 |
| Nachweis? | **Angriffstests gegen einen echten Relay** (H4). Bei einem Sicherheitsblock ist „behauptet" zu wenig |
| Missbrauch? | **Nur protokollieren** — abgewiesene Pakete mit IP ins Log, damit die Grenzen nachjustierbar sind. Kein automatisches Sperren: ein Fehlalarm hinter geteilter IP schließt einen echten Mitspieler aus |

### H7 Erledigt statt offen

Hier standen **H2.4** (`lobby.settings` nimmt beliebige Schlüssel) und **H2.7**
(Verstärkung ×5 innerhalb der Lobby) als bewusst außerhalb von Block H. Der Rat
dort war, H2.4 mitzunehmen und H2.7 zusammen mit der Lastmessung zu erledigen,
weil dort derselbe Zähler entsteht.

Genau so ist es am 04.08.2026 gekommen — **beide sind drin**, siehe die Tabelle in
H2. H2.4 nimmt nur noch die 23 bekannten Schlüssel an und deckelt die Ablage auf
64 KB; die Liste ist zugleich die einzige Stelle, an der überhaupt steht, was in
`settings` liegen darf. H2.7 zählt je Slot in einem Sekundenfenster.

Ein Test hält die Erlaubnisliste an den Client gebunden: er liest aus
`online_lobby_page.py`, welche Schlüssel dort gesetzt werden, und schlägt an,
sobald einer davon serverseitig nicht bekannt ist. Ohne das fiele beim nächsten
neuen Feld still etwas weg — und der Relay verteilt `settings` an alle, also
hätte es niemand gleich gemerkt.

### H8 Beim Bauen aufgefallen: hinter dem Tunnel gibt es keine IP

Entdeckt am 04.08.2026 beim Umsetzen von H2.3, und es ändert, **was die Grenzen
je IP auf welchem Server bedeuten**.

Hamburg hängt hinter zwei playit.gg-Tunneln. Deren Agent läuft auf dem
Heimserver selbst und verbindet sich nach `127.0.0.1` — **jeder** Spieler kommt
dort mit derselben Quelladresse an. Eine Grenze „12 Verbindungen je IP" hätte
Hamburg damit auf zwölf Spieler *insgesamt* gedeckelt und beim dreizehnten einen
echten Mitspieler abgewiesen. Nicht Härtung, sondern ein Eigentor.

Deshalb gibt es `TRUSTED_PROXIES` (Vorgabe `127.0.0.1,::1`): für solche Adressen
werden die Zähler je IP übersprungen. Die Folge, ehrlich aufgeschrieben:

| | Helsinki (direkter VPS) | Hamburg (hinter playit.gg) |
|---|---|---|
| Grenzen je IP | greifen vollständig | greifen **nicht** — alle sehen gleich aus |
| Gesamtgrenzen (Verbindungen, Lobbys) | greifen | greifen |
| Aufnahmesperre H2.14 | greift | greift — **hier ist sie der Hauptschutz** |
| UDP-Rate je Slot (H2.7) | greift | greift (sie zählt je Slot, nicht je IP) |
| Sitzungstoken (H2.1 Stufe 2) | greift | greift — und ist dort das **einzige**, was einen fremden Slot abhält, weil die IP-Prüfung nichts unterscheiden kann |

Das ist kein neuer Befund, sondern eine Präzisierung von H1: der Tunnelbetreiber
war schon vorher außerhalb des Bedrohungsmodells. Neu ist die Erkenntnis, dass
**auch die Angreifer hinter dem Tunnel** nicht auseinanderzuhalten sind. H2.14
war als Schutz gegen zwanzig echte Spieler gedacht; auf Hamburg ist sie
zusätzlich der Ersatz für die Grenzen je IP. Gut, dass sie im selben Block liegt.

Wer den Tunnel später gegen eine direkte Portweiterleitung tauscht, muss
`RACE_TRUSTED_PROXIES=""` setzen — dann greifen auch dort die Grenzen je IP.

### H9 Abnahme: was wo geprüft wird

Festgelegt am 05.08.2026, beim Testlauf nach dem ersten Deploy.

**Angriffstests gehören nicht gegen die Produktion.** Sie laufen gegen einen
lokal gestarteten Relay (`tests/test_relais_absicherung.py`, 59 Prüfungen, Teil
des normalen Testlaufs). Gegen Helsinki oder Hamburg wären sie falsch, und zwar
aus vier unabhängigen Gründen: eine Verbindungsflut ist von einem echten Angriff
nicht zu unterscheiden; sie kann den playit.gg-Tunnel drosseln; die Aufnahmesperre
absichtlich auszulösen sperrt gerade spielende Leute aus; und über eine Leitung
ist das Ergebnis nie reproduzierbar. Dazu messen die Grenzen je IP dort ohnehin
etwas anderes (H8).

**Gegen die echten Server gehört ein Rauchtest:** `python tools/relais_pruefen.py`.
Er fragt `INFO` ab, pingt UDP und öffnet **eine** Lobby, die er sofort wieder
schließt. Die wichtigste seiner Prüfungen ist, ob die neuen `INFO`-Felder
(`lobby_max`, `load`) überhaupt ankommen:

> `live_config.json` wird bei jeder Anfrage frisch gelesen, `server.py` **nicht**.
> Ein Pull ohne Neustart des Prozesses sieht in der Versionsanzeige völlig richtig
> aus und hat trotzdem keine der neuen Prüfungen an Bord. Die neuen Felder sind
> der Beweis, dass der neue Code läuft — und das fehlende Sitzungstoken in
> `JOIN_OK` wäre der Grund, warum danach jedes Rennen bewegungslos bliebe.

Das Werkzeug ist gegengeprobt: gegen einen Relay, dem man die neuen Felder und
das Token wegnimmt, meldet es genau diese zwei Fehler und gibt 1 zurück.

**Was nur am Spiel selbst prüfbar ist** (zwei Rechner, zwei Fenster):
Lobby aufmachen und beitreten, ein Rennen mit Bewegung auf beiden Seiten (das ist
der Ende-zu-Ende-Beweis für das Token), die Auslastung in der Serverauswahl, und
der Ankündigungskasten mit der Kennzeichnung „Servernachricht".

---

## 8. Arbeitsweise

Entschieden: **gebündelt je Themenblock**. Ich arbeite einen Block komplett ab
und lege das Ergebnis am Stück vor.

* je Block ein eigener Branch, Merge nach main erst nach deiner Abnahme
* Tests laufen vor jedem Merge vollständig — und seit dem 06.08.2026 bei
  jedem Push in der Pipeline. Stand 07.08.2026: **2161** (04.08.: 1531).
  Was sie erreichen, steht gemessen in §8a
* Server-Deploy nur wenn der Block den Relay berührt (Grand Prix online;
  Block D für das `paint`-Feld im Roster — zwei Zeilen, siehe D7, aber ohne
  Deploy sehen sich online alle im Werkslack; Block H fast vollständig)
* **Block H und der Rest von Block D gehören in denselben Release.** Beide
  ändern das Protokoll — die Lackierung im Roster und das Sitzungstoken. Zwei
  Pflicht-Updates hintereinander vergrätzen Spieler, eines ist zumutbar.
  **Stand 04.08.2026:** Block H ist fertig und hebt `required_version` auf
  0.7.0-beta. Damit ist der Pflichtschnitt gesetzt; D7 (`paint` im Roster) fährt
  ohne eigenen Schnitt mit, **wenn es vor dem Deploy landet** — danach bräuchte
  es einen zweiten Server-Deploy, aber kein zweites Update
* Playtest-Funde sammeln sich in `playtest_findings.md`

---

## 8a. Was die Tests erreichen — gemessen, nicht geschätzt

Am **07.08.2026** zum ersten Mal gemessen statt vermutet: `coverage` über die
ganze Suite. Das Ergebnis erklärte, warum Funde immer aus derselben Ecke kamen.

**Vorher 61 % über alles** — und die drei Bereiche, aus denen die meisten
Meldungen kamen, waren die schlechtesten:

| Modul | vorher | nachher |
|---|---|---|
| `states/race_state.py` (1616 Zeilen, größte Datei) | 38 % | **64 %** |
| `states/editor_state.py` | 19 % | **66 %** |
| `core/gamepad.py` | 20 % | **59 %** |
| `hud/hud.py` | 23 % | **82 %** |
| `track/track_renderer.py` | 15 % | **84 %** |
| `track/lap_tracker.py` | 29 % | **99 %** |
| `core/ghost.py` | 29 % | **79 %** |
| `entities/components/physics_body.py` | 24 % | **98 %** |
| `states/menu_shell_state.py` | 36 % | **66 %** |
| **gesamt** | **61 %** | **76 %** |

Das Muster war überall dasselbe: geprüft war, was gemeldet worden war. Jeder
Fund hatte seinen Test bekommen, die **Regel** dahinter aber nie.

### Vier neue Testarten

1. **`test_rennsimulation.py` — Rennen wirklich fahren.** Bis dahin hat kein
   einziger Test ein Rennen gefahren. Ein volles Feld über eine Runde kostet
   rund vier Sekunden, weil nichts gezeichnet wird. Gefahren wird über alle
   mitgelieferten Strecken, alle fünf Klassen (je Klasse ein Auto pro Modell,
   also wirklich alle 15 Fahrzeuge) und alle drei Schwierigkeiten. Zugesagt
   wird, was ohne Ausnahme gelten muss: das Rennen **endet**, kein Auto
   verlässt die Welt, keine Zahl wird `nan`, Runden zählen nur vorwärts und nie
   über das Ziel hinaus, kein Startplatz doppelt.

2. **`test_layout_regeln.py` — Überlagerungen als Regel.** `theme.text` gibt
   das Rechteck zurück, in das es gemalt hat; der Test belauscht es und
   vergleicht. Verglichen wird die **Tinte**, nicht der Schriftkasten — der
   erste Anlauf verglich Kästen und meldete vier Fehler, von denen keiner zu
   sehen war (die Überschrift „WERTUNG & FAHRER" belegt y=165..195, die
   Spaltenköpfe y=186..208, die Zeichen selbst lassen 4 px Luft). Über jede
   Seite, jeden Reiter, in Deutsch **und** Englisch, weil deutscher Text länger
   ist.

3. **`test_controller_durchlauf.py` — Controller ohne Controller.** Der
   `GamepadManager` verlangt von einem Joystick vier Methoden, kein Gerät.
   Damit läuft die ganze Übersetzung — D-Pad, Stick, Totzone, Wiederholung,
   Gerätetrennung — auch auf dem Bauknecht, wo nie ein Pad stecken wird.
   Gefahren wird durch die **echte** Menüschale: ESC und Controller-B
   beantwortet `MenuShellState`, nicht die Seite. Der erste Anlauf schickte die
   Ereignisse an die Seite und meldete neunmal einen Fehler, den es nicht gab.

4. **`test_affentest.py` — zufällige Eingaben.** Eine Zusage: es bricht nichts.
   Fester Startwert, damit ein Fund nachstellbar bleibt. Er hat sich sofort
   bezahlt gemacht (siehe unten).

Gemeinsame Bausteine liegen **einmal** in `tests/spielhilfe.py` — die Lehre vom
06.08.2026, als die Relay-Hilfe dreimal wortgleich im Baum lag und damit
derselbe Fehler dreimal.

### Was dabei herauskam

Zwei echte Fehler im Spiel, beide vorher unbemerkt:

* **Jedes Offline-Rennen ließ einen Rückruf am Ereignisbus hängen.** `enter()`
  meldet `impact_vehicle_vehicle` bedingungslos an, `exit()` meldete es nur
  `if self._online` ab — eine Änderung vom 04.08.2026, bei der eine der beiden
  Seiten stehengeblieben ist.
* **Absturz in der Profilseite.** `_sichtbar_h` wurde nur beim Zeichnen
  gesetzt, aber schon beim Verarbeiten gelesen; wer die Seite mit einer
  laufenden Radbewegung öffnete, traf auf einen `AttributeError`.

Beide stehen mit Ursache in `playtest_findings.md`.

### Grenzen, damit sie nicht vergessen werden

* Die Überlagerungsregel sieht nur, was über `theme.text`/`theme.text_fit`
  läuft. Das **HUD** malt mit rohem `screen.blit` und ist davon nicht erfasst.
* Der Affentest findet Abstürze, keine Denkfehler. Ob ein Ergebnis sinnvoll
  ist, weiß er nicht.
* Das Spiel zeichnet immer in eine feste Fläche von 1920×1080 und skaliert
  erst aufs Fenster. Fenstergrößen zu variieren prüft deshalb nichts — der
  erste Anlauf tat es und meldete 35 Fehler, die alle keine waren.
* Was Automatik nicht kann, bleibt beim Spielen: Fahrgefühl, Balance, ob eine
  Farbe gut aussieht, ob der Motor gut klingt.

### Laufzeit

Die Suite wächst von 1984 auf **2161 Tests** und von 1:49 auf **4:16**.
Entschieden am 07.08.2026: **alles läuft bei jedem Push.** Vier Minuten
Rückmeldung sind der Preis dafür, einen Fehler am Tag seiner Entstehung zu
sehen statt am Tag des Releases.

### Zwei Lehren über die Tests selbst

Beide Male war der erste Befund nicht der richtige:

* **Prozessweiter Zustand.** Die Renntests waren einzeln grün und im vollen
  Lauf rot. Ursache war nicht das Rennen, sondern der `EventBus` — ein
  Singleton, in dem nach rund 1480 Tests **88** fremde Rückrufe hängen.
  Fahrzeugnummern beginnen in jedem Rennen wieder bei 1, also greifen alte
  Rundenzähler auf die Nummern des laufenden Rennens zu. Dasselbe in Grün beim
  `race_setup`, das der Controller-Durchlauf verstellte.
* **Tests schreiben nichts in den Arbeitsbaum.** Der Affe fand in Fahrzeug- und
  Klanglabor den Speichern-Knopf; beide schreiben über relative Pfade zurück
  nach `data/`. Die Umlenkung in `conftest.py` gilt nur für Nutzerdaten.
  Aufgefallen ist es allein an `git status` — jetzt steht die Regel als eigener
  Test da.


## 9. Risiken

| Risiko | Auswirkung | Umgang |
|---|---|---|
| Unbunte Fahrzeuge lassen sich mit Reglern allein nicht umfärben (noch offen: Rookie_3 weiß, Electric_3 fast schwarz) | Werkstatt wirkt unfertig | Rookie_2 ist am 30.07. mit Helligkeitsfenster auf 72,4 % Abdeckung gefallen — das Fenster trägt weiter als gedacht. Reicht es bei den anderen zwei nicht: Ausschlussrechtecke, dann Pinsel. Ablauf in D6 |
| Schrift kennt `↺ ↻ ◀ ▶ ✓` nicht (gemessen 30.07.) | leere Kästchen als Knopfsymbol im Auslieferungsbuild | nur `‹ › « » ● ▲ ▼ ♦ √` verwenden; Drehknöpfe tragen `‹ ›` mit Textbeschriftung. In D4 festgehalten |
| Sichtprüfung der Umfärbung nur im Labor, kein Kontrollblatt (D6) | ich kann kein Ergebnis vorlegen, die Abnahme hängt vollständig an dir | bewusst so entschieden; ich melde Maskenabdeckung je Fahrzeug als Zahl, damit wenigstens Ausreißer auffallen |
| ~~Lackierung im Wire-Format~~ | — | **entfällt.** Die Lackierung reist im TCP-Roster (D7), das UDP-Format bleibt unangetastet, `required_version` bleibt stehen. Alter Server und alter Client gehen beide sanft aus |
| Server-Deploy für zwei Zeilen im Relay (D7) | Lackierung online unsichtbar, bis der Heimserver läuft | Deploy war für Block D in §8 ohnehin vorgesehen; ohne ihn sehen alle einander im Werkslack, es bricht nichts |
| Kurzweg Fahrzeugauswahl → Werkstatt hat drei Rückwege und keinen Test (D10) | man landet nach dem Lackieren in der falschen Lobby oder verliert die Streckenwahl | jeder Weg von Hand geprüft; die Stelle ist als wahrscheinlichster Fehler benannt |
| Online-GP hängt am Host | Serie stirbt mit dem Host | bewusst akzeptiert, muss dem Gast klar angezeigt werden |
| Motor-Synthese klingt billig | schlechter als kein Sound | früh einen Prototyp hörbar machen, notfalls doch Samples |
| macOS-Build ungetestet | kaputte Auslieferung | entweder testen oder nicht anbieten |
| Kein Spieler online | Online-MP wirkt tot | Statusseite zeigt Lobbys; ggf. später Lobby-Browser |
| Verkehr bleibt im Klartext (Block H ohne TLS) | playit.gg und jeder im Netzpfad lesen und ändern alles, inkl. übertragener Streckendateien | **bewusst akzeptiert** (H1), und seit 05.08.2026 auch bewusst **nicht ausgewiesen**: der Hinweis stand einen Tag unter „Info" und ist auf Wunsch wieder heraus, in die itch.io-Beschreibung kommt er nicht. Das Risiko bleibt damit unverändert bestehen und steht nur noch hier |
| Kein Signaturzertifikat | „Unbekannter Autor" beim ersten Start; ein Teil der Spieler bricht die Installation ab | **bewusst getragen** (05.08.2026). Zertifikate werden nicht gekauft; kein Code ändert daran etwas |
| Sitzungstoken (H2.1 Stufe 2) ist eine Protokolländerung | alte Clients kommen nicht mehr online | mit der Lackierung im Roster (D7) in **einen** Release und `required_version` einmal anheben, nicht zweimal |
| Grenzen je IP treffen geteilte Anschlüsse | zwei Spieler im selben Haushalt kommen nicht beide rein | Grenzen großzügig (3 Verbindungen, 2 Lobbys je IP); H2.1 Stufe 2 macht die IP-Prüfung dort ohnehin entbehrlich |
| Aufnahmesperre (H2.14) greift zu früh | echte Spieler werden abgewiesen, obwohl der Server könnte | Schwellen aus dem Log nachjustieren (H6), nicht vorab raten; `JOIN` bleibt immer offen, betroffen ist nur das Neu-Hosten |
| Angriffstests brauchen echte Sockets | Testlauf wird langsamer und auf CI-Rechnern wackliger | freie Ports wie in `test_block_g_online.py`, kurze Zeitgrenzen; wenn es klemmt, als eigene Testmarke laufen lassen |
