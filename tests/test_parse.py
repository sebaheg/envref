from envref.parse import parse


def test_mustache_reference_is_explicit():
    (entry,) = parse("KEY={{ op://vault/item/field }}")
    assert entry.ref == "op://vault/item/field"
    assert entry.explicit
    assert entry.scheme == "op"


def test_bare_scheme_is_a_candidate_reference_only():
    (entry,) = parse("URL=https://example.com/x")
    assert entry.ref == "https://example.com/x"
    assert not entry.explicit
    assert entry.value == "https://example.com/x"


def test_literals_quotes_comments_and_export():
    entries = parse(
        "# comment\n\nexport A='single quoted'\nB=\"double\\nquoted\"\nC=plain # trailing\nD=\n"
    )
    assert [(e.name, e.value, e.ref) for e in entries] == [
        ("A", "single quoted", None),
        ("B", "double\nquoted", None),
        ("C", "plain", None),
        ("D", "", None),
    ]


def test_line_numbers_and_garbage_lines():
    entries = parse("A=1\nthis is not an assignment\nB={{op://v/i/f}}")
    assert [(e.name, e.line) for e in entries] == [("A", 1), ("B", 3)]
    assert entries[1].ref == "op://v/i/f"
