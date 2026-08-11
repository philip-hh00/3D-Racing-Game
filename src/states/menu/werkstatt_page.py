"""Werkstatt — Lackierung je Fahrzeug waehlen.

Aufteilung „Auto zuerst" (Releaseplan D4): das Fahrzeug nimmt zwei Drittel der
Flaeche, die Flotte laeuft als Streifen darunter, rechts eine Schiene mit Finish
und Grundfarben.

Bedient wird ausschliesslich ueber **sichtbare Schaltflaechen** — Stepper fuer
das Finish, Klick auf Farbfeld und Fahrzeugkachel, Pfeilknoepfe fuers Drehen und
Blaettern. Es gibt bewusst keine Fusszeile mit Tastenhinweisen; Tastatur und
Controller laufen ueber die Fokus-Verwaltung.

Ein Fallstrick, der Zeit gekostet hat: die gebuendelte Schrift kennt
``↺ ↻ ◀ ▶ ✓ √ ★`` **nicht** und zeichnet leere Kaestchen. Benutzbar sind
``‹ › « » ● ▲ ▼ ► ♦ × →`` — die Drehknoepfe tragen deshalb ``‹ ›`` mit der
Beschriftung „DREHEN" darueber. Nachgehalten wird das in
``tests/test_schriftzeichen.py``; ``√`` stand hier bis zum 04.08.2026 in der
Liste der benutzbaren Zeichen und war selbst ein leeres Kaestchen.
"""
from __future__ import annotations

import math

import pygame

from src.core import display, lack, profile
from src.core.i18n import tr
from src.entities.vehicle_factory import VehicleFactory
from src.states.menu.page import Page
from src.ui import theme
from src.ui.focus import FocusGroup
from src.ui.widgets import Button, Stepper

#: Sichtbare Kacheln im Flottenstreifen.
KACHELN = 7


class _Feld:
    """Eine gezeichnete Flaeche, die auch der Fokus erreichen soll.

    Farbfelder und Fahrzeugkacheln sind keine Knoepfe — sie werden von Hand
    gezeichnet, und ihre Lage steht erst dabei fest. Fuer die Fokusgruppe
    braucht es trotzdem etwas mit ``rect``, ``focusable`` und ``activate``;
    genau das ist diese Huelle und sonst nichts. Das Zeichnen traegt die Lage
    nach (``WerkstattPage._felder_nachfuehren``).

    Damit erledigt sich die Richtungsfrage von selbst: ``FocusGroup._move_spatial``
    sucht das raeumlich naechste Element, und wenn die Kacheln unten liegen,
    fuehrt Steuerkreuz-Runter auch dorthin — gemeldet am 05.08.2026 („wenn ich
    nach unten gehe möchte ich auch nach unten zu den Fahrzeugen kommen und
    nicht nach rechts zum Lack").
    """

    #: Kein Bearbeitungsmodus: ein Feld hat einen Wert und keine Reihe, A loest
    #: es direkt aus. Die Stepper-Regel („erst A, dann links/rechts") bleibt
    #: davon unberuehrt — sie gilt fuer Stepper.
    bearbeitbar = False

    def __init__(self, action: str) -> None:
        self.action = action
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.focusable = False
        self.enabled = True

    def hit(self, pos) -> bool:
        return bool(self.focusable and self.rect.collidepoint(pos))

    def activate(self) -> str:
        return self.action

    def draw(self, screen) -> None:
        """Zeichnen tut die Seite selbst — hier ist bewusst nichts zu tun."""

#: Kacheln je Rastung des Mausrads. Eine ganze Seite je Raste fuehlt sich wie
#: Springen an — gemeldet am 04.08.2026 als „Scrollen der Fahrzeuge wirkt
#: unnatuerlich".
RAD_WEITE = 2.0

#: Wie schnell der Streifen seinem Ziel folgt (1/s im Exponenten). 14 heisst:
#: nach ~0,2 s ist die Bewegung praktisch fertig. Gerechnet wird mit dem
#: gemessenen Zeitschritt, damit es bei 30 wie bei 240 Bildern gleich laeuft.
GLEITEN = 14.0


def _ausgegraut(rgb) -> tuple[int, int, int]:
    """Eine Farbe fuer ein gesperrtes Feld: sichtbar, aber sichtbar nicht dran.

    Ein Rest Farbe bleibt stehen (§E2: *sichtbar und ausgegraut*) — wer alle
    zwoelf Felder als graue Kaesten sieht, weiss nicht mehr, was ihn erwartet.
    """
    r, g, b = (int(k) for k in rgb[:3])
    grau = 0.299 * r + 0.587 * g + 0.114 * b
    return tuple(max(0, min(255, int((0.45 * k + 0.55 * grau) * 0.55 + 14)))
                 for k in (r, g, b))


class WerkstattPage(Page):
    title = "WERKSTATT"

    def __init__(self) -> None:
        self.shell = None
        self.fahrzeuge: list[str] = []
        self.index = 0
        #: Ist- und Sollstand des Flottenstreifens, in Kacheln (auch krumm).
        #: Getrennt, weil ``update`` den Iststand dem Sollstand nachfuehrt.
        self.scroll = 0.0
        self._ziel_scroll = 0.0
        self.finish_index = 0
        self.farb_index = 0
        self.winkel = 0.0
        self._gruppe = FocusGroup([])
        self._finish_stepper: Stepper | None = None
        self._knopf_zurueck: Button | None = None
        self._knopf_ansicht: Button | None = None
        self._knopf_werkslack: Button | None = None
        self._knopf_speichern: Button | None = None
        self._farb_rects: list[tuple[int, pygame.Rect]] = []
        self._kachel_rects: list[tuple[int, pygame.Rect]] = []
        #: Fokuselemente zu den gezeichneten Flaechen; gefuellt in _widgets_bauen.
        self._farb_felder: list[_Feld] = []
        self._kachel_felder: list[_Feld] = []
        self._dreh_rects: tuple[pygame.Rect, pygame.Rect] | None = None
        self._blatt_rects: tuple[pygame.Rect, pygame.Rect] | None = None
        self._leiste_rect: pygame.Rect | None = None
        self._zieht_leiste = False
        #: Die Meldung in zwei Teilen: was los ist, und wie weit man ist. Getrennt
        #: gehalten, weil sie in der Schiene zweizeilig steht — 440 px lassen den
        #: ganzen Satz sonst auf Winzschrift zusammenschrumpfen. ``_meldung``
        #: liest beide Teile in einer Zeile zusammen.
        self._grund = ""
        self._stand = ""
        #: Was im Profil steht. Alles davor ist Vorschau: seit dem 04.08.2026
        #: uebernimmt erst „Speichern" (gemeldet: „Button zum Speichern fehlt,
        #: vor dem Speichern sollen die Aenderungen auch nicht uebernommen
        #: werden").
        self._gespeichert = lack.WERK
        self._dialog = None
        self._dialog_danach = None
        #: Wohin „Zurueck" fuehrt: ``(Zustandsname, kwargs)``. Der Kurzweg aus
        #: der Fahrzeugauswahl setzt das, damit man genau dort landet, wo man
        #: hergekommen ist — mit unveraenderter Fahrzeug- und Streckenwahl.
        #: None heisst: normale Menueseite, ESC geht eine Ebene hoch.
        self.rueckweg: tuple[str, dict] | None = None

    # ------------------------------------------------------------------
    def enter(self, shell, **kwargs) -> None:
        self.shell = shell
        if not VehicleFactory.get_available_configs():
            VehicleFactory.load_all_configs("data/vehicles")
        from src.core.race_setup import CLASSES
        self.fahrzeuge = [k for k in CLASSES["Alle"] if VehicleFactory.get_config(k)]
        self.rueckweg = kwargs.get("rueckweg") or self.rueckweg

        wunsch = kwargs.get("vehicle_config")
        if wunsch in self.fahrzeuge:
            self.index = self.fahrzeuge.index(wunsch)
        self.index = max(0, min(self.index, max(0, len(self.fahrzeuge) - 1)))
        self._sichtbar_machen(sofort=True)
        self._aus_profil_lesen()
        self._widgets_bauen()

    @property
    def _meldung(self) -> str:
        """Meldung und Fortschritt in einer Zeile — fuer Tests und Berichte.

        Gezeichnet wird beides getrennt (siehe ``_grund``/``_stand``); als ein
        Text gelesen ist es aber genau die eine Aussage, die die Seite macht.
        """
        return "  ".join(t for t in (self._grund, self._stand) if t)

    def _key(self) -> str:
        return self.fahrzeuge[self.index] if self.fahrzeuge else ""

    def _cfg(self):
        return VehicleFactory.get_config(self._key())

    def _aus_profil_lesen(self) -> None:
        """Stepper und Farbfeld auf die gespeicherte Wahl stellen."""
        kenn = lack.normalisiere(profile.current().paint(self._key()))
        teile = lack.zerlege(kenn)
        finish_keys = [f["key"] for f in lack.finishes()]
        farb_keys = [f["key"] for f in lack.farben()]
        if teile is None:
            # Werkslack: Stepper steht auf dem Werkslack-Eintrag (Index 0).
            self.finish_index = 0
            self.farb_index = min(self.farb_index, max(0, len(farb_keys) - 1))
        else:
            fin, far = teile
            self.finish_index = (finish_keys.index(fin) + 1) if fin in finish_keys else 0
            self.farb_index = farb_keys.index(far) if far in farb_keys else 0
        self._farb_index_richten()
        self._gespeichert = kenn

    # -- Finish-Auswahl: Werkslack ist Eintrag 0, dann die Finishes ------
    def _finish_namen(self) -> list[str]:
        return [tr("Werkslack")] + [tr(f["name"]) for f in lack.finishes()]

    def _kennung(self) -> str:
        """Kennung aus dem aktuellen Stand von Finish- und Farbwahl."""
        if self.finish_index <= 0:
            return lack.WERK
        finishes = lack.finishes()
        farben = lack.farben()
        if not finishes or not farben:
            return lack.WERK
        fin = finishes[min(self.finish_index - 1, len(finishes) - 1)]
        far = farben[min(self.farb_index, len(farben) - 1)]
        return lack.kennung(fin["key"], far["key"])

    def _aktuelles_finish(self) -> dict | None:
        if self.finish_index <= 0:
            return None
        finishes = lack.finishes()
        return finishes[min(self.finish_index - 1, len(finishes) - 1)] if finishes else None

    def _frei(self, farb_key: str) -> bool:
        """Ob diese Grundfarbe im **derzeit gewaehlten Finish** benutzbar ist.

        Die Staffelung ist je Farbe verschieden (drei Farben frueh, alle zwoelf
        spaeter, §E2) — die Frage laesst sich also nicht fuers Finish im Ganzen
        beantworten, nur Feld fuer Feld. Steht der Stepper auf Werkslack, wuerde
        ein Klick auf ein Feld nach Standard springen; gefragt wird deshalb
        genau danach.
        """
        finishes = lack.finishes()
        if not finishes:
            return True
        i = min(max(self.finish_index - 1, 0), len(finishes) - 1)
        return lack.ist_freigeschaltet(lack.kennung(finishes[i]["key"], farb_key))

    def _sichtbare_farben(self) -> list[tuple[int, dict]]:
        """Die Felder, die im gewaehlten Finish gezeigt werden — mit ihrem Index
        in der **vollen** Palette.

        Der Index bleibt der der ganzen Palette, damit ``farb_index`` immer
        dieselbe Farbe meint, egal welches Finish gerade steht. Neon laesst die
        unbunten Felder weg (§04.08.2026: „Feld ganz ausblenden"), und ein
        weggelassenes Feld darf die Nummern der anderen nicht verschieben.
        """
        alle = list(enumerate(lack.farben()))
        fin = self._aktuelles_finish()
        if fin is None:
            return alle          # Werkslack zeigt die ganze Palette
        erlaubt = {f["key"] for f in lack.farben_fuer(fin["key"])}
        return [(i, f) for i, f in alle if f["key"] in erlaubt]

    def _farb_index_richten(self) -> None:
        """Nach einem Finishwechsel auf ein Feld zeigen, das es noch gibt.

        Auf das **naechstgelegene**: wer von Metallic Anthrazit auf Neon wechselt,
        soll nicht am anderen Ende der Palette landen.
        """
        sichtbar = [i for i, _f in self._sichtbare_farben()]
        if sichtbar and self.farb_index not in sichtbar:
            self.farb_index = min(sichtbar, key=lambda i: abs(i - self.farb_index))

    def _farbe_waehlen(self, i: int) -> None:
        """Eine Lackfarbe auftragen — von der Maus wie vom Controller.

        An einer Stelle, weil beide Wege dasselbe tun muessen: bis zum
        05.08.2026 gab es diesen Weg nur fuer die Maus, und der Controller kam
        gar nicht erst an die Farbfelder heran.
        """
        self.farb_index = i
        if self.finish_index <= 0:   # aus dem Werkslack heraus
            self.finish_index = 1
            if self._finish_stepper is not None:
                self._finish_stepper.index = 1
        self._uebernehmen()
        # Der abweisende Laut kommt von der Fokusgruppe: ein gesperrtes Feld ist
        # nicht fokussierbar, und sie quittiert einen Klick darauf selbst. Hier
        # noch einmal zu klingen hiesse, denselben Klick zweimal zu beantworten.

    def _widgets_bauen(self) -> None:
        self._finish_stepper = Stepper(pygame.Rect(0, 0, 10, 10), "",
                                       self._finish_namen(), self.finish_index,
                                       action="finish")
        # Derselbe Knopf wie auf jeder anderen Seite (``Page.zurueck_knopf``) —
        # hier zusaetzlich in der Fokusgruppe, damit ihn auch Tastatur und
        # Controller erreichen.
        self._knopf_zurueck = self.zurueck_knopf()
        self._knopf_zurueck.action = "zurueck"
        self._knopf_ansicht = Button(pygame.Rect(0, 0, 10, 10), "Ansicht zurück",
                                     "ansicht", style="secondary",
                                     hint="Das Fahrzeug steht schon so.")
        self._knopf_werkslack = Button(pygame.Rect(0, 0, 10, 10), "Werkslack",
                                       "werkslack", style="secondary")
        self._knopf_speichern = Button(pygame.Rect(0, 0, 10, 10), "Speichern",
                                       "speichern",
                                       hint="Nichts geändert.")
        # Farbfelder und Fahrzeugkacheln gehoeren in die Fokusgruppe, sonst
        # erreicht sie nur die Maus — gemeldet am 05.08.2026: „Mit
        # Controllersteuerung nicht möglich die Farben zu erreichen … Auch die
        # Fahrzeuge können mit dem Controller nicht erreicht werden."
        #
        # Je ein festes Element pro Farbe und pro Fahrzeug, nicht je Bild neu:
        # ``set_widgets`` setzt den Fokus zurueck. Wo sie liegen und ob sie
        # gerade sichtbar sind, traegt das Zeichnen nach (``_felder_nachfuehren``).
        self._farb_felder = [_Feld(f"farbe_{i}") for i in range(len(lack.farben()))]
        self._kachel_felder = [_Feld(f"kachel_{i}") for i in range(len(self.fahrzeuge))]
        self._gruppe.set_widgets([
            self._knopf_zurueck, self._finish_stepper, self._knopf_ansicht,
            self._knopf_werkslack, self._knopf_speichern,
            *self._farb_felder, *self._kachel_felder,
        ])
        self._knoepfe_richten()

    def _felder_nachfuehren(self, rects: list[tuple[int, pygame.Rect]],
                            felder: list,
                            gesperrt: set[int] | None = None) -> None:
        """Die gezeichneten Flaechen an die Fokuselemente melden.

        Wo ein Farbfeld oder eine Kachel liegt, steht erst nach dem Zeichnen
        fest: die Farbfelder haengen am gewaehlten Finish (Neon zeigt zehn statt
        zwoelf), die Kacheln am Bildlauf. Was gerade nicht gezeichnet wird, ist
        auch nicht fokussierbar — sonst stuende der Fokus auf einer Kachel, die
        niemand sieht.

        *gesperrt* sind Felder, die zwar gezeichnet, aber noch nicht erspielt
        sind. Sie bleiben sichtbar (das ist der Anreiz) und anklickbar, aber
        **nicht** fokussierbar — dieselbe Regel wie bei gesperrten Knoepfen. Am
        Klang haengt das auch: die Fokusgruppe quittiert einen Klick auf etwas
        Gesperrtes selbst mit dem abweisenden Laut, waehrend sie einen Klick auf
        ein freies Feld als ausgeloest meldet. Waeren gesperrte Felder
        fokussierbar, klaenge derselbe Klick zweimal.
        """
        gesperrt = gesperrt or set()
        for feld in felder:
            feld.focusable = False
            feld.enabled = True
        for i, r in rects:
            if 0 <= i < len(felder):
                felder[i].rect = pygame.Rect(r)
                felder[i].focusable = i not in gesperrt
                felder[i].enabled = i not in gesperrt

    def _knoepfe_richten(self) -> None:
        """Was gerade geht und was nicht — an den **vorhandenen** Knoepfen.

        Nicht durch Neubauen: ``set_widgets`` setzt den Fokus zurueck, und wer
        gerade mit der Tastatur auf „Speichern" steht, sollte nach dem Speichern
        nicht wieder bei „Zurueck" anfangen.
        """
        for knopf, offen in (
            (self._finish_stepper, lack.lackierbar(self._key())),
            # Gemeldet 04.08.2026: „Button zum reset view soll ausgegraut werden
            # solange das Fahrzeug noch in der Standardrichtung ausgerichtet ist".
            (self._knopf_ansicht, self.winkel != 0.0),
            (self._knopf_werkslack, self._kennung() != lack.WERK),
            (self._knopf_speichern, self._geaendert()),
        ):
            if knopf is None:
                continue
            knopf.enabled = offen
            knopf.focusable = offen
        self._gruppe.fokus_richten()

    # ------------------------------------------------------------------
    # Auswahl aendern
    # ------------------------------------------------------------------
    def _pruefen(self) -> bool:
        """Ob die gezeigte Wahl benutzbar ist; setzt sonst die Meldung."""
        kenn = self._kennung()
        if kenn != lack.WERK and not lack.ist_freigeschaltet(kenn):
            self._grund = tr("Diese Lackierung ist noch gesperrt.")
            self._stand = lack.fortschritt_text(kenn)
            return False
        self._grund = self._stand = ""
        return True

    def _uebernehmen(self) -> None:
        """Die Wahl uebernehmen — **in die Vorschau**, nicht ins Profil.

        Bis zum 04.08.2026 stand hier der Schreibvorgang: jede Aenderung war
        sofort im Profil, und ein Blick auf eine Lackierung hiess, sie zu
        besitzen. Gemeldet als „Button zum Speichern fehlt, vor dem Speichern
        sollen die Aenderungen auch nicht uebernommen werden". Geschrieben wird
        jetzt nur noch in :meth:`_speichern`.
        """
        self._pruefen()
        self._knoepfe_richten()

    def _geaendert(self) -> bool:
        """Ob die Vorschau vom gespeicherten Stand abweicht."""
        return self._kennung() != self._gespeichert

    def _speichern(self) -> bool:
        """Die Wahl ins Profil schreiben. Der einzige Ort, der das tut."""
        if not self._pruefen():
            return False
        profile.current().set_paint(self._key(), self._kennung())
        self._gespeichert = lack.normalisiere(profile.current().paint(self._key()))
        self._knoepfe_richten()
        return True

    def _fahrzeug_waehlen(self, i: int) -> None:
        if not self.fahrzeuge:
            return
        if self._geaendert() and i % len(self.fahrzeuge) != self.index:
            # Der Wechsel wuerde die Vorschau des alten Fahrzeugs wegwerfen —
            # dieselbe Verlustgefahr wie beim Verlassen, also dieselbe Rueckfrage.
            self._frage_stellen(lambda: self._fahrzeug_wechseln(i))
            return
        self._fahrzeug_wechseln(i)

    def _fahrzeug_wechseln(self, i: int) -> None:
        self.index = i % len(self.fahrzeuge)
        self.winkel = 0.0
        self._grund = self._stand = ""
        self._sichtbar_machen()
        self._aus_profil_lesen()
        if self._finish_stepper is not None:
            self._finish_stepper.index = self.finish_index
        self._knoepfe_richten()

    # -- Flottenstreifen: Ziel setzen, Iststand folgt in update ----------
    def _grenze(self) -> float:
        return float(max(0, len(self.fahrzeuge) - KACHELN))

    def _sichtbar_machen(self, sofort: bool = False) -> None:
        ziel = self._ziel_scroll
        if self.index < ziel:
            ziel = float(self.index)
        elif self.index >= ziel + KACHELN:
            ziel = float(self.index - KACHELN + 1)
        self._ziel_scroll = max(0.0, min(self._grenze(), ziel))
        if sofort:
            self.scroll = self._ziel_scroll

    def _blaettern(self, kacheln: float) -> None:
        """Das **Ziel** verschieben. Den Weg dorthin geht ``update``."""
        self._ziel_scroll = max(0.0, min(self._grenze(),
                                         self._ziel_scroll + kacheln))

    def _leiste_setzen(self, x: int) -> None:
        """Den Streifen an die Stelle unter dem Zeiger schieben (Bildlaufleiste).

        Sofort und ohne Gleiten: beim Ziehen ist der Zeiger der Fuehrende, jede
        Nachlaufzeit fuehlt sich dabei nach Gummiband an.
        """
        r = self._leiste_rect
        if r is None or r.width <= 0 or not self.fahrzeuge:
            return
        anteil = min(1.0, KACHELN / float(len(self.fahrzeuge)))
        daumen = max(24, int(r.width * anteil))
        weg = max(1, r.width - daumen)
        t = (x - r.x - daumen / 2.0) / float(weg)
        self._ziel_scroll = max(0.0, min(self._grenze(), t * self._grenze()))
        self.scroll = self._ziel_scroll

    # ------------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> bool:
        # Die Rueckfrage liegt ueber allem anderen — sonst laesst sich hinter
        # ihr weiterlackieren, und sie fragt am Ende nach dem falschen Stand.
        if self._dialog is not None:
            return self._dialog_ereignis(event)

        aktion = self._gruppe.handle_event(event)
        if aktion == "zurueck":
            self._verlassen()
            return True
        if aktion == "finish":
            self.finish_index = self._finish_stepper.index
            self._farb_index_richten()
            self._uebernehmen()
            return True
        if aktion == "ansicht":
            self._drehen(-self.winkel)
            return True
        if aktion == "werkslack":
            self.finish_index = 0
            if self._finish_stepper is not None:
                self._finish_stepper.index = 0
            self._uebernehmen()
            return True
        if aktion == "speichern":
            self._speichern()
            return True
        if aktion and aktion.startswith("farbe_"):
            self._farbe_waehlen(int(aktion[len("farbe_"):]))
            return True
        if aktion and aktion.startswith("kachel_"):
            # Ueber dieselbe Stelle wie der Mausklick: der Fahrzeugwechsel
            # fragt bei ungespeicherten Aenderungen nach, und das darf am
            # Controller nicht anders sein.
            self._fahrzeug_waehlen(int(aktion[len("kachel_"):]))
            return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._leiste_rect is not None and \
                    self._leiste_rect.inflate(0, 16).collidepoint(event.pos):
                self._zieht_leiste = True
                self._leiste_setzen(event.pos[0])
                return True
            for i, r in self._farb_rects:
                if r.collidepoint(event.pos):
                    self._farbe_waehlen(i)
                    return True
            for i, r in self._kachel_rects:
                if r.collidepoint(event.pos):
                    self._fahrzeug_waehlen(i)
                    return True
            if self._dreh_rects:
                links, rechts = self._dreh_rects
                if links.collidepoint(event.pos):
                    self._drehen(-15.0)
                    return True
                if rechts.collidepoint(event.pos):
                    self._drehen(+15.0)
                    return True
            if self._blatt_rects:
                links, rechts = self._blatt_rects
                if links.collidepoint(event.pos):
                    self._blaettern(-KACHELN)
                    return True
                if rechts.collidepoint(event.pos):
                    self._blaettern(+KACHELN)
                    return True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self._zieht_leiste:
                self._zieht_leiste = False
                return True
        elif event.type == pygame.MOUSEMOTION and self._zieht_leiste:
            self._leiste_setzen(event.pos[0])
            return True
        elif event.type == pygame.MOUSEWHEEL:
            self._blaettern(-RAD_WEITE if event.y > 0 else RAD_WEITE)
            return True
        elif event.type == pygame.KEYDOWN and event.key in (pygame.K_PAGEUP, pygame.K_PAGEDOWN):
            return False          # Tabwechsel gehoert der Shell
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            # ESC und Controller-B nehmen denselben Weg wie „Zurück". Ohne das
            # landete man mit der Taste im Hauptmenue, waehrend der Knopf
            # daneben in die Lobby zurueckfuehrte — zwei Wege fuer dieselbe
            # Absicht (gemeldet 03.08.2026). Die Shell wuerde hier
            # ``pop_page()`` rufen, und der Kurzweg aus der Fahrzeugauswahl hat
            # nichts, was sie abheben koennte.
            self._verlassen()
            return True
        return False

    def _drehen(self, grad: float) -> None:
        """Das gezeigte Auto drehen.

        Der Winkel bleibt in 0…360, damit „steht in der Standardansicht" nach
        einer ganzen Umdrehung wieder wahr ist — sonst waere „Ansicht zurueck"
        ab dem 24. Klick auf ewig freigeschaltet, obwohl das Auto genau so steht
        wie am Anfang.
        """
        self.winkel = (self.winkel + grad) % 360.0
        self._knoepfe_richten()

    # ------------------------------------------------------------------
    # Verlassen und Rueckfrage
    # ------------------------------------------------------------------
    def verlassen_erlaubt(self, weiter) -> bool:
        """Von der Shell gerufen, bevor sie die Seite wegraeumt (Tabklick,
        Bild auf/ab). Mit ungespeicherter Lackierung wird erst gefragt."""
        if not self._geaendert():
            return True
        self._frage_stellen(weiter)
        return False

    def _frage_stellen(self, danach) -> None:
        """Rueckfrage vor dem Verwerfen einer ungespeicherten Lackierung.

        Drei Antworten, weil es drei Absichten gibt: behalten, wegwerfen, oder
        doch hierbleiben. Die Reihenfolge ist Absicht — ESC und Controller-B
        nehmen den **letzten** Knopf, und „Abbrechen" ist die einzige Antwort,
        die nichts kaputtmachen kann.
        """
        from src.ui.widgets import Dialog
        self._dialog = Dialog("Ungespeicherte Änderungen",
                              "Lackierung speichern, bevor du gehst?",
                              [("Speichern", "speichern"),
                               ("Verwerfen", "verwerfen"),
                               ("Abbrechen", "abbrechen")])
        self._dialog_danach = danach

    def _dialog_ereignis(self, event: pygame.event.Event) -> bool:
        antwort = self._dialog.handle_event(event)
        if antwort is None:
            return True
        self._dialog = None
        danach, self._dialog_danach = self._dialog_danach, None
        if antwort == "speichern" and not self._speichern():
            # Gesperrte Lackierung: es gibt nichts zu speichern, und still
            # weitergehen hiesse, die Antwort zu uebergehen. Die Meldung steht
            # jetzt in der Schiene, der Weg bleibt zu.
            return True
        if antwort == "abbrechen":
            return True
        if antwort == "verwerfen":
            self._aus_profil_lesen()
            if self._finish_stepper is not None:
                self._finish_stepper.index = self.finish_index
            self._knoepfe_richten()
        if danach is not None:
            danach()
        return True

    def zurueck(self) -> None:
        """Der Rueckweg dieser Seite — die Schale ruft ihn fuer ESC.

        Heisst genau so, weil die Schale danach fragt: ``zurueck_gehen`` sucht an
        der obersten Seite eine Methode dieses Namens und nimmt sonst den
        Seitenstapel. Die Werkstatt braucht das doppelt — sie hat einen Kurzweg
        zurueck in die Fahrzeugauswahl, und sie fragt vor dem Verwerfen.
        """
        self._verlassen()

    def _verlassen(self) -> None:
        """Zurueck — mit Rueckfrage, wenn etwas ungespeichert ist."""
        if self._geaendert():
            self._frage_stellen(self._weggehen)
            return
        self._weggehen()

    def _weggehen(self) -> None:
        """Eine Menueebene hoch oder auf den Kurzweg.

        Der Kurzweg gibt genau den Zustand zurueck, aus dem er kam. Die
        Fahrzeugauswahl kennt drei Rueckwege (Einzelspieler, lokal, online); die
        Werkstatt entscheidet keinen davon selbst, sie reicht zurueck, was ihr
        uebergeben wurde.
        """
        if self.shell is None:
            return
        if self.rueckweg:
            (ziel, argumente), self.rueckweg = self.rueckweg, None
            # Mit dem Fahrzeug zurueck, das hier zuletzt auf der Buehne stand —
            # nicht mit dem, mit dem man hergekommen ist. Wer in der Werkstatt
            # wechselt, meint den Wechsel (gemeldet 05.08.2026); der Streifen
            # ist eine Auswahl und keine blosse Vorschau.
            argumente = dict(argumente)
            if self._key():
                argumente["vehicle_config"] = self._key()
            self.shell.state_machine.transition(ziel, **argumente)
            return
        self.shell.pop_page()

    def update(self, dt: float) -> None:
        """Den Streifen seinem Ziel nachfuehren.

        Exponentielle Annaeherung statt fester Schrittweite: der Anfang ist
        schnell, das Ende weich, und beides haengt am gemessenen Zeitschritt und
        nicht an der Bildrate.
        """
        rest = self._ziel_scroll - self.scroll
        if rest:
            if abs(rest) < 0.002:
                self.scroll = self._ziel_scroll
            else:
                self.scroll += rest * (1.0 - math.exp(-max(0.0, dt) * GLEITEN))

    # ------------------------------------------------------------------
    # Zeichnen
    # ------------------------------------------------------------------
    def draw(self, screen: pygame.Surface, area: pygame.Rect) -> None:
        if not self.fahrzeuge:
            theme.text(screen, tr("Keine Fahrzeuge gefunden."), theme.BODY,
                       theme.TEXT_DIM, area.center, center=True)
            return

        rand = 40
        zurueck = self.zurueck_zeichnen(screen, area)
        oben = zurueck.bottom + 16
        streifen_h = 190
        buehne = pygame.Rect(area.x + rand, oben,
                             area.width - 2 * rand - 460,
                             area.bottom - oben - streifen_h - 24)
        schiene = pygame.Rect(buehne.right + 20, oben, 440, buehne.height)
        streifen = pygame.Rect(area.x + rand, buehne.bottom + 16,
                               area.width - 2 * rand, streifen_h)

        self._buehne_zeichnen(screen, buehne)
        self._schiene_zeichnen(screen, schiene)
        self._streifen_zeichnen(screen, streifen)
        # Nochmal, damit der Fokusrahmen ueber den Flaechen liegt.
        self._knopf_zeichnen(screen, self._knopf_zurueck)
        if self._dialog is not None:
            self._dialog.draw(screen)

    def _knopf_zeichnen(self, screen: pygame.Surface, knopf: Button) -> None:
        knopf.draw(screen, focused=self._gruppe.focused is knopf)

    # -- Buehne ---------------------------------------------------------
    def _buehne_zeichnen(self, screen: pygame.Surface, r: pygame.Rect) -> None:
        theme.panel(screen, r, alpha=215)
        pygame.draw.rect(screen, (15, 17, 24), r.inflate(-4, -4), border_radius=8)
        for i in range(14):
            t = i / 13.0
            y = int(r.y + r.height * 0.34 + t * t * r.height * 0.6)
            if y < r.bottom - 8:
                pygame.draw.line(screen, (26, 29, 38), (r.x + 20, y), (r.right - 20, y), 1)
        oval = pygame.Rect(0, 0, int(r.width * 0.76), int(r.height * 0.62))
        oval.center = (r.centerx, r.centery + int(r.height * 0.06))
        pygame.draw.ellipse(screen, (20, 23, 31), oval)
        pygame.draw.ellipse(screen, (30, 34, 44), oval, 2)

        cfg = self._cfg()
        kenn = self._kennung()
        bild = lack.sprite(self._key(), cfg.visual_type if cfg else self._key(),
                           kenn, lack.BREITE_VORSCHAU)
        if bild is not None:
            kasten = pygame.Rect(0, 0, int(r.width * 0.72), int(r.height * 0.66))
            kasten.center = (r.centerx, r.centery + 10)
            self._auto_zeichnen(screen, bild, kasten, self.winkel)

        theme.text(screen, tr(cfg.name) if cfg else self._key(), theme.TITLE,
                   theme.TEXT, (r.x + 44, r.y + 26), max_w=r.width - 480)
        fin = self._aktuelles_finish()
        farbe = lack.farben()[min(self.farb_index, len(lack.farben()) - 1)] \
            if lack.farben() else None
        if fin is None or farbe is None:
            theme.text(screen, tr("WERKSLACK"), theme.HEADER, theme.TEXT_DIM,
                       (r.x + 46, r.y + 104))
        else:
            # Die Buehne zeigt auch Gesperrtes — man soll sehen, worauf man
            # hinarbeitet. Damit das nicht wie „schon deins" aussieht, traegt
            # die Zeile dann ein Schloss und blasse Farbe.
            offen = lack.ist_freigeschaltet(kenn)
            zeile = theme.text(
                screen, f"{tr(fin['name']).upper()} · {tr(farbe['name']).upper()}",
                theme.HEADER, farbe["rgb"] if offen else _ausgegraut(farbe["rgb"]),
                (r.x + 46, r.y + 104), max_w=r.width - 480)
            if not offen:
                self._schloss(screen, (zeile.right + 26, zeile.centery - 2), 1.8)

        # Die Meldung („noch gesperrt") stand bis zum 04.08.2026 hier in der
        # Mitte der Buehne — also quer ueber dem Auto und dadurch nur halb
        # lesbar. Sie steht jetzt in der Schiene, direkt unter den Farbfeldern:
        # dort ist der Klick passiert, auf den sie antwortet.

        # Bedienleiste: alles, was am gezeigten Auto passiert.
        dy = r.bottom - 74
        theme.text(screen, tr("DREHEN"), theme.SMALL, theme.TEXT_FAINT, (r.x + 46, dy - 24))
        links = pygame.Rect(r.x + 44, dy, 58, 54)
        rechts = pygame.Rect(r.x + 110, dy, 58, 54)
        self._dreh_rects = (links, rechts)
        self._pfeilknopf(screen, links, "‹")
        self._pfeilknopf(screen, rechts, "›")
        self._knopf_ansicht.rect = pygame.Rect(r.x + 182, dy, 200, 54)
        self._knopf_werkslack.rect = pygame.Rect(r.x + 394, dy, 200, 54)
        self._knopf_speichern.rect = pygame.Rect(r.x + 606, dy, 200, 54)
        for w in (self._knopf_ansicht, self._knopf_werkslack,
                  self._knopf_speichern):
            self._knopf_zeichnen(screen, w)
        if self._geaendert():
            # Der Knopf allein sagt „hier waere etwas zu tun", nicht „sonst ist
            # es weg". Ein Wort daneben schon — und zwar *daneben*: ueber dem
            # Knopf laege es wieder auf dem Auto, und genau das war eine der
            # Meldungen vom 04.08.2026.
            theme.text(screen, tr("nicht gespeichert"), theme.HINT, theme.ACCENT,
                       (self._knopf_speichern.rect.right + 16,
                        self._knopf_speichern.rect.centery), midleft=True,
                       max_w=200)

        if not lack.lackierbar(self._key()):
            theme.text(screen, tr("Für dieses Fahrzeug ist bisher nur der Werkslack abgestimmt."),
                       theme.HINT, theme.TEXT_FAINT, (r.right - 24, dy + 16),
                       topright=True, max_w=r.width - 1100)

    def _auto_zeichnen(self, screen, bild: pygame.Surface, kasten: pygame.Rect,
                       winkel: float) -> None:
        from src.core import gfx
        f = min(kasten.width / bild.get_width(), kasten.height / bild.get_height())
        gr = (max(1, int(bild.get_width() * f)), max(1, int(bild.get_height() * f)))
        img = gfx.scale(bild, gr)
        if winkel:
            img = pygame.transform.rotate(img, winkel)
        schatten = pygame.Surface(img.get_size(), pygame.SRCALPHA)
        pygame.draw.ellipse(schatten, (0, 0, 0, 70),
                            (0, int(img.get_height() * 0.18),
                             img.get_width(), int(img.get_height() * 0.7)))
        screen.blit(schatten, schatten.get_rect(
            center=(kasten.centerx - 8, kasten.centery + 14)))
        screen.blit(img, img.get_rect(center=kasten.center))

    def _pfeilknopf(self, screen, r: pygame.Rect, glyph: str) -> None:
        hover = r.collidepoint(display.mouse_pos())
        pygame.draw.rect(screen, (46, 50, 62) if hover else (32, 36, 46), r, border_radius=8)
        pygame.draw.rect(screen, theme.ACCENT_HOT if hover else theme.BORDER_LIGHT,
                         r, 2, border_radius=8)
        theme.text(screen, glyph, theme.HEADER,
                   theme.ACCENT_HOT if hover else theme.ACCENT, r.center, center=True)

    # -- Schiene --------------------------------------------------------
    def _schiene_zeichnen(self, screen: pygame.Surface, r: pygame.Rect) -> None:
        theme.panel(screen, r, alpha=210)
        stepper = self._finish_stepper
        stepper.rect = pygame.Rect(r.x + 16, r.y + 18, r.width - 32, 58)
        stepper.index = self.finish_index
        stepper.draw(screen, focused=self._gruppe.focused is stepper)

        theme.text(screen, tr("FINISH"), theme.SMALL, theme.TEXT_FAINT,
                   (r.x + 20, r.y + 86))
        # Fortschritt statt nur der Huerde (§E2): „7 / 20 Rennen" sagt, ob man
        # kurz davor ist oder weit weg — „gesperrt" allein sagt das nicht. Die
        # Zahl gilt fuer die *gewaehlte* Farbe, weil die Staffelung je Farbe
        # verschieden ist.
        kenn = self._kennung()
        stand = lack.fortschritt_text(kenn)
        if not stand:
            hinweis, farbton = tr("immer verfügbar"), theme.TEXT_FAINT
        elif lack.ist_freigeschaltet(kenn):
            hinweis, farbton = tr("frei"), theme.TEXT_FAINT
        else:
            hinweis, farbton = stand, theme.ACCENT
        theme.text(screen, hinweis, theme.SMALL, farbton,
                   (r.right - 20, r.y + 86), topright=True, max_w=r.width - 120)

        theme.text(screen, tr("GRUNDFARBE"), theme.LABEL, theme.TEXT_DIM,
                   (r.x + 20, r.y + 120))
        # Die Farbfelder nutzen die Hoehe der Schiene aus. Hier sass bis zum
        # 31.07.2026 ein reservierter, ausgegrauter "TITEL"-Kasten fuer Block E.
        # Titel sind aus Block E gestrichen, also ist der Platzhalter weg: ein
        # Versprechen ohne Termin gehoert nicht ins Spiel.
        self._farb_rects = []
        # Nur die Felder, die im gewaehlten Finish etwas ergeben. Neon laesst
        # Anthrazit und Perlweiss weg (gemeldet 04.08.2026: „Neon Lackierung fuer
        # Weiss, Grautoene und Schwarz ergeben keinen Sinn", entschieden: „Feld
        # ganz ausblenden") — die Reihen ruecken dann einfach nach.
        sichtbar = self._sichtbare_farben()
        spalten, luecke = 3, 14
        bw = (r.width - 40 - (spalten - 1) * luecke) // spalten
        zeilen = max(1, math.ceil(len(sichtbar) / spalten))
        oben = r.y + 158
        # Unten bleiben 96 px frei: eine Zeile fuer den Farbnamen und zwei fuer
        # die Meldung, die bis zum 04.08.2026 quer ueber dem Auto lag.
        rest = (r.bottom - 96) - oben - (zeilen - 1) * luecke
        bh = max(56, min(96, rest // zeilen))
        aktiv_farbe = self.farb_index if self.finish_index > 0 else -1
        for platz, (i, f) in enumerate(sichtbar):
            x = r.x + 20 + (platz % spalten) * (bw + luecke)
            y = oben + (platz // spalten) * (bh + luecke)
            kasten = pygame.Rect(x, y, bw, bh)
            self._farb_rects.append((i, kasten))
            self._farbfeld(screen, kasten, f["rgb"], gewaehlt=(i == aktiv_farbe),
                           frei=self._frei(f["key"]))
        self._felder_nachfuehren(
            self._farb_rects, self._farb_felder,
            gesperrt={i for i, f in sichtbar if not self._frei(f["key"])})
        farben = lack.farben()
        unten = oben + zeilen * (bh + luecke)
        if farben:
            theme.text(screen, tr(farben[min(self.farb_index, len(farben) - 1)]["name"]),
                       theme.BODY, theme.TEXT if aktiv_farbe >= 0 else theme.TEXT_FAINT,
                       (r.x + 20, min(unten + 4, r.bottom - 80)))
        if self._grund:
            theme.text(screen, self._grund, theme.SMALL, theme.DANGER,
                       (r.x + 20, r.bottom - 48), max_w=r.width - 40)
        if self._stand:
            theme.text(screen, self._stand, theme.SMALL, theme.ACCENT,
                       (r.x + 20, r.bottom - 26), max_w=r.width - 40)

    def _farbfeld(self, screen, r: pygame.Rect, rgb, *, gewaehlt: bool,
                  frei: bool = True) -> None:
        flaeche = pygame.Surface(r.size, pygame.SRCALPHA)
        pygame.draw.rect(flaeche, (*(rgb if frei else _ausgegraut(rgb)), 255),
                         (0, 0, r.width, r.height), border_radius=8)
        screen.blit(flaeche, r.topleft)
        if gewaehlt:
            pygame.draw.rect(screen, theme.ACCENT_HOT, r.inflate(6, 6), 3, border_radius=10)
        else:
            hover = r.collidepoint(display.mouse_pos())
            pygame.draw.rect(screen, theme.BORDER_LIGHT if hover else theme.BORDER,
                             r, 2 if hover else 1, border_radius=8)
        if not frei:
            self._schloss(screen, (r.right - 22, r.y + 16), 1.4)

    def _schloss(self, screen, mitte: tuple[int, int], skala: float = 1.0) -> None:
        """Ein kleines Schloss, von Hand gezeichnet.

        Die gebuendelte Schrift kennt kein Schloss-Zeichen und zeichnet ein
        leeres Kaestchen — dasselbe Loch, das die Profilseite beim Haken hat.
        Zwei Rechtecke und ein Bogen sind billiger als eine zweite Schrift.
        Der dunkle Umriss darunter haelt es auf jedem Untergrund lesbar; die
        Felder sind schliesslich in allen zwoelf Grundfarben eingefaerbt.
        """
        x, y = mitte
        s = max(1, int(round(5 * skala)))
        hell, dunkel = (232, 236, 244), (12, 14, 20)
        stark = max(2, int(round(2 * skala)))
        buegel = pygame.Rect(x - s + 1, y - s - 1, 2 * s - 2, 2 * s)
        pygame.draw.arc(screen, dunkel, buegel.inflate(3, 3), 0.0, math.pi, stark + 2)
        pygame.draw.arc(screen, hell, buegel, 0.0, math.pi, stark)
        koerper = pygame.Rect(x - s - 2, y - 1, 2 * s + 4, int(1.8 * s))
        pygame.draw.rect(screen, dunkel, koerper.inflate(3, 3), border_radius=3)
        pygame.draw.rect(screen, hell, koerper, border_radius=3)

    # -- Flottenstreifen ------------------------------------------------
    def _streifen_zeichnen(self, screen: pygame.Surface, r: pygame.Rect) -> None:
        """Die Flotte als Streifen — gleitend, mit Bildlaufleiste.

        Gemeldet am 04.08.2026: „Scrollen der Fahrzeuge wirkt unnatuerlich".
        Zwei Ursachen. Der Streifen sprang **seitenweise** (auch am Mausrad, wo
        eine Raste eine ganze Seite umblaetterte), und er sprang **hart** — es gab
        keinen Zwischenstand, an dem man gesehen haette, in welche Richtung es
        gerade geht. Jetzt steht ``scroll`` auf einer krummen Kachelposition,
        ``update`` fuehrt sie dem Ziel nach, und die Leiste darunter sagt, wo im
        Feld man ist.
        """
        theme.panel(screen, r, alpha=200)
        self._kachel_rects = []
        blaettert = len(self.fahrzeuge) > KACHELN
        knopf_b = 52 if blaettert else 0
        leiste_h = 14 if blaettert else 0
        innen = pygame.Rect(r.x + knopf_b + 28, r.y + 18,
                            r.width - 2 * (knopf_b + 28),
                            r.height - 36 - leiste_h)
        if blaettert:
            links = pygame.Rect(r.x + 14, innen.centery - 48, knopf_b, 96)
            rechts = pygame.Rect(r.right - knopf_b - 14, innen.centery - 48,
                                 knopf_b, 96)
            self._blatt_rects = (links, rechts)
            self._pfeilknopf(screen, links, "‹")
            self._pfeilknopf(screen, rechts, "›")
        else:
            self._blatt_rects = None

        kb = max(120, (innen.width - (KACHELN - 1) * 14) // KACHELN)
        schritt = kb + 14
        vorher = screen.get_clip()
        screen.set_clip(innen)
        for i in range(len(self.fahrzeuge)):
            kasten = pygame.Rect(innen.x + int(round((i - self.scroll) * schritt)),
                                 innen.y, kb, innen.height)
            if kasten.right <= innen.x or kasten.x >= innen.right:
                continue
            # Getroffen werden kann nur, was man sieht: eine halb aus dem
            # Streifen ragende Kachel darf keine Klicks daneben einsammeln.
            self._kachel_rects.append((i, kasten.clip(innen)))
            self._kachel_zeichnen(screen, kasten, i)
        screen.set_clip(vorher)
        self._felder_nachfuehren(self._kachel_rects, self._kachel_felder)

        if blaettert:
            self._leiste_zeichnen(screen, pygame.Rect(innen.x, r.bottom - 20,
                                                     innen.width, 8))
        else:
            self._leiste_rect = None

    def _leiste_zeichnen(self, screen: pygame.Surface, r: pygame.Rect) -> None:
        """Bildlaufleiste: wie viel vom Feld man sieht und an welcher Stelle."""
        self._leiste_rect = r
        pygame.draw.rect(screen, (22, 25, 33), r, border_radius=4)
        anteil = min(1.0, KACHELN / float(len(self.fahrzeuge)))
        daumen = max(24, int(r.width * anteil))
        grenze = self._grenze()
        t = (self.scroll / grenze) if grenze > 0 else 0.0
        x = r.x + int(round(max(0.0, min(1.0, t)) * (r.width - daumen)))
        kasten = pygame.Rect(x, r.y, daumen, r.height)
        hell = self._zieht_leiste or r.inflate(0, 16).collidepoint(display.mouse_pos())
        pygame.draw.rect(screen, theme.ACCENT_HOT if hell else theme.ACCENT,
                         kasten, border_radius=4)

    def _kachel_zeichnen(self, screen: pygame.Surface, r: pygame.Rect, i: int) -> None:
        key = self.fahrzeuge[i]
        cfg = VehicleFactory.get_config(key)
        gewaehlt = (i == self.index)
        karte = pygame.Surface(r.size, pygame.SRCALPHA)
        karte.fill((60, 45, 20, 225) if gewaehlt else (24, 27, 36, 190))
        screen.blit(karte, r.topleft)
        pygame.draw.rect(screen, theme.ACCENT if gewaehlt else (46, 50, 62), r,
                         2 if gewaehlt else 1, border_radius=6)

        # Die Kachel zeigt den **gespeicherten** Stand, auch beim gerade
        # bearbeiteten Fahrzeug. Der Streifen ist der eigene Bestand, die Buehne
        # die Anprobe — und der Unterschied zwischen beiden ist genau das, was
        # noch nicht gespeichert ist. Vor dem 04.08.2026 zeigte die Kachel die
        # laufende Bearbeitung mit, weil sie ohnehin schon im Profil stand.
        kenn = lack.normalisiere(profile.current().paint(key))
        bild = lack.sprite(key, cfg.visual_type if cfg else key, kenn, lack.BREITE_SPIEL)
        if bild is not None:
            self._auto_zeichnen(screen, bild,
                                pygame.Rect(r.x + 8, r.y + 6, r.width - 16, r.height - 62),
                                0.0)
        theme.text_fit(screen, tr(cfg.name) if cfg else key, theme.SMALL,
                       theme.TEXT if gewaehlt else theme.TEXT_DIM,
                       pygame.Rect(r.x + 6, r.bottom - 44, r.width - 12, 22), center=True)
        theme.text_fit(screen, lack.anzeigename(kenn), theme.SMALL,
                       theme.ACCENT if gewaehlt else theme.TEXT_FAINT,
                       pygame.Rect(r.x + 6, r.bottom - 22, r.width - 12, 18), center=True)
