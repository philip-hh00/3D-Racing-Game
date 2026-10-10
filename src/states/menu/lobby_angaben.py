"""Die Angaben zu einer Online-Lobby: Sichtbarkeit, Name, Passwort (Plan 1.1.0).

Ein Formular, das an zwei Stellen gebraucht wird und deshalb nur einmal gebaut
ist: beim Erstellen der Lobby (``OnlineLobbyPage._HOST_SERVER``) und fuer den
Host in der Lobby (``_LOBBY_EDIT``). Es besteht aus

* einem Wahlfeld **Sichtbarkeit** (Oeffentlich — Oeffentlich mit Passwort —
  Privat), Vorgabe Oeffentlich,
* einem Feld **Lobby-Name** (Vorgabe „<Host>'s Lobby", hoechstens 24 Zeichen,
  geprueft wie Spielernamen samt Sperrliste),
* einem Feld **Passwort** (4 bis 16 Zeichen), das nur bei „Oeffentlich mit
  Passwort" da ist.

Die Seite holt sich die Bedienelemente ueber :meth:`widgets` in ihre
``FocusGroup``, setzt sie nach jeder Aenderung der Sichtbarkeit neu
(:meth:`passwort_sichtbar`) und zeichnet die Beschriftungen ueber :meth:`draw`.
"""
from __future__ import annotations

import pygame

from src.core import profile
from src.core.i18n import tr
from src.ui import theme
from src.ui.widgets import Stepper, TextInput

#: Interne Werte, wie der Relay sie kennt (``server.py:SICHTBARKEITEN``).
OEFFENTLICH = "public"
PASSWORT = "password"
PRIVAT = "private"
WERTE = [OEFFENTLICH, PASSWORT, PRIVAT]
#: Anzeige, in derselben Reihenfolge.
BESCHRIFTUNG = ["Öffentlich", "Öffentlich mit Passwort", "Privat"]


def sichtbarkeit_text(wert: str) -> str:
    """Kurzer Text fuer die Anzeige in der Lobby."""
    if wert in WERTE:
        return tr(BESCHRIFTUNG[WERTE.index(wert)])
    return tr(BESCHRIFTUNG[2])


class LobbyAngaben:
    """Sichtbarkeit, Name und Passwort einer Lobby, mit Pruefung."""

    ZEILE_H = 56

    def __init__(self, *, sichtbarkeit: str = OEFFENTLICH, name: str = "",
                 passwort: str = "") -> None:
        self.stepper = Stepper(
            pygame.Rect(0, 0, 840, self.ZEILE_H), tr("Sichtbarkeit"),
            [tr(b) for b in BESCHRIFTUNG],
            WERTE.index(sichtbarkeit) if sichtbarkeit in WERTE else 0,
            action="sichtbarkeit", waehler_breite=440)
        self.name_feld = TextInput(
            pygame.Rect(0, 0, 840, self.ZEILE_H), name,
            max_len=profile.LOBBY_NAME_MAX)
        self.pw_feld = TextInput(
            pygame.Rect(0, 0, 840, self.ZEILE_H), passwort,
            max_len=profile.LOBBY_PW_MAX)
        self.meldung = ""
        #: In der Lobby mit schon gesetztem Passwort darf das Feld leer bleiben:
        #: dann gilt das alte weiter.
        self.pw_behalten = False

    # -- Werte -----------------------------------------------------------------
    @property
    def sichtbarkeit(self) -> str:
        return WERTE[self.stepper.index]

    @property
    def name(self) -> str:
        return self.name_feld.text.strip()

    @property
    def passwort(self) -> str:
        return self.pw_feld.text

    def passwort_sichtbar(self) -> bool:
        """Ob das Passwortfeld gerade da ist."""
        return self.sichtbarkeit == PASSWORT

    def widgets(self) -> list:
        w = [self.stepper, self.name_feld]
        if self.passwort_sichtbar():
            w.append(self.pw_feld)
        return w

    # -- Pruefung --------------------------------------------------------------
    def pruefen(self, *, passwort_noetig: bool | None = None) -> bool:
        """Ob die Eingaben gesendet werden duerfen. Sonst steht der Grund in
        ``meldung``.

        Das Passwort ist Pflicht bei „mit Passwort" - ausser in der Lobby, wenn
        schon eines gilt (``pw_behalten``): dann darf das Feld leer bleiben.
        """
        if passwort_noetig is None:
            passwort_noetig = not self.pw_behalten
        ok, grund = profile.validate_lobby_name(self.name)
        if not ok:
            self.meldung = grund
            return False
        if self.passwort_sichtbar() and (passwort_noetig or self.passwort):
            ok, grund = profile.validate_lobby_password(self.passwort)
            if not ok:
                self.meldung = grund
                return False
        self.meldung = ""
        return True

    def nachricht(self, vorgabe_name: str) -> dict:
        """Die Felder fuer ``HOST`` bzw. ``SET_LOBBY_INFO``."""
        out = {
            "visibility": self.sichtbarkeit,
            "lobby_name": self.name or vorgabe_name,
        }
        if self.passwort_sichtbar() and self.passwort:
            out["password"] = self.passwort
        return out

    # -- Layout und Zeichnen ---------------------------------------------------
    def anordnen(self, x: int, y: int, breite: int = 840, abstand: int = 14,
                 beschriftung: int = 30) -> int:
        """Setzt die Rechtecke ab (x, y) untereinander; gibt das untere Ende zurueck.

        Das Wahlfeld hat seine Beschriftung selbst, die zwei Textfelder bekommen
        eine kleine ueber sich (:meth:`draw`).
        """
        self._x = x
        self.stepper.rect = pygame.Rect(x, y, breite, self.ZEILE_H)
        y += self.ZEILE_H + abstand + beschriftung
        self._name_label_y = y - beschriftung
        self.name_feld.rect = pygame.Rect(x, y, breite, self.ZEILE_H)
        y += self.ZEILE_H + abstand
        self._pw_label_y = y + 0
        if self.passwort_sichtbar():
            y += beschriftung
            self.pw_feld.rect = pygame.Rect(x, y, breite, self.ZEILE_H)
            y += self.ZEILE_H
        return y

    def draw(self, screen: pygame.Surface, gruppe) -> None:
        """Beschriftungen und Felder zeichnen. *gruppe* ist die FocusGroup der
        Seite (fuer den Fokusrahmen der Textfelder)."""
        fokus = gruppe.focused
        # Am Controller ist der Wahler erst nach A „offen" (siehe FocusGroup).
        self.stepper.bearbeitet = bool(gruppe.bearbeiten and fokus is self.stepper)
        self.stepper.draw(screen, fokus is self.stepper)
        theme.text(screen, tr("Lobby-Name"), theme.HINT, theme.TEXT_DIM,
                   (self._x, self._name_label_y))
        self.name_feld.draw(screen, fokus is self.name_feld)
        if self.passwort_sichtbar():
            titel = (tr("Neues Passwort (leer = unverändert)") if self.pw_behalten
                     else tr("Passwort (4 bis 16 Zeichen)"))
            theme.text(screen, titel, theme.HINT, theme.TEXT_DIM,
                       (self._x, self._pw_label_y))
            self.pw_feld.draw(screen, fokus is self.pw_feld)
