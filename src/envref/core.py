"""Resolve parsed entries through the resolver each scheme names, and export."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from envref.parse import Entry, parse_file


class EnvrefError(Exception):
    """Base class; everything envref raises on purpose derives from it."""


class UnknownScheme(EnvrefError):
    """A `{{ scheme://… }}` reference whose scheme has no resolver installed."""


class ResolverUnavailable(EnvrefError):
    """The resolver exists but cannot run here: no `op` binary, not macOS, no token."""


class ResolveError(EnvrefError):
    """One or more references could not be resolved. `failures` maps ref → reason."""

    def __init__(self, failures: Mapping[str, str], hint: str = "") -> None:
        self.failures = dict(failures)
        lines = [f"  {ref}: {reason}" for ref, reason in sorted(self.failures.items())]
        message = "could not resolve:\n" + "\n".join(lines)
        if hint:
            message += f"\n{hint}"
        super().__init__(message)


@runtime_checkable
class Resolver(Protocol):
    """What a scheme's backend provides. `resolve` gets every reference of its
    scheme in one call so backends can batch (one round trip, one unlock)."""

    scheme: str

    def resolve(self, refs: Sequence[str]) -> dict[str, str]:
        """Map each reference to its value. Raise `ResolveError` for the ones
        that fail, `ResolverUnavailable` when the backend cannot run at all."""
        ...


def _registry(registry: Mapping[str, Resolver] | None) -> Mapping[str, Resolver]:
    if registry is not None:
        return registry
    from envref.resolvers import registry as default_registry

    return default_registry()


def resolve(
    entries: Iterable[Entry], *, registry: Mapping[str, Resolver] | None = None
) -> dict[str, str]:
    """Return name → value for every entry, references resolved.

    References are grouped by scheme and handed to that scheme's resolver in
    one call. A bare (brace-less) reference whose scheme has no resolver is
    kept as the literal it probably was; an explicit `{{ }}` one raises.
    """
    resolvers = _registry(registry)
    entries = list(entries)

    by_scheme: dict[str, list[str]] = {}
    for entry in entries:
        if entry.ref is None:
            continue
        scheme = entry.scheme or ""
        if scheme not in resolvers:
            if entry.explicit:
                known = ", ".join(sorted(resolvers)) or "none"
                raise UnknownScheme(
                    f"{entry.name} (line {entry.line}): no resolver for '{scheme}://'. "
                    f"Installed: {known}."
                )
            continue
        by_scheme.setdefault(scheme, []).append(entry.ref)

    values: dict[str, str] = {}
    for scheme, refs in by_scheme.items():
        unique = sorted(set(refs))
        resolved = resolvers[scheme].resolve(unique)
        missing = [ref for ref in unique if ref not in resolved]
        if missing:
            raise ResolveError({ref: "resolver returned no value" for ref in missing})
        values.update(resolved)

    result: dict[str, str] = {}
    for entry in entries:
        if entry.ref is not None and entry.ref in values:
            result[entry.name] = values[entry.ref]
        else:
            result[entry.name] = entry.value
    return result


def load(
    *paths: str | Path,
    export: bool = True,
    override: bool = False,
    registry: Mapping[str, Resolver] | None = None,
    environ: dict[str, str] | None = None,
) -> dict[str, str]:
    """Resolve one or more env files and, by default, export into `os.environ`.

    Files are read in order and the first file to set a name wins, so
    `load(".env.op", ".env")` lets a local `.env` fill in what the references
    file lacks without overriding it. Missing files are skipped. Variables
    already in the environment are kept unless `override=True`.
    """
    environ = os.environ if environ is None else environ
    entries: list[Entry] = []
    seen: set[str] = set()
    for path in paths or (".env",):
        file = Path(path).expanduser()
        if not file.exists():
            continue
        for entry in parse_file(file):
            if entry.name in seen:
                continue
            seen.add(entry.name)
            entries.append(entry)

    values = resolve(entries, registry=registry)
    if export:
        for name, value in values.items():
            if override or name not in environ:
                environ[name] = value
    return values
