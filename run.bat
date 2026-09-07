@echo off
REM Double-click this to install dependencies, start the app, and open a browser.
cd /d "%~dp0"
where uv >nul 2>nul || (
  echo uv is not installed. Get it from https://docs.astral.sh/uv/
  pause
  exit /b 1
)
uv sync
uv run python run.py %*
pause
