@echo off
title AttendAI Faculty Desktop Edge Station
cd /d "%~dp0\.."

set "PYTHON_EXE=attendance_system_test\venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE=python"
)

echo =========================================================
echo Starting AttendAI Faculty Desktop Edge Application...
echo Running with Python: %PYTHON_EXE%
echo =========================================================

"%PYTHON_EXE%" desktop_app\main.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Application exited with error code %ERRORLEVEL%.
    pause
)
