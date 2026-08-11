"""Der Audiofaden und sein Rückfallweg (06.08.2026).

Ein Gerät gibt es hier nicht, und genau deshalb prüft diese Datei die Hälfte,
die ohne Gerät entscheidet: **dass das Spiel ohne Audiofaden weiterläuft**.

Das ist keine Nebensache. ``sounddevice`` braucht PortAudio; unter Windows und
macOS liegt es im Paket bei, unter Linux nicht immer, und auf einem Rechner ohne
Ausgabegerät nützt es ohnehin nichts. Fällt der Weg aus und niemand fängt es ab,
ist ein Rennen still — schlimmer als der alte Klang, den er ersetzen sollte.

Der Rechner, auf dem diese Tests laufen, hat kein PortAudio. Der Rückfall ist
hier also nicht nachgestellt, sondern der Normalfall — was ihn zur ehrlichsten
Prüfung macht, die es dafür gibt.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.core import tonausgabe as ta  # noqa: E402


@pytest.fixture(autouse=True)
def sauber():
    yield
    ta.beenden()


# ── Der Rückfall ─────────────────────────────────────────────────────────────

def test_ohne_portaudio_meldet_es_sich_und_stuerzt_nicht_ab():
    gut, warum = ta.verfuegbar()
    if gut:
        pytest.skip("PortAudio ist hier vorhanden — der Rueckfall ist nicht zu pruefen")
    assert warum, "ein Fehlschlag ohne Begruendung ist im Feld nicht zu klaeren"
    assert ta.starten() is False
    assert ta.laeuft() is False
    assert ta.grund()


def test_ohne_laufenden_faden_gibt_es_keine_stimme():
    """Und zwar ``None`` statt einer Ausnahme — der Aufrufer soll den alten Weg
    nehmen, nicht abstürzen."""
    if ta.laeuft():
        pytest.skip("laeuft gerade")
    assert ta.stimme_anlegen(lambda n: None) is None


def test_beenden_ohne_start_ist_folgenlos():
    ta.beenden()
    ta.beenden()


def test_der_zustand_ist_auch_ohne_geraet_lesbar():
    """Er landet im Mitschnitt. Wirft er ohne Geraet, ist der Mitschnitt kaputt,
    und zwar genau auf den Rechnern, auf denen man ihn braucht."""
    z = ta.zustand()
    for feld in ("laeuft", "grund", "geraet", "rate", "vorrat_frames",
                 "vorrat_ms", "unterlaeufe", "stimmen"):
        assert feld in z, feld
    assert isinstance(z["laeuft"], bool)


# ── Die Kennwerte ────────────────────────────────────────────────────────────

def test_der_vorrat_liegt_im_vertretbaren_bereich():
    """Zu wenig reisst Loecher, zu viel laesst den Motor hinter dem Gaspedal
    herhinken."""
    ms = 1000.0 * ta.VORRAT / 48000
    assert 40.0 <= ms <= 150.0, f"{ms:.0f} ms"
    assert ta.KAPAZITAET > ta.VORRAT, "ohne Luft ueber dem Vorrat stockt der Erzeuger"
    assert ta.STUECK <= ta.VORRAT // 2, \
        "in zu grossen Stuecken laesst sich der Vorrat nicht fein halten"


# ── Die Verkabelung im Rennklang ─────────────────────────────────────────────

def test_die_rennstimme_waehlt_den_weg_nach_dem_faden():
    """Beide Wege müssen dieselbe Schnittstelle haben, sonst merkt es erst der
    Spieler — auf dem einen Rechner, auf dem der andere Weg greift."""
    from src.core import sfx_rennen
    gemeinsam = ("stille", "aktualisieren", "beenden")
    for name in gemeinsam:
        assert callable(getattr(sfx_rennen._RingStimme, name, None)), name
        assert callable(getattr(sfx_rennen._Stimme, name, None)), name


def test_die_ringstimme_belegt_keinen_mixerkanal():
    """Sonst waeren die Kanaele fuer Reifen und Aufpralle knapp, obwohl der
    Motorklang sie gar nicht mehr braucht."""
    from src.core import sfx_rennen
    assert not hasattr(sfx_rennen._RingStimme, "kanal_nr")
    import inspect
    quelle = inspect.getsource(sfx_rennen.Rennklang._stimme_fuer)
    assert "tonausgabe.laeuft()" in quelle, "der Weg wird gar nicht gewaehlt"


def test_das_abraeumen_kommt_ohne_kanalnummer_aus():
    """Eine Ringstimme hat keine. Ein blindes ``stimme.kanal_nr`` waere ein
    AttributeError mitten im Rennen, sobald ein Fahrzeug verschwindet."""
    import inspect
    from src.core import sfx_rennen
    quelle = inspect.getsource(sfx_rennen.Rennklang.aktualisieren)
    assert 'getattr(stimme, "kanal_nr", None)' in quelle


def test_der_audiofaden_wird_beim_beenden_geschlossen():
    """Ein offener Strom an einem beendeten Prozess haengt unter Windows das
    Fenster beim Schliessen."""
    import inspect
    from src.core.game import GameManager
    assert "tonausgabe" in inspect.getsource(GameManager.quit)


def test_der_audiofaden_wird_beim_laden_gestartet():
    import inspect
    from src.states.loading_state import LoadingState
    quelle = inspect.getsource(LoadingState._step_audio)
    assert "tonausgabe" in quelle
    assert "starten()" in quelle


# ── Die Regel, die alles trägt ───────────────────────────────────────────────

def test_im_rueckruf_wird_nur_kopiert():
    """Die wichtigste Regel des ganzen Umbaus: der Audiofaden rechnet nicht.

    Geprüft am Quelltext, weil sie sich ohne Gerät nicht vorführen lässt — und
    weil sie beim nächsten Eingriff genau die Regel ist, die man versehentlich
    bricht.
    """
    import inspect
    quelle = inspect.getsource(ta.starten)
    anfang = quelle.index("def _rueckruf")
    ende = quelle.index("_strom = sd.OutputStream")
    rueckruf = quelle[anfang:ende]
    assert "abrufen" in rueckruf
    for verboten in ("erzeugen", "with ", "sleep", "np.", "Motorstimme"):
        assert verboten not in rueckruf, \
            f"{verboten!r} gehoert nicht in den Audiofaden"


def test_der_erzeuger_schlaeft_wenn_der_vorrat_reicht():
    """Ein enges Warten haelt den GIL und nimmt dem Spiel Rechenzeit weg."""
    import inspect
    quelle = inspect.getsource(ta._erzeugen_bis_halt)
    assert "sleep" in quelle


# ── Der echte Weg, mit eingeschobenem Gerät ──────────────────────────────────
#
# Hier gibt es keine Soundkarte, und trotzdem darf der Weg, der beim Spieler
# gilt, nicht ungeprüft bleiben — sonst ist getestet, was **nicht** läuft.
# Deshalb wird ``sounddevice`` durch eine Attrappe ersetzt, die den Rückruf
# aufhebt, statt ihn an ein Gerät zu hängen. Danach lässt sich der Audiofaden
# von Hand takten, genau wie ein Treiber es täte.

class _AttrappenStrom:
    def __init__(self, samplerate, channels, dtype, blocksize, latency,
                 callback):
        self.samplerate = samplerate
        self.channels = channels
        self.callback = callback
        self.device = 0
        self.gestartet = False
        self.geschlossen = False

    def start(self):
        self.gestartet = True

    def stop(self):
        self.gestartet = False

    def close(self):
        self.geschlossen = True

    def takten(self, frames: int):
        """Einen Rückruf auslösen, wie der Treiber es tut."""
        import numpy as np
        puffer = np.zeros((frames, 2), dtype=np.float32)
        self.callback(puffer, frames, None, None)
        return puffer


@pytest.fixture
def attrappe(monkeypatch):
    import types
    modul = types.ModuleType("sounddevice")
    stroeme: list[_AttrappenStrom] = []

    def OutputStream(*, samplerate, channels, dtype, blocksize, latency,
                     callback):
        s = _AttrappenStrom(samplerate, channels, dtype, blocksize, latency,
                            callback)
        stroeme.append(s)
        return s

    modul.OutputStream = OutputStream
    modul.query_devices = lambda n: {"name": "Attrappe"}
    monkeypatch.setitem(sys.modules, "sounddevice", modul)
    ta.beenden()
    yield stroeme
    ta.beenden()


def test_mit_geraet_laeuft_der_faden_und_liefert_ton(attrappe):
    """Der Nachweis für den Weg, der beim Spieler gilt: von der Quelle über den
    Erzeugerfaden in den Puffer, den der Treiber abholt.

    Die Quelle ist bewusst ein Sinus und **nicht** ``Motorstimme``. Geprüft wird
    hier die Kette, nicht die Synthese — die hat ihre eigenen Tests. Mit den
    echten Aufnahmen hinge dieser Test an Zwischenspeichern in ``sfx``, die
    andere Testdateien verstellen; er fiel dann nur im vollen Lauf und war
    allein nicht zu reizen (gefunden 06.08.2026).
    """
    import time
    import numpy as np

    assert ta.starten() is True
    assert ta.laeuft() is True
    assert ta.grund() == ""

    phase = {"n": 0}

    def sinus(laenge: int) -> np.ndarray:
        t = np.arange(phase["n"], phase["n"] + laenge, dtype=np.float32)
        phase["n"] += laenge
        return (0.5 * np.sin(2.0 * np.pi * 440.0 * t / 48000.0)).astype(np.float32)

    assert ta.stimme_anlegen(sinus, 1.0, 1.0) is not None

    # Dem Erzeugerfaden Zeit geben, den Vorrat aufzubauen — genau das, was er
    # im Rennen auch tut, bevor der erste Rueckruf kommt.
    puffer = np.zeros((1, 2), dtype=np.float32)
    ende = time.monotonic() + 5.0
    while time.monotonic() < ende:
        puffer = attrappe[0].takten(512)
        if np.any(puffer):
            break
        time.sleep(0.01)

    assert np.any(puffer), "der Treiber hat nur Stille bekommen"
    assert np.max(np.abs(puffer)) <= 1.0, "uebersteuert"
    assert not np.any(np.isnan(puffer))

    z = ta.zustand()
    assert z["rate"] == 48000
    assert z["geraet"] == "Attrappe"


def test_eine_echte_motorstimme_laesst_sich_anhaengen(attrappe):
    """Der Anschluss an die Synthese, ohne ihren Pegel zu bewerten."""
    from src.core import sfx
    if not sfx.schichten("6zyl"):
        pytest.skip("keine Motoraufnahmen vorhanden")
    assert ta.starten() is True
    stimme = sfx.Motorstimme("6zyl")
    assert ta.stimme_anlegen(lambda n: stimme.block(3000.0, n), 1.0, 1.0) is not None


def test_mit_geraet_wird_beim_beenden_geschlossen(attrappe):
    assert ta.starten() is True
    ta.beenden()
    assert attrappe[0].geschlossen, "das Geraet blieb offen"
    assert ta.laeuft() is False


def test_ein_fehler_im_mischer_macht_den_rueckruf_nicht_kaputt(attrappe):
    """Der Rueckruf darf **nie** werfen. Eine Ausnahme im Audiofaden nimmt
    PortAudio uebel, und der Ton ist danach ganz weg statt kurz gestoert."""
    import numpy as np
    assert ta.starten() is True
    monkey = ta._mischer
    monkey.abrufen = lambda frames: (_ for _ in ()).throw(RuntimeError("absichtlich"))
    puffer = attrappe[0].takten(256)
    assert not np.any(puffer), "bei einem Fehler gehoert Stille heraus, kein Absturz"


def test_ohne_geraet_faellt_es_auf_pygame_zurueck(monkeypatch):
    """Der Fall, den es auf fremden Rechnern wirklich gibt."""
    import types
    modul = types.ModuleType("sounddevice")

    def OutputStream(**kw):
        raise OSError("kein Ausgabegeraet")

    modul.OutputStream = OutputStream
    modul.query_devices = lambda n: {"name": ""}
    monkeypatch.setitem(sys.modules, "sounddevice", modul)
    ta.beenden()
    assert ta.starten() is False
    assert ta.laeuft() is False
    assert "kein Ausgabegeraet" in ta.grund()


# ── Gerätewechsel im Betrieb (gemeldet 06.08.2026) ───────────────────────────
#
# „Wenn ich im Rennen das Audiogerät wechsle, schaltet nur der Menüsound um.
# Die Sounds im Rennen bleiben auf dem vorherigen Ausgabegerät."
#
# Kein Fehler, sondern der Unterschied der beiden Wege: SDL öffnet das
# **Standardgerät** als solches, und Windows verschiebt so einen Strom beim
# Umschalten mit. PortAudio löst beim Öffnen auf einen **konkreten** Endpunkt
# auf und bleibt dort.

def test_ein_wechsel_des_standardgeraets_verbindet_neu(attrappe, monkeypatch):
    """Der Kern: der Ring und alle Stimmen bleiben stehen, nur das Gerät wird
    darunter ausgetauscht."""
    assert ta.starten() is True
    ta.stimme_anlegen(lambda n: None, 1.0, 1.0)
    stimmen_vorher = ta.zustand()["stimmen"]

    monkeypatch.setattr(ta, "_standard", "Kopfhoerer")
    monkeypatch.setattr(ta, "standardgeraet", lambda: "Monitor")
    ta._wache()

    assert len(attrappe) == 2, "es wurde kein neuer Strom geoeffnet"
    assert attrappe[0].geschlossen, "der alte Strom blieb offen"
    assert ta.laeuft() is True
    assert ta.zustand()["stimmen"] == stimmen_vorher, \
        "beim Wechsel gingen Stimmen verloren"
    assert ta.zustand()["wechsel"] == 1


def test_ohne_wechsel_wird_nichts_angefasst(attrappe, monkeypatch):
    """Einmal je Sekunde nachsehen darf nicht einmal je Sekunde umschalten."""
    assert ta.starten() is True
    monkeypatch.setattr(ta, "_standard", "Kopfhoerer")
    monkeypatch.setattr(ta, "standardgeraet", lambda: "Kopfhoerer")
    for _ in range(5):
        ta._wache()
    assert len(attrappe) == 1
    assert ta.zustand()["wechsel"] == 0


def test_ohne_erkennbares_standardgeraet_haelt_die_wache_still(attrappe, monkeypatch):
    """Auf einem Rechner, auf dem SDL die Auskunft nicht gibt, soll es beim
    bisherigen Verhalten bleiben — und nicht dauernd neu verbunden werden."""
    assert ta.starten() is True
    monkeypatch.setattr(ta, "_standard", "Kopfhoerer")
    monkeypatch.setattr(ta, "standardgeraet", lambda: "")
    for _ in range(5):
        ta._wache()
    assert len(attrappe) == 1
    assert ta.zustand()["wechsel"] == 0


def test_der_erste_durchgang_verbindet_nicht_neu(attrappe, monkeypatch):
    """Beim allerersten Nachsehen gibt es noch keinen Vergleichswert — daraus
    darf kein Wechsel werden."""
    assert ta.starten() is True
    monkeypatch.setattr(ta, "_standard", "")
    monkeypatch.setattr(ta, "standardgeraet", lambda: "Monitor")
    ta._wache()
    assert len(attrappe) == 1
    assert ta._standard == "Monitor", "der Vergleichswert wurde nicht gemerkt"


def test_der_ton_laeuft_nach_dem_wechsel_weiter(attrappe, monkeypatch):
    """Nicht nur „ein neuer Strom ist da" — es muss auch wieder klingen."""
    import time
    import numpy as np
    assert ta.starten() is True

    phase = {"n": 0}

    def sinus(laenge: int) -> np.ndarray:
        t = np.arange(phase["n"], phase["n"] + laenge, dtype=np.float32)
        phase["n"] += laenge
        return (0.5 * np.sin(2.0 * np.pi * 440.0 * t / 48000.0)).astype(np.float32)

    ta.stimme_anlegen(sinus, 1.0, 1.0)
    monkeypatch.setattr(ta, "_standard", "Kopfhoerer")
    monkeypatch.setattr(ta, "standardgeraet", lambda: "Monitor")
    ta._wache()

    puffer = np.zeros((1, 2), dtype=np.float32)
    ende = time.monotonic() + 5.0
    while time.monotonic() < ende:
        puffer = attrappe[-1].takten(512)
        if np.any(puffer):
            break
        time.sleep(0.01)
    assert np.any(puffer), "nach dem Wechsel kam nur Stille"


def test_ein_gescheitertes_neuverbinden_nennt_den_grund(attrappe, monkeypatch):
    """Bleibt es stumm, muss im Mitschnitt stehen, warum."""
    assert ta.starten() is True
    modul = sys.modules["sounddevice"]

    def kaputt(**kw):
        raise OSError("Geraet weg")

    monkeypatch.setattr(modul, "OutputStream", kaputt)
    assert ta.neu_verbinden() is False
    assert "Neuverbinden fehlgeschlagen" in ta.grund()
    assert ta.laeuft() is False


def test_das_standardgeraet_steht_im_zustand():
    z = ta.zustand()
    assert "standardgeraet" in z
    assert "wechsel" in z


def test_die_wache_laeuft_im_erzeugerfaden_mit():
    """Kein zweiter Faden: der Erzeuger laeuft ohnehin, und ein zweiter waere
    ein zweiter Ort zum Aufraeumen."""
    import inspect
    quelle = inspect.getsource(ta._erzeugen_bis_halt)
    assert "_wache()" in quelle
    assert "WACHE_SEKUNDEN" in quelle


def test_sounddevice_steht_in_den_anforderungen():
    """Sonst fehlt es im gepackten Buendel — der Fehler von soundfile am
    04.08.2026, und er faellt erst dem ersten Spieler auf."""
    with open(os.path.join(_ROOT, "requirements.txt"), encoding="utf-8") as fh:
        inhalt = fh.read()
    assert "sounddevice" in inhalt


@pytest.mark.parametrize("spec", ["game.spec", "game_macos.spec"])
def test_sounddevice_wandert_ins_buendel(spec):
    """PyInstaller findet es nicht von selbst: importiert wird es erst zur
    Laufzeit, und die PortAudio-Bibliothek haengt am Hook."""
    with open(os.path.join(_ROOT, "Release", "pyinstaller", spec),
              encoding="utf-8") as fh:
        inhalt = fh.read()
    assert "'sounddevice'" in inhalt, f"{spec} nimmt den Audiofaden nicht mit"
