@echo off
REM ComfyUI mit TRELLIS 2 starten.
REM --lowvram bleibt drin, bis der Durchlauf bei 1024^3 stabil laeuft.
cd /d "%~dp0ComfyUI"
call venv\Scripts\activate.bat
python main.py --lowvram
pause
