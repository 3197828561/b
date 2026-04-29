@echo off
cd /d "%~dp0"
chcp 65001 >nul
title Kunshan Shangwei Bid Assistant - One Click Start

echo ================================================
echo Kunshan Shangwei Bid Assistant - One Click Start
echo ================================================
echo.

set "PY_CMD=python"
if exist ".venv\Scripts\python.exe" (
    set "PY_CMD=.venv\Scripts\python.exe"
)

echo Checking Python...
%PY_CMD% --version
if errorlevel 1 (
    echo Python is not installed or not in PATH.
    pause
    exit /b 1
)

echo Checking Node.js...
node --version
if errorlevel 1 (
    echo Node.js is not installed or not in PATH.
    pause
    exit /b 1
)

echo.
echo Step 1/2: Build frontend assets...
pushd frontend
call npm install
if errorlevel 1 (
    echo npm install failed.
    popd
    pause
    exit /b 1
)
call npm run build
if errorlevel 1 (
    echo npm run build failed.
    popd
    pause
    exit /b 1
)
popd

echo.
echo Step 2/2: Copy frontend build to backend/static...
if exist backend\static rmdir /s /q backend\static
xcopy /e /i /y frontend\build backend\static >nul
if errorlevel 1 (
    echo Copy static files failed.
    pause
    exit /b 1
)

echo.
echo Starting integrated app...
echo URL: http://localhost:8000
echo Docs: http://localhost:8000/docs
echo.
echo Browser will open automatically in a few seconds.
echo Press Ctrl+C to stop.
echo ================================================

%PY_CMD% -X utf8 app_launcher.py

echo.
echo Service stopped.
pause