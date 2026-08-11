@echo off
REM Bild freistellen und nach ComfyUI\input legen.
REM   tools\freistellen.bat "C:\pfad\zum\bild.png"
REM Datei kann auch per Drag and Drop auf diese .bat gezogen werden.
setlocal
cd /d "%~dp0"

if "%~1"=="" (
    echo Aufruf: freistellen.bat "Pfad\zum\bild.png"
    echo         oder die Bilddatei auf diese Datei ziehen.
    pause
    exit /b 1
)

REM rembg liegt im ComfyUI-venv, nicht im Projekt-venv.
"%~dp0ComfyUI\venv\Scripts\python.exe" "%~dp0freistellen.py" %*
pause
