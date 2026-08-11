"""Generic finite state machine with push/pop stack for overlay states."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

if TYPE_CHECKING:
    from src.states.base_state import BaseState

#: Zustaende, die keine Menueebene sind. Aus einem Rennen fuehrt kein "eine
#: Ebene zurueck", und wer daraus kommt, will auch nicht in die Bildschirme
#: zurueck, die davor lagen — der Verlauf faengt danach neu an.
KEINE_EBENE = frozenset({"loading", "welcome", "race"})

#: Mehr Ebenen kann kein Weg im Spiel haben; die Grenze faengt nur den Fall ab,
#: dass zwei Bildschirme sich gegenseitig aufrufen und der Verlauf endlos waechst.
MAX_VERLAUF = 16


class StateMachine:
    """Manages game states with transition and push/pop stack.

    Supports:
    - transition(): Hard switch between states (exit old → enter new).
    - push(): Overlay a state on top (e.g. pause menu).
    - pop(): Return to the previous state.
    - zurueck(): eine Ebene zurueck, ohne dass der Aufrufer wissen muss, woher
      er kam.
    """

    def __init__(self) -> None:
        self._states: dict[str, BaseState] = {}
        self._current: BaseState | None = None
        self._stack: list[BaseState] = []
        #: Woher der Weg kam: [(Zustandsname, kwargs), ...], juengster zuletzt.
        #:
        #: Vorher schrieb jeder Bildschirm seinen Rueckweg selbst hin, meist als
        #: ``transition("menu")``. Das ging so lange gut, wie es nur einen Weg
        #: dorthin gab — der Streckeneditor sprang deshalb aus der Strecke
        #: heraus gleich ins Hauptmenue statt in seine Projektliste
        #: (gemeldet 02.08.2026). Mit dem Verlauf muss kein Bildschirm mehr
        #: raten, und ein neuer erbt das richtige Verhalten, ohne dass jemand
        #: daran denken muss.
        self._verlauf: list[tuple[str, dict]] = []
        #: Womit ein Zustand zuletzt betreten wurde — die Vorgabe fuer den
        #: Rueckweg, wenn er nichts Eigenes meldet.
        self._letzte_kwargs: dict[str, dict] = {}

    @property
    def current(self):
        """The currently active state object (or None)."""
        return self._current

    @property
    def current_state_name(self) -> str | None:
        """Return the name of the currently active state, or None."""
        for name, state in self._states.items():
            if state is self._current:
                return name
        return None

    def register(self, name: str, state: BaseState) -> None:
        """Register a state under a given name."""
        self._states[name] = state

    def transition(self, name: str, *, _zurueck: bool = False, **kwargs) -> None:
        """Hard-switch to a new state. Calls exit() on old, enter() on new.

        Nebenbei wird der Verlauf gefuehrt, damit ``zurueck()`` eine Ebene
        hochgehen kann. ``_zurueck`` ist dafuer reserviert und gehoert nicht in
        Aufrufe von aussen — ein Rueckweg legt keinen neuen Rueckweg an.
        """
        if name not in self._states:
            raise KeyError(f"State '{name}' not registered.")
        if not _zurueck:
            self._verlauf_fortschreiben(name)
        self._letzte_kwargs[name] = dict(kwargs)
        if self._current is not None:
            self._current.exit()
        self._update_music(name)
        self._current = self._states[name]
        self._current.enter(**kwargs)

    # ------------------------------------------------------------------
    # Rueckweg
    # ------------------------------------------------------------------
    def _verlauf_fortschreiben(self, ziel: str) -> None:
        alt = self.current_state_name
        if ziel in KEINE_EBENE or alt in KEINE_EBENE or alt is None:
            self._verlauf.clear()
            return
        if ziel == alt:
            # Ein Bildschirm, der sich selbst neu betritt (Fahrzeugwahl von
            # Spieler 1 auf Spieler 2), ist eine neue Ebene wie jede andere —
            # aber zwei gleiche Eintraege hintereinander waeren einer zu viel,
            # wenn er nur seine Argumente wechselt.
            if self._verlauf and self._verlauf[-1][0] == alt:
                return
        self._verlauf.append((alt, self._rueckweg_kwargs(alt)))
        del self._verlauf[:-MAX_VERLAUF]

    def _rueckweg_kwargs(self, name: str) -> dict:
        """Womit *name* wiederherzustellen ist.

        Vorgabe sind die Argumente, mit denen er zuletzt betreten wurde. Ein
        Zustand, der seinen Stand selbst haelt (die Menue-Shell mit ihrem
        Seitenstapel), meldet ueber ``rueckweg_kwargs()`` etwas anderes.
        """
        eigene = getattr(self._states.get(name), "rueckweg_kwargs", None)
        if callable(eigene):
            werte = eigene()
            if werte is not None:
                return dict(werte)
        return dict(self._letzte_kwargs.get(name, {}))

    def kann_zurueck(self) -> bool:
        return bool(self._verlauf)

    def zurueck(self, fallback: str | None = "menu") -> bool:
        """Eine Ebene zurueck. False, wenn es keine gibt.

        *fallback* ist der Ausweg fuer den Fall, dass der Verlauf leer ist —
        etwa nach einem Rennen, das ihn zurueckgesetzt hat.
        """
        from src.core import sfx
        while self._verlauf:
            name, kwargs = self._verlauf.pop()
            if name in self._states:
                sfx.menue("zurueck")
                self.transition(name, _zurueck=True, **kwargs)
                return True
        if fallback and fallback in self._states:
            self.transition(fallback, _zurueck=True)
            return True
        return False

    def verlauf_leeren(self) -> None:
        """Von hier aus gibt es kein Zurueck mehr (z.B. nach einem Rennen)."""
        self._verlauf.clear()

    def push(self, name: str, **kwargs) -> None:
        """Push current state onto stack and switch to a new state."""
        if name not in self._states:
            raise KeyError(f"State '{name}' not registered.")
        if self._current is not None:
            self._current.pause()
            self._stack.append(self._current)
        self._update_music(name)
        self._current = self._states[name]
        self._current.enter(**kwargs)

    def pop(self) -> None:
        """Pop the top state and resume the one below."""
        if self._current is not None:
            self._current.exit()
        if self._stack:
            self._current = self._stack.pop()
            self._update_music(self.current_state_name)
            self._current.resume()
        else:
            self._current = None

    def _update_music(self, state_name: str | None) -> None:
        from src.core import audio
        if state_name in ("vehicle_lab", "dev"):
            audio.play_race_music()
        elif state_name in ("welcome", "menu", "car_select", "track_select", "editor"):
            audio.play_menu_music()
        else:
            audio.stop_music()

    def handle_events(self, events: list[pygame.event.Event]) -> None:
        """Forward events to the current state."""
        if self._current is not None:
            self._current.handle_events(events)

    def update(self, dt: float) -> None:
        """Update the current state."""
        self._netz_am_leben_halten(dt)
        if self._current is not None:
            self._current.update(dt)

    @staticmethod
    def _netz_am_leben_halten(dt: float) -> None:
        """Den TCP-Keepalive der Netzsitzung ticken — in **jedem** Zustand.

        ``NetworkClient.update`` schickt alle 20 Sekunden ein ``PING``; der
        Server wartet in ``_recv`` hoechstens 60 Sekunden auf den naechsten
        Nachrichtenkopf und schliesst danach. Der Keepalive ist damit das
        Einzige, was eine stille Lobby am Leben haelt.

        Gerufen wurde er frueher nur in der Online-Lobby und im Rennen. Die
        Fahrzeugauswahl ist ein eigener Zustand — wer laenger als eine Minute
        durch die fuenfzehn Autos blaetterte, flog heraus, ohne dass etwas zu
        sehen war: die Trennung faellt in eine Zeit, in der niemand die
        Ereignisschlange liest. Dasselbe galt fuer Streckenauswahl, Werkstatt
        und Ladebildschirm (gemeldet 07.08.2026).

        Hier und nicht in den Zustaenden, weil es keine Zustandslogik ist,
        sondern Infrastruktur: jeder Bildschritt kommt hier vorbei, ein neuer
        Zustand kann es nicht vergessen.
        """
        from src.net import session
        netz = session.get()
        if netz is None:
            return
        try:
            netz.update(dt)
        except Exception:
            # Ein Netzfehler darf den Bildlauf nicht mitreissen. Bemerkt wird er
            # ohnehin: der Empfangsfaden legt ein Fehlerereignis in die
            # Schlange, und die liest der Zustand, den es angeht.
            pass

    def render(self, screen: pygame.Surface) -> None:
        """Render the current state."""
        if self._current is not None:
            self._current.render(screen)
