"""Entwurfsbilder fuer die Profilseite (Releaseplan E5, Schritt 3).

Drei Varianten derselben Seite: Statistik aus E1 und die 28 Erfolge aus E1a,
sichtbar nur im eigenen Profil (so am 02.08.2026 entschieden), als siebter Tab
in der Menueleiste.

Wie bei den Lack- und Klang-Entwuerfen ist nichts erfunden: die Erfolgsliste
kommt aus ``src.core.statistik.ERFOLGE``, welche offen sind rechnet
``statistik.erreicht()``, und die Fortschrittszahlen kommen aus
``statistik.stand()``. Wer einen Erfolg aendert, sieht die Wirkung hier sofort,
ohne das Spiel zu starten.

    python tools/profil_entwurf.py            # nach Documentation/entwurf/
    python tools/profil_entwurf.py /tmp/x     # woanders hin
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

pygame.init()
pygame.display.set_mode((1920, 1080))

from src.core import statistik  # noqa: E402
from src.ui import theme  # noqa: E402

W, H = 1920, 1080
TAB_H = 108
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join("Documentation", "entwurf")

#: Ein Spielstand, wie er nach ein paar Wochen aussieht — genug, dass ein Teil
#: offen ist und ein Teil kurz davor. Ein leeres Profil zeigte nur Nullen und
#: liesse den Entwurf nicht beurteilen.
BEISPIEL = dict(statistik.VORGABE)
BEISPIEL.update({
    "rennen": 47, "siege": 12, "podeste": 26,
    "meter": 184_300.0, "spielzeit_s": 6 * 3600 + 12 * 60,
    "gp_siege": 2,
    "ghosts_geschlagen": ["oval", "desert"],
    "strecken_gefahren": ["oval", "desert", "city", "rundkurs"],
    "fahrzeuge_gefahren": ["rookie", "rookie_2", "supercar", "supercar_2",
                           "drifter", "limousine", "electric"],
    "klassen_gewonnen": ["Hatchback", "Rennfahrzeug", "Drifter"],
    "start_ziel_siege": 4, "aufholjagden": 1, "schnellste_runden": 9,
    "online_rennen": 6, "online_siege": 2, "lobbys_gehostet": 1,
    "strecken_geteilt": 0, "fremde_strecken_gefahren": 3,
    "strecken_erstellt": 2, "strecken_veroeffentlicht": 1,
    "eigene_strecke_gefahren": 5, "eigene_strecke_gewonnen": 2,
})

BESTZEITEN = [("Oval", 16.214), ("Wüste", 27.084), ("Stadt", 30.236),
              ("Rundkurs", 56.066), ("Strecke 1", 88.110)]

NAME = "philip"

_TABS = ["EINZELSPIELER", "MEHRSPIELER LOKAL", "MEHRSPIELER ONLINE",
         "STRECKENEDITOR", "WERKSTATT", "PROFIL", "EINSTELLUNGEN"]


# ---------------------------------------------------------------------------
# Daten
# ---------------------------------------------------------------------------
def offen() -> set[str]:
    return statistik.erreicht(BEISPIEL)


def gruppen() -> list[tuple[str, list]]:
    """Erfolge nach Gruppe, Reihenfolge wie in ERFOLGE."""
    aus: list[tuple[str, list]] = []
    for eintrag in statistik.ERFOLGE:
        gruppe = eintrag[1]
        if not aus or aus[-1][0] != gruppe:
            aus.append((gruppe, []))
        aus[-1][1].append(eintrag)
    return aus


def zeit(sekunden: float) -> str:
    h = int(sekunden // 3600)
    m = int((sekunden % 3600) // 60)
    return f"{h} h {m:02d} min"


def kennzahlen() -> list[tuple[str, str]]:
    b = BEISPIEL
    return [
        ("Rennen", str(b["rennen"])),
        ("Siege", str(b["siege"])),
        ("Podeste", str(b["podeste"])),
        ("Grand Prix", str(b["gp_siege"])),
        ("Strecke", f"{b['meter'] / 1000:.0f} km"),
        ("Zeit am Steuer", zeit(b["spielzeit_s"])),
    ]


# ---------------------------------------------------------------------------
# Zeichenhelfer — Optik wie tools/lack_entwurf.py
# ---------------------------------------------------------------------------
_schild: dict[str, tuple[str, str, str]] = {}


def variantenschild(nr, titel, untertitel):
    _schild["aktuell"] = (nr, titel, untertitel)


def mit_band(s: pygame.Surface) -> pygame.Surface:
    nr, titel, untertitel = _schild.get("aktuell", ("?", "", ""))
    band = 104
    out = pygame.Surface((W, H + band))
    out.fill((8, 9, 14))
    out.blit(s, (0, 0))
    pygame.draw.line(out, theme.ACCENT_DIM, (0, H), (W, H), 2)
    theme.text(out, f"VARIANTE {nr}  —  {titel}", theme.HEADER, theme.ACCENT, (40, H + 18))
    theme.text(out, untertitel, theme.BODY, theme.TEXT_DIM, (40, H + 62), max_w=W - 80)
    return out


def hintergrund(s):
    theme.draw_background(s)
    s.blit(theme.vignette((W, H), 110), (0, 0))
    dunkel = pygame.Surface((W, H), pygame.SRCALPHA)
    dunkel.fill((0, 0, 0, 150))
    s.blit(dunkel, (0, 0))


def tableiste(s, aktiv=5):
    """Sieben Tabs — die Breite kommt aus der Anzahl, nicht aus einer Konstante.

    Mit den bisherigen 288 px waeren sieben Tabs 2064 px breit und passten nicht
    mehr. Deshalb rechnet die Leiste ab jetzt: (Rand abziehen, durch Anzahl).
    """
    luecke, th = 8, 60
    tw = (W - 80 - (len(_TABS) - 1) * luecke) // len(_TABS)
    gesamt = len(_TABS) * tw + (len(_TABS) - 1) * luecke
    x0 = W // 2 - gesamt // 2
    for i, lbl in enumerate(_TABS):
        r = pygame.Rect(x0 + i * (tw + luecke), 28, tw, th)
        an = (i == aktiv)
        flaeche = pygame.Surface(r.size, pygame.SRCALPHA)
        flaeche.fill((44, 40, 24, 200) if an else (28, 30, 40, 180))
        s.blit(flaeche, r.topleft)
        pygame.draw.rect(s, theme.ACCENT if an else theme.BORDER, r,
                         2 if an else 1, border_radius=6)
        theme.text_fit(s, lbl, theme.LABEL,
                       theme.TEXT if an else theme.TEXT_FAINT,
                       r.inflate(-12, 0), center=True)


def panel(s, r: pygame.Rect, *, alpha=195, rand=(46, 50, 62)):
    flaeche = pygame.Surface(r.size, pygame.SRCALPHA)
    flaeche.fill((10, 12, 22, alpha))
    s.blit(flaeche, r.topleft)
    pygame.draw.rect(s, rand, r, 1, border_radius=6)


def kachel(s, r: pygame.Rect, titel: str, wert: str):
    panel(s, r, alpha=205)
    theme.text(s, titel.upper(), theme.SMALL, theme.TEXT_FAINT, (r.x + 14, r.y + 12))
    theme.text_fit(s, wert, theme.TITLE, theme.ACCENT,
                   pygame.Rect(r.x + 12, r.y + 34, r.width - 24, r.height - 44),
                   center=True)


def balken(s, r: pygame.Rect, anteil: float, *, farbe=None):
    pygame.draw.rect(s, (28, 31, 40), r, border_radius=r.height // 2)
    pygame.draw.rect(s, (50, 54, 68), r, 1, border_radius=r.height // 2)
    breit = int(r.width * max(0.0, min(1.0, anteil)))
    if breit > 2:
        pygame.draw.rect(s, farbe or theme.ACCENT, (r.x, r.y, breit, r.height),
                         border_radius=r.height // 2)


def haken(s, mitte, groesse, farbe):
    """Erledigt-Zeichen. Gezeichnet statt getippt — ein Haken als Schriftzeichen
    fehlt in der Schrift und kaeme als leerer Kasten heraus."""
    x, y = mitte
    g = groesse
    pygame.draw.lines(s, farbe, False,
                      [(x - g, y), (x - g * 0.25, y + g * 0.7), (x + g, y - g * 0.8)], 3)


def erfolgszeile(s, r: pygame.Rect, eintrag, *, kompakt=False):
    """Ein Erfolg: Zustand, Name, Bedingung, Fortschritt.

    Der Fortschritt steht als Zahl da, nicht nur als Balken — „7 / 20" sagt,
    ob man kurz davor ist; ein halber Balken sagt das nicht.
    """
    key, _gruppe, name, text, _q, _z = eintrag
    wert, ziel = statistik.stand(key, BEISPIEL)
    fertig = wert >= ziel

    if fertig:
        pygame.draw.circle(s, (34, 60, 42), (r.x + 18, r.centery), 13)
        haken(s, (r.x + 18, r.centery), 6, theme.SUCCESS)
    else:
        pygame.draw.circle(s, (30, 33, 44), (r.x + 18, r.centery), 13)
        pygame.draw.circle(s, (60, 64, 80), (r.x + 18, r.centery), 13, 1)

    nx = r.x + 42
    theme.text(s, name, theme.LABEL if not kompakt else theme.HINT,
               theme.TEXT if fertig else theme.TEXT_DIM, (nx, r.y + 2))
    if not kompakt:
        theme.text(s, text, theme.SMALL, theme.TEXT_FAINT, (nx, r.y + 28))

    if fertig:
        theme.text(s, "erreicht", theme.SMALL, theme.SUCCESS,
                   (r.right - 8, r.y + 4), topright=True)
    else:
        theme.text(s, f"{wert} / {ziel}", theme.SMALL, theme.ACCENT_DIM,
                   (r.right - 8, r.y + 4), topright=True)
        bb = pygame.Rect(r.right - 150, r.y + (26 if not kompakt else 24), 142, 6)
        balken(s, bb, wert / max(1, ziel), farbe=theme.ACCENT_DIM)


# ===========================================================================
# Variante A — Zwei Spalten: links die Zahlen, rechts die Erfolge
# ===========================================================================
def profil_a():
    s = pygame.Surface((W, H))
    hintergrund(s)
    tableiste(s)

    theme.text(s, NAME, theme.HEADER, theme.ACCENT, (40, TAB_H + 4))
    fertig, gesamt = len(offen()), len(statistik.ERFOLGE)
    theme.text(s, f"{fertig} von {gesamt} Erfolgen", theme.BODY, theme.TEXT_DIM,
               (40, TAB_H + 54))
    balken(s, pygame.Rect(300, TAB_H + 62, 300, 10), fertig / gesamt)

    # -- linke Spalte: Kennzahlen und Bestzeiten
    links = pygame.Rect(40, TAB_H + 104, 720, H - TAB_H - 154)
    kx, ky = links.x, links.y
    for i, (titel, wert) in enumerate(kennzahlen()):
        r = pygame.Rect(kx + (i % 3) * 244, ky + (i // 3) * 118, 232, 106)
        kachel(s, r, titel, wert)
    ky += 2 * 118 + 14

    best = pygame.Rect(links.x, ky, 720, links.bottom - ky)
    panel(s, best)
    theme.text(s, "BESTZEITEN", theme.HINT, theme.TEXT_DIM, (best.x + 16, best.y + 14))
    y = best.y + 52
    for name, t in BESTZEITEN:
        theme.text(s, name, theme.BODY, theme.TEXT, (best.x + 20, y))
        theme.text(s, f"{t:.3f} s", theme.BODY, theme.ACCENT,
                   (best.right - 20, y), topright=True)
        pygame.draw.line(s, (34, 38, 50), (best.x + 16, y + 38),
                         (best.right - 16, y + 38), 1)
        y += 50

    # -- rechte Spalte: Erfolge
    rechts = pygame.Rect(links.right + 24, TAB_H + 104, W - links.right - 64,
                         H - TAB_H - 154)
    panel(s, rechts)
    y = rechts.y + 16
    for gruppe, eintraege in gruppen():
        theme.text(s, gruppe.upper(), theme.HINT, theme.ACCENT_DIM, (rechts.x + 18, y))
        y += 28
        for e in eintraege[:4]:
            erfolgszeile(s, pygame.Rect(rechts.x + 18, y, rechts.width - 36, 44),
                         e, kompakt=True)
            y += 40
        y += 10
        if y > rechts.bottom - 80:
            break
    theme.text(s, "▼  weiter blättern", theme.SMALL, theme.TEXT_FAINT,
               (rechts.centerx, rechts.bottom - 24), center=True)

    variantenschild("A", "Zwei Spalten — Zahlen links, Erfolge rechts",
                    "Die Statistik steht als Kachelblock zusammen, die Erfolge laufen rechts als Liste "
                    "durch. Alles auf einen Blick, aber die Erfolgsliste wird schmal und muss blättern.")
    return s


# ===========================================================================
# Variante B — Kennzahlenband oben, Erfolge als Karten darunter
# ===========================================================================
def profil_b():
    s = pygame.Surface((W, H))
    hintergrund(s)
    tableiste(s)

    kopf = pygame.Rect(40, TAB_H + 4, W - 80, 132)
    panel(s, kopf, alpha=205)
    theme.text(s, NAME, theme.HEADER, theme.ACCENT, (kopf.x + 22, kopf.y + 16))
    fertig, gesamt = len(offen()), len(statistik.ERFOLGE)
    theme.text(s, f"{fertig} von {gesamt} Erfolgen", theme.SMALL, theme.TEXT_DIM,
               (kopf.x + 22, kopf.y + 74))
    balken(s, pygame.Rect(kopf.x + 22, kopf.y + 100, 260, 10), fertig / gesamt)

    zahlen = kennzahlen()
    bx = kopf.x + 320
    breite = (kopf.right - bx - 20) // len(zahlen)
    for i, (titel, wert) in enumerate(zahlen):
        x = bx + i * breite
        theme.text(s, titel.upper(), theme.SMALL, theme.TEXT_FAINT, (x, kopf.y + 26))
        theme.text_fit(s, wert, theme.HEADER, theme.TEXT,
                       pygame.Rect(x, kopf.y + 52, breite - 16, 52))
        if i:
            pygame.draw.line(s, (38, 42, 54), (x - 14, kopf.y + 24),
                             (x - 14, kopf.bottom - 20), 1)

    # -- Erfolge als Karten, drei Spalten
    bereich = pygame.Rect(40, kopf.bottom + 16, W - 80, H - kopf.bottom - 66)
    spalten, luecke = 3, 16
    sb = (bereich.width - (spalten - 1) * luecke) // spalten
    spalte_y = [bereich.y] * spalten
    # In die jeweils kuerzeste Spalte setzen, nicht reihum: die Gruppen sind
    # verschieden lang, und reihum blieb "Erkunden" hinter der langen
    # Mengen-Karte haengen und fiel ganz aus dem Bild.
    for gruppe, eintraege in gruppen():
        sp = min(range(spalten), key=lambda k: spalte_y[k])
        hoehe = 44 + len(eintraege) * 52
        r = pygame.Rect(bereich.x + sp * (sb + luecke), spalte_y[sp], sb, hoehe)
        if r.bottom > bereich.bottom:
            continue
        panel(s, r)
        theme.text(s, gruppe.upper(), theme.HINT, theme.ACCENT_DIM, (r.x + 16, r.y + 12))
        y = r.y + 42
        for e in eintraege:
            erfolgszeile(s, pygame.Rect(r.x + 14, y, r.width - 28, 46), e)
            y += 52
        spalte_y[sp] = r.bottom + luecke

    theme.text(s, "Bestzeiten je Strecke stehen im Reiter EINZELSPIELER",
               theme.SMALL, theme.TEXT_FAINT, (bereich.x + 4, bereich.bottom + 8))

    variantenschild("B", "Kennzahlenband oben, Erfolge als Karten",
                    "Die Zahlen liegen als Band über der Seite, darunter die Erfolge nach Gruppen in "
                    "Karten. Jeder Erfolg hat Platz für seine Bedingung — dafür müssen die Bestzeiten woanders hin.")
    return s


# ===========================================================================
# Variante C — Vitrine: was fehlt, steht oben
# ===========================================================================
def profil_c():
    s = pygame.Surface((W, H))
    hintergrund(s)
    tableiste(s)

    fertig, gesamt = len(offen()), len(statistik.ERFOLGE)
    kopf = pygame.Rect(40, TAB_H + 4, W - 80, 96)
    panel(s, kopf, alpha=205)
    theme.text(s, NAME, theme.HEADER, theme.ACCENT, (kopf.x + 22, kopf.y + 12))
    theme.text(s, f"{fertig} von {gesamt} Erfolgen", theme.BODY, theme.TEXT,
               (kopf.x + 22, kopf.y + 56))
    bb = pygame.Rect(kopf.x + 300, kopf.y + 44, kopf.width - 340, 14)
    balken(s, bb, fertig / gesamt)
    theme.text(s, f"{int(100 * fertig / gesamt)} %", theme.LABEL, theme.ACCENT,
               (bb.right, kopf.y + 12), topright=True)

    # -- Was als Nächstes drin ist: die drei mit dem höchsten Anteil
    offen_liste = [e for e in statistik.ERFOLGE if e[0] not in offen()]
    def anteil(e):
        w, z = statistik.stand(e[0], BEISPIEL)
        return w / max(1, z)
    naechste = sorted(offen_liste, key=anteil, reverse=True)[:3]

    naechst = pygame.Rect(40, kopf.bottom + 14, W - 80, 132)
    panel(s, naechst, rand=theme.ACCENT_DIM)
    theme.text(s, "KURZ DAVOR", theme.HINT, theme.ACCENT, (naechst.x + 18, naechst.y + 12))
    breite = (naechst.width - 40) // 3
    for i, e in enumerate(naechste):
        r = pygame.Rect(naechst.x + 18 + i * breite, naechst.y + 46, breite - 20, 60)
        w, z = statistik.stand(e[0], BEISPIEL)
        theme.text(s, e[2], theme.LABEL, theme.TEXT, (r.x, r.y))
        theme.text(s, f"noch {z - w}", theme.SMALL, theme.ACCENT,
                   (r.right - 4, r.y + 4), topright=True)
        balken(s, pygame.Rect(r.x, r.y + 34, r.width - 4, 8), w / max(1, z))
        theme.text(s, e[3], theme.SMALL, theme.TEXT_FAINT, (r.x, r.y + 46),
                   max_w=r.width - 60)

    # -- Zahlen als schmale Zeile
    zeile = pygame.Rect(40, naechst.bottom + 14, W - 80, 92)
    panel(s, zeile)
    zahlen = kennzahlen() + [("Ghosts geschlagen", str(len(BEISPIEL["ghosts_geschlagen"])))]
    b = (zeile.width - 32) // len(zahlen)
    for i, (titel, wert) in enumerate(zahlen):
        x = zeile.x + 16 + i * b
        theme.text(s, titel.upper(), theme.SMALL, theme.TEXT_FAINT, (x, zeile.y + 16))
        theme.text_fit(s, wert, theme.HEADER, theme.TEXT,
                       pygame.Rect(x, zeile.y + 40, b - 14, 44))
        if i:
            pygame.draw.line(s, (38, 42, 54), (x - 12, zeile.y + 14),
                             (x - 12, zeile.bottom - 14), 1)

    # -- Alle Erfolge, kompakt in zwei Spalten
    unten = pygame.Rect(40, zeile.bottom + 14, W - 80, H - zeile.bottom - 64)
    # Drei Spalten: mit zweien fiel die letzte Gruppe unten heraus.
    n_sp = 3
    spalte_b = (unten.width - (n_sp - 1) * 16) // n_sp
    spalten_y = [unten.y] * n_sp
    for gruppe, eintraege in gruppen():
        sp = min(range(n_sp), key=lambda k: spalten_y[k])
        hoehe = 34 + len(eintraege) * 32
        r = pygame.Rect(unten.x + sp * (spalte_b + 16), spalten_y[sp], spalte_b, hoehe)
        if r.bottom > unten.bottom:
            continue
        theme.text(s, gruppe.upper(), theme.SMALL, theme.ACCENT_DIM, (r.x + 4, r.y + 6))
        y = r.y + 30
        for e in eintraege:
            erfolgszeile(s, pygame.Rect(r.x + 4, y, r.width - 8, 30), e, kompakt=True)
            y += 32
        spalten_y[sp] = r.bottom + 12

    # Unter den Spalten ist Platz — dort passen die Bestzeiten noch hin. Damit
    # zeigt diese Variante als einzige alles ohne Blaettern.
    best_y = max(spalten_y) + 6
    if best_y < unten.bottom - 80:
        best = pygame.Rect(unten.x, best_y, unten.width, unten.bottom - best_y)
        panel(s, best)
        theme.text(s, "BESTZEITEN", theme.HINT, theme.TEXT_DIM,
                   (best.x + 16, best.y + 12))
        b = (best.width - 32) // len(BESTZEITEN)
        for i, (name, zeit_s) in enumerate(BESTZEITEN):
            x = best.x + 16 + i * b
            theme.text(s, name, theme.SMALL, theme.TEXT_FAINT, (x, best.y + 44))
            theme.text(s, f"{zeit_s:.3f} s", theme.HEADER, theme.TEXT, (x, best.y + 66))
            if i:
                pygame.draw.line(s, (38, 42, 54), (x - 12, best.y + 40),
                                 (x - 12, best.bottom - 16), 1)

    variantenschild("C", "Vitrine — was fehlt, steht oben",
                    "Ein Fortschrittsband, darunter die drei Erfolge, denen am wenigsten fehlt, dann die Zahlen, "
                    "alle 28 Erfolge und die Bestzeiten. Zeigt sofort, wo es weitergeht, und kommt als einzige ohne Blättern aus.")
    return s


# ===========================================================================
if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for name, fn in [("profil_A_zwei_spalten", profil_a),
                     ("profil_B_kennzahlenband", profil_b),
                     ("profil_C_vitrine", profil_c)]:
        pfad = os.path.join(OUT, f"{name}.png")
        pygame.image.save(mit_band(fn()), pfad)
        print("geschrieben:", pfad)
