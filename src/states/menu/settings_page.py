"""Settings page: category column plus per-category content.

Allgemein  — change the driver name (validated).
Steuerung  — rebind the driving keys (arrow keys by default).
Video/Audio — planned rows shown as 'coming soon'.
Dev-Mode   — the only place to launch the Fahrzeug-Labor / KI-Labor.
"""
from __future__ import annotations

import pygame

from src.states.menu.page import Page
from src.core import profile, keybindings as kb
from src.core import gamepad
from src.core import display
from src.core.i18n import tr
from src.ui import theme
from src.ui.widgets import Button, TextInput, Stepper, OnScreenKeyboard, Dialog
from src.ui.focus import FocusGroup

_CATEGORIES = ["Allgemein", "Steuerung", "Video", "Audio", "Dev-Mode", "Info"]
_SOON_ROWS = {
    "Audio": ["Gesamtlautstärke", "Effekte"],
}
_ISSUES_URL = "https://github.com/philip-hh00/3D-Racing-Game/issues"

# The game drives at most two local players, so the Steuerung page shows two
# controller slots (pad0 / pad1) even when only one pad is plugged in.
PAD_SLOTS = 2
_INFO_SCROLL_STEP = 60


def _grafik_regler() -> list[tuple[str, str, list[tuple[object, str]]]]:
    """Die Einzelregler der Grafik: ``(feld, beschriftung, [(wert, anzeige), …])``.

    Je Feld aus ``src/render3d/grafik.py`` ein Stepper. Die Werte sind die
    Rohwerte des Feldes, die Anzeigen übersetzt — zurückgerechnet wird nie
    aus dem Text (siehe ``_werte``).
    """
    aus, an = tr("Aus"), tr("An")
    return [
        ("aufloesung_skala", tr("3D-Auflösung"),
         [(0.5, "50 %"), (0.67, "67 %"), (0.75, "75 %"), (0.85, "85 %"), (1.0, "100 %")]),
        ("schatten_px", tr("Schatten"),
         [(0, aus), (1024, "1024"), (2048, "2048"), (4096, "4096"), (8192, "8192")]),
        ("ssao", tr("Verdeckung (SSAO)"), [(0, aus), (1, tr("Halb")), (2, tr("Voll"))]),
        ("bloom", tr("Bloom"), [(False, aus), (True, an)]),
        ("kantenglaettung", tr("Kantenglättung"),
         [("aus", aus), ("fxaa", "FXAA"), ("msaa4", "MSAA 4×")]),
        ("deko_dichte", tr("Deko-Dichte"),
         [(0.3, "30 %"), (0.4, "40 %"), (0.55, "55 %"), (0.7, "70 %"), (0.85, "85 %"), (1.0, "100 %")]),
        ("sichtweite_m", tr("Sichtweite"),
         [(v, f"{int(v)} m") for v in (500.0, 700.0, 900.0, 1100.0, 1600.0, 2000.0, 2400.0)]),
        ("gras", tr("Gras"), [(0, aus), (1, tr("Dünn")), (2, tr("Dicht"))]),
        ("gelaende_detail", tr("Geländedetail"), [(0, tr("Grob")), (1, tr("Mittel")), (2, tr("Fein"))]),
        ("gelaende_schatten", tr("Geländeschatten"),
         [(0, aus), (1, tr("Grob")), (2, tr("Mittel")), (3, tr("Fein"))]),
        ("strecken_details", tr("Streckendetails"), [(0, aus), (1, tr("Einige")), (2, tr("Alle"))]),
        ("reifenspuren", tr("Reifenspuren"), [(False, aus), (True, an)]),
        ("fahrzeug_lod_m", tr("Autos vereinfacht ab"),
         [(v, f"{int(v)} m") for v in (20.0, 35.0, 60.0, 120.0, 250.0)]),
    ]


#: Die Stufen in der Reihenfolge des Steppers; "eigen" steht, sobald ein
#: Einzelwert von der gewählten Stufe abweicht.
_GRAFIK_STUFEN = ("niedrig", "mittel", "hoch", "ultra", "eigen")


def _umbrechen(text: str, groesse: int, breite: int) -> list[str]:
    """Einen Hinweis in Zeilen, die in *breite* Pixel passen."""
    schrift = theme.font(groesse)
    zeilen, zeile = [], ""
    for wort in text.split(" "):
        probe = (zeile + " " + wort).strip()
        if zeile and schrift.size(probe)[0] > breite:
            zeilen.append(zeile)
            zeile = wort
        else:
            zeile = probe
    if zeile:
        zeilen.append(zeile)
    return zeilen


def _grafik_stufen_namen() -> list[str]:
    return [tr("Niedrig"), tr("Mittel"), tr("Hoch"), tr("Ultra"), tr("Eigen")]


def _grafik_stufe_erkennen(werte: dict) -> str:
    """Welche Stufe genau diese Werte hat, sonst "eigen"."""
    from src.render3d import grafik
    for name in grafik.STUFEN_NAMEN:
        vorgabe = grafik.als_dict(grafik.STUFEN[name])
        if all(werte.get(k) == v for k, v in vorgabe.items() if k != "stufe"):
            return name
    return "eigen"


class SettingsPage(Page):
    #: Der Zurück-Knopf steht mit dem Inhalt auf einer Kante (x + 80); der Titel
    #: rückt dafür nach rechts und liest sich als Fortsetzung: „‹ Zurück  TITEL".
    ZURUECK_VERSATZ = (80, 16)
    #: Unten links: oben ist hier kein Platz (gemeldet 05.08.2026).
    ZURUECK_UNTEN = True

    def __init__(self) -> None:
        self.cat = 0
        self._focus_content = False
        self.msg = ""
        self.msg_ok = False
        self._capture: str | None = None      # action id awaiting a new key
        self._sel_bind = 0                     # selected row in Steuerung (keys, then pad slots)
        self._save_focus = False               # SPEICHERN reachable from the category column
        self._name_input: TextInput | None = None
        self._content_group: FocusGroup | None = None
        self.osk: OnScreenKeyboard | None = None
        self._controller_flash: dict[int, float] = {}
        self.is_pause_context = False
        self._issues_rect: pygame.Rect | None = None
        self._crash_rect: pygame.Rect | None = None

    @property
    def categories(self) -> list[str]:
        from src.core.version import IS_RELEASE
        if self.is_pause_context:
            return ["Allgemein", "Steuerung", "Video", "Audio"]
        if IS_RELEASE:
            return ["Allgemein", "Steuerung", "Video", "Audio", "Info"]
        return _CATEGORIES

    def enter(self, shell, **kwargs) -> None:
        self.shell = shell
        self.osk = None
        self._controller_flash = {}
        self._pending: dict = {}
        #: Rohwerte je Stepper-Aktion, in derselben Reihenfolge wie seine
        #: Beschriftungen. Gebraucht, weil die Beschriftung **übersetzt** ist:
        #: „Stumm" heißt auf Englisch „Muted", „Vollbild" heißt „Fullscreen".
        #: Wer den angezeigten Text zurückrechnet, baut einen Fehler, der nur in
        #: einer Sprache auftritt — und genau davon gab es sechs (04.08.2026).
        self._werte: dict[str, list] = {}
        self._leave_dialog = None
        self._leave_nav = None
        self._save_rect: pygame.Rect | None = None
        self._save_focus = False
        self._info_scroll = 0
        self._info_max_scroll = 0
        self._build_content()

    def _eff(self, key, current):
        """Effective value: pending override if edited, else the current profile value."""
        return self._pending.get(key, current)

    @property
    def _dirty(self) -> bool:
        return bool(self._pending)

    # ------------------------------------------------------------------
    def _cat_rects(self) -> list[pygame.Rect]:
        x, y = 80, 190
        return [pygame.Rect(x, y + i * 76, 360, 62) for i in range(len(self.categories))]

    def _bind_rects(self) -> list[pygame.Rect]:
        return [pygame.Rect(560, 240 + i * 68, 700, 58) for i in range(len(kb.ACTIONS))]

    def _pad_rects(self) -> list[pygame.Rect]:
        """Selectable controller slots in the Steuerung column on the right."""
        x, y = 1320, 168
        return [pygame.Rect(x, y + 56 + i * 46, 340, 40) for i in range(PAD_SLOTS)]

    @property
    def _steuerung_rows(self) -> int:
        return len(kb.ACTIONS) + PAD_SLOTS

    def _identify_pad(self, slot: int) -> None:
        """Vibrate the pad in *slot* so the player can tell the two apart."""
        if slot < gamepad.device_count():
            gamepad.rumble(slot, 0.8, 0.8, 400)
            self._controller_flash[slot] = 0.6
            self.msg = ""
        else:
            self.msg = tr("Controller {i} ist nicht verbunden.").format(i=slot + 1)
            self.msg_ok = False

    def _build_content(self) -> None:
        self.msg = ""
        self._capture = None
        self._content_group = None
        self._name_input = None
        name = self.categories[self.cat]
        if name == "Allgemein":
            from src.core import i18n
            col = theme.Column(560, 250, gap=30)
            self._name_input = TextInput(pygame.Rect(0, 0, 500, 60),
                                         self._eff("username", profile.current().username),
                                         max_len=profile.NAME_MAX, allowed=profile.NAME_ALLOWED)
            col.add(self._name_input)
            lang_opts = [i18n.LANGUAGE_LABELS[c] for c in i18n.LANGUAGES]
            code = self._eff("language", i18n.current())
            lang_idx = i18n.LANGUAGES.index(code) if code in i18n.LANGUAGES else 0
            lang_step = Stepper(pygame.Rect(0, 0, 500, 60), tr("Sprache"),
                                lang_opts, lang_idx, action="change_language")
            col.add(lang_step)
            # Beenden-Knopf: oeffnet denselben Dialog wie ESC im Hauptmenue
            # (08.08.2026), damit man das Spiel auch aus den Einstellungen
            # heraus verlassen kann, ohne erst eine Ebene hoch zu muessen.
            quit_btn = Button(pygame.Rect(0, 0, 500, 60), tr("Spiel beenden"), "quit_game")
            col.add(quit_btn)
            self._content_group = FocusGroup([lang_step, quit_btn])
        elif name == "Dev-Mode":
            col = theme.Column(560, 240, gap=20)
            b1 = Button(pygame.Rect(0, 0, 420, 66), "Fahrzeug-Labor", "vehicle_lab")
            b2 = Button(pygame.Rect(0, 0, 420, 66), "KI-Labor", "ki_labor")
            col.add(b1)
            col.add(b2)
            self._content_group = FocusGroup([b1, b2])
        elif name == "Video":
            from src.core.display import RESOLUTION_LABELS, resolution_str_to_label
            res_labels = RESOLUTION_LABELS
            cur_res = resolution_str_to_label(self._eff("resolution", profile.current().resolution))
            res_idx = res_labels.index(cur_res) if cur_res in res_labels else 2  # default 1920×1080
            fs_opts = [tr("Fenster"), tr("Vollbild")]
            fs_idx = 1 if self._eff("fullscreen", profile.current().fullscreen) else 0
            fps_opts = ["30", "60", "120", "144", "240", tr("Unbegrenzt")]
            fps_map = {"30": 30, "60": 60, "120": 120, "144": 144, "240": 240, tr("Unbegrenzt"): 0}
            fps_rev = {v: k for k, v in fps_map.items()}
            cur_fps_str = fps_rev.get(self._eff("fps_limit", profile.current().fps_limit), "60")
            fps_idx = fps_opts.index(cur_fps_str) if cur_fps_str in fps_opts else 1
            vs_opts = [tr("Aus"), tr("An")]
            vs_idx = 1 if self._eff("vsync", profile.current().vsync) else 0
            tex_opts = [tr("Niedrig"), tr("Hoch")]
            tex_idx = 1 if self._eff("texture_quality", profile.current().texture_quality) == "Hoch" else 0
            
            # Rohwerte NEBEN den Beschriftungen — siehe Audio-Block.
            self._werte["change_resolution"] = list(res_labels)
            self._werte["toggle_fullscreen"] = [False, True]
            self._werte["change_fps"] = [30, 60, 120, 144, 240, 0]
            self._werte["toggle_vsync"] = [False, True]
            self._werte["change_texquality"] = ["Niedrig", "Hoch"]

            col = theme.Column(560, 250, gap=12)
            s1 = Stepper(pygame.Rect(0, 0, 500, 60), tr("Auflösung"),    res_labels, res_idx,    action="change_resolution")
            s2 = Stepper(pygame.Rect(0, 0, 500, 60), tr("Fenstermodus"), fs_opts,    fs_idx,    action="toggle_fullscreen")
            s3 = Stepper(pygame.Rect(0, 0, 500, 60), tr("FPS-Limit"),    fps_opts,   fps_idx,   action="change_fps")
            s4 = Stepper(pygame.Rect(0, 0, 500, 60), tr("V-Sync"),       vs_opts,    vs_idx,    action="toggle_vsync")
            s5 = Stepper(pygame.Rect(0, 0, 500, 60), tr("Texturqualität"), tex_opts, tex_idx,   action="change_texquality")
            
            col.add(s1)
            col.add(s2)
            col.add(s3)
            col.add(s4)
            col.add(s5)
            self._content_group = FocusGroup([s1, s2, s3, s4, s5] + self._grafik_bauen())
        elif name == "Audio":
            menu_pct = int(round(self._eff("menu_volume", profile.current().menu_volume) * 10.0))
            menu_pct = max(0, min(10, menu_pct))
            race_pct = int(round(self._eff("race_volume", profile.current().race_volume) * 10.0))
            race_pct = max(0, min(10, race_pct))
            options = [tr("Stumm")] + [f"{i*10}%" for i in range(1, 11)]
            # Rohwerte NEBEN den Beschriftungen. Der angezeigte Text ist
            # uebersetzt ("Stumm"/"Muted"); wer ihn zurueckrechnet, baut einen
            # Fehler, der nur in einer Sprache auftritt. Genau so ist der
            # Absturz vom 04.08.2026 entstanden: int("Muted").
            for a in ("change_menu_volume", "change_race_volume",
                      "change_sfx_menu_volume", "change_sfx_race_volume"):
                self._werte[a] = [i / 10.0 for i in range(0, 11)]
            
            # Vier Regler seit dem 02.08.2026: Musik und Effekte je getrennt
            # nach Menü und Rennen. Vorher teilten sich Menüklänge und
            # Rennklänge einen Regler — wer die Menüklicks leiser wollte, drehte
            # zwangsläufig auch den Motor herunter.
            def _pct(feld: str) -> int:
                wert = self._eff(feld, getattr(profile.current(), feld, 0.7))
                return max(0, min(10, int(round(float(wert) * 10.0))))

            col = theme.Column(560, 250, gap=12)
            s1 = Stepper(pygame.Rect(0, 0, 500, 60), tr("Musik (Menü)"), options, menu_pct, action="change_menu_volume")
            s2 = Stepper(pygame.Rect(0, 0, 500, 60), tr("Musik (Rennen)"), options, race_pct, action="change_race_volume")
            s3 = Stepper(pygame.Rect(0, 0, 500, 60), tr("Effekte (Menü)"), options,
                         _pct("sfx_menu_volume"), action="change_sfx_menu_volume")
            s4 = Stepper(pygame.Rect(0, 0, 500, 60), tr("Effekte (Rennen)"), options,
                         _pct("sfx_race_volume"), action="change_sfx_race_volume")
            for w in (s1, s2, s3, s4):
                col.add(w)
            self._content_group = FocusGroup([s1, s2, s3, s4])


    # -- Grafik ------------------------------------------------------------
    #: Zweite Spalte der Video-Seite: Stufe und je Feld ein Regler. Die
    #: letzte Zeile muss über dem SPEICHERN-Knopf enden (vierzehn Zeilen).
    GRAFIK_X, GRAFIK_Y, GRAFIK_ZEILE, GRAFIK_ABSTAND = 1120, 250, 46, 4

    def _grafik_werte(self) -> dict:
        """Die Grafikwerte, wie sie gerade gelten würden (mit Ungespeichertem)."""
        from src.render3d import grafik
        return dict(self._pending.get("grafik") or grafik.als_dict())

    def _grafik_bauen(self) -> list:
        werte = self._grafik_werte()
        col = theme.Column(self.GRAFIK_X, self.GRAFIK_Y, gap=self.GRAFIK_ABSTAND)
        stufe = werte.get("stufe", "hoch")
        if stufe not in _GRAFIK_STUFEN:
            stufe = _grafik_stufe_erkennen(werte)
        self._werte["grafik_stufe"] = list(_GRAFIK_STUFEN)
        widgets = [Stepper(pygame.Rect(0, 0, 500, self.GRAFIK_ZEILE), tr("Grafikstufe"),
                           _grafik_stufen_namen(), _GRAFIK_STUFEN.index(stufe),
                           action="grafik_stufe")]
        for feld, beschriftung, optionen in _grafik_regler():
            wert = werte.get(feld)
            if wert is not None and all(w != wert for w, _a in optionen):
                # Ein Wert aus einem älteren Profil oder einer Stufe, den der
                # Regler nicht kennt: einreihen statt verlieren.
                optionen = sorted(optionen + [(wert, str(wert))],
                                  key=lambda o: (isinstance(o[0], str), o[0]))
            self._werte["grafik_" + feld] = [w for w, _a in optionen]
            index = next((i for i, (w, _a) in enumerate(optionen) if w == wert), 0)
            widgets.append(Stepper(pygame.Rect(0, 0, 500, self.GRAFIK_ZEILE), beschriftung,
                                   [a for _w, a in optionen], index, action="grafik_" + feld))
        for w in widgets:
            col.add(w)
        return widgets

    def _stepper(self, aktion: str):
        widgets = self._content_group.widgets if self._content_group else []
        return next((w for w in widgets if getattr(w, "action", None) == aktion), None)

    def _grafik_aendern(self, aktion: str) -> None:
        """Ein Grafikregler wurde bewegt: Werte puffern, Stufe nachziehen."""
        from src.render3d import grafik
        w = self._stepper(aktion)
        roh = self._werte.get(aktion) or []
        if w is None or not roh:
            return
        wert = roh[max(0, min(w.index, len(roh) - 1))]
        werte = self._grafik_werte()
        if aktion == "grafik_stufe":
            if wert == "eigen":
                werte["stufe"] = "eigen"
            else:
                werte = grafik.als_dict(grafik.STUFEN[wert])
            # Alle Einzelregler auf die Werte der Stufe stellen, ohne die
            # Seite neu zu bauen — sonst springt der Fokus an den Anfang.
            for feld, _b, _o in _grafik_regler():
                r = self._stepper("grafik_" + feld)
                liste = self._werte.get("grafik_" + feld) or []
                if r is not None and werte.get(feld) in liste:
                    r.index = liste.index(werte[feld])
        else:
            werte[aktion.removeprefix("grafik_")] = wert
            werte["stufe"] = _grafik_stufe_erkennen(werte)
            r = self._stepper("grafik_stufe")
            if r is not None:
                r.index = _GRAFIK_STUFEN.index(werte["stufe"])
        self._pending["grafik"] = werte
        self.msg = ""

    def _rohwert(self, aktion: str, widget_index: int):
        """Der Wert hinter der Stellung eines Steppers — nie sein Anzeigetext.

        *widget_index* ist die Position in ``_content_group``; die Zuordnung
        stimmt, weil dieselbe Methode die Widgets aufbaut. Fehlt die Liste oder
        steht der Zeiger daneben, kommt der erste Wert zurück statt einer
        Ausnahme: eine Einstellungsseite darf am falschen Index nicht abstürzen.
        """
        werte = self._werte.get(aktion) or []
        if not werte:
            return None
        widgets = self._content_group.widgets if self._content_group else []
        if not (0 <= widget_index < len(widgets)):
            return werte[0]
        i = int(getattr(widgets[widget_index], "index", 0))
        return werte[i] if 0 <= i < len(werte) else werte[0]

    # ------------------------------------------------------------------
    def verlassen_erlaubt(self, weiter) -> bool:
        """Ungespeicherte Änderungen gehen nicht kommentarlos verloren."""
        if not self._dirty:
            return True
        self._leave_nav = weiter
        self._leave_dialog = Dialog(
            tr("Einstellungen speichern?"),
            tr("Du hast ungespeicherte Änderungen."),
            [(tr("Speichern"), "save"), (tr("Verwerfen"), "discard"),
             (tr("Abbrechen"), "cancel")])
        return False

    def handle_event(self, event: pygame.event.Event) -> bool | None:
        if self.zurueck_geklickt(event):
            return True
        if self.osk:
            if self.osk.handle_event(event):
                # Nur die Tastatur zumachen. Vorher ging mit ihr auch die
                # Inhaltsspalte zu — ein B sprang damit zwei Ebenen, und aus der
                # Tiefe war man nach zwei Druecken im Hauptmenue statt nach drei
                # (gemeldet 02.08.2026).
                self.osk = None
            return True

        if self._leave_dialog is not None:
            res = self._leave_dialog.handle_event(event)
            if res == "save":
                if self._apply_pending():          # only leave if save succeeded
                    self._leave_dialog = None
                    nav = self._leave_nav; self._leave_nav = None
                    if nav: nav()
                else:
                    self._leave_dialog = None       # validation failed: stay, show msg
            elif res == "discard":
                self._pending = {}
                self._leave_dialog = None
                nav = self._leave_nav; self._leave_nav = None
                self._build_content()
                if nav: nav()
            elif res == "cancel":
                self._leave_dialog = None
                self._leave_nav = None
            return True

        # Key-capture mode (Steuerung rebinding) swallows the next key.
        if self._capture is not None and event.type == pygame.KEYDOWN:
            if getattr(event, "synthetic", False):
                self.msg = tr("Tastenbelegung nur mit der Tastatur änderbar.")
                self.msg_ok = False
                self._capture = None
                return True
            ok, m = kb.rebind(self._capture, event.key)
            self.msg = "" if ok else tr(m)
            self.msg_ok = False
            self._capture = None
            return True

        name = self.categories[self.cat]

        if self.categories[self.cat] == "Info":
            if event.type == pygame.MOUSEWHEEL:
                self._info_scroll = max(0, min(getattr(self, "_info_max_scroll", 0),
                                               self._info_scroll - event.y * 40))
                return True
            if event.type == pygame.MOUSEBUTTONDOWN and event.button in (4, 5):
                d = 40 if event.button == 5 else -40
                self._info_scroll = max(0, min(getattr(self, "_info_max_scroll", 0),
                                               self._info_scroll + d))
                return True

        if event.type == pygame.MOUSEMOTION:
            over_cat = False
            if self._save_rect and self._save_rect.collidepoint(event.pos):
                self._save_focus = True
                self._focus_content = False
            elif self._save_focus:
                self._save_focus = False
            # Nur noch Position merken, NICHT auswaehlen — bloss der Weg von der
            # Maus zu einer Nachbarkategorie loeste schon einen Seitenwechsel
            # aus. Ausgewaehlt wird jetzt nur per Klick (siehe MOUSEBUTTONDOWN
            # unten); draw() zeichnet die Zeile unter dem Zeiger mit der
            # leichten Hover-Fuellung PANEL_LIGHT, ohne self.cat zu aendern
            # (gemeldet 05.08.2026).
            for r in self._cat_rects():
                if r.collidepoint(event.pos):
                    over_cat = True
                    break

            if not over_cat:
                if self._name_input and self._name_input.rect.collidepoint(event.pos):
                    self._focus_content = True
                elif self._content_group:
                    for w in self._content_group.widgets:
                        if getattr(w, "focusable", False) and w.hit(event.pos):
                            self._focus_content = True
                            break
                    self._content_group.handle_event(event)
            return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._dirty and self._save_rect and self._save_rect.collidepoint(event.pos):
                self._apply_pending()
                return True
            if event.pos[1] < 108:
                # Die Tab-Leiste gehoert der Shell; die fragt vorher bei
                # verlassen_erlaubt() nach, ob hier noch etwas offen ist.
                return None
            if (self.categories[self.cat] == "Info" and self._issues_rect
                    and self._issues_rect.collidepoint(event.pos)):
                import webbrowser
                webbrowser.open(_ISSUES_URL)
                return True
            if (self.categories[self.cat] == "Info" and self._crash_rect
                    and self._crash_rect.collidepoint(event.pos)):
                from src.core import absturz
                absturz.oeffnen()
                return True
            for i, r in enumerate(self._cat_rects()):
                if r.collidepoint(event.pos):
                    self.cat = i
                    self._focus_content = False
                    self.osk = None
                    self._build_content()
                    return True
            if name == "Steuerung":
                for i, r in enumerate(self._bind_rects()):
                    if r.collidepoint(event.pos):
                        self._sel_bind = i
                        self._capture = kb.ACTIONS[i][0]
                        return True
            if self._name_input and self._name_input.rect.collidepoint(event.pos):
                self._focus_content = True
            
            # Controller identification: check mouse clicks on controller rows
            if name == "Steuerung":
                for slot, r in enumerate(self._pad_rects()):
                    if r.collidepoint(event.pos):
                        self._focus_content = True
                        self._sel_bind = len(kb.ACTIONS) + slot
                        self._identify_pad(slot)
                        return True

            if self._content_group:
                self._dispatch(self._content_group.handle_event(event))
            return True

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_PAGEUP:
                self.cat = (self.cat - 1) % len(self.categories)
                self._focus_content = False
                self._save_focus = False
                self.osk = None
                self._build_content()
                return True
            elif event.key == pygame.K_PAGEDOWN:
                self.cat = (self.cat + 1) % len(self.categories)
                self._focus_content = False
                self._save_focus = False
                self.osk = None
                self._build_content()
                return True
            elif event.key == pygame.K_ESCAPE and self._focus_content:
                # One level back: leave the content column, stay on the page.
                self._focus_content = False
                self.osk = None
                return True
            elif event.key == pygame.K_ESCAPE and self._save_focus:
                # One level back: leave the SPEICHERN button, stay on the page.
                self._save_focus = False
                return True
            elif event.key == pygame.K_ESCAPE and not self._focus_content and self._dirty:
                self._leave_nav = self.shell.pop_page
                self._leave_dialog = Dialog(tr("Einstellungen speichern?"),
                    tr("Du hast ungespeicherte Änderungen."),
                    [(tr("Speichern"), "save"), (tr("Verwerfen"), "discard"), (tr("Abbrechen"), "cancel")])
                return True
            elif event.key in (pygame.K_UP, pygame.K_w, kb.get("throttle")) and not self._focus_content:
                self._move_left_column(-1)
                return True
            elif event.key in (pygame.K_DOWN, pygame.K_s, kb.get("brake")) and not self._focus_content:
                self._move_left_column(+1)
                return True
            elif event.key == pygame.K_RETURN and not self._focus_content:
                if self._save_focus:
                    self._apply_pending()
                    return True
                self._focus_content = True
                if name == "Steuerung":
                    self._sel_bind = 0
                return True
            elif self._focus_content:
                self._content_key(name, event)
                return True
        return None

    def _move_left_column(self, d: int) -> None:
        """Navigate the category column; the SPEICHERN button is the last stop.

        Making Save a regular row is what lets a controller reach it — before,
        it was mouse-only and pad users had to trigger the leave dialog with B.
        """
        n = len(self.categories)
        cur = n if self._save_focus else self.cat
        nxt = (cur + d) % (n + 1)
        if nxt == n:
            self._save_focus = True
            return
        self._save_focus = False
        if nxt != self.cat:
            self.cat = nxt
            self.osk = None
            self._build_content()

    def _content_key(self, name: str, event: pygame.event.Event) -> None:
        if name == "Allgemein" and self._name_input:
            if event.key == pygame.K_RETURN:
                # Controller: A opens the on-screen keyboard; keyboard: save.
                if gamepad.using_pad() and self.osk is None:
                    self.osk = OnScreenKeyboard(self._name_input, on_done=self._save_name)
                else:
                    self._save_name()
            else:
                self._name_input.handle_key(event.key, getattr(event, "unicode", ""))
                self._pending["username"] = self._name_input.text
                self.msg = ""
        elif name == "Steuerung":
            rows = self._steuerung_rows
            if event.key in (pygame.K_UP, pygame.K_w, kb.get("throttle")):
                self._sel_bind = (self._sel_bind - 1) % rows
            elif event.key in (pygame.K_DOWN, pygame.K_s, kb.get("brake")):
                self._sel_bind = (self._sel_bind + 1) % rows
            elif event.key in (pygame.K_LEFT, pygame.K_RIGHT):
                # Jump between the key list and the controller slots.
                if self._sel_bind < len(kb.ACTIONS):
                    self._sel_bind = len(kb.ACTIONS)
                else:
                    self._sel_bind = 0
            elif event.key == pygame.K_RETURN:
                if self._sel_bind >= len(kb.ACTIONS):
                    self._identify_pad(self._sel_bind - len(kb.ACTIONS))
                elif getattr(event, "synthetic", False):
                    self.msg = tr("Tastenbelegung nur mit der Tastatur änderbar.")
                    self.msg_ok = False
                else:
                    self._capture = kb.ACTIONS[self._sel_bind][0]
        elif name == "Info":
            if event.key in (pygame.K_UP, pygame.K_w, kb.get("throttle")):
                self._info_scroll = max(0, self._info_scroll - _INFO_SCROLL_STEP)
            elif event.key in (pygame.K_DOWN, pygame.K_s, kb.get("brake")):
                self._info_scroll = min(getattr(self, "_info_max_scroll", 0),
                                        self._info_scroll + _INFO_SCROLL_STEP)
            elif event.key == pygame.K_RETURN:
                import webbrowser
                webbrowser.open(_ISSUES_URL)
        elif self._content_group:
            self._dispatch(self._content_group.handle_event(event))

    def _draw_info(self, screen: pygame.Surface) -> None:
        from src.core import version as ver
        from src.net import server_info
        server_info.fetch_info_async()
        x, y = 560, 176
        theme.text(screen, tr("Über das Spiel"), theme.HEADER, theme.TEXT, (x, y))
        # Nur die Versionsnummer, ohne den Commit-Hash aus version_string() —
        # der stand hier hinter der Version in Klammern und wurde als
        # verwirrend gemeldet (05.08.2026). Der Hash bleibt an anderer Stelle
        # bewusst sichtbar; version.py selbst bleibt unveraendert.
        # Die Uhrzeit steht dabei, sobald eine eingebrannt ist (06.08.2026):
        # Testbuilds tragen dieselbe Versionsnummer und unterscheiden sich nur
        # in der Bauzeit. Ohne sie liesse sich am laufenden Spiel nicht sagen,
        # welcher Stand gerade laeuft. Aus dem Quelltext gestartet gibt es keine,
        # dann bleibt es beim Datum allein.
        bau = ver.BUILD_DATE + (f"  {ver.BUILD_TIME} UTC" if ver.BUILD_TIME else "")
        rows = [
            ("Spiel",       "3D-Racing-Game"),
            ("Version",     f"v{ver.VERSION}"),
            ("Build-Datum", bau),
            ("Engine",      "pygame-ce · pymunk"),
        ]
        yy = y + 56
        for label, value in rows:
            theme.text(screen, tr(label), theme.BODY, theme.TEXT_DIM, (x, yy))
            theme.text(screen, value, theme.BODY, theme.TEXT, (x + 240, yy))
            yy += 48

        info = server_info.get_cached()
        ok = server_info.version_ok()
        yy += 16
        if ok is True:
            theme.text(screen, tr("Version aktuell") + f" {theme.HAKEN}", theme.BODY, theme.SUCCESS, (x, yy))
        elif ok is False:
            req = (info or {}).get("required_version", "?")
            theme.text(screen, tr("Neue Version verfügbar: {v}").format(v=req), theme.BODY, theme.DANGER, (x, yy))
        else:
            theme.text(screen, tr("Server nicht erreichbar."), theme.BODY, theme.TEXT_FAINT, (x, yy))
        yy += 44

        # Der Hinweis auf den unverschluesselten Online-Verkehr stand hier von
        # 05.08.2026 bis 05.08.2026 und ist auf Wunsch wieder entfernt worden —
        # er soll auch nicht in der itch.io-Beschreibung stehen. Der Verkehr ist
        # unveraendert im Klartext; das bleibt in Block H1 festgehalten, nur
        # eben nicht mehr im Spiel ausgewiesen.

        # --- Announcements: framed, clipped, scrollable box ---
        theme.text(screen, tr("Ankündigungen"), theme.HEADER, theme.TEXT, (x, yy))
        from src.ui import hints
        theme.text(screen,
                   hints.bar(("scroll" if self._focus_content else "confirm", tr("Scrollen"))),
                   theme.HINT, theme.ACCENT if self._focus_content else theme.TEXT_FAINT,
                   (x + 1120, yy + 12), midright=True)
        # Abstand Ueberschrift->Kasten: die "Ankuendigungen"-Zeile (HEADER-Groesse
        # 46, skaliert auf 37px, siehe theme._load_font) rendert als Flaeche von
        # 50px Hoehe (gemessen per font.render(...).get_height()). Mit +46 stand
        # die Kastenoberkante 4px VOR dem Textende — der Kasten schnitt in den
        # Schriftzug (gemeldet 05.08.2026). +66 laesst der Zeile ihre vollen
        # 50px plus 16px Luft, bevor der Kasten beginnt.
        box = pygame.Rect(x, yy + 66, 1120, 900 - (yy + 66))   # bottom edge at y=900
        theme.panel(screen, box, alpha=200,
                    border=theme.ACCENT if self._focus_content else theme.BORDER)
        anns = sorted((info or {}).get("announcements", []) or [],
                      key=lambda a: str(a.get("date", "")), reverse=True)
        inner_x = box.x + 24
        wrap_w = box.width - 48
        font = theme.font(theme.BODY)
        if not anns:
            self._info_max_scroll = 0
            theme.text(screen, tr("Keine Ankündigungen vorhanden."), theme.BODY,
                       theme.TEXT_DIM, (inner_x, box.y + 20))
        else:
            from src.core.i18n import current as _lang
            lg = _lang()
            # Pre-wrap all entries to know the total content height.
            entries = []   # (head, [lines])
            for ann in anns:
                title = (ann.get("title") or {}).get(lg) or (ann.get("title") or {}).get("de") or ""
                text  = (ann.get("text") or {}).get(lg) or (ann.get("text") or {}).get("de") or ""
                head = f"{ann.get('date', '')}  —  {title}".strip(" —")
                lines = []
                paragraphs = text.split("\n")
                for p in paragraphs:
                    words = p.split(" ")
                    cur = ""
                    for wd in words:
                        t2 = (cur + " " + wd).strip()
                        if cur and font.size(t2)[0] > wrap_w:
                            lines.append(cur); cur = wd
                        else:
                            cur = t2
                    if cur:
                        lines.append(cur)
                    if not p:
                        lines.append("")
                entries.append((head, lines))
            content_h = sum(44 + len(ls) * 30 + 26 for _h, ls in entries) + 16
            self._info_max_scroll = max(0, content_h - box.height)
            self._info_scroll = max(0, min(self._info_scroll, self._info_max_scroll))
            prev_clip = screen.get_clip()
            screen.set_clip(box.inflate(-4, -4))
            ey = box.y + 16 - self._info_scroll
            for head, lines in entries:
                theme.text(screen, head, theme.BODY, theme.ACCENT, (inner_x, ey)); ey += 38
                for ln in lines:
                    theme.text(screen, ln, theme.BODY, theme.TEXT_DIM, (inner_x, ey)); ey += 30
                ey += 6
                pygame.draw.line(screen, theme.BORDER, (inner_x, ey), (box.right - 24, ey), 1)
                ey += 26
            screen.set_clip(prev_clip)
            # slim scrollbar when scrollable
            if self._info_max_scroll > 0:
                track_h = box.height - 12
                handle_h = max(30, int(track_h * box.height / content_h))
                frac = self._info_scroll / self._info_max_scroll
                hy = box.y + 6 + int(frac * (track_h - handle_h))
                pygame.draw.rect(screen, theme.ACCENT, (box.right - 10, hy, 4, handle_h), border_radius=2)

        link_y = 916
        label = tr("Bugs melden: GitHub Issues öffnen")
        surf_font = theme.font(theme.BODY)
        w = surf_font.size(label)[0]
        self._issues_rect = pygame.Rect(x, link_y, w + 8, 34)
        hover = self._issues_rect.collidepoint(display.mouse_pos())
        theme.text(screen, label, theme.BODY, theme.ACCENT_HOT if hover else theme.ACCENT, (x, link_y))
        pygame.draw.line(screen, theme.ACCENT_HOT if hover else theme.ACCENT,
                         (x, link_y + 30), (x + w, link_y + 30), 1)

        # Der Absturzbericht. Nach einem Absturz steht sein Pfad sechs Sekunden
        # auf dem roten Bildschirm — zu kurz zum Abschreiben, und im gepackten
        # macOS-Buendel liegt er ausserdem woanders als im Arbeitsverzeichnis
        # (Block F2). Ohne Bericht wird der Pfad genannt statt eines toten
        # Links: dann weiss man wenigstens, wo er auftauchen wird.
        from src.core import absturz
        crash_y = link_y + 44
        if absturz.vorhanden():
            crash_label = tr("Absturzbericht öffnen (crash.log)")
            cw = surf_font.size(crash_label)[0]
            self._crash_rect = pygame.Rect(x, crash_y, cw + 8, 34)
            c_hover = self._crash_rect.collidepoint(display.mouse_pos())
            farbe = theme.ACCENT_HOT if c_hover else theme.ACCENT
            theme.text(screen, crash_label, theme.BODY, farbe, (x, crash_y))
            pygame.draw.line(screen, farbe, (x, crash_y + 30), (x + cw, crash_y + 30), 1)
        else:
            self._crash_rect = None
            theme.text(screen, tr("Kein Absturzbericht vorhanden ({p})").format(
                p=absturz.pfad()), theme.HINT, theme.TEXT_FAINT, (x, crash_y + 4))

    def _draw_controller_info(self, screen: pygame.Surface) -> None:
        """Two controller slots (pad0/pad1) with a vibration identify action."""
        x, y = 1320, 168
        theme.text(screen, tr("Controller"), theme.HEADER, theme.TEXT, (x, y))
        n = gamepad.device_count()
        rects = self._pad_rects()
        for slot, r in enumerate(rects):
            connected = slot < n
            selected = (self._focus_content
                        and self._sel_bind == len(kb.ACTIONS) + slot)
            flashing = (slot in self._controller_flash)
            pygame.draw.rect(screen, theme.PANEL_SEL if selected else theme.PANEL, r, border_radius=8)
            pygame.draw.rect(screen, theme.ACCENT if (selected or flashing) else theme.BORDER,
                             r, 2, border_radius=8)
            label = f"{tr('Controller')} {slot + 1}"
            theme.text(screen, label, theme.LABEL, theme.TEXT_DIM, (r.x + 12, r.centery - 12))
            if connected:
                val = gamepad.short_device_name(gamepad.device_name(slot), 18)
                col = theme.ACCENT if flashing else theme.SUCCESS
                if flashing:
                    val = tr("[VIBRIERT]")
            else:
                val, col = tr("Nicht verbunden"), theme.DISABLED
            theme.text(screen, val, theme.LABEL, col, (r.right - 12, r.centery), midright=True)

        from src.ui import hints
        tip_y = rects[-1].bottom + 8
        theme.text(screen, hints.bar(("select", tr("Vibrieren"))),
                   theme.HINT, theme.TEXT_DIM, (x, tip_y))
        if n > PAD_SLOTS:
            theme.text(screen, tr("Nur die ersten {k} Controller werden genutzt.").format(k=PAD_SLOTS),
                       theme.HINT, theme.TEXT_FAINT, (x, tip_y + 26))

        y2 = tip_y + (56 if n > PAD_SLOTS else 32)
        theme.text(screen, tr("Belegung (fest):"), theme.LABEL, theme.TEXT_DIM, (x, y2))
        rows = [
            ("RT", "Gas"), ("LT", "Bremse / Rückwärts"), ("Linker Stick", "Lenken"),
            ("A", "Handbremse / Bestätigen"), ("B", "Zurück"),
            ("D-Pad / Stick", "Navigieren"), ("LB / RB", "Menü wechseln"),
        ]
        yy = y2 + 34
        for keys, desc in rows:
            theme.text(screen, tr(keys), theme.HINT, (230, 220, 160), (x, yy))
            theme.text(screen, tr(desc), theme.HINT, theme.TEXT_DIM, (x + 170, yy))
            yy += 30

    def _save_name(self) -> None:
        # Buffer the edited name; the "Ungespeicherte Änderungen" hint above the
        # Save button already signals the pending state, so no extra message.
        self._pending["username"] = self._name_input.text
        self.msg = ""

    def _dispatch(self, action) -> None:
        if action == "change_language":
            from src.core import i18n
            stepper = next((w for w in self._content_group.widgets
                            if getattr(w, "action", None) == "change_language"), None)
            if stepper:
                self._pending["language"] = i18n.LANGUAGES[stepper.index]
                self.msg = ""
        elif action == "quit_game":
            # Dieselbe Rueckfrage wie ESC im Hauptmenue — eine Stelle, nicht zwei.
            self.shell.beenden_bestaetigen()
        elif action == "vehicle_lab":
            self.shell.state_machine.transition("vehicle_lab", vehicle_config="rookie")
        elif action == "ki_labor":
            self.shell.state_machine.transition("dev")
        elif action == "change_menu_volume":
            self._pending["menu_volume"] = self._rohwert(action, 0)
            self.msg = ""
        elif action in ("change_sfx_menu_volume", "change_sfx_race_volume"):
            # Der Regler wirkt erst beim Speichern; zum Beurteilen muss man ihn
            # aber jetzt hören. Also einmal mit dem gerade eingestellten Wert
            # vorspielen — beim Rennregler mit einem Rennklang, sonst hört man
            # den falschen.
            feld = ("sfx_menu_volume" if action.endswith("menu_volume")
                    else "sfx_race_volume")
            vol = self._rohwert(action, 2 if feld == "sfx_menu_volume" else 3)
            self._pending[feld] = vol
            from src.core import sfx as _sfx
            # „car-wall" war hier der Aufprall gegen die Mauer — bei jedem
            # Reglerschritt einmal krachen zu lassen war nicht auszuhalten
            # (gemeldet 04.08.2026). Das Reifenquietschen ist der richtige
            # Vertreter für Rennklänge: es trägt, ohne zu erschrecken, und es
            # ist der Klang, den man im Rennen am häufigsten hört.
            probe, grund = (("click", 0.7) if feld == "sfx_menu_volume"
                            else ("tire-screeching-1", 0.5))
            _sfx.spielen(probe, grund * vol, bereich=_sfx.DIREKT)
            self.msg = ""
        elif action == "change_race_volume":
            self._pending["race_volume"] = self._rohwert(action, 1)
            self.msg = ""
        # --- Video actions -----------------------------------------------
        elif action == "change_resolution":
            from src.core import display
            self._pending["resolution"] = display.resolution_label_to_str(
                self._rohwert(action, 0))
            self.msg = ""
        elif action == "toggle_fullscreen":
            self._pending["fullscreen"] = self._rohwert(action, 1)
            self.msg = ""
        elif action == "change_fps":
            self._pending["fps_limit"] = self._rohwert(action, 2)
            self.msg = ""
        elif action == "change_texquality":
            self._pending["texture_quality"] = self._rohwert(action, 4)
            self.msg = ""
        elif action == "toggle_vsync":
            self._pending["vsync"] = self._rohwert(action, 3)
            self.msg = ""
        elif isinstance(action, str) and action.startswith("grafik_"):
            self._grafik_aendern(action)

    def _apply_pending(self) -> bool:
        """Persist and apply all buffered changes. Returns True on success."""
        p = self._pending
        if not p:
            return True
        # Validate username first if edited.
        if "username" in p:
            ok, m = profile.validate_username(p["username"].strip())
            if not ok:
                self.msg = m; self.msg_ok = False
                return False
        cur = profile.current()
        if "username" in p: profile.set_username(p["username"].strip())
        if "language" in p:
            from src.core import i18n
            i18n.set_language(p["language"]); cur.language = p["language"]
        if "menu_volume" in p: cur.set_menu_volume(p["menu_volume"])
        if "race_volume" in p: cur.set_race_volume(p["race_volume"])
        if "sfx_menu_volume" in p: cur.set_sfx_menu_volume(p["sfx_menu_volume"])
        if "sfx_race_volume" in p: cur.set_sfx_race_volume(p["sfx_race_volume"])
        if "fps_limit" in p: cur.fps_limit = p["fps_limit"]
        if "texture_quality" in p: cur.texture_quality = p["texture_quality"]
        video_changed = any(k in p for k in ("resolution", "fullscreen", "vsync"))
        if "resolution" in p: cur.resolution = p["resolution"]
        if "fullscreen" in p: cur.fullscreen = p["fullscreen"]
        if "vsync" in p: cur.vsync = p["vsync"]
        if "grafik" in p:
            # Wirkt sofort: Schatten, Nachbearbeitung und Reifenspuren lesen
            # die Werte in jedem Bild; was beim Laden einer Strecke entsteht
            # (Gelände, Gras, Deko), ab dem nächsten Rennen.
            from src.render3d import grafik
            cur.grafik = grafik.als_dict(grafik.aus_dict(p["grafik"]))
        cur.save()
        if video_changed:
            from src.core import display
            display.apply_settings(resolution=cur.resolution, fullscreen=cur.fullscreen, vsync=cur.vsync)
        self._pending = {}
        self._build_content()   # rebuild so labels/values reflect saved state
        self.msg = tr("Gespeichert."); self.msg_ok = True
        return True

    def update(self, dt: float) -> None:
        if self._name_input:
            self._name_input.update(dt)
        if self.osk:
            self.osk.update(dt)
        for idx in list(self._controller_flash.keys()):
            self._controller_flash[idx] -= dt
            if self._controller_flash[idx] <= 0:
                del self._controller_flash[idx]

    # ------------------------------------------------------------------
    def draw(self, screen: pygame.Surface, area: pygame.Rect) -> None:
        self.zurueck_zeichnen(screen, area)
        # Titel auf derselben Kante wie die Kategoriespalte darunter (x=80,
        # siehe _cat_rects). Der alte Versatz auf 290 war nur Platz fuer den
        # Zurueck-Knopf, der frueher oben links sass — der sitzt jetzt unten
        # links, und die Einrueckung blieb als Luecke stehen (gemeldet
        # 05.08.2026).
        theme.text(screen, tr("EINSTELLUNGEN"), theme.HEADER, theme.ACCENT, (80, 128))
        for i, r in enumerate(self._cat_rects()):
            active = (i == self.cat)
            # Nur eine leichte Fuellung (PANEL_LIGHT) unter dem Zeiger, deutlich
            # schwaecher als PANEL_SEL bei der gewaehlten Kategorie — hovern
            # waehlt seit 05.08.2026 nicht mehr aus, das macht nur noch der Klick.
            hover = r.collidepoint(display.mouse_pos())
            if active:
                if not self._focus_content and not self._save_focus:
                    fill = theme.PANEL_SEL
                    border_color = theme.ACCENT
                    text_color = theme.TEXT
                else:
                    fill = theme.PANEL_LIGHT
                    border_color = theme.BORDER
                    text_color = theme.TEXT_DIM
            else:
                fill = theme.PANEL_LIGHT if hover else theme.PANEL
                border_color = theme.BORDER
                text_color = theme.TEXT_DIM
                
            pygame.draw.rect(screen, fill, r, border_radius=8)
            pygame.draw.rect(screen, border_color, r, 2, border_radius=8)
            theme.text(screen, tr(self.categories[i]), theme.BODY,
                       text_color, (r.x + 20, r.centery - 14))

        name = self.categories[self.cat]
        if name == "Allgemein":
            theme.text(screen, tr("Benutzername"), theme.BODY, theme.TEXT_DIM, (560, 210))
            self._name_input.draw(screen, focused=self._focus_content)
            if self.osk:
                self.osk.draw(screen)
            else:
                self._content_group.draw(screen, focused=self._focus_content)
        elif name == "Steuerung":
            theme.text(screen, tr("Tastatur & Maus"), theme.HEADER, theme.TEXT, (560, 168))
            for i, r in enumerate(self._bind_rects()):
                aid, lbl, _dk = kb.ACTIONS[i]
                sel = self._focus_content and i == self._sel_bind
                pygame.draw.rect(screen, theme.PANEL_SEL if sel else theme.PANEL, r, border_radius=8)
                pygame.draw.rect(screen, theme.ACCENT if sel else theme.BORDER, r, 2, border_radius=8)
                theme.text(screen, tr(lbl), theme.BODY, theme.TEXT, (r.x + 18, r.centery - 14))
                capturing = (self._capture == aid)
                key_txt = tr("Taste drücken…") if capturing else kb.key_name(kb.get(aid))
                theme.text(screen, key_txt, theme.BODY,
                           theme.ACCENT if capturing else theme.TEXT, (r.right - 20, r.centery), midright=True)
            self._draw_controller_info(screen)
        elif name == "Dev-Mode":
            theme.text(screen, tr("Entwickler-Werkzeuge"), theme.BODY, theme.TEXT_DIM, (560, 190))
            self._content_group.draw(screen, focused=self._focus_content)
        elif name == "Video":
            theme.text(screen, tr("Video-Einstellungen"), theme.BODY, theme.TEXT_DIM, (560, 190))
            if self._content_group:
                self._content_group.draw(screen, focused=self._focus_content)
            theme.text(screen, tr("Grafik"), theme.BODY, theme.TEXT_DIM, (self.GRAFIK_X, 190))
            y = 630
            for hinweis in (tr("Änderungen werden erst mit SPEICHERN übernommen."),
                            tr("Texturqualität: Hoch = weiche Skalierung, Niedrig = schneller (weniger Mikroruckler)."),
                            tr("Grafik wirkt sofort; Gelände, Gras und Deko ab dem nächsten Rennen.")):
                for zeile in _umbrechen(hinweis, theme.HINT, 500):
                    theme.text(screen, zeile, theme.HINT, theme.TEXT_FAINT, (560, y))
                    y += 28
                y += 8
        elif name == "Audio":
            theme.text(screen, tr("Audio-Einstellungen"), theme.BODY, theme.TEXT_DIM, (560, 190))
            self._content_group.draw(screen, focused=self._focus_content)
        elif name == "Info":
            self._draw_info(screen)
        else:
            theme.text(screen, tr(name), theme.HEADER, theme.TEXT, (560, 176))
            y = 250
            for row in _SOON_ROWS.get(name, []):
                theme.text(screen, tr(row), theme.BODY, theme.DISABLED, (580, y))
                theme.text(screen, tr("Bald verfügbar"), theme.HINT, theme.TEXT_FAINT, (940, y + 4))
                y += 54

        if self.msg:
            col = theme.SUCCESS if self.msg_ok else theme.DANGER
            theme.text(screen, self.msg, theme.BODY, col, (560, area.bottom - 90))

        self._save_rect = pygame.Rect(area.right - 340, area.bottom - 96, 300, 60)
        hot = self._save_focus or self._save_rect.collidepoint(display.mouse_pos())
        if self._dirty:
            theme.text(screen, tr("Ungespeicherte Änderungen"), theme.HINT, theme.ACCENT,
                       (self._save_rect.centerx, self._save_rect.y - 20), center=True)
            fill = (70, 56, 22) if hot else (44, 38, 18)
            border, txt_col = theme.ACCENT_HOT if hot else theme.ACCENT, theme.TEXT
        else:
            fill = (36, 38, 48) if hot else (26, 28, 36)
            border = theme.ACCENT if hot else theme.DISABLED
            txt_col = theme.TEXT_DIM if hot else theme.DISABLED
        pygame.draw.rect(screen, fill, self._save_rect, border_radius=8)
        pygame.draw.rect(screen, border, self._save_rect, 3 if self._save_focus else 2, border_radius=8)
        theme.text(screen, tr("SPEICHERN"), theme.BODY, txt_col, self._save_rect.center, center=True)

        if self._leave_dialog is not None:
            self._leave_dialog.draw(screen)

        from src.ui import hints
        theme.text(screen, hints.bar(("back", tr("Zurück"))),
                   theme.HINT, theme.TEXT_DIM, (area.centerx, area.bottom - 40), center=True)
