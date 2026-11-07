"""`op://vault/item/field` — 1Password.

Two ways to ask, picked by the environment:

* **Service account** when `OP_SERVICE_ACCOUNT_TOKEN` is set: the `onepassword-sdk`
  package (`pip install envref[op]`), no binary, no biometrics, nobody present.
  For containers and scheduled jobs.
* **CLI** otherwise: the `op` binary on PATH. All references go through one
  `op inject` call. If that fails for want of a session, `op signin` mints one,
  the account password coming from macOS Keychain behind Touch ID when
  `envref op save-password` has stored it there, or from the terminal when not.
  The session token is cached (see SECURITY.md) so a burst of commands costs one
  sign-in rather than one each; concurrent processes share it through a lock.

Session caching presumes "biometric unlock for the 1Password CLI" is *off* in
the 1Password app. With it on, `op signin --raw` returns nothing and `op`
prompts per invocation; this resolver then degrades to a single `op inject`.

Environment knobs: `OP_ACCOUNT` (shorthand, when several accounts are signed
in), `ENVREF_OP_SESSION_TTL` (seconds, default 1500, 0 disables the cache),
`ENVREF_OP_KEYCHAIN_SERVICE` (default `envref-op`), `ENVREF_OP_KEYCHAIN_ACCOUNT`
(default: the account's email).
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import re
import secrets
import shutil
import subprocess
import time
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from envref.core import ResolveError, ResolverUnavailable
from envref.touchid import cache_dir

KEYCHAIN_SERVICE_DEFAULT = "envref-op"
_INTEGRATION_NAME = "envref"
_INTEGRATION_VERSION = "v1.0.0"


def session_ttl() -> int:
    """Buffer under op's ~30-minute sliding timeout, so renewal happens before a
    mid-run auth failure. 0 disables caching altogether."""
    return int(os.environ.get("ENVREF_OP_SESSION_TTL", 25 * 60))


def session_cache_path() -> Path:
    return cache_dir() / "op-session.json"


def keychain_service() -> str:
    return os.environ.get("ENVREF_OP_KEYCHAIN_SERVICE", KEYCHAIN_SERVICE_DEFAULT)


# --- session cache --------------------------------------------------------


def read_cached_session() -> dict | None:
    path = session_cache_path()
    if session_ttl() <= 0 or not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not (data.get("account") and data.get("token")):
        return None
    if time.time() - float(data.get("mtime", 0)) > session_ttl():
        return None
    return data


def write_cached_session(account: str, token: str) -> None:
    if session_ttl() <= 0:
        return
    path = session_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"account": account, "token": token, "mtime": time.time()}))
    tmp.chmod(0o600)
    tmp.replace(path)


def touch_cached_session() -> None:
    """A successful use extends op's sliding window; mirror that in the cache."""
    path = session_cache_path()
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text())
        data["mtime"] = time.time()
        path.write_text(json.dumps(data))
        path.chmod(0o600)
    except (OSError, json.JSONDecodeError):
        return


@contextmanager
def _signin_lock() -> Iterator[None]:
    """Serialise sign-ins across processes, so shells that start together on an
    expired session raise one Touch ID prompt rather than one each."""
    lock = cache_dir() / "op-signin.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


# --- accounts -------------------------------------------------------------


def _accounts() -> list[dict]:
    result = subprocess.run(
        ["op", "account", "list", "--format=json"], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return []
    try:
        return json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return []


def resolve_account(cached: dict | None = None) -> str | None:
    """The account shorthand to sign in to: `OP_ACCOUNT`, else the cached one,
    else the only signed-in account. Several accounts with no `OP_ACCOUNT` is an
    error, since guessing would sign in to the wrong vault."""
    if os.environ.get("OP_ACCOUNT"):
        return os.environ["OP_ACCOUNT"]
    if cached and cached.get("account"):
        return cached["account"]
    accounts = _accounts()
    if len(accounts) == 1:
        return accounts[0].get("shorthand") or accounts[0].get("account_uuid")
    if len(accounts) > 1:
        raise ResolveError(
            {"op://": "several 1Password accounts are signed in"},
            "Set OP_ACCOUNT to the shorthand of the one to use.",
        )
    return None


def account_email(account: str) -> str | None:
    for acct in _accounts():
        if account in (
            acct.get("shorthand"),
            acct.get("email"),
            acct.get("account_uuid"),
            acct.get("user_uuid"),
        ):
            return acct.get("email")
    return None


def keychain_account(account: str) -> str:
    return os.environ.get("ENVREF_OP_KEYCHAIN_ACCOUNT") or account_email(account) or account


def signin(account: str) -> str | None:
    """Mint a session token. The password comes from Keychain (behind Touch ID)
    when stored; otherwise `op signin` prompts on the terminal."""
    from envref.touchid import read_password_with_touch_id

    password = read_password_with_touch_id(
        keychain_service(), keychain_account(account), "unlock the 1Password session"
    )
    cmd = ["op", "signin", "--raw", "--account", account]
    if password is not None:
        result = subprocess.run(
            cmd, input=password + "\n", capture_output=True, text=True, check=False
        )
    else:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def save_password(account: str, password: str) -> tuple[str, str]:
    """Store the account password in Keychain for `signin`. Returns (service, account)."""
    from envref.resolvers.keychain import save_generic_password

    service, name = keychain_service(), keychain_account(account)
    save_generic_password(service, name, password)
    return service, name


# --- resolution -----------------------------------------------------------


def _template(refs: Sequence[str], marker: str) -> str:
    """One `op inject` template for every reference. Values are fenced by a
    per-run random marker, so a multi-line value (a PEM key) survives intact."""
    return "".join(f"{marker}{i}{marker}{{{{ {ref} }}}}{marker}\n" for i, ref in enumerate(refs))


def _parse_injected(output: str, refs: Sequence[str], marker: str) -> dict[str, str]:
    pattern = re.compile(re.escape(marker) + r"(\d+)" + re.escape(marker) + r"(.*?)" + re.escape(marker), re.S)
    return {refs[int(index)]: value for index, value in pattern.findall(output)}


def _inject(refs: Sequence[str], env: dict[str, str]) -> tuple[dict[str, str] | None, str]:
    """Resolve via `op inject`. (values, "") on success, (None, stderr) on failure."""
    marker = f"\x1f{secrets.token_hex(8)}\x1f"
    result = subprocess.run(
        ["op", "inject"],
        input=_template(refs, marker),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        return None, result.stderr.strip()
    return _parse_injected(result.stdout, refs, marker), ""


def _looks_like_auth_failure(stderr: str) -> bool:
    """Only an authentication failure is worth a sign-in and retry; a reference
    that does not exist would fail again identically."""
    text = stderr.lower()
    if not text:
        return True
    return any(
        s in text
        for s in ("signed in", "sign in", "signin", "session", "unauthori", "authenticat", "401")
    )


class OnePasswordResolver:
    scheme = "op"

    # -- service account --
    def _resolve_sdk(self, refs: Sequence[str], token: str) -> dict[str, str]:
        try:
            from onepassword.client import Client
        except ImportError as exc:
            raise ResolverUnavailable(
                "OP_SERVICE_ACCOUNT_TOKEN is set but the 1Password SDK is not installed: "
                "pip install 'envref[op]'"
            ) from exc

        async def go() -> dict[str, str]:
            client = await Client.authenticate(
                auth=token,
                integration_name=_INTEGRATION_NAME,
                integration_version=_INTEGRATION_VERSION,
            )
            response = await client.secrets.resolve_all(list(refs))
            values: dict[str, str] = {}
            failures: dict[str, str] = {}
            for ref, individual in response.individual_responses.items():
                if individual.content is not None:
                    values[ref] = individual.content.secret
                else:
                    failures[ref] = str(individual.error)
            if failures:
                raise ResolveError(
                    failures, "Check the service account has read access to that vault."
                )
            return values

        # Synchronous by contract (callers load config at import time), but the
        # SDK is async. Inside a running loop, run it on a worker thread.
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(go())
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: asyncio.run(go())).result()

    # -- CLI --
    def _resolve_cli(self, refs: Sequence[str]) -> dict[str, str]:
        if not shutil.which("op"):
            raise ResolverUnavailable(
                "the `op` CLI is not on PATH and OP_SERVICE_ACCOUNT_TOKEN is not set"
            )
        cached = read_cached_session()
        env = dict(os.environ)
        if cached:
            env[f"OP_SESSION_{cached['account']}"] = cached["token"]

        values, stderr = _inject(refs, env)
        if values is not None:
            if cached:
                touch_cached_session()
            return values
        if not _looks_like_auth_failure(stderr):
            raise ResolveError({ref: stderr or "op inject failed" for ref in refs})

        with _signin_lock():
            # Another process may have signed in while this one waited.
            fresh = read_cached_session()
            if fresh and fresh != cached:
                env[f"OP_SESSION_{fresh['account']}"] = fresh["token"]
                values, stderr = _inject(refs, env)
                if values is not None:
                    return values
            account = resolve_account(fresh or cached)
            token = signin(account) if account else None
            if not (account and token):
                raise ResolveError(
                    {ref: stderr or "not signed in" for ref in refs},
                    "Run `op signin`, or `envref op save-password` to let envref sign in.",
                )
            env[f"OP_SESSION_{account}"] = token
            write_cached_session(account, token)
            values, stderr = _inject(refs, env)
            if values is None:
                raise ResolveError({ref: stderr or "op inject failed" for ref in refs})
            return values

    def resolve(self, refs: Sequence[str]) -> dict[str, str]:
        token = os.environ.get("OP_SERVICE_ACCOUNT_TOKEN", "")
        if token:
            return self._resolve_sdk(refs, token)
        return self._resolve_cli(refs)

    def doctor(self) -> str:
        if os.environ.get("OP_SERVICE_ACCOUNT_TOKEN"):
            try:
                import onepassword  # noqa: F401
            except ImportError:
                return "service account token set, but SDK missing: pip install 'envref[op]'"
            return "service account"
        if not shutil.which("op"):
            return "`op` CLI not on PATH"
        cached = read_cached_session()
        if cached:
            age = int(time.time() - float(cached.get("mtime", 0)))
            return f"op CLI, session cached for {cached['account']} ({age}s old)"
        if session_ttl() <= 0:
            return "op CLI, session cache disabled"
        return "op CLI, no cached session (next load signs in)"
