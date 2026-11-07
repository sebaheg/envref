import pytest

from envref import ResolveError, UnknownScheme, load, parse, resolve


class Upper:
    scheme = "upper"

    def __init__(self):
        self.calls: list[list[str]] = []

    def resolve(self, refs):
        self.calls.append(list(refs))
        return {ref: ref.partition("://")[2].upper() for ref in refs}


def test_resolve_batches_per_scheme_and_keeps_literals():
    upper = Upper()
    entries = parse("A={{ upper://a }}\nB={{ upper://b }}\nC=plain\nD={{ upper://a }}")
    values = resolve(entries, registry={"upper": upper})
    assert values == {"A": "A", "B": "B", "C": "plain", "D": "A"}
    assert upper.calls == [["upper://a", "upper://b"]], "one call, deduplicated"


def test_explicit_unknown_scheme_raises_but_bare_url_passes():
    entries = parse("URL=https://example.com\nX={{ nope://y }}")
    with pytest.raises(UnknownScheme, match="nope://"):
        resolve(entries, registry={})
    values = resolve(entries[:1], registry={})
    assert values == {"URL": "https://example.com"}


def test_resolver_omitting_a_ref_is_an_error():
    class Partial:
        scheme = "p"

        def resolve(self, refs):
            return {}

    with pytest.raises(ResolveError, match="returned no value"):
        resolve(parse("A={{ p://x }}"), registry={"p": Partial()})


def test_load_first_file_wins_and_does_not_override_environ(tmp_path):
    (tmp_path / "a.env").write_text("A={{ upper://from-a }}\nSHARED=a\n")
    (tmp_path / "b.env").write_text("SHARED=b\nB=from-b\n")
    environ = {"A": "already"}
    values = load(tmp_path / "a.env", tmp_path / "b.env", tmp_path / "missing.env",
                  registry={"upper": Upper()}, environ=environ)
    assert values == {"A": "FROM-A", "SHARED": "a", "B": "from-b"}
    assert environ == {"A": "already", "SHARED": "a", "B": "from-b"}


def test_load_override(tmp_path):
    (tmp_path / ".env").write_text("A=new\n")
    environ = {"A": "old"}
    load(tmp_path / ".env", registry={}, environ=environ, override=True)
    assert environ["A"] == "new"


def test_load_export_false_touches_nothing(tmp_path):
    (tmp_path / ".env").write_text("A=1\n")
    environ: dict[str, str] = {}
    assert load(tmp_path / ".env", registry={}, environ=environ, export=False) == {"A": "1"}
    assert environ == {}
