"""Interactive menu widgets: Button, Stepper, TextInput, Label, Dialog.

All widgets share a tiny contract so a :class:`~src.ui.focus.FocusGroup` can drive
them uniformly:

    .rect                bounding rectangle (for mouse hit-testing / focus)
    .focusable           can it take keyboard focus?
    hit(pos) -> bool     is the point inside an interactive part?
    activate() -> str|None            triggered by ENTER / left-click
    handle_key(key) -> str|None       LEFT/RIGHT/typing while focused
    draw(screen, focused)             render (hover read from the mouse)

Return strings are free-form "action ids" the owning screen interprets.
"""
from __future__ import annotations

import pygame

from src.ui import theme
from src.core import display
from src.core.i18n import tr


class _Base:
    focusable = True
    #: Ob links/rechts auf diesem Widget einen Wert aendert (Stepper) statt den
    #: Fokus zu bewegen. Am Controller muss so ein Widget erst mit A geoeffnet
    #: werden — sonst schluckt es links/rechts und man kommt nie zum Nachbarn
    #: daneben (gemeldet 31.07.2026). Siehe FocusGroup.
    bearbeitbar = False
    #: Setzt die FocusGroup vor dem Zeichnen: Widget ist geoeffnet.
    bearbeitet = False

    def __init__(self, rect: pygame.Rect) -> None:
        self.rect = pygame.Rect(rect)

    def hit(self, pos) -> bool:
        return self.rect.collidepoint(pos)

    def activate(self) -> str | None:
        return None

    def handle_key(self, key: int) -> str | None:
        return None

    def _hover(self) -> bool:
        return self.rect.collidepoint(display.mouse_pos())


class Label(_Base):
    """Non-interactive text (headers, hints)."""
    focusable = False

    def __init__(self, pos, text: str, size: int = theme.BODY,
                 color=theme.TEXT, center=False) -> None:
        self.pos = pos
        self.text = text
        self.size = size
        self.color = color
        self.center = center
        surf = theme.font(size).render(text, True, color)
        r = surf.get_rect(center=pos) if center else surf.get_rect(topleft=pos)
        super().__init__(r)

    def draw(self, screen, focused=False) -> None:
        theme.text(screen, self.text, self.size, self.color, self.pos, center=self.center)


class Button(_Base):
    """Clickable button with hover / focus / disabled / coming-soon states."""

    def __init__(self, rect, label: str, action: str = "activate", *,
                 enabled: bool = True, coming_soon: bool = False,
                 style: str = "primary", hint: str = "") -> None:
        super().__init__(rect)
        self.label = label
        self.action = action
        self.coming_soon = coming_soon
        self.enabled = enabled and not coming_soon
        self.style = style
        self.focusable = self.enabled
        #: Begruendung fuer einen gesperrten Knopf, gezeigt beim Zeigen darauf.
        #: Ohne sie sieht man nur, DASS es nicht geht, nicht warum.
        self.hint = hint

    def activate(self) -> str | None:
        return self.action if self.enabled else None

    def draw(self, screen, focused=False) -> None:
        hover = self._hover() and self.enabled
        if not self.enabled:
            fill, border, txt = (26, 28, 36), theme.DISABLED, theme.DISABLED
        elif focused or hover:
            fill = (70, 56, 22) if self.style == "primary" else (46, 50, 62)
            border, txt = theme.ACCENT_HOT, theme.TEXT
        else:
            fill = (44, 38, 18) if self.style == "primary" else (32, 36, 46)
            border, txt = theme.ACCENT if self.style == "primary" else theme.BORDER_LIGHT, theme.TEXT
        pygame.draw.rect(screen, fill, self.rect, border_radius=8)
        pygame.draw.rect(screen, border, self.rect, 2 + (1 if focused else 0), border_radius=8)
        
        lbl_rect = pygame.Rect(self.rect.x + 16, self.rect.y, self.rect.width - 32, self.rect.height)
        theme.text_fit(screen, tr(self.label), theme.BODY, txt, lbl_rect, center=True)
        
        if self.coming_soon:
            theme.text(screen, "COMING SOON", theme.SMALL, theme.TEXT_FAINT,
                       (self.rect.centerx, self.rect.bottom - 12), center=True)

        # Gesperrt und der Zeiger liegt darauf: sagen, was fehlt. _hover() oben
        # ist mit self.enabled verundet, hier zaehlt genau der andere Fall.
        if self.hint and not self.enabled and self._hover():
            theme.text(screen, tr(self.hint), theme.HINT, theme.TEXT_DIM,
                       (self.rect.centerx, self.rect.top - 18), center=True)


class ZurueckKnopf(Button):
    """Der Rueckweg als sichtbare Schaltflaeche — auf jedem Bildschirm gleich.

    Gemeldet am 04.08.2026: „In den Menues Lobbys usw. gibt es noch teilweise
    keine zurueck Buttons und der User ist auf ESC angewiesen (das fuehrt aber
    manchmal auch direkt zum Hauptmenue)."

    Ein Knopf, den jeder Bildschirm selbst hinstellt, sitzt auf jedem
    Bildschirm anders — deshalb steht die Groesse und die Beschriftung hier und
    nicht bei den Aufrufern. Wo genau er sitzt, entscheidet der Bildschirm: die
    Menueseiten haben eine Inhaltsflaeche unter der Reiterleiste, die
    Auswahlbildschirme das ganze Fenster.

    Er fuehrt **immer** dorthin, wo auch die ESC-Taste hinfuehrt. Nicht aus
    Bequemlichkeit: zwei Wege fuer dieselbe Absicht liefen im Spiel schon
    auseinander (Werkstatt, gemeldet 03.08.2026), und ein Knopf, der etwas
    anderes tut als die Taste daneben, ist schlimmer als keiner.
    """

    BREITE = 190
    HOEHE = 52

    def __init__(self, x: int, y: int, action: str = "zurueck") -> None:
        super().__init__(pygame.Rect(x, y, self.BREITE, self.HOEHE),
                         "‹ Zurück", action, style="secondary")


class Stepper(_Base):
    """‹ value › selector cycling through *options*.

    Am Controller ist der Stepper ein **geschlossenes** Bedienelement: erst A
    druecken, dann mit dem D-Pad den Wert aendern, mit A oder B wieder zu.
    Ohne das schluckte er links/rechts und der Fokus kam nie zum Nachbarn.
    An der Tastatur bleibt es beim Direktzugriff — dort stoert nichts.
    """

    bearbeitbar = True

    def __init__(self, rect, label: str, options: list[str], index: int = 0, *,
                 action: str = "change", enabled: bool = True) -> None:
        super().__init__(rect)
        self.label = label
        self.options = options
        self.index = max(0, min(index, len(options) - 1)) if options else 0
        self.action = action
        self.enabled = enabled
        self.focusable = enabled

    @property
    def value(self) -> str:
        return self.options[self.index] if self.options else ""

    def _arrow_rects(self) -> tuple[pygame.Rect, pygame.Rect]:
        """Wo die beiden Pfeile **gezeichnet** werden."""
        s = 46
        # If there's no label, place arrows at the left and right edges of the widget.
        if not self.label:
            left = pygame.Rect(self.rect.x + 6, self.rect.y + 6, s, self.rect.height - 12)
            right = pygame.Rect(self.rect.right - s - 6, self.rect.y + 6, s, self.rect.height - 12)
        else:
            # If there is a label, the selector occupies the right part of the widget.
            # We allocate up to 250px (or half the width) on the right for it.
            sel_width = min(250, self.rect.width // 2)
            left = pygame.Rect(self.rect.right - sel_width, self.rect.y + 6, s, self.rect.height - 12)
            right = pygame.Rect(self.rect.right - s - 6, self.rect.y + 6, s, self.rect.height - 12)
        return left, right

    def _klickhaelften(self) -> tuple[pygame.Rect, pygame.Rect]:
        """Die beiden Klickhälften des Wählers: zurück und vor.

        Gemeldet im Playtest am 03.08.2026: „nur die linke Seite des Buttons
        lässt einen nach links gehen, der Pfeil sitzt aber mittig". Beides war
        richtig beobachtet. Der Wähler sitzt bei einem Stepper mit Beschriftung
        **rechts** im Element, das ‹ steht also in der Mitte des Kastens — und
        ``handle_click`` zählte alles, was nicht genau auf einem der zwei 46 px
        breiten Pfeile lag, **vorwärts**. Ein Klick auf die Beschriftung ganz
        links verstellte damit den Wert nach rechts.

        Jetzt gilt für den Wähler dieselbe Regel, die man ihm ansieht: was links
        vom Wert liegt, geht zurück, was rechts liegt, vor. Die Beschriftung ist
        kein Knopf und tut nichts.
        """
        links, _rechts = self._arrow_rects()
        # Ohne Beschriftung ist der ganze Kasten der Waehler — bis an die Kante,
        # nicht bis an den 6-px-Rand des Pfeilkastens. Ein toter Streifen am
        # Rand eines Knopfes ist genau die Sorte Kleinigkeit, die sich wie ein
        # verschluckter Klick anfuehlt.
        beginn = links.x if self.label else self.rect.x
        waehler = pygame.Rect(beginn, self.rect.y,
                              self.rect.right - beginn, self.rect.height)
        mitte = waehler.centerx
        return (pygame.Rect(waehler.x, waehler.y, mitte - waehler.x, waehler.height),
                pygame.Rect(mitte, waehler.y, waehler.right - mitte, waehler.height))

    def _step(self, d: int) -> str | None:
        if not self.enabled or not self.options:
            return None
        self.index = (self.index + d) % len(self.options)
        return self.action

    def handle_key(self, key: int) -> str | None:
        if key == pygame.K_LEFT:
            return self._step(-1)
        if key == pygame.K_RIGHT:
            return self._step(+1)
        return None

    def activate(self) -> str | None:
        return self._step(+1)

    def hit(self, pos) -> bool:
        return self.rect.collidepoint(pos)

    def handle_click(self, pos) -> str | None:
        zurueck, vor = self._klickhaelften()
        if zurueck.collidepoint(pos):
            return self._step(-1)
        if vor.collidepoint(pos):
            return self._step(+1)
        return None          # Beschriftung: getroffen, aber kein Knopf

    def draw(self, screen, focused=False) -> None:
        offen = bool(self.bearbeitet)
        col_border = (theme.ACCENT_HOT if offen else theme.ACCENT) if focused else theme.BORDER
        base = theme.PANEL_SEL if focused else theme.PANEL_LIGHT
        pygame.draw.rect(screen, base, self.rect, border_radius=8)
        # Offen = kraeftigerer Rahmen. Ohne sichtbaren Unterschied waere das
        # eine unsichtbare Umschaltung, und niemand wuesste, warum das D-Pad
        # mal den Wert und mal den Fokus bewegt.
        pygame.draw.rect(screen, col_border, self.rect, 3 if offen else 2, border_radius=8)
        lbl_col = theme.TEXT if self.enabled else theme.DISABLED

        left, right = self._arrow_rects()
        if self.label:
            lbl_rect = pygame.Rect(self.rect.x + 20, self.rect.y, left.left - self.rect.x - 30, self.rect.height)
            theme.text_fit(screen, tr(self.label), theme.BODY, lbl_col, lbl_rect, center=False)

        acol = theme.ACCENT if self.enabled else theme.DISABLED
        if offen and self.enabled:
            acol = theme.ACCENT_HOT
        # Hervorgehoben wird nach der KLICKFLAECHE, nicht nach dem Pfeilkasten:
        # so zeigt der Pfeil, wie weit man treffen darf. Vorher leuchtete er nur
        # auf 46 px, obwohl der halbe Waehler zaehlte — man klickte danach.
        mp = display.mouse_pos()
        h_zurueck, h_vor = self._klickhaelften()
        theme.text(screen, "‹", theme.HEADER,
                   theme.ACCENT_HOT if h_zurueck.collidepoint(mp) else acol,
                   left.center, center=True)
        theme.text(screen, "›", theme.HEADER,
                   theme.ACCENT_HOT if h_vor.collidepoint(mp) else acol,
                   right.center, center=True)
        vcol = theme.TEXT if self.enabled else theme.DISABLED
        
        val_rect = pygame.Rect(left.right + 4, self.rect.y, right.left - left.right - 8, self.rect.height)
        theme.text_fit(screen, tr(self.value), theme.BODY, vcol, val_rect, center=True)

        # Dass am Controller erst A gedrueckt werden muss, sieht man dem
        # Element sonst nicht an. Ein kleines A in der Ecke sagt es genau dort,
        # wo es gebraucht wird — an der Tastatur ist es weg, dort gilt es nicht.
        if focused and not offen and self.enabled:
            from src.core import input_mode
            if input_mode.is_pad():
                r = 11
                mitte = (self.rect.right - r - 3, self.rect.y + r + 3)
                pygame.draw.circle(screen, theme.PANEL, mitte, r)
                pygame.draw.circle(screen, theme.ACCENT_HOT, mitte, r, 2)
                theme.text(screen, "A", theme.HINT, theme.ACCENT_HOT, mitte, center=True)



class TextInput(_Base):
    """Single-line text field with cursor and character whitelist."""

    # Tells a FocusGroup this widget consumes typing, so WASD/throttle keys are
    # entered as text instead of being swallowed as menu navigation.
    captures_text = True

    def __init__(self, rect, text: str = "", *, max_len: int = 16,
                 allowed: str | None = None, uppercase: bool = False) -> None:
        super().__init__(rect)
        self.text = text
        self.max_len = max_len
        self.allowed = allowed
        self.uppercase = uppercase
        self._cursor_t = 0.0
        self.active = True

    def update(self, dt: float) -> None:
        self._cursor_t = (self._cursor_t + dt) % 1.0

    def handle_key(self, key: int, unicode: str = "") -> str | None:
        if key == pygame.K_BACKSPACE:
            self.text = self.text[:-1]
            return "edit"
        if self.uppercase and unicode:
            unicode = unicode.upper()
        if unicode and unicode.isprintable() and len(self.text) < self.max_len:
            if self.allowed is None or unicode in self.allowed:
                self.text += unicode
                return "edit"
        return None

    def draw(self, screen, focused=True) -> None:
        pygame.draw.rect(screen, theme.PANEL_LIGHT, self.rect, border_radius=6)
        pygame.draw.rect(screen, theme.ACCENT if focused else theme.BORDER,
                         self.rect, 2, border_radius=6)
        shown = self.text
        if focused and self._cursor_t < 0.5:
            shown += "|"
        text_rect = pygame.Rect(self.rect.x + 14, self.rect.y, self.rect.width - 28, self.rect.height)
        theme.text_fit(screen, shown, theme.BODY, theme.TEXT, text_rect, center=False)


def signal_bars(screen, rect: pygame.Rect, level: int, *, enabled: bool = True) -> None:
    """Three rising bars, *level* of them filled (0–3).

    Colour follows the level, not the widget state: one bar is always red, two
    amber, three green — so quality reads at a glance without the legend.
    """
    colors = {3: theme.SUCCESS, 2: theme.ACCENT, 1: theme.DANGER}
    on = colors.get(level, theme.DISABLED) if enabled else theme.DISABLED
    off = theme.BORDER if enabled else (40, 42, 52)

    bar_w = max(4, rect.width // 5)
    gap = max(2, bar_w // 2)
    for i in range(3):
        h = int(rect.height * (0.4 + 0.3 * i))
        bar = pygame.Rect(rect.x + i * (bar_w + gap), rect.bottom - h, bar_w, h)
        pygame.draw.rect(screen, on if i < level else off, bar, border_radius=2)


class ServerRow(_Base):
    """Selectable relay server: name, quality bars, ping, lobby count.

    Unreachable or version-mismatched servers stay visible but are greyed out
    and drop out of the focus order (``focusable`` mirrors ``enabled``), so a
    player can see *why* a server is missing instead of it silently vanishing.

    Column positions are fixed offsets from the row's left edge, not fractions:
    the longest right-hand texts are "Version veraltet" (150 px) and
    "Keine Lobbys" (128 px), so that column needs a guaranteed 170 px. The
    header labels in the owning page use the same constants, so headings and
    values line up.
    """

    #: Offsets vom linken Rand der Zeile (Zeilenbreite: 840 px).
    COL_NAME = 44          # linke Kante des Servernamens
    COL_BARS = 380         # linke Kante der Balken (34 px breit)
    COL_PING = 560         # RECHTE Kante des Pingwerts
    COL_STATUS_W = 170     # Breite der rechten Spalte (Lobbys / Offline)

    def __init__(self, rect, label: str, action: str = "pick_server", *,
                 selected: bool = False) -> None:
        super().__init__(rect)
        self.label = label
        self.action = action
        self.selected = selected
        self.bars = 0
        self.ping_ms: float | None = None
        self.status_text = ""        # replaces the lobby count when not online
        self.lobby_count = 0
        #: Lobbygrenze des Servers, 0 = unbekannt. Ein Relay ohne die Neuerung
        #: aus Block H (H2.14) schickt sie nicht; dann steht dort weiter nur die
        #: Zahl der offenen Lobbys.
        self.lobby_max = 0
        #: Ob der Server gerade keine neuen Lobbys annimmt (H2.14).
        self.ausgelastet = False
        self.enabled = False
        self.focusable = False

    def set_status(self, *, enabled: bool, bars: int, ping_ms: float | None,
                   lobby_count: int, status_text: str = "",
                   lobby_max: int = 0, ausgelastet: bool = False) -> None:
        self.enabled = enabled
        self.focusable = enabled
        self.bars = bars
        self.ping_ms = ping_ms
        self.lobby_count = lobby_count
        self.lobby_max = lobby_max
        self.ausgelastet = ausgelastet
        self.status_text = status_text

    def activate(self) -> str | None:
        return self.action if self.enabled else None

    def draw(self, screen, focused=False) -> None:
        hover = self._hover() and self.enabled
        if not self.enabled:
            fill, border, txt = (24, 26, 34), theme.BORDER, theme.DISABLED
        elif focused or hover:
            fill, border, txt = (52, 44, 20), theme.ACCENT_HOT, theme.TEXT
        elif self.selected:
            fill, border, txt = theme.PANEL_SEL, theme.ACCENT, theme.TEXT
        else:
            fill, border, txt = theme.PANEL_LIGHT, theme.BORDER, theme.TEXT
        pygame.draw.rect(screen, fill, self.rect, border_radius=8)
        pygame.draw.rect(screen, border, self.rect, 2 + (1 if focused else 0), border_radius=8)

        # Selection marker — visible without relying on the fill tint alone.
        if self.selected and self.enabled:
            dot = pygame.Rect(self.rect.x + 16, self.rect.centery - 7, 14, 14)
            pygame.draw.rect(screen, theme.ACCENT, dot, border_radius=7)

        # Feste Spalten statt gerechneter Abstände: die längsten Texte sind
        # "Version veraltet" (150 px) und "Keine Lobbys" (128 px), dafür braucht
        # die rechte Spalte 170 px. Vorher überlagerten sich Ping und Status.
        name_rect = pygame.Rect(self.rect.x + self.COL_NAME, self.rect.y,
                                self.COL_BARS - self.COL_NAME - 24, self.rect.height)
        theme.text_fit(screen, tr(self.label), theme.BODY, txt, name_rect, center=False)

        bars_rect = pygame.Rect(self.rect.x + self.COL_BARS, self.rect.centery - 14, 34, 28)
        signal_bars(screen, bars_rect, self.bars, enabled=self.enabled)

        ping = f"{self.ping_ms:.0f} ms" if (self.enabled and self.ping_ms is not None) else "—"
        theme.text(screen, ping, theme.LABEL, txt,
                   (self.rect.x + self.COL_PING, self.rect.centery), midright=True)

        # Reihenfolge nach Dringlichkeit: erreichbar? — ausgelastet? — wie voll?
        # „Ausgelastet" steht dort, wo sonst die Lobbyzahl stuende, in Warnfarbe;
        # die Zeile selbst ist dann ausgegraut und nicht waehlbar, genau wie bei
        # „Version veraltet" (H2.14).
        if self.status_text:
            right, color = tr(self.status_text), theme.DISABLED
        elif self.ausgelastet:
            right, color = tr("Ausgelastet"), theme.DANGER
        elif self.lobby_max > 0:
            # „8 / 50 Lobbys" sagt zusaetzlich, wie viel Luft noch ist.
            right = tr("{n} / {m} Lobbys").format(n=self.lobby_count, m=self.lobby_max)
            color = theme.TEXT_DIM
        elif self.lobby_count == 0:
            right, color = tr("Keine Lobbys"), theme.TEXT_DIM
        elif self.lobby_count == 1:
            right, color = tr("1 Lobby"), theme.TEXT_DIM
        else:
            right, color = tr("{n} Lobbys").format(n=self.lobby_count), theme.TEXT_DIM
        theme.text(screen, right, theme.LABEL, color,
                   (self.rect.right - 20, self.rect.centery), midright=True,
                   max_w=self.COL_STATUS_W)


class Dialog:
    """Modal Yes/No (or OK/Cancel) box. Owner reads .result after a click/key."""

    def __init__(self, title: str, message: str,
                 buttons: list[tuple[str, str]] | None = None) -> None:
        # buttons: list of (label, action)
        self.title = title
        self.message = message
        self.buttons = buttons or [("OK", "ok"), ("Abbrechen", "cancel")]
        self.result: str | None = None
        self._rects: list[tuple[pygame.Rect, str]] = []
        self.focus = 0

    def handle_event(self, event) -> str | None:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.result = self.buttons[-1][1]
            elif event.key in (pygame.K_LEFT, pygame.K_RIGHT):
                d = -1 if event.key == pygame.K_LEFT else 1
                self.focus = (self.focus + d) % len(self.buttons)
            elif event.key == pygame.K_RETURN:
                self.result = self.buttons[self.focus][1]
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for rect, action in self._rects:
                if rect.collidepoint(event.pos):
                    self.result = action
        return self.result

    def draw(self, screen) -> None:
        w, h = screen.get_size()
        overlay = pygame.Surface((w, h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        screen.blit(overlay, (0, 0))
        n = len(self.buttons)
        bw_btn, bh_btn, gap = 190, 52, 24
        total = n * bw_btn + (n - 1) * gap
        # Widen the box so the buttons never touch the side edges (40px margin
        # each side); a 2-button dialog keeps the original 620px width.
        bw = max(620, total + 80)
        
        # Word wrap self.message by pixel width
        max_msg_w = bw - 80
        words = tr(self.message).split(" ")
        lines = []
        current_line = []
        f = theme.font(theme.BODY)
        for word in words:
            subwords = word.split("\n")
            for idx, sw in enumerate(subwords):
                if idx > 0:
                    lines.append(" ".join(current_line))
                    current_line = []
                test_line = current_line + [sw]
                test_w, _ = f.size(" ".join(test_line))
                if test_w > max_msg_w and current_line:
                    lines.append(" ".join(current_line))
                    current_line = [sw]
                else:
                    current_line.append(sw)
        if current_line:
            lines.append(" ".join(current_line))
            
        bh = 260 + max(0, len(lines) - 2) * 24
        x, y = w // 2 - bw // 2, h // 2 - bh // 2
        box = pygame.Rect(x, y, bw, bh)
        theme.panel(screen, box, alpha=245, border=theme.ACCENT, fill=(26, 28, 36))
        theme.text(screen, tr(self.title), theme.HEADER, theme.ACCENT, (x + bw // 2, y + 30), midtop=True)
        
        curr_y = y + 100
        for line in lines:
            theme.text(screen, line, theme.BODY, theme.TEXT_DIM, (x + bw // 2, curr_y), midtop=True)
            curr_y += 24
            
        self._rects = []
        bx = x + bw // 2 - total // 2
        by = y + bh - bh_btn - 24
        mp = display.mouse_pos()
        for i, (label, action) in enumerate(self.buttons):
            r = pygame.Rect(bx + i * (bw_btn + gap), by, bw_btn, bh_btn)
            self._rects.append((r, action))
            focused = (i == self.focus) or r.collidepoint(mp)
            pygame.draw.rect(screen, (66, 54, 24) if focused else (34, 38, 48), r, border_radius=8)
            pygame.draw.rect(screen, theme.ACCENT if focused else theme.BORDER, r, 2, border_radius=8)
            theme.text(screen, tr(label), theme.BODY, theme.TEXT, r.center, center=True)


class OnScreenKeyboard:
    """Gamepad-driven on-screen keyboard overlay.

    A = Zeichen wählen, B = Schließen, X = Löschen, Y = Leerzeichen, Start = Fertig;
    physische Tastatur tippt direkt.
    """

    def __init__(self, target: TextInput, on_done=None) -> None:
        self.target = target
        self.on_done = on_done
        self.uppercase = True
        self.row = 0
        self.col = 0
        self._cursor_timer = 0.0
        self._rebuild_layout()

    def _rebuild_layout(self) -> None:
        is_upper = self.uppercase or getattr(self.target, "uppercase", False)
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if is_upper else "abcdefghijklmnopqrstuvwxyz"
        
        self.layout = [
            list(letters[0:10]),
            list(letters[10:20]),
            list(letters[20:26]) + ["a/A", "_", "0", "1", "2"],
            ["3", "4", "5", "6", "7", "8", "9", "Leer", "Löschen", "Fertig"]
        ]

    def update(self, dt: float) -> None:
        self._cursor_timer += dt

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Route input event to navigate or input text. Returns True if Done/Escape is pressed."""
        if event.type != pygame.KEYDOWN:
            return False
        synthetic = getattr(event, "synthetic", False)

        if not synthetic:
            # Physical keyboard: printable characters type directly.
            if event.key == pygame.K_BACKSPACE:
                self.target.handle_key(pygame.K_BACKSPACE)
                return False
            if event.key == pygame.K_RETURN:
                if self.on_done:
                    self.on_done()
                return True
            if event.key == pygame.K_ESCAPE:
                return True
            if event.key == pygame.K_LEFT:
                cols = len(self.layout[self.row])
                self.col = (self.col - 1) % cols
                return False
            if event.key == pygame.K_RIGHT:
                cols = len(self.layout[self.row])
                self.col = (self.col + 1) % cols
                return False
            if event.key == pygame.K_UP:
                self.row = (self.row - 1) % len(self.layout)
                self.col = min(self.col, len(self.layout[self.row]) - 1)
                return False
            if event.key == pygame.K_DOWN:
                self.row = (self.row + 1) % len(self.layout)
                self.col = min(self.col, len(self.layout[self.row]) - 1)
                return False
            unicode = event.unicode
            if unicode and len(unicode) == 1 and unicode.isprintable():
                self.target.handle_key(0, unicode)
            return False

        # Synthetic (gamepad) events: console conventions.
        from src.core import gamepad
        pad_button = getattr(event, "pad_button", None)
        if pad_button == gamepad.BTN_A:
            val = self.layout[self.row][self.col]
            if val == "Löschen":
                self.target.handle_key(pygame.K_BACKSPACE)
            elif val == "Leer":
                self.target.handle_key(0, " ")
            elif val == "Fertig":
                if self.on_done:
                    self.on_done()
                return True
            elif val == "a/A":
                if not getattr(self.target, "uppercase", False):
                    self.uppercase = not self.uppercase
                    self._rebuild_layout()
            else:
                self.target.handle_key(0, val)
            return False
        if pad_button == gamepad.BTN_B:
            return True
        if pad_button == gamepad.BTN_X:
            self.target.handle_key(pygame.K_BACKSPACE)
            return False
        if pad_button == gamepad.BTN_Y:
            self.target.handle_key(0, " ")
            return False
        if pad_button == gamepad.BTN_START:
            if self.on_done:
                self.on_done()
            return True
        if pad_button is None:
            if event.key == pygame.K_LEFT:
                cols = len(self.layout[self.row])
                self.col = (self.col - 1) % cols
            elif event.key == pygame.K_RIGHT:
                cols = len(self.layout[self.row])
                self.col = (self.col + 1) % cols
            elif event.key == pygame.K_UP:
                self.row = (self.row - 1) % len(self.layout)
                self.col = min(self.col, len(self.layout[self.row]) - 1)
            elif event.key == pygame.K_DOWN:
                self.row = (self.row + 1) % len(self.layout)
                self.col = min(self.col, len(self.layout[self.row]) - 1)
            return False
        return False

    def draw(self, screen: pygame.Surface) -> None:
        w, h = screen.get_size()
        panel_w = 720
        panel_h = 240
        panel_x = w // 2 - panel_w // 2
        panel_y = h - panel_h - 40
        rect = pygame.Rect(panel_x, panel_y, panel_w, panel_h)

        # Translucent background panel
        surf = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        surf.fill((10, 10, 15, 235))
        pygame.draw.rect(surf, theme.ACCENT, (0, 0, panel_w, panel_h), 2, border_radius=12)
        screen.blit(surf, rect.topleft)

        r_h = panel_h // len(self.layout)
        for r_idx, r in enumerate(self.layout):
            c_w = panel_w // len(r)
            for c_idx, val in enumerate(r):
                kx = panel_x + c_idx * c_w
                ky = panel_y + r_idx * r_h
                k_rect = pygame.Rect(kx + 4, ky + 4, c_w - 8, r_h - 8)

                disabled = (val == "a/A" and getattr(self.target, "uppercase", False))
                selected = (r_idx == self.row and c_idx == self.col) and not disabled
                if disabled:
                    bg_color = (20, 22, 28)
                    text_color = (80, 80, 90)
                elif selected:
                    bg_color = (255, 160, 0)
                    text_color = (15, 15, 20)
                else:
                    bg_color = (35, 38, 48)
                    text_color = (220, 220, 230)

                pygame.draw.rect(screen, bg_color, k_rect, border_radius=6)
                if selected:
                    pygame.draw.rect(screen, (255, 220, 100), k_rect, 2, border_radius=6)
                elif disabled:
                    pygame.draw.rect(screen, (45, 48, 58), k_rect, 1, border_radius=6)

                lbl = theme.font(theme.LABEL).render(val, True, text_color)
                screen.blit(lbl, lbl.get_rect(center=k_rect.center))
