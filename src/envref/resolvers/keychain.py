"""`keychain://service/account` — a macOS Keychain generic password.

Reads with `security find-generic-password -w`. macOS shows its own
authorisation dialog when the item's access control asks for one. Set
`ENVREF_KEYCHAIN_TOUCH_ID=1` to require Touch ID in front of every read via the
bundled helper (see `envref.touchid`). Store an item with:

    security add-generic-password -U -s <service> -a <account> -w
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from collections.abc import Sequence

from envref.core import ResolveError, ResolverUnavailable


def read_generic_password(service: str, account: str | None) -> str | None:
    """The password, or None when the item does not exist or the user declined."""
    cmd = ["security", "find-generic-password", "-w", "-s", service]
    if account:
        cmd += ["-a", account]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    return result.stdout.rstrip("\n") or None


def save_generic_password(service: str, account: str, password: str) -> None:
    """Create or update (-U) the item. The creating tool, `security`, is placed on
    the item's access list, so later reads from it are silent."""
    subprocess.run(
        ["security", "add-generic-password", "-U", "-s", service, "-a", account, "-w", password],
        check=True,
        capture_output=True,
        text=True,
    )


class KeychainResolver:
    scheme = "keychain"

    def available(self) -> str | None:
        """Why this resolver cannot run here, or None when it can."""
        if platform.system() != "Darwin":
            return "macOS Keychain is only available on macOS"
        if not shutil.which("security"):
            return "the `security` tool is not on PATH"
        return None

    def resolve(self, refs: Sequence[str]) -> dict[str, str]:
        reason = self.available()
        if reason:
            raise ResolverUnavailable(reason)

        touch_id = os.environ.get("ENVREF_KEYCHAIN_TOUCH_ID", "") not in ("", "0", "false")
        values: dict[str, str] = {}
        failures: dict[str, str] = {}
        for ref in refs:
            service, _, account = ref.partition("://")[2].partition("/")
            if touch_id:
                from envref.touchid import read_password_with_touch_id

                value = read_password_with_touch_id(service, account or None, "unlock the keychain")
            else:
                value = read_generic_password(service, account or None)
            if value is None:
                failures[ref] = "no such item, or access was denied"
            else:
                values[ref] = value
        if failures:
            raise ResolveError(failures)
        return values

    def doctor(self) -> str:
        return self.available() or "ok"
