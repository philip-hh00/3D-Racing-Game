@echo off
REM ============================================================================
REM  TRELLIS 2 Installer fuer 3D-Racing-Game
REM  Zielsystem: Windows 11, RTX 5060 Ti (Blackwell, sm_120), Python 3.11
REM
REM  Idempotent: kann mehrfach ausgefuehrt werden, ueberspringt Fertiges.
REM  Doppelklick genuegt.
REM ============================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "ROOT=%~dp0ComfyUI"
set "PY=%ROOT%\venv\Scripts\python.exe"
set "TRELLIS=%ROOT%\custom_nodes\ComfyUI-Trellis2"
set "WHEELS=%TRELLIS%\wheels\Windows\Torch270"

echo.
echo ===========================================================
echo  BLOCK 0 - Voraussetzungen pruefen
echo ===========================================================

where git >nul 2>&1 || (echo [ABBRUCH] git nicht gefunden. https://git-scm.com/download/win & goto :fail)
py -3.11 -c "import sys" >nul 2>&1 || (echo [ABBRUCH] Python 3.11 nicht gefunden. Offizieller Installer, NICHT das embeddable package. & goto :fail)
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader || (echo [ABBRUCH] nvidia-smi nicht gefunden. & goto :fail)
echo [OK] git, Python 3.11 und NVIDIA-Treiber vorhanden.

echo.
echo ===========================================================
echo  BLOCK 1 - ComfyUI und venv
echo ===========================================================

if not exist "%ROOT%\main.py" (
    git clone --depth 1 https://github.com/comfyanonymous/ComfyUI "%ROOT%" || goto :fail
) else (
    echo [SKIP] ComfyUI liegt bereits in %ROOT%
)

if not exist "%PY%" (
    py -3.11 -m venv "%ROOT%\venv" || goto :fail
) else (
    echo [SKIP] venv existiert bereits
)

"%PY%" -m pip install --upgrade pip wheel || goto :fail
REM setuptools gepinnt - neuere Versionen brechen Ninja-Builds
"%PY%" -m pip install setuptools==75.8.2 || goto :fail

echo.
echo ===========================================================
echo  BLOCK 2 - PyTorch 2.7.0 + cu128  (Blackwell braucht cu128)
echo ===========================================================

"%PY%" -m pip install torch==2.7.0 torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cu128 || goto :fail
"%PY%" -m pip install -r "%ROOT%\requirements.txt" || goto :fail

echo.
echo --- SPERRE: erwartet "2.7.0+cu128 True (12, 0)" ---
"%PY%" -c "import torch; cap=torch.cuda.get_device_capability(); print(torch.__version__, torch.cuda.is_available(), cap); raise SystemExit(0 if cap==(12,0) and torch.cuda.is_available() else 1)"
if errorlevel 1 (
    echo [ABBRUCH] Compute Capability ist nicht ^(12, 0^) oder CUDA nicht verfuegbar.
    echo           Ohne das ist alles Weitere sinnlos. Erst Treiber/Torch klaeren.
    goto :fail
)
echo [OK] Torch sieht die Blackwell-Karte.

echo.
echo ===========================================================
echo  BLOCK 3 - ComfyUI-Trellis2 und vorkompilierte Wheels
echo ===========================================================

if not exist "%TRELLIS%\__init__.py" (
    git clone --depth 1 https://github.com/visualbruno/ComfyUI-Trellis2 "%TRELLIS%" || goto :fail
) else (
    echo [SKIP] ComfyUI-Trellis2 bereits geklont
)

REM Dateinamen laut README des Nodes, Stand 2026-07-31. natten wird bewusst
REM NICHT installiert - nur fuer Pixal3D-T noetig und muesste kompiliert werden.
for %%W in (
    cumesh-1.0-cp311-cp311-win_amd64.whl
    nvdiffrast-0.4.0-cp311-cp311-win_amd64.whl
    nvdiffrec_render-0.0.0-cp311-cp311-win_amd64.whl
    flex_gemm-0.0.1-cp311-cp311-win_amd64.whl
    o_voxel-0.0.1-cp311-cp311-win_amd64.whl
) do (
    if not exist "%WHEELS%\%%W" (
        echo [ABBRUCH] Wheel fehlt: %WHEELS%\%%W
        echo           Der Node hat die Dateinamen geaendert - Ordner pruefen.
        goto :fail
    )
    "%PY%" -m pip install "%WHEELS%\%%W" || goto :fail
)

"%PY%" -m pip install -r "%TRELLIS%\requirements.txt" || goto :fail
REM Bekannte funktionierende Pins gegen Gradio/ASGI-Fehler
"%PY%" -m pip install pydantic==2.10.6 open3d==0.19.0 || goto :fail

echo.
echo --- SPERRE: alle CUDA-Module importierbar? ---
"%PY%" -c "import cumesh, nvdiffrast, o_voxel, flex_gemm; print('cumesh nvdiffrast o_voxel flex_gemm OK')" || goto :fail

echo.
echo ===========================================================
echo  BLOCK 4 - DINOv3  (gated, braucht HuggingFace-Login)
echo ===========================================================

if exist "%ROOT%\models\facebook\dinov3-vitl16-pretrain-lvd1689m\config.json" (
    echo [SKIP] DINOv3 bereits vorhanden
) else (
    echo.
    echo   DINOv3 ist auf HuggingFace gated. Vorher noetig:
    echo     1. https://huggingface.co/facebook/dinov3-vitl16-pretrain-lvd1689m
    echo        oeffnen und die Lizenz annehmen
    echo     2. Unter Settings - Access Tokens einen READ-Token anlegen
    echo     3. Im gleichen Fenster: hf auth login
    echo.
    pause
    "%PY%" -m pip install -U "huggingface_hub[cli]" || goto :fail
    "%ROOT%\venv\Scripts\hf.exe" auth login || goto :fail
    git lfs install
    git clone https://huggingface.co/facebook/dinov3-vitl16-pretrain-lvd1689m "%ROOT%\models\facebook\dinov3-vitl16-pretrain-lvd1689m" || goto :fail
)

echo.
echo ===========================================================
echo  FERTIG
echo ===========================================================
echo  Starten mit:  tools\start_comfyui.bat
echo  TRELLIS.2-4B ^(~10 GB^) laedt der Node beim ersten Lauf selbst.
echo.
pause
exit /b 0

:fail
echo.
echo [FEHLGESCHLAGEN] Siehe Meldung oben. Nichts weiter ausgefuehrt.
pause
exit /b 1
