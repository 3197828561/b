@echo off
cd /d "%~dp0"
chcp 65001 >nul
echo ================================================
echo Kunshan Shangwei Bid Assistant - Build EXE
echo ================================================
echo.
set "PY_CMD=python"
if exist ".venv\Scripts\python.exe" (
    set "PY_CMD=.venv\Scripts\python.exe"
)

echo Checking Python environment...
%PY_CMD% --version
if errorlevel 1 (
    echo Python is not installed or not in PATH.
    pause
    exit /b 1
)
echo.
echo Checking Node.js environment...
node --version
if errorlevel 1 (
    echo Node.js is not installed or not in PATH.
    pause
    exit /b 1
)
echo.
echo Starting build...
echo The build process will clean these paths first:
echo   - dist/
echo   - build/
echo   - frontend/build/
echo   - backend/static/
echo   - __pycache__/
echo   - *.spec
echo.
%PY_CMD% -X utf8 build.py
if errorlevel 1 (
    echo.
    echo ================================================
    echo Build failed. Please check the error messages above.
    echo ================================================
) else (
    echo.
    echo ================================================
    echo Build succeeded!
    echo EXE path: dist\ks-shangwei-bid-assistant.exe
    echo ================================================
)
echo.
pause