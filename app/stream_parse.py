"""Pull complete objects out of a JSON document while it is still streaming.

The composer streams {"theme": ..., "headline": ..., "ui_components_ordered": [{...}, {...}]}.
ComponentScanner.feed() returns each component object the moment its closing
brace arrives, so the UI can render it while the model is still writing the next.
"""

from __future__ import annotations

import contextlib
import json
import re

ARRAY_KEY = '"ui_components_ordered"'


class ComponentScanner:
    def __init__(self) -> None:
        self.buf = ""
        self._pos = 0  # next character to scan
        self._in_array = False
        self._depth = 0  # brace depth inside the array
        self._start = -1
        self._in_str = False
        self._escape = False

    def feed(self, chunk: str) -> list[dict]:
        self.buf += chunk
        found: list[dict] = []
        if not self._in_array:
            key = self.buf.find(ARRAY_KEY)
            bracket = self.buf.find("[", key) if key >= 0 else -1
            if bracket < 0:
                return found
            self._in_array, self._pos = True, bracket + 1
        while self._pos < len(self.buf):
            ch = self.buf[self._pos]
            if self._in_str:
                if self._escape:
                    self._escape = False
                elif ch == "\\":
                    self._escape = True
                elif ch == '"':
                    self._in_str = False
            elif ch == '"':
                self._in_str = True
            elif ch == "{":
                if self._depth == 0:
                    self._start = self._pos
                self._depth += 1
            elif ch == "}":
                self._depth -= 1
                if self._depth == 0 and self._start >= 0:
                    with contextlib.suppress(json.JSONDecodeError):  # malformed object: skip it, keep scanning
                        found.append(json.loads(self.buf[self._start : self._pos + 1]))
                    self._start = -1
            self._pos += 1
        return found

    def head(self) -> dict:
        """theme and headline, as soon as they have streamed."""
        out = {}
        for key in ("theme", "headline"):
            m = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"', self.buf)
            if m:
                out[key] = json.loads(f'"{m.group(1)}"')
        return out
