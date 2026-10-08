@echo off
rem ======================================================================
rem  Line-2 dashboard full screen on the digital standee.
rem  This PC sends its picture to the standee over HDMI (wireless HDMI).
rem  Double-click to start. To start it after every restart of this PC:
rem  Win+R, type  shell:startup , and put a shortcut to this file there.
rem  To close the full-screen page: click on it and press Alt+F4.
rem ======================================================================

rem ---- settings --------------------------------------------------------
rem Page to show. If the dashboard (app.py) runs on this PC keep localhost,
rem otherwise put the dashboard PC's address, e.g. http://172.25.x.x:5001/station/7
set "URL=http://localhost:5001/station/7"

rem Where the standee screen starts in Windows' display layout (Settings > Display):
rem   standee extended to the RIGHT of a 1920-wide laptop screen  -> 1920
rem   standee is this PC's only / main screen                     -> 0
set "SCREEN_X=1920"
rem ----------------------------------------------------------------------

rem own browser profile: always a fresh window on the standee, even if the
rem browser is already open on the laptop screen
set "PROFILE=%LOCALAPPDATA%\Line2Standee"

set "BROWSER=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%BROWSER%" set "BROWSER=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%BROWSER%" set "BROWSER=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not exist "%BROWSER%" set "BROWSER=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if not exist "%BROWSER%" (
    echo Chrome or Edge not found.
    pause
    exit /b 1
)

rem after a restart give the network and the dashboard a moment
timeout /t 20 /nobreak >nul

start "" "%BROWSER%" --kiosk "%URL%" --edge-kiosk-type=fullscreen --window-position=%SCREEN_X%,0 ^
    --user-data-dir="%PROFILE%" --no-first-run --no-default-browser-check ^
    --disable-session-crashed-bubble --disable-features=Translate --overscroll-history-navigation=0
