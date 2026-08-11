@echo off
setlocal enabledelayedexpansion
:: Startet die Pipeline auf GitHub, indem ein Tag gesetzt und gepusht wird.
:: Es braucht nichts ausser git - kein zusaetzliches Werkzeug, keine Anmeldung.
::
::   release_starten.bat            fragt nach: Testbuild oder Release
::   release_starten.bat test       gleich ein Testbuild, ohne Rueckfrage
::   release_starten.bat release    gleich ein Release, ohne Rueckfrage
::
:: Der Unterschied liegt allein im Tag. Ein Testbuild traegt dieselbe Version
:: und unterscheidet sich nur in der eingebrannten Bauzeit; er legt deshalb
:: kein Release an, sondern haengt die Pakete als Artefakt an den Lauf.
cd /d "%~dp0..\.."

set "ART=%~1"

:: Voller Pfad statt des blossen Wortes "python": ein Programmname ohne Pfad in
:: Anfuehrungszeichen bringt die Auswertung von cmd durcheinander.
if not defined PY (
    for /f "delims=" %%p in ('where python 2^>nul') do if not defined PY set "PY=%%p"
)
if not defined PY ( echo [FEHLER] Python nicht gefunden. Abhilfe: set "PY=C:\Pfad\zu\python.exe" & pause & exit /b 1 )

:: === Version aus version.py ==================================================
:: Ohne inneres Anfuehrungszeichen - die fruehere Fassung mit -c "..." begann
:: und endete mit einem Anfuehrungszeichen, und cmd entfernt in dem Fall das
:: aeussere Paar (siehe tools/version_ausgeben.py, 06.08.2026).
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

for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD') do set "BRANCH=%%b"

:: Erst den Stand von GitHub holen. Ohne das kennt keiner der Vergleiche unten
:: die Wahrheit: weder ob dieser Branch hinterherhinkt, noch ob es den Tag
:: drueben schon gibt.
git fetch --quiet origin %BRANCH% --tags >nul 2>&1

:: Zeigt der Tag auf einen veralteten Commit, wird der falsche Stand gebaut -
:: und das faellt erst auf, wenn im fertigen Paket etwas fehlt. Am 06.08.2026
:: genau so passiert: getaggt wurde zwei Merges vor dem aktuellen Stand.
set "HINTEN=0"
for /f "delims=" %%h in ('git rev-list --count HEAD..origin/%BRANCH% 2^>nul') do set "HINTEN=%%h"

:: Ein Tag zeigt auf einen Commit, nicht auf den Arbeitsbaum. Ungespeicherte
:: Aenderungen waeren im Build nicht drin - und das faellt sonst erst auf, wenn
:: das fertige Paket sie nicht enthaelt.
set "SAUBER=ja"
for /f "delims=" %%s in ('git status --porcelain') do set "SAUBER=nein"

:: === Was soll gebaut werden? =================================================
:: Frueher entschied das ein Argument, das man beim Aufruf vergisst - und ein
:: vergessenes Argument hiess: aus Versehen eine Versionsnummer verbraucht, die
:: sich nicht mehr zurueckholen laesst (gemeldet 07.08.2026). Jetzt wird gefragt.
if not "%ART%"=="" goto :gewaehlt
echo.
echo  Was soll gebaut werden?
echo.
echo    [1]  Testbuild    - Pakete zum Ausprobieren, kein Release,
echo                        verbraucht KEINE Versionsnummer
echo    [2]  Release      - offizielle Fassung v%VERSION% als Entwurf
echo.
:frage
set "WAHL="
set /p WAHL="Auswahl [1/2, Enter = 1]: "
if "!WAHL!"=="" set "WAHL=1"
if "!WAHL!"=="1" ( set "ART=test" & goto :gewaehlt )
if "!WAHL!"=="2" ( set "ART=release" & goto :gewaehlt )
echo Bitte 1 oder 2.
goto :frage
:gewaehlt

if "%ART%"=="test" (
    for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format MMdd-HHmm"') do set "TS=%%i"
    set "TAG=test-%VERSION%-!TS!"
    set "WAS=Testbuild (kein Release, Pakete als Artefakt am Lauf)"
) else (
    set "TAG=v%VERSION%"
    set "WAS=Release (Entwurf mit beiden Paketen)"
)

echo.
echo ============================================
echo  Pipeline starten
echo  Version     : %VERSION%
echo  Branch      : %BRANCH%
echo  Arbeitsbaum : %SAUBER%
echo  Rueckstand  : %HINTEN% Commit^(s^) hinter origin/%BRANCH%
echo  Tag         : !TAG!
echo  Ergebnis    : !WAS!
echo ============================================
echo.

if "%SAUBER%"=="nein" (
    echo [WARNUNG] Der Arbeitsbaum ist nicht sauber. Ein Tag zeigt auf den
    echo           letzten Commit - alles Ungespeicherte fehlt im Build.
    echo.
)

if not "%HINTEN%"=="0" (
    echo [FEHLER] Dieser Branch ist %HINTEN% Commit^(s^) hinter origin/%BRANCH%.
    echo          Getaggt wuerde der alte Stand, gebaut also das Falsche.
    echo          Abhilfe:  git pull --ff-only
    pause & exit /b 1
)

:: Ein doppelt vergebener Tag wird von GitHub abgewiesen, und die Meldung dazu
:: ist wenig hilfreich. Lieber hier sagen, was los ist.
set "TAG_DA="
git rev-parse -q --verify "refs/tags/!TAG!" >nul 2>&1
if not errorlevel 1 set "TAG_DA=1"
git ls-remote --exit-code --tags origin "!TAG!" >nul 2>&1
if not errorlevel 1 set "TAG_DA=1"
if defined TAG_DA (
    echo [FEHLER] Tag !TAG! gibt es schon ^(oertlich oder auf GitHub^).
    if "%ART%"=="test" ( echo          Eine Minute warten, der Zeitstempel aendert sich. ) else ( echo          Fuer eine neue Fassung VERSION in src\core\version.py erhoehen. )
    pause & exit /b 1
)

set /p ANTWORT="Tag !TAG! setzen und pushen? [j/N] "
if /i not "!ANTWORT!"=="j" ( echo Abgebrochen. & exit /b 0 )

git tag "!TAG!" || ( echo [FEHLER] Tag liess sich nicht setzen. & pause & exit /b 1 )
git push origin "!TAG!" || ( echo [FEHLER] Push fehlgeschlagen - Tag wird zurueckgenommen. & git tag -d "!TAG!" & pause & exit /b 1 )

for /f "delims=" %%u in ('git remote get-url origin') do set "REMOTE=%%u"
echo.
echo ============================================
echo  Gestartet. Der Fortschritt steht unter:
echo  %REMOTE%  ^-^>  Actions
echo.
echo  Erst wenn die Tests gruen sind, wird gebaut. Sind sie rot,
echo  entsteht KEIN Paket - der Tag steht dann trotzdem da.
echo  Das Zip "Source code" an einem Tag ist nicht der Build,
echo  das legt GitHub von sich aus an.
echo ============================================
echo.
pause
