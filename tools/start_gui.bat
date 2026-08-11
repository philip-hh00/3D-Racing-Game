@echo off
REM ============================================================================
REM  ComfyUI mit TRELLIS 2 starten und die Oberflaeche im Browser oeffnen.
REM  Doppelklick genuegt.
REM ============================================================================
setlocal
cd /d "%~dp0"

set "ROOT=%~dp0ComfyUI"
set "PY=%ROOT%\venv\Scripts\python.exe"
set "PORT=8188"
set "URL=http://127.0.0.1:%PORT%"
set "LOG=%ROOT%\comfyui.log"
set "SPRITES=F:\Fahr-Rennspiel-2D\data\vehicles"

if not exist "%PY%" (
    echo [ABBRUCH] Kein venv unter %ROOT%\venv
    echo           Erst tools\install_trellis2.bat ausfuehren.
    pause
    exit /b 1
)

REM Laeuft schon etwas auf dem Port? Dann nur den Browser oeffnen.
curl -s -o nul -m 2 "%URL%" && (
    echo ComfyUI laeuft bereits - oeffne nur den Browser.
    start "" "%URL%"
    exit /b 0
)

REM Alle 15 Fahrzeug-Sprites bereitstellen, damit sie im Bild-Node
REM auswaehlbar sind. Ueberschreibt nur, was sich geaendert hat.
if exist "%SPRITES%" (
    echo Sprites aus dem 2D-Spiel uebernehmen...
    xcopy "%SPRITES%\*.png" "%ROOT%\input\" /Y /D /Q >nul
)

echo Starte ComfyUI, Log: %LOG%
start "ComfyUI" /min cmd /c ""%PY%" "%ROOT%\main.py" --lowvram --port %PORT% > "%LOG%" 2>&1"

REM Auf den Server warten. Der erste Start dauert laenger, weil die Custom
REM Nodes geladen werden - deshalb grosszuegige 120 Sekunden.
set /a VERSUCHE=0
echo Warte auf den Server...
:warten
set /a VERSUCHE+=1
curl -s -o nul -m 2 "%URL%" && goto bereit
if %VERSUCHE% GEQ 60 goto aufgegeben
REM Abbruch erkennen: steht im Log ein Traceback, warten wir umsonst.
find /i "Traceback" "%LOG%" >nul 2>&1 && goto abgestuerzt
timeout /t 2 /nobreak >nul
goto warten

:bereit
echo Server bereit nach etwa %VERSUCHE% Versuchen.
start "" "%URL%"
echo.
echo   Workflow per Drag and Drop auf die Flaeche ziehen:
echo     %~dp0..\workflows\Fahrzeug_TopDown_HQ.json
echo     %~dp0..\workflows\Fahrzeug_TopDown_Sicher.json   ^(bei out of memory^)
echo.
echo   Das Fenster kann geschlossen werden, der Server laeuft weiter.
echo   Zum Beenden das minimierte Fenster "ComfyUI" schliessen.
echo.
pause
exit /b 0

:abgestuerzt
echo.
echo [FEHLER] Der Server ist beim Start abgebrochen. Letzte Zeilen:
echo ---------------------------------------------------------------
powershell -NoProfile -Command "Get-Content '%LOG%' -Tail 25"
echo ---------------------------------------------------------------
pause
exit /b 1

:aufgegeben
echo.
echo [FEHLER] Server nach 120 Sekunden nicht erreichbar. Letzte Zeilen:
echo ---------------------------------------------------------------
powershell -NoProfile -Command "Get-Content '%LOG%' -Tail 25"
echo ---------------------------------------------------------------
pause
exit /b 1
