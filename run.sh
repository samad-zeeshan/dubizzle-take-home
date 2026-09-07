#!/bin/sh
# Run this to install dependencies, start the app, and open a browser.
set -e
cd "$(dirname "$0")"
if ! command -v uv >/dev/null 2>&1; then
  echo "uv is not installed. Get it from https://docs.astral.sh/uv/"
  exit 1
fi
uv sync
exec uv run python run.py "$@"
