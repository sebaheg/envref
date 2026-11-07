"""Find resolvers: the built-in four plus anything installed under the
`envref.resolvers` entry-point group (name = scheme, value = `module:Class`)."""

from __future__ import annotations

from functools import lru_cache
from importlib.metadata import entry_points

from envref.core import Resolver

_GROUP = "envref.resolvers"


def _builtins() -> dict[str, Resolver]:
    from envref.resolvers.env import EnvResolver
    from envref.resolvers.file import FileResolver
    from envref.resolvers.keychain import KeychainResolver
    from envref.resolvers.op import OnePasswordResolver

    found = [EnvResolver(), FileResolver(), KeychainResolver(), OnePasswordResolver()]
    return {r.scheme: r for r in found}


@lru_cache(maxsize=1)
def registry() -> dict[str, Resolver]:
    """Scheme → resolver instance. Entry points override built-ins of the same name,
    so a user can swap the 1Password implementation without forking."""
    found = _builtins()
    for ep in entry_points(group=_GROUP):
        if ep.value.startswith("envref.resolvers."):
            continue  # our own registrations, already instantiated above
        found[ep.name] = ep.load()()
    return found
