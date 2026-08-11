"""Playtest-Fund 05.08.2026: Erstnutzer sollen nicht mit der ganzen bisherigen
Ankündigungssammlung begrüßt werden.

Ein druckfrisches Profil soll die zu diesem Zeitpunkt bekannten Ankündigungen
(vom Server, zwischengespeichert in ``server_info``) direkt als gesehen
eintragen — nur was danach neu erscheint, ist für den Erstnutzer wirklich neu.
Ein bestehendes Profil darf davon nicht berührt werden, und ohne erreichbare
Liste (Server beim ersten Start offline) darf nichts passieren: kein Absturz,
kein blockierender Netzaufruf.

Zusätzlich: die Kurzanleitung ("So spielst du") bekommt eine Zeile, die sagt,
wo Ankündigungen später stehen (Einstellungen → Info) — dieselbe Karte, die
in ``tests/test_block_f.py`` schon getestet wird; das Muster von dort
(``welcome_state as ws``, ``_Maschine`` als StateMachine-Attrappe) wird hier
übernommen.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pygame
import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from src.core import i18n, profile, sfx  # noqa: E402
from src.net import server_info  # noqa: E402
from src.states import welcome_state as ws  # noqa: E402


@pytest.fixture(autouse=True)
def deutsch_danach():
    yield
    i18n.set_language("de")


@pytest.fixture(autouse=True)
def ohne_cache_leck(monkeypatch):
    """``server_info._cached`` ist Modul-global — ohne Rücksetzen würde ein
    Test dem nächsten seinen Stand unterschieben."""
    monkeypatch.setattr(server_info, "_cached", None, raising=False)
    yield
    monkeypatch.setattr(server_info, "_cached", None, raising=False)


def _info(*ids: str) -> dict:
    return {"announcements": [{"id": i, "date": "2026-07-01"} for i in ids]}


class _Maschine:
    """Nur das, was WelcomeState anfasst (Muster aus test_block_f.py)."""

    def __init__(self) -> None:
        self.gewechselt: list[str] = []

    def transition(self, name: str, **kwargs) -> None:
        self.gewechselt.append(name)


@pytest.fixture
def leeres_profil(monkeypatch):
    """Ein Profil, wie es vor der Erstanlage aussieht: kein Name, nichts gesehen."""
    p = profile.Profile()
    p.save = lambda: None
    monkeypatch.setattr(profile, "_current", p, raising=False)
    monkeypatch.setattr(profile, "current", lambda: p)
    monkeypatch.setattr(sfx, "spielen", lambda *a, **k: None)
    return p


# ===========================================================================
# (1) Neues Profil erbt die bestehenden Ankündigungen als gesehen
# ===========================================================================
def test_ein_neues_profil_hat_die_vorhandenen_ankuendigungen_als_gesehen(monkeypatch):
    monkeypatch.setattr(server_info, "_cached",
                         _info("alt-1", "alt-2"), raising=False)
    p = profile.Profile()
    p.save = lambda: None

    p.seed_seen_announcements()

    assert set(p.seen_announcements) == {"alt-1", "alt-2"}


def test_danach_neu_hinzugekommene_ankuendigungen_bleiben_ungesehen(monkeypatch):
    """Genau der Kern des Fundes: nur die Vergangenheit wird geschenkt."""
    monkeypatch.setattr(server_info, "_cached", _info("alt"), raising=False)
    p = profile.Profile()
    p.save = lambda: None
    p.seed_seen_announcements()

    from src.states.menu_shell_state import newest_unseen_announcement
    neu = {"id": "ganz-neu", "date": "2026-08-05", "text": {"de": "x"}}
    treffer = newest_unseen_announcement(
        [{"id": "alt", "date": "2026-07-01", "text": {"de": "y"}}, neu],
        set(p.seen_announcements))

    assert treffer["id"] == "ganz-neu"


def test_der_erststart_ueber_den_willkommensbildschirm_saet_ebenfalls(
        leeres_profil, monkeypatch):
    """Der eigentliche Weg: Name eingeben, ``_confirm`` tut den Rest."""
    monkeypatch.setattr(server_info, "_cached",
                         _info("2026-07-17-welcome"), raising=False)
    z = ws.WelcomeState(_Maschine())
    z.enter()
    z.input.text = "Neuling"

    z._confirm()

    assert "2026-07-17-welcome" in profile.current().seen_announcements


# ===========================================================================
# (2) Ein bestehendes Profil bleibt unverändert
# ===========================================================================
def test_ein_bestehendes_profil_wird_nicht_angefasst(monkeypatch):
    monkeypatch.setattr(server_info, "_cached",
                         _info("alt-1", "alt-2"), raising=False)
    p = profile.Profile(username="Philip", seen_announcements=["schon-gesehen"])
    gespeichert = []
    p.save = lambda: gespeichert.append(True)

    # Der Weg, den ein bestehendes Profil nimmt: seed_seen_announcements() wird
    # von welcome_state nur bei der Erstanlage aufgerufen (dort, wo
    # ``exists()`` vor dem Setzen des Namens False war). Wird die Methode
    # trotzdem auf einem bestehenden Profil ausgeführt, muss sie zumindest
    # gutartig bleiben statt eigene Einträge zu verlieren.
    p.seed_seen_announcements()

    assert "schon-gesehen" in p.seen_announcements


def test_ein_bestehender_erststart_ruft_das_saeen_gar_nicht_erst_auf(
        monkeypatch):
    """``_confirm`` unterscheidet Erstanlage von Namensänderung — nur die
    Erstanlage darf ``seed_seen_announcements`` überhaupt anfassen."""
    p = profile.Profile(username="Philip", seen_announcements=["alt-1"])
    p.save = lambda: None
    monkeypatch.setattr(profile, "_current", p, raising=False)
    monkeypatch.setattr(profile, "current", lambda: p)
    monkeypatch.setattr(sfx, "spielen", lambda *a, **k: None)
    monkeypatch.setattr(server_info, "_cached", _info("alt-1", "alt-2", "alt-3"),
                        raising=False)
    gerufen = []
    monkeypatch.setattr(profile.Profile, "seed_seen_announcements",
                        lambda self: gerufen.append(True))

    z = ws.WelcomeState(_Maschine())
    z.enter()
    z.input.text = "Neuername"
    z._confirm()

    assert gerufen == []


# ===========================================================================
# (3) Ohne erreichbare Ankündigungsliste passiert nichts Schlimmes
# ===========================================================================
def test_ohne_cache_bleibt_das_profil_leer_und_stuerzt_nicht_ab():
    """Server beim ersten Start nicht erreichbar: ``get_cached()`` liefert
    None. Kein Netzaufruf, kein Absturz, nur der unveränderte Ausgangsstand."""
    assert server_info.get_cached() is None
    p = profile.Profile()
    p.save = lambda: None

    p.seed_seen_announcements()          # darf nicht werfen

    assert p.seen_announcements == []


def test_ohne_cache_wird_gar_nicht_erst_gespeichert(monkeypatch):
    """Ohne Änderung auch kein unnötiger Schreibzugriff."""
    p = profile.Profile()
    gespeichert = []
    p.save = lambda: gespeichert.append(True)

    p.seed_seen_announcements()

    assert gespeichert == []


def test_eine_leere_ankuendigungsliste_vom_server_ist_ebenfalls_harmlos(
        monkeypatch):
    monkeypatch.setattr(server_info, "_cached", {"announcements": []}, raising=False)
    p = profile.Profile()
    p.save = lambda: None

    p.seed_seen_announcements()

    assert p.seen_announcements == []


def test_ein_kaputter_cache_ohne_id_stuerzt_nicht_ab(monkeypatch):
    """Fremde/kaputte Einträge (kein dict, keine ``id``) einfach überspringen —
    dieselbe Nachsicht wie bei ``newest_unseen_announcement``."""
    monkeypatch.setattr(server_info, "_cached",
                        {"announcements": ["kein Objekt", None,
                                           {"date": "2026-01-01"},  # ohne id
                                           {"id": "gueltig"}]},
                        raising=False)
    p = profile.Profile()
    p.save = lambda: None

    p.seed_seen_announcements()

    assert p.seen_announcements == ["gueltig"]


def test_der_erststart_ohne_erreichbaren_server_zeigt_trotzdem_die_kurzanleitung(
        leeres_profil):
    """Der eigentliche Ablauf darf nicht an einem fehlenden Cache hängen
    bleiben — die Kurzanleitung muss trotzdem erscheinen."""
    assert server_info.get_cached() is None
    z = ws.WelcomeState(_Maschine())
    z.enter()
    z.input.text = "Neuling"

    z._confirm()

    assert z.schritt == ws.SCHRITT_HILFE
    assert profile.current().seen_announcements == []


# ===========================================================================
# (4) Die Kurzanleitung erwähnt, wo Ankündigungen stehen
# ===========================================================================
def test_die_kurzanleitung_sagt_wo_ankuendigungen_stehen():
    zeilen = dict(ws.spielhinweise())
    assert i18n.tr("Ankündigungen") in zeilen
    hinweis = zeilen[i18n.tr("Ankündigungen")]
    assert "Einstellungen" in hinweis
    assert "Info" in hinweis


def test_der_hinweis_gibt_es_auch_auf_englisch():
    i18n.set_language("en")
    zeilen = dict(ws.spielhinweise())
    assert "Announcements" in zeilen
    assert "Settings" in zeilen["Announcements"]


def test_die_kurzanleitung_zeichnet_weiterhin_ohne_absturz(leeres_profil):
    z = ws.WelcomeState(_Maschine())
    z.enter()
    z.input.text = "Neuling"
    z._confirm()

    schirm = pygame.Surface((1920, 1080), pygame.SRCALPHA)
    z.render(schirm)                     # keine Ausnahme = bestanden


# ===========================================================================
# (5) Neuinstallation: ensure_announcements_seeded holt die Saat nach, sobald
#     die Liste zum ersten Mal wirklich vorliegt (08.08.2026).
#     seed_seen_announcements griff nur bei schon gefuelltem Cache; bei einer
#     Neuinstallation ist der beim Willkommen leer, also sah der Erstnutzer
#     alles. Diese Tests halten die Regel unabhaengig vom Cache-Zeitpunkt.
# ===========================================================================
from src.states.menu_shell_state import newest_unseen_announcement  # noqa: E402


def test_frisches_profil_verschluckt_die_erste_liste_stumm():
    """Regel: ein frisches Profil (announcements_seeded False) quittiert die
    ganze erste Liste stumm — danach ist nichts mehr ungesehen."""
    p = profile.Profile()
    p.save = lambda: None
    assert p.announcements_seeded is False

    anns = [{"id": "alt-1", "date": "2026-07-01", "text": {"de": "a"}},
            {"id": "alt-2", "date": "2026-07-02", "text": {"de": "b"}}]
    p.ensure_announcements_seeded(anns)

    assert p.announcements_seeded is True
    assert newest_unseen_announcement(anns, set(p.seen_announcements)) is None


def test_nach_der_saat_erscheint_eine_wirklich_neue_ankuendigung():
    """Nur die Vergangenheit wird geschenkt: was DANACH neu erscheint, kommt."""
    p = profile.Profile()
    p.save = lambda: None
    alt = {"id": "alt", "date": "2026-07-01", "text": {"de": "y"}}
    p.ensure_announcements_seeded([alt])

    neu = {"id": "ganz-neu", "date": "2026-08-08", "text": {"de": "x"}}
    treffer = newest_unseen_announcement([alt, neu], set(p.seen_announcements))
    assert treffer["id"] == "ganz-neu"


def test_ensure_ist_idempotent_und_verschluckt_spaeter_nichts():
    """Zweiter Aufruf ist ein no-op: eine spaeter hinzugekommene Ankuendigung
    darf nicht auch noch verschluckt werden."""
    p = profile.Profile()
    p.save = lambda: None
    p.ensure_announcements_seeded([{"id": "alt", "date": "2026-07-01"}])
    p.ensure_announcements_seeded([{"id": "alt", "date": "2026-07-01"},
                                   {"id": "neu", "date": "2026-08-08"}])
    assert "neu" not in p.seen_announcements


def test_bestehendes_profil_bekommt_nichts_verschluckt():
    """Ein bestehendes Profil (announcements_seeded True) laeuft ins Leere —
    seine Ankuendigungen erscheinen weiter."""
    p = profile.Profile(username="Philip", announcements_seeded=True)
    p.save = lambda: None
    p.ensure_announcements_seeded([{"id": "alt-1"}, {"id": "alt-2"}])
    assert p.seen_announcements == []


def test_load_grandfathert_ein_altes_profil_als_versorgt(monkeypatch):
    """Regel: ein auf Platte liegendes Profil ohne das neue Feld gilt als
    versorgt (True) — sonst wuerde einem bestehenden Spieler nach dem Update die
    ganze Sammlung nachtraeglich verschluckt."""
    import json
    from src.core import tresor
    alt = json.dumps({"username": "Philip", "seen_announcements": []})
    monkeypatch.setattr(tresor, "lesen", lambda *_a, **_k: alt)
    p = profile.Profile.load()
    assert p.announcements_seeded is True
