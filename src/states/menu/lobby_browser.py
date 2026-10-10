"""Lobbyliste: die erste Ansicht nach „Online" (Plan 1.1.0).

Zeigt die offenen Lobbys **aller** Server in einer Liste (Helsinki und Hamburg
gemischt, jeder Server wird parallel abgefragt, siehe ``src/net/lobby_liste.py``).

Spalten: Status (offen / im Rennen / voll), Name der Lobby mit Schloss bei
Passwort, Host, Spieler x/y, Ping (Balken und ms). Lobbys im Rennen und volle
stehen ausgegraut in der Liste und sind nicht waehlbar; beitretbare stehen oben,
darunter nach Ping sortiert. Filter: „nur beitretbare" und Server. Alle fuenf
Sekunden wird neu gefragt.

Oben: „Lobby erstellen", „Mit Code beitreten", „Online-Strecken".

Diese Klasse ist nur die Ansicht. Was nach einer Wahl passiert (verbinden, nach
dem Passwort fragen, Seite wechseln), entscheidet ``OnlineLobbyPage``: die
Ansicht meldet es als Aktion zurueck:

``create``     Lobby erstellen
``code``       mit Code beitreten
``strecken``   Online-Strecken oeffnen
``beitreten``  eine Zeile wurde gewaehlt, der Eintrag steht in ``gewaehlt``
"""
from __future__ import annotations

import pygame

from src.core.i18n import tr
from src.net import lobby_liste, server_probe
from src.net.lobby_liste import LobbyEintrag, LobbyListe
from src.ui import theme, zeichnen
from src.ui.focus import FocusGroup
from src.ui.widgets import Button, Stepper, _Base, signal_bars

#: Zeilen, die gleichzeitig zu sehen sind; der Rest wird gescrollt.
ZEILEN = 8
_LIST_X, _LIST_W = 80, 1760
_ZEILE_H, _ZEILE_ABSTAND = 62, 70
_LIST_Y = 372
_TASTEN_Y, _FILTER_Y = 176, 250

#: Spaltenversaetze vom linken Rand der Zeile.
COL_STATUS = 24
COL_SCHLOSS = 196
COL_NAME = 236
COL_HOST = 960
COL_SPIELER_R = 1440       # RECHTE Kante
COL_BALKEN = 1510
COL_PING_R = 1716          # RECHTE Kante


def schloss_zeichnen(screen, rect: pygame.Rect, farbe) -> None:
    """Ein kleines Vorhaengeschloss aus Grundformen — ohne Schriftzeichen, damit
    es in jeder Schrift gleich aussieht."""
    koerper = pygame.Rect(rect.x, rect.y + rect.height * 0.42, rect.width,
                          rect.height * 0.58)
    bogen = pygame.Rect(rect.x + rect.width * 0.2, rect.y,
                        rect.width * 0.6, rect.height * 0.9)
    zeichnen.rect(screen, farbe, bogen, max(2, rect.width // 7),
                  border_radius=max(3, rect.width // 3))
    zeichnen.rect(screen, farbe, koerper, border_radius=3)
    zeichnen.circle(screen, (20, 22, 30), koerper.center, max(2, rect.width // 8))


class LobbyZeile(_Base):
    """Eine Zeile der Liste."""

    def __init__(self, rect: pygame.Rect, index: int) -> None:
        super().__init__(rect)
        self.index = index
        self.eintrag: LobbyEintrag | None = None
        self.enabled = False
        self.focusable = False

    def setzen(self, eintrag: LobbyEintrag | None) -> None:
        self.eintrag = eintrag
        ok = bool(eintrag is not None and eintrag.beitretbar)
        # Leere Zeilen zaehlen nicht als „gesperrt": ein Klick ins Leere soll
        # nicht wie ein abgewiesener Knopf klingen.
        self.enabled = ok or eintrag is None
        self.focusable = ok

    def activate(self) -> str | None:
        return f"zeile_{self.index}" if self.enabled else None

    def hit(self, pos) -> bool:
        return self.eintrag is not None and self.rect.collidepoint(pos)

    def _status(self) -> tuple[str, tuple]:
        e = self.eintrag
        if e.im_rennen:
            return tr("Im Rennen"), theme.TEXT_DIM
        if e.voll:
            return tr("Voll"), theme.TEXT_DIM
        return tr("Offen"), theme.SUCCESS

    def draw(self, screen, focused: bool = False) -> None:
        e = self.eintrag
        if e is None:
            return
        r = self.rect
        hell = (focused or self._hover()) and self.enabled
        if not self.enabled:
            fill, border, txt, dim = (24, 26, 34), theme.BORDER, theme.DISABLED, theme.DISABLED
        elif hell:
            fill, border, txt, dim = (52, 44, 20), theme.ACCENT_HOT, theme.TEXT, theme.TEXT_DIM
        else:
            fill, border, txt, dim = theme.PANEL_LIGHT, theme.BORDER, theme.TEXT, theme.TEXT_DIM
        zeichnen.rect(screen, fill, r, border_radius=8)
        zeichnen.rect(screen, border, r, 3 if focused else 2, border_radius=8)

        text, farbe = self._status()
        theme.text(screen, text, theme.LABEL, farbe if self.enabled else theme.DISABLED,
                   (r.x + COL_STATUS, r.centery), midleft=True, max_w=COL_SCHLOSS - COL_STATUS - 10)
        if e.password:
            schloss_zeichnen(screen, pygame.Rect(r.x + COL_SCHLOSS, r.centery - 13, 20, 26),
                             theme.ACCENT if self.enabled else theme.DISABLED)
        name_rect = pygame.Rect(r.x + COL_NAME, r.y + 4, COL_HOST - COL_NAME - 24, 34)
        theme.text_fit(screen, e.name, theme.BODY, txt, name_rect, center=False)
        zusatz = tr(e.server.label) if not e.mode else f"{tr(e.server.label)}  ·  {tr(e.mode)}"
        theme.text_fit(screen, zusatz, theme.SMALL, dim,
                       pygame.Rect(r.x + COL_NAME, r.y + 38, COL_HOST - COL_NAME - 24, 22),
                       center=False)
        theme.text_fit(screen, e.host, theme.LABEL, txt,
                       pygame.Rect(r.x + COL_HOST, r.y, COL_SPIELER_R - COL_HOST - 150, r.height),
                       center=False)
        theme.text(screen, f"{e.players} / {e.max}", theme.LABEL, txt,
                   (r.x + COL_SPIELER_R, r.centery), midright=True)
        balken = server_probe.quality_bars(e.ping_ms)
        signal_bars(screen, pygame.Rect(r.x + COL_BALKEN, r.centery - 14, 34, 28),
                    balken, enabled=self.enabled and e.ping_ms is not None)
        ping = f"{e.ping_ms:.0f} ms" if e.ping_ms is not None else "—"
        theme.text(screen, ping, theme.LABEL, txt if e.ping_ms is not None else theme.DISABLED,
                   (r.x + COL_PING_R, r.centery), midright=True)


class LobbyBrowser:
    """Ansicht und Bedienung der Lobbyliste."""

    def __init__(self, liste: LobbyListe | None = None) -> None:
        self.liste = liste or LobbyListe()
        self.zeit_seit_abfrage = lobby_liste.INTERVALL     # beim ersten update sofort
        self.versatz = 0
        self.gewaehlt: LobbyEintrag | None = None
        self.meldung = ""
        self._ansicht: list[LobbyEintrag] = []
        self._fokus_code = ""

        self.b_erstellen = Button(pygame.Rect(_LIST_X, _TASTEN_Y, 420, 60),
                                  tr("Lobby erstellen") + "  ›", "create")
        self.b_code = Button(pygame.Rect(_LIST_X + 440, _TASTEN_Y, 420, 60),
                             tr("Mit Code beitreten"), "code", style="secondary")
        self.b_strecken = Button(pygame.Rect(_LIST_X + 880, _TASTEN_Y, 420, 60),
                                 tr("Online-Strecken"), "strecken", style="secondary")

        namen = [sd.label for sd in self.liste.server()]
        self.s_server = Stepper(pygame.Rect(_LIST_X, _FILTER_Y, 560, 56), tr("Server"),
                                [tr("Alle Server")] + [tr(n) for n in namen], 0,
                                action="filter")
        self.s_nur = Stepper(pygame.Rect(_LIST_X + 580, _FILTER_Y, 560, 56), tr("Anzeigen"),
                             [tr("Alle Lobbys"), tr("Nur beitretbare")], 0, action="filter")
        self.zeilen = [LobbyZeile(pygame.Rect(_LIST_X, _LIST_Y + i * _ZEILE_ABSTAND,
                                              _LIST_W, _ZEILE_H), i)
                       for i in range(ZEILEN)]
        self.gruppe = FocusGroup([self.b_erstellen, self.b_code, self.b_strecken,
                                  self.s_server, self.s_nur, *self.zeilen])

    # -- Filter ------------------------------------------------------------------
    @property
    def nur_beitretbare(self) -> bool:
        return self.s_nur.index == 1

    @property
    def server_id(self) -> str:
        """Id des gewaehlten Servers, leer = alle."""
        i = self.s_server.index
        srv = self.liste.server()
        return srv[i - 1].id if 0 < i <= len(srv) else ""

    # -- Lebenslauf --------------------------------------------------------------
    def betreten(self) -> None:
        """Beim (erneuten) Zeigen der Liste: gleich neu fragen."""
        self.zeit_seit_abfrage = lobby_liste.INTERVALL
        self.meldung = ""

    def jetzt_aktualisieren(self) -> None:
        self.zeit_seit_abfrage = 0.0
        self.liste.aktualisieren()

    def update(self, dt: float) -> None:
        self.zeit_seit_abfrage += dt
        if self.zeit_seit_abfrage >= lobby_liste.INTERVALL:
            self.jetzt_aktualisieren()
        self.neu_zeigen()

    def neu_zeigen(self) -> None:
        """Die Zeilen mit dem aktuellen Stand der Liste fuellen."""
        fokus = self.gruppe.focused
        if isinstance(fokus, LobbyZeile) and fokus.eintrag is not None:
            self._fokus_code = fokus.eintrag.code
        elif not isinstance(fokus, LobbyZeile):
            self._fokus_code = ""
        self._ansicht = self.liste.ansicht(nur_beitretbare=self.nur_beitretbare,
                                           server_id=self.server_id)
        self.versatz = max(0, min(self.versatz, max(0, len(self._ansicht) - ZEILEN)))
        sichtbar = self._ansicht[self.versatz:self.versatz + ZEILEN]
        for i, z in enumerate(self.zeilen):
            z.setzen(sichtbar[i] if i < len(sichtbar) else None)
        # Die Reihenfolge aendert sich mit jeder Runde (Ping, neue Lobbys). Der
        # Fokus bleibt bei seiner Lobby, nicht an seinem Platz.
        if self._fokus_code:
            for i, z in enumerate(self.zeilen):
                if z.eintrag is not None and z.eintrag.code == self._fokus_code and z.focusable:
                    self.gruppe.index = self.gruppe.widgets.index(z)
                    break
        self.gruppe.fokus_richten()

    # -- Bedienung ---------------------------------------------------------------
    def _scrollen(self, d: int) -> bool:
        neu = max(0, min(self.versatz + d, max(0, len(self._ansicht) - ZEILEN)))
        if neu == self.versatz:
            return False
        self.versatz = neu
        self.neu_zeigen()
        return True

    def handle_event(self, event: pygame.event.Event) -> str | None:
        """Gibt eine Aktion zurueck (siehe Modulkopf) oder ``None``."""
        if event.type == pygame.MOUSEWHEEL:
            self._scrollen(-event.y)
            return None
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_PAGEDOWN:
                self._scrollen(ZEILEN)
                return None
            if event.key == pygame.K_PAGEUP:
                self._scrollen(-ZEILEN)
                return None
            if event.key == pygame.K_F5:
                self.jetzt_aktualisieren()
                return None
            fokus = self.gruppe.focused
            if isinstance(fokus, LobbyZeile):
                # An den Rand der Zeilen gefahren: die Liste rollt weiter, solange
                # darunter (bzw. darueber) noch eine waehlbare Lobby kommt.
                if event.key == pygame.K_DOWN and fokus.index == ZEILEN - 1:
                    nxt = self.versatz + ZEILEN
                    if nxt < len(self._ansicht) and self._ansicht[nxt].beitretbar:
                        self._scrollen(1)
                        return None
                elif event.key == pygame.K_UP and fokus.index == 0 and self.versatz > 0:
                    self._scrollen(-1)
                    return None
        aktion = self.gruppe.handle_event(event)
        if aktion is None:
            return None
        if aktion == "filter":
            self.versatz = 0
            self.neu_zeigen()
            return None
        if aktion.startswith("zeile_"):
            z = self.zeilen[int(aktion[6:])]
            if z.eintrag is None or not z.eintrag.beitretbar:
                return None
            self.gewaehlt = z.eintrag
            return "beitreten"
        return aktion

    # -- Zeichnen ----------------------------------------------------------------
    def _fusszeile(self) -> tuple[str, tuple]:
        """Text unter der Liste und seine Farbe."""
        if self.meldung:
            return self.meldung, theme.DANGER
        srv = self.liste.server()
        if not self.liste.geladen:
            return tr("Lade Lobbys …"), theme.TEXT_DIM
        if self.liste.alle_fehlgeschlagen():
            return tr("Keine Verbindung zu den Servern."), theme.DANGER
        if not self._ansicht:
            if self.nur_beitretbare:
                return tr("Keine beitretbare Lobby. Erstelle eine oder stelle den Filter um."), theme.TEXT_DIM
            return tr("Gerade ist keine Lobby offen. Erstelle eine oder tritt per Code bei."), theme.TEXT_DIM
        ausgefallen = [tr(s.label) for s in srv if self.liste.fehler.get(s.id)]
        if ausgefallen:
            return tr("Nicht erreichbar: {s}").format(s=", ".join(ausgefallen)), theme.ACCENT
        offen = sum(1 for e in self._ansicht if e.beitretbar)
        return tr("{n} von {m} Lobbys beitretbar").format(n=offen, m=len(self._ansicht)), theme.TEXT_DIM

    def draw(self, screen: pygame.Surface, area: pygame.Rect) -> None:
        kopf_y = _LIST_Y - 30
        for text, x, rechts in (
                (tr("Status"), COL_STATUS, False), (tr("Lobby"), COL_NAME, False),
                (tr("Host"), COL_HOST, False), (tr("Spieler"), COL_SPIELER_R, True),
                (tr("Ping"), COL_PING_R, True)):
            theme.text(screen, text, theme.SMALL, theme.TEXT_FAINT,
                       (_LIST_X + x, kopf_y), topright=rechts)

        self.gruppe.draw(screen)

        # Scrollleiste, nur wenn es mehr gibt als Zeilen.
        gesamt = len(self._ansicht)
        if gesamt > ZEILEN:
            bahn = pygame.Rect(_LIST_X + _LIST_W + 12, _LIST_Y, 8, ZEILEN * _ZEILE_ABSTAND - 8)
            zeichnen.rect(screen, theme.BORDER, bahn, border_radius=4)
            h = max(30, int(bahn.height * ZEILEN / gesamt))
            y = bahn.y + int((bahn.height - h) * self.versatz / (gesamt - ZEILEN))
            zeichnen.rect(screen, theme.ACCENT, pygame.Rect(bahn.x, y, bahn.width, h),
                          border_radius=4)

        text, farbe = self._fusszeile()
        theme.text(screen, text, theme.BODY, farbe,
                   (_LIST_X, _LIST_Y + ZEILEN * _ZEILE_ABSTAND + 8))
