import pytest

from scanner.text import canonicalize_url, matches_exclude, normalize_title, titles_match


@pytest.mark.parametrize("raw,expected", [
    ("https://www.Example.com/a/?utm_source=x&id=2&fbclid=y#frag", "https://example.com/a?id=2"),
    ("http://example.com/a/", "https://example.com/a"),
    ("example.com/a", "https://example.com/a"),
    ("https://example.com/?b=2&a=1", "https://example.com/?a=1&b=2"),
    ("  https://example.com/x  ", "https://example.com/x"),
])
def test_canonicalize_url_cases(raw, expected):
    assert canonicalize_url(raw) == expected


def test_canonicalize_url_never_raises_on_junk():
    assert canonicalize_url("") == ""
    assert isinstance(canonicalize_url("not a url at all ::::"), str)
    assert isinstance(canonicalize_url("http://[broken"), str)


def test_normalize_title_strips_outlet_suffix():
    assert normalize_title("Tesla Roadster flies - Reuters") == "tesla roadster flies"
    assert normalize_title("Tesla Roadster flies | The Verge") == "tesla roadster flies"
    assert normalize_title("Why the war - and the peace - matter to five big nations") == \
        "why the war and the peace matter to five big nations"


def test_titles_match():
    assert titles_match("Tesla Roadster takes flight in demo - BBC",
                        "Tesla Roadster takes flight in demo | The Verge")
    assert not titles_match("Tesla Roadster flies", "France elects new prime minister")
    assert not titles_match("", "")


def test_matches_exclude():
    assert matches_exclude("Celebrity gossip roundup", ["gossip"])
    assert not matches_exclude("Gossipy neighbours", ["gossip"])
    assert not matches_exclude("anything", [])
