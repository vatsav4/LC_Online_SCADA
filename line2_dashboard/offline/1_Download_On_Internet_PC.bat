@echo off
rem ======================================================================
rem  Run this on a PC WITH internet (Windows 64-bit, Python installed).
rem  It downloads the two Python packages the dashboard needs (Flask, pyodbc
rem  and what they depend on) into the folder "wheels" next to this file.
rem  Then copy the whole line2_dashboard folder to the new PC on a USB stick.
rem ======================================================================

rem Python version that will be installed on the NEW PC (first two numbers)
set "PYVER=3.12"

cd /d "%~dp0"
python -m pip download -r ..\requirements.txt -d wheels --only-binary=:all: --platform win_amd64 --python-version %PYVER%
rem click (part of Flask) needs colorama on Windows
python -m pip download colorama -d wheels --only-binary=:all: --platform win_amd64 --python-version %PYVER%
if errorlevel 1 (
    echo.
    echo Download failed - check the internet connection and that Python / pip work on this PC.
    pause
    exit /b 1
)
echo.
echo Done. Also put these two installers on the USB stick (download them on this PC):
echo   - Python %PYVER% for Windows, 64-bit installer          (python.org - Downloads - Windows)
echo   - Microsoft ODBC Driver 18 for SQL Server, x64 .msi     (search: "Download ODBC Driver for SQL Server")
pause
