@echo off
title AttendAI Faculty Desktop Edge Station
cd /d "%~dp0"

echo =========================================================
echo Launching AttendAI Faculty Desktop Edge Application...
echo =========================================================

set "PYTHON_EXE=attendance_system_test\venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE=python"
)

"%PYTHON_EXE%" desktop_app\main.py

echo.
echo Application closed.
pause
