@echo off
setlocal enabledelayedexpansion
:: Liegt in Release\skripte\, gearbeitet wird im Wurzelverzeichnis: die
:: Spezifikationen und der Installer arbeiten mit Pfaden relativ dazu
:: (data\..., src\...), und PyInstaller loest sie gegen das Arbeitsverzeichnis auf.
cd /d "%~dp0..\.."

:: === Werkzeug-Pfade =========================================================
:: Vorgabe ist die venv des Projekts: nur dort liegen moderngl und die
:: uebrigen Laufzeitpakete des 3D-Spiels. Ein anderes Python packt sonst
:: stillschweigend ein Spiel ohne 3D-Welt. Ueber die Umgebung ueberschreibbar.
if not defined PY if exist ".venv\Scripts\python.exe" set "PY=%CD%\.venv\Scripts\python.exe"
if not defined PY   set "PY=C:\Users\phili\AppData\Local\Programs\Python\Python311\python.exe"
if not defined ISCC set "ISCC=C:\Users\phili\AppData\Local\Programs\Inno Setup 6\ISCC.exe"

:: Steht dort nichts, wird das Python vom Suchpfad genommen - auf einem frischen
:: Rechner und auf dem Bauknecht der Pipeline ist genau das richtig. Gesucht
:: wird der **volle Pfad**, nicht das blosse Wort "python": ein Programmname
:: ohne Pfad in Anfuehrungszeichen bringt die Auswertung von cmd durcheinander
:: (siehe tools/version_ausgeben.py, gemeldet 06.08.2026).
if not exist "%PY%" (
    set "PY="
    for /f "delims=" %%p in ('where python 2^>nul') do if not defined PY set "PY=%%p"
)
if not exist "%PY%" (
    echo [FEHLER] Python 3.11 nicht gefunden.
    echo          Weder unter dem voreingestellten Pfad noch im Suchpfad.
    echo          Abhilfe:  set "PY=C:\Pfad\zu\python.exe"  und neu starten.
    pause & exit /b 1
)
if not exist "%ISCC%" (
    echo [FEHLER] Inno Setup nicht gefunden: %ISCC%
    echo          Abhilfe:  set "ISCC=C:\Pfad\zu\ISCC.exe"  und neu starten.
    pause & exit /b 1
)
echo Python: %PY%

:: === Laufzeitpakete und PyInstaller in genau diesem Python ===================
"%PY%" -c "import moderngl, glcontext, pygame, pymunk, cv2, soundfile, sounddevice, PIL" 2>nul
if errorlevel 1 (
    echo Laufzeitpakete fehlen - installiere requirements.txt ...
    "%PY%" -m pip install -r requirements.txt
    if errorlevel 1 ( echo [FEHLER] requirements.txt liess sich nicht installieren. & pause & exit /b 1 )
)
"%PY%" -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo PyInstaller fehlt - wird installiert ...
    "%PY%" -m pip install "pyinstaller>=6.10" --quiet
    if errorlevel 1 ( echo [FEHLER] PyInstaller liess sich nicht installieren. & pause & exit /b 1 )
)

:: === 3D-Assets vorhanden? ===================================================
:: Die Modelle, Texturen und Himmel sind nicht versioniert, sondern werden von
:: tools\blender\bauen.bat erzeugt. Ohne sie baut PyInstaller klaglos ein Spiel
:: mit unsichtbaren Autos - deshalb hier abbrechen statt spaeter wundern.
set /a GLB=0
for %%f in (assets\vehicles\*.glb) do set /a GLB+=1
set "FEHLT="
if %GLB% LSS 15 set "FEHLT=Fahrzeuge (assets\vehicles, %GLB% von 15)"
if not exist "assets\umgebung\katalog.json" set "FEHLT=%FEHLT% Umgebung"
if not exist "assets\himmel\City.jpg" set "FEHLT=%FEHLT% Himmel"
if not exist "assets\texturen\asphalt_farbe.jpg" set "FEHLT=%FEHLT% Texturen"
if defined FEHLT (
    echo [FEHLER] 3D-Assets fehlen: !FEHLT!
    echo          Erst bauen:  tools\blender\bauen.bat
    pause & exit /b 1
)

:: === Version aus version.py lesen ===========================================
:: Ohne inneres Anfuehrungszeichen. Die fruehere Zeile begann und endete mit
:: einem Anfuehrungszeichen; cmd entfernt in dem Fall das aeussere Paar, und als
:: Programmname blieb  python" -c "from  uebrig (06.08.2026).
set "VERSION="
:: Ueber den Dateipfad, nicht ueber -m: ein Aufruf als Modul haengt
:: daran, dass Python das Arbeitsverzeichnis in den Suchpfad legt. Mit
:: PYTHONSAFEPATH oder -P in der Umgebung tut es das **nicht**, und dann kommt
:: "No module named 'tools'" (gemeldet 07.08.2026). Die Datei haengt sich das
:: Wurzelverzeichnis selbst an, ist also von beidem unabhaengig.
for /f "usebackq delims=" %%v in (`"%PY%" tools\version_ausgeben.py`) do set "VERSION=%%v"
if not defined VERSION (
    echo [FEHLER] Version konnte nicht gelesen werden.
    echo          Zum Nachsehen von Hand:  "%PY%" tools\version_ausgeben.py
    pause & exit /b 1
)

:: === Zeitstempel ============================================================
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HHmm"') do set "TS=%%i"

set "STAGE=build_tmp\stage"
set "AUSGABE=Release\ausgabe"
set "OUTNAME=3D-Racing-Game_Setup_v%VERSION%_%TS%"
set "ZIPNAME=3D-Racing-Game_Portable_v%VERSION%_%TS%"

echo.
echo ============================================
echo  3D-Rennspiel Release-Build
echo  Version : %VERSION%
echo  Zeit    : %TS%
echo  Setup   : %AUSGABE%\%OUTNAME%.exe
echo  Portabel: %AUSGABE%\%ZIPNAME%.zip
echo ============================================
echo.

:: === 0) Bauzeit einbrennen ==================================================
:: Ohne das zeigt die Info-Seite dem Spieler sein eigenes Tagesdatum als
:: Build-Datum, weil version.py sonst date.today() nimmt.
"%PY%" tools\baustempel.py
if errorlevel 1 ( echo. & echo [FEHLER] Bauzeit konnte nicht geschrieben werden. & pause & exit /b 1 )

:: === 1) PyInstaller: Programm + Assets packen ===============================
echo [1/3] PyInstaller...
if exist "%STAGE%" rmdir /s /q "%STAGE%"
"%PY%" -m PyInstaller Release\pyinstaller\game.spec --distpath "%STAGE%" --workpath build_tmp --noconfirm
if errorlevel 1 ( echo. & echo [FEHLER] PyInstaller fehlgeschlagen. & pause & exit /b 1 )

:: === 2) Inno Setup: Installer erzeugen ======================================
echo.
echo [2/3] Inno Setup...
if not exist "%AUSGABE%" mkdir "%AUSGABE%"
:: Absolute Pfade: Inno loest relative gegen das Verzeichnis der .iss-Datei
:: auf, nicht gegen das Arbeitsverzeichnis (gemeldet 07.08.2026).
"%ISCC%" /Q "/DMyAppVersion=%VERSION%" "/DSourceDir=%CD%\%STAGE%\3D-Racing-Game" "/O%CD%\%AUSGABE%" "/F%OUTNAME%" Release\installer\installer.iss
if errorlevel 1 ( echo. & echo [FEHLER] Inno Setup fehlgeschlagen. & pause & exit /b 1 )

:: === 3) Portables ZIP: der entpackte Ordner fuer itch.io und GameJolt =======
:: Die App-Clients von itch.io und GameJolt entpacken ein Archiv selbst und
:: starten die .exe direkt; ein Installer passt dort nicht (Adminrechte,
:: Program Files, kein sauberes Aktualisieren/Entfernen durch den Client). Das
:: ZIP enthaelt den ganzen Ordner 3D-Racing-Game (exe + _internal), denn die
:: blosse .exe laeuft ohne _internal nicht.
::
:: NICHT Compress-Archive: es legt fuer einen Unterordner zusaetzlich einen
:: 0-Byte-Eintrag ohne Schraegstrich an (Datei numpy neben Ordner numpy/), und
:: butler lehnt so ein Archiv ab ("Two entries have the same name", 08.08.2026).
:: tools\portables_zip.py schreibt saubere Eintraege ueber zipfile.
echo.
echo [3/3] Portables ZIP...
"%PY%" tools\portables_zip.py %STAGE%\3D-Racing-Game %AUSGABE%\%ZIPNAME%.zip
if errorlevel 1 ( echo. & echo [FEHLER] ZIP konnte nicht erstellt werden. & pause & exit /b 1 )

echo.
echo ============================================
echo  FERTIG. Upload-Dateien:
echo  Installer (Direkt-Download): %AUSGABE%\%OUTNAME%.exe
echo  Portabel  (itch.io/GameJolt): %AUSGABE%\%ZIPNAME%.zip
echo ============================================
echo.
if not "%RACE_KEIN_PAUSE%"=="1" pause
