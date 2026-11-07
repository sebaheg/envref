"""`env://NAME` — another environment variable. Useful for aliasing a name a
library insists on (`GITHUB_TOKEN={{ env://GH_TOKEN }}`)."""

from __future__ import annotations

import os
from collections.abc import Sequence

from envref.core import ResolveError


class EnvResolver:
    scheme = "env"

    def resolve(self, refs: Sequence[str]) -> dict[str, str]:
        values: dict[str, str] = {}
        failures: dict[str, str] = {}
        for ref in refs:
            name = ref.partition("://")[2]
            if name in os.environ:
                values[ref] = os.environ[name]
            else:
                failures[ref] = f"{name} is not set"
        if failures:
            raise ResolveError(failures)
        return values

    def doctor(self) -> str:
        return "ok"
