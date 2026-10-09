"""Online-Strecken: durchsuchen, herunterladen, hochladen, melden (Plan 1.1.0 §5).

Eine Seite mit zwei Arten:

``liste``    die Strecken auf dem gewaehlten Server — sortiert nach Neueste oder
             Beliebteste, mit Suche, Seiten, Vorschau, Download und Melden
``eigene``   die eigenen veroeffentlichten Strecken — eine waehlen, bestaetigen,
             hochladen

**Strecken gehoeren zu einem Server.** Helsinki und Hamburg sind getrennte
Relays mit getrennten Speichern; was auf dem einen liegt, sieht der andere nicht.
Die Seite sagt das ausdruecklich, und der Server laesst sich hier umschalten.

Alle Netzanfragen laufen in einem Arbeitsfaden (``strecken_client`` blockiert);
die Seite fragt in ``update`` nach Ergebnissen. Tests setzen ``synchron=True``
und eine eigene ``api``, dann laeuft alles im selben Faden ohne Netz.

Bedienung ueber ``FocusGroup`` wie die Menues: Pfeile bzw. D-Pad bewegen den
Fokus, ENTER/A loest aus, ESC/B geht zurueck, Bild hoch/runter (LB/RB) blaettert.
Die Suche nimmt am Controller die Bildschirmtastatur.
"""
from __future__ import annotations

import queue
import threading
import time
from typing import TYPE_CHECKING

import pygame

from src.core import gamepad, input_mode, profile
from src.core.i18n import tr
from src.core.settings import SCREEN_HEIGHT, SCREEN_WIDTH
from src.net import servers, strecken_client
from src.net.strecken_client import StreckenFehler
from src.states.base_state import BaseState
from src.track import strecken_online as lokal
from src.ui import hints, theme, zeichnen
from src.ui.focus import FocusGroup
from src.ui.widgets import Button, Dialog, OnScreenKeyboard, TextInput, ZurueckKnopf, _Base

if TYPE_CHECKING:
    from src.core.state_machine import StateMachine

#: Zeilen je Seite — die Liste und die eigenen Strecken teilen sich das Raster.
ZEILEN = 8
_ZEILE_H = 72
_ZEILE_ABSTAND = 78

_SCHWIERIGKEIT_FARBE = {"Einfach": (50, 220, 80), "Mittel": (255, 160, 0), "Schwer": (240, 50, 50)}

#: Der zuletzt gewaehlte Server bleibt fuer den Rest der Sitzung.
_letzter_server: str = ""


def _km(laenge_px) -> str:
    """Laenge wie in der Streckenauswahl: 1000 px = 1 km."""
    try:
        return f"{float(laenge_px) / 1000.0:.1f} km"
    except (TypeError, ValueError):
        return "? km"


def _datum(ts) -> str:
    try:
        return time.strftime("%d.%m.%Y", time.localtime(int(ts)))
    except (TypeError, ValueError, OverflowError, OSError):
        return "?"


class StreckenZeile(_Base):
    """Eine Zeile der Liste: Vorschaubild, Name, Autor, Eckdaten."""

    def __init__(self, rect: pygame.Rect, index: int) -> None:
        super().__init__(rect)
        self.index = index
        self.eintrag: dict | None = None
        self.gewaehlt = False
        self.geladen = False
        self.focusable = False

    def setzen(self, eintrag: dict | None, *, geladen: bool = False) -> None:
        self.eintrag = eintrag
        self.geladen = geladen
        self.focusable = eintrag is not None

    def activate(self) -> str | None:
        return f"zeile_{self.index}" if self.eintrag is not None else None

    def draw(self, screen, focused: bool = False) -> None:
        e = self.eintrag
        if e is None:
            return
        hover = self._hover()
        hell = focused or hover
        r = self.rect
        fill = theme.PANEL_SEL if self.gewaehlt else ((38, 42, 54) if hell else (26, 29, 38))
        zeichnen.rect(screen, fill, r, border_radius=8)
        zeichnen.rect(screen, theme.ACCENT if (self.gewaehlt or focused) else theme.BORDER,
                      r, 3 if focused else 2, border_radius=8)
        vorschau_zeichnen(screen, pygame.Rect(r.x + 8, r.y + 8, r.height - 16, r.height - 16),
                          e.get("outline"), theme.ACCENT if self.gewaehlt else (0, 220, 235))
        links = r.x + r.height + 8
        rechts = r.right - 16
        theme.text_fit(screen, str(e.get("name", "?")), theme.BODY, theme.TEXT,
                       pygame.Rect(links, r.y + 4, rechts - links - 190, 36))
        autor = str(e.get("author", "?"))
        schwer = str(e.get("difficulty", ""))
        info = f"{tr('von')} {autor}   {_km(e.get('length'))}"
        theme.text_fit(screen, info, theme.HINT, theme.TEXT_DIM,
                       pygame.Rect(links, r.y + 38, rechts - links - 190, 28))
        theme.text(screen, tr(schwer).upper() if schwer else "", theme.SMALL,
                   _SCHWIERIGKEIT_FARBE.get(schwer, theme.TEXT_DIM),
                   (rechts, r.y + 12), topright=True)
        if self.geladen:
            theme.text(screen, f"{theme.HAKEN} " + tr("geladen"), theme.SMALL, theme.SUCCESS,
                       (rechts, r.y + 42), topright=True)
        elif "downloads" in e:
            theme.text(screen, tr("{n} Abrufe").format(n=int(e.get("downloads", 0))),
                       theme.SMALL, theme.TEXT_FAINT, (rechts, r.y + 42), topright=True)


def vorschau_zeichnen(screen, rect: pygame.Rect, umriss, farbe) -> None:
    """Die Strecke als Umriss von oben, in *rect*; ganz aus den Punkten gebaut.

    Ueber das Netz gehen keine Bilder, nur die Punkte (0..255). Fehlen sie, bleibt
    ein leerer Rahmen.
    """
    zeichnen.rect(screen, (14, 16, 22), rect, border_radius=6)
    zeichnen.rect(screen, theme.BORDER, rect, 1, border_radius=6)
    punkte = lokal.umriss_in_rechteck(umriss, rect, rand=max(5, rect.width // 12))
    if len(punkte) >= 3:
        breite = max(2, rect.width // 45)
        zeichnen.lines(screen, farbe, True, punkte, breite)
        zeichnen.circle(screen, (255, 255, 255), punkte[0], max(3, breite + 1))


class OnlineStreckenState(BaseState):
    """Der Bildschirm „Online-Strecken"."""

    def __init__(self, state_machine: "StateMachine") -> None:
        super().__init__(state_machine)
        self.api = strecken_client
        self.synchron = False
        self.modus = "liste"
        self.eintraege: list[dict] = []
        self.eigene: list = []
        self.seite = 0
        self.seiten = 1
        self.gesamt = 0
        self.sortierung = "new"
        self.auswahl = -1
        self.status = ""
        self.status_ok = True
        self.beschaeftigt = ""
        self.dialog: Dialog | None = None
        self.dialog_art = ""
        self._dialog_ziel: dict | None = None
        self.osk: OnScreenKeyboard | None = None
        self.server: servers.ServerDef | None = None
        self.geladen_ids: set[str] = set()
        self._gen = 0
        self._ergebnisse: "queue.Queue" = queue.Queue()
        self._zeit = 0.0
        self.gruppe = FocusGroup([])
        self.zeilen: list[StreckenZeile] = []
        self.laedt_liste = False

    # ------------------------------------------------------------------
    # Aufbau
    # ------------------------------------------------------------------
    def enter(self, **kwargs) -> None:
        global _letzter_server
        self.api = kwargs.get("api", self.api)
        self.synchron = kwargs.get("synchron", self.synchron)
        alle = servers.all_servers()
        self.server = (servers.by_id(_letzter_server) if _letzter_server else None) \
            or (alle[0] if alle else None)
        self.modus = "liste"
        self.seite, self.seiten, self.gesamt = 0, 1, 0
        self.eintraege, self.auswahl = [], -1
        self.status, self.beschaeftigt = "", ""
        self.dialog, self.osk = None, None
        self.geladen_ids = lokal.geladene_kennungen()
        self._bauen()
        self.liste_laden()

    def _bauen(self) -> None:
        self.zurueck = ZurueckKnopf(80, 72)
        y = 170
        self.b_server = Button(pygame.Rect(80, y, 420, 56), "", "server", style="secondary")
        self.b_sort = Button(pygame.Rect(520, y, 380, 56), "", "sort", style="secondary")
        self.suchfeld = TextInput(pygame.Rect(920, y, 380, 56), "", max_len=30)
        self.b_suchen = Button(pygame.Rect(1320, y, 170, 56), tr("Suchen"), "suchen")
        self.b_modus = Button(pygame.Rect(1510, y, 330, 56), "", "modus")
        self.zeilen = [StreckenZeile(pygame.Rect(80, 290 + i * _ZEILE_ABSTAND, 900, _ZEILE_H), i)
                       for i in range(ZEILEN)]
        self.b_zurueck_seite = Button(pygame.Rect(80, 920, 200, 52), "‹ " + tr("Vorherige"),
                                      "prev", style="secondary")
        self.b_vor_seite = Button(pygame.Rect(780, 920, 200, 52), tr("Nächste") + " ›",
                                  "next", style="secondary")
        self.b_aktion = Button(pygame.Rect(1050, 800, 380, 64), "", "aktion")
        self.b_melden = Button(pygame.Rect(1450, 800, 360, 64), tr("Melden"), "melden",
                               style="secondary")
        self._knoepfe_aktualisieren()

    def _widgets(self) -> list:
        w = [self.zurueck, self.b_server, self.b_sort, self.suchfeld, self.b_suchen,
             self.b_modus]
        w += self.zeilen
        w += [self.b_zurueck_seite, self.b_vor_seite, self.b_aktion, self.b_melden]
        return w

    def _aktueller_eintrag(self) -> dict | None:
        if 0 <= self.auswahl < len(self.eintraege):
            return self.eintraege[self.auswahl]
        return None

    def _knoepfe_aktualisieren(self) -> None:
        """Beschriftungen und Sperren aus dem Zustand ableiten."""
        liste = self.modus == "liste"
        name = self.server.label if self.server else "?"
        self.b_server.label = tr("Server: {name}").format(name=name)
        self.b_sort.label = (tr("Sortierung: Neueste") if self.sortierung == "new"
                             else tr("Sortierung: Beliebteste"))
        self.b_modus.label = tr("Zur Liste") if not liste else tr("Eigene hochladen")
        for b in (self.b_sort, self.b_suchen):
            b.enabled = b.focusable = liste
        self.suchfeld.focusable = liste
        e = self._aktueller_eintrag()
        frei = not self.beschaeftigt
        if liste:
            geladen = bool(e and e.get("id") in self.geladen_ids)
            self.b_aktion.label = tr("Schon geladen") if geladen else tr("Herunterladen")
            ok = bool(e) and not geladen and frei
            self.b_melden.enabled = self.b_melden.focusable = bool(e) and frei
        else:
            self.b_aktion.label = tr("Hochladen")
            ok = bool(e) and frei
            self.b_melden.enabled = self.b_melden.focusable = False
        self.b_aktion.enabled = self.b_aktion.focusable = ok
        self.b_zurueck_seite.enabled = self.b_zurueck_seite.focusable = self.seite > 0
        self.b_vor_seite.enabled = self.b_vor_seite.focusable = self.seite < self.seiten - 1
        for z in self.zeilen:
            z.gewaehlt = (z.index == self.auswahl)
        vorher = self.gruppe.focused
        self.gruppe.set_widgets(self._widgets(), keep_focus=True)
        if vorher is None:
            self.gruppe.index = self.gruppe.widgets.index(self.b_server)
        self.gruppe.fokus_richten()

    # ------------------------------------------------------------------
    # Arbeitsfaeden
    # ------------------------------------------------------------------
    def _starte(self, beschriftung: str, arbeit, danach, *, sperrt: bool = True) -> None:
        """*arbeit* im Hintergrund laufen lassen; *danach(ergebnis, fehler)* im Bildlauf.

        Liste und Aktionen teilen sich die Seite: wer eine Aktion laufen hat,
        kann keine zweite starten (``beschaeftigt``). Eine neue Listenanfrage
        macht eine alte, noch laufende hinfaellig (``_gen``).
        """
        if sperrt:
            self.beschaeftigt = beschriftung
        gen = self._gen

        def lauf() -> None:
            try:
                erg, fehler = arbeit(), None
            except StreckenFehler as f:
                erg, fehler = None, f
            except Exception as exc:                      # nie den Faden still sterben lassen
                erg, fehler = None, StreckenFehler("ERROR", str(exc))
            self._ergebnisse.put((danach, erg, fehler, gen, sperrt))

        if self.synchron:
            lauf()
            self.update(0.0)
        else:
            threading.Thread(target=lauf, daemon=True, name="strecken-netz").start()
        self._knoepfe_aktualisieren()

    def update(self, dt: float) -> None:
        self._zeit += dt
        if self.suchfeld:
            self.suchfeld.update(dt)
        if self.osk:
            self.osk.update(dt)
        while True:
            try:
                danach, erg, fehler, gen, sperrt = self._ergebnisse.get_nowait()
            except queue.Empty:
                break
            if sperrt:
                self.beschaeftigt = ""
            if danach is not None:
                danach(erg, fehler, gen)
        # Auswahl folgt dem Fokus: wer mit den Pfeilen durch die Liste geht, sieht
        # die Einzelheiten der Zeile, auf der er steht.
        f = self.gruppe.focused
        if isinstance(f, StreckenZeile) and f.eintrag is not None and f.index != self.auswahl:
            self.auswahl = f.index
            self._knoepfe_aktualisieren()

    def _meldung(self, text: str, ok: bool = True) -> None:
        self.status, self.status_ok = text, ok

    def _fehler(self, f: StreckenFehler) -> None:
        self._meldung(f.text, False)

    # ------------------------------------------------------------------
    # Liste
    # ------------------------------------------------------------------
    def liste_laden(self, seite: int | None = None) -> None:
        if self.modus != "liste" or self.server is None:
            return
        if seite is not None:
            self.seite = max(0, seite)
        self._gen += 1
        sd, sortierung, suche, nr = self.server, self.sortierung, self.suchfeld.text.strip(), self.seite
        self._meldung("")
        self.laedt_liste = True
        self._starte(tr("Lade Liste …"),
                     lambda: self.api.liste(sd, sortierung, suche, nr, ZEILEN),
                     self._liste_da, sperrt=False)

    def _liste_da(self, antwort, fehler, gen) -> None:
        if gen != self._gen or self.modus != "liste":
            return                                       # inzwischen veraltet
        self.laedt_liste = False
        if fehler is not None:
            self.eintraege, self.auswahl = [], -1
            self.seiten, self.gesamt = 1, 0
            self._fehler(fehler)
        else:
            roh = [e for e in antwort.get("tracks", []) if lokal.eintrag_ok(e)]
            self.eintraege = [e for e in roh if lokal.anzeigbar(e)][:ZEILEN]
            self.seite = int(antwort.get("page", 0) or 0)
            self.seiten = max(1, int(antwort.get("pages", 1) or 1))
            self.gesamt = int(antwort.get("total", len(self.eintraege)) or 0)
            self.auswahl = 0 if self.eintraege else -1
        self._zeilen_fuellen()

    def _zeilen_fuellen(self) -> None:
        for i, z in enumerate(self.zeilen):
            e = self.eintraege[i] if i < len(self.eintraege) else None
            z.setzen(e, geladen=bool(e and e.get("id") in self.geladen_ids))
        self._knoepfe_aktualisieren()

    # ------------------------------------------------------------------
    # Aktionen
    # ------------------------------------------------------------------
    def _aktion(self, aktion: str | None) -> None:
        if not aktion:
            return
        if aktion == "zurueck":
            self._zurueck()
        elif aktion == "server":
            self._server_wechseln()
        elif aktion == "sort":
            self.sortierung = "downloads" if self.sortierung == "new" else "new"
            self.liste_laden(0)
        elif aktion == "suchen":
            self.liste_laden(0)
        elif aktion == "modus":
            self._modus_wechseln()
        elif aktion == "prev":
            self._blaettern(-1)
        elif aktion == "next":
            self._blaettern(+1)
        elif aktion.startswith("zeile_"):
            self.auswahl = int(aktion[6:])
            self._knoepfe_aktualisieren()
        elif aktion == "aktion":
            self._laden_oder_hochladen()
        elif aktion == "melden":
            self._melden_fragen()

    def _zurueck(self) -> None:
        if self.modus == "eigene":
            self._modus_wechseln()
            return
        self.state_machine.zurueck(fallback="menu")

    def _server_wechseln(self) -> None:
        global _letzter_server
        alle = servers.all_servers()
        if len(alle) < 2 or self.server is None:
            return
        i = next((n for n, s in enumerate(alle) if s.id == self.server.id), -1)
        self.server = alle[(i + 1) % len(alle)]
        _letzter_server = self.server.id
        self.geladen_ids = lokal.geladene_kennungen()
        self.seite = 0
        self.eintraege, self.auswahl = [], -1
        self._zeilen_fuellen()
        if self.modus == "liste":
            self.liste_laden(0)
        else:
            self._knoepfe_aktualisieren()

    def _blaettern(self, d: int) -> None:
        neu = self.seite + d
        if not 0 <= neu < self.seiten:
            return
        if self.modus == "liste":
            self.liste_laden(neu)
        else:
            self.seite = neu
            self._eigene_zeigen()

    def _modus_wechseln(self) -> None:
        if self.modus == "liste":
            self.modus = "eigene"
            self._gen += 1                               # eine laufende Liste verfaellt
            self.eigene = lokal.eigene_strecken()
            self.seite = 0
            self._eigene_zeigen()
            self._meldung("" if self.eigene else
                          tr("Du hast noch keine eigene Strecke veröffentlicht. Baue eine im Streckeneditor."),
                          bool(self.eigene))
        else:
            self.modus = "liste"
            self.seite, self.seiten = 0, 1
            self.eintraege, self.auswahl = [], -1
            self._zeilen_fuellen()
            self.liste_laden(0)

    def _eigene_zeigen(self) -> None:
        autor = (profile.current().username or tr("Spieler"))
        self.seiten = max(1, -(-len(self.eigene) // ZEILEN))
        self.seite = min(self.seite, self.seiten - 1)
        teil = self.eigene[self.seite * ZEILEN:(self.seite + 1) * ZEILEN]
        self.eintraege = [{"id": f"eigen{self.seite * ZEILEN + i}", "name": s.name, "author": autor,
                           "difficulty": s.schwierigkeit, "theme": s.thema, "length": s.laenge_px,
                           "outline": s.umriss, "_eigen": s}
                          for i, s in enumerate(teil)]
        self.gesamt = len(self.eigene)
        self.auswahl = 0 if self.eintraege else -1
        self._zeilen_fuellen()

    def _laden_oder_hochladen(self) -> None:
        e = self._aktueller_eintrag()
        if not e or self.beschaeftigt or self.server is None:
            return
        if self.modus == "liste":
            self._herunterladen(e)
        else:
            self._hochladen_fragen(e)

    # -- Herunterladen --------------------------------------------------
    def _herunterladen(self, e: dict) -> None:
        if e.get("id") in self.geladen_ids:
            return
        sd, tid = self.server, e["id"]
        self._meldung("")
        self._starte(tr("Lade Strecke …"), lambda: self.api.holen(sd, tid),
                     lambda erg, f, gen: self._heruntergeladen(erg, f, sd))

    def _heruntergeladen(self, daten, fehler, sd) -> None:
        if fehler is not None:
            self._fehler(fehler)
            self._knoepfe_aktualisieren()
            return
        try:
            pfad, neu = lokal.speichern(daten, sd.id)
        except lokal.EntwurfFehler as exc:
            self._meldung(str(exc), False)
            self._knoepfe_aktualisieren()
            return
        except OSError as exc:
            self._meldung(tr("Strecke konnte nicht gespeichert werden: {e}").format(e=exc), False)
            self._knoepfe_aktualisieren()
            return
        self.geladen_ids.add(str(daten.get("id", "")))
        self._meldung(tr("„{name}“ gespeichert. Du findest sie in der Streckenauswahl unter „Eigene“.")
                      .format(name=daten.get("name", "?")), True)
        self._zeilen_fuellen()

    # -- Hochladen ------------------------------------------------------
    def _hochladen_fragen(self, e: dict) -> None:
        s = e.get("_eigen")
        if s is None:
            return
        ok, grund = lokal.hochladbar(s)
        if not ok:
            self._meldung(grund, False)
            return
        autor = profile.current().username or tr("Spieler")
        self.dialog_art = "hochladen"
        self.dialog = Dialog(
            tr("Strecke hochladen?"),
            tr("„{name}“ wird auf {server} hochgeladen und ist dort für alle Spieler sichtbar. "
               "Als Autor erscheint dein Spielername ({autor}). Strecken, die gemeldet werden, "
               "verschwinden wieder.").format(name=s.name, server=self.server.label, autor=autor),
            [(tr("Hochladen"), "ja"), (tr("Abbrechen"), "nein")])
        self._dialog_ziel = e

    def _hochladen(self, e: dict) -> None:
        s, sd = e["_eigen"], self.server
        autor = profile.current().username or tr("Spieler")
        self._meldung("")
        self._starte(tr("Lade hoch …"),
                     lambda: self.api.hochladen(sd, s.entwurf, s.name, autor),
                     lambda erg, f, gen: self._hochgeladen(erg, f, s, sd))

    def _hochgeladen(self, antwort, fehler, s, sd) -> None:
        if fehler is not None:
            self._fehler(fehler)
        else:
            self._meldung(tr("„{name}“ ist jetzt auf {server} online.")
                          .format(name=s.name, server=sd.label), True)
        self._knoepfe_aktualisieren()

    # -- Melden ---------------------------------------------------------
    def _melden_fragen(self) -> None:
        e = self._aktueller_eintrag()
        if not e or self.modus != "liste" or self.beschaeftigt:
            return
        self.dialog_art = "melden"
        self.dialog = Dialog(
            tr("Strecke melden?"),
            tr("„{name}“ von {autor} melden? Strecken mit mehreren Meldungen werden ausgeblendet.")
            .format(name=e.get("name", "?"), autor=e.get("author", "?")),
            [(tr("Melden"), "ja"), (tr("Abbrechen"), "nein")])
        self._dialog_ziel = e

    def _melden(self, e: dict) -> None:
        sd, tid = self.server, e["id"]
        self._meldung("")
        self._starte(tr("Melde …"), lambda: self.api.melden(sd, tid),
                     lambda erg, f, gen: self._gemeldet(erg, f, tid))

    def _gemeldet(self, versteckt, fehler, tid) -> None:
        if fehler is not None:
            self._fehler(fehler)
        else:
            self._meldung(tr("Danke, die Strecke wurde gemeldet."), True)
            if versteckt:
                self.eintraege = [x for x in self.eintraege if x.get("id") != tid]
                self.auswahl = 0 if self.eintraege else -1
                self._zeilen_fuellen()
        self._knoepfe_aktualisieren()

    # ------------------------------------------------------------------
    # Eingabe
    # ------------------------------------------------------------------
    def handle_events(self, events: list[pygame.event.Event]) -> None:
        for event in events:
            if self.dialog is not None:
                res = self.dialog.handle_event(event)
                if res is not None:
                    art, ziel = self.dialog_art, self._dialog_ziel
                    self.dialog = None
                    if res == "ja" and ziel is not None:
                        (self._hochladen if art == "hochladen" else self._melden)(ziel)
                continue
            if self.osk is not None:
                if self.osk.handle_event(event):
                    self.osk = None
                    self.liste_laden(0)
                continue
            self._ereignis(event)

    def _ereignis(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._zurueck()
                return
            if event.key == pygame.K_PAGEUP:
                self._blaettern(-1)
                return
            if event.key == pygame.K_PAGEDOWN:
                self._blaettern(+1)
                return
            if event.key == pygame.K_RETURN and self.gruppe.focused is self.suchfeld:
                if gamepad.using_pad():
                    self.osk = OnScreenKeyboard(self.suchfeld)
                else:
                    self.liste_laden(0)
                return
            if event.key == pygame.K_y and getattr(event, "synthetic", False):
                self._modus_wechseln()                   # Y am Controller
                return
        if event.type == pygame.MOUSEWHEEL:
            self._blaettern(-1 if event.y > 0 else +1)
            return
        self._aktion(self.gruppe.handle_event(event))

    # ------------------------------------------------------------------
    # Zeichnen
    # ------------------------------------------------------------------
    def render(self, screen: pygame.Surface) -> None:
        theme.draw_background(screen)
        theme.text(screen, tr("ONLINE-STRECKEN"), theme.TITLE, theme.ACCENT,
                   (SCREEN_WIDTH // 2, 36), midtop=True)

        name = self.server.label if self.server else "?"
        theme.text_fit(
            screen,
            tr("Strecken gehören zu einem Server: Auf {server} siehst du nur, was dort hochgeladen wurde.")
            .format(server=name),
            theme.HINT, theme.TEXT_DIM, pygame.Rect(80, 238, 1760, 32))

        theme.panel(screen, pygame.Rect(70, 280, 920, 640))
        theme.panel(screen, pygame.Rect(1030, 280, 820, 640))

        for z in self.zeilen:
            z.draw(screen, focused=(self.gruppe.focused is z))
        if not self.eintraege:
            self._leer_zeichnen(screen)

        # Alles andere ueber die Gruppe — die Zeilen oben haben ihren Fokus selbst bekommen.
        versteckt = ({self.suchfeld, self.b_sort, self.b_suchen, self.b_melden}
                     if self.modus == "eigene" else set())
        for w in self.gruppe.widgets:
            if isinstance(w, StreckenZeile) or w in versteckt:
                continue
            w.draw(screen, focused=(self.gruppe.focused is w))
        if (self.modus == "liste" and not self.suchfeld.text
                and self.gruppe.focused is not self.suchfeld):
            theme.text(screen, tr("Name oder Autor …"), theme.BODY, theme.TEXT_FAINT,
                       (self.suchfeld.rect.x + 14, self.suchfeld.rect.centery), midleft=True)
        theme.text(screen, tr("Seite {a} von {b}  ({n} Strecken)")
                   .format(a=self.seite + 1, b=self.seiten, n=self.gesamt),
                   theme.HINT, theme.TEXT_DIM, (530, 946), center=True)

        self._details_zeichnen(screen)

        zeile = self.beschaeftigt or self.status
        if zeile:
            farbe = theme.TEXT_DIM if self.beschaeftigt else (theme.SUCCESS if self.status_ok else theme.DANGER)
            theme.text_fit(screen, zeile, theme.LABEL, farbe,
                           pygame.Rect(80, 984, 1760, 36), center=True)
        blaettern = "LB/RB" if input_mode.is_pad() else tr("Bild hoch/runter")
        theme.text(screen, hints.bar(("confirm", tr("Auswählen")), ("nav", tr("Bewegen")),
                                     ("back", tr("Zurück")))
                   + f"     {blaettern} {tr('Blättern')}",
                   theme.HINT, theme.TEXT_FAINT, (SCREEN_WIDTH // 2, 1050), center=True)
        theme.draw_input_badge(screen, (SCREEN_WIDTH - 20, 20))
        if self.osk is not None:
            self.osk.draw(screen)
        if self.dialog is not None:
            self.dialog.draw(screen)

    def _leer_zeichnen(self, screen) -> None:
        if self.beschaeftigt or self.laedt_liste:
            text = tr("Lade …")
        elif self.modus == "eigene":
            text = tr("Keine eigenen Strecken zum Hochladen.")
        elif self.status and not self.status_ok:
            text = ""                                    # der Fehler steht unten
        else:
            text = tr("Keine Strecken gefunden.")
        if text:
            theme.text(screen, text, theme.BODY, theme.TEXT_DIM, (530, 560), center=True)

    def _details_zeichnen(self, screen) -> None:
        e = self._aktueller_eintrag()
        if e is None:
            return
        x = 1060
        vorschau_zeichnen(screen, pygame.Rect(x, 310, 360, 300), e.get("outline"), theme.ACCENT)
        theme.text_fit(screen, str(e.get("name", "?")), theme.HEADER, theme.ACCENT,
                       pygame.Rect(1440, 312, 390, 56))
        theme.text_fit(screen, f"{tr('von')} {e.get('author', '?')}", theme.LABEL, theme.TEXT,
                       pygame.Rect(1440, 372, 390, 36))
        schwer = str(e.get("difficulty", ""))
        zeilen = [
            (tr("Thema"), str(e.get("theme", "?")), theme.TEXT),
            (tr("Schwierigkeit"), tr(schwer) if schwer else "?",
             _SCHWIERIGKEIT_FARBE.get(schwer, theme.TEXT)),
            (tr("Länge"), _km(e.get("length")), theme.TEXT),
        ]
        if self.modus == "liste":
            zeilen += [(tr("Bauteile"), str(e.get("pieces", "?")), theme.TEXT),
                       (tr("Abrufe"), str(int(e.get("downloads", 0))), theme.TEXT),
                       (tr("Hochgeladen"), _datum(e.get("created")), theme.TEXT)]
        y = 424
        for k, v, f in zeilen:
            theme.text(screen, k, theme.HINT, theme.TEXT_DIM, (1440, y))
            theme.text(screen, v, theme.HINT, f, (1830, y), topright=True)
            y += 30
        if self.modus == "eigene":
            for i, t in enumerate(_umbrechen(
                    tr("Beim Hochladen sehen alle Spieler dieses Servers Name und Autor der Strecke. "
                       "Der Server prüft sie, bevor er sie annimmt."), theme.HINT, 760)):
                theme.text(screen, t, theme.HINT, theme.TEXT_DIM, (x, 640 + i * 28))
        if self.modus == "liste":
            if e.get("id") in self.geladen_ids:
                theme.text(screen, f"{theme.HAKEN} " + tr("Liegt schon bei dir unter „Eigene“."),
                           theme.HINT, theme.SUCCESS, (x, 650))


def _umbrechen(text: str, groesse: int, breite: int) -> list[str]:
    """Wörter auf Zeilen verteilen, die in *breite* Pixeln passen."""
    f = theme.font(groesse)
    zeilen, akt = [], ""
    for w in text.split():
        probe = f"{akt} {w}".strip()
        if f.size(probe)[0] > breite and akt:
            zeilen.append(akt)
            akt = w
        else:
            akt = probe
    if akt:
        zeilen.append(akt)
    return zeilen
