from pathlib import Path

import pytest

from takasaki import model as m
from takasaki.readme import _badge, build_outputs, v1_schema
from takasaki.store import LAYOUT, load_dataset

ROOT = Path(__file__).resolve().parents[2]


def test_badge_escapes_shields_separators():
    assert _badge("data updated", "2026-10-19", "e4007f") == \
        "https://img.shields.io/badge/data%20updated-2026--10--19-e4007f?style=flat-square"


@pytest.fixture(scope="module")
def readme() -> str:
    ds = load_dataset(ROOT / "data")
    return build_outputs(ds)["README.md"].decode("utf-8")


def test_readme_follows_the_data(readme):
    ds = load_dataset(ROOT / "data")
    assert "{{" not in readme
    for group in ds.layout.integrated_order:  # every group has a status row and a file-name line per language
        assert readme.count(f"→ `{group}`") == 3
    for project in ds.projects.values():  # every notice is in the Disclaimer of its language
        for c in project.copyright:
            assert f"> {c.text}" in readme
    for anchor in ("english", "korean", "japanese", "database-status", "downloads-and-api", "v1-schema"):
        assert f'<a id="{anchor}"></a>' in readme


def test_readme_describes_every_v1_field(readme):
    for sub, cls, _ in LAYOUT.values():  # a block per entity file and a row per field
        assert f"<code>{sub}.json</code>" in readme
        for name, f in cls.model_fields.items():
            assert f"| `{f.alias or name}` |" in readme
    assert "| `catalog` | string | — | Catalog number" in readme
    assert '"smartlink": "https://lnk.to/' in readme  # the release example comes from data/


def test_a_field_without_a_docstring_fails_the_build(monkeypatch):
    monkeypatch.setattr(m.Edition.model_fields["catalog"], "description", None)
    with pytest.raises(ValueError, match=r"Edition\.catalog"):
        v1_schema()
