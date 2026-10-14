@echo off
rem ======================================================================
rem  Run this on the NEW PC (no internet needed), after installing
rem    1. Python (tick "Add python.exe to PATH" in the installer)
rem    2. Microsoft ODBC Driver 18 for SQL Server (x64 .msi)
rem  It installs Flask and pyodbc from the "wheels" folder next to this file.
rem ======================================================================

cd /d "%~dp0"
python --version
if errorlevel 1 (
    echo Python not found - install it first and tick "Add python.exe to PATH".
    pause
    exit /b 1
)
python -m pip install --no-index --find-links wheels -r ..\requirements.txt
if errorlevel 1 (
    echo.
    echo Install failed - was 1_Download_On_Internet_PC.bat run for the same Python version?
    pause
    exit /b 1
)
echo.
echo Done. Next: put config.ini into the line2_dashboard folder and start Run_Dashboard.bat
pause
