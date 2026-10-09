"""Streckenaustausch im Spiel: Seite, lokale Ablage und Netz (Plan 1.1.0 §5).

* die Seite mit einer falschen Verbindung (``synchron``, eigene ``api``)
* Speichern und Pruefen heruntergeladener Strecken
* Ende zu Ende gegen einen echten Relay im selben Prozess (Arbeitsfaden)
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import types

import pygame
import pytest

from src.net import strecken_client
from src.net.strecken_client import StreckenFehler
from src.track import strecken_online as lokal
from tests.strecken_hilfe import Relay, kopie, rundkurs, srv

# pygame wird in tests/conftest.py einmalig fuer den ganzen Lauf gestartet.


# --------------------------------------------------------------------------
# Hilfen
# --------------------------------------------------------------------------

@pytest.fixture
def ordner(tmp_path, monkeypatch):
    """Arbeitsverzeichnis und Nutzerverzeichnis in einem leeren Ordner."""
    from src.core import paths
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "track_roots", lambda: [tmp_path])
    return tmp_path


def _spielstrecke(entwurf: dict) -> dict:
    """Die Datei, die der Editor beim Veroeffentlichen schreibt."""
    from src.track.tile_track import TileTrackDraft
    return TileTrackDraft.from_draft_dict(entwurf).to_game_json()


def _eigene_ablegen(ordner, entwurf: dict, dateiname: str, **extra) -> str:
    ziel = ordner / "data" / "tracks" / "custom"
    ziel.mkdir(parents=True, exist_ok=True)
    daten = dict(_spielstrecke(entwurf), **extra)
    pfad = ziel / dateiname
    pfad.write_text(json.dumps(daten), encoding="utf-8")
    return str(pfad)


class FalscheApi:
    """Ersetzt ``strecken_client``: antwortet aus dem Speicher, merkt sich Aufrufe."""

    def __init__(self, tracks=None, fehler: dict | None = None):
        self.tracks = list(tracks or [])
        self.fehler = fehler or {}
        self.aufrufe: list[tuple] = []
        self.hochgeladen: list[dict] = []
        self.gemeldet: list[str] = []
        self.versteckt_nach_meldung = False

    def _pruefe(self, name):
        f = self.fehler.get(name)
        if f is not None:
            raise StreckenFehler(f)

    def liste(self, sd, sortierung, suche, seite, je_seite):
        self.aufrufe.append(("liste", sd.id, sortierung, suche, seite))
        self._pruefe("liste")
        treffer = [t for t in self.tracks
                   if not suche or (isinstance(t, dict) and suche.lower() in str(t.get("name")).lower())]
        if sortierung == "downloads":
            treffer.sort(key=lambda t: -t.get("downloads", 0))
        seiten = max(1, -(-len(treffer) // je_seite))
        seite = max(0, min(seite, seiten - 1))
        return {"type": "TRACK_LIST", "tracks": treffer[seite * je_seite:(seite + 1) * je_seite],
                "page": seite, "pages": seiten, "total": len(treffer)}

    def holen(self, sd, tid):
        self.aufrufe.append(("holen", sd.id, tid))
        self._pruefe("holen")
        t = next(t for t in self.tracks if t["id"] == tid)
        return dict(t, type="TRACK_DATA", track=t["_entwurf"])

    def hochladen(self, sd, entwurf, name, autor):
        self.aufrufe.append(("hochladen", sd.id, name, autor))
        self._pruefe("hochladen")
        self.hochgeladen.append(entwurf)
        return {"type": "TRACK_UPLOAD_OK", "id": "abcdef01", "name": name}

    def melden(self, sd, tid):
        self.aufrufe.append(("melden", sd.id, tid))
        self._pruefe("melden")
        self.gemeldet.append(tid)
        return self.versteckt_nach_meldung


def _eintrag(n: int, name: str | None = None, **extra) -> dict:
    d = {"id": f"{n:08x}", "name": name or f"Strecke {n}", "author": "Anna",
         "theme": "Plains", "difficulty": "Mittel", "length": 9200 + n, "pieces": 24,
         "downloads": n, "created": 1_790_000_000 + n,
         "outline": [[0, 0], [255, 0], [255, 180], [0, 180]],
         "_entwurf": rundkurs(5 + n, 4, name=name or f"Strecke {n}")}
    d.update(extra)
    return d


def _seite(api, **kw):
    from src.states.online_strecken_state import OnlineStreckenState
    sm = types.SimpleNamespace(zurueck_aufrufe=0, transition=lambda *a, **k: None)
    sm.zurueck = lambda fallback="menu": setattr(sm, "zurueck_aufrufe", sm.zurueck_aufrufe + 1)
    st = OnlineStreckenState(sm)
    st.enter(api=api, synchron=True, **kw)
    return st, sm


def _taste(key, **extra):
    return pygame.event.Event(pygame.KEYDOWN, key=key, unicode="", mod=0, **extra)


def _klick(rect):
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=rect.center, button=1)


def _weiter(st, anzahl=1):
    st.update(0.0)


# --------------------------------------------------------------------------
# Seite: Liste
# --------------------------------------------------------------------------

def test_seite_zeigt_die_liste_des_gewaehlten_servers(ordner):
    api = FalscheApi([_eintrag(n) for n in range(3)])
    st, _ = _seite(api)
    assert [z.eintrag["name"] for z in st.zeilen if z.eintrag] == [f"Strecke {n}" for n in range(3)]
    assert api.aufrufe[0][0] == "liste"
    assert st.auswahl == 0 and st.gesamt == 3
    assert st.b_aktion.label == "Herunterladen" and st.b_aktion.enabled


def test_server_umschalten_laedt_die_liste_dieses_servers_neu(ordner):
    from src.net import servers
    alle = servers.all_servers()
    if len(alle) < 2:
        pytest.skip("nur ein Server im Katalog")
    api = FalscheApi([_eintrag(1)])
    st, _ = _seite(api)
    erster = st.server.id
    st._aktion("server")
    assert st.server.id != erster
    assert api.aufrufe[-1][:2] == ("liste", st.server.id)
    assert st.server.label in st.b_server.label


def test_sortierung_suche_und_blaettern(ordner):
    api = FalscheApi([_eintrag(n) for n in range(20)])
    st, _ = _seite(api)
    assert st.seiten == 3 and st.seite == 0
    st._aktion("next")
    assert api.aufrufe[-1][4] == 1 and st.seite == 1
    st._aktion("sort")
    assert st.sortierung == "downloads" and api.aufrufe[-1][2:5] == ("downloads", "", 0)
    st.suchfeld.text = "strecke 1"
    st._aktion("suchen")
    assert api.aufrufe[-1][3] == "strecke 1" and st.gesamt == 11


def test_bild_runter_und_wheel_blaettern(ordner):
    api = FalscheApi([_eintrag(n) for n in range(20)])
    st, _ = _seite(api)
    st.handle_events([_taste(pygame.K_PAGEDOWN)])
    assert st.seite == 1
    st.handle_events([_taste(pygame.K_PAGEUP)])
    assert st.seite == 0
    st.handle_events([_taste(pygame.K_PAGEUP)])     # am Anfang: nichts
    assert st.seite == 0


def test_gesperrte_namen_werden_ausgeblendet(ordner, monkeypatch):
    from src.core import profile
    monkeypatch.setattr(profile, "_ist_gesperrt", lambda t: "boese" in t.lower())
    api = FalscheApi([_eintrag(1, "Schoene Runde"), _eintrag(2, "Boese Runde"),
                      _eintrag(3, author="boesewicht")])
    st, _ = _seite(api)
    assert [z.eintrag["name"] for z in st.zeilen if z.eintrag] == ["Schoene Runde"]


def test_kaputte_eintraege_aus_dem_netz_werden_uebersprungen(ordner):
    api = FalscheApi([_eintrag(1)])
    api.tracks += [{"id": "kurz"}, "text", {"id": "12345678", "name": 5, "author": "x"}]
    st, _ = _seite(api)
    assert len([z for z in st.zeilen if z.eintrag]) == 1


@pytest.mark.parametrize("code", ["OFFLINE", "TIMEOUT", "UNSUPPORTED", "RATE", "DISABLED"])
def test_fehler_beim_laden_wird_freundlich_angezeigt(ordner, code):
    st, _ = _seite(FalscheApi(fehler={"liste": code}))
    assert st.status and st.status_ok is False
    assert st.eintraege == [] and not any(z.eintrag for z in st.zeilen)
    assert st.status == StreckenFehler(code).text
    # Der Bildschirm laesst sich trotzdem zeichnen und bedienen.
    st.render(pygame.display.get_surface())
    st.handle_events([_taste(pygame.K_DOWN), _taste(pygame.K_RETURN)])


def test_veraltete_antwort_wird_verworfen(ordner):
    api = FalscheApi([_eintrag(1)])
    st, _ = _seite(api)
    st._gen += 1                                   # eine neuere Anfrage ist unterwegs
    st._liste_da({"tracks": [_eintrag(9)], "page": 0, "pages": 1, "total": 1}, None, st._gen - 1)
    assert st.eintraege[0]["name"] == "Strecke 1"


# --------------------------------------------------------------------------
# Seite: Herunterladen
# --------------------------------------------------------------------------

def test_herunterladen_legt_eine_spielstrecke_an(ordner):
    api = FalscheApi([_eintrag(1, "Alpenring")])
    st, _ = _seite(api)
    st._aktion("aktion")
    assert ("holen", st.server.id, f"{1:08x}") in api.aufrufe
    dateien = list((ordner / "data" / "tracks" / "custom").glob("*.json"))
    assert len(dateien) == 1
    d = json.loads(dateien[0].read_text(encoding="utf-8"))
    assert d["name"] == "Alpenring" and len(d["centerline"]) > 100
    assert d["online"]["id"] == f"{1:08x}" and d["online"]["author"] == "Anna"
    assert "editor_tiles" in d
    assert st.status_ok and "Alpenring" in st.status
    assert st.b_aktion.label == "Schon geladen" and not st.b_aktion.enabled
    # Ein zweiter Versuch legt keine Kopie an.
    st._aktion("aktion")
    assert len(list((ordner / "data" / "tracks" / "custom").glob("*.json"))) == 1


def test_heruntergeladene_strecke_taucht_in_der_streckenauswahl_auf(ordner):
    from src.states.track_select_state import TrackSelectState
    api = FalscheApi([_eintrag(1, "Alpenring")])
    st, _ = _seite(api)
    st._aktion("aktion")
    sel = TrackSelectState(types.SimpleNamespace())
    sel.enter()
    assert any(k.startswith("custom/") and sel._tracks_cache[k]["name"] == "Alpenring"
               for k in sel.track_keys)


def test_namensgleiche_eigene_strecke_wird_nicht_ueberschrieben(ordner):
    eigene = _eigene_ablegen(ordner, rundkurs(7, 5, name="Alpenring"), "alpenring.json")
    vorher = open(eigene, encoding="utf-8").read()
    api = FalscheApi([_eintrag(1, "Alpenring")])
    st, _ = _seite(api)
    st._aktion("aktion")
    assert open(eigene, encoding="utf-8").read() == vorher
    namen = sorted(json.loads(p.read_text(encoding="utf-8"))["name"]
                   for p in (ordner / "data" / "tracks" / "custom").glob("*.json"))
    assert namen == ["Alpenring", "Alpenring (2)"]


def test_defekter_entwurf_wird_nicht_gespeichert(ordner):
    kaputt = _eintrag(1)
    kaputt["_entwurf"] = {"pieces": "nein"}
    offen = _eintrag(2)
    offen["_entwurf"]["pieces"] = offen["_entwurf"]["pieces"][:-3]
    st, _ = _seite(FalscheApi([kaputt, offen]))
    st._aktion("aktion")
    assert st.status_ok is False and "beschädigt" in st.status
    st.auswahl = 1
    st._knoepfe_aktualisieren()
    st._aktion("aktion")
    assert st.status_ok is False and "nicht fahrbar" in st.status
    assert not (ordner / "data" / "tracks" / "custom").exists() or \
        not list((ordner / "data" / "tracks" / "custom").glob("*.json"))


def test_gesperrter_name_wird_nicht_gespeichert(ordner, monkeypatch):
    from src.core import profile
    monkeypatch.setattr(profile, "_ist_gesperrt", lambda t: "boese" in t.lower())
    st, _ = _seite(FalscheApi([_eintrag(1, "Boese Runde")]))
    # Die Zeile ist ausgeblendet; der Weg ueber speichern() ist trotzdem zu.
    with pytest.raises(lokal.EntwurfFehler):
        lokal.speichern(dict(_eintrag(1, "Boese Runde"), track=rundkurs()))


def test_dateiname_aus_dem_netz_kann_nicht_ausbrechen(ordner):
    daten = dict(_eintrag(1, "../../../Startup/x"), track=rundkurs(name="../../../Startup/x"))
    pfad, neu = lokal.speichern(daten)
    assert neu
    assert os.path.dirname(os.path.abspath(pfad)) == str(ordner / "data" / "tracks" / "custom")


# --------------------------------------------------------------------------
# Seite: Hochladen
# --------------------------------------------------------------------------

def test_eigene_strecken_zur_auswahl_nur_selbstgebaute(ordner):
    _eigene_ablegen(ordner, rundkurs(8, 6, name="Meine"), "meine.json")
    _eigene_ablegen(ordner, rundkurs(9, 6, name="Fremde"), "fremde.json",
                    online={"id": "12345678", "author": "X", "server": "helsinki"})
    (ordner / "data" / "tracks" / "custom" / "handarbeit.json").write_text(
        json.dumps({"name": "Ohne Entwurf", "centerline": []}), encoding="utf-8")
    (ordner / "data" / "tracks" / "custom" / "kaputt.json").write_text("{", encoding="utf-8")
    assert [s.name for s in lokal.eigene_strecken()] == ["Meine"]


def test_hochladen_mit_bestaetigung(ordner, monkeypatch):
    from src.core import profile
    monkeypatch.setattr(profile.current(), "username", "Felix", raising=False)
    _eigene_ablegen(ordner, rundkurs(8, 6, name="Meine"), "meine.json")
    api = FalscheApi([])
    st, _ = _seite(api)
    st._aktion("modus")
    assert st.modus == "eigene" and [e["name"] for e in st.eintraege] == ["Meine"]
    assert st.b_aktion.label == "Hochladen" and st.b_aktion.enabled
    st._aktion("aktion")
    # Erst die Frage: noch nichts geschickt.
    assert st.dialog is not None and api.hochgeladen == []
    assert "Felix" in st.dialog.message and st.server.label in st.dialog.message
    st.handle_events([_taste(pygame.K_RETURN)])          # „Hochladen" ist vorgewaehlt
    assert len(api.hochgeladen) == 1
    assert api.hochgeladen[0]["name"] == "Meine"
    assert ("hochladen", st.server.id, "Meine", "Felix") in api.aufrufe
    assert st.status_ok and "online" in st.status


def test_hochladen_abbrechen_schickt_nichts(ordner):
    _eigene_ablegen(ordner, rundkurs(8, 6, name="Meine"), "meine.json")
    api = FalscheApi([])
    st, _ = _seite(api)
    st._aktion("modus")
    st._aktion("aktion")
    st.handle_events([_taste(pygame.K_ESCAPE)])
    assert st.dialog is None and api.hochgeladen == []


@pytest.mark.parametrize("code", ["LIMIT_DAY", "STORE_FULL", "DUPLICATE", "BAD_TRACK",
                                  "TOO_LARGE", "OFFLINE", "UNSUPPORTED"])
def test_hochladefehler_werden_hoeflich_gezeigt(ordner, code):
    _eigene_ablegen(ordner, rundkurs(8, 6, name="Meine"), "meine.json")
    st, _ = _seite(FalscheApi(fehler={"hochladen": code}))
    st._aktion("modus")
    st._aktion("aktion")
    st.handle_events([_taste(pygame.K_RETURN)])
    assert st.status_ok is False and st.status == StreckenFehler(code).text
    assert st.beschaeftigt == ""                         # die Seite bleibt bedienbar
    st.render(pygame.display.get_surface())


def test_gesperrter_eigener_name_wird_gar_nicht_erst_hochgeladen(ordner, monkeypatch):
    from src.core import profile
    monkeypatch.setattr(profile, "_ist_gesperrt", lambda t: "boese" in t.lower())
    _eigene_ablegen(ordner, rundkurs(8, 6, name="Boese Runde"), "b.json")
    api = FalscheApi([])
    st, _ = _seite(api)
    st._aktion("modus")
    st._aktion("aktion")
    assert st.dialog is None and api.hochgeladen == []
    assert "nicht erlaubt" in st.status


def test_ohne_eigene_strecken_erklaert_die_seite_was_zu_tun_ist(ordner):
    st, _ = _seite(FalscheApi([]))
    st._aktion("modus")
    assert "Streckeneditor" in st.status
    assert not st.b_aktion.enabled
    st.render(pygame.display.get_surface())


# --------------------------------------------------------------------------
# Seite: Melden
# --------------------------------------------------------------------------

def test_melden_fragt_nach_und_blendet_versteckte_aus(ordner):
    api = FalscheApi([_eintrag(1), _eintrag(2)])
    api.versteckt_nach_meldung = True
    st, _ = _seite(api)
    st._aktion("melden")
    assert st.dialog is not None and api.gemeldet == []
    st.handle_events([_taste(pygame.K_RETURN)])
    assert api.gemeldet == [f"{1:08x}"]
    assert [z.eintrag["id"] for z in st.zeilen if z.eintrag] == [f"{2:08x}"]
    assert "gemeldet" in st.status


def test_melden_abbrechen(ordner):
    api = FalscheApi([_eintrag(1)])
    st, _ = _seite(api)
    st._aktion("melden")
    st.handle_events([_taste(pygame.K_RIGHT), _taste(pygame.K_RETURN)])   # „Abbrechen"
    assert api.gemeldet == []


# --------------------------------------------------------------------------
# Seite: Bedienung
# --------------------------------------------------------------------------

def test_escape_geht_eine_ebene_zurueck(ordner):
    _eigene_ablegen(ordner, rundkurs(8, 6, name="Meine"), "meine.json")
    st, sm = _seite(FalscheApi([_eintrag(1)]))
    st._aktion("modus")
    st.handle_events([_taste(pygame.K_ESCAPE)])
    assert st.modus == "liste" and sm.zurueck_aufrufe == 0
    st.handle_events([_taste(pygame.K_ESCAPE)])
    assert sm.zurueck_aufrufe == 1


def test_zurueckknopf_per_klick(ordner):
    st, sm = _seite(FalscheApi([_eintrag(1)]))
    st.handle_events([_klick(st.zurueck.rect)])
    assert sm.zurueck_aufrufe == 1


def test_fokus_kommt_mit_den_pfeilen_in_die_liste_und_wieder_hinaus(ordner):
    st, _ = _seite(FalscheApi([_eintrag(n) for n in range(4)]))
    erreicht = set()
    for _ in range(40):
        st.handle_events([_taste(pygame.K_DOWN)])
        st.update(0.0)
        erreicht.add(type(st.gruppe.focused).__name__)
    assert "StreckenZeile" in erreicht and "Button" in erreicht
    # Die Auswahl folgt dem Fokus auf einer Zeile.
    st.gruppe.index = st.gruppe.widgets.index(st.zeilen[2])
    st.update(0.0)
    assert st.auswahl == 2


def test_enter_in_der_suche_sucht(ordner):
    api = FalscheApi([_eintrag(n) for n in range(5)])
    st, _ = _seite(api)
    st.gruppe.index = st.gruppe.widgets.index(st.suchfeld)
    st.suchfeld.text = "strecke 3"
    st.handle_events([_taste(pygame.K_RETURN)])
    assert api.aufrufe[-1][3] == "strecke 3" and st.gesamt == 1


def test_beschaeftigt_sperrt_zweite_aktion(ordner):
    st, _ = _seite(FalscheApi([_eintrag(1)]))
    st.beschaeftigt = "Lade …"
    st._knoepfe_aktualisieren()
    assert not st.b_aktion.enabled and not st.b_melden.enabled


def test_zeichnen_in_beiden_arten_und_beiden_sprachen(ordner):
    from src.core import i18n
    _eigene_ablegen(ordner, rundkurs(8, 6, name="Meine"), "meine.json")
    api = FalscheApi([_eintrag(n) for n in range(10)])
    # Die Sprachtabelle wird relativ zum Arbeitsverzeichnis gelesen; das steht hier
    # in einem Wegwerfordner. Ohne diese Zeile wuerde eine leere Tabelle fuer den
    # ganzen Lauf zwischengespeichert und andere Tests sehen kein Englisch.
    wurzel = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(wurzel, "data", "i18n", "en.json"), encoding="utf-8") as f:
        i18n._tables["en"] = json.load(f)
    try:
        for sprache in ("de", "en"):
            i18n.set_language(sprache)
            st, _ = _seite(api)
            st.render(pygame.display.get_surface())
            st._aktion("modus")
            st.render(pygame.display.get_surface())
    finally:
        i18n.set_language("de")


# --------------------------------------------------------------------------
# Vorschau
# --------------------------------------------------------------------------

def test_umriss_passt_ins_rechteck_und_haelt_das_verhaeltnis():
    rect = pygame.Rect(100, 100, 200, 100)
    pts = lokal.umriss_in_rechteck([[0, 0], [255, 0], [255, 100], [0, 100]], rect, rand=10)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    assert min(xs) >= rect.x + 10 and max(xs) <= rect.right - 10
    assert min(ys) >= rect.y + 10 and max(ys) <= rect.bottom - 10
    assert (max(xs) - min(xs)) / (max(ys) - min(ys)) == pytest.approx(2.55, rel=0.05)
    # y ist gespiegelt: der Welt-Punkt (0, 0) liegt unten.
    assert pts[0][1] > pts[2][1]


@pytest.mark.parametrize("muell", [None, [], [[1]], ["a", "b"], [[float("nan"), 1]], 5])
def test_umriss_vertraegt_muell_aus_dem_netz(muell):
    try:
        assert lokal.umriss_in_rechteck(muell, pygame.Rect(0, 0, 50, 50)) == []
    except TypeError:
        pytest.fail("Muell im Umriss darf nicht abstuerzen")


def test_vorschau_zeichnet_ohne_punkte_einen_leeren_rahmen():
    from src.states.online_strecken_state import vorschau_zeichnen
    flaeche = pygame.Surface((120, 120))
    vorschau_zeichnen(flaeche, pygame.Rect(10, 10, 100, 100), None, (255, 255, 255))
    vorschau_zeichnen(flaeche, pygame.Rect(10, 10, 100, 100),
                      [[0, 0], [255, 0], [255, 255], [0, 255]], (255, 255, 255))


# --------------------------------------------------------------------------
# Netz: der echte Client gegen einen echten Relay
# --------------------------------------------------------------------------

class _RelayImFaden:
    """Der Relay laeuft in einem eigenen Faden mit eigener Ereignisschleife; der
    blockierende Client spricht von aussen mit ihm wie im Spiel."""

    def __init__(self, verzeichnis, **grenzen):
        self.verzeichnis, self.grenzen = verzeichnis, grenzen
        self.port = 0
        self._bereit = threading.Event()
        self._stop = None
        self._faden = threading.Thread(target=self._lauf, daemon=True)

    def _lauf(self):
        async def main():
            self._stop = asyncio.Event()
            async with Relay(self.verzeichnis, **self.grenzen) as r:
                self.port = r.port
                self._bereit.set()
                await self._stop.wait()
        self._schleife = asyncio.new_event_loop()
        self._schleife.run_until_complete(main())

    def __enter__(self):
        self._faden.start()
        assert self._bereit.wait(5)
        return self

    def __exit__(self, *exc):
        self._schleife.call_soon_threadsafe(self._stop.set)
        self._faden.join(5)

    @property
    def server(self):
        from src.net.servers import ServerDef
        return ServerDef(id="test", code_prefix="H", label="Test", tcp_host="127.0.0.1",
                         tcp_port=self.port, udp_host="127.0.0.1", udp_port=self.port)


def test_client_gegen_relay_ende_zu_ende(ordner, tmp_path_factory, monkeypatch):
    speicher = tmp_path_factory.mktemp("relay")
    with _RelayImFaden(str(speicher), pro_tag=9) as r:
        sd = r.server
        monkeypatch.setattr(strecken_client.server_probe, "resolve_endpoint",
                            lambda s: ("127.0.0.1", r.port, r.port))
        eigene = _eigene_ablegen(ordner, rundkurs(8, 6, name="Netzrunde"), "netz.json")
        s = lokal.eigene_strecken()[0]
        ok, _ = lokal.hochladbar(s)
        assert ok

        up = strecken_client.hochladen(sd, s.entwurf, s.name, "Anna")
        assert up["name"] == "Netzrunde"

        liste = strecken_client.liste(sd)
        assert liste["total"] == 1
        e = liste["tracks"][0]
        assert e["name"] == "Netzrunde" and e["author"] == "Anna" and lokal.eintrag_ok(e)

        daten = strecken_client.holen(sd, e["id"])
        os.remove(eigene)                                  # als kaeme sie von jemand anderem
        pfad, neu = lokal.speichern(daten, sd.id)
        assert neu
        gespeichert = json.loads(open(pfad, encoding="utf-8").read())
        assert gespeichert["name"] == "Netzrunde" and gespeichert["online"]["author"] == "Anna"

        with pytest.raises(StreckenFehler) as f:
            strecken_client.hochladen(sd, s.entwurf, "Nochmal", "Anna")
        assert f.value.code == "DUPLICATE" and "schon" in f.value.text

        assert strecken_client.melden(sd, e["id"]) is False
        with pytest.raises(StreckenFehler) as f:
            strecken_client.holen(sd, "00000000")
        assert f.value.code == "NOT_FOUND"


def test_seite_gegen_echten_relay(ordner, tmp_path_factory, monkeypatch):
    """Die Seite mit dem echten Client, im Arbeitsfaden wie im Spiel."""
    import time as _t
    speicher = tmp_path_factory.mktemp("relay2")
    with _RelayImFaden(str(speicher)) as r:
        monkeypatch.setattr(strecken_client.server_probe, "resolve_endpoint",
                            lambda s: ("127.0.0.1", r.port, r.port))
        from src.net import servers
        monkeypatch.setattr(servers, "all_servers", lambda: [r.server])
        monkeypatch.setattr(servers, "by_id", lambda i: r.server)
        _eigene_ablegen(ordner, rundkurs(8, 6, name="Seitenrunde"), "s.json")

        from src.states.online_strecken_state import OnlineStreckenState
        sm = types.SimpleNamespace(zurueck=lambda **k: None, transition=lambda *a, **k: None)
        st = OnlineStreckenState(sm)
        st.enter()                                          # echter Faden, echter Client

        def warte(bedingung):
            for _ in range(200):
                st.update(0.0)
                if bedingung():
                    return
                _t.sleep(0.025)
            raise AssertionError("Zeitueberschreitung: " + (st.status or st.beschaeftigt))

        warte(lambda: not st.laedt_liste)
        assert st.eintraege == []
        st._aktion("modus")
        st._aktion("aktion")
        st.handle_events([_taste(pygame.K_RETURN)])
        warte(lambda: st.status_ok and "online" in st.status)
        st._aktion("modus")
        warte(lambda: any(z.eintrag for z in st.zeilen))
        assert st.eintraege[0]["name"] == "Seitenrunde"
        st._aktion("aktion")
        warte(lambda: "gespeichert" in st.status)
        st.render(pygame.display.get_surface())


def test_server_offline_und_alter_server(ordner, monkeypatch):
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()                                              # nichts hoert mehr zu
    monkeypatch.setattr(strecken_client.server_probe, "resolve_endpoint",
                        lambda sd: ("127.0.0.1", port, port))
    from src.net.servers import ServerDef
    sd = ServerDef(id="x", code_prefix="H", label="X", tcp_host="127.0.0.1", tcp_port=port,
                   udp_host="127.0.0.1", udp_port=port)
    with pytest.raises(StreckenFehler) as f:
        strecken_client.liste(sd)
    assert f.value.code == "OFFLINE"

    # Ein „alter" Server: nimmt die Verbindung an und schliesst ohne Antwort.
    alt = socket.socket()
    alt.bind(("127.0.0.1", 0))
    alt.listen(1)
    port2 = alt.getsockname()[1]

    def bedienen():
        c, _ = alt.accept()
        c.recv(4096)
        c.close()
    threading.Thread(target=bedienen, daemon=True).start()
    monkeypatch.setattr(strecken_client.server_probe, "resolve_endpoint",
                        lambda sd: ("127.0.0.1", port2, port2))
    with pytest.raises(StreckenFehler) as f:
        strecken_client.liste(sd)
    assert f.value.code == "UNSUPPORTED"
    alt.close()


def test_minecraft_vorspann_wird_vor_die_anfrage_gesetzt(ordner, monkeypatch):
    """Hamburg: die Verbindung beginnt mit dem Vorspann des Tunnels."""
    import socket
    from src.net.servers import ServerDef
    srvsock = socket.socket()
    srvsock.bind(("127.0.0.1", 0))
    srvsock.listen(1)
    port = srvsock.getsockname()[1]
    empfangen = []

    def bedienen():
        c, _ = srvsock.accept()
        empfangen.append(c.recv(4096))
        c.close()
    threading.Thread(target=bedienen, daemon=True).start()
    monkeypatch.setattr(strecken_client.server_probe, "resolve_endpoint",
                        lambda sd: ("127.0.0.1", port, port))
    sd = ServerDef(id="hh", code_prefix="D", label="HH", tcp_host="127.0.0.1", tcp_port=port,
                   udp_host="127.0.0.1", udp_port=port, tcp_preamble="minecraft")
    with pytest.raises(StreckenFehler):
        strecken_client.liste(sd)
    srvsock.close()
    vorspann = sd.preamble_bytes("127.0.0.1", port)
    assert empfangen and empfangen[0].startswith(vorspann) and len(vorspann) > 5
    assert b"TRACK_LIST" in empfangen[0][len(vorspann):]


def test_kennung_bleibt_gleich(ordner):
    a = strecken_client.kennung()
    assert len(a) >= 8 and a == strecken_client.kennung()
