@echo off
echo === MDT Data Extractor ===
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    py --version >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Python not found. Install from https://python.org
        pause
        exit /b 1
    )
    set PYTHON=py
) else (
    set PYTHON=python
)

:: Install dependencies
echo Installing dependencies...
%PYTHON% -m pip install -r requirements.txt -q
echo.

:: Start app
echo Starting MDT Extractor on http://localhost:5000
echo Press Ctrl+C to stop
echo.
%PYTHON% app.py
