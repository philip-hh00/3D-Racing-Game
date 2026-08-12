@echo off
REM Vorschau: ein Fahrzeug auf einer echten Strecke, Verfolgerkamera, HUD.
REM   vorschau3d.bat                 rookie auf oval
REM   vorschau3d.bat supercar gp     anderes Fahrzeug, andere Strecke
setlocal
cd /d "%~dp0.."

set "FAHRZEUG=%~1"
set "STRECKE=%~2"
if "%FAHRZEUG%"=="" set "FAHRZEUG=rookie"
if "%STRECKE%"=="" set "STRECKE=oval"

if not exist ".venv\Scripts\python.exe" (
    echo [ABBRUCH] Kein venv. Erst einrichten:
    echo     py -3.11 -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

".venv\Scripts\python.exe" "tools\vorschau3d.py" --fahrzeug "%FAHRZEUG%" --strecke "%STRECKE%"
if errorlevel 1 pause
