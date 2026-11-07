import json
import os

import pytest

from envref import ResolveError, ResolverUnavailable
from envref.resolvers import op
from envref.resolvers.op import OnePasswordResolver

REFS = ["op://vault/item/field", "op://vault/item/pem"]


def test_cli_inject_without_a_session_when_op_needs_none(fake_op):
    values = OnePasswordResolver().resolve(REFS)
    assert values["op://vault/item/field"] == "s3cret"
    assert values["op://vault/item/pem"] == "-----BEGIN KEY-----\nabc\n-----END KEY-----\n"
    assert fake_op.read_text().splitlines() == ["inject"]


def test_cli_signs_in_with_keychain_password_and_caches_the_session(fake_op, no_touch_id, monkeypatch):
    monkeypatch.setenv("FAKE_OP_SESSION_REQUIRED", "1")
    monkeypatch.setattr("envref.resolvers.keychain.read_generic_password", lambda s, a: "correct horse")

    values = OnePasswordResolver().resolve(REFS[:1])

    assert values == {"op://vault/item/field": "s3cret"}
    calls = fake_op.read_text().splitlines()
    assert calls[0] == "inject", "first attempt is without a session"
    assert "signin --raw --account test" in calls
    assert calls[-1] == "inject"
    cached = json.loads(op.session_cache_path().read_text())
    assert cached["account"] == "test" and cached["token"] == "SESSION-TOKEN-1"
    assert oct(op.session_cache_path().stat().st_mode & 0o777) == "0o600"


def test_cached_session_is_reused_and_refreshed(fake_op, monkeypatch):
    monkeypatch.setenv("FAKE_OP_SESSION_REQUIRED", "1")
    op.write_cached_session("test", "SESSION-TOKEN-1")
    before = json.loads(op.session_cache_path().read_text())["mtime"]

    OnePasswordResolver().resolve(REFS[:1])

    assert fake_op.read_text().splitlines() == ["inject"], "no sign-in needed"
    assert json.loads(op.session_cache_path().read_text())["mtime"] >= before


def test_expired_cache_is_ignored(monkeypatch):
    op.write_cached_session("test", "T")
    monkeypatch.setenv("ENVREF_OP_SESSION_TTL", "0")
    assert op.read_cached_session() is None


def test_wrong_password_raises_with_a_hint(fake_op, no_touch_id, monkeypatch):
    monkeypatch.setenv("FAKE_OP_SESSION_REQUIRED", "1")
    monkeypatch.setattr("envref.resolvers.keychain.read_generic_password", lambda s, a: "wrong")
    with pytest.raises(ResolveError, match="save-password"):
        OnePasswordResolver().resolve(REFS[:1])


def test_unresolvable_reference_is_not_retried_as_auth(fake_op):
    with pytest.raises(ResolveError, match="could not resolve"):
        OnePasswordResolver().resolve(["op://vault/missing/x"])
    assert fake_op.read_text().splitlines() == ["inject"]


def test_missing_op_binary_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(ResolverUnavailable, match="`op` CLI"):
        OnePasswordResolver().resolve(REFS)


def test_service_account_without_sdk_is_unavailable(monkeypatch):
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "ops_x")
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("onepassword"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ResolverUnavailable, match=r"envref\[op\]"):
        OnePasswordResolver().resolve(REFS)


def test_template_round_trip_survives_multiline_values():
    marker = "@envrefM@"
    refs = ["op://a/b/c", "op://d/e/f"]
    template = op._template(refs, marker)
    output = template.replace("{{ op://a/b/c }}", "line1\nline2\n").replace("{{ op://d/e/f }}", "x")
    assert op._parse_injected(output, refs, marker) == {"op://a/b/c": "line1\nline2\n", "op://d/e/f": "x"}


def test_keychain_names_are_configurable(fake_op, monkeypatch):
    assert op.keychain_service() == "envref-op"
    assert op.keychain_account("test") == "me@example.com"
    monkeypatch.setenv("ENVREF_OP_KEYCHAIN_SERVICE", "my-service")
    monkeypatch.setenv("ENVREF_OP_KEYCHAIN_ACCOUNT", "me")
    assert (op.keychain_service(), op.keychain_account("test")) == ("my-service", "me")


def test_service_account_path_batches_through_the_sdk(monkeypatch):
    """Drive the SDK branch with a stub client: one resolve_all call, failures named."""
    import sys
    import types

    calls: dict[str, object] = {}

    class Content:
        def __init__(self, secret):
            self.secret = secret

    class Individual:
        def __init__(self, secret=None, error=None):
            self.content = Content(secret) if secret is not None else None
            self.error = error

    class Response:
        def __init__(self, individual):
            self.individual_responses = individual

    class Secrets:
        async def resolve_all(self, refs):
            calls["refs"] = list(refs)
            return Response({
                "op://v/a/f": Individual("alpha"),
                "op://v/b/f": Individual(error="no such item"),
            })

    class Client:
        @classmethod
        async def authenticate(cls, *, auth, integration_name, integration_version):
            calls["auth"] = auth
            client = cls()
            client.secrets = Secrets()
            return client

    stub = types.ModuleType("onepassword.client")
    stub.Client = Client
    monkeypatch.setitem(sys.modules, "onepassword", types.ModuleType("onepassword"))
    monkeypatch.setitem(sys.modules, "onepassword.client", stub)
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "ops_token")

    with pytest.raises(ResolveError) as exc:
        OnePasswordResolver().resolve(["op://v/a/f", "op://v/b/f"])
    assert exc.value.failures == {"op://v/b/f": "no such item"}
    assert "read access to that vault" in str(exc.value)
    assert calls == {"auth": "ops_token", "refs": ["op://v/a/f", "op://v/b/f"]}

    class HappySecrets(Secrets):
        async def resolve_all(self, refs):
            return Response({ref: Individual(ref.upper()) for ref in refs})

    Client.authenticate = classmethod(
        lambda cls, **kw: _coro(_with_secrets(cls(), HappySecrets()))
    )
    assert OnePasswordResolver().resolve(["op://v/a/f"]) == {"op://v/a/f": "OP://V/A/F"}
    assert not (op.session_cache_path()).exists(), "the SDK path never touches the CLI cache"


def _with_secrets(client, secrets):
    client.secrets = secrets
    return client


async def _coro(value):
    return value
