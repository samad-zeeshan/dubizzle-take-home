"""
Start the backend, the client, and a browser with one command.

Picks the mode from what is on the machine, so a reviewer with no API key still gets a
working app rather than an error on the first turn.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def first_free_port(start: int) -> int:
    """Ports are often already taken by an editor or an earlier run, so step past them."""
    for port in range(start, start + 20):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise SystemExit(f"no free port between {start} and {start + 19}")


def gemini_key_present() -> bool:
    # Read .env directly rather than importing settings, because settings raises on a bad
    # value and this has to answer before anything else starts.
    if os.environ.get("GEMINI_API_KEY", "").strip():
        return True
    env_file = ROOT / ".env"
    if not env_file.exists():
        return False
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == "GEMINI_API_KEY" and value.strip():
            return True
    return False


def wait_for_backend(base_url: str, process: subprocess.Popen[bytes], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.4)
    return False


def spawn(command: list[str], env: dict[str, str]) -> subprocess.Popen[bytes]:
    # A separate process group on Windows keeps Ctrl+C from killing this script before it
    # has a chance to shut the children down.
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    return subprocess.Popen(command, cwd=ROOT, env=env, creationflags=flags)


def stop(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the assistant: backend, client, browser.")
    parser.add_argument(
        "--mode",
        choices=("auto", "live", "mock"),
        default="auto",
        help="auto uses the model when a key is present, otherwise the offline stand-in",
    )
    parser.add_argument("--port", type=int, default=8000, help="backend port")
    parser.add_argument("--client-port", type=int, default=8501, help="Streamlit port")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser")
    parser.add_argument("--no-seed", action="store_true", help="skip the returning-user demo data")
    args = parser.parse_args()

    mode = args.mode
    if mode == "auto":
        mode = "live" if gemini_key_present() else "mock"

    api_port = first_free_port(args.port)
    client_port = first_free_port(args.client_port)
    base_url = f"http://127.0.0.1:{api_port}"

    env = os.environ.copy()
    env["BACKEND_URL"] = base_url
    env["BACKEND_PORT"] = str(api_port)
    if mode == "mock":
        env["LLM_PROVIDER"] = "mock"

    # A missing database means a fresh clone, and that is the only time seeding is safe.
    # Running it twice would stack duplicate searches and a second booking onto Sara.
    fresh = not (ROOT / "data" / "app.db").exists()

    backend = client = None
    try:
        print(f"Starting the backend on {base_url} ...", flush=True)
        backend = spawn(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(api_port),
            ],
            env,
        )
        if not wait_for_backend(base_url, backend, timeout=90):
            print("\nThe backend did not start. Its output is above.", file=sys.stderr)
            return 1

        if fresh and not args.no_seed:
            subprocess.run([sys.executable, "scripts/seed_demo_user.py"], cwd=ROOT, env=env)

        client = spawn(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                "app.py",
                "--server.port",
                str(client_port),
                "--server.headless",
                "true",
                "--browser.gatherUsageStats",
                "false",
            ],
            env,
        )

        client_url = f"http://localhost:{client_port}"
        engine = "Gemini" if mode == "live" else "the offline stand-in, so no API key is needed"
        print(
            f"\n  Sayara is running on {client_url}\n"
            f"  Answers come from {engine}.\n\n"
            f"  Try:  show me a white SUV under 150k\n"
            f"        what's the mileage on that first one?\n"
            f"  A returning customer named Sara is already in the database, so"
            f" try:  hi, it's Sara\n\n"
            f"  Stop both servers with Ctrl+C.\n",
            flush=True,
        )
        if not args.no_browser:
            webbrowser.open(client_url)

        client.wait()
    except KeyboardInterrupt:
        print("\nStopping.", flush=True)
    finally:
        stop(client)
        stop(backend)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
