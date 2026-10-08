"""Movie-Modus nach der eigenen Zieldurchfahrt (Plan 1.1.0, Abschnitt 2).

Wer ins Ziel kommt, sieht nicht mehr die Verfolgerkamera, sondern erst ein
Auszoomen und dann TV-Kameras an der Strecke, die dem Feld folgen — solange
andere noch fahren. 30 Sekunden nach dem Ende des Feldes (alle im Ziel oder
DNF) kommen die Ergebnisse; waehrend dieser 30 s springt ``Enter``/``A`` sofort
dorthin. Vorher tut die Taste nichts: niemand wird vorzeitig gewertet.

Die Rechnung steht in ``src/render3d/tv_regie.py`` (rein, ohne Fenster). Dieses
Modul klebt sie an den Rennzustand: es liest Fahrzeuge, haelt die Uhr, ersetzt
die Kamera beim Zeichnen und das HUD. ``RaceState`` ruft nur wenige Haken:

* ``zuruecksetzen()``        in ``enter()``
* ``beginnen(fahrzeug)``     bei der Zieldurchfahrt eines Menschen
* ``fortschreiben(dt)``      je Bild nach dem Nachziehen der Kameras
* ``tick(dt)``               je Bild, zaehlt den Nachlauf
* ``zurueckhalten(zeilen)``  am Anfang von ``_starte_ausblenden``
* ``ansichten(...)``         in ``_welt_zeichnen``
* ``taste(ereignis)``        in ``handle_events``
* ``hud_zeichnen(...)``      in ``render``

Der Online-Ablauf bleibt unberuehrt: Ergebnisse und Wertung kommen wie bisher
an; die Uhr verschiebt nur den Zeitpunkt, an dem die Seite erscheint.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pygame

from src.core.i18n import tr

#: In diesen Modi laeuft der Film. Zeitfahren und Team-Zeitfahren gehen wie
#: bisher sofort in die Ergebnisse.
MOVIE_MODI = ("Rennen", "Grand Prix")


def _ohne_absturz(funktion):
    """Ein Fehler im Film darf kein Rennen kosten: Film aus, Rennen laeuft wie vor 1.1.0."""
    import functools

    @functools.wraps(funktion)
    def huelle(self, *args, **kwargs):
        try:
            return funktion(self, *args, **kwargs)
        except Exception as fehler:
            import traceback
            traceback.print_exc()
            print(f"[RaceState] Movie-Modus abgeschaltet: {fehler}")
            self.filme.clear()
            self.wartet = False
            return None
    return huelle


class MovieModus:
    """Der Movie-Modus eines Rennens (ein Exemplar je ``RaceState``)."""

    def __init__(self, rennen) -> None:
        self.r = rennen
        self.zuruecksetzen()

    # -- Zustand -------------------------------------------------------------
    def zuruecksetzen(self) -> None:
        from src.render3d import tv_regie
        self.filme: dict[int, Any] = {}        # Index in ``_humans`` -> Film
        self.reihenfolge: list[int] = []       # in der Reihenfolge der Zieldurchfahrten
        self.nachspiel = tv_regie.Nachspiel()
        self.wartet = False                    # _starte_ausblenden ist zurueckgehalten
        self.freigegeben = False               # die Uhr ist durch (oder uebersprungen)
        self.zeilen = None                     # die zurueckgehaltenen Ergebniszeilen
        self.skip_gewuenscht = False           # Enter/A im Nachlauf gedrueckt
        self._kurs = None
        self._standorte = None
        self._hoehe_fn = None
        self._hindernisse_arr = None
        self._vorbereitet = False

    @property
    def aktiv(self) -> bool:
        return bool(self.filme)

    def alle_menschen_im_film(self) -> bool:
        r = self.r
        humans = getattr(r, "_humans", None) or []
        return bool(humans) and all(i in self.filme for i in range(len(humans)))

    # -- Vorbereitung: Standorte einmal je Rennen -----------------------------
    def _vorbereiten(self) -> bool:
        if self._vorbereitet:
            return bool(self._standorte)
        self._vorbereitet = True
        r = self.r
        track = getattr(r, "track", None)
        if track is None:
            return False
        from src.core.settings import M_PER_PX
        from src.render3d import tv_regie
        try:
            szene = getattr(r, "szene", None)
            netz = getattr(szene, "netz", None)
            if netz is not None and len(getattr(netz, "mittellinie", [])) >= 3:
                linie = np.asarray(netz.mittellinie, dtype=np.float64)[:, :2]
                halb = float(netz.halbe_breite_m)
                name = netz.name or str(r._track_path)
            else:
                linie = np.asarray(track.centerline, dtype=np.float64) * M_PER_PX
                halb = float(track.track_width) * M_PER_PX / 2.0
                name = str(getattr(r, "_track_path", "strecke"))
            hindernisse = self._hindernisse(szene)
            self._hindernisse_arr = hindernisse
            gel = getattr(szene, "gelaende", None)
            self._hoehe_fn = gel.hoehe if gel is not None else None
            self._kurs = tv_regie.Rundkurs(linie)
            self._standorte = tv_regie.kameras_platzieren(
                linie, halb, name=name, hoehe_fn=self._hoehe_fn,
                hindernisse=hindernisse, abstand_m=40.0)
        except Exception as fehler:     # ein Fehler im Film darf kein Rennen kosten
            import traceback
            traceback.print_exc()
            print(f"[RaceState] Movie-Modus aus: {fehler}")
            self._standorte = None
        return bool(self._standorte)

    @staticmethod
    def _hindernisse(szene) -> np.ndarray:
        """``x, y, Radius, Hoehe`` von allem, was die Szene um die Strecke stellt."""
        orte = getattr(szene, "platzierungen", None) or []
        if not orte:
            return np.zeros((0, 4))
        from src.render3d import platzierung
        try:
            tafel = platzierung.grundrisse(szene.thema)
            katalog = platzierung.standardkatalog()
        except Exception:
            tafel, katalog = {}, {}
        zeilen = []
        for o in orte:
            gr = tafel.get(o.modell)
            skala = float(o.skala)
            r = (gr.umkreis if gr is not None else 2.0) * skala
            h = float((katalog.get(o.modell) or {}).get("hoehe_m", 0.0)) * skala
            zeilen.append((o.x, o.y, max(0.3, r), h if h > 0.0 else float("nan")))
        a = np.asarray(zeilen, dtype=np.float64).reshape(-1, 4)
        fehlt = np.isnan(a[:, 3])
        if fehlt.any():
            from src.render3d import tv_regie
            a[fehlt, 3] = tv_regie.hindernisse_normalisieren(a[fehlt, :3])[:, 3]
        return a

    def vorbereiten(self) -> None:
        """Die Kameras beim Laden aufstellen (kostet einen Moment, der hinter dem
        Ladebildschirm nicht auffaellt, aber im Ziel ruckeln wuerde)."""
        from src.core import race_setup
        if race_setup.current().mode in MOVIE_MODI:
            self._vorbereiten()

    # -- Haken: Beginn ---------------------------------------------------------
    @_ohne_absturz
    def beginnen(self, fahrzeug) -> None:
        """Ein Mensch ist (regulaer) ins Ziel gekommen."""
        r = self.r
        from src.core import race_setup
        if race_setup.current().mode not in MOVIE_MODI:
            return
        humans = getattr(r, "_humans", None) or []
        if fahrzeug not in humans:
            return
        idx = humans.index(fahrzeug)
        if idx in self.filme or not self._vorbereiten():
            return
        from src.render3d import tv_regie
        rm = r.race_manager
        regie = tv_regie.Regie(self._kurs, self._standorte,
                               runden_gesamt=getattr(rm, "total_laps", 3),
                               hindernisse=self._hindernisse_arr, hoehe_fn=self._hoehe_fn)
        platz = r._online_position(fahrzeug.id) if r._online else rm.get_position(fahrzeug.id)
        from src.states.race_state import SICHTFELD_GRAD
        film = tv_regie.Film(regie, fov_basis=SICHTFELD_GRAD, hoehe_fn=self._hoehe_fn,
                             platz=platz, kennung=fahrzeug.id)
        self.filme[idx] = film
        self.reihenfolge.append(idx)

    # -- Haken: je Bild --------------------------------------------------------
    def _autos(self) -> list:
        from src.render3d import tv_regie
        from src.core.settings import M_PER_PX
        from src.states.race_state import szenen_kennung
        r = self.r
        rm = r.race_manager
        if rm is None or r.track is None:
            return []
        num_wp = max(1, len(r.track.waypoints))
        gesamt = float(getattr(rm, "total_laps", 3))
        autos = []
        humans = set(id(v) for v in (getattr(r, "_humans", None) or []))
        for v in (*r._humans, *r.ai_vehicles):
            t = rm.lap_trackers.get(v.id)
            if t is None:
                continue
            autos.append(tv_regie.Auto(
                kennung=szenen_kennung(v), x=v.position[0] * M_PER_PX,
                y=v.position[1] * M_PER_PX, gier=float(v.angle),
                tempo=float(getattr(v, "speed", 0.0)) * M_PER_PX,
                runden=min(gesamt, (t.current_lap - 1) + t.waypoint_progress / num_wp),
                im_ziel=v.id in rm.finished_ids, eigen=id(v) in humans,
                name=r._driver_names.get(v.id, "")))
        if r._online:
            for rv in r._remote_vehicles:
                if not getattr(rv, "bereit", False):
                    continue
                lauf = (rv.lap - 1) + rv.wp / num_wp
                autos.append(tv_regie.Auto(
                    kennung=szenen_kennung(rv), x=rv.position[0] * M_PER_PX,
                    y=rv.position[1] * M_PER_PX, gier=float(rv.angle),
                    tempo=float(rv.speed) * M_PER_PX,
                    runden=min(gesamt, max(0.0, lauf)), im_ziel=lauf >= gesamt,
                    name=getattr(rv, "driver_name", "") or ""))
        return autos

    @_ohne_absturz
    def fortschreiben(self, dt: float) -> None:
        if not self.filme:
            return
        r = self.r
        from src.states.race_state import szenen_kennung
        autos = self._autos()
        for idx, film in self.filme.items():
            if idx >= len(r._humans) or idx >= len(r._kameras):
                continue
            hp = r._humans[idx]
            cam = r._kameras[idx]
            eigen = next((a for a in autos if a.kennung == szenen_kennung(hp)), None)
            film.aktualisieren(dt, cam.auge, cam.ziel, eigen, autos)
            film.ziel_name = next((a.name for a in autos
                                   if a.kennung == film.regie.ziel_kennung), "")

    # -- Haken: Uhr und Ergebnisse ----------------------------------------------
    def zurueckhalten(self, zeilen) -> bool:
        """``True``: das Ausblenden wird verschoben, bis die Uhr durch ist.

        Wird von ``_starte_ausblenden`` gefragt, also erst, wenn das Feld
        fertig ist (offline: Rennmanager ``finished``; online: die Wertung vom
        Server ist da). Ab hier laufen :data:`tv_regie.NACHLAUF_S` Sekunden.
        """
        if not self.filme or self.freigegeben or self.nachspiel.uebersprungen:
            return False
        self.zeilen = zeilen
        self.wartet = True
        self.nachspiel.feld_fertig()
        return True

    def tick(self, dt: float) -> None:
        if not self.wartet:
            return
        self.nachspiel.tick(dt)
        if self.nachspiel.bereit:
            self.wartet = False
            self.freigegeben = True
            self.r._starte_ausblenden(self.zeilen)

    def ueberspringen_erlaubt(self) -> bool:
        """Enter/A gilt erst, wenn das Feld fertig ist (alle im Ziel oder nach
        der bisherigen DNF-Frist DNF) — also waehrend der 30 s Nachlauf. Vorher
        tut es nichts: niemand wird vorzeitig gewertet."""
        return self.wartet and self.alle_menschen_im_film() and not self.skip_gewuenscht

    def ueberspringen(self) -> None:
        """Enter/A: die Restzeit des Nachlaufs ueberspringen, sofort zu den Ergebnissen."""
        if not self.ueberspringen_erlaubt():
            return
        self.skip_gewuenscht = True
        self.nachspiel.ueberspringen()
        self.tick(0.0)

    def taste(self, ereignis) -> bool:
        """Enter / A im Film. Gibt ``True`` zurueck, wenn die Taste verbraucht ist."""
        if not self.ueberspringen_erlaubt():
            return False
        from src.core import gamepad
        if ereignis.type == pygame.KEYDOWN and ereignis.key in (
                pygame.K_RETURN, pygame.K_KP_ENTER):
            pass
        elif ereignis.type == pygame.JOYBUTTONDOWN and ereignis.button == gamepad.BTN_A:
            pass
        else:
            return False
        self.ueberspringen()
        return True

    # -- Haken: Zeichnen -------------------------------------------------------
    def ansichten(self, haelften: list, kameras: list) -> tuple[list, list]:
        """Bildhaelften und Kameras fuer ``_welt_zeichnen``.

        Wer im Film ist, bekommt die Filmkamera; sind im Splitscreen beide im
        Film, gibt es ein einziges Bild ueber das ganze Fenster.
        """
        if not self.filme:
            return haelften, kameras
        r = self.r
        if r._split and len(kameras) > 1 and self.alle_menschen_im_film():
            erster = self.filme[self.reihenfolge[0]]
            return [haelften_gesamt(haelften)], [erster.kamera]
        neu = list(kameras)
        for idx, film in self.filme.items():
            if idx < len(neu):
                neu[idx] = film.kamera
        return haelften, neu

    @staticmethod
    def _zeile(flaeche: pygame.Surface, text: str, groesse: int, farbe, mitte: tuple,
               scale: float) -> None:
        """Eine Zeile mittig auf einem dunklen Streifen, damit sie ueber jedem Bild lesbar ist."""
        from src.ui import theme, leinwand
        groesse = max(12, int(groesse * scale))
        b, h = theme.font(groesse).size(text)
        pad = int(18 * scale)
        hg = leinwand.flaeche((b + 2 * pad, h + int(12 * scale)), pygame.SRCALPHA)
        hg.fill((10, 10, 15, 150))
        flaeche.blit(hg, (mitte[0] - (b + 2 * pad) // 2, mitte[1] - (h + int(12 * scale)) // 2))
        theme.text(flaeche, text, groesse, farbe, mitte, center=True)

    def _banner(self, flaeche: pygame.Surface, film, scale: float) -> None:
        from src.ui import theme
        w, h = flaeche.get_size()
        mitte = w // 2
        platz = f"{film.platz}" if film.platz > 0 else "-"
        self._zeile(flaeche, tr("ZIEL - Position {pos}").format(pos=platz),
                    theme.HEADER, theme.ACCENT, (mitte, int(62 * scale)), scale)
        if film.ziel_name and film.phase == "regie":
            self._zeile(flaeche, film.ziel_name, theme.LABEL, theme.TEXT,
                        (mitte, int(116 * scale)), scale)

        # Hinweis unten: nur, solange Enter/A etwas tut (Nachlauf).
        if self.wartet and self.nachspiel.rest is not None:
            from src.core import gamepad
            taste = tr("A: Ergebnisse") if gamepad.using_pad() else tr("ENTER: Ergebnisse")
            taste += "   -   " + tr("Ergebnisse in {n} s").format(
                n=int(math.ceil(self.nachspiel.rest)))
            self._zeile(flaeche, taste, theme.HINT, theme.TEXT, (mitte, h - int(44 * scale)), scale)

    def hud_zeichnen(self, screen: pygame.Surface, index: int, scale: float = 1.0) -> bool:
        """Das Banner statt des Renn-HUDs. ``True``, wenn gezeichnet wurde.

        ``index`` ist der Mensch (Splitscreen: die Bildhaelfte); ``screen`` die
        Flaeche dieser Haelfte.
        """
        film = self.filme.get(index)
        if film is None:
            return False
        self._banner(screen, film, scale)
        return True

    def geteilt_gesamt(self) -> bool:
        """Splitscreen mit beiden im Film: ein Bild, ein Banner."""
        return bool(self.r._split) and len(getattr(self.r, "_kameras", [])) > 1 \
            and self.alle_menschen_im_film()

    def gesamt_banner(self, screen: pygame.Surface) -> None:
        film = self.filme[self.reihenfolge[0]]
        self._banner(screen, film, 1.0)


def haelften_gesamt(haelften: list):
    """Das ganze Fenster aus den beiden Haelften (links + rechts)."""
    x = min(h[0] for h in haelften)
    y = min(h[1] for h in haelften)
    b = max(h[0] + h[2] for h in haelften) - x
    hoehe = max(h[3] for h in haelften)
    return (x, y, b, hoehe)
