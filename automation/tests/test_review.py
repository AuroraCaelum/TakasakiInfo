import pytest

from takasaki import model as m
from takasaki.build_v1 import build_v1
from takasaki.review import ReviewError, apply_reviews, distinct, merge
from takasaki.store import load_dataset, repo_root

DATA = repo_root() / "data"
pytestmark = pytest.mark.skipif(not (DATA / "meta.yaml").exists(), reason="data/ not migrated yet")


@pytest.fixture
def ds():
    return load_dataset(DATA)


def _persons_named(ds, ja):
    return [p.id for p in ds.persons.values() if p.names.ja == ja]


def test_merge_person_rewrites_credits_and_keeps_alias(ds):
    a, b = _persons_named(ds, "菊池博人"), _persons_named(ds, "菊地博人")
    assert len(a) == 1 and len(b) == 1
    merge(ds, [f"person:{a[0]}", f"person:{b[0]}"], f"person:{b[0]}")
    assert a[0] not in ds.persons
    assert [x.text for x in ds.persons[b[0]].aliases] == ["菊池博人"]
    csv = b"".join(v for k, v in build_v1(ds).items() if k.endswith(".csv")).decode("utf-8-sig")
    assert "菊池博人" not in csv and "菊地博人" in csv


def test_merge_artist_variant_into_character(ds):
    # singer "渡辺 曜" (spacing variant) is the character 渡辺曜 (§5.6: decided by a person, not guessed)
    variant = next(x.id for x in ds.artists.values() if x.names.ja == "渡辺 曜")
    char = next(c.id for c in ds.characters.values() if c.names.ja == "渡辺曜")
    merge(ds, [f"artist:{variant}", f"character:{char}"], f"character:{char}")
    assert variant not in ds.artists
    performers = {p.ref for w in ds.works.values() for r in w.recordings for p in r.performers}
    assert ("artist", variant) not in performers and ("character", char) in performers


def test_distinct_and_errors(ds):
    a, b = _persons_named(ds, "菊池博人")[0], _persons_named(ds, "菊地博人")[0]
    distinct(ds, [f"person:{a}", f"person:{b}"])
    assert b in ds.persons[a].distinct_from and a in ds.persons[b].distinct_from
    with pytest.raises(ReviewError):
        merge(ds, [f"person:{a}"], f"person:{b}")  # target must be one of the refs


def test_apply_reviews_reads_decisions(ds, tmp_path):
    a, b = _persons_named(ds, "菊池博人")[0], _persons_named(ds, "菊地博人")[0]
    (tmp_path / "x.yaml").write_text(
        f"type: merge\nitems:\n  - {{ref: 'person:{a}'}}\n  - {{ref: 'person:{b}'}}\ndecision: 'merge:person:{b}'\n",
        encoding="utf-8",
    )
    (tmp_path / "open.yaml").write_text("type: merge\nitems: []\ndecision:\n", encoding="utf-8")
    applied = apply_reviews(ds, tmp_path)
    assert [x.path.name for x in applied] == ["x.yaml"]
    assert a not in ds.persons
    assert isinstance(ds.persons[b], m.Person)
