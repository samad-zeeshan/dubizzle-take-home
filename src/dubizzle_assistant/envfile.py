"""
Write a Gemini key into .env, from the launcher or from the client.

One implementation, because two of them would drift and this file holds a credential.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

KEY = "GEMINI_API_KEY"


def looks_like_a_key(value: str) -> bool:
    """Catch a typo without guessing at Google's format.

    Studio has issued at least two shapes, AIza... and AQ.A..., so matching a prefix would
    have refused a working key. Length and no whitespace is all that can be claimed honestly.
    """
    value = value.strip()
    # Both halves are needed. isspace alone missed a null byte, which sailed through and then
    # killed os.environ; isprintable alone allows a space, which is a split paste. And a
    # credential two hundred characters long is not a credential.
    return 20 <= len(value) <= 200 and all(c.isprintable() and not c.isspace() for c in value)


def masked(value: str) -> str:
    """Enough to recognise which key is in place, never enough to use it."""
    value = value.strip()
    return f"{value[:4]}…{value[-4:]}" if len(value) >= 12 else "set"


def write_key(env: Path, value: str) -> Path:
    """Put the key in this file, keeping every other line, and take it off group and world.

    Takes the file rather than a directory, because a caller pointing at another name for it
    otherwise silently got the default one next door.

    Seeds from .env.example when the file does not exist yet, so comments and defaults survive.
    """
    value = value.strip()
    if not looks_like_a_key(value):
        raise ValueError("that does not look like a Gemini key")

    example = env.with_name(".env.example")
    source = env if env.exists() else example
    lines = source.read_text(encoding="utf-8").splitlines() if source.exists() else []

    out, replaced = [], False
    for line in lines:
        if line.split("=", 1)[0].strip() == KEY:
            out.append(f"{KEY}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.insert(0, f"{KEY}={value}")

    env.write_text("\n".join(out) + "\n", encoding="utf-8")
    with contextlib.suppress(OSError):
        env.chmod(0o600)
    return env
