from pathlib import Path

import pytest

from takasaki import model as m
from takasaki.readme import READMES, _badge, build_outputs, db_schema
from takasaki.store import LAYOUT, load_dataset

ROOT = Path(__file__).resolve().parents[2]


def test_badge_escapes_shields_separators():
    assert _badge("data updated", "2026-10-19", "e4007f") == \
        "https://img.shields.io/badge/data%20updated-2026--10--19-e4007f?style=flat-square"


@pytest.fixture(scope="module")
def readmes() -> dict[str, str]:
    ds = load_dataset(ROOT / "data")
    files = build_outputs(ds)
    return {name: files[name].decode("utf-8") for name in READMES}


@pytest.fixture(scope="module")
def readme(readmes) -> str:
    return readmes["README.md"]


def test_readme_follows_the_data(readmes):
    ds = load_dataset(ROOT / "data")
    for name, text in readmes.items():
        assert "{{" not in text, name
        for group in ds.layout.integrated_order:  # every group has a file-name line in each language
            assert text.count(f"→ `{group}`") == 1, (name, group)
        for other in READMES:  # each page links the other two languages
            assert other == name or f"]({other})" in text, (name, other)
    every = "".join(readmes.values())
    for project in ds.projects.values():  # every notice is in the Disclaimer of its language
        for c in project.copyright:
            assert f"> {c.text}" in every
    for anchor in ("database-status", "downloads-and-api", "db-schema"):
        assert f'<a id="{anchor}"></a>' in readmes["README.md"]


def test_the_language_pages_link_into_the_english_readme(readmes):
    for name in ("README.ko.md", "README.ja.md"):
        assert "README.md#db-schema" in readmes[name] and "README.md#json-structure" in readmes[name]
        assert "Database status" not in readmes[name]


def test_readme_describes_every_field(readme):
    for sub, cls, _ in LAYOUT.values():  # a block per entity file and a row per field
        assert f"<code>{sub}.json</code>" in readme
        for name, f in cls.model_fields.items():
            assert f"| `{f.alias or name}` |" in readme
    assert "| `catalog` | string | — | Catalog number" in readme
    assert '"smartlink": "https://lnk.to/' in readme  # the release example comes from data/


def test_a_field_without_a_docstring_fails_the_build(monkeypatch):
    monkeypatch.setattr(m.Edition.model_fields["catalog"], "description", None)
    with pytest.raises(ValueError, match=r"Edition\.catalog"):
        db_schema()
