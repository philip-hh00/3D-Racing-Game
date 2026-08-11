"""FocusGroup — keyboard + mouse focus management for a set of widgets.

Keeps hover and keyboard focus in sync: moving the mouse over a widget makes it
the focused one, and the arrow keys move focus from wherever the pointer left it.
The owning screen builds a group, feeds it events, and reads back action strings.

Der Controller laeuft ueber dieselben Wege — der Gamepad-Manager uebersetzt ihn
in synthetische Tastenereignisse. Ein Unterschied bleibt: Elemente, die
links/rechts fuer sich beanspruchen (Stepper), muessen dort erst mit A geoeffnet
werden, siehe ``bearbeiten``.
"""
from __future__ import annotations

import pygame


class FocusGroup:
    """Ordered list of focusable widgets navigated with arrows + mouse."""

    def __init__(self, widgets: list | None = None, *, vertical: bool = True) -> None:
        self.widgets = list(widgets or [])
        self.vertical = vertical
        self.index = self._first_focusable()
        #: Ob das fokussierte Widget am Controller "geoeffnet" ist.
        #:
        #: Ein Stepper beantwortet links/rechts immer mit einer Wertaenderung.
        #: Damit kam der Fokus am Controller nie zu einem Nachbarn, der links
        #: oder rechts daneben liegt — man sass fest (gemeldet 31.07.2026).
        #:
        #: Deshalb ist ein Stepper am Controller geschlossen: A oeffnet ihn,
        #: dann aendert das D-Pad den Wert, A schliesst ihn wieder.
        #: Geschlossen bewegt links/rechts den Fokus.
        #:
        #: **Nur fuer den Controller.** Der Gamepad-Manager uebersetzt Tasten in
        #: synthetische KEYDOWN-Ereignisse (``synthetic=True``); daran wird es
        #: erkannt. An der Tastatur bleibt der Direktzugriff: dort stoert das
        #: Schlucken nicht, und ein Pflicht-ENTER vor jeder Lautstaerkeaenderung
        #: waere ein Rueckschritt.
        self.bearbeiten = False
        #: Ob der letzte Klick ein Bedienelement getroffen hat — auch dann, wenn
        #: es keine Aktion ausgeloest hat. Nur fuer den Klang.
        self._klick_traf = False

    def set_widgets(self, widgets: list, keep_focus: bool = False) -> None:
        self.bearbeiten = False
        prev = self.focused if keep_focus else None
        self.widgets = list(widgets)
        if prev is not None and prev in self.widgets and getattr(prev, "focusable", False):
            self.index = self.widgets.index(prev)
        else:
            self.index = self._first_focusable()

    def fokus_richten(self) -> None:
        """Den Fokus von einem gesperrten Element wegholen.

        Eine Seite darf ``enabled`` an ihren Knoepfen umstellen, ohne die Liste
        neu zu setzen — sonst springt der Fokus bei jeder Aenderung zurueck an
        den Anfang. Bleibt er dabei auf einem gesperrten Knopf stehen, laeuft
        jede Taste ins Leere.
        """
        if not getattr(self.focused, "focusable", False):
            self.index = self._first_focusable()

    def _first_focusable(self) -> int:
        for i, w in enumerate(self.widgets):
            if getattr(w, "focusable", False):
                return i
        return 0

    @property
    def focused(self):
        if 0 <= self.index < len(self.widgets):
            return self.widgets[self.index]
        return None

    def _schliessen(self) -> None:
        self.bearbeiten = False

    def _bearbeitbar(self, w) -> bool:
        """Ob *w* am Controller erst geoeffnet werden muss."""
        return bool(w is not None and getattr(w, "bearbeitbar", False)
                    and getattr(w, "focusable", False))

    def _pruefen(self) -> None:
        """Ein offener Zustand ohne passendes Widget waere ein Geist: das
        D-Pad ginge dann ins Leere. Kann passieren, wenn eine Seite die Liste
        an ``self.widgets`` vorbei umbaut."""
        if self.bearbeiten and not self._bearbeitbar(self.focused):
            self.bearbeiten = False

    def _move(self, d: int) -> None:
        self._schliessen()
        n = len(self.widgets)
        if n == 0:
            return
        i = self.index
        for _ in range(n):
            i = (i + d) % n
            if getattr(self.widgets[i], "focusable", False):
                self.index = i
                return

    def _move_spatial(self, direction: str) -> None:
        """Find and focus the closest focusable widget in 2D space ('up', 'down', 'left', 'right')."""
        self._schliessen()
        if not self.widgets:
            return
        cur = self.focused
        if cur is None or not hasattr(cur, "rect") or cur.rect is None:
            if direction in ("up", "left"):
                self._move(-1)
            else:
                self._move(+1)
            return

        cx, cy = cur.rect.center
        best_idx = None
        best_dist = float("inf")

        for i, w in enumerate(self.widgets):
            if i == self.index or not getattr(w, "focusable", False):
                continue
            r = getattr(w, "rect", None)
            if r is None:
                continue
            wx, wy = r.center

            dx = wx - cx
            dy = wy - cy
            valid = False
            dist = float("inf")

            if direction == "left" and dx < -5:
                valid = True
                dist = abs(dx) + 2.5 * abs(dy)
            elif direction == "right" and dx > 5:
                valid = True
                dist = abs(dx) + 2.5 * abs(dy)
            elif direction == "up" and dy < -5:
                valid = True
                dist = abs(dy) + 2.5 * abs(dx)
            elif direction == "down" and dy > 5:
                valid = True
                dist = abs(dy) + 2.5 * abs(dx)

            if valid and dist < best_dist:
                best_dist = dist
                best_idx = i

        if best_idx is not None:
            self.index = best_idx
        else:
            if direction in ("up", "left"):
                self._move(-1)
            else:
                self._move(+1)

    def handle_event(self, event) -> str | None:
        """Route one event; return an action string if a widget fired one.

        Klingt dabei, was etwas bewirkt: ein verstellter Wert leiser, ein
        ausgelöster Knopf deutlicher, ein gesperrter Knopf abweisend. Blosses
        Bewegen des Fokus bleibt still — klänge jeder Schritt, hiesse keiner
        mehr etwas.
        """
        self._klick_traf = False
        ergebnis = self._verarbeiten(event)
        from src.core import sfx
        if ergebnis is not None:
            # Wer gehandelt hat, ist danach der fokussierte: ein Klick setzt den
            # Fokus vorher, und eine Taste bewegt ihn nur, wenn nichts passiert.
            sfx.menue("verstellt" if getattr(self.focused, "bearbeitbar", False)
                      else "ausgeloest")
        elif self._klick_traf:
            # Getroffen, aber keine Aktion: ein Textfeld nimmt den Klick nur an,
            # um den Schreibfokus zu bekommen. Das ist eine Reaktion und gehoert
            # quittiert — gemeldet am 03.08.2026 („Klick-Sound wird nicht bei
            # jedem Klick auf einen Button oder ein Textfeld abgespielt").
            # Leiser Anlass, weil sich nichts geaendert hat.
            sfx.menue("verstellt")
        elif self._auf_gesperrtes_geklickt(event):
            sfx.menue("gesperrt")
        return ergebnis

    def _auf_gesperrtes_geklickt(self, event) -> bool:
        """Klick auf einen gesperrten Knopf.

        Gesperrte Knöpfe sind nicht fokussierbar, treffen kann man sie mit der
        Maus trotzdem. Ohne Antwort sieht es aus, als hätte das Spiel den Klick
        verloren — dabei war er nur nicht erlaubt.
        """
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return False
        for w in self.widgets:
            if getattr(w, "focusable", False) or getattr(w, "enabled", True):
                continue
            r = getattr(w, "rect", None)
            if r is not None and r.collidepoint(event.pos):
                return True
        return False

    def _verarbeiten(self, event) -> str | None:
        self._pruefen()
        # Mouse hover updates focus to whatever is under the pointer.
        if event.type == pygame.MOUSEMOTION:
            for i, w in enumerate(self.widgets):
                if getattr(w, "focusable", False) and w.hit(event.pos):
                    if i != self.index:
                        self._schliessen()
                    self.index = i
                    break
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i, w in enumerate(self.widgets):
                if getattr(w, "focusable", False) and w.hit(event.pos):
                    # Die Maus trifft den Pfeil direkt; ein Bearbeitungsmodus
                    # waere hier nur ein zusaetzlicher Klick.
                    self._klick_traf = True
                    self._schliessen()
                    self.index = i
                    # Steppers distinguish which arrow was clicked.
                    if hasattr(w, "handle_click"):
                        return w.handle_click(event.pos)
                    return w.activate()
        # Rohe JOYHATMOTION-Ereignisse werden hier bewusst nicht mehr
        # ausgewertet: der Gamepad-Manager uebersetzt jeden D-Pad-Druck bereits
        # in ein synthetisches KEYDOWN. Wer beides annahm, sprang pro Druck zwei
        # Felder weiter bzw. zaehlte einen Stepper um zwei Werte hoch.
        elif event.type == pygame.KEYDOWN:
            from src.core import keybindings as kb
            w = self.focused
            typing = bool(getattr(w, "captures_text", False))
            # Nur der Controller kennt den Bearbeitungsmodus — seine Eingaben
            # kommen als synthetische Ereignisse herein.
            pad = bool(getattr(event, "synthetic", False))
            zu = pad and self._bearbeitbar(w) and not self.bearbeiten

            is_up = event.key in ((pygame.K_UP,) if typing else (pygame.K_UP, pygame.K_w, kb.get("throttle")))
            is_down = event.key in ((pygame.K_DOWN,) if typing else (pygame.K_DOWN, pygame.K_s, kb.get("brake")))
            is_left = event.key in ((pygame.K_LEFT,) if typing else (pygame.K_LEFT, pygame.K_a, kb.get("left")))
            is_right = event.key in ((pygame.K_RIGHT,) if typing else (pygame.K_RIGHT, pygame.K_d, kb.get("right")))

            if is_up:
                self._move_spatial("up")
            elif is_down:
                self._move_spatial("down")
            elif is_left or is_right:
                richtung = "left" if is_left else "right"
                taste = pygame.K_LEFT if is_left else pygame.K_RIGHT
                if zu:
                    # Geschlossen: der Wert bleibt, der Fokus wandert weiter.
                    self._move_spatial(richtung)
                    return None
                res = w.handle_key(taste) if (w is not None and hasattr(w, "handle_key")) else None
                if res is not None:
                    return res
                if not typing:
                    # Auch offen: ein Widget, das nichts damit anfangen kann,
                    # darf den Fokus nicht festhalten.
                    self._move_spatial(richtung)
            elif event.key == pygame.K_RETURN:
                if pad and self._bearbeitbar(w):
                    self.bearbeiten = not self.bearbeiten
                    return None
                if w is not None:
                    return w.activate()
            elif event.key == pygame.K_ESCAPE and self.bearbeiten:
                # Greift nur, wenn die Seite ESC nicht schon vorher abfaengt —
                # dort ist B ohnehin "zurueck", und A schliesst genauso.
                self._schliessen()
                return None
            else:
                if w is not None and hasattr(w, "handle_key"):
                    try:
                        return w.handle_key(event.key, getattr(event, "unicode", ""))
                    except TypeError:
                        return w.handle_key(event.key)
        return None

    def draw(self, screen, focused: bool = True) -> None:
        self._pruefen()
        for i, w in enumerate(self.widgets):
            if getattr(w, "bearbeitbar", False):
                # Das Widget zeichnet den offenen Zustand selbst — es muss ihn
                # nur kennen.
                w.bearbeitet = self.bearbeiten and i == self.index
            w.draw(screen, focused=focused and (i == self.index))
