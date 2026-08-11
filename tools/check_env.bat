@echo off
REM Prueft die harten Sperren einzeln nach. Aendert nichts.
setlocal
cd /d "%~dp0"
set "ROOT=%~dp0ComfyUI"
set "PY=%ROOT%\venv\Scripts\python.exe"

echo === GPU und Treiber ===
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv

echo.
echo === Python im venv ===
if not exist "%PY%" (echo [FEHLT] venv nicht angelegt & goto :end)
"%PY%" --version

echo.
echo === SPERRE 1: Torch sieht Blackwell? erwartet "2.7.0+cu128 True (12, 0)" ===
"%PY%" -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_capability())" 2>&1

echo.
echo === SPERRE 2: CUDA-Module des Nodes importierbar? ===
"%PY%" -c "import cumesh, nvdiffrast, o_voxel, flex_gemm; print('cumesh nvdiffrast o_voxel flex_gemm OK')" 2>&1

echo.
echo === SPERRE 3: DINOv3 vorhanden? ===
if exist "%ROOT%\models\facebook\dinov3-vitl16-pretrain-lvd1689m\config.json" (
    echo [OK] DINOv3 liegt in models\facebook
) else (
    echo [FEHLT] DINOv3 nicht heruntergeladen
)

:end
echo.
pause
