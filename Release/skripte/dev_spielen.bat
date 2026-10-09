@echo off
REM ============================================================================
REM  dev_spielen.bat - das Spiel gegen die Entwicklungsinstanz starten
REM
REM  Die Dev-Instanz laeuft auf Helsinki neben dem Live-Server (Kennzeichen T,
REM  TCP 7878 / UDP 7877, siehe Documentation/DEV_SERVER.md). Solange diese
REM  Variablen gesetzt sind, zeigt das Online-Menue NUR den Dev-Server: kein
REM  Klick landet versehentlich bei den Live-Spielern.
REM
REM    dev_spielen.bat                  dieser Quellordner, sonst installierte .exe
REM    dev_spielen.bat <Pfad zur .exe>  diese .exe (z. B. entpackte Portable-Zip)
REM
REM  ASCII-only mit Absicht (cmd.exe liest Batch-Dateien in der OEM-Codepage).
REM ============================================================================
setlocal

set "RACE_SERVER_HOST=62.238.50.156"
set "RACE_SERVER_TAG=T"
set "RACE_SERVER_PORT=7878"
set "RACE_SERVER_UDP_PORT=7877"

if not "%~1"=="" (
    set "SPIEL=%~1"
    goto :starten
)

REM Liegt dieses Skript in einem Quellordner, gilt dieser Stand - nicht ein
REM installiertes Spiel, das eine andere Version haben kann (der Dev-Server
REM verlangt genau seine Version).
cd /d "%~dp0..\.."
if not exist "main.py" goto :installiert
if exist ".venv\Scripts\python.exe" (
    echo Starte %CD% aus dem Quelltext gegen den Dev-Server ...
    ".venv\Scripts\python.exe" main.py
    goto :eof
)
where py >nul 2>&1
if not errorlevel 1 (
    echo Starte %CD% mit py -3.11 gegen den Dev-Server ...
    py -3.11 main.py
    goto :eof
)

:installiert
set "SPIEL=%LOCALAPPDATA%\ProgramsD-Racing-GameD-Racing-Game.exe"
if exist "%SPIEL%" goto :starten
set "SPIEL=%ProgramFiles%D-Racing-GameD-Racing-Game.exe"
if exist "%SPIEL%" goto :starten
echo [FEHLER] Weder Quelltext mit Python noch ein installiertes Spiel gefunden.
echo          Pfad zur .exe als Argument angeben: dev_spielen.bat C:\...D-Racing-Game.exe
pause
goto :eof

:starten
)
set "SPIEL=%LOCALAPPDATA%\Programs\3D-Racing-Game\3D-Racing-Game.exe"
if exist "%SPIEL%" goto :starten
set "SPIEL=%ProgramFiles%\3D-Racing-Game\3D-Racing-Game.exe"
if exist "%SPIEL%" goto :starten

REM Kein installiertes Spiel: aus dem Quelltext starten.
cd /d "%~dp0..\.."
if exist ".venv\Scripts\python.exe" (
    echo Starte aus dem Quelltext gegen den Dev-Server ...
    ".venv\Scripts\python.exe" main.py
    goto :eof
)
echo [FEHLER] Weder ein installiertes Spiel noch .venv gefunden.
echo          Pfad zur .exe als Argument angeben: dev_spielen.bat C:\...\3D-Racing-Game.exe
pause
goto :eof

:starten
echo Starte %SPIEL% gegen den Dev-Server (Kennzeichen T) ...
start "" "%SPIEL%"
