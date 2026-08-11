# Prompt for the next session

Copy everything below the line into a fresh chat.

---

I'm working on **`philip-hh00/2D-Racing-Game`**, a German-language Python/pygame
top-down racing game heading for its 1.0.0 release on itch.io and GameJolt.

**Branch:** develop, commit and push only on
`claude/release-1-0-0-analysis-f64o1k`. Never push anywhere else. Don't open a
pull request unless I ask.

## Read these first

* `playtest_findings.md` — the **Offen** table holds seven open items, each with
  the cause already measured in a previous session. Don't re-derive them; verify
  and fix. Closed findings go into the **Erledigt** table with the reasoning.
* `release_1_0_plan.md` — §8a documents what the test suite reaches and where
  its limits are.
* `Documentation/ITCHIO_RELEASE.md` and `Documentation/itchio_page.html` — store
  page text (German + English; the HTML is the paste-ready English version).

## House rules

* German comments and docstrings, explaining **why**, not what. No emojis in
  code. Cite dates for findings.
* Batch files must be pure ASCII (cmd.exe reads them in the OEM codepage).
* Every finding gets a test that holds the **rule**, not the one instance.
  Counter-check each new test: break the thing deliberately, confirm the test
  fails, restore.
* Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest -q -p no:cacheprovider`
  Currently **2290 pass, 8 skip, ~4:30**. Everything runs on every push.
* Shared test helpers live in `tests/spielhilfe.py` — headless races, a fake
  gamepad, recording what is actually drawn. Use them; don't copy them.
* Tests must never touch the network and never write into the working tree.
  `tests/conftest.py` enforces both; a previous CI failure came from exactly that.
* No signing certificate will be bought — the "unknown publisher" warning stays.
  The unencrypted-traffic note must not appear in-game or on any store page.
* Interview me before far-reaching decisions.

## Work for this session

### A. Seven bugs — details and measured causes are in `playtest_findings.md`

1. **Window icon** — the Python snake shows instead of the game icon. Both load
   paths fail silently: `data/icon.ico` raises `Unsupported ICO bitmap format`,
   and `data/menu/Icon.png` doesn't exist (and is a relative path).
2. **Music too loud** — about 30 % quieter. I keep it at 10 % and it's still
   loud. `audio.py:44` sets the profile value with no headroom.
3. **Race end needs a short transition** — the results screen appears the
   instant the last car finishes or goes DNF. It feels thrown in your face.
4. **Two tracks can't be deleted** — received via online Grand Prix.
   `delete_track` looks for `<slugify(name)>.json`, but received tracks are saved
   under their transferred filename (`Rundkurs (2).json`, `U Strecke.json`).
   Deletion silently misses and still reports success.
5. **"Finish Grand Prix" → "Exit Grand Prix"** in `data/i18n/en.json`
   (two entries).
6. **HUD status panel, top right: a horizontal bar runs through the text.**
   The only candidate is the divider in `hud.py:484`. Measured, it clears the
   text by 8 px at every scale from 0.6 to 2.0 — so the trigger is still
   unknown. **Ask me for my resolution and scaling first**, then reproduce
   headlessly. I have a screenshot.
7. **Settings → General needs a quit-game button**, opening the same dialog as
   ESC in the main menu (`menu_shell_state.py:518`). One place, not two.

### B. Store artwork for GameJolt

I have `Documentation/Screenshots und cover/Thumbnail_itchio.png`, but the
format and resolution don't fit GameJolt.

**Thumbnail:** 16:9 exactly, at least 588×331, at most 2000×2000, PNG, under
30 MB. Larger is better.
**Game header:** a matching one, same visual language.

GameJolt requires original material — so build both from the game's own assets
and from screenshots you capture yourself. The game renders headlessly
(`SDL_VIDEODRIVER=dummy`) and a previous session already saved screens that way,
for example `Documentation/Screenshots und cover/erststart_*.png`. Show me a
draft before you settle on one.

## What was finished in the previous session

Don't redo any of this:

* The **seed ghost** no longer takes two minutes. The progress bar was redrawn
  once per simulation step, each redraw waiting for vsync — 6871 frames.
  An empty ghost is no longer written or read, so one failed generation can no
  longer block a track forever.
* **Start grid** follows the centreline backwards instead of extrapolating in a
  straight line, and a new track gets two run-up straights instead of one.
* **Minimap** draws the start/finish as a line across the road, not a dot.
* **Custom tracks, drafts, received tracks and ghosts** are out of the repo
  (`.gitignore`); they still sit on my disk.
* The editor's **default track name** is translated now.

Start by reading `playtest_findings.md`, then tell me which of the seven you'll
take first and why.
