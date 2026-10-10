"""Menühintergrund-Video: Entschlüsselung im Faden, Anzeige als OpenGL-Ebene.

Bis 1.0.1 entschlüsselte :class:`src.ui.video_player.VideoPlayer` die Bilder
zwar schon in einem Faden, rechnete sie aber auf die Größe der Oberfläche um,
blendete sie über eine pygame-Fläche ein und lud sie danach noch einmal als Teil
der ganzen Oberfläche hoch. Das Video kostete den Hauptfaden jedes Bild
(mehrere Millisekunden in 1440p), und ein Tabwechsel öffnete die Datei
**im** Hauptfaden (gemessen 125-160 ms Aussetzer, 10.10.2026).

Hier ist es getrennt:

* :class:`VideoStrom` — ein Hintergrundfaden öffnet die Datei, entschlüsselt
  Bild für Bild und legt sie, mit Anzeigezeit versehen, in eine **begrenzte**
  Warteschlange. Der Hauptfaden holt nur, was fällig ist; ist er langsam,
  werden Bilder übersprungen, nie wartet er auf den Faden.
* :class:`VideoEbene` — zeichnet das jeweils neueste Bild als Textur über das
  **ganze Fenster** (Zuschnitt statt Strecken, siehe :func:`zuschnitt`),
  mit Abdunklung, Randabdunklung und Überblendung beim Videowechsel — alles im
  Shader. Die Oberfläche (Menü) liegt darüber und läuft in voller Bildrate;
  das Video läuft mit seinen eigenen 30 Bildern.

Fällt OpenCV aus oder lässt sich die Datei nicht öffnen, meldet der Strom
``fehler``; das Menü zeigt dann sein Standbild.
"""
from __future__ import annotations

import threading
import time
import weakref
from collections import deque

import numpy as np

try:
    import cv2
    _HAVE_CV2 = True
except Exception:      # pragma: no cover - optionale Abhaengigkeit
    cv2 = None
    _HAVE_CV2 = False

try:                                             # pragma: no cover - Importpfad
    import moderngl
except ImportError:                              # pragma: no cover
    moderngl = None

#: cv2-Kennungen, falls cv2 fehlt (Tests mit einer Attrappe).
_PROP_FPS = getattr(cv2, "CAP_PROP_FPS", 5)
_PROP_POS = getattr(cv2, "CAP_PROP_POS_FRAMES", 1)

#: Wie viele fertige Bilder der Faden hoechstens vorhaelt.
TIEFE = 4

#: Dauer der Ueberblendung beim Videowechsel.
UEBERBLENDEN_S = 0.25

#: Ab so vielen Fehlschlaegen in Folge gilt das Video als kaputt.
_FEHLVERSUCHE = 40


def zuschnitt(fenster: tuple[int, int], video: tuple[int, int]) -> tuple[float, float]:
    """Sichtbarer Anteil des Videos je Achse, wenn es das Fenster **füllt**.

    Das Video wird nie gestreckt: es wird so skaliert, dass es das Fenster
    ganz bedeckt, und was übersteht, abgeschnitten (cover). Ist das Fenster
    breiter als das Video, bleibt die volle Breite sichtbar und oben/unten
    fällt etwas weg — und umgekehrt. Ergebnis ``(anteil_x, anteil_y)`` in
    0..1, mindestens einer davon ist 1.
    """
    fb, fh = max(1, int(fenster[0])), max(1, int(fenster[1]))
    vb, vh = max(1, int(video[0])), max(1, int(video[1]))
    fenster_a, video_a = fb / fh, vb / vh
    if fenster_a >= video_a:
        return (1.0, video_a / fenster_a)
    return (fenster_a / video_a, 1.0)


# ---------------------------------------------------------------------------
# Der Faden
# ---------------------------------------------------------------------------

_offene: "weakref.WeakSet[VideoStrom]" = weakref.WeakSet()


def _cv2_oeffnen(pfad: str):
    """Die Aufnahme öffnen, oder ``None``."""
    if not _HAVE_CV2:
        return None
    cap = cv2.VideoCapture(pfad)
    if not cap.isOpened():
        cap.release()
        return None
    return cap


class VideoStrom:
    """Ein Video, das ein Hintergrundfaden in seinem eigenen Takt entschlüsselt.

    Der Faden öffnet die Datei (auch das kostet 100 ms und mehr), liest Bild
    für Bild und versieht jedes mit seiner Anzeigezeit (Startzeit + Nummer ×
    Bilddauer). Er hält höchstens ``tiefe`` Bilder vor und wartet danach — das
    ist **sein** Warten, der Hauptfaden wartet nie. Am Ende der Datei springt
    er an den Anfang; die Clips sind so geschnitten, dass das nahtlos ist.

    ``oeffnen`` (Tests): Aufruf ``oeffnen(pfad)``, der etwas mit ``read``,
    ``set``, ``get`` und ``release`` wie ``cv2.VideoCapture`` liefert — oder
    ``None``. ``uhr``: Zeitquelle, vorgegeben ``time.perf_counter``.
    """

    def __init__(self, pfad: str, *, oeffnen=None, tiefe: int = TIEFE,
                 uhr=time.perf_counter) -> None:
        self.pfad = pfad
        self._oeffnen = oeffnen or _cv2_oeffnen
        self._uhr = uhr
        self._tiefe = max(1, int(tiefe))
        self._cv = threading.Condition()
        self._schlange: deque = deque()
        self._halt = False
        self._fehler = False
        self._fps = 30.0
        self._groesse: tuple[int, int] | None = None
        #: Bilder, die entschluesselt, aber nie angezeigt wurden (Hauptfaden zu langsam).
        self.uebersprungen = 0
        self._gemeldet = False
        self._faden = threading.Thread(target=self._lauf, name="video-decode", daemon=True)
        _offene.add(self)
        self._faden.start()

    # -- Auskunft ------------------------------------------------------------
    @property
    def fehler(self) -> bool:
        """Die Datei liess sich nicht öffnen oder nicht (mehr) lesen."""
        return self._fehler

    @property
    def groesse(self) -> tuple[int, int] | None:
        """``(breite, hoehe)`` des Videos, sobald das erste Bild da ist."""
        return self._groesse

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def lebt(self) -> bool:
        return self._faden.is_alive()

    @property
    def wartende(self) -> int:
        with self._cv:
            return len(self._schlange)

    # -- Hauptfaden ------------------------------------------------------------
    def neuestes(self):
        """Das jetzt fällige Bild (BGR, ``uint8``, ``(h, w, 3)``), oder ``None``.

        ``None`` heißt: seit dem letzten Aufruf ist kein neues Bild fällig —
        das zuletzt gezeigte bleibt stehen. Sind mehrere fällig (der Aufrufer
        war langsam), zählt das neueste; die übrigen sind übersprungen.
        """
        jetzt = self._uhr()
        bild = None
        with self._cv:
            while self._schlange and self._schlange[0][0] <= jetzt:
                eintrag = self._schlange.popleft()
                if bild is not None:
                    self.uebersprungen += 1
                bild = eintrag[1]
            if bild is not None:
                self._cv.notify_all()
        return bild

    def close(self, warten: bool = False) -> None:
        """Den Faden anhalten. Ohne ``warten`` kehrt der Aufruf sofort zurück.

        Der Faden gibt die Aufnahme selbst frei, sobald er aus ``read``
        zurück ist; ``close`` fasst sie nicht an (sonst stürzte ein
        gleichzeitiges ``release`` ab). ``warten=True`` wartet bis zu zwei
        Sekunden auf sein Ende (Beenden des Spiels, Tests).
        """
        with self._cv:
            self._halt = True
            self._schlange.clear()
            self._cv.notify_all()
        if warten and self._faden is not threading.current_thread():
            self._faden.join(timeout=2.0)

    # -- Hintergrundfaden ---------------------------------------------------------
    def _lauf(self) -> None:
        cap = None
        try:
            cap = self._oeffnen(self.pfad)
            if cap is None:
                self._fehler = True
                return
            fps = cap.get(_PROP_FPS)
            if fps and fps > 1:
                self._fps = float(fps)
            dauer = 1.0 / self._fps
            start = None
            nummer = 0
            fehlschlaege = 0
            while not self._halt:
                ok, bild = cap.read()
                if not ok or bild is None:
                    # Ende der Datei: von vorn. Gelingt auch das nicht, kurz
                    # warten — ein Fehlschlag darf das Video nicht einfrieren.
                    cap.set(_PROP_POS, 0)
                    ok, bild = cap.read()
                    if not ok or bild is None:
                        fehlschlaege += 1
                        if fehlschlaege >= _FEHLVERSUCHE:
                            self._fehler = True
                            return
                        with self._cv:
                            self._cv.wait(0.05)
                        continue
                fehlschlaege = 0
                if start is None:
                    start = self._uhr()
                    self._groesse = (int(bild.shape[1]), int(bild.shape[0]))
                anzeige = start + nummer * dauer
                nummer += 1
                with self._cv:
                    while len(self._schlange) >= self._tiefe and not self._halt:
                        self._cv.wait(0.05)
                    if self._halt:
                        return
                    self._schlange.append((anzeige, bild))
        except Exception as fehler:
            self._fehler = True
            if not self._gemeldet:
                self._gemeldet = True
                print(f"[video] Entschluesseln fehlgeschlagen ({self.pfad}): {fehler!r}")
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass



def alle_beenden(timeout: float = 2.0) -> None:
    """Alle noch laufenden Videofäden anhalten und auf ihr Ende warten (beim Beenden)."""
    strome = list(_offene)
    for strom in strome:
        strom.close()
    ende = time.perf_counter() + timeout
    for strom in strome:
        rest = ende - time.perf_counter()
        if rest > 0 and strom._faden.is_alive():
            strom._faden.join(rest)


# ---------------------------------------------------------------------------
# Die Ebene
# ---------------------------------------------------------------------------

_VERTEX = """
#version 330
in vec2 in_position;
in vec2 in_uv;
out vec2 uv;
void main() {
    // Senkrecht gespiegelt: Zeile 0 des Videos liegt oben, OpenGL zaehlt
    // Texturzeilen von unten.
    uv = vec2(in_uv.x, 1.0 - in_uv.y);
    gl_Position = vec4(in_position, 0.0, 1.0);
}
"""

_FRAGMENT = """
#version 330
uniform sampler2D vorn;
uniform sampler2D hinten;
uniform vec2 anteil_vorn;      // sichtbarer Anteil je Achse (Zuschnitt)
uniform vec2 anteil_hinten;
uniform float hinten_menge;    // 0 = nur vorn, 1 = nur hinten (Ueberblendung)
uniform bool hat_bild;
uniform float abdunkeln;       // gleichmaessiger schwarzer Ueberzug, 0..1
uniform float vignette;        // Staerke der Randabdunklung, 0..1
uniform vec2 raster;           // virtuelle Flaeche in Rasterpunkten
in vec2 uv;
out vec4 farbe;
void main() {
    vec3 c = vec3(0.035, 0.04, 0.055);
    if (hat_bild) {
        c = texture(vorn, (uv - 0.5) * anteil_vorn + 0.5).rgb;
        if (hinten_menge > 0.0) {
            vec3 h = texture(hinten, (uv - 0.5) * anteil_hinten + 0.5).rgb;
            c = mix(c, h, hinten_menge);
        }
    }
    // Die Randabdunklung gilt dem 16:9-Bereich (Ecke = 1) und laeuft
    // darueber hinaus weiter, damit am Fensterrand kein heller Streifen bleibt.
    vec2 p = (uv - 0.5) * raster;
    float d = min(length(p) / 1101.9, 1.25);
    float dunkel = 1.0 - (1.0 - abdunkeln) * (1.0 - vignette * d * d);
    farbe = vec4(c * (1.0 - dunkel), 1.0);
}
"""

#: Wie schnell Abdunklung und Randabdunklung zu einem neuen Wert laufen (je Sekunde).
_ANGLEICH = 14.0


class VideoEbene:
    """Zeichnet das Video eines :class:`VideoStrom` als Textur hinter die Oberfläche.

    Das Menü ruft in jedem Bild :meth:`zeigen`; :mod:`src.core.display` ruft
    danach :meth:`zeichnen` — vor der Überlagerung der pygame-Fläche. Wer
    :meth:`zeigen` in einem Bild nicht aufruft, hat dort kein Video (ein Rennen
    zeigt nie das Menüvideo).

    Zwei Texturen: ``vorn`` und ``hinten``. Kommt das erste Bild eines **neuen**
    Stroms an, wird getauscht — das alte Video liegt jetzt hinten und blendet
    in :data:`UEBERBLENDEN_S` aus. Bis das erste Bild des neuen Stroms da ist
    (die Datei öffnet im Faden), steht das alte unverändert; es gibt keinen
    Aussetzer beim Tabwechsel.
    """

    def __init__(self, ctx) -> None:
        self._ctx = ctx
        self._programm = ctx.program(vertex_shader=_VERTEX, fragment_shader=_FRAGMENT)
        daten = np.array([[-1, -1, 0, 0], [1, -1, 1, 0], [-1, 1, 0, 1], [1, 1, 1, 1]], dtype="f4")
        self._vbo = ctx.buffer(daten.tobytes())
        self._vao = ctx.vertex_array(self._programm, [
            (self._vbo, "2f 2f", "in_position", "in_uv")])
        self._programm["vorn"].value = 0
        self._programm["hinten"].value = 1
        self._tex: list = [None, None]          # je (Textur, (b, h))
        self._vorn = 0
        self._strom_vorn = None
        self._hat_hinten = False
        self._tausch_zeit = 0.0
        self._anfrage = None
        self._dim = [0.0, 0.0]
        self._zuletzt = 0.0
        #: Wie oft ein Bild hochgeladen wurde (Messung, Tests).
        self.hochgeladen = 0

    # -- Menue ----------------------------------------------------------------
    def zeigen(self, strom, abdunkeln: float = 0.0, vignette: float = 0.0) -> None:
        """Dieses Bild das Video von ``strom`` zeigen. ``abdunkeln``/``vignette`` in 0..1."""
        self._anfrage = (strom, float(abdunkeln), float(vignette))

    @property
    def hat_bild(self) -> bool:
        return self._tex[self._vorn] is not None

    # -- Anzeige ----------------------------------------------------------------
    def zeichnen(self, fenster: tuple[int, int], raster: tuple[int, int]) -> None:
        """Das Video über das ganze Fenster legen (ohne Mischung, ohne Tiefentest)."""
        anfrage, self._anfrage = self._anfrage, None
        if anfrage is None:
            return
        strom, abdunkeln, vignette = anfrage
        jetzt = time.perf_counter()

        bild = strom.neuestes() if strom is not None else None
        if bild is not None:
            if strom is not self._strom_vorn:
                if self._tex[self._vorn] is not None:
                    self._vorn = 1 - self._vorn           # das alte Bild liegt jetzt hinten
                    self._hat_hinten = True
                    self._tausch_zeit = jetzt
                self._strom_vorn = strom
            self._hochladen(self._vorn, bild)

        # Abdunklung gleitet, statt zu springen (Seite auf/zu).
        if jetzt - self._zuletzt > 0.5:
            self._dim = [abdunkeln, vignette]
        else:
            k = 1.0 - np.exp(-_ANGLEICH * (jetzt - self._zuletzt))
            self._dim = [a + (z - a) * k for a, z in zip(self._dim, (abdunkeln, vignette))]
        self._zuletzt = jetzt

        menge = 0.0
        if self._hat_hinten:
            menge = 1.0 - (jetzt - self._tausch_zeit) / UEBERBLENDEN_S
            if menge <= 0.0:
                self._hat_hinten, menge = False, 0.0

        vorn, hinten = self._tex[self._vorn], self._tex[1 - self._vorn]
        p = self._programm
        p["hat_bild"].value = vorn is not None
        if vorn is not None:
            vorn[0].use(0)
            p["anteil_vorn"].value = zuschnitt(fenster, vorn[1])
        p["hinten_menge"].value = menge if (menge > 0.0 and hinten is not None) else 0.0
        if hinten is not None and menge > 0.0:
            hinten[0].use(1)
            p["anteil_hinten"].value = zuschnitt(fenster, hinten[1])
        p["abdunkeln"].value = float(min(1.0, max(0.0, self._dim[0])))
        p["vignette"].value = float(min(1.0, max(0.0, self._dim[1])))
        p["raster"].value = (float(raster[0]), float(raster[1]))
        ctx = self._ctx
        ctx.disable(moderngl.DEPTH_TEST)
        ctx.disable(moderngl.BLEND)
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def _hochladen(self, platz: int, bild) -> None:
        h, b = bild.shape[:2]
        eintrag = self._tex[platz]
        if eintrag is None or eintrag[1] != (b, h):
            if eintrag is not None:
                eintrag[0].release()
            textur = self._ctx.texture((b, h), 3)
            textur.filter = (moderngl.LINEAR, moderngl.LINEAR)
            textur.repeat_x = textur.repeat_y = False
            textur.swizzle = "BGR1"           # cv2 liefert BGR; kein Umrechnen auf der CPU
            eintrag = self._tex[platz] = (textur, (b, h))
        eintrag[0].write(np.ascontiguousarray(bild))
        self.hochgeladen += 1

    def freigeben(self) -> None:
        for eintrag in self._tex:
            if eintrag is not None:
                eintrag[0].release()
        self._tex = [None, None]
        for teil in (self._vao, self._vbo, self._programm):
            teil.release()


# ---------------------------------------------------------------------------
# Gemeinsamer Hintergrund fuer alle Vollbildzustaende
# ---------------------------------------------------------------------------

class HintergrundVideo:
    """Das Menuevideo als Hintergrund fuer Zustaende ausserhalb der Menueschale.

    Streckenwahl, Fahrzeugwahl, Online-Strecken, Willkommen, Ladebild: alle
    hatten einen eigenen, flachen Hintergrund und liessen neben dem sicheren
    16:9-Bereich eine dunkle Flaeche stehen. Jetzt zeigen sie dasselbe Video
    wie das Menue, ueber das ganze Fenster (:class:`VideoEbene`). Der Zustand
    ruft in jedem Bild :meth:`zeigen` und zeichnet nichts dahinter.

    Der Strom bleibt :data:`LEERLAUF_S` Sekunden nach dem letzten Aufruf
    offen — beim Wechsel zwischen zwei Zustaenden oeffnet nichts neu — und
    wird dann von :meth:`aufraeumen` (jedes Bild, aus ``display``) geschlossen.
    """

    LEERLAUF_S = 3.0

    def __init__(self, ordner: str = "data/menu", uhr=time.perf_counter) -> None:
        self._ordner = ordner
        self._uhr = uhr
        self._strom: VideoStrom | None = None
        self._stem: str | None = None
        self._zuletzt = 0.0

    @property
    def strom(self):
        return self._strom

    def zeigen(self, ebene, stem: str, abdunkeln: float = 0.59, vignette: float = 0.0) -> bool:
        """Das Video ``stem`` zeigen. ``False``: keins verfuegbar — der Aufrufer malt selbst."""
        import os
        if ebene is None:
            return False
        if stem != self._stem or self._strom is None:
            self._schliessen()
            self._stem = stem
            pfad = os.path.join(self._ordner, f"{stem}.mp4")
            if os.path.isfile(pfad):
                try:
                    self._strom = VideoStrom(pfad)
                except Exception:
                    self._strom = None
        if self._strom is None or self._strom.fehler:
            return False
        self._zuletzt = self._uhr()
        ebene.zeigen(self._strom, abdunkeln, vignette)
        return True

    def aufraeumen(self) -> None:
        if self._strom is not None and self._uhr() - self._zuletzt > self.LEERLAUF_S:
            self._schliessen()
            self._stem = None

    def _schliessen(self) -> None:
        if self._strom is not None:
            self._strom.close()
            self._strom = None
