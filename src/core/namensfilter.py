"""Namensfilter: ein Name gegen die Sperrliste pruefen (Plan 1.1.0).

**Dieselbe Pruefung laeuft an zwei Stellen** — im Spiel (Eingabe: Spielername,
Streckenname, Lobbyname) und auf dem Relay (``server/server.py``), der sie
durchsetzt. Der Relay wird einzeln auf einen Server kopiert und kennt das
``src``-Paket nicht, deshalb steht der Block zwischen den Marken
``NAMENSFILTER BEGIN`` und ``NAMENSFILTER END`` in **beiden** Dateien
buchstabengleich; ``tests/test_namensfilter.py`` vergleicht beide Texte.
Aenderungen an der Pruefung gehoeren in alle vier Kopien (3D-Spiel, 3D-Relay,
2D-Spiel, 2D-Relay) - der Test in jedem Repo erinnert daran.

Die Liste selbst (``name_blacklist.json``) hat zwei Gruppen:

``enthalten``    trifft ueberall im Namen (auch mitten im Wort, auch mit
                 Leerzeichen/Punkten dazwischen, wenn das Wort sechs Buchstaben
                 oder mehr hat)
``ganzes_wort``  trifft nur ein eigenstaendiges Wort. Ziffern, Unterstriche,
                 Leerzeichen und Grossbuchstaben-Wechsel (``ServerAdmin``)
                 trennen Woerter, Buchstaben nicht.

**Normalisierung.** Vor dem Vergleich wird der Name in mehrere Lesarten
gebracht, und er ist gesperrt, sobald *eine* davon trifft:

* Gross-/Kleinschreibung, Voll- und Sonderbreite (``fuck`` in Vollbreite) und unsichtbare
  Zeichen fallen weg;
* Akzente fallen weg (``é`` wird ``e``); ``ä ö ü`` lesen wir einmal als
  ``a o u`` und einmal als ``ae oe ue``; ``ß`` wird ``ss``;
* kyrillische und griechische Buchstaben, die lateinischen gleichen, werden
  uebersetzt (ein kyrillisches a in ``admin``); kyrillischer Text wird zusaetzlich
  umschrieben (das russische Wort fuer Huendin wird ``suka``);
* Leetspeak: ``0 3 4 5 7 @ $ + (`` werden ``o e a s t a s t c``; ``1 ! |`` werden
  einmal ``i`` und einmal ``l``. Als zusaetzliche Lesart - die Ziffern bleiben in
  der strengen Lesart Trenner (``bot99`` ist gesperrt);
* alles, was kein Buchstabe oder keine Ziffer ist, trennt Woerter;
* mehrere gleiche Buchstaben hintereinander zaehlen als einer (``fuuuck``), ein
  Wort mit Doppelbuchstaben verlangt sie aber (``nigger``, nicht ``niger``);
* drei oder mehr Einzelbuchstaben hintereinander werden zusammengezogen
  (``f u c k``, ``a.d.m.i.n``).

Eintraege mit Ziffern (``1488``, ``88``) werden nur in der strengen Lesart
verglichen. Das Modul braucht nur die Standardbibliothek.
"""
# --- NAMENSFILTER BEGIN ---
import re as _nf_re
import unicodedata as _nf_ud

_NF_LEET = {"0": "o", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a",
            "$": "s", "+": "t", "(": "c", chr(0x20AC): "e"}
_NF_EINS = "1!|"
_NF_GLYPHEN = {
    # kyrillisch -> lateinisch (gleiches Aussehen); Schluessel sind Codepunkte; Schluessel sind Codepunkte
    0x0430: "a", 0x0432: "b", 0x0435: "e", 0x0451: "e", 0x043A: "k",
    0x043C: "m", 0x043D: "h", 0x043E: "o", 0x0440: "p", 0x0441: "c",
    0x0442: "t", 0x0443: "y", 0x0445: "x", 0x0456: "i", 0x0458: "j",
    0x0455: "s", 0x0491: "r",
    # griechisch
    0x03B1: "a", 0x03B2: "b", 0x03B5: "e", 0x03B9: "i", 0x03BA: "k",
    0x03BD: "v", 0x03BF: "o", 0x03C1: "p", 0x03C4: "t", 0x03C5: "u",
    0x03C7: "x", 0x03C9: "w",
}
_NF_KYRILLISCH = {
    0x0430: "a", 0x0431: "b", 0x0432: "v", 0x0433: "g", 0x0434: "d",
    0x0435: "e", 0x0451: "e", 0x0436: "zh", 0x0437: "z", 0x0438: "i",
    0x0439: "y", 0x043A: "k", 0x043B: "l", 0x043C: "m", 0x043D: "n",
    0x043E: "o", 0x043F: "p", 0x0440: "r", 0x0441: "s", 0x0442: "t",
    0x0443: "u", 0x0444: "f", 0x0445: "kh", 0x0446: "ts", 0x0447: "ch",
    0x0448: "sh", 0x0449: "shch", 0x044A: "", 0x044B: "y", 0x044C: "",
    0x044D: "e", 0x044E: "yu", 0x044F: "ya", 0x0456: "i", 0x0491: "g",
    0x0454: "e", 0x0457: "yi",
}
_NF_SONDER = {"ß": "ss", "æ": "ae", "œ": "oe", "ø": "o",
              "đ": "d", "ð": "d", "ł": "l", "ı": "i",
              "þ": "th"}
_NF_UMLAUTE = {"ä": "a", "ö": "o", "ü": "u"}


def _nf_buchstaben(text: str, ausschreiben: bool) -> str:
    """Akzente weg; ``ä ö ü`` als ``a o u`` oder (ausschreiben) ``ae oe ue``."""
    aus = []
    for z in text:
        if z in _NF_UMLAUTE:
            aus.append(_NF_UMLAUTE[z] + ("e" if ausschreiben else ""))
        elif z in _NF_SONDER:
            aus.append(_NF_SONDER[z])
        elif z.isascii():
            aus.append(z)
        else:
            aus.append("".join(c for c in _nf_ud.normalize("NFKD", z)
                               if not _nf_ud.combining(c)))
    return "".join(aus)


def _nf_lesarten(text: str) -> list:
    """Alle Lesarten von *text* als ``(streng, Ansicht)``.

    ``Ansicht`` besteht nur aus ``a-z``, ``0-9`` und Leerzeichen (Trenner).
    ``streng`` ist wahr, wenn keine Leetspeak-Ersetzung stattfand.
    """
    t = _nf_ud.normalize("NFKC", text).lower()
    t = "".join(z for z in t if _nf_ud.category(z) != "Cf")
    skripte = [t.translate(_NF_GLYPHEN)]
    if any(0x0400 <= ord(z) <= 0x04FF for z in t):
        skripte.append("".join(_NF_KYRILLISCH.get(ord(z), z) for z in t))
    aus = []
    gesehen = set()
    for s in skripte:
        for ausschreiben in (False, True):
            u = _nf_buchstaben(s, ausschreiben)
            for modus in (0, 1, 2):
                if modus == 0:
                    v = u
                else:
                    ein = "i" if modus == 1 else "l"
                    v = "".join(ein if z in _NF_EINS else _NF_LEET.get(z, z)
                                for z in u)
                v = _nf_re.sub(r"[^a-z0-9]+", " ", v).strip()
                if (modus == 0, v) not in gesehen:
                    gesehen.add((modus == 0, v))
                    aus.append((modus == 0, v))
    return aus


def _nf_camel(text: str) -> str:
    """Trenner an Grossbuchstaben-Wechseln: ``ServerAdmin`` -> ``Server Admin``."""
    aus = []
    for i, z in enumerate(text):
        if i and z.isupper() and text[i - 1].isalpha():
            if text[i - 1].islower() or (i + 1 < len(text) and text[i + 1].islower()):
                aus.append(" ")
        aus.append(z)
    return "".join(aus)


def _nf_rle(s: str) -> tuple:
    """``'fuuck'`` -> ``('fuck', (1, 2, 1, 1))``: Buchstaben und Wiederholungen."""
    buchstaben, zaehler = [], []
    for z in s:
        if buchstaben and buchstaben[-1] == z:
            zaehler[-1] += 1
        else:
            buchstaben.append(z)
            zaehler.append(1)
    return "".join(buchstaben), tuple(zaehler)


def _nf_eintrag(wort) -> str:
    w = _nf_ud.normalize("NFKD", str(wort).lower())
    w = "".join(z for z in w if not _nf_ud.combining(z))
    return "".join(z for z in w if z.isascii() and z.isalnum())


def nf_kompiliere(enthalten, ganzes_wort) -> dict:
    """Die Listen in eine Form bringen, in der ein Name schnell geprueft wird."""
    teil, ganz, ziffern = {}, {}, {"teil": {}, "ganz": {}}
    for gruppe, wort in ([("teil", w) for w in enthalten]
                         + [("ganz", w) for w in ganzes_wort]):
        w = _nf_eintrag(wort)
        if not w:
            continue
        ziel = ziffern[gruppe] if any(z.isdigit() for z in w) else \
            (teil if gruppe == "teil" else ganz)
        buchstaben, zaehler = _nf_rle(w)
        # Gedehnte Buchstaben (``fuuuck``) zaehlen bei Teilwoertern und bei
        # ganzen Woertern ab 5 Zeichen; ein kurzes ganzes Wort muss genau
        # stimmen, sonst waere ``Boot`` ein ``bot`` und ``Mood`` ein ``mod``.
        exakt = gruppe == "ganz" and len(w) < 5
        ziel.setdefault(buchstaben, []).append((zaehler, exakt))
    laengen = {"teil": sorted({len(k) for k in teil}),
               "ziffern": sorted({len(k) for k in ziffern["teil"]})}
    return {"teil": teil, "ganz": ganz, "ziffern": ziffern, "laengen": laengen}


def _nf_zaehler_passt(eintrag, vorhanden) -> bool:
    gefordert, exakt = eintrag
    if exakt:
        return tuple(vorhanden) == tuple(gefordert)
    return all(v >= g for g, v in zip(gefordert, vorhanden))


def _nf_teil(rle: tuple, tabelle: dict, laengen, mindest: int = 0) -> bool:
    """Ob ein Eintrag der Tabelle als Teilstueck in *rle* steckt. *mindest* ist
    die Zeichenzahl, die der Eintrag haben muss, um zu zaehlen."""
    buchstaben, zaehler = rle
    for n in laengen:
        for i in range(len(buchstaben) - n + 1):
            for gefordert in tabelle.get(buchstaben[i:i + n], ()):
                if sum(gefordert[0]) >= mindest and _nf_zaehler_passt(
                        gefordert, zaehler[i:i + n]):
                    return True
    return False


def _nf_ganz(wort: str, tabelle: dict) -> bool:
    buchstaben, zaehler = _nf_rle(wort)
    return any(_nf_zaehler_passt(g, zaehler) for g in tabelle.get(buchstaben, ()))


def _nf_zusammenziehen(woerter: list) -> list:
    """Drei oder mehr Einzelbuchstaben hintereinander -> ein Wort (``f u c k``)."""
    aus, lauf = [], []
    for w in woerter + [""]:
        if len(w) == 1 and w.isalpha():
            lauf.append(w)
            continue
        if len(lauf) >= 3:
            aus.append("".join(lauf))
        lauf = []
    return aus


#: Ab so vielen Buchstaben darf ein ``enthalten``-Wort auch ueber Leerzeichen
#: und Satzzeichen hinweg treffen (``schwanz lutscher``). Kuerzer waere das
#: Risiko zu gross, dass zwei harmlose Woerter zusammen eines ergeben.
_NF_ZUSAMMEN_AB = 6


def nf_gesperrt(text, kompiliert: dict) -> bool:
    """Ob *text* gegen die Sperrliste verstoesst. ``kompiliert`` kommt von
    :func:`nf_kompiliere`."""
    roh = str(text or "")[:120]
    if not roh.strip():
        return False
    teil, ganz, zif = kompiliert["teil"], kompiliert["ganz"], kompiliert["ziffern"]
    l_teil, l_zif = kompiliert["laengen"]["teil"], kompiliert["laengen"]["ziffern"]
    for mit_camel in (False, True):
        quelle = _nf_camel(roh) if mit_camel else roh
        for streng, ansicht in _nf_lesarten(quelle):
            woerter = ansicht.split()
            buchstabenwoerter = _nf_re.findall(r"[a-z]+", ansicht)
            zus = _nf_zusammenziehen(woerter)
            for w in buchstabenwoerter + zus:
                if _nf_ganz(w, ganz):
                    return True
            if streng:
                for w in woerter:
                    if _nf_ganz(w, zif["ganz"]):
                        return True
            if mit_camel:
                continue
            # Teilzeichenketten: nur die Lesart ohne Grossbuchstaben-Trenner,
            # sonst traefe ein Wort, das ueber eine Grenze hinweg entsteht.
            for w in woerter + zus:
                rle = _nf_rle(w)
                if _nf_teil(rle, teil, l_teil):
                    return True
                if streng and _nf_teil(rle, zif["teil"], l_zif):
                    return True
            zusammen = "".join(woerter)
            if len(woerter) > 1 and len(zusammen) >= _NF_ZUSAMMEN_AB:
                rle = _nf_rle(zusammen)
                if _nf_teil(rle, teil, l_teil, _NF_ZUSAMMEN_AB):
                    return True
                if streng and _nf_teil(rle, zif["teil"], l_zif):
                    return True
    return False
# --- NAMENSFILTER END ---
