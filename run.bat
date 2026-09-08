@echo off
REM Double-click this to install everything, start the app, and open a browser.
setlocal enabledelayedexpansion
cd /d "%~dp0"

where uv >nul 2>nul
if not errorlevel 1 goto haveuv

REM uv brings its own Python and resolves the lockfile, so it is the only prerequisite.
REM Nothing is downloaded before you say yes.
echo This needs uv ^(https://docs.astral.sh/uv/^), which is not installed.
set /p reply="Install it now, for this user only? [y/N] "
if /i not "!reply!"=="y" goto nouv
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
REM The installer edits PATH for new shells, so add it for this one.
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>nul
if errorlevel 1 goto nopath

:haveuv
REM Creates .venv and installs from uv.lock. Fast, and a no-op once it is already there.
uv sync
uv run python run.py %*
pause
exit /b 0

:nouv
echo Nothing installed. Get uv from https://docs.astral.sh/uv/ and run this again.
pause
exit /b 1

:nopath
echo uv still is not on PATH. Open a new terminal and run this again.
pause
exit /b 1
