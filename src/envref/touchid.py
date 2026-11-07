"""A Touch ID gate in front of a Keychain read.

Keychain items with a biometric access control (`kSecAccessControlBiometryCurrentSet`)
need a Developer-signed binary with entitlements, which a script compiled on
the fly does not have. So the helper splits the job: `LAContext` asks for the
fingerprint (no entitlements needed), and only on success does it call
`/usr/bin/security` to read an ordinary generic-password item. The item must
let `security` read it silently, which is the case when `security` created it.

The helper is compiled from `touchid/helper.swift` on first use into the cache
directory. Its file name is what macOS shows in the dialog ("envref wants to
authenticate"). Without `swiftc` or biometrics the caller falls back to a plain
`security` read, which shows the system's own authorisation dialog instead.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

HELPER_SOURCE = Path(__file__).with_name("touchid") / "helper.swift"


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base).expanduser() / "envref"


def helper_binary() -> Path | None:
    """Path to the compiled helper, building it if missing or stale. None when
    the source is missing or `swiftc` is not installed."""
    if not HELPER_SOURCE.exists() or not shutil.which("swiftc"):
        return None
    binary = cache_dir() / "touchid" / "envref"
    if binary.exists() and binary.stat().st_mtime >= HELPER_SOURCE.stat().st_mtime:
        return binary
    binary.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["swiftc", str(HELPER_SOURCE), "-o", str(binary)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return binary


def read_password_with_touch_id(service: str, account: str | None, reason: str) -> str | None:
    """Touch ID, then the Keychain item. Falls back to `security` alone when the
    helper cannot be built. None when the item is missing or the user declined."""
    binary = helper_binary()
    if binary is None:
        from envref.resolvers.keychain import read_generic_password

        return read_generic_password(service, account)
    result = subprocess.run(
        [str(binary), "get", service, account or "", reason],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", "replace").rstrip("\n") or None
