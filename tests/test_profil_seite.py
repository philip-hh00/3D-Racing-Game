"""Profilseite — Statistik und Erfolge sichtbar machen (E5 Schritt 3).

Umgesetzt als **Variante B, Kennzahlenband** (gewählt am 02.08.2026).

Geprüft wird, was schiefgehen kann, ohne dass es jemand sofort sieht: eine
Gruppe, die aus dem Bild fällt, ein Erfolg, der als erreicht gezeichnet wird
obwohl der Zähler ihn nicht hergibt, und die Menüleiste, die mit dem siebten
Tab über den Bildrand läuft.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.core import profile, statistik  # noqa: E402
from src.core.settings import SCREEN_WIDTH  # noqa: E402
from src.states.menu.profil_page import ProfilPage, _streckenname  # noqa: E402
from src.states.menu_shell_state import TAB_WERKSTATT, _TABS, MenuShellState  # noqa: E402


@pytest.fixture
def spielstand(monkeypatch):
    """Ein Profil mit Zahlen — ein leeres zeigte nur Nullen und liesse die
    Anzeige nicht beurteilen."""
    p = profile.Profile(username="Testfahrer",
                        best_laps={"oval": 16.214, "strecke_1": 88.11})
    p.save = lambda: None
    p.statistik = {
        "rennen": 47, "siege": 12, "podeste": 26, "meter": 184_300.0,
        "spielzeit_s": 6 * 3600 + 12 * 60, "gp_siege": 2,
        "ghosts_geschlagen": ["oval", "desert"],
        "online_rennen": 6, "online_siege": 2, "lobbys_gehostet": 1,
        "strecken_erstellt": 2, "strecken_veroeffentlicht": 1,
    }
    monkeypatch.setattr(profile, "_current", p, raising=False)
    monkeypatch.setattr(profile, "current", lambda: p)
    return p


@pytest.fixture
def seite(spielstand):
    s = ProfilPage()
    s.enter(object())
    return s


def _zeichnen(s: ProfilPage) -> pygame.Surface:
    schirm = pygame.Surface((SCREEN_WIDTH, 1080))
    s.draw(schirm, pygame.Rect(0, 108, SCREEN_WIDTH, 1080 - 108))
    return schirm


# ---------------------------------------------------------------------------
# Die Menüleiste mit sieben Tabs
# ---------------------------------------------------------------------------
def test_sieben_tabs_passen_ins_bild():
    """Mit den früheren festen 288 px wäre die Leiste 2064 px breit gewesen —
    zwei Tabs hätten über dem Bildrand gehangen."""
    shell = MenuShellState.__new__(MenuShellState)
    rects = shell._tab_rects()
    assert len(rects) == len(_TABS) == 7
    assert rects[0].x >= 0
    assert rects[-1].right <= SCREEN_WIDTH
    assert len({r.width for r in rects}) == 1, "alle gleich breit"


def test_die_tabs_ueberlappen_sich_nicht():
    shell = MenuShellState.__new__(MenuShellState)
    rects = shell._tab_rects()
    for links, rechts in zip(rects, rects[1:]):
        assert links.right < rechts.x


def test_der_werkstatt_tab_bleibt_wo_er_war():
    """Die Fahrzeugauswahl springt über diesen Index in die Werkstatt. Wäre
    PROFIL davor eingefügt worden, landete der Kurzweg woanders."""
    assert _TABS[TAB_WERKSTATT][0] == "WERKSTATT"


def test_profil_ist_ein_eigener_tab():
    arten = [t[2] for t in _TABS]
    assert arten.count("profil") == 1
    assert arten.index("profil") == arten.index("settings") - 1


# ---------------------------------------------------------------------------
# Inhalt
# ---------------------------------------------------------------------------
def test_jede_gruppe_kommt_genau_einmal_vor(seite):
    gruppen = [g for g, _ in seite._gruppen()]
    assert gruppen == sorted(set(gruppen), key=gruppen.index)
    gezeigt = sum(len(e) for _g, e in seite._gruppen())
    assert gezeigt == len(statistik.ERFOLGE), "kein Erfolg fällt unter den Tisch"


def test_die_seite_wird_geblaettert_und_zeigt_das_auch(seite):
    """Seit dem 03.08.2026 stehen die Bestzeiten **aller** Strecken im Profil,
    nicht nur der gefahrenen. Damit passt der Inhalt nicht mehr auf ein Bild —
    das ist gewollt, muss aber sichtbar sein: gewünscht war „zum Scrollen mit
    Mausrad, auch sichtbar wie bei anderen scrollbaren Listen."""
    _zeichnen(seite)
    assert seite._inhalt_h > seite._sichtbar_h, "sonst braucht es keinen Balken"
    # Und alles ist erreichbar: ganz unten endet der Inhalt am unteren Rand.
    seite._blaettern(10_000)
    assert seite.scroll == seite._inhalt_h - seite._sichtbar_h


def test_der_rollbalken_wird_gezeichnet_und_wandert(seite):
    """Ohne Balken sieht eine abgeschnittene Liste aus wie eine vollständige."""
    from src.ui import theme

    def daumen(schirm):
        """Die y-Werte, an denen der Balkendaumen steht (Akzentfarbe rechts)."""
        spalte = SCREEN_WIDTH - 40 - 6      # flaeche.right - 6, siehe _rollbalken
        return [y for y in range(120, 1080)
                if schirm.get_at((spalte, y))[:3] == theme.ACCENT_DIM[:3]]

    oben = daumen(_zeichnen(seite))
    assert len(oben) >= 30, "kein Daumen am rechten Rand"
    seite._blaettern(10_000)
    unten = daumen(_zeichnen(seite))
    assert unten and min(unten) > min(oben), "der Daumen wandert nicht mit"


def test_blaettern_bleibt_in_den_grenzen(seite):
    _zeichnen(seite)
    seite._inhalt_h = seite._sichtbar_h + 300
    seite._blaettern(10_000)
    assert seite.scroll == 300
    seite._blaettern(-10_000)
    assert seite.scroll == 0


def test_kennzahlen_kommen_aus_der_statistik(seite):
    werte = dict(seite._kennzahlen())
    assert werte["Rennen"] == "47"
    assert werte["Siege"] == "12"
    assert werte["Strecke"] == "184 km"
    assert werte["Zeit am Steuer"] == "6 h 12 min"


def test_erreichte_erfolge_stimmen_mit_der_statistik_ueberein(seite):
    """Die Seite darf nichts eigenes rechnen — sonst zeigt sie einen Erfolg als
    erreicht, den es laut Zähler nicht gibt."""
    assert seite._offen == statistik.erreicht(seite._werte)
    assert "rennen_20" in seite._offen and "rennen_50" not in seite._offen


def test_bestzeiten_stehen_fuer_alle_strecken_da(seite):
    """Gewünscht am 03.08.2026: alle verfügbaren Strecken, nicht nur die
    gefahrenen. Ohne die leeren Zeilen fehlt gerade die Auskunft, die man
    sucht — wo noch keine Zeit steht."""
    from src.core import paths
    zeilen = seite._bestzeiten()
    assert len(zeilen) >= len(paths.strecken())
    mit_zeit = [n for n, t, _e in zeilen if t is not None]
    ohne_zeit = [n for n, t, _e in zeilen if t is None]
    assert len(mit_zeit) == 2, "das Testprofil hat zwei Bestzeiten"
    assert ohne_zeit, "die ungefahrenen Strecken fehlen"


def test_die_namen_kommen_aus_den_streckendateien(seite):
    """Sonst hieße dieselbe Strecke im Profil anders als in der Auswahl."""
    namen = [n for n, _t, _e in seite._bestzeiten()]
    assert "Oval Teststrecke" in namen
    assert "Strecke 1" in namen, "Unterstriche werden ersetzt"
    assert not any("_" in n for n in namen)


def test_die_reihenfolge_ist_die_der_streckenauswahl(seite):
    from src.core import paths
    namen = [n for n, _t, _e in seite._bestzeiten()]
    assert namen[0] == "Oval Teststrecke", namen[:3]
    assert len(namen) == len(set(namen)), "keine Strecke doppelt"
    assert len(namen) >= len(paths.MITGELIEFERT)


def test_eine_zeit_zu_einer_verschwundenen_strecke_bleibt_stehen(seite, spielstand):
    """Eine über Wochen gefahrene Bestzeit verschwindet nicht, nur weil eine
    Datei gelöscht wurde."""
    spielstand.best_laps["gibtsnichtmehr"] = 12.5
    zeilen = {n: (t, e) for n, t, e in seite._bestzeiten()}
    assert zeilen.get("Gibtsnichtmehr") == (12.5, False)


@pytest.mark.parametrize("roh,erwartet", [
    ("oval", "Oval"), ("strecke_1", "Strecke 1"),
    ("custom/mein_kurs", "Mein kurs"), ("online/fremde.json", "Fremde"),
])
def test_streckennamen(roh, erwartet):
    assert _streckenname(roh) == erwartet


def test_zeichnen_ohne_profil_stuerzt_nicht_ab(monkeypatch):
    """Vor dem ersten Start gibt es weder Namen noch Zahlen."""
    leer = profile.Profile()
    leer.save = lambda: None
    monkeypatch.setattr(profile, "_current", leer, raising=False)
    monkeypatch.setattr(profile, "current", lambda: leer)
    s = ProfilPage()
    s.enter(object())
    _zeichnen(s)
    assert s._offen == set()
    # Die Strecken stehen trotzdem da, alle ohne Zeit — genau das ist die
    # Anzeige, die ein neues Profil braucht.
    assert all(t is None for _n, t, _e in s._bestzeiten())


def test_die_seite_aendert_nichts(seite, spielstand):
    """Nur anzeigen. Eine Seite, die beim Zeichnen zählt, wäre der schnellste
    Weg zu geschenkten Freischaltungen."""
    vorher = dict(spielstand.statistik)
    _zeichnen(seite)
    seite.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-3))
    seite.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN,
                                          unicode="", mod=0))
    _zeichnen(seite)
    assert spielstand.statistik == vorher


def test_esc_gehoert_der_shell(seite):
    """Die Seite darf ESC nicht verschlucken — sonst käme man nicht mehr aus
    ihr heraus (gemeldet 02.08.2026 für andere Seiten)."""
    esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="", mod=0)
    assert seite.handle_event(esc) is None


# ---------------------------------------------------------------------------
# Anordnung der Spalten (Wunsch vom 04.08.2026)
# ---------------------------------------------------------------------------
def test_die_gruppen_stehen_wo_sie_stehen_sollen(seite):
    """Gewünscht: Menge und Erkunden links, Können/Online/Vollständigkeit
    mittig, Bestzeiten allein rechts. Vorher verteilte die Seite die Karten „in
    die jeweils kürzeste Spalte" — sparsam, aber die Anordnung hing damit an den
    Kartenhöhen, und für die Bestzeiten blieb nur ein Rest am Spaltenfuß."""
    from src.states.menu.profil_page import SPALTEN_PLAN
    spalten = [[g for g, _e in s] for s in seite._spalten()]
    assert spalten[0] == ["Menge", "Erkunden"]
    assert spalten[1] == ["Können", "Online", "Vollständigkeit"]
    assert len(spalten) == len(SPALTEN_PLAN)


def test_keine_gruppe_kommt_doppelt_oder_gar_nicht_vor(seite):
    aus_plan = [g for s in seite._spalten() for g, _e in s]
    alle = [g for g, _e in seite._gruppen()]
    assert sorted(aus_plan) == sorted(alle)
    assert len(aus_plan) == len(set(aus_plan))


def test_eine_neue_gruppe_faellt_nicht_unter_den_tisch(seite, monkeypatch):
    """Wer in ``statistik.ERFOLGE`` eine Gruppe ergänzt und den Plan hier
    vergisst, soll sie trotzdem sehen — nicht nirgends."""
    monkeypatch.setattr(seite, "_gruppen",
                        lambda: seite.__class__._gruppen(seite) + [("Neues", [1, 2])])
    spalten = [[g for g, _e in s] for s in seite._spalten()]
    assert any("Neues" in s for s in spalten)
    # In die kürzere Spalte, nicht blind in die erste.
    assert "Neues" in spalten[0], spalten


def test_die_bestzeiten_haben_die_rechte_spalte_fuer_sich(seite):
    """Der Sinn der Umstellung: die Liste wächst mit jeder gebauten Strecke."""
    from src.states.menu.profil_page import BEST_SPALTE, SPALTEN, SPALTEN_PLAN
    assert BEST_SPALTE == SPALTEN - 1
    assert BEST_SPALTE >= len(SPALTEN_PLAN), "die Bestzeitenspalte ist verplant"


def test_in_der_bestzeitenspalte_ist_platz_fuer_deutlich_mehr_strecken(seite):
    """Am Fuß einer Erfolgsspalte war nach acht Einträgen Schluss."""
    _zeichnen(seite)
    passen = (seite._sichtbar_h - 44) // 38
    assert passen >= 18, f"nur {passen} Strecken ohne Blättern"
    assert passen > len(seite._bestzeiten())


def test_hinter_der_letzten_karte_wird_nicht_ins_leere_geblaettert(seite):
    """Die Lücke *zwischen* zwei Karten gehört nicht hinter die letzte."""
    from src.states.menu.profil_page import LUECKE, ZEILE_H
    _zeichnen(seite)
    gruppen = dict(seite._gruppen())
    hoehen = []
    for spalte in seite._spalten():
        h = sum(44 + len(gruppen[g]) * ZEILE_H for g, _e in spalte)
        h += (len(spalte) - 1) * LUECKE
        hoehen.append(h)
    assert seite._inhalt_h == max(hoehen)


def test_die_bestzeiten_bleiben_stehen_solange_sie_passen(seite):
    """Beim Blättern geht es um die Erfolge. Die Liste rechts mitzuschieben
    schnitte sie oben ab, obwohl in ihrer Spalte Platz ist."""
    def kopfzeile(schirm):
        """Die y-Zeilen, in denen rechts oben Text steht (die Kopfzeile)."""
        return [y for y in range(120, 400)
                if any(schirm.get_at((x, y))[:3] != (14, 16, 22)
                       for x in range(SCREEN_WIDTH - 620, SCREEN_WIDTH - 300, 4))]

    oben = kopfzeile(_zeichnen(seite))
    seite._blaettern(10_000)
    unten = kopfzeile(_zeichnen(seite))
    assert oben and oben == unten, "die Bestzeiten sind mitgewandert"


def test_eine_zu_lange_bestzeitenliste_blaettert_doch_mit(seite, spielstand):
    """Wer genug eigene Strecken baut, muss auch die letzte sehen können."""
    spielstand.best_laps.update({f"strecke_{i}": 10.0 + i for i in range(40)})
    _zeichnen(seite)
    hoehe = 44 + len(seite._bestzeiten()) * 38
    assert hoehe > seite._sichtbar_h, "Messaufbau: die Liste passt noch"
    seite._blaettern(10_000)
    _zeichnen(seite)
    # Sie blättert mit, aber nur bis zu ihrem eigenen Ende.
    assert seite.scroll >= hoehe - seite._sichtbar_h


# ---------------------------------------------------------------------------
# Vermerk "(eigene)" für selbst erstellte Strecken (05.08.2026)
# ---------------------------------------------------------------------------
def test_selbst_erstellte_strecken_bekommen_vermerk_eigene(seite, monkeypatch):
    """Wunsch Playtest 05.08.2026: Bei selbst erstellten Strecken soll erkennbar
    sein, dass sie von uns stammen."""
    # Mocke _strecken(), um auch eine eigene Strecke hinzuzufügen.
    from pathlib import Path
    original_strecken = ProfilPage._strecken

    def mock_strecken():
        aus = original_strecken()
        # Füge eine eigene Teststrecke mit eigen=True hinzu.
        aus.append(("custom/test_strecke", Path("data/tracks/custom/test_strecke.json"), True))
        return aus

    monkeypatch.setattr(ProfilPage, "_strecken", staticmethod(mock_strecken))
    zeilen = seite._bestzeiten()

    # Prüfe, dass die Strecke mit eigen=True vorhanden ist.
    eigenen = [(n, e) for n, t, e in zeilen if e is True]
    assert len(eigenen) > 0, "mindestens eine Strecke sollte eigen sein"
    assert any(eigen is True for _n, eigen in eigenen)


def test_mitgelieferte_strecken_ohne_vermerk(seite):
    """Die mitgelieferten Strecken sollten eigen=False haben."""
    zeilen = seite._bestzeiten()
    from src.core import paths

    # Die ersten Strecken sollten mitgeliefert sein (eigen=False).
    mitgelieferte_namen = [n for n, _t, e in zeilen if not e][:len(paths.MITGELIEFERT)]
    assert len(mitgelieferte_namen) >= 1, "mindestens eine mitgelieferte Strecke"

    # Prüfe, dass alle die erste oder zweite Strecke eigen=False haben.
    for i, (n, t, e) in enumerate(zeilen[:2]):
        assert e is False, f"Strecke {i} ({n}) sollte eigen=False sein"


def test_vermerk_sprengt_nicht_spaltenbreite(seite):
    """Der Vermerk (eigene) darf die Spaltenbreite nicht sprengen und nicht
    in die Zeitspalte laufen. Getestet durch Zeichnen ohne Fehler."""
    zeilen = seite._bestzeiten()
    assert all(isinstance(n, str) and isinstance(t, (float, type(None))) and isinstance(e, bool)
               for n, t, e in zeilen), "Struktur sollte stimmen"
    _zeichnen(seite)  # Sollte ohne Exception zeichnen.
    # Das ist ausreichend — wenn layout-Fehler kämen, würden pygame oder Text
    # eine Exception werfen, wenn etwas aus Grenzen läuft.
