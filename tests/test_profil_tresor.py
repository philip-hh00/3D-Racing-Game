"""Verschlüsselte Profilablage mit Sicherung (E5 Schritt 6, §E4).

Der Zweck der Datei ist eine Bremsschwelle, der Zweck dieser Tests ist ein
anderer: **nichts darf verlorengehen**. In einem Profil stehen Bestzeiten, die
jemand über Wochen gefahren ist, und verschlüsselt heißt, dass niemand sie von
Hand retten kann, wenn das Format klemmt. Geprüft wird deshalb vor allem der
Weg zurück — kaputte Hauptdatei, halber Schreibvorgang, Klartext von vorher.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.core import profile, tresor  # noqa: E402

_BEISPIEL = {"username": "philip", "best_laps": {"oval": 16.214},
             "statistik": {"rennen": 7}}


@pytest.fixture
def pfad(tmp_path, monkeypatch):
    """Ein Profilpfad im tmp-Verzeichnis — das echte Profil bleibt unberührt."""
    p = tmp_path / "profile.json"
    monkeypatch.setattr(profile, "_profile_path", lambda: str(p))
    monkeypatch.setattr(profile, "_current", None, raising=False)
    return str(p)


def _text(pfad: str) -> str:
    with open(pfad, encoding="utf-8") as f:
        return f.read()


def _verbiegen(data: str) -> str:
    """Ein Zeichen des Geheimtexts **verlässlich** ändern.

    ``"A" + data[1:]`` sah aus wie eine Änderung, war aber in etwa einem von
    siebzig Läufen keine: der Nonce macht jeden Behälter anders, und irgendwann
    fängt einer von sich aus mit „A" an. Dann prüfte der Test eine unversehrte
    Datei und schlug fehl — ein Flackern, das nichts mit dem Tresor zu tun hat.
    """
    return ("B" if data[0] == "A" else "A") + data[1:]


# ---------------------------------------------------------------------------
# Behälter
# ---------------------------------------------------------------------------
def test_hin_und_zurueck():
    klar = json.dumps(_BEISPIEL)
    assert tresor.entpacken(tresor.packen(klar)) == klar


@pytest.mark.parametrize("klar", [
    "", "{}", "ä" * 500, json.dumps({"username": "Fahrer_Ö"}),
    "\n\t weird \x00 aber gueltig",
])
def test_jeder_text_ueberlebt(klar):
    assert tresor.entpacken(tresor.packen(klar)) == klar


def test_der_behaelter_bleibt_lesbarer_text():
    """Eine Datei, die plötzlich binär ist, lässt sich weder in einem
    Fehlerbericht zeigen noch in der Versionsverwaltung ansehen."""
    d = json.loads(tresor.packen(json.dumps(_BEISPIEL)))
    assert d["format"] == tresor.FORMAT
    assert "Bremsschwelle" in d["hinweis"], "offenes Visier: die Datei sagt es selbst"
    assert set(d) == {"format", "hinweis", "nonce", "sig", "data"}


def test_der_inhalt_steht_nicht_mehr_offen_da():
    behaelter = tresor.packen(json.dumps(_BEISPIEL))
    assert "philip" not in behaelter
    assert "best_laps" not in behaelter
    assert "16.214" not in behaelter


def test_zweimal_packen_gibt_zwei_verschiedene_behaelter():
    """Ohne Nonce wäre an zwei gleichen Dateien ablesbar, dass sich nichts
    geändert hat — und gleiche Anfänge verraten gleiche Inhalte."""
    klar = json.dumps(_BEISPIEL)
    a, b = tresor.packen(klar), tresor.packen(klar)
    assert a != b
    assert tresor.entpacken(a) == tresor.entpacken(b) == klar


def test_verbogener_geheimtext_faellt_auf():
    d = json.loads(tresor.packen(json.dumps(_BEISPIEL)))
    d["data"] = _verbiegen(d["data"])
    assert tresor.entpacken(json.dumps(d)) is None


def test_verbogener_nonce_faellt_auf():
    d = json.loads(tresor.packen(json.dumps(_BEISPIEL)))
    d["nonce"] = ("f" if d["nonce"][0] != "f" else "0") + d["nonce"][1:]
    assert tresor.entpacken(json.dumps(d)) is None


def test_fremde_unterschrift_faellt_auf():
    d = json.loads(tresor.packen(json.dumps(_BEISPIEL)))
    d["sig"] = "0" * 64
    assert tresor.entpacken(json.dumps(d)) is None


@pytest.mark.parametrize("kaputt", [
    "", "kein json", "[]", '{"format": "rp1"}', '{"format": "xx"}',
    '{"format": "rp1", "nonce": "zz", "sig": "", "data": ""}',
    '{"format": "rp1", "nonce": "00", "sig": "", "data": "!!!"}',
])
def test_muell_gibt_none_statt_absturz(kaputt):
    assert tresor.entpacken(kaputt) is None


def test_klartext_wird_nicht_fuer_einen_behaelter_gehalten():
    assert tresor.ist_behaelter(json.dumps(_BEISPIEL)) is False
    assert tresor.ist_behaelter(tresor.packen("{}")) is True


# ---------------------------------------------------------------------------
# Dateien, Sicherung, Übernahme
# ---------------------------------------------------------------------------
def test_schreiben_und_lesen(tmp_path):
    p = str(tmp_path / "profile.json")
    tresor.schreiben(p, json.dumps(_BEISPIEL))
    assert json.loads(tresor.lesen(p)) == _BEISPIEL
    assert tresor.ist_behaelter(_text(p))


def test_kein_zwischenstand_bleibt_liegen(tmp_path):
    p = str(tmp_path / "profile.json")
    tresor.schreiben(p, "{}")
    assert sorted(os.listdir(tmp_path)) == ["profile.json"]
    tresor.schreiben(p, "{}")
    assert sorted(os.listdir(tmp_path)) == ["profile.bak", "profile.json"]


def test_die_sicherung_haelt_die_vorherige_fassung(tmp_path):
    p = str(tmp_path / "profile.json")
    tresor.schreiben(p, json.dumps({"rennen": 1}))
    tresor.schreiben(p, json.dumps({"rennen": 2}))
    assert json.loads(tresor.lesen(p)) == {"rennen": 2}
    assert json.loads(tresor.entpacken(_text(tresor.bak_pfad(p)))) == {"rennen": 1}


def test_kaputte_hauptdatei_wird_still_aus_der_sicherung_ersetzt(tmp_path):
    p = str(tmp_path / "profile.json")
    tresor.schreiben(p, json.dumps({"rennen": 1}))
    tresor.schreiben(p, json.dumps({"rennen": 2}))
    with open(p, "w", encoding="utf-8") as f:
        f.write("halb geschr")
    assert json.loads(tresor.lesen(p)) == {"rennen": 1}, \
        "verloren ist höchstens die letzte Änderung, nicht alles"


def test_eine_kaputte_datei_ueberschreibt_die_gute_sicherung_nicht(tmp_path):
    """Sonst zerstört genau der Vorgang die Rettung, der sie braucht."""
    p = str(tmp_path / "profile.json")
    tresor.schreiben(p, json.dumps({"rennen": 1}))
    tresor.schreiben(p, json.dumps({"rennen": 2}))
    with open(p, "w", encoding="utf-8") as f:
        f.write("kaputt")
    tresor.schreiben(p, json.dumps({"rennen": 3}))
    assert json.loads(tresor.entpacken(_text(tresor.bak_pfad(p)))) == {"rennen": 1}
    assert json.loads(tresor.lesen(p)) == {"rennen": 3}


def test_ohne_datei_kommt_nichts(tmp_path):
    assert tresor.lesen(str(tmp_path / "gibtsnicht.json")) is None


def test_klartextprofil_von_vorher_wird_uebernommen(tmp_path):
    p = str(tmp_path / "profile.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(_BEISPIEL, f)
    assert json.loads(tresor.lesen(p)) == _BEISPIEL


# ---------------------------------------------------------------------------
# Am echten Profil
# ---------------------------------------------------------------------------
def test_profil_ueberlebt_speichern_und_laden(pfad):
    p = profile.Profile(username="philip", best_laps={"oval": 16.214})
    p.statistik = {"rennen": 7, "ghosts_geschlagen": ["oval"]}
    p.paints = {"kompaktwagen": "metallic:rubinrot"}
    p.language = "en"
    p.save()

    neu = profile.Profile.load()
    assert neu.username == "philip"
    assert neu.best_laps == {"oval": 16.214}
    assert neu.statistik == {"rennen": 7, "ghosts_geschlagen": ["oval"]}
    assert neu.paints == {"kompaktwagen": "metallic:rubinrot"}
    assert neu.language == "en"


def test_gespeichertes_profil_ist_verschluesselt(pfad):
    profile.Profile(username="philip").save()
    assert tresor.ist_behaelter(_text(pfad))
    assert "philip" not in _text(pfad)


def test_altes_klartextprofil_wird_gelesen_und_beim_speichern_umgestellt(pfad):
    """Die Migration braucht keinen eigenen Schritt: gelesen wird beides,
    geschrieben nur noch das eine."""
    with open(pfad, "w", encoding="utf-8") as f:
        json.dump({"username": "philip", "best_laps": {"oval": 16.214},
                   "sfx_volume": 0.3, "volume": 0.2}, f)
    p = profile.Profile.load()
    assert p.username == "philip"
    assert p.best_laps == {"oval": 16.214}
    assert p.sfx_menu_volume == p.sfx_race_volume == 0.3, "alte Regler erben"
    assert p.menu_volume == p.race_volume == 0.2

    p.save()
    assert tresor.ist_behaelter(_text(pfad))
    assert profile.Profile.load().best_laps == {"oval": 16.214}


def test_verbogenes_profil_faellt_auf_die_sicherung_zurueck(pfad):
    profile.Profile(username="philip", best_laps={"oval": 16.214}).save()
    profile.Profile(username="philip", best_laps={"oval": 15.0}).save()
    d = json.loads(_text(pfad))
    d["data"] = _verbiegen(d["data"])
    with open(pfad, "w", encoding="utf-8") as f:
        json.dump(d, f)
    assert profile.Profile.load().best_laps == {"oval": 16.214}


def test_ohne_profil_gibt_es_vorgaben(pfad):
    p = profile.Profile.load()
    assert p.username == "" and p.best_laps == {} and p.statistik == {}


def test_speichern_auf_einen_unmoeglichen_pfad_stuerzt_nicht_ab(monkeypatch, tmp_path):
    """``save`` wird aus dem Spielverlauf gerufen — es darf nie hochkommen."""
    monkeypatch.setattr(profile, "_profile_path",
                        lambda: str(tmp_path / "gibtsnicht" / "x" / "p.json"))
    profile.Profile(username="philip").save()      # keine Ausnahme


# ---------------------------------------------------------------------------
# Erststart-Vorgaben (08.08.2026)
# ---------------------------------------------------------------------------
def test_frisches_profil_startet_auf_englisch():
    """Regel: ein frisch angelegtes Profil ist englisch — das Spiel geht an ein
    internationales Publikum, Deutsch bleibt in den Einstellungen einen Klick
    entfernt."""
    assert profile.Profile().language == "en"


def test_frisches_profil_gilt_als_noch_nicht_versorgt():
    """Regel-Gegenstueck zum Grandfathering: ein frisches Profil ist NICHT
    versorgt, damit die erste Ankuendigungsliste stumm quittiert werden kann."""
    assert profile.Profile().announcements_seeded is False


def test_announcements_seeded_ueberlebt_speichern_und_laden(pfad):
    p = profile.Profile(username="philip")
    p.announcements_seeded = True
    p.save()
    assert profile.Profile.load().announcements_seeded is True
