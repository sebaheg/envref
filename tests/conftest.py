import os
import stat
import sys
from pathlib import Path

import pytest

FAKE_OP = r'''#!/usr/bin/env python3
"""A stand-in for the 1Password CLI, driven by environment variables.

FAKE_OP_SESSION_REQUIRED=1  inject fails unless OP_SESSION_test is set
FAKE_OP_LOG=<path>          every invocation's argv is appended here
"""
import json, os, re, sys

args = sys.argv[1:]
log = os.environ.get("FAKE_OP_LOG")
if log:
    with open(log, "a") as fh:
        fh.write(" ".join(args) + "\n")

if args[:2] == ["account", "list"]:
    print(json.dumps([{"shorthand": "test", "email": "me@example.com", "account_uuid": "U1"}]))
    sys.exit(0)

if args[:1] == ["signin"]:
    pw = sys.stdin.readline().strip() if not sys.stdin.isatty() else ""
    if pw == "correct horse":
        print("SESSION-TOKEN-1")
        sys.exit(0)
    sys.exit(1)

if args[:1] == ["inject"]:
    if os.environ.get("FAKE_OP_SESSION_REQUIRED") == "1" and not os.environ.get("OP_SESSION_test"):
        print("[ERROR] 2026/01/01 00:00:00 You are not currently signed in.", file=sys.stderr)
        sys.exit(1)
    template = sys.stdin.read()
    values = {
        "op://vault/item/field": "s3cret",
        "op://vault/item/pem": "-----BEGIN KEY-----\nabc\n-----END KEY-----\n",
        "op://vault/other/x": "other",
    }
    def sub(m):
        ref = m.group(1).strip()
        if ref not in values:
            print(f"[ERROR] could not resolve {ref}", file=sys.stderr)
            sys.exit(1)
        return values[ref]
    sys.stdout.write(re.sub(r"\{\{\s*(op://[^}]*?)\s*\}\}", sub, template))
    sys.exit(0)

print("unknown fake op invocation: " + " ".join(args), file=sys.stderr)
sys.exit(1)
'''


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Keep every test off the real ~/.cache/envref and real 1Password settings."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    for var in ("OP_SERVICE_ACCOUNT_TOKEN", "OP_ACCOUNT", "ENVREF_OP_SESSION_TTL",
                "ENVREF_OP_KEYCHAIN_SERVICE", "ENVREF_OP_KEYCHAIN_ACCOUNT",
                "ENVREF_KEYCHAIN_TOUCH_ID", "FAKE_OP_SESSION_REQUIRED", "FAKE_OP_LOG"):
        monkeypatch.delenv(var, raising=False)
    for name in list(os.environ):
        if name.startswith("OP_SESSION_"):
            monkeypatch.delenv(name)


@pytest.fixture
def fake_op(tmp_path, monkeypatch):
    """Put a fake `op` first on PATH. Returns the path of its invocation log."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "op"
    script.write_text(FAKE_OP.replace("#!/usr/bin/env python3", f"#!{sys.executable}", 1))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    log = tmp_path / "op.log"
    monkeypatch.setenv("FAKE_OP_LOG", str(log))
    return log


@pytest.fixture
def no_touch_id(monkeypatch):
    """Never compile or run the Swift helper in tests."""
    import envref.touchid as touchid

    monkeypatch.setattr(touchid, "helper_binary", lambda: None)
