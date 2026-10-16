# Online-Synchronisation: Gegenwarts-Vorhersage (1.1.0)

Gilt für das 3D-Spiel. Der Relay (`server/server.py`) gehört beiden Spielen; seine einzige
Änderung hier ist das längere PONG (siehe 2.1), das 2D-Spiel liest es unverändert.

## 1. Problem

Ferne Autos wurden per Snapshot-Interpolation gezeichnet: um Laufzeit (Absender → Relay →
Gegenstelle) **plus** 40–150 ms Puffer in der Vergangenheit. Bei 200 km/h (55 m/s) sind das
4–10 m. Beide Spieler sahen sich selbst vorn, ein Rempler traf ein Auto, das in Wahrheit
weiter vorn fuhr. Die frühere Dead-Reckoning-Fassung (bis 06.10.2026) setzte bei jedem Paket
die Hochrechnung hart zurück und zog das Abbild sichtbar rückwärts; das darf sich nicht
wiederholen.

## 2. Aufbau

### 2.1 Gemeinsame Uhr (`src/net/uhrsync.py`)

NTP-Art über die vorhandenen UDP-`PING`/`PONG`. Das PONG trägt neben dem zurückgespiegelten
PING-Stempel die Relayzeit (`!B d d`, 17 Byte; die ersten 9 Byte sind das alte PONG):

```
rtt = t3 - t0          offset = Ts - (t0 + t3) / 2     (Relayuhr minus eigene Uhr)
```

* **Min-RTT-Filter**: aus den letzten 24 Proben (höchstens 40 s alt) zählen nur die mit
  `rtt <= rtt_min + 3 ms`; ihr Versatz wird gemittelt (Warteschlangen machen die Laufzeit nur
  größer, nie kleiner).
* Der benutzte Versatz folgt dem Ziel in kleinen Schritten (25 % der Abweichung, mindestens
  0,3 ms je Probe), damit nichts ruckelt; ein Sprung über 250 ms wird sofort übernommen.
* Anlauf: bis 8 Antworten da sind, wird alle 0,25 s gepingt, danach jede Sekunde. Der
  Abgleich steht damit lange vor dem Rennstart.
* Fehler: höchstens `rtt/2` je Seite, bei symmetrischer Leitung ≈ 0. Das Alter eines Pakets
  hängt von der Differenz beider Fehler ab (10 ms Asymmetrie am Empfänger = 5 ms = 0,3 m).

### 2.2 Paketformat (`src/net/protocol.py`)

Die Fahrzeugkörper bleiben **unverändert 29 Byte** (`VEHICLE_FMT`), der Kopf 17 Byte
(`send_time` = monotonic des Absenders, bleibt streng wachsend). Neu ist ein **Anhang hinter
den Fahrzeugen**: wer nach `car_count` Körpern aufhört (Relay `schutz.py`, 2D-Spiel), sieht
ihn nie.

| Teil | Bytes | Inhalt |
|---|---|---|
| Kopf | 10 | Marke `0xE1`, Flags (Bit 0: Versatz gültig), `clock_offset` (d) = Relayuhr − Uhr des Absenders |
| je Auto | 4 | Lenkung (b, −127..127), Gas (b, negativ = rückwärts), Bremse (B, 0..255), Flags (Bit 0: Handbremse) |

Ein Auto: 17 + 29 + 10 + 4 = **60 Byte**, sechs Autos 225 Byte. Der Anhang wird nur gelesen,
wenn seine Länge genau zu `car_count` passt (beschädigt/alt → ignoriert). Mit `send_time` und
`clock_offset` des Absenders und dem eigenen Versatz kennt der Empfänger das **Alter jeder Lage
beim Eintreffen** (`NetworkClient.alter_von`, im Empfangsthread berechnet). Gesendet wird mit dem
Zeitpunkt des letzten Physikschritts, nicht mit dem Moment des Absendens.

### 2.3 Hochrechnung (`src/net/vorhersage.py`, `RemoteVehicle`)

Das Abbild wird nicht in der Vergangenheit gezeichnet, sondern **jetzt**: vom neuesten Paket um
sein Alter hochgerechnet (höchstens `PREDICT_MAX` = 0,3 s), bezogen auf den Zeitpunkt des
letzten Physikschritts des eigenen Autos (`bezug_setzen`), damit eigenes und fernes Auto im
selben Augenblick gelten.

* Tempo: geschätzte Beschleunigung aus den letzten Paketen (geglättet, begrenzt), klingt mit
  τ = 0,35 s ab; nie unter null.
* Richtung: Kreisbogen mit der gemeldeten Gierrate, Mittelpunktregel in 10-ms-Schritten.
* Eingaben als Vorwissen: aus der Lenkeingabe folgt eine Soll-Gierrate (Einspurmodell mit dem
  Lenkausschlag des Spiels, begrenzt durch die Querhaftung `grip·380·0,9`), der die Gierrate
  mit τ = 0,12 s zustrebt — das Auto schwenkt nach dem Lenkausschlag erst mit Verzug ein, die
  Eingabe weiß es eine Rampe früher. Aus bei Handbremse und bei Schräglauf > 11°.
* Jenseits der Frist (Verlust, Pause, Absturz des Gegners) wird nichts mehr gerechnet; das
  Abbild läuft nur noch mit dem Tempo von damals aus (τ = 0,4 s, höchstens 1 s), steht dann.

### 2.4 Weiches Nachführen

Ein neues Paket verschiebt die hochgerechnete Bahn. Der Unterschied wird **nicht gesprungen**,
sondern als Versatz abgebaut (derselbe Mechanismus wie bisher, `_versatz_abbauen`): mit
10/s, je Bild höchstens ein halber Bildschritt des Pfads — die Korrektur kann ein
vorwärts fahrendes Auto bremsen oder beschleunigen, aber nie rückwärts ziehen. Auch der Winkel
wird übergeblendet. **Sprung** nur, wenn der Absender selbst springt (Weg zwischen zwei Paketen
passt nicht zu seinem Tempo: Reset auf die Strecke, `TELEPORT_DISTANCE` = 12 m) oder der
Rückstand 36 m übersteigt. Nach einem Funkloch liegt das Abbild weit zurück, obwohl niemand
gesprungen ist: das wird eingeholt.

### 2.5 Rückfall und Schalter

Die Interpolation (Puffer, Wiedergabeuhr, Hermite) läuft unverändert mit. Das Gewicht `_w`
(0 = Interpolation, 1 = Vorhersage) wandert weich (1/s hin, 2/s zurück):

* kein gültiges Alter (älterer Relay ohne Relayzeit im PONG, noch kein Abgleich, Absender
  nicht abgeglichen, Alter außerhalb von −50..1000 ms): 5 ungültige Pakete in Folge → zurück,
  10 gültige → wieder Vorhersage,
* Schwankung des Alters über 100 ms (geglättet) blendet stufenlos zurück, ab 300 ms reine
  Interpolation. Die Messung (4) zeigt, dass die Vorhersage auch auf sehr schlechten Leitungen
  besser ist als die Interpolation; die Schwelle fängt nur kaputte Uhren und Extremfälle ab.

`RACE_NETZ_MODUS=interpolation` (Umgebung) erzwingt die Interpolation für A/B-Vergleiche;
`vorhersage` ist die Vorgabe. Je Fahrzeug: `rv.modus`.

### 2.6 Kollisionen, Rangliste, KI

* Der kinematische pymunk-Körper folgt der gezeichneten (= vorhergesagten) Lage und
  Geschwindigkeit; `UDP_BUMP` und die Berührung am Geist rechnen damit.
* Runde/Wegpunkt (`lap`, `wp`) kommen unverändert aus dem neuesten Paket; Rangliste und Zielerkennung
  hängen nicht an der Hochrechnung.
* Vom Host gestreamte KI-Autos laufen über denselben Weg (Eingaben stammen aus `steer_input`
  usw. der KI).

## 3. Messstand

`python tools/netz_messung.py` (`--kurz`: nur die Hauptleitung). Der Absender fährt mit der
**echten** Fahrzeugphysik (Supercar, `Vehicle.update` + pymunk, 60 Hz) eine feste Fahrt:
Beschleunigung auf 200+ km/h, Vollbremsung, Schikane, Gerade, zweite Bremsung mit
seitlichem Rempler (3,5 m/s), Kurve, Drift mit Handbremse und Gegenlenken. Daraus entsteht
ein Strom wie im Spiel (50 Hz aus der 60-fps-Schleife, UDP über den simulierten Relay mit
Laufzeit je Strecke, exponentiell verteilter Schwankung, Vertauschung durch die Schwankung,
Verlust, Funkloch) und ein `RemoteVehicle` auf virtueller Uhr. Die Uhren von Absender, Relay
und Empfänger sind gegeneinander um Tausende Sekunden verschoben; der Abgleich läuft über
`UhrSync` mit simulierten PING/PONG. In jedem Bild (60 fps) wird die gezeichnete Lage mit
der wahren Lage des Absenders **zum selben Zeitpunkt** verglichen (ab 3 s; 1 px = 0,08 m).

## 4. Ergebnis

Fehler in Metern; „G+B" = nur Geraden und Bremsungen. „Zurück" = Bilder, in denen sich das
Abbild bei Tempo > 3 m/s mehr als 2 cm gegen die Fahrtrichtung bewegt. „Bildabw." = größte
Abweichung der Bildbewegung des Abbilds von der wahren Bildbewegung (Maß für Ruck/Korrektur
je Bild).

| Leitung (Hin/Zurück, Schwankung) | Modus | Mittel | p95 | Max | G+B Mittel | G+B p95 | Zurück | Bildabw. max |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 15 ms, 2 ms | Interpolation (alt) | 3,55 | 4,81 | 4,97 | 3,53 | 4,69 | 0 | 0,058 |
| | Vorhersage (neu) | 0,02 | 0,10 | 0,36 | 0,01 | 0,01 | 0 | 0,058 |
| **30 ms, 5 ms (Hauptfall)** | Interpolation (alt) | 5,42 | 7,27 | 7,62 | 5,38 | 7,20 | 0 | 0,059 |
| | **Vorhersage (neu)** | **0,05** | **0,23** | 0,73 | **0,03** | **0,07** | **0** | 0,079 |
| 30 ms, 5 ms, 3 % Verlust | Interpolation (alt) | 5,43 | 7,29 | 7,59 | 5,39 | 7,18 | 0 | 0,061 |
| | Vorhersage (neu) | 0,05 | 0,22 | 0,79 | 0,03 | 0,06 | 0 | 0,070 |
| 30/60 ms, 8 ms | Interpolation (alt) | 7,24 | 9,74 | 10,25 | 7,19 | 9,62 | 0 | 0,079 |
| | Vorhersage (neu) | 0,07 | 0,36 | 1,11 | 0,03 | 0,09 | 0 | 0,142 |
| 30 ms, 5 ms, Ping-Asymmetrie 10 ms (Uhrfehler 5 ms) | Interpolation (alt) | 5,42 | 7,27 | 7,62 | 5,38 | 7,20 | 0 | 0,059 |
| | Vorhersage (neu) | 0,49 | 0,65 | 1,04 | 0,47 | 0,62 | 0 | 0,093 |
| 60 ms, 10 ms, 5 % Verlust | Interpolation (alt) | 9,01 | 12,17 | 12,66 | 8,98 | 12,06 | 0 | 0,100 |
| | Vorhersage (neu) | 0,10 | 0,46 | 1,75 | 0,05 | 0,15 | 0 | 0,167 |
| 60 ms, 20 ms, 10 % Verlust | Interpolation (alt) | 10,80 | 14,47 | 15,22 | 10,74 | 14,35 | 0 | 0,109 |
| | Vorhersage (neu) | 0,11 | 0,47 | 1,94 | 0,06 | 0,16 | 0 | 0,179 |
| 30 ms, 5 ms, 0,4 s Funkloch (gebündelt) | Interpolation (alt) | 5,52 | 7,57 | 10,35 | 5,51 | 7,53 | 0 | 0,225 |
| | Vorhersage (neu) | 0,05 | 0,29 | 0,93 | 0,03 | 0,08 | 0 | 0,220 |
| 30 ms, 5 ms, 0,4 s Funkloch (Verlust) | Interpolation (alt) | 5,42 | 7,27 | 7,62 | 5,38 | 7,20 | 0 | 0,888 |
| | Vorhersage (neu) | 0,07 | 0,39 | 2,46 | 0,05 | 0,10 | 0 | 0,382 |
| 100 ms, 40 ms, 15 % Verlust | Interpolation (alt) | 16,03 | 21,75 | 22,83 | 15,86 | 21,21 | 0 | 0,187 |
| | Vorhersage (neu) | 0,29 | 0,98 | 3,06 | 0,17 | 0,55 | 0 | 0,257 |

Ziele (30 ms je Strecke, 5 ms Schwankung): Mittel < 1 m — **0,05 m**; p95 < 2 m auf Geraden und
beim Bremsen — **0,07 m** (alle Phasen 0,23 m); keine Rückwärtssprünge — **0**; je Bild
höchstens 8 cm Abweichung von der wahren Bewegung. Die Lenkeingaben halbieren den Fehler in
der Schikane (p95 0,15 → 0,07 m).

Der größte Einzelfehler (Rempler, Drift, Funkloch) bleibt unter 3 m. Die Interpolation liegt
konstant um Laufzeit + Puffer (5–16 m) zurück.

## 5. Grenzen

* **Uhrfehler**: ungleiche Hin-/Rückstrecke zum Relay verschiebt das Bild um die halbe
  Asymmetrie (5 ms ≈ 0,3 m bei 200 km/h). Im Test 0,5 m bei 10 ms Asymmetrie. Nicht
  messbar von innen.
* **Unvorhersehbares**: ein Rempler, ein plötzlicher Dreher oder Wandtreffer des Gegners
  wird erst mit dem nächsten Paket (≈ 70 ms später) sichtbar und dann in ~0,2 s eingeblendet.
* **Funkloch > 0,3 s**: das Abbild läuft mit abklingendem Tempo aus und holt danach auf
  (bis 0,4 s Loch: Fehler < 2,5 m).
* Gemessen mit einem Fahrzeug (Supercar) und Skript-Eingaben; echte Spieler lenken
  ruckartiger, die Tendenz (Eingaben helfen in Kurven, Rest folgt aus Alter und Beschleunigung)
  bleibt.
* Nicht geändert: Startsynchronisation (`einfache_laufzeit_s`, `RACE_GO`), Schutz im Relay
  (liest nur die wahren Lagen des Absenders), Streckenaustausch.
