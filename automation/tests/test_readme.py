from pathlib import Path

import pytest

from takasaki.readme import _badge, build_outputs
from takasaki.store import load_dataset

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
    for anchor in ("english", "korean", "japanese", "database-status", "downloads-and-api"):
        assert f'<a id="{anchor}"></a>' in readme
