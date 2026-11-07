import platform

import pytest

from envref import ResolveError, parse, resolve
from envref.resolvers.env import EnvResolver
from envref.resolvers.file import FileResolver
from envref.resolvers.keychain import KeychainResolver


def test_env_resolver(monkeypatch):
    monkeypatch.setenv("SOURCE", "value")
    assert EnvResolver().resolve(["env://SOURCE"]) == {"env://SOURCE": "value"}
    with pytest.raises(ResolveError, match="MISSING is not set"):
        EnvResolver().resolve(["env://MISSING"])


def test_file_resolver_strips_one_trailing_newline(tmp_path):
    key = tmp_path / "key.pem"
    key.write_text("-----BEGIN-----\nabc\n-----END-----\n")
    assert FileResolver().resolve([f"file://{key}"]) == {f"file://{key}": "-----BEGIN-----\nabc\n-----END-----"}
    with pytest.raises(ResolveError):
        FileResolver().resolve([f"file://{tmp_path}/nope"])


def test_file_resolver_through_the_registry(tmp_path):
    key = tmp_path / "k"
    key.write_text("hunter2")
    values = resolve(parse(f"PW={{{{ file://{key} }}}}"), registry={"file": FileResolver()})
    assert values == {"PW": "hunter2"}


@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS only")
def test_keychain_missing_item_is_a_resolve_error():
    with pytest.raises(ResolveError, match="no such item"):
        KeychainResolver().resolve(["keychain://envref-test-does-not-exist/nobody"])


def test_keychain_doctor_explains_itself():
    status = KeychainResolver().doctor()
    assert status == "ok" if platform.system() == "Darwin" else "only available on macOS" in status
