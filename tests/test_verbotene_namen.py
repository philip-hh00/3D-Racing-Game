"""Verbotene Namen — für Spieler **und** für Strecken.

Gemeldet am 07.08.2026: „Liste der verbotenen Namen muss erweitert werden für
Benutzernamen und Strecke. Was passiert, wenn ich in einem neuen Build neue
Namen zu dieser Liste hinzufüge, ein User diesen Namen aber schon hatte?" —
mit der Antwort des Melders: „Dann muss der User Namen neu wählen,
Spielfortschritt bleibt erhalten!"

Drei Dinge stecken darin, und alle drei waren offen:

1. **Streckennamen wurden gar nicht geprüft.** ``paths.safe_track_filename``
   entschärft den Namen für den *Dateipfad* — gegen ``../../../Startup/x.json``,
   nicht gegen Inhalte. Der Titel selbst war frei. Und eine eigene Strecke
   reist im Online-Rennen **automatisch zu allen Mitspielern**: der
   Streckenname war damit der einzige Text, den ein Spieler Fremden
   ungefiltert vorsetzen konnte.

2. **Die Prüfung suchte Teilzeichenketten.** ``"gm" in "sigmund"`` ist wahr.
   Gesperrt waren damit Sigmund, Modena (mod), Devin (dev), Sussex (sex),
   Robotex (bot), Amodeus (mod) und Bota (bot). Eine längere Liste hätte das
   verschlimmert, also gibt es jetzt zwei Gruppen: ``enthalten`` trifft
   überall, ``ganzes_wort`` nur als eigenständiges Wort.

3. **Ein Name, der erst später verboten wird.** Genau der Fall aus der Frage:
   der Spieler hat ihn seit Monaten, ein Update verbietet ihn. Er wird beim
   Start zur Namenswahl geschickt — und **behält alles andere**: Bestzeiten,
   Statistik, Freischaltungen, Lackierungen.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.core import profile  # noqa: E402


@pytest.fixture(autouse=True)
def _frische_liste(monkeypatch):
    """Der Zwischenspeicher der Sperrliste ist prozessweit."""
    monkeypatch.setattr(profile, "_blacklist_cache", None, raising=False)
    yield
    monkeypatch.setattr(profile, "_blacklist_cache", None, raising=False)


# ---------------------------------------------------------------------------
# 1. Was durchgehen muss
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "Sigmund",      # gm
    "Modena",       # mod
    "Devin",        # dev
    "Sussex",       # sex
    "Robotex",      # bot
    "Amodeus",      # mod
    "Bota",         # bot
    "Hancock",      # cock
    "Dickens",      # dick
    "Philip",
    "Rennfahrer_7",
])
def test_ein_harmloser_name_wird_nicht_abgewiesen(name):
    """Alle elf waren vor dem 07.08.2026 gesperrt oder wären es geworden.

    Ein Fehlalarm wiegt schwerer als eine Lücke: ein durchgerutschter Name
    lässt sich melden, ein abgewiesener Spieler ist weg.
    """
    ok, grund = profile.validate_username(name)
    assert ok, f"{name} abgelehnt: {grund}"


# ---------------------------------------------------------------------------
# 2. Was nicht durchgehen darf
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "admin", "Admin_1", "ADMIN", "GameMaster", "moderator", "support",
    "bot", "bot99", "x_bot", "Cheater", "hacker",
])
def test_wer_sich_als_betreiber_ausgibt_kommt_nicht_durch(name):
    """Ein Spieler namens „Support" kann andere nach ihrem Konto fragen.

    Zahlen und Unterstriche gelten als Trennung — genau das ist der übliche
    Weg, eine Sperre zu umgehen.
    """
    ok, _ = profile.validate_username(name)
    assert not ok, f"{name} kam durch"


@pytest.mark.parametrize("name", [
    "xxfuckxx", "Hurensohn1", "wichser", "Arschloch_9", "nigger",
])
def test_beleidigungen_kommen_nicht_durch(name):
    ok, _ = profile.validate_username(name)
    assert not ok, f"{name} kam durch"


def test_die_gruppen_der_liste_sind_beide_belegt():
    """Ohne beide Gruppen ist die Trennung nur eine Absichtserklärung."""
    enthalten, ganzes_wort = profile._load_blacklist()
    assert len(enthalten) >= 10, enthalten
    assert len(ganzes_wort) >= 20, ganzes_wort


def test_kurze_woerter_stehen_nicht_in_der_enthalten_gruppe():
    """Die Regel, die den Fehlalarm verhindert.

    Ein Wort mit drei Buchstaben als Teilzeichenkette sperrt zwangsläufig
    normale Namen mit — ``gm``, ``mod``, ``bot`` und ``sex`` waren genau das.
    Vier Buchstaben sind die Grenze, ab der eine Teilzeichenkette vertretbar
    ist; wer etwas Kürzeres hinzufügt, soll hier aufgehalten werden und es nach
    ``ganzes_wort`` legen.

    Vier ist nicht risikofrei — ``cunt`` steckt in *Scunthorpe*, einer echten
    englischen Stadt. Genau deshalb steht es in ``ganzes_wort``. Bei ``fuck``
    und ``fick`` ist die Abwägung andersherum ausgegangen: Anhängsel sind dort
    der übliche Weg, eine Sperre zu umgehen, und ein Name, der sie als Silbe
    enthält, ist selten genug.
    """
    enthalten, _ = profile._load_blacklist()
    zu_kurz = [w for w in enthalten if len(w) < 4]
    assert zu_kurz == [], (
        f"zu kurz für eine Teilzeichenketten-Sperre: {zu_kurz} — "
        f"gehören nach 'ganzes_wort'")


def test_scunthorpe_darf_spielen():
    """Der bekannteste Fehlalarm der Zunft, hier festgenagelt."""
    assert profile.validate_username("Scunthorpe")[0]
    assert profile.validate_track_name("Scunthorpe Ring")[0]


def test_die_alte_form_der_datei_wird_weiter_gelesen(monkeypatch, tmp_path):
    """Eine schlichte Liste ist die Form vor dem 07.08.2026.

    Sie soll nicht stillschweigend alles erlauben — ein Spielstand mit einer
    älteren Datei wäre sonst ungeschützt.
    """
    datei = tmp_path / "alt.json"
    datei.write_text(json.dumps(["schimpfwort"]), encoding="utf-8")
    monkeypatch.setattr(profile, "_BLACKLIST_PATH", str(datei))
    monkeypatch.setattr(profile, "_blacklist_cache", None, raising=False)

    enthalten, ganzes_wort = profile._load_blacklist()
    assert enthalten == ["schimpfwort"]
    assert ganzes_wort == []
    assert not profile.validate_username("xschimpfwortx")[0]


# ---------------------------------------------------------------------------
# 3. Streckennamen
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "Alte Mühle (Nacht)", "Modena Ring", "GP-Kurs 2", "Wüstenpiste",
])
def test_ein_streckenname_darf_leerzeichen_und_klammern_haben(name):
    ok, grund = profile.validate_track_name(name)
    assert ok, f"{name} abgelehnt: {grund}"


@pytest.mark.parametrize("name", ["Fuck City", "admin track", "Hurensohn GP"])
def test_ein_verbotener_streckenname_wird_abgewiesen(name):
    ok, _ = profile.validate_track_name(name)
    assert not ok, f"{name} kam durch"


def test_ein_leerer_streckenname_geht_nicht():
    assert not profile.validate_track_name("")[0]
    assert not profile.validate_track_name("   ")[0]


def test_der_editor_veroeffentlicht_keinen_verbotenen_namen():
    """Der Ort, an dem ein Streckenname zum ersten Mal öffentlich wird.

    Der **Entwurf** bleibt bewusst frei: solange nichts das Gerät verlässt,
    geht der Name niemanden etwas an.
    """
    import inspect

    from src.states.editor_state import EditorState

    quelle = inspect.getsource(EditorState._do_publish)
    assert "validate_track_name" in quelle, \
        "_do_publish prüft den Namen nicht mehr"


def test_eine_geschenkte_strecke_bekommt_einen_harmlosen_namen():
    """Beim Empfänger, nicht nur beim Absender.

    Ein veränderter Client kann senden, was er will — geschützt wird deshalb
    dort, wo die Datei landet.
    """
    import inspect

    from src.states.menu.online_lobby_page import OnlineLobbyPage

    quelle = inspect.getsource(OnlineLobbyPage._save_offer)
    assert "validate_track_name" in quelle, \
        "eine geschenkte Strecke wird unter jedem Namen abgelegt"


# ---------------------------------------------------------------------------
# 4. Ein Name, der erst später verboten wird
# ---------------------------------------------------------------------------

def test_ein_nachtraeglich_verbotener_name_fuehrt_zur_neuwahl(monkeypatch,
                                                              tmp_path):
    """Die Frage aus der Meldung, beantwortet wie gewünscht.

    Der Spieler heißt seit Monaten so, ein Update verbietet den Namen. Er wird
    zur Namenswahl geschickt — **und behält alles andere.**
    """
    from src.core import paths

    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(profile, "_current", None, raising=False)

    p = profile.current()
    p.username = "Hurensohn1"
    p.save()

    assert profile.namensneuwahl_noetig(), \
        "ein inzwischen verbotener Name muss zur Neuwahl fuehren"


def test_ein_erlaubter_name_fuehrt_zu_keiner_neuwahl(monkeypatch, tmp_path):
    from src.core import paths

    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(profile, "_current", None, raising=False)

    p = profile.current()
    p.username = "Sigmund"
    p.save()

    assert not profile.namensneuwahl_noetig()


def test_der_fortschritt_ueberlebt_die_neuwahl(monkeypatch, tmp_path):
    """Der Kern der Zusage: nur der Name ist weg, sonst nichts.

    Das Profil einfach zu verwerfen wäre der einfachste Weg — und der falsche:
    Bestzeiten, Statistik und Freischaltungen hängen daran, und ein Spieler,
    der für ein Wort seine Erfolge verliert, hört auf zu spielen.
    """
    from src.core import paths

    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(profile, "_current", None, raising=False)

    p = profile.current()
    p.username = "Hurensohn1"
    p.best_laps = {"oval": 42.5}
    p.save()

    monkeypatch.setattr(profile, "_current", None, raising=False)
    assert profile.namensneuwahl_noetig()

    profile.set_username("Sigmund")

    monkeypatch.setattr(profile, "_current", None, raising=False)
    danach = profile.current()
    assert danach.username == "Sigmund"
    assert danach.best_laps.get("oval") == 42.5, \
        "die Bestzeit ist bei der Namensneuwahl verlorengegangen"
    assert not profile.namensneuwahl_noetig()


def test_der_start_schickt_einen_verbotenen_namen_zur_neuwahl():
    """Der Ladebildschirm entscheidet, wohin es nach dem Start geht."""
    import inspect

    from src.states.loading_state import LoadingState

    quelle = inspect.getsource(LoadingState._step_finish)
    assert "namensneuwahl_noetig" in quelle, (
        "der Start prueft den gespeicherten Namen nicht gegen die aktuelle "
        "Sperrliste")
