"""Vorschau der itch.io-Seite im Browser: ``Release/store/vorschau_itchio.html``.

itch.io verlangt, dass Bilder zuerst auf die Seite hochgeladen werden; im Text
stehen deshalb Platzhalter wie ``SCREENSHOT_02_URL``. Dieses Werkzeug baut aus
``Documentation/itchio_page.html`` eine vollstaendige Seite im dunklen Stil von
itch.io und setzt statt der Platzhalter die lokalen Dateien aus
``Release/store/screenshots/`` ein — damit sieht man vor dem Hochladen, wie die
Seite wirkt.

Aufruf::

    .venv\\Scripts\\python tools\\itchio_vorschau.py [ZIELORDNER]

Ohne Argument ist der Zielordner ``Release/store`` (dort liegen die Bilder).
Die Vorschau ist nur zum Ansehen. In itch.io gehoert ausschliesslich der
Inhalt von ``itchio_page.html`` — nie diese Datei.
"""
from __future__ import annotations

import glob
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FRAGMENT = os.path.join(_ROOT, "Documentation", "itchio_page.html")

#: Kurzbeschreibung unter dem Titel (siehe Documentation/ITCHIO_RELEASE.md).
_KURZ = ("3D racing with real driving physics: 15 cars, a track editor, "
         "split-screen and online races for up to 6 players.")

_SEITE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vorschau: 3D Racing Game auf itch.io</title>
<style>
  :root {{
    --bg: #0d0f14; --panel: #161a22; --panel2: #1d222c; --line: #2a303c;
    --text: #e6e6e6; --muted: #9aa1ae; --accent: #e62828; --accent-hi: #ff4a4a;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--text);
         font: 16px/1.6 "Noto Sans", system-ui, -apple-system, "Segoe UI", sans-serif; }}
  a {{ color: var(--accent-hi); }}
  .hinweis {{ background: #2b1d00; color: #ffd27a; text-align: center;
             padding: 8px 16px; font-size: 14px; border-bottom: 1px solid #5a3d00; }}
  .banner {{ width: 100%; max-height: 240px; object-fit: cover; display: block; }}
  .seite {{ max-width: 1000px; margin: 0 auto; padding: 0 16px 64px; }}
  .kopf {{ padding: 28px 0 8px; }}
  .kopf h1 {{ margin: 0; font-size: 2.2rem; line-height: 1.15; }}
  .kopf p {{ margin: 8px 0 0; color: var(--muted); font-size: 1.05rem; }}
  .spalten {{ display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 32px;
             align-items: start; margin-top: 24px; }}
  @media (max-width: 800px) {{ .spalten {{ grid-template-columns: minmax(0, 1fr); }} }}
  .box {{ background: var(--panel); border: 1px solid var(--line);
         border-radius: 4px; padding: 16px; margin-bottom: 16px; }}
  .box h4 {{ margin: 0 0 10px; font-size: .8rem; letter-spacing: .08em;
            text-transform: uppercase; color: var(--muted); }}
  .download {{ display: flex; justify-content: space-between; align-items: center;
              gap: 8px; padding: 10px 0; border-top: 1px solid var(--line); font-size: .9rem; }}
  .download:first-of-type {{ border-top: 0; }}
  .download small {{ color: var(--muted); display: block; }}
  .knopf {{ background: var(--accent); color: #fff; border-radius: 3px; padding: 6px 14px;
           font-weight: 700; white-space: nowrap; font-size: .85rem; }}
  .knopf.aus {{ background: var(--panel2); color: var(--muted); }}
  table.info {{ width: 100%; border-collapse: collapse; font-size: .9rem; }}
  table.info td {{ padding: 6px 0; vertical-align: top; border-top: 1px solid var(--line); }}
  table.info tr:first-child td {{ border-top: 0; }}
  table.info td:first-child {{ color: var(--muted); width: 38%; }}
  .tags a {{ display: inline-block; margin: 0 4px 4px 0; padding: 2px 8px;
            background: var(--panel2); border-radius: 3px; text-decoration: none;
            font-size: .8rem; color: var(--text); }}
  .galerie {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(88px, 1fr)); gap: 6px; }}
  .galerie img {{ width: 100%; aspect-ratio: 16 / 9; object-fit: cover; border-radius: 2px; display: block; }}

  /* Beschreibungsfeld: so setzt itch.io den eingefuegten Text */
  .beschreibung {{ min-width: 0; }}
  .beschreibung h1 {{ font-size: 1.6rem; line-height: 1.25; margin: 0 0 .6em; }}
  .beschreibung h2 {{ font-size: 1.45rem; margin: 1.6em 0 .5em; }}
  .beschreibung h3 {{ font-size: 1.15rem; margin: 1.3em 0 .4em; }}
  .beschreibung p {{ margin: 0 0 1em; }}
  .beschreibung img {{ max-width: 100%; height: auto; border-radius: 3px; display: block; }}
  .beschreibung hr {{ border: 0; border-top: 1px solid var(--line); margin: 1.8em 0; }}
  .beschreibung ul, .beschreibung ol {{ padding-left: 1.4em; margin: 0 0 1em; }}
  .beschreibung li {{ margin: .25em 0; }}
  .beschreibung table {{ border-collapse: collapse; width: 100%; margin: 0 0 1em; }}
  .beschreibung th, .beschreibung td {{ border: 1px solid var(--line); padding: 8px 12px;
                                       text-align: left; vertical-align: top; }}
  .beschreibung th {{ background: var(--panel2); }}
  .beschreibung code {{ background: var(--panel2); padding: 1px 6px; border-radius: 3px;
                       font-family: Consolas, "Courier New", monospace; font-size: .9em;
                       overflow-wrap: anywhere; }}
  .beschreibung blockquote {{ margin: 0 0 1em; padding: .2em 1em; border-left: 3px solid var(--accent);
                             color: var(--muted); }}
</style>
</head>
<body>
<div class="hinweis">Lokale Vorschau, nicht itch.io. Die Bilder kommen aus screenshots/; auf itch.io ersetzen die hochgeladenen Bilder die Platzhalter.</div>
{banner}
<div class="seite">
  <div class="kopf">
    <h1>3D Racing Game</h1>
    <p>{kurz}</p>
  </div>
  <div class="spalten">
    <main class="beschreibung">
{fragment}
    </main>
    <aside>
      <div class="box">
        <h4>Download</h4>
        <div class="download"><span>3D-Racing-Game_Setup_v1.0.0_Windows.exe<small>Windows, installer</small></span><span class="knopf">Download</span></div>
        <div class="download"><span>3D-Racing-Game_Portable_v1.0.0_Windows.zip<small>Windows, portable</small></span><span class="knopf">Download</span></div>
        <div class="download"><span>3D-Racing-Game_Portable_v1.0.0_macOS.zip<small>macOS, coming soon</small></span><span class="knopf aus">Soon</span></div>
      </div>
      <div class="box">
        <h4>Info</h4>
        <table class="info">
          <tr><td>Status</td><td>Released</td></tr>
          <tr><td>Platforms</td><td>Windows, macOS</td></tr>
          <tr><td>Genre</td><td>Racing</td></tr>
          <tr><td>Players</td><td>Single player, local and online multiplayer (1&ndash;6)</td></tr>
          <tr><td>Inputs</td><td>Keyboard, gamepad</td></tr>
          <tr><td>Languages</td><td>English, German</td></tr>
        </table>
      </div>
      <div class="box tags">
        <h4>Tags</h4>
        <a href="#">racing</a><a href="#">3d</a><a href="#">multiplayer</a><a href="#">split-screen</a><a href="#">physics</a><a href="#">level-editor</a><a href="#">local-multiplayer</a><a href="#">online-multiplayer</a><a href="#">car-racing</a><a href="#">singleplayer</a>
      </div>
      <div class="box">
        <h4>Screenshots</h4>
        <div class="galerie">
{galerie}
        </div>
      </div>
    </aside>
  </div>
</div>
</body>
</html>
"""


def _bilder(ordner: str) -> dict[str, str]:
    """``{"01": "screenshots/01_....jpg", ...}`` fuer alle vorhandenen Bilder."""
    gefunden = {}
    for pfad in sorted(glob.glob(os.path.join(ordner, "screenshots", "[0-9][0-9]_*.jpg"))):
        name = os.path.basename(pfad)
        gefunden[name[:2]] = "screenshots/" + name
    return gefunden


def bauen(ordner: str) -> str:
    with open(_FRAGMENT, encoding="utf-8") as f:
        fragment = f.read()
    bilder = _bilder(ordner)
    fehlen = sorted({n for n in re.findall(r"SCREENSHOT_(\d\d)_URL", fragment)}
                    - set(bilder))
    if fehlen:
        raise SystemExit(f"Screenshots fehlen in {ordner}/screenshots: {fehlen}")
    fragment = re.sub(r"SCREENSHOT_(\d\d)_URL", lambda m: bilder[m.group(1)], fragment)
    banner = ""
    if os.path.exists(os.path.join(ordner, "itchio_banner_1920x480.png")):
        banner = '<img class="banner" src="itchio_banner_1920x480.png" alt="">'
    galerie = "\n".join(f'          <img src="{p}" alt="">' for p in bilder.values())
    return _SEITE.format(banner=banner, kurz=_KURZ, fragment=fragment, galerie=galerie)


def main(argv: list[str]) -> int:
    ordner = argv[1] if len(argv) > 1 else os.path.join(_ROOT, "Release", "store")
    ziel = os.path.join(ordner, "vorschau_itchio.html")
    with open(ziel, "w", encoding="utf-8", newline="\n") as f:
        f.write(bauen(ordner))
    print(ziel)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
