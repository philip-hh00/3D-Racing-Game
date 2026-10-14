"""Namensfilter: Normalisierung, Liste, und dass Spiel und Relay gleich pruefen.

Das Gegengewicht zur langen Sperrliste ist die Liste der **harmlosen** Namen
unten: sie muss durchgehen. Ein durchgerutschter Name laesst sich melden, ein
abgewiesener Spieler ist weg - jedes neue Wort in ``name_blacklist.json`` muss
diese Liste bestehen (das „Scunthorpe-Problem").

Die Datei und die Pruefung stehen in **vier Kopien** (3D-Spiel, 2D-Spiel, je ein
Relay). Dieser Test haelt die beiden Kopien eines Repos zusammen; zwischen den
Repos pinnt ``LISTEN_HASH`` den Inhalt der Liste - wer sie aendert, aendert die
Konstante in beiden Repos (der Test nennt den neuen Wert).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.core import namensfilter as nf  # noqa: E402

#: Inhalt der Liste (``enthalten`` und ``ganzes_wort``, sortiert). In beiden
#: Repos gleich; siehe oben.
LISTEN_HASH = "538a8dd45b88bff709afe81cda8ad70da8636e5bfcd5fd2aad5f34920fb9c50a"

_PFAD_SPIEL = os.path.join(_ROOT, "data", "settings", "name_blacklist.json")
_PFAD_RELAY = os.path.join(_ROOT, "server", "name_blacklist.json")


def _liste() -> dict:
    with open(_PFAD_SPIEL, encoding="utf-8") as f:
        return json.load(f)


_K = nf.nf_kompiliere(_liste()["enthalten"], _liste()["ganzes_wort"])


def gesperrt(text: str) -> bool:
    return nf.nf_gesperrt(text, _K)


# ---------------------------------------------------------------------------
# 1. Harmlose Namen muessen durchgehen
# ---------------------------------------------------------------------------

HARMLOS = """
Hans Anna Philip Sigmund Modena Devin Sussex Robotex Amodeus Bota Hancock Dickens Rennfahrer_7
Classic Assassin Hamburg Helsinki Schwanstein Analyse Therapist Scunthorpe Penistone Essex Middlesex Wessex
Cockburn Cockpit Peacock Hitchcock Shuttlecock Dickson Dickinson Analysis Canal Banal Pianist Grape Drape Scrape
Sextant Sexton Unisex Cumbria Cumulus Document Circumference Cucumber Succumb Titan Titanic Mittenwald
Penguin Pennsylvania Spenser Assen Hassan Assad Massimo Cassandra Passion Bass Kassel Lassen Russ Cassie
Dickie Dickerson Pissarro Pisa Analog Cumberland Shiitake Wichtel Schwanberg Schwanensee Schwanger
Berlin München Köln Düsseldorf Frankfurt Stuttgart Leipzig Dresden Hannover Nürnberg Essen Dortmund Bochum
Wuppertal Bielefeld Bonn Mannheim Karlsruhe Wiesbaden Münster Gelsenkirchen Aachen Mönchengladbach Kiel Lübeck
Rostock Hagen Hamm Saarbrücken Zwickau Fürth Passau Arsenal Arsen Marsch Spasski Gmund Model Modern Modul
Remodel Devon Device Devil Rooster Rootbeer Roots Observer Reserved Systems Ecosystem Staffel Supporter Owners
Bottle Botschaft Abbott Robot Boot Mood Hackenberg Hackl Mongolei Mongolia Mia Max Luca Noah Emma Leon Felix
Lukas Sophie Jonas Lea Paul Jan Tim Tom Ben Lena Nico Finn Ole Turbo Drift Nitro Slipstream Apex Chicane
Pitstop Nigeria Niger Fagott Heroine Salopette Bitche Hellraiser Speedster Rennteufel SpeedKing MaxPower
Lightning Blitz Donner Flitzer Raser Kurvenkönig Gasfuß Bleifuß Mr_Fast Captain_Nitro Drift_King Sky_Runner
Thunder_Bolt RedBaron BlueFalcon Night_Rider Turbo_Tim PitCrew Nordschleife Waldring Küstenstraße Bergpass
Stadtkurs Hafenrunde Vulkanpiste Sonntagsfahrt Feierabend Freunde Philipp Matthias Mathias Sebastian Tobias
Cosima Nadine Jasmin Mohammed Ahmed Ali Yusuf Aylin Zeynep Chen Wei Li Игорь Анна Мария Αλέξανδρος
Hans1988 Anna88 Max2000 Lara_2010 Racer_1 Player1 Spieler42 Gast_17 Penny Pete Peter Pia Pascal Patrick
Pauline Pablo Cassius Wasser Wassermann Grasshopper Glasbruch Klassenfahrt Mathematik Mustang Musterfrau
Skoda Opel Audi Ford Fiat Seat Dicker_Hans Hansdampf Kleinwagen Gebrauchtwagen Tankstelle Kreisverkehr
Autobahn Ampel Bremsweg Sachsenring Hockenheim Nürburgring Spa Monza Imola Suzuka Silverstone Daytona
Fuchs Fuchsbau Staubsauger Ascot Assisi Masse Gasse Strasse Hass Fass Klasse Tasse Kasse Kassette
Mönch Schwan Schwanz_Hans_ist_ok_nicht Lobby Rennen Runde Strecke Gast Spieler
""".split()
# „Schwanz_Hans_ist_ok_nicht" ist ein Platzhalter-Wort, kein Name: herausnehmen.
HARMLOS = [w for w in HARMLOS if not w.startswith("Schwanz_")]

HARMLOS_MEHRERE_WOERTER = [
    "Alter Mönch Ring", "Prince Stefan", "Chen Tai", "Sebas Tian", "Hans Ickes", "Claim Jumper",
    "Moby Anna", "Tennis Gerd", "Glas Hohl", "Wolf Gang", "Anna Lena", "Max Imilian",
    "Anna's Lobby", "Hans's Lobby", "Offene Runde", "Alte Mühle (Nacht)", "GP-Kurs 2",
    "Rennen Nr 1", "Wüstenpiste", "Bergrennen Süd", "Helsinki Ring", "Hamburg Hafen",
    "Team Alpha", "Die Freunde", "Nachtfahrt 2",
]


@pytest.mark.parametrize("name", HARMLOS + HARMLOS_MEHRERE_WOERTER)
def test_ein_harmloser_name_geht_durch(name):
    assert not gesperrt(name), f"{name!r} wurde gesperrt"


def test_der_vorgabename_einer_lobby_geht_fuer_erlaubte_namen_durch():
    for spieler in ("Anna", "Hans", "Scunthorpe", "Classic", "Assassin", "Rennfahrer_7"):
        assert not gesperrt(f"{spieler}'s Lobby"), spieler


# ---------------------------------------------------------------------------
# 2. Unerwuenschte Namen und ihre Verkleidungen
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    # Beleidigungen, deutsch
    "Arschloch", "Hurensohn", "Hurensöhne", "Wichser", "Schlampe", "Fotze", "Fotzen", "Spast", "Missgeburt",
    "Vollidiot", "Idiot", "Mongo", "Behindert", "Scheisse", "Scheiße", "Kackbratze", "Schwanzlutscher",
    # englisch
    "fuck", "motherfucker", "Bitch", "Bastard", "Asshole", "Dickhead", "Cunt", "Slut", "Whore", "Wanker",
    "Pussy", "Shithead", "Bullshit", "Retard",
    # Slurs
    "Nigger", "Nigga", "Neger", "Kanake", "Faggot", "Schwuchtel", "Zigeuner", "Untermensch", "Wetback",
    # Sexuelles
    "Penis", "Vagina", "Titten", "Porno", "Pornhub", "Dildo", "Blowjob", "Orgasm", "Sex", "Rapist", "Vergewaltiger",
    # extremistisch
    "Hitler", "Nazi", "Neonazi", "Heil Hitler", "SiegHeil", "Hakenkreuz", "Auschwitz", "Gaskammer", "Judensau",
    "KKK", "WhitePower", "1488", "14_88", "Hans_88", "88", "HH88", "hh_88",
    # Drogen
    "Kokain", "Cocaine", "Heroin", "Weed", "Crystalmeth", "Ecstasy", "Marihuana", "Hans_420", "Kiffer",
    # andere Sprachen
    "Putain", "Mierda", "Cazzo", "Vaffanculo", "Kurwa", "Pierdol", "Blyat", "Orospu", "Siktir", "Puta",
    # Betrueger/Betreiber
    "Admin", "Administrator", "Moderator", "Mod", "Server", "System", "Support", "Staff", "Owner", "Root",
    "GameMaster", "GM", "Dev", "Developer", "Sysadmin", "Official", "Bot", "Cheater", "Hacker",
    "Free_Coins", "Wallhack",
])
def test_ein_verbotener_name_wird_gesperrt(name):
    assert gesperrt(name), f"{name!r} kam durch"


# ---------------------------------------------------------------------------
# 3. Normalisierung: jede Regel einzeln
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, regel", [
    ("ADMIN", "Grossschreibung"),
    ("aDmIn", "Wechselschreibung"),
    ("4dm1n", "Leetspeak 4=a 1=i"),
    ("@dm!n", "Leetspeak @=a !=i"),
    ("Adm|n", "Leetspeak |=i"),
    ("$erver", "Leetspeak $=s"),
    ("Sy5t3m", "Leetspeak 5=s 3=e"),
    ("Supp0rt", "Leetspeak 0=o"),
    ("N1gg3r", "Leetspeak 1=i"),
    ("Hurens0hn", "Leetspeak 0=o in langem Wort"),
    ("ĂdmĪn", "Akzente"),
    ("Ädmin", "Umlaut als Buchstabe"),
    ("Ärschloch", "Umlaut ä=a"),
    ("Hurensöhn", "Umlaut ö=o"),
    ("Hurensoehne", "Umlaut ö=oe"),
    ("ａｄｍｉｎ", "Vollbreite"),
    ("ad​min", "unsichtbares Zeichen"),
    ("аdmin", "kyrillisches a"),
    ("Αdmin", "griechisches Alpha"),
    ("сука", "Kyrillisch, Umschrift (suka)"),
    ("пизда", "Kyrillisch, Umschrift (pizda)"),
    ("f.u.c.k", "Punkte dazwischen"),
    ("f_u_c_k", "Unterstriche dazwischen"),
    ("f u c k", "Leerzeichen dazwischen"),
    ("a-d-m-i-n", "Bindestriche dazwischen"),
    ("fuuuuck", "gedehnte Buchstaben"),
    ("Schwanz Lutscher", "Wort ab 6 Buchstaben ueber Leerzeichen"),
    ("xxfuckxx", "Anhaengsel um ein langes Wort"),
    ("ServerAdmin", "Grossbuchstaben-Wechsel trennt Woerter"),
    ("xXAdminXx", "Wort zwischen Grossbuchstaben"),
    ("Admin99", "Ziffern trennen"),
    ("x_bot", "Unterstrich trennt"),
    ("RoBot", "Grossbuchstaben-Wechsel: Bot"),
    ("Heil88", "Zahlencode am Wort"),
])
def test_jede_verkleidung_wird_erkannt(name, regel):
    assert gesperrt(name), f"{name!r} ({regel}) kam durch"


@pytest.mark.parametrize("name, grund", [
    ("Boot", "kurzes ganzes Wort verlangt genaue Buchstabenzahl (bot)"),
    ("Mood", "dito (mod)"),
    ("Niger", "nigger braucht zwei g"),
    ("Fagott", "faggot braucht zwei g"),
    ("Heroine", "heroin gilt nur als ganzes Wort"),
    ("Hans88", "88 sperrt nur als eigene Zahl, nicht als Anhaengsel"),
    ("Anna1988", "ein Geburtsjahr ist kein Code"),
    ("HH", "HH allein ist ein Hamburger Kennzeichen"),
    ("Hamburg_HH", "dito"),
    ("Robotex", "Silbe mitten im Wort"),
    ("Cockpit", "ganzes Wort, kein Teilwort"),
])
def test_diese_ausnahmen_sind_gewollt(name, grund):
    assert not gesperrt(name), f"{name!r} gesperrt, obwohl: {grund}"


def test_leere_und_seltsame_eingaben_werfen_nichts():
    for roh in ("", "   ", None, 0, "​", "!!!", "‮", "x" * 5000, "ß", "ǅ"):
        gesperrt(roh)       # darf nicht werfen
    assert not gesperrt("")
    assert not gesperrt(None)


def test_die_pruefung_ist_schnell_genug_fuer_den_relay():
    import time
    t0 = time.perf_counter()
    for i in range(500):
        gesperrt(f"Spieler_{i}")
        gesperrt("Eine ziemlich lange Strecke mit Namen " + str(i))
    assert time.perf_counter() - t0 < 5.0


# ---------------------------------------------------------------------------
# 4. Die Liste selbst
# ---------------------------------------------------------------------------

def test_die_liste_ist_deutlich_groesser_als_vorher():
    liste = _liste()
    assert len(liste["enthalten"]) >= 150
    assert len(liste["ganzes_wort"]) >= 150


def test_jeder_eintrag_steht_in_kanonischer_form():
    """Kleinbuchstaben und Ziffern, kein Akzent, keine Leerzeichen - so wie der
    Filter vergleicht."""
    liste = _liste()
    for gruppe in ("enthalten", "ganzes_wort"):
        for w in liste[gruppe]:
            assert re.fullmatch(r"[a-z0-9]+", w), f"{gruppe}: {w!r}"
        assert len(set(liste[gruppe])) == len(liste[gruppe]), f"doppelt in {gruppe}"
    assert not set(liste["enthalten"]) & set(liste["ganzes_wort"]), \
        "ein Wort steht in beiden Gruppen"


def test_enthalten_hat_nur_laengere_woerter():
    kurz = [w for w in _liste()["enthalten"] if len(w) < 4]
    assert kurz == [], f"unter vier Zeichen gehoert nach ganzes_wort: {kurz}"


def test_ganzes_wort_enthaelt_nichts_was_enthalten_schon_trifft():
    liste = _liste()
    mit = [g for g in liste["ganzes_wort"]
           if any(e in g for e in liste["enthalten"] if not any(c.isdigit() for c in e))]
    assert mit == [], f"doppelt gemoppelt: {mit}"


def test_jeder_eintrag_sperrt_sich_selbst():
    """Faengt Tippfehler und Eintraege, die der Filter nie treffen kann."""
    liste = _liste()
    for w in liste["enthalten"] + liste["ganzes_wort"]:
        assert gesperrt(w), f"{w!r} steht in der Liste, trifft sich aber nicht"


def test_kein_teilwort_steckt_in_einem_harmlosen_namen():
    """Das Scunthorpe-Problem, fuer die ganze Liste auf einmal: kein
    ``enthalten``-Wort darf mitten in einem der harmlosen Namen stehen."""
    korpus = [re.sub(r"[^a-z]", "", n.lower()) for n in HARMLOS + HARMLOS_MEHRERE_WOERTER]
    for w in _liste()["enthalten"]:
        if any(c.isdigit() for c in w):
            continue
        for n in korpus:
            assert w not in n, f"{w!r} steckt in {n!r}"


def test_die_verkleidungswoerter_der_aufgabe_sind_gesperrt():
    for w in ("admin", "moderator", "server", "system", "support"):
        assert w in _liste()["ganzes_wort"] or gesperrt(w)
        assert gesperrt(w.capitalize())


def test_keine_namen_echter_personen_in_der_liste():
    """Die Liste sperrt Woerter, keine Menschen. Einzige Ausnahme steht hier
    ausdruecklich: der Name des Diktators ist selbst das Symbol (Hitler)."""
    erlaubt = {"hitler"}
    bekannt = {"merkel", "trump", "putin", "biden", "obama", "scholz", "himmler", "goebbels",
               "eichmann", "goering", "stalin", "mussolini", "bin laden", "binladen"}
    liste = _liste()
    treffer = [w for w in liste["enthalten"] + liste["ganzes_wort"]
               if w in bekannt and w not in erlaubt]
    assert treffer == []


def test_listeninhalt_ist_in_beiden_repos_gleich():
    liste = _liste()
    kanon = json.dumps({"enthalten": sorted(liste["enthalten"]),
                        "ganzes_wort": sorted(liste["ganzes_wort"])})
    h = hashlib.sha256(kanon.encode()).hexdigest()
    assert h == LISTEN_HASH, (
        f"Die Sperrliste hat sich geaendert. Neuer Wert fuer LISTEN_HASH: {h}\n"
        "Die Liste muss in 3D-Spiel und 2D-Spiel (je data/settings/ UND server/) "
        "gleich sein - die Konstante in tests/test_namensfilter.py beider Repos "
        "auf diesen Wert setzen und die Dateien kopieren.")


def test_spiel_und_relay_haben_dieselbe_datei():
    with open(_PFAD_SPIEL, "rb") as a, open(_PFAD_RELAY, "rb") as b:
        assert a.read().replace(b"\r\n", b"\n") == b.read().replace(b"\r\n", b"\n"), (
            "server/name_blacklist.json und data/settings/name_blacklist.json "
            "muessen gleich sein")


# ---------------------------------------------------------------------------
# 5. Spiel und Relay pruefen gleich
# ---------------------------------------------------------------------------

def _block(pfad: str) -> str:
    with open(pfad, encoding="utf-8") as f:
        text = f.read()
    a = text.index("# --- NAMENSFILTER BEGIN ---")
    b = text.index("# --- NAMENSFILTER END ---")
    return text[a:b]


def test_der_pruefblock_ist_im_spiel_und_im_relay_buchstabengleich():
    assert _block(os.path.join(_ROOT, "src", "core", "namensfilter.py")) == \
        _block(os.path.join(_ROOT, "server", "server.py")), (
            "Der Block zwischen den Marken NAMENSFILTER BEGIN/END weicht ab - "
            "Aenderungen gehoeren in beide Dateien")


def test_relay_und_spiel_urteilen_auf_ein_paar_hundert_namen_gleich():
    sys.path.insert(0, os.path.join(_ROOT, "server"))
    import server as srv
    proben = HARMLOS + HARMLOS_MEHRERE_WOERTER + [
        "Hurensohn", "Admin", "4dm1n", "f.u.c.k", "Hans_88", "1488", "сука", "Hitler", "ServerAdmin",
        "x_bot", "Schwanz Lutscher", "Kokain", "Weed", "Boot", "Nazi99", "Sch3iss", "", "   ",
    ]
    for p in proben:
        assert srv.name_gesperrt(p) == gesperrt(p), p


# ---------------------------------------------------------------------------
# 6. Das Spiel selbst benutzt den Filter
# ---------------------------------------------------------------------------

def test_profil_und_streckenname_nutzen_die_neue_liste():
    from src.core import profile
    assert profile.validate_username("Hans")[0]
    assert profile.validate_username("Classic")[0]
    assert not profile.validate_username("Adm1n")[0]
    assert not profile.validate_username("N4zi_99")[0]
    ok, grund = profile.validate_username("Sy5tem")
    assert not ok and grund
    assert profile.validate_track_name("Helsinki Ring")[0]
    assert not profile.validate_track_name("Hurens0hn Piste")[0]
    if hasattr(profile, "validate_lobby_name"):
        assert profile.validate_lobby_name("Anna's Lobby")[0]
        assert profile.validate_lobby_name("")[0]
        assert not profile.validate_lobby_name("Nazi Treff")[0]


def test_die_absage_des_relays_wird_uebersetzt_angezeigt():
    from src.core import i18n
    from src.net import servertext
    alt = i18n.current()
    try:
        i18n.set_language("de")
        de = {f: servertext.name_absage(f) for f in ("player", "lobby", "track", "")}
        i18n.set_language("en")
        en = {f: servertext.name_absage(f) for f in ("player", "lobby", "track", "")}
    finally:
        i18n.set_language(alt)
    assert all("nicht erlaubt" in t for t in de.values())
    assert len(set(de.values())) == 4
    assert all("allowed" in t for t in en.values()), en
    assert not any("nicht erlaubt" in t for t in en.values()), "unuebersetzt: " + str(en)
