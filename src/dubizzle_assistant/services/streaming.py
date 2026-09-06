"""
Turn raw model deltas into draft text the client may show: released a sentence at a time through the reply scrub.

The final reply still goes through the full post-filter and grounding check,
and may replace the draft. Streaming only makes the wait feel shorter.
"""

from __future__ import annotations

import re
from collections.abc import Callable

_BOUNDARY_RE = re.compile(r"[.!?]\s|\n")
_HEX_RE = re.compile(r"^[0-9a-fA-F]{4}$")
_SIMPLE_ESCAPES = {
    "n": "\n",
    "t": "\t",
    '"': '"',
    "\\": "\\",
    "/": "/",
    "r": "\r",
    "b": "\b",
    "f": "\f",
}


class SentenceGate:
    """Buffers deltas and emits complete sentences through scrub, so a phone number never leaks mid-stream."""

    def __init__(self, scrub: Callable[[str], str], emit: Callable[[str], None]) -> None:
        self._scrub = scrub
        self._emit = emit
        self._buf = ""
        self.emitted = ""

    def feed(self, text: str) -> None:
        self._buf += text
        cut = 0
        for m in _BOUNDARY_RE.finditer(self._buf):
            cut = m.end()
        if cut:
            self._release(self._buf[:cut])
            self._buf = self._buf[cut:]

    def close(self) -> None:
        if self._buf:
            self._release(self._buf)
            self._buf = ""

    def _release(self, chunk: str) -> None:
        out = self._scrub(chunk)
        self.emitted += out
        self._emit(out)


class ReplyFieldExtractor:
    """Pulls the reply_markdown string out of a structured JSON reply while it is still being generated."""

    def __init__(self, key: str = "reply_markdown") -> None:
        self._key = f'"{key}"'
        self._buf = ""
        self._state = 0  # 0 find key, 1 find opening quote, 2 inside the string, 3 done
        self._pending = ""  # an escape sequence cut by a chunk boundary

    def feed(self, delta: str) -> str:
        if self._state == 3:
            return ""
        if self._state == 0:
            self._buf += delta
            idx = self._buf.find(self._key)
            if idx < 0:
                self._buf = self._buf[-(len(self._key) - 1) :]
                return ""
            self._state = 1
            delta = self._buf[idx + len(self._key) :]
            self._buf = ""
        if self._state == 1:
            q = delta.find('"')
            if q < 0:
                return ""
            self._state = 2
            delta = delta[q + 1 :]
        return self._consume(self._pending + delta)

    def _consume(self, text: str) -> str:
        out: list[str] = []
        i = 0
        self._pending = ""
        while i < len(text):
            ch = text[i]
            if ch == '"':
                self._state = 3
                break
            if ch != "\\":
                out.append(ch)
                i += 1
                continue
            if i + 1 >= len(text):
                self._pending = text[i:]
                break
            nxt = text[i + 1]
            if nxt == "u":
                hexpart = text[i + 2 : i + 6]
                if len(hexpart) < 4:
                    self._pending = text[i:]
                    break
                out.append(chr(int(hexpart, 16)) if _HEX_RE.match(hexpart) else "")
                i += 6
                continue
            out.append(_SIMPLE_ESCAPES.get(nxt, nxt))
            i += 2
        return "".join(out)
