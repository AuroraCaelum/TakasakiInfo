"""Checks against the real ``data/`` tree: YAML round-trip, golden legacy build (E8), validation."""

import pytest

from takasaki.build_legacy import build_legacy
from takasaki.store import dump_model, load_dataset, repo_root
from takasaki.validate import validate

ROOT = repo_root()
DATA = ROOT / "data"
pytestmark = pytest.mark.skipif(not (DATA / "meta.yaml").exists(), reason="data/ not migrated yet")


@pytest.fixture(scope="module")
def ds():
    return load_dataset(DATA)


def test_yaml_round_trip(ds):
    from takasaki.store import LAYOUT, entity_path

    mismatched = []
    for kind, ent in ds.iter_all():
        path = entity_path(DATA, kind, ent)
        if path.read_text(encoding="utf-8") != dump_model(ent):
            mismatched.append(str(path.relative_to(ROOT)))
    assert mismatched == []
    assert set(LAYOUT)  # every entity type is covered by iter_all


def test_legacy_files_match_build(ds):
    from takasaki.readme import build_outputs

    files = build_outputs(ds)
    stale = [rel for rel, blob in files.items() if (ROOT / rel).read_bytes() != blob]
    assert stale == [], "run `takasaki build` and commit the result"


def test_no_validation_errors(ds):
    errors = [str(f) for f in validate(ds, ROOT / "automation" / "review") if f.level == "error"]
    assert errors == []


def test_same_song_on_several_albums_shares_one_recording(ds):
    # §4.2 / D1: the single and Aqours CHRONICLE list the same recording as separate tracks
    refs = [
        (rel.id, t.recording)
        for rel in ds.releases.values()
        for d in rel.discs
        for t in d.tracks
        if t.recording == "aqours/kimi-no-kokoro-wa-kagayaiteru-kai#original"
    ]
    assert len({r for r, _ in refs}) >= 2


def test_main_url_fallback_is_same_recording_only(ds):
    # D2: TVA2 BD Vol.1 "One More Sunshine Story" must not borrow the Album Version URL
    files = build_legacy(ds)
    text = files["albums/Aqours/Aqours.csv"].decode("utf-8-sig")
    row = next(line for line in text.split("\r\n") if line.startswith("TVA2 BD Vol.1,1,"))
    assert ",NA," in row
