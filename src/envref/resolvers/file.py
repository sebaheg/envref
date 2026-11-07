"""`file://path` — a file's contents, for keys and certificates that libraries
want as a string (`TLS_KEY={{ file://~/.ssh/server.pem }}`). `~` expands; a
relative path is relative to the working directory. One trailing newline is
dropped, since nothing wants it in an environment variable."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from envref.core import ResolveError


class FileResolver:
    scheme = "file"

    def resolve(self, refs: Sequence[str]) -> dict[str, str]:
        values: dict[str, str] = {}
        failures: dict[str, str] = {}
        for ref in refs:
            path = Path(ref.partition("://")[2]).expanduser()
            try:
                text = path.read_text()
            except OSError as exc:
                failures[ref] = exc.strerror or str(exc)
                continue
            values[ref] = text[:-1] if text.endswith("\n") else text
        if failures:
            raise ResolveError(failures)
        return values

    def doctor(self) -> str:
        return "ok"
