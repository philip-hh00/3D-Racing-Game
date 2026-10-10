"""Fahrhilfen und Controller-Vibration im Rennen — die Verdrahtung.

Alles, was Plan 1.1.0 (Punkt 3 und 6) im ``RaceState`` zu tun hat, steht hier und
nicht dort: der Rennzustand ruft nur wenige Haken (``aufbauen``, ``abgleichen``,
``fortschreiben``, ``stoss``, ``linie_setzen``, ``beenden``).

* **ABS / Traktionskontrolle:** jeder Mensch bekommt ein
  :class:`~src.entities.components.fahrhilfen.Fahrhilfen`-Objekt, solange er eine
  Hilfe eingeschaltet hat — sonst ``None`` und die Physik läuft wie vorher.
  Die Werte kommen aus dem Profil und werden jedes Bild geprüft, damit eine
  Änderung im Pausenmenü sofort gilt. KI, Ghost und die Abbilder der
  Mitspieler haben nie welche; online ändert die Hilfe nur die Eingabe des
  eigenen Autos, gesendet wird nichts Neues.
* **Ideallinie:** je Mensch ein Band (:class:`~src.render3d.ideallinie.Ideallinie3D`),
  das beim ersten Bedarf aus dem Fahrplan der KI gebaut wird.
* **Vibration:** je Mensch ein :class:`~src.core.vibration.Vibration` auf *seinem*
  Controller (Splitscreen: jeder auf seinem eigenen).
"""
from __future__ import annotations

from src.core import profile as profil_modul
from src.core import vibration
from src.core.settings import M_PER_PX
from src.entities.components.fahrhilfen import Fahrhilfen


class RennHilfen:
    def __init__(self, rennen) -> None:
        self.rennen = rennen
        self.vibration: dict[int, vibration.Vibration] = {}
        self.linien: dict = {}                 # Fahrzeugnummer -> Ideallinie3D
        self.randsteine = None
        self._randstein_fehler = False

    # -- Aufbau / Abbau ---------------------------------------------------------
    def aufbauen(self) -> None:
        r = self.rennen
        p = profil_modul.current()
        stufe = p.fahrhilfe("vibration")
        for hp in r._humans:
            self.vibration[hp.id] = vibration.Vibration(
                vibration.pad_index_von(getattr(hp, "input_source", None)), stufe)
        self.randsteine = None
        szene = r.szene
        netz = getattr(szene, "netz", None) if szene is not None else None
        if netz is not None:
            try:
                from src.physics.randstein_ort import Randsteine
                self.randsteine = Randsteine(netz)
            except Exception as fehler:        # nie ein Rennen kosten
                print(f"[RennHilfen] Randsteine nicht aufgebaut: {fehler}")

    def beenden(self) -> None:
        for v in self.vibration.values():
            v.stoppen()
        self.vibration.clear()
        for linie in self.linien.values():
            linie.freigeben()
        self.linien.clear()
        for hp in getattr(self.rennen, "_humans", []):
            hp.fahrhilfen = None

    # -- Fahrhilfen -------------------------------------------------------------
    def abgleichen(self) -> None:
        """Vor der Physik: Hilfen der Menschen nach Profil und Lage setzen."""
        r = self.rennen
        p = profil_modul.current()
        abs_an, tc_an = p.fahrhilfe("abs"), p.fahrhilfe("tc")
        # Die KI fährt die Auslaufrunde eines Menschen, und ein ausrollendes
        # Auto bekommt keine Eingabe: dort hilft nichts.
        fremd = set(getattr(r, "_player_ai_ids", ())) if r._dnf_coast_timer <= 0.0 else \
            {hp.id for hp in r._humans}
        for hp in r._humans:
            if hp.id in fremd or not (abs_an or tc_an):
                hp.fahrhilfen = None
                continue
            fh = hp.fahrhilfen
            if fh is None:
                fh = hp.fahrhilfen = Fahrhilfen()
            fh.abs_an, fh.tc_an = abs_an, tc_an

    # -- Ideallinie -------------------------------------------------------------
    def _linie_fuer(self, hp):
        """Das Band dieses Menschen; gebaut beim ersten Bedarf, sonst ``None``."""
        r = self.rennen
        if hp.id in self.linien:
            return self.linien[hp.id]
        from src.core import display
        ctx = display.kontext()
        if ctx is None or r.track is None:
            return None
        try:
            from src.ai import ideallinie as daten
            from src.render3d.ideallinie import Ideallinie3D
            linie = Ideallinie3D(ctx, daten.fuer_fahrzeug(r.track, getattr(hp, "wirk_config", hp.config)))
        except Exception as fehler:
            print(f"[RennHilfen] Ideallinie nicht aufgebaut: {fehler}")
            return None
        self.linien[hp.id] = linie
        return linie

    def linie_setzen(self, kamera) -> None:
        """Vor dem Zeichnen einer Kamera: ihre Linie (oder keine) an die Szene geben."""
        r = self.rennen
        szene = r.szene
        if szene is None:
            return
        szene.ideallinie_aktiv = None
        if not profil_modul.current().fahrhilfe("linie"):
            return
        try:
            index = r._kameras.index(kamera)
        except ValueError:
            index = 0
        if 0 <= index < len(r._humans):
            szene.ideallinie_aktiv = self._linie_fuer(r._humans[index])

    # -- Vibration --------------------------------------------------------------
    def stoss(self, fahrzeug, impuls: float) -> None:
        """Ein Treffer an einem Fahrzeug; wirkt nur, wenn es ein Mensch mit Controller ist."""
        v = self.vibration.get(getattr(fahrzeug, "id", None)) \
            if fahrzeug in self.rennen._humans else None
        if v is not None:
            v.stoss(impuls)

    def stoppen(self) -> None:
        for v in self.vibration.values():
            v.stoppen()

    def fortschreiben(self, dt: float) -> None:
        """Nach der Physik: Vibration aus dem Zustand der Autos."""
        r = self.rennen
        stufe = profil_modul.current().fahrhilfe("vibration")
        laeuft = r.race_manager is not None and r.race_manager.state == "racing"
        for hp in r._humans:
            v = self.vibration.get(hp.id)
            if v is None:
                continue
            v.stufe_setzen(stufe)
            if (not laeuft or hp.id in getattr(r, "_player_ai_ids", ())
                    or r._dnf_coast_timer > 0.0):
                v.stoppen()
                continue
            v.fortschreiben(dt, schlupf=self._schlupf(hp), wand=bool(hp.is_touching_wall),
                            randstein=self._auf_randstein(hp),
                            tempo_ms=hp.speed * M_PER_PX)

    def _schlupf(self, hp) -> float:
        """Rutschen 0..1, so wie Reifenspuren und Rauch es sehen (unabhängig von der Grafikstufe)."""
        from src.render3d import reifenspuren
        v = hp.physics.body.velocity
        kennung = hp.id
        laengs = (getattr(self.rennen, "_laengs_beschleunigung", None) or {}).get(kennung, 0.0)
        fh = hp.fahrhilfen
        vorn, hinten = reifenspuren.reifenschlupf(
            (v.x * M_PER_PX, v.y * M_PER_PX), float(hp.angle), laengs,
            gas=float(hp.gas_wirksam), bremse=float(hp.bremse_wirksam),
            handbremse=bool(hp.handbrake),
            antrieb=str(getattr(hp.config, "drive_type", "rwd") or "rwd"),
            abs_an=bool(fh is not None and fh.abs_an))
        return max(vorn, hinten)

    def _auf_randstein(self, hp) -> bool:
        if self.randsteine is None or self._randstein_fehler:
            return False
        try:
            x, y = hp.position
            return self.randsteine.auf_randstein(x, y, float(hp.angle), schluessel=hp.id)
        except Exception as fehler:
            print(f"[RennHilfen] Randsteinabfrage: {fehler}")
            self._randstein_fehler = True
            return False
