# Fahrer-KI neu: Bahnplaner, Taktik, vier Stufen — Entwurf

Stand 30.09.2026, vom Besitzer freigegeben (Ansatz „Frenet-Planer").

## 1. Ziel

Die KI-Gegner sollen sich wie in üblichen Rennspielen anfühlen: nicht auf
Schienen, echtes Überholen und Verteidigen, vier klar gestufte
Schwierigkeiten. Sie muss auf **jeder** Strecke (auch frisch im Editor gebaut)
**sofort** fahren — kein Training, keine Streckendaten.

Nicht-Ziele: lernende Verfahren, einstellbare Regler für den Besitzer,
KI-Labor.

## 2. Befund der alten KI (`src/ai/ai_controller.py`)

- Eine feste Linie je Auto, `steering_noise`/`line_deviation` = 0 → jede Runde
  identisch.
- Auch „hard" nutzt nur 70 % der Haftung (`grip_usage`), `speed_scale` 0,88 —
  der reine Verfolgungs-Lenkregler (Pure Pursuit) hält den Grenzbereich nicht.
- Überholen = Zielpunkt 70 px zur Seite schieben, erst unter 90 px Abstand,
  dabei auf 90–95 % des Vordermanns abbremsen → hängt hinten dran.
- Verteidigen nur, wenn niemand vorn ist.

## 3. Entscheidungen des Besitzers

| Frage | Antwort |
|---|---|
| Ansatz | Bahnplaner im Streckenkoordinatensystem (Frenet), deterministisch |
| Stufen | 4: Anfänger, Fortgeschritten, Profi, Meister |
| Aufholhilfe | nur Anfänger und Fortgeschritten |
| Zweikampf | fair, hart verteidigen (ein Spurwechsel), kein absichtliches Rammen |
| KI-Labor | entfernen, stattdessen Mess-Werkzeug |
| Abstimmung | Besitzer gibt nur kurze Rückmeldungen („Profi zu leicht") |

## 4. Aufbau

Neue Module in `src/ai/`. Die Schnittstelle nach außen bleibt:
`AIController(vehicle, track, stufe)` mit `compute_inputs(dt) ->
(gas, bremse, lenkung)`, dazu die heute genutzten Attribute (`racing_line`,
`opponents`, `speed_multiplier`, `dbg_*`, Grid-Spurhalten, Befreien aus der
Wand). Rennen, Ghost-Erzeugung und KI-Übernahme nach dem Ziel laufen ohne
Umbau weiter.

| Modul | Aufgabe | hängt ab von |
|---|---|---|
| `strecke_frenet.py` | Mittellinie als Bogenlänge `s`, Querversatz `d`, halbe Fahrbahnbreite, Normale je Stützpunkt; `xy_zu_sd`, `sd_zu_xy`, Krümmung; einmal je Strecke gebaut und im Track-Objekt zwischengespeichert | `Track.centerline`, `track_width` |
| `racing_line_solver.py`, `speed_profile.py` (vorhanden) | Ideallinie und Geschwindigkeitsprofil; Haftungsanteil kommt jetzt aus der Stufe | Fahrzeugwerte |
| `regler.py` | Bahnverfolgung: Lenkung = Vorsteuerung aus Bahnkrümmung (Einspurmodell) + Stanley-Rückführung auf Quer- und Winkelfehler; Längsregler mit Brems-Vorsteuerung aus dem Profil | Frenet, Fahrzeugwerte |
| `planer.py` | 10 Hz je Auto: Kandidatenbahnen über 2,5 s (Querversatz-Ziele im Korridor × 2–3 Übergangslängen, quintische Übergänge in `d(s)`), Gegner mit konstanter Geschwindigkeit entlang `s` vorhergesagt; Kosten: Zeitverlust gegen Profil, Wandnähe, Kollisionsrisiko (Fahrzeugrechtecke mit Sicherheitsabstand), Abweichung von der Ideallinie, Taktikwunsch, Wechselstrafe gegen Zappeln. Liefert gewählte Bahn + Tempodeckel | Frenet, Profil, Taktik |
| `taktik.py` | Zustände *Frei, Folgen, Windschatten, Angriff, Nebeneinander, Verteidigen*; setzt Wunschseite, Bremspunkt-Verschiebung, Kostengewichte. Angriff bevorzugt Bremszonen (Profil fällt stark ab) auf der Kurveninnenseite; Verteidigen = ein Spurwechsel zur Innenseite vor der Bremszone, danach halten | Frenet, Gegnerliste |
| `stufen.py` | vier feste Stufen, siehe 5.; ersetzt `difficulty.py` | – |
| `fahrer.py` | Persönlichkeit je KI-Fahrer aus fester Startnummer: kleine Abweichungen (±) bei Bremspunkt, Kurventempo, Konstanz, Angriffslust; Fehlerereignisse (verbremst, zu weit raus) nach Stufe, per `random.Random(seed)` | Stufe |
| `ai_controller.py` | dünne Hülle: Taktik → Planer → Regler, Befreien, Grid-Spurhalten, Aufholhilfe | alles oben |

Datenfluss je Bild: Position → Frenet (`s`, `d`) → (alle 0,1 s) Taktik und
Planer → Regler → Eingaben. Zwischen Planerläufen folgt der Regler der
zuletzt gewählten Bahn.

**Deterministisch** heißt: nichts wird gelernt; Zufall nur aus festem Seed je
Fahrer, also reproduzierbar in Tests und Online-Rennen.

## 5. Die vier Stufen

Geeicht gegen die Rundenzeit von *Meister* mit demselben Auto auf derselben
Strecke (freie Fahrt, allein):

| Schlüssel | Anzeige | Rundenzeit | Verhalten |
|---|---|---|---|
| `easy` | Anfänger | +11 … +14 % | früh bremsen, weite Linien, überholt nur auf Geraden mit viel Platz, verteidigt nicht, Fehler öfter, Aufholhilfe |
| `medium` | Fortgeschritten | +5 … +7 % | überholt auf Geraden, verteidigt selten, kleine Fehler, leichte Aufholhilfe |
| `hard` | Profi | +2 … +3,5 % | greift in Bremszonen an, verteidigt, selten Fehler, keine Hilfe |
| `expert` | Meister | 0 (≈ 97 % Haftung) | späte Bremspunkte, alle Taktiken, kaum Fehler, keine Hilfe |

Je Stufe nur wenige interne Werte (Haftungsanteil, Bremsanteil,
Bremspunkt-Vorhalt, Fehlerrate, erlaubte Taktiken, Mut im Zweikampf,
Aufholhilfe). Sie stehen fest in `stufen.py`, nichts wird gespeichert.

**Aufholhilfe** (nur `easy`, `medium`): Liegt die KI weit vor dem besten
Menschen, sinkt ihr Tempo leicht; liegt sie weit dahinter, steigt ihr Mut
(nicht über die Stufe darüber). Kein Teleportieren, keine Physik-Tricks.

**Übergang der Schlüssel:** `easy/medium/hard` bleiben (Speicherstände,
Online-Protokoll, Editor-Entwürfe), `expert` kommt dazu. Angezeigte Namen
ändern sich in Lobby, Online-Lobby, Editor, Fahrerliste. Der Server reicht
`ai_difficulty` nur durch — keine Änderung dort. Ghost und KI-Übernahme
nutzen `expert`.

## 6. Entfernen

KI-Labor im Dev-Modus (`src/states/dev_state.py`, Knopf in
`settings_page.py`), `data/ai_settings/`, `DifficultyConfig`-Felder, die nur
das Labor brauchte, `trajectory_optimizer.py` falls danach unbenutzt.

## 7. Fehlerfälle

- Strecke ohne brauchbare Mittellinie: Rückfall auf Wegpunkte (wie heute).
- Keine gültige Kandidatenbahn (eingeklemmt): Planer nimmt die Bahn mit dem
  geringsten Kollisionsrisiko und senkt das Tempo; Befreien (Rückwärts) bleibt.
- Auto neben der Fahrbahn (`|d|` > Korridor): Planer erzeugt nur Bahnen zurück
  in den Korridor.
- Rechenzeit: Planer höchstens ~0,3 ms je Auto und Lauf (gemessen in
  `tools/rennen_probe.py`); Bildzeit-Ziel bleibt ≤ 16 ms bei „hoch".

## 8. Prüfen

- `tools/ki_messung.py` (ohne Grafik, schneller als Echtzeit): je Strecke
  (alle mitgelieferten + zwei erzeugte Editor-Strecken) und Stufe freie
  Rundenzeiten; dazu Feldrennen 8 Autos gemischt: Überholungen,
  Wandkontakte, Auto-Auto-Kontakte, Hänger, Zieleinläufe. Ausgabe als Tabelle.
- Tests (pytest): Frenet-Umrechnung hin und zurück; Regler hält einen Kreis
  bei 95 % Haftung ohne Rutschen; Planer weicht einem stehenden Auto aus und
  überholt ein langsameres; Stufen-Reihenfolge und Zielbänder auf einer
  Teststrecke; frische Editor-Strecke: alle Stufen kommen ohne Hänger ins
  Ziel; gleicher Seed → gleiche Eingaben.
- Bestehende Tests `tests/test_ai.py`, `tests/test_ki_fremde_fahrzeuge.py`
  werden auf die neue Schnittstelle angepasst, ihr Verhalten bleibt geprüft.
- Zum Schluss: Besitzer fährt je Stufe ein Rennen und gibt kurze Rückmeldung.

## 9. Vorbedingung Fahrphysik

Wandkontakt kostet heute zu wenig (Besitzer, 30.09.). Wird die Fahrphysik
geändert, geschieht das **vor** dem Einmessen der Stufen (letzte
Planaufgabe); danach Prüfsummen neu (`tools/pruefsummen.py`). Die KI selbst
leitet alles beim Laden aus den Fahrzeugwerten ab und braucht keine Anpassung.

## 10. Umsetzung

Plan unter `docs/superpowers/plans/`, Aufgaben einzeln an günstige
Sub-Agents (englische Aufträge), je Aufgabe Test + Review, Messung am Ende.
