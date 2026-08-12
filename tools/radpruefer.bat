@echo off
REM Radpruefer: Nabe von Hand setzen und die Rundheit ansehen.
REM   radpruefer.bat            rookie
REM   radpruefer.bat supercar   anderes Fahrzeug
setlocal
cd /d "%~dp0.."

set "FAHRZEUG=%~1"
if "%FAHRZEUG%"=="" set "FAHRZEUG=rookie"

if not exist ".venv\Scripts\python.exe" (
    echo [ABBRUCH] Kein venv. Erst einrichten:
    echo     py -3.11 -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

".venv\Scripts\python.exe" "tools\radpruefer.py" --fahrzeug "%FAHRZEUG%"
if errorlevel 1 pause
