@echo off
setlocal
title Build Native VNC

pushd "%~dp0"
if errorlevel 1 (
    echo ERROR: Cannot open the project directory.
    pause
    exit /b 1
)

if not exist "run_native.py" (
    echo ERROR: Missing run_native.py.
    goto failed
)
if not exist "requirements.txt" (
    echo ERROR: Missing requirements.txt.
    goto failed
)
if not exist "NativeVNC.spec" (
    echo ERROR: Missing NativeVNC.spec.
    goto failed
)

if exist ".venv\Scripts\python.exe" goto dependencies
echo [1/3] Creating the build environment...
python -c "import sys" >nul 2>&1
if errorlevel 1 (
    py -3 -m venv ".venv"
) else (
    python -m venv ".venv"
)
if errorlevel 1 goto failed

:dependencies
echo [2/3] Installing build dependencies...
".venv\Scripts\python.exe" -m pip install -r "requirements.txt" pyinstaller
if errorlevel 1 goto failed

echo [3/3] Building Native VNC as a single file...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean "NativeVNC.spec"
if errorlevel 1 goto failed
if not exist "dist\NativeVNC.exe" goto failed

echo.
echo Build complete: "%CD%\dist\NativeVNC.exe"
echo Send this single NativeVNC.exe file to the other computer.
popd
pause
exit /b 0

:failed
echo.
echo Build failed. Check the error messages above.
popd
pause
exit /b 1
