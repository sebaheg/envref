"""Read a `.env` file into entries, telling references from literals.

The grammar is the ordinary dotenv one — `KEY=value`, optional `export `,
`#` comments, single or double quotes — plus one rule: a value that is
`{{ scheme://… }}` is a *reference*, to be resolved before export. That is
`op inject`'s mustache syntax, so files written for it are valid as they are.

A bare `scheme://…` without braces is also flagged as a possible reference,
because the 1Password SDK and `op read` speak that form. Whether it is treated
as one is decided later, by whether a resolver for that scheme exists: an
`https://` URL stays a literal, an `op://` without braces resolves.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
_MUSTACHE = re.compile(r"^\{\{\s*([A-Za-z][A-Za-z0-9+.-]*://[^}]*?)\s*\}\}$")
_BARE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://\S+$")


@dataclass(frozen=True)
class Entry:
    name: str
    value: str
    """The literal value, or the reference text (`scheme://…`) when `ref` is set."""
    ref: str | None
    """`scheme://…` for a reference, None for a literal."""
    explicit: bool
    """True when the reference was written with `{{ }}`: an unknown scheme is then an error."""
    line: int

    @property
    def scheme(self) -> str | None:
        return self.ref.partition("://")[0] if self.ref else None


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        inner = value[1:-1]
        if value[0] == '"':
            inner = inner.replace(r"\n", "\n").replace(r"\"", '"').replace(r"\\", "\\")
        return inner
    # An unquoted value ends at ` #`, the way dotenv parsers agree it does.
    head, _sep, _comment = value.partition(" #")
    return head.rstrip()


def parse(text: str) -> list[Entry]:
    """Every assignment in `text`, in file order. Later duplicates win at load time."""
    entries: list[Entry] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        match = _ASSIGNMENT.match(raw)
        if match is None:
            continue
        name, value = match.group(1), match.group(2)
        mustache = _MUSTACHE.match(value)
        if mustache:
            entries.append(Entry(name, mustache.group(1), mustache.group(1), True, number))
            continue
        value = _unquote(value)
        bare = _BARE.match(value)
        if bare:
            entries.append(Entry(name, value, value, False, number))
        else:
            entries.append(Entry(name, value, None, False, number))
    return entries


def parse_file(path: str | Path) -> list[Entry]:
    return parse(Path(path).expanduser().read_text())
