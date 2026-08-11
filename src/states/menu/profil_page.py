"""Profilseite — Statistik und Erfolge (Releaseplan E1 / E1a, E5 Schritt 3).

Aufbau **Variante B, Kennzahlenband** (gewählt am 02.08.2026): die Zahlen als
Band über der Seite, darunter die Erfolge nach Gruppen in Karten. Jeder Erfolg
hat dort Platz für seine Bedingung — „20 Rennen gefahren" statt nur eines
Namens, den niemand einordnen kann.

Die Seite zeigt nur, sie ändert nichts. Erfolge sind eine reine Funktion der
Statistik (:func:`statistik.erreicht`), es gibt also keinen Zustand, der hier
verstellt werden könnte.

**Nur das eigene Profil.** Erfolge stehen nirgendwo sonst — nicht in der Lobby,
nicht in der Ergebnisliste. Das ist dieselbe Linie, die mit dem Streichen der
Titel (E3) gezogen wurde: nach außen gibt es nichts zu tragen.
"""
from __future__ import annotations

import pygame

from src.core import profile, statistik
from src.core.i18n import tr
from src.states.menu.page import Page
from src.ui import theme

#: Höhe des Kennzahlenbands über den Karten.
KOPF_H = 132
#: Spalten der Kartenfläche.
SPALTEN = 3
LUECKE = 16
#: Höhe einer Erfolgszeile in einer Karte.
ZEILE_H = 52

#: Welche Erfolgsgruppe in welcher Spalte steht, von oben nach unten (Wunsch vom
#: 04.08.2026). Die dritte Spalte bleibt frei — sie gehört den Bestzeiten.
#:
#: Die Namen sind die Gruppennamen aus ``statistik.ERFOLGE``. Steht dort eine
#: Gruppe, die hier fehlt, landet sie in der kürzeren der beiden Spalten; ein
#: Erfolg fällt also nie unter den Tisch, weil jemand das Nachtragen vergisst.
SPALTEN_PLAN: tuple[tuple[str, ...], ...] = (
    ("Menge", "Erkunden"),
    ("Können", "Online", "Vollständigkeit"),
)
#: Spalte, die allein den Bestzeiten gehört.
BEST_SPALTE = 2


class ProfilPage(Page):
    #: Das Kennzahlenband ist über die ganze Breite belegt — Name und
    #: Fortschritt links, die sechs Zahlen rechts. Der Zurück-Knopf bekommt
    #: deshalb die oberste Zeile für sich, ganz oben und ohne Rand.
    ZURUECK_VERSATZ = (40, 0)


    def enter(self, shell, **kwargs) -> None:
        self.shell = shell
        self.scroll = 0
        self._inhalt_h = 0
        #: Hoehe der sichtbaren Karten-Flaeche. Wird beim Zeichnen auf den
        #: echten Wert gesetzt — **hier** aber schon einmal belegt, weil
        #: ``_blaettern`` sie liest und Ereignisse vor dem ersten Zeichnen
        #: eintreffen: die Schleife verarbeitet erst, dann malt sie. Wer diese
        #: Seite mit einer schon rollenden Radbewegung oeffnet, traf sonst auf
        #: ``AttributeError: 'ProfilPage' object has no attribute
        #: '_sichtbar_h'``. Null ist der richtige Anfangswert: ohne bekannte
        #: Sichthoehe gibt es nichts zu rollen, und beim ersten Bild stimmt sie.
        #: Gefunden am 07.08.2026 von tests/test_affentest.py, Schritt 85.
        self._sichtbar_h = 0
        #: Momentaufnahme beim Betreten. Die Statistik ändert sich nur im
        #: Rennen, und ein Neurechnen je Bild wäre Arbeit ohne Ergebnis.
        self._werte = dict(statistik.werte())
        self._offen = statistik.erreicht(self._werte)

    # ------------------------------------------------------------------
    # Daten
    # ------------------------------------------------------------------
    def _gruppen(self) -> list[tuple[str, list]]:
        """Erfolge nach Gruppe, Reihenfolge wie in ``statistik.ERFOLGE``."""
        aus: list[tuple[str, list]] = []
        for eintrag in statistik.ERFOLGE:
            gruppe = eintrag[1]
            if not aus or aus[-1][0] != gruppe:
                aus.append((gruppe, []))
            aus[-1][1].append(eintrag)
        return aus

    def _kennzahlen(self) -> list[tuple[str, str]]:
        w = self._werte
        return [
            (tr("Rennen"), str(int(w.get("rennen", 0)))),
            (tr("Siege"), str(int(w.get("siege", 0)))),
            (tr("Podeste"), str(int(w.get("podeste", 0)))),
            (tr("Grand Prix"), str(int(w.get("gp_siege", 0)))),
            (tr("Strecke"), f"{float(w.get('meter', 0.0)) / 1000:.0f} km"),
            (tr("Zeit am Steuer"), _zeit(float(w.get("spielzeit_s", 0.0)))),
        ]

    def _bestzeiten(self) -> list[tuple[str, float | None, bool]]:
        """Jede verfügbare Strecke mit ihrer Bestzeit — ``None``, wenn keine.

        Gewünscht im Playtest am 03.08.2026: „Im Profil sollen die Rundenzeiten
        für alle verfügbaren Strecken angezeigt werden." Vorher standen nur die
        gefahrenen da, und damit fehlte gerade die Auskunft, die man sucht — wo
        noch keine Zeit steht.

        Reihenfolge wie in der Streckenauswahl (``paths.strecken()``), nicht
        alphabetisch: das ist die Reihenfolge, die der Spieler kennt. Zeiten zu
        Strecken, die es nicht mehr gibt, hängen hinten dran — eine über Wochen
        gefahrene Bestzeit verschwindet nicht, nur weil eine Datei gelöscht wurde.

        Seit dem 05.08.2026: Mit dem ``eigen``-Flag, um selbst erstellte Strecken
        zu kennzeichnen (Wunsch Playtest 05.08.2026).
        """
        gefahren = getattr(profile.current(), "best_laps", {}) or {}
        gefahren = {str(k): float(v) for k, v in gefahren.items()
                    if isinstance(v, (int, float)) and v > 0}

        aus: list[tuple[str, float | None, bool]] = []
        gesehen: set[str] = set()
        for schluessel, pfad, eigen in self._strecken():
            # Der Zeitschlüssel ist der Dateiname ohne Endung — race_state legt
            # ihn so ab, auch für eigene Strecken (dort ohne "custom/").
            stamm = str(schluessel).rsplit("/", 1)[-1]
            gesehen.add(stamm)
            aus.append((_anzeigename(pfad, stamm), gefahren.get(stamm), eigen))
        for stamm in sorted(k for k in gefahren if k not in gesehen):
            aus.append((_streckenname(stamm), gefahren[stamm], False))
        return aus

    @staticmethod
    def _strecken() -> list:
        """Getrennt, damit ein Test die Streckenliste vorgeben kann."""
        from src.core import paths
        return paths.strecken()

    # ------------------------------------------------------------------
    # Bedienung
    # ------------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> bool | None:
        """Blättern, sonst nichts. Alles andere gehört der Shell — vor allem
        ESC, das eine Ebene hochgeht."""
        if self.zurueck_geklickt(event):
            return True
        schritt = 60
        if event.type == pygame.MOUSEWHEEL:
            self._blaettern(-event.y * schritt)
            return True
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_DOWN, pygame.K_s):
                self._blaettern(schritt)
                return True
            if event.key in (pygame.K_UP, pygame.K_w):
                self._blaettern(-schritt)
                return True
            if event.key == pygame.K_PAGEDOWN:
                self._blaettern(4 * schritt)
                return True
            if event.key == pygame.K_PAGEUP:
                self._blaettern(-4 * schritt)
                return True
        return None

    def _blaettern(self, d: int) -> None:
        grenze = max(0, self._inhalt_h - self._sichtbar_h)
        self.scroll = max(0, min(grenze, self.scroll + d))

    # ------------------------------------------------------------------
    # Zeichnen
    # ------------------------------------------------------------------
    def draw(self, screen: pygame.Surface, area: pygame.Rect) -> None:
        # Der Zurück-Knopf bekommt die oberste Zeile für sich. Das Kennzahlenband
        # ist über die ganze Breite belegt — Name und Fortschritt links, die sechs
        # Zahlen rechts —, also gibt es darin keinen Platz, und das Band rückt
        # nach unten. Die Karten darunter scrollen; sie verlieren Sicht, nichts
        # anderes.
        knopf = self.zurueck_zeichnen(screen, area)
        kopf = pygame.Rect(area.x + 40, knopf.bottom + 4, area.width - 80, KOPF_H)
        self._kopf_zeichnen(screen, kopf)

        # Der Fuß rückt näher heran (28 statt 40): der Knopf kostet eine Zeile
        # der Bestzeitenliste, und die war der Grund, warum die Spalte überhaupt
        # freigeräumt wurde (Wunsch vom 03.08.2026). Was zu holen war, ist geholt.
        flaeche = pygame.Rect(area.x + 40, kopf.bottom + 16,
                              area.width - 80, area.bottom - kopf.bottom - 44)
        self._sichtbar_h = flaeche.height
        self._karten_zeichnen(screen, flaeche)

    def _kopf_zeichnen(self, screen: pygame.Surface, r: pygame.Rect) -> None:
        _panel(screen, r, alpha=205)
        name = (profile.current().username or tr("Kein Profil")).strip()
        theme.text(screen, name, theme.HEADER, theme.ACCENT, (r.x + 22, r.y + 16))
        gesamt = max(1, len(statistik.ERFOLGE))
        fertig = len(self._offen)
        theme.text(screen, tr("{a} von {b} Erfolgen").format(a=fertig, b=gesamt),
                   theme.SMALL, theme.TEXT_DIM, (r.x + 22, r.y + 74))
        _balken(screen, pygame.Rect(r.x + 22, r.y + 100, 260, 10), fertig / gesamt)

        zahlen = self._kennzahlen()
        bx = r.x + 320
        breite = max(80, (r.right - bx - 20) // len(zahlen))
        for i, (titel, wert) in enumerate(zahlen):
            x = bx + i * breite
            theme.text(screen, titel.upper(), theme.SMALL, theme.TEXT_FAINT,
                       (x, r.y + 26))
            theme.text_fit(screen, wert, theme.HEADER, theme.TEXT,
                           pygame.Rect(x, r.y + 52, breite - 16, 52))
            if i:
                pygame.draw.line(screen, (38, 42, 54), (x - 14, r.y + 24),
                                 (x - 14, r.bottom - 20), 1)

    def _spalten(self) -> list[list[tuple[str, list]]]:
        """Welche Erfolgsgruppe in welcher Spalte steht, von oben nach unten.

        Fest nach :data:`SPALTEN_PLAN` und nicht mehr „in die jeweils kürzeste
        Spalte" (bis 04.08.2026). Die automatische Verteilung war sparsam mit dem
        Platz, aber sie hat die Anordnung dem Zufall der Kartenhöhen überlassen —
        und dabei blieb für die Bestzeiten nur ein Rest am Fuß einer Spalte, in
        dem keine acht Strecken standen. Die Anordnung ist eine Entscheidung,
        keine Optimierung.

        Gruppen, die im Plan fehlen, kommen in die kürzeste geplante Spalte. Eine
        neue Gruppe in ``statistik.ERFOLGE`` darf nicht stillschweigend
        verschwinden, nur weil hier niemand nachgetragen hat.
        """
        vorhanden = dict(self._gruppen())
        aus: list[list[tuple[str, list]]] = []
        for gruppen in SPALTEN_PLAN:
            aus.append([(g, vorhanden.pop(g)) for g in gruppen if g in vorhanden])
        for gruppe, eintraege in list(vorhanden.items()):
            kurz = min(range(len(aus)),
                       key=lambda k: sum(len(e) for _g, e in aus[k]))
            aus[kurz].append((gruppe, eintraege))
        return aus

    def _karten_zeichnen(self, screen: pygame.Surface, flaeche: pygame.Rect) -> None:
        """Erfolge links und mittig, Bestzeiten rechts in einer eigenen Spalte."""
        sb = (flaeche.width - (SPALTEN - 1) * LUECKE) // SPALTEN
        spalte_y = [0] * SPALTEN

        karten: list[tuple[pygame.Rect, str, list]] = []
        for sp, gruppen in enumerate(self._spalten()):
            for gruppe, eintraege in gruppen:
                hoehe = 44 + len(eintraege) * ZEILE_H
                karten.append((pygame.Rect(flaeche.x + sp * (sb + LUECKE),
                                           flaeche.y + spalte_y[sp] - self.scroll,
                                           sb, hoehe), gruppe, eintraege))
                spalte_y[sp] += hoehe + LUECKE

        # Die Bestzeiten haben ihre eigene Spalte. Sie wachsen mit jeder Strecke,
        # die jemand baut — als Rest am Fuß einer Erfolgsspalte war sie nach acht
        # Einträgen voll.
        best = self._bestzeiten()
        best_h = 44 + max(1, len(best)) * 38
        # Solange die Liste ganz ins Bild passt, bleibt sie stehen. Beim Blättern
        # geht es um die Erfolge links und mittig; die Bestzeiten mitzuschieben
        # schnitte sie oben ab, obwohl in ihrer Spalte Platz ist. Läuft sie
        # irgendwann über — genug eigene Strecken —, blättert sie mit, aber nur
        # bis zu ihrem eigenen Ende.
        best_scroll = min(self.scroll, max(0, best_h - flaeche.height))
        best_r = pygame.Rect(flaeche.x + BEST_SPALTE * (sb + LUECKE),
                             flaeche.y + spalte_y[BEST_SPALTE] - best_scroll, sb,
                             best_h)
        spalte_y[BEST_SPALTE] += best_r.height + LUECKE
        # Die Lücke *hinter* der letzten Karte zählt nicht zum Inhalt. Sie tat es
        # bis zum 04.08.2026 und machte die Seite 16 px länger als sie ist — man
        # konnte an ihr Ende blättern und sah dort nichts.
        self._inhalt_h = max((y - LUECKE if y else 0) for y in spalte_y)

        alt = screen.get_clip()
        screen.set_clip(flaeche)
        for r, gruppe, eintraege in karten:
            if r.bottom < flaeche.y or r.y > flaeche.bottom:
                continue
            self._karte(screen, r, gruppe, eintraege)
        if best_r.bottom >= flaeche.y and best_r.y <= flaeche.bottom:
            self._bestzeiten_karte(screen, best_r, best)
        screen.set_clip(alt)

        if self._inhalt_h > flaeche.height:
            _rollbalken(screen, flaeche, self.scroll, self._inhalt_h)

    def _karte(self, screen: pygame.Surface, r: pygame.Rect, gruppe: str,
               eintraege: list) -> None:
        _panel(screen, r)
        theme.text(screen, tr(gruppe).upper(), theme.HINT, theme.ACCENT_DIM,
                   (r.x + 16, r.y + 12))
        y = r.y + 42
        for eintrag in eintraege:
            self._erfolgszeile(screen, pygame.Rect(r.x + 14, y, r.width - 28, 46),
                               eintrag)
            y += ZEILE_H

    def _erfolgszeile(self, screen: pygame.Surface, r: pygame.Rect,
                      eintrag) -> None:
        """Zustand, Name, Bedingung, Fortschritt.

        Der Fortschritt steht als **Zahl** da, nicht nur als Balken: „7 / 20"
        sagt, ob man kurz davor ist; ein halb gefüllter Balken sagt das nicht.
        """
        key, _gruppe, name, text, _q, _z = eintrag
        wert, ziel = statistik.stand(key, self._werte)
        fertig = key in self._offen

        mitte = (r.x + 18, r.centery)
        if fertig:
            pygame.draw.circle(screen, (34, 60, 42), mitte, 13)
            _haken(screen, mitte, 6, theme.SUCCESS)
        else:
            pygame.draw.circle(screen, (30, 33, 44), mitte, 13)
            pygame.draw.circle(screen, (60, 64, 80), mitte, 13, 1)

        nx = r.x + 42
        theme.text_fit(screen, tr(name), theme.LABEL,
                       theme.TEXT if fertig else theme.TEXT_DIM,
                       pygame.Rect(nx, r.y, r.width - 170, 26))
        theme.text_fit(screen, tr(text), theme.SMALL, theme.TEXT_FAINT,
                       pygame.Rect(nx, r.y + 26, r.width - 60, 20))

        if fertig:
            theme.text(screen, tr("erreicht"), theme.SMALL, theme.SUCCESS,
                       (r.right - 8, r.y + 4), topright=True)
        else:
            theme.text(screen, f"{wert} / {ziel}", theme.SMALL, theme.ACCENT_DIM,
                       (r.right - 8, r.y + 4), topright=True)
            _balken(screen, pygame.Rect(r.right - 150, r.y + 26, 142, 6),
                    wert / max(1, ziel), farbe=theme.ACCENT_DIM)

    def _bestzeiten_karte(self, screen: pygame.Surface, r: pygame.Rect,
                          best: list[tuple[str, float | None, bool]]) -> None:
        _panel(screen, r)
        gefahren = sum(1 for _n, t, _e in best if t)
        theme.text(screen, tr("BESTZEITEN"), theme.HINT, theme.ACCENT_DIM,
                   (r.x + 16, r.y + 12))
        theme.text(screen, f"{gefahren} / {len(best)}", theme.HINT,
                   theme.TEXT_FAINT, (r.right - 16, r.y + 12), topright=True)
        if not best:
            theme.text(screen, tr("Keine Strecken gefunden."), theme.SMALL,
                       theme.TEXT_FAINT, (r.x + 16, r.y + 48))
            return
        y = r.y + 44
        for name, zeit_s, eigen in best:
            gefahren = zeit_s is not None
            # Die Name-Box wird um 50 Pixel schmäler gemacht, um Platz für den
            # "(eigene)"-Vermerk zu schaffen. So bleiben auch lange Namen lesbar.
            name_box_width = r.width - 200
            theme.text_fit(screen, name, theme.BODY,
                           theme.TEXT if gefahren else theme.TEXT_DIM,
                           pygame.Rect(r.x + 16, y, name_box_width, 26))
            # Vermerk "(eigene)" hinzufügen, wenn die Strecke selbst erstellt ist
            # (05.08.2026: Wunsch Playtest). Der Vermerk wird nach dem Namen
            # gezeichnet, mit gedämpfter Farbe, um nicht zu strahlen.
            if eigen:
                vermerk_x = r.x + 16 + name_box_width + 6
                theme.text(screen, tr("(eigene)"), theme.SMALL, theme.TEXT_FAINT,
                           (vermerk_x, y))
            # Ein Strich statt einer Null: eine ungefahrene Strecke hat keine
            # Zeit, und „0,000 s" waere eine Bestzeit, die niemand gefahren ist.
            theme.text(screen, f"{zeit_s:.3f} s" if gefahren else "—", theme.BODY,
                       theme.ACCENT if gefahren else theme.TEXT_FAINT,
                       (r.right - 16, y), topright=True)
            y += 38


# ---------------------------------------------------------------------------
# Zeichenhelfer
# ---------------------------------------------------------------------------
def _zeit(sekunden: float) -> str:
    h = int(sekunden // 3600)
    m = int((sekunden % 3600) // 60)
    if h:
        return f"{h} h {m:02d} min"
    return f"{m} min"


def _streckenname(schluessel: str) -> str:
    """Aus einem Streckenschluessel etwas Lesbares machen.

    Gespeichert wird der Schluessel (``custom/mein_kurs``), angezeigt gehoert
    der Name. Eine eigene Namenstabelle waere eine zweite Wahrheit neben den
    Streckendateien; die Umschrift reicht und geht nie kaputt.
    """
    name = schluessel.rsplit("/", 1)[-1]
    if name.endswith(".json"):
        name = name[:-5]
    return name.replace("_", " ").strip().capitalize() or schluessel


#: Gelesene Streckennamen, Pfad -> Name. Die Profilseite fragt sie beim Betreten
#: ab; achtmal eine kleine JSON zu lesen ist billig, es je Bild zu tun wäre es
#: nicht.
_namen_cache: dict[str, str] = {}


def _anzeigename(pfad, stamm: str) -> str:
    """Der Name aus der Streckendatei, sonst der umgeschriebene Schlüssel.

    Aus der Datei, damit im Profil steht, was auch in der Streckenauswahl steht.
    Unterstriche werden ersetzt: eine selbst gebaute ``Strecke_1`` heißt dort
    „Strecke 1" und soll hier nicht anders heißen.
    """
    p = str(pfad)
    if p not in _namen_cache:
        name = ""
        try:
            import json
            with open(p, encoding="utf-8") as fh:
                name = str(json.load(fh).get("name", "")).strip()
        except (OSError, ValueError, AttributeError):
            name = ""
        _namen_cache[p] = name.replace("_", " ").strip()
    return _namen_cache[p] or _streckenname(stamm)


def _panel(screen: pygame.Surface, r: pygame.Rect, *, alpha: int = 195) -> None:
    flaeche = pygame.Surface(r.size, pygame.SRCALPHA)
    flaeche.fill((10, 12, 22, alpha))
    screen.blit(flaeche, r.topleft)
    pygame.draw.rect(screen, (46, 50, 62), r, 1, border_radius=6)


def _balken(screen: pygame.Surface, r: pygame.Rect, anteil: float,
            *, farbe=None) -> None:
    radius = max(1, r.height // 2)
    pygame.draw.rect(screen, (28, 31, 40), r, border_radius=radius)
    pygame.draw.rect(screen, (50, 54, 68), r, 1, border_radius=radius)
    breit = int(r.width * max(0.0, min(1.0, anteil)))
    if breit > 2:
        pygame.draw.rect(screen, farbe or theme.ACCENT,
                         (r.x, r.y, breit, r.height), border_radius=radius)


def _haken(screen: pygame.Surface, mitte, groesse: float, farbe) -> None:
    """Erledigt-Zeichen, gezeichnet statt getippt.

    Ein Haken als Schriftzeichen fehlt in der mitgelieferten Schrift und käme
    als leerer Kasten heraus — dieselbe Falle wie bei den Pfeilen in Block D.
    """
    x, y = mitte
    g = groesse
    pygame.draw.lines(screen, farbe, False,
                      [(x - g, y), (x - g * 0.25, y + g * 0.7),
                       (x + g, y - g * 0.8)], 3)


def _rollbalken(screen: pygame.Surface, flaeche: pygame.Rect, scroll: int,
                inhalt: int) -> None:
    """Zeigt, dass unten noch etwas kommt. Ohne ihn sieht eine abgeschnittene
    Kartenspalte aus wie das Ende der Liste."""
    bahn = pygame.Rect(flaeche.right - 6, flaeche.y, 4, flaeche.height)
    pygame.draw.rect(screen, (26, 29, 38), bahn, border_radius=2)
    anteil = flaeche.height / max(1, inhalt)
    hoehe = max(30, int(flaeche.height * anteil))
    grenze = max(1, inhalt - flaeche.height)
    y = flaeche.y + int((flaeche.height - hoehe) * min(1.0, scroll / grenze))
    pygame.draw.rect(screen, theme.ACCENT_DIM, (bahn.x, y, bahn.width, hoehe),
                     border_radius=2)
