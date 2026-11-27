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
    for name, text in readmes.items():
        for anchor in ("database-status", "downloads-and-api", "db-schema"):
            assert f'<a id="{anchor}"></a>' in text, (name, anchor)


def test_every_language_has_the_whole_readme(readmes):
    """The Korean and Japanese pages carry everything the English one does, in their language."""
    en = readmes["README.md"]
    for name in ("README.ko.md", "README.ja.md"):
        text = readmes[name]
        assert "README.md#" not in text, name  # nothing is left to the English page
        for block in ("/api/v1/openapi.json", "/api/v1/random", "Petals of History", "<code>tracks.json</code>",
                      "<code>recordings.json</code>", '"smartlink": "https://lnk.to/', "```jsonc"):
            assert block in text, (name, block)
        assert text.count("| `") >= en.count("| `") - 2, name  # every row of the tables
        for sub, cls, _ in LAYOUT.values():
            for field, f in cls.model_fields.items():
                assert f"| `{f.alias or field}` |" in text, (name, field)
    assert "| 프로젝트 | 최신 발매 |" in readmes["README.ko.md"] and "| 필드 | 타입 | 기본값 | 설명 |" in readmes["README.ko.md"]
    assert "| プロジェクト | 最新リリース |" in readmes["README.ja.md"]


def test_mood_rules_in_every_language():
    from takasaki.audio import MOOD_RULES
    from takasaki.readme import MOOD_RULES_TEXT, TEXT

    for rules in MOOD_RULES_TEXT.values():
        assert set(rules) == set(MOOD_RULES)
    assert all(set(w) == set(TEXT["en"]) for w in TEXT.values())


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
