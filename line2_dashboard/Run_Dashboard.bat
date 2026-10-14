@echo off
rem ======================================================================
rem  Starts the Line-2 dashboard (app.py) and starts it again if it stops.
rem  Open http://localhost:5001/ in a browser on this PC
rem  (from other PCs: http://<this PC's IP>:5001/).
rem  To start it after every restart: Win+R, shell:startup, put a shortcut to this file there.
rem ======================================================================

cd /d "%~dp0"
title Line-2 Dashboard
:run
python app.py
echo.
echo Dashboard stopped - starting again in 10 s (close this window to stop it).
timeout /t 10 /nobreak >nul
goto run
