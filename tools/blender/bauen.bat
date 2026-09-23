@echo off
REM Alle 3D-Assets neu bauen: CC0-Material laden, Texturen erzeugen, Himmel,
REM Fahrzeuge und Umgebung in Blender.
REM
REM   tools\blender\bauen.bat              alles
REM   tools\blender\bauen.bat fahrzeuge    nur die Fahrzeuge
REM   tools\blender\bauen.bat umgebung     nur die Umgebung
REM
REM Blender: Umgebungsvariable BLENDER oder die portable Installation unter
REM F:\Blender\blender-4.5.14-windows-x64.
setlocal
cd /d "%~dp0..\.."

if "%BLENDER%"=="" set "BLENDER=F:\Blender\blender-4.5.14-windows-x64\blender.exe"
if not exist "%BLENDER%" (
    echo [ABBRUCH] Blender nicht gefunden: %BLENDER%
    echo           BLENDER auf blender.exe setzen oder Blender 4.5 LTS nach F:\Blender entpacken.
    pause
    exit /b 1
)
set "PY=.venv\Scripts\python.exe"
set "TEIL=%~1"

if "%TEIL%"=="fahrzeuge" goto fahrzeuge
if "%TEIL%"=="umgebung" goto umgebung

echo === CC0-Material laden (Poly Haven) ===
"%PY%" tools\assets_laden.py || goto fehler
echo === Texturen erzeugen ===
"%PY%" tools\texturen_erzeugen.py || goto fehler
echo === Himmel ===
"%BLENDER%" -b -P tools\blender\himmel_bauen.py || goto fehler

:fahrzeuge
echo === Fahrzeuge ===
"%BLENDER%" -b -P tools\blender\fahrzeug_bauen.py -- --fahrzeug alle || goto fehler
if "%TEIL%"=="fahrzeuge" goto ende

:umgebung
echo === Umgebung ===
"%BLENDER%" -b -P tools\blender\umgebung_bauen.py || goto fehler

:ende
echo Fertig.
exit /b 0

:fehler
echo [FEHLER] Abbruch, siehe Ausgabe oben.
pause
exit /b 1
