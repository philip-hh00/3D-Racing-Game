"""Soundeffekte: Kanalverwaltung und Motorstimmen (Block C, §C6).

Geprüft wird das, was ohne Audiogerät prüfbar ist — und das ist genau der Teil,
in dem die Fehler stecken: Blockgrenzen, Schichtmischung, Kanalvergabe.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.core import sfx  # noqa: E402


# ── Schichtmischung ────────────────────────────────────────────────────────

def test_schichten_sind_nach_drehzahl_sortiert():
    s = sfx.schichten("6zyl")
    if not s:
        pytest.skip("keine Aufnahmen vorhanden")
    assert s.drehzahlen == sorted(s.drehzahlen)


def test_gewichte_summieren_sich_auf_eins():
    """Sonst schwankt die Lautstärke über den Drehzahlbereich."""
    s = sfx.schichten("6zyl")
    if not s:
        pytest.skip("keine Aufnahmen vorhanden")
    lo, hi = s.bereich
    for upm in np.linspace(lo, hi, 40):
        summe = sum(s.gewichte(float(upm)))
        assert abs(summe - 1.0) < 1e-6, f"bei {upm:.0f} U/min: {summe}"


def test_nie_mehr_als_zwei_schichten_gleichzeitig():
    """Drei gleichzeitig hieße drei verschiedene Aufnahmen übereinander — das
    verwaschen sich gegenseitig."""
    s = sfx.schichten("6zyl")
    if not s:
        pytest.skip("keine Aufnahmen vorhanden")
    lo, hi = s.bereich
    for upm in np.linspace(lo, hi, 200):
        aktiv = [w for w in s.gewichte(float(upm)) if w > 0.001]
        assert len(aktiv) <= 2, f"bei {upm:.0f} U/min: {len(aktiv)} Schichten"


def test_an_einer_aufnahmedrehzahl_klingt_nur_diese():
    """Genau dort ist keine Verstimmung nötig, also soll auch nichts
    beigemischt werden."""
    s = sfx.schichten("6zyl")
    if not s:
        pytest.skip("keine Aufnahmen vorhanden")
    for i, upm in enumerate(s.drehzahlen):
        g = s.gewichte(float(upm))
        assert g[i] == pytest.approx(1.0), f"{upm} U/min: {g}"


def test_ausserhalb_des_bereichs_wird_gehalten():
    s = sfx.schichten("6zyl")
    if not s:
        pytest.skip("keine Aufnahmen vorhanden")
    lo, hi = s.bereich
    assert s.gewichte(lo - 500)[0] == pytest.approx(1.0)
    assert s.gewichte(hi + 5000)[-1] == pytest.approx(1.0)


# ── Blockgrenzen ───────────────────────────────────────────────────────────

def _naht_und_grenze(folge: list[float]) -> tuple[float, float]:
    stimme = sfx.Motorstimme("6zyl")
    ganz = np.concatenate([stimme.block(u) for u in folge])
    L = sfx.BLOCK
    naht = [abs(float(ganz[i * L] - ganz[i * L - 1])) for i in range(1, len(folge))]
    innen = np.abs(np.diff(ganz))
    return max(naht), float(np.percentile(innen, 99.9))


@pytest.mark.parametrize("name,folge", [
    ("konstant", [3000.0] * 8),
    ("rampe", [1250.0 + i * 800 for i in range(9)]),
    ("sprung", [1250.0, 7930.0, 1250.0, 7930.0]),
])
def test_bloecke_haengen_ohne_knacken_zusammen(name, folge):
    """Der eigentliche Fund: die Drehzahl wurde über den Block geführt, die
    Schichtgewichte aber nicht — sie sprangen an der Blockgrenze. Gemessen
    0,194 Sprung gegen 0,032 im Inneren, also ein hörbares Knacken im Takt der
    Blocklänge."""
    if not sfx.schichten("6zyl"):
        pytest.skip("keine Aufnahmen vorhanden")
    naht, grenze = _naht_und_grenze(folge)
    assert naht < grenze, f"{name}: Naht {naht:.5f} über der Grenze {grenze:.5f}"


def test_phase_laeuft_ueber_bloecke_weiter():
    if not sfx.schichten("6zyl"):
        pytest.skip("keine Aufnahmen vorhanden")
    stimme = sfx.Motorstimme("6zyl")
    stimme.block(3000)
    erste = stimme.phase
    stimme.block(3000)
    assert stimme.phase > erste, "Phase wurde zurückgesetzt"


def test_block_bleibt_im_wertebereich():
    if not sfx.schichten("6zyl"):
        pytest.skip("keine Aufnahmen vorhanden")
    stimme = sfx.Motorstimme("6zyl")
    for upm in (1250, 4000, 7930):
        b = stimme.block(float(upm))
        assert b.dtype == np.float32
        assert np.all(np.abs(b) <= 1.0)


def test_ohne_aufnahmen_kommt_stille_statt_absturz():
    """Ein fehlender Motor darf das Rennen nicht abbrechen."""
    stimme = sfx.Motorstimme("gibt-es-nicht")
    assert not stimme
    b = stimme.block(3000)
    assert len(b) == sfx.BLOCK
    assert not np.any(b)


# ── Klangfärbung je Fahrzeug (§C5) ─────────────────────────────────────────

def _zentroid(x: np.ndarray) -> float:
    sp = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    fr = np.fft.rfftfreq(len(x), 1.0 / sfx.SR)
    return float(np.sum(sp * fr) / max(1e-9, np.sum(sp)))


def _rauschen(n: int = 8192) -> np.ndarray:
    return np.random.default_rng(7).normal(0.0, 0.2, n).astype(np.float32)


def test_ohne_faerbung_bleibt_das_signal_unangetastet():
    x = _rauschen()
    assert np.array_equal(sfx.Faerbung(0.0)(x), x)


def test_dunkel_nimmt_hoehen_weg_hell_gibt_welche_dazu():
    x = _rauschen()
    mitte = _zentroid(x)
    assert _zentroid(sfx.Faerbung(+0.4)(x)) < mitte
    assert _zentroid(sfx.Faerbung(-0.4)(x)) > mitte


def test_faerbung_aendert_die_lautstaerke_kaum():
    """Sonst wäre ein dunkler gefärbtes Fahrzeug auch leiser, und aus einer
    Klangfarbe würde eine Bevorzugung."""
    x = _rauschen()
    laut = lambda y: float(np.sqrt(np.mean(np.square(y))))
    for staerke in (-0.4, -0.2, 0.2, 0.4):
        verhaeltnis = laut(sfx.Faerbung(staerke)(x)) / laut(x)
        assert 0.85 < verhaeltnis < 1.15, f"{staerke}: Faktor {verhaeltnis:.2f}"


def test_faerbung_setzt_ueber_blockgrenzen_fort():
    """Ohne die Reste des letzten Blocks fängt der Filter alle 2048 Samples bei
    null an — hörbar als Knacken im Takt der Blocklänge.

    Nicht bitgleich, sondern auf ein Promille genau: der nachgeführte
    Pegelausgleich (§C8) misst je Aufruf und steht deshalb nach zwei Blöcken
    minimal anders als nach einem. Um das geht es hier nicht — geprüft wird der
    Filterspeicher.
    """
    x = _rauschen(4096)
    ganz = sfx.Faerbung(0.4)(x)
    f = sfx.Faerbung(0.4)
    stueckweise = np.concatenate([f(x[:2048]), f(x[2048:])])
    assert np.allclose(ganz, stueckweise, rtol=2e-3, atol=1e-5)
    naht = abs(float(stueckweise[2048] - stueckweise[2047]))
    innen = float(np.percentile(np.abs(np.diff(stueckweise)), 99.9))
    assert naht < innen, f"Naht {naht:.5f} über der üblichen Bewegung {innen:.5f}"


def test_tonhoehenversatz_verschiebt_den_klang():
    """Gemittelt, nicht einmal gemessen.

    Die Zyklusstreuung würfelt je Stimme eine langsame Ratenschwankung aus, und
    die verschiebt den Schwerpunkt um ±30–40 Hz. Zwischen 1,0 und 1,06 liegen
    aber nur rund 60 Hz — drei Einzelmessungen zu vergleichen ist damit ein
    Münzwurf, und der ging bis zum 05.08.2026 nur deshalb meist gut aus, weil
    die kürzeren Blöcke weniger von der Schwankung erfassten. Mit 4096 fiel er
    zum ersten Mal um. Geprüft wird der Zusammenhang, nicht eine Ziehung.
    """
    if not sfx.schichten("6zyl"):
        pytest.skip("keine Aufnahmen vorhanden")

    def zentroid_bei(tonhoehe):
        werte = []
        for _ in range(5):
            st = sfx.Motorstimme("6zyl", tonhoehe=tonhoehe)
            werte.append(_zentroid(
                np.concatenate([st.block(3000.0) for _ in range(8)])))
        return float(np.mean(werte))

    tief, mitte, hoch = zentroid_bei(0.94), zentroid_bei(1.0), zentroid_bei(1.06)
    assert hoch > mitte > tief, f"{tief:.0f} / {mitte:.0f} / {hoch:.0f} Hz"


def test_versatz_wird_begrenzt():
    """Ein grober Wert in einer Fahrzeug-JSON darf den Motor nicht in eine
    andere Bauart verwandeln."""
    assert sfx.Motorstimme("6zyl", tonhoehe=3.0).tonhoehe == pytest.approx(1.1)
    assert sfx.Motorstimme("6zyl", tonhoehe=0.1).tonhoehe == pytest.approx(0.9)


# ── Kanalverwaltung ────────────────────────────────────────────────────────

def test_freier_kanal_wird_genommen():
    k = sfx.Kanaele(anzahl=4)
    assert k.belegen(0.5, lambda n: True) == 0


def test_ohne_freien_kanal_weicht_der_leiseste():
    """Den ersten gefundenen zu verdrängen würgt sonst genau den Klang ab, der
    gerade am wichtigsten ist — bei zwei Kollisionen die laute."""
    k = sfx.Kanaele(anzahl=3)
    for i, laut in enumerate((0.9, 0.2, 0.7)):
        assert k.belegen(laut, lambda n, i=i: n == i) == i

    # Alles belegt: ein lauterer Klang verdrängt den leisesten (Kanal 1).
    assert k.belegen(0.8, lambda n: False) == 1


def test_leiser_klang_verdraengt_nichts():
    """Sonst reisst ein beilaeufiges Geraeusch einen Aufprall ab."""
    k = sfx.Kanaele(anzahl=2)
    k.belegen(0.9, lambda n: n == 0)
    k.belegen(0.8, lambda n: n == 1)
    assert k.belegen(0.1, lambda n: False) is None


def test_freigegebener_kanal_zaehlt_nicht_mehr():
    k = sfx.Kanaele(anzahl=2)
    k.belegen(0.9, lambda n: n == 0)
    k.frei_geben(0)
    assert k.belegen(0.1, lambda n: False) is None, "nichts belegt, nichts zu verdrängen"


# ── Lautstärke ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bereich,feld", [
    (sfx.RENNEN, "sfx_race_volume"),
    (sfx.MENUE, "sfx_menu_volume"),
])
def test_effektlautstaerke_bleibt_im_bereich(monkeypatch, bereich, feld):
    from src.core import profile
    for wert, erwartet in ((-1.0, 0.0), (0.0, 0.0), (0.35, 0.35), (5.0, 1.0)):
        monkeypatch.setattr(profile.current(), feld, wert, raising=False)
        assert sfx.effekt_lautstaerke(bereich) == pytest.approx(erwartet)


def test_die_beiden_regler_stoeren_sich_nicht(monkeypatch):
    """Der Grund für die Trennung: den Menüklick leiser drehen darf den Motor
    nicht mitnehmen."""
    from src.core import profile
    monkeypatch.setattr(profile.current(), "sfx_menu_volume", 0.1, raising=False)
    monkeypatch.setattr(profile.current(), "sfx_race_volume", 0.9, raising=False)
    assert sfx.effekt_lautstaerke(sfx.MENUE) == pytest.approx(0.1)
    assert sfx.effekt_lautstaerke(sfx.RENNEN) == pytest.approx(0.9)


def test_direkt_geht_an_beiden_reglern_vorbei(monkeypatch):
    """Zum Vorhören in den Einstellungen: dort zählt der gerade eingestellte
    Wert, nicht der zuletzt gespeicherte."""
    from src.core import profile
    monkeypatch.setattr(profile.current(), "sfx_menu_volume", 0.0, raising=False)
    monkeypatch.setattr(profile.current(), "sfx_race_volume", 0.0, raising=False)
    assert sfx.effekt_lautstaerke(sfx.DIREKT) == 1.0


def test_altes_profil_erbt_den_einen_regler(tmp_path, monkeypatch):
    """Wer die Effekte vor der Trennung leise gestellt hatte, findet sie
    danach nicht plötzlich laut vor."""
    import json
    from src.core import profile as prof

    pfad = tmp_path / "profile.json"
    pfad.write_text(json.dumps({"username": "Test", "sfx_volume": 0.2}),
                    encoding="utf-8")
    monkeypatch.setattr(prof, "_profile_path", lambda: str(pfad))
    p = prof.Profile.load()
    assert p.sfx_menu_volume == pytest.approx(0.2)
    assert p.sfx_race_volume == pytest.approx(0.2)


def test_spielen_ueberschreitet_die_kanalzahl_nicht(monkeypatch):
    """Der Mixer kann weniger Kanäle haben als EINZEL_KANAELE — etwa wenn
    pygame.init() ihn mit acht hochgezogen hat und mixer_starten() nicht
    durchkam. pygame.mixer.Channel(8) wirft dann IndexError, und zwar mitten
    im Menü. Aufgefallen, als jeder Knopfdruck einen Klang bekam (02.08.2026).
    """
    import pygame

    gespielt = []

    class _Kanal:
        def __init__(self, k):
            if k >= 8:
                raise IndexError("invalid channel index")
            self.k = k

        def get_busy(self):
            return False

        def set_volume(self, *a):
            pass

        def play(self, klang):
            gespielt.append(self.k)

    monkeypatch.setattr(sfx, "_mixer_bereit", lambda: True)
    monkeypatch.setattr(pygame.mixer, "get_num_channels", lambda: 8)
    monkeypatch.setattr(pygame.mixer, "Channel", _Kanal)
    monkeypatch.setattr(sfx, "_kanaele", sfx.Kanaele(anzahl=16))
    from src.core import profile
    monkeypatch.setattr(profile.current(), "sfx_menu_volume", 1.0, raising=False)

    sfx.spielen("click", 1.0, bereich=sfx.MENUE)
    assert gespielt and max(gespielt) < 8


# ── Anfang einer Stimme (§C8) ──────────────────────────────────────────────

def test_erster_block_knackt_nicht():
    """Gemessen am 02.08.2026: der allererste Block einer Motorstimme sprang
    bei Sample 15 um 0,109 — die Färbung hatte keine Vergangenheit und lieferte
    16 Ausgaben nahe null, bevor das Signal auf seinen echten Wert sprang.

    Hörbar bei **jedem** Motorstart, im Rennen also einmal je Fahrzeug: sechs
    Autos, sechs Knackser beim Start. Jetzt wird die Vergangenheit mit dem
    ersten Abtastwert gefüllt.
    """
    if not sfx.schichten("8zyl"):
        pytest.skip("keine Aufnahmen vorhanden")
    for faerbung in (0.0, 0.06, 0.4, -0.4):
        stimme = sfx.Motorstimme("8zyl", 0.96, faerbung)
        ganz = np.concatenate([stimme.block(3200.0) for _ in range(4)])
        spruenge = np.abs(np.diff(ganz))
        anfang = float(spruenge[:64].max())
        ueblich = float(np.percentile(spruenge, 99.9))
        assert anfang <= ueblich * 1.5, (
            f"Färbung {faerbung}: Anfang springt {anfang:.5f}, "
            f"üblich sind {ueblich:.5f}")


def test_faerbung_startet_ohne_stufe():
    """Dieselbe Falle isoliert: ein konstantes Signal darf am Anfang keine
    Stufe bekommen."""
    x = np.full(512, 0.3, dtype=np.float32)
    aus = sfx.Faerbung(0.4)(x)
    assert float(np.abs(np.diff(aus)).max()) < 1e-3


def test_hochpass_startet_ohne_stufe():
    x = np.full(512, 0.3, dtype=np.float32)
    aus = sfx.Hochpass(40.0)(x)
    assert float(np.abs(np.diff(aus)).max()) < 1e-3
    assert abs(float(aus[0])) < 1e-3, "der Gleichanteil ist sofort weg, nicht erst später"


# ---------------------------------------------------------------------------
# Akustische Drehzahl (Playtest 05.08.2026)
# ---------------------------------------------------------------------------
# „Motorsound elektrische Fahrzeuge hören sich wie ein summen und fiepen an."
# Und beim zweiten Durchgang mit der Stelle dazu: „In den sound dateien beginnt
# ab ca. 4sec der unrealistische Bereich" — 4 s der Hörprobe waren genau
# 6000 UPM. Der Grundton der Aufnahmen steigt streng proportional (UPM/5), der
# Elektro hat keine Gänge und dreht bis 16000: dort wären das 3200 Hz.

def test_unter_dem_knie_bleibt_die_drehzahl_unangetastet():
    st = sfx.Motorstimme("elektro")
    st.knie_upm, st.kompression = 6000.0, 0.25
    for upm in (0.0, 900.0, 3000.0, 5999.0, 6000.0):
        assert st.akustische_drehzahl(upm) == pytest.approx(upm)


def test_ueber_dem_knie_steigt_es_nur_noch_gebremst():
    st = sfx.Motorstimme("elektro")
    st.knie_upm, st.kompression = 6000.0, 0.25
    assert st.akustische_drehzahl(16000.0) == pytest.approx(8500.0)
    assert st.akustische_drehzahl(9000.0) == pytest.approx(6750.0)


def test_der_ton_steigt_weiter_und_bleibt_nicht_stehen():
    """Ein Elektromotor, dessen Ton bei Vollgas stehen bliebe, klänge tot."""
    st = sfx.Motorstimme("elektro")
    st.knie_upm, st.kompression = 6000.0, 0.25
    werte = [st.akustische_drehzahl(u) for u in (6000, 9000, 12000, 16000)]
    assert all(b > a for a, b in zip(werte, werte[1:])), werte


def test_ohne_knie_aendert_sich_gar_nichts():
    """Die Verbrenner laufen unverändert — ihr Getriebe hält sie ohnehin
    unter der Drehzahlgrenze."""
    st = sfx.Motorstimme("6zyl")
    st.knie_upm, st.kompression = 0.0, 1.0
    for upm in (900.0, 3000.0, 6000.0, 16000.0):
        assert st.akustische_drehzahl(upm) == pytest.approx(upm)


def test_nur_der_elektro_bekommt_das_knie():
    """Aus der Einstellungsdatei gelesen, nicht im Code verdrahtet."""
    from src.core import motorklang
    assert motorklang.werte("elektro")["knie_upm"] > 0.0
    for motor in ("4zyl", "6zyl", "8zyl"):
        assert motorklang.werte(motor)["knie_upm"] == 0.0


def test_bei_vollgas_liegt_der_grundton_deutlich_tiefer():
    """Gemessen am Klang, nicht an der Formel.

    Der Grundton bei 16000 UPM muss klar unter dem liegen, was ohne Knie
    herauskäme — sonst rechnet die Formel zwar, wirkt aber nicht.
    """
    if not sfx.schichten("elektro"):
        pytest.skip("keine Aufnahmen vorhanden")

    def grundton(knie, komp):
        st = sfx.Motorstimme("elektro")
        st.knie_upm, st.kompression = knie, komp
        x = np.concatenate([st.block(16000.0) for _ in range(6)])
        sp = np.abs(np.fft.rfft(x * np.hanning(len(x))))
        fr = np.fft.rfftfreq(len(x), 1.0 / sfx.SR)
        return float(fr[int(np.argmax(sp))])

    ohne, mit = grundton(0.0, 1.0), grundton(6000.0, 0.25)
    assert mit < ohne * 0.75, f"ohne {ohne:.0f} Hz, mit {mit:.0f} Hz"


# ---------------------------------------------------------------------------
# Die abgenommene Elektro-Färbung (Playtest 05.08.2026)
# ---------------------------------------------------------------------------
# Aus drei Hörproben (tools/elektro_hoerproben.py) wurde „etwas-dunkler"
# gewählt: Färbung +0,30 über dem Knie 5000/0,18. Gemessen liegt die bei
# 2207 Hz im spektralen Schwerpunkt.
#
# Diese Probe ist die **Obergrenze**, nicht der Mittelwert. Die Beanstandung
# lautete „viel zu hoch und fiepsig"; ein Elektro, der heller klingt als das
# abgenommene Muster, fiele wieder darunter. Die Streuung zwischen den drei
# Elektro-Fahrzeugen geht deshalb nur nach unten.

#: Spektraler Schwerpunkt der abgenommenen Hörprobe „etwas-dunkler", in Hz.
ABGENOMMEN_HZ = 2207.0


def _schwerpunkt(faerbung: float) -> float:
    """Spektraler Schwerpunkt der Elektro-Stimme über den Drehzahlverlauf der
    Hörproben — also das, was das Ohr als „hell" oder „dunkel" hört."""
    from src.core import motorklang
    verlauf = [(0.0, 900), (2.0, 6000), (3.5, 6000), (6.0, 16000),
               (8.0, 16000), (10.0, 1200)]

    def upm(t):
        for (t0, u0), (t1, u1) in zip(verlauf, verlauf[1:]):
            if t0 <= t <= t1:
                return u0 + (u1 - u0) * ((t - t0) / max(1e-9, t1 - t0))
        return verlauf[-1][1]

    st = sfx.Motorstimme("elektro", tonhoehe=1.0, faerbung=faerbung)
    werte = motorklang.werte("elektro")
    st.knie_upm = werte["knie_upm"]
    st.kompression = werte["kompression"]
    stuecke, t = [], 0.0
    while t < verlauf[-1][0]:
        stuecke.append(st.block(upm(t)))
        t += st.blocklaenge / sfx.SR
    x = np.concatenate(stuecke)
    sp = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    fr = np.fft.rfftfreq(len(x), 1.0 / sfx.SR)
    return float(np.sum(sp * fr) / max(1e-9, np.sum(sp)))


def test_kein_elektro_klingt_heller_als_die_abgenommene_probe():
    """Der eigentliche Beschluss aus dem Playtest, am Klang geprüft."""
    if not sfx.schichten("elektro"):
        pytest.skip("keine Aufnahmen vorhanden")
    from src.core import sfx_rennen
    from src.entities.vehicle_factory import VehicleFactory
    VehicleFactory.load_all_configs("data/vehicles")

    gemessen = {}
    for key in ("electric", "electric_2", "electric_3"):
        _ton, farb = sfx_rennen.klangfarbe_von_schluessel(key)
        gemessen[key] = _schwerpunkt(farb)
    # 1 % Luft: die Zyklusstreuung verschiebt den Schwerpunkt von Zug zu Zug.
    for key, hz in gemessen.items():
        assert hz <= ABGENOMMEN_HZ * 1.01, f"{key}: {hz:.0f} Hz, heller als abgenommen"
    # Und mindestens eines soll die Probe auch treffen, sonst ist die ganze
    # Klasse unbemerkt weiter abgesackt.
    assert min(gemessen.values()) < ABGENOMMEN_HZ * 0.99
    assert max(gemessen.values()) > ABGENOMMEN_HZ * 0.95, gemessen


def test_die_elektros_bleiben_untereinander_unterscheidbar():
    """Sonst sind die drei akustisch dasselbe Auto."""
    if not sfx.schichten("elektro"):
        pytest.skip("keine Aufnahmen vorhanden")
    from src.core import sfx_rennen
    from src.entities.vehicle_factory import VehicleFactory
    VehicleFactory.load_all_configs("data/vehicles")
    werte = sorted(_schwerpunkt(sfx_rennen.klangfarbe_von_schluessel(k)[1])
                   for k in ("electric", "electric_2", "electric_3"))
    for tiefer, hoeher in zip(werte, werte[1:]):
        assert hoeher - tiefer > 100.0, f"zu dicht beieinander: {werte}"


def test_der_elektro_bleibt_ueber_den_verbrennern():
    """Dunkler ja, aber ein Elektro darf nicht nach Diesel klingen.

    Der Sechszylinder liegt im Schwerpunkt bei rund 1000 Hz. Rutscht der
    Elektro dorthin, ist die Bauart nicht mehr zu hören.
    """
    if not sfx.schichten("elektro"):
        pytest.skip("keine Aufnahmen vorhanden")
    from src.core import sfx_rennen
    from src.entities.vehicle_factory import VehicleFactory
    VehicleFactory.load_all_configs("data/vehicles")
    for key in ("electric", "electric_2", "electric_3"):
        hz = _schwerpunkt(sfx_rennen.klangfarbe_von_schluessel(key)[1])
        assert hz > 1500.0, f"{key}: {hz:.0f} Hz, das klingt nicht mehr elektrisch"
