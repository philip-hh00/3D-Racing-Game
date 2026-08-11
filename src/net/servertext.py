"""Text vom Relay auf Anzeigbares begrenzen (Block H, H2.12).

Der Relay schickt Text, den das Spiel **anzeigt**: Ankündigungen aus
``live_config.json`` und die Begründung einer Absage (``reason``). Beides landete
ungeprüft im Menü. Ein bösartiger oder übernommener Relay konnte damit jeden
Text einblenden — in einem Fenster, das aussieht wie das Spiel selbst. Das ist
Phishing mit fremdem Briefkopf, und es kostet nichts, es abzustellen.

Drei Regeln, und alle drei sind Anzeige, nicht Vertrauen:

* **Länge.** Ein Text, der über den Bildschirm hinauswächst, verdeckt alles
  andere — auch den Knopf, mit dem man ihn schließt.
* **Zeichen.** Steuerzeichen, Zeilenumbrüche in Massen und die unsichtbaren
  Richtungszeichen aus dem Unicode-Bereich für Rechts-nach-links-Schrift. Mit
  letzteren lässt sich die Leserichtung eines Satzes umdrehen, ohne dass man es
  sieht — ``„Datei sicher"`` liest sich dann anders, als sie geschrieben ist.
* **Herkunft.** Der Text wird als **Servernachricht** gekennzeichnet. Auch ein
  harmloser Hinweis soll nicht wie eine Aussage des Spiels aussehen.

Was hier **nicht** passiert: eine Inhaltsprüfung. Ob der Relay die Wahrheit
schreibt, kann das Spiel nicht wissen — es kann nur dafür sorgen, dass der Text
nichts kaputt macht und erkennbar von außen kommt.
"""
from __future__ import annotations

#: Zeichen je Text. Der Ankündigungskasten ist 900 px breit und umbricht selbst;
#: 600 Zeichen sind darin etwa zwölf Zeilen und füllen ihn gut aus.
MAX_ZEICHEN = 600
#: Zeichen in einer Überschrift — eine Zeile, nicht mehr.
MAX_TITEL = 80
#: Zeilen je Text. Mehr wäre nicht mehr zu lesen, sondern eine Wand.
MAX_ZEILEN = 12

#: Unsichtbare Zeichen, die die Leserichtung oder den Zusammenhalt von Wörtern
#: verändern. Sie haben in einer Servernachricht keinen ehrlichen Zweck.
_UNSICHTBAR = frozenset(
    [chr(c) for c in range(0x200B, 0x2010)]      # ZWSP … RLM
    + [chr(c) for c in range(0x202A, 0x202F)]    # LRE … RLO, PDF
    + [chr(c) for c in range(0x2066, 0x206A)]    # LRI … PDI
    + ["﻿", "­", " ", " "]   # BOM, weiches Trennen, Zeilen-/Absatztrenner
)


def saeubern(roh, grenze: int = MAX_ZEICHEN, *, zeilen: bool = True) -> str:
    """Einen Text vom Relay auf Anzeigbares bringen.

    *grenze* ist die Zeichenzahl, *zeilen* sagt, ob Zeilenumbrüche erlaubt sind
    (in einer Überschrift nicht). Rückgabe ist immer eine Zeichenkette — auch
    wenn ``roh`` gar keine war.
    """
    if not isinstance(roh, str):
        roh = "" if roh is None else str(roh)
    aus = []
    for z in roh:
        if z in _UNSICHTBAR:
            continue
        if z == "\n":
            if zeilen:
                aus.append(z)
            else:
                aus.append(" ")
            continue
        if z == "\t":
            aus.append(" ")
            continue
        # Steuerzeichen (auch die aus dem Latein-1-Bereich) fliegen raus.
        if ord(z) < 0x20 or 0x7F <= ord(z) <= 0x9F:
            continue
        aus.append(z)
    text = "".join(aus)

    if zeilen:
        # Leerzeilen zusammenfassen und die Zeilenzahl begrenzen: eine Nachricht
        # aus 500 Umbrüchen ist ein Vollbild aus Nichts.
        rohzeilen = [z.rstrip() for z in text.split("\n")]
        gekuerzt: list[str] = []
        leer = 0
        for zeile in rohzeilen:
            if zeile:
                leer = 0
            else:
                leer += 1
                if leer > 1:
                    continue
            gekuerzt.append(zeile)
        text = "\n".join(gekuerzt[:MAX_ZEILEN])
    else:
        text = " ".join(text.split())

    text = text.strip()
    if len(text) > grenze:
        text = text[:grenze].rstrip() + "…"
    return text


def saeubere_ankuendigung(roh) -> dict | None:
    """Eine Ankündigung vom Relay in eine anzeigbare Form bringen.

    ``None``, wenn nichts Anzeigbares übrig bleibt — eine leere Ankündigung
    wäre ein Fenster ohne Inhalt, das der Spieler wegklicken muss.

    Die Sprachtabellen (``title``/``text`` als ``{"de": …, "en": …}``) bleiben
    erhalten, aber nur mit Sprachkürzeln, die wie welche aussehen: sonst legt ein
    Relay tausend Schlüssel ab und das Spiel trägt sie mit.
    """
    if not isinstance(roh, dict):
        return None
    kennung = saeubern(roh.get("id"), 64, zeilen=False)
    if not kennung:
        return None
    aus = {"id": kennung, "date": saeubern(roh.get("date"), 20, zeilen=False)}
    for feld, grenze, mehrzeilig in (("title", MAX_TITEL, False),
                                     ("text", MAX_ZEICHEN, True)):
        tabelle = roh.get(feld)
        sauber: dict[str, str] = {}
        if isinstance(tabelle, dict):
            for sprache, wert in list(tabelle.items())[:8]:
                kuerzel = str(sprache)[:5]
                if kuerzel.isalpha():
                    sauber[kuerzel.lower()] = saeubern(wert, grenze, zeilen=mehrzeilig)
        elif tabelle is not None:
            # Ein Relay, das nur einen Text schickt, ist kein Fehlerfall.
            sauber["de"] = saeubern(tabelle, grenze, zeilen=mehrzeilig)
        aus[feld] = sauber
    if not any(aus["title"].values()) and not any(aus["text"].values()):
        return None
    return aus
