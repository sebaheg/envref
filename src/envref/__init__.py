"""envref — a .env where any value can be a reference into a secret store.

    ATTIO_KEY={{ op://vault/Attio/api_key }}
    DB_PASSWORD={{ keychain://myapp/db }}
    TLS_KEY={{ file://~/.ssh/server.pem }}
    REGION=eu-north-1

    >>> import envref
    >>> envref.load(".env")          # resolves every reference, exports the rest

The scheme of a reference picks the resolver. Four ship built in (`op`,
`keychain`, `file`, `env`); others register through the `envref.resolvers`
entry-point group.
"""

from envref.core import (
    EnvrefError,
    Resolver,
    ResolveError,
    ResolverUnavailable,
    UnknownScheme,
    load,
    resolve,
)
from envref.parse import Entry, parse

__version__ = "0.1.0"

__all__ = [
    "Entry",
    "EnvrefError",
    "ResolveError",
    "Resolver",
    "ResolverUnavailable",
    "UnknownScheme",
    "__version__",
    "load",
    "parse",
    "resolve",
]
