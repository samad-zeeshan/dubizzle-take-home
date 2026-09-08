#!/bin/sh
# Run this to install everything, start the app, and open a browser.
set -e
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  # uv brings its own Python and resolves the lockfile, so it is the only prerequisite.
  # Nothing is downloaded before you say yes.
  echo "This needs uv (https://docs.astral.sh/uv/), which is not installed."
  printf "Install it now, for this user only? [y/N] "
  read -r reply || reply=n
  case "$reply" in
    [yY]*) curl -LsSf https://astral.sh/uv/install.sh | sh ;;
    *) echo "Nothing installed. Get uv yourself, then run this again."; exit 1 ;;
  esac
  # The installer edits the shell profile, which this shell already read, so add it by hand.
  PATH="$HOME/.local/bin:$PATH"
  export PATH
  if ! command -v uv >/dev/null 2>&1; then
    echo "uv still is not on PATH. Open a new terminal and run this again."
    exit 1
  fi
fi

# Creates .venv and installs from uv.lock. Fast and a no-op once it is already there.
uv sync
exec uv run python run.py "$@"
