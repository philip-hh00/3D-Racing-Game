# -*- mode: python ; coding: utf-8 -*-

# soundfile steht in hiddenimports, damit PyInstaller seinen Hook sicher zieht.
# Der Hook (pyinstaller-hooks-contrib, hook-soundfile.py) holt libsndfile aus
# _soundfile_data neben dem Modul — unter Windows libsndfile*.dll. Von Hand mit
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


a = Analysis(
    [_w('main.py')],
    pathex=[],
    binaries=[
        # MS Visual C++ runtime — required by opencv/numpy/pygame on clean
        # Windows without the VC++ Redistributable installed. Without these the
        # menu video (cv2) fails to load and the tab bar never renders.
        (r'C:\Windows\System32\msvcp140.dll', '.'),
        (r'C:\Windows\System32\msvcp140_1.dll', '.'),
        (r'C:\Windows\System32\vcruntime140.dll', '.'),
        (r'C:\Windows\System32\vcruntime140_1.dll', '.'),
        (r'C:\Windows\System32\concrt140.dll', '.'),
    ],
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
        (_w('data/icon.ico'), 'data'),
        # data/icon.png ist das Fenstersymbol zur Laufzeit: pygame kann die ICO
        # nicht lesen ("Unsupported ICO bitmap format", 08.08.2026), die ICO
        # bleibt aber das Symbol der ausfuehrbaren Datei (icon= unten).
        (_w('data/icon.png'), 'data'),
        (_w('data/settings/name_blacklist.json'), 'data/settings'),
        (_w('data/settings/server.json'),         'data/settings'),
        (_w('data/settings/servers.dat'),         'data/settings'),
        # Bauzeit, von tools/baustempel.py vor dem Packen erzeugt.
        # Ohne sie zeigt die Info-Seite dem Spieler sein eigenes Tagesdatum.
        (_w('data/settings/build_stamp.json'),     'data/settings'),
    ],
    hiddenimports=[
        'pygame',
        'pymunk',
        'numpy',
        'cv2',
        'soundfile',
        # Der Audiofaden (tonausgabe.py). Der Hook von
        # pyinstaller-hooks-contrib nimmt die PortAudio-Bibliothek aus
        # _sounddevice_data mit; ohne den Eintrag hier wuerde er nicht
        # greifen, weil das Modul erst zur Laufzeit importiert wird.
        'sounddevice',
        '_sounddevice',
    ],
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
    icon=_w('data', 'icon.ico'),
    disable_windowed_traceback=False,
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
