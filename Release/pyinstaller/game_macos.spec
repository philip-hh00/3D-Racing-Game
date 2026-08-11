# -*- mode: python ; coding: utf-8 -*-
# macOS build spec — produces "2D-Racing-Game.app". Run on macOS only:
#   pyinstaller game_macos.spec --noconfirm

# soundfile steht in hiddenimports, damit PyInstaller seinen Hook sicher zieht.
# Der Hook (pyinstaller-hooks-contrib, hook-soundfile.py) holt libsndfile aus
# _soundfile_data neben dem Modul — auf macOS libsndfile.dylib. Von Hand mit
# collect_data_files/collect_dynamic_libs geht das NICHT: soundfile ist eine
# einzelne Moduldatei und kein Paket, beide Aufrufe kommen leer zurueck.
#
# Voraussetzung ist nur, dass soundfile in der Build-Umgebung installiert ist —
# steht seit dem 04.08.2026 in requirements.txt. Fehlt es, warnt der Hook mit
# "sndfile shared library not found" und das Buendel hat keinen Motorklang.

# Alle Pfade hier gehen ueber _WURZEL, und das ist der Grund:
# **PyInstaller loest Pfade in einer .spec gegen das Verzeichnis der Spec-Datei
# auf** (``SPECPATH``), nicht gegen das Arbeitsverzeichnis. Solange die Spec im
# Wurzelverzeichnis lag, fiel das nicht auf. Seit dem Umzug nach
# ``Release/pyinstaller/`` am 06.08.2026 zeigte jeder relative Pfad zwei Ebenen
# zu tief, und der Build brach ab mit
#   ERROR: script '...\Release\pyinstaller\main.py' not found
# (gemeldet 07.08.2026). Ein ``cd`` im Bauskript hilft dagegen nicht — es ist
# nicht das Arbeitsverzeichnis, das zaehlt.
import os
_WURZEL = os.path.abspath(os.path.join(SPECPATH, '..', '..'))


def _w(*teile):
    """Pfad ab dem Wurzelverzeichnis des Projekts."""
    return os.path.join(_WURZEL, *teile)


import importlib.util as _ilu
_spec = _ilu.spec_from_file_location('_v', _w('src', 'core', 'version.py'))
_mod = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_mod)
_version = _mod.VERSION

a = Analysis(
    [_w('main.py')],
    pathex=[],
    binaries=[],
    datas=[
        (_w('data/fonts'),    'data/fonts'),
        (_w('data/textures'), 'data/textures'),
        (_w('data/vehicles'), 'data/vehicles'),
        # NUR die fuenf mitgelieferten Strecken (entschieden 04.08.2026).
        # Ohne drafts/: unfertige Entwuerfe sind kein Auslieferungsinhalt.
        # Ohne custom/: das sind die eigenen Strecken des Entwicklers, und
        # "mitgeliefert" soll heissen, dass eine Strecke abgestimmt ist.
        (_w('data/tracks/*.json'), 'data/tracks'),
        (_w('data/audio'),    'data/audio'),
        (_w('data/menu'),     'data/menu'),
        (_w('data/ai_settings'), 'data/ai_settings'),
        (_w('data/i18n'),     'data/i18n'),
        (_w('data/icon.icns'), 'data'),
        # data/icon.png ist das Fenstersymbol zur Laufzeit (siehe game.spec).
        (_w('data/icon.png'), 'data'),
        (_w('data/settings/name_blacklist.json'), 'data/settings'),
        (_w('data/settings/server.json'),         'data/settings'),
        (_w('data/settings/servers.dat'),         'data/settings'),
        # Bauzeit, von tools/baustempel.py vor dem Packen erzeugt.
        # Ohne sie zeigt die Info-Seite dem Spieler sein eigenes Tagesdatum.
        (_w('data/settings/build_stamp.json'),     'data/settings'),
    ],
    # sounddevice/_sounddevice: der Audiofaden (tonausgabe.py, 06.08.2026).
    # Wie bei soundfile zieht der Hook aus pyinstaller-hooks-contrib die
    # PortAudio-Bibliothek aus _sounddevice_data mit — aber nur, wenn das Modul
    # hier steht, denn importiert wird es erst zur Laufzeit.
    hiddenimports=['pygame', 'pymunk', 'numpy', 'cv2', 'soundfile',
                   'sounddevice', '_sounddevice'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='2D-Racing-Game',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='2D-Racing-Game',
)

app = BUNDLE(
    coll,
    name='2D-Racing-Game.app',
    icon=_w('data', 'icon.icns'),
    bundle_identifier='de.philipraht.racinggame',
    info_plist={
        'CFBundleName': '2D-Racing-Game',
        'CFBundleDisplayName': '2D-Racing-Game',
        # Aus version.py, nicht von Hand: hier stand '0.1.0', waehrend das Spiel
        # selbst 0.6.0-beta meldete. macOS zeigt diesen Wert im Finder und im
        # Ueber-Fenster — zwei verschiedene Versionen sind schlimmer als eine.
        'CFBundleShortVersionString': _version,
        'CFBundleVersion': _version,
        'NSHighResolutionCapable': True,
    },
)
