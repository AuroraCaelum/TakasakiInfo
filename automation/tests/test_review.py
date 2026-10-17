import pytest

from takasaki import model as m
from takasaki.build_legacy import render_credits, render_performers
from takasaki.review import ReviewError, apply_reviews, distinct, merge
from takasaki.store import Dataset


def _names(ja: str, rom: str, ko: str) -> m.Names:
    return m.Names(ja=ja, rom=rom, ko=ko)


@pytest.fixture
def ds() -> Dataset:
    ds = Dataset()
    ds.projects["p"] = m.Project(id="p", names=_names("P", "P", "P"))
    ds.persons["kikuchi"] = m.Person(id="kikuchi", names=_names("菊池博人", "Hiroto Kikuchi", "키쿠치 히로토"))
    ds.persons["kikuchi-2"] = m.Person(id="kikuchi-2", names=_names("菊地博人", "Hiroto Kikuchi", "키쿠치 히로토"))
    ds.persons["cv"] = m.Person(id="cv", names=_names("斉藤朱夏", "Shuka Saito", "사이토 슈카"))
    ds.persons["yu"] = m.Person(id="yu", names=_names("高咲 侑", "Yu Takasaki", "타카사키 유우"))
    ds.characters["p/you"] = m.Character(
        id="p/you", project="p", names=_names("渡辺曜", "You Watanabe", "와타나베 요우"), casting=[m.Casting(person="cv")]
    )
    ds.characters["p/yu"] = m.Character(id="p/yu", project="p", names=_names("高咲侑", "Yu Takasaki", "타카사키 유우"))
    ds.artists["you-variant"] = m.Artist(id="you-variant", kind="unclassified", names=_names("渡辺 曜", "You Watanabe", "와타나베 요우"))
    ds.works["p/song"] = m.Work(
        id="p/song",
        project="p",
        title=_names("曲", "Kyoku", "곡"),
        credits=m.WorkCredits(lyricist=[m.Credit(person="yu")], composer=[m.Credit(person="kikuchi-2")]),
        recordings=[m.Recording(id="original", performers=[m.Performer(artist="you-variant")],
                                arranger=[m.Credit(person="kikuchi")])],
    )
    return ds


def test_merge_person_rewrites_credits_and_keeps_alias(ds):
    merge(ds, ["person:kikuchi", "person:kikuchi-2"], "person:kikuchi")
    assert "kikuchi-2" not in ds.persons
    assert [a.text for a in ds.persons["kikuchi"].aliases] == ["菊地博人"]
    assert render_credits(ds, ds.works["p/song"].credits.composer)[0] == "菊池博人"


def test_merge_artist_variant_into_character(ds):
    # singer "渡辺 曜" (spacing variant) is the character 渡辺曜 (§5.6: decided by a person, not guessed)
    merge(ds, ["artist:you-variant", "character:p/you"], "character:p/you")
    assert "you-variant" not in ds.artists
    rec = ds.works["p/song"].recordings[0]
    assert [p.ref for p in rec.performers] == [("character", "p/you")]
    assert render_performers(ds, rec.performers)[0] == "渡辺曜"


def test_merge_person_into_character_rewrites_credits(ds):
    # D27: a character credited in-story (高咲侑 as lyricist) is a character, not a person
    merge(ds, ["person:yu", "character:p/yu"], "character:p/yu")
    assert "yu" not in ds.persons
    credit = ds.works["p/song"].credits.lyricist[0]
    assert credit.ref == ("character", "p/yu") and credit.person is None
    assert render_credits(ds, [credit]) == ["高咲侑", "Yu Takasaki", "타카사키 유우"]


def test_credit_needs_exactly_one_ref():
    with pytest.raises(ValueError):
        m.Credit()
    with pytest.raises(ValueError):
        m.Credit(person="a", character="p/b")


def test_distinct_and_errors(ds):
    distinct(ds, ["person:kikuchi", "person:kikuchi-2"])
    assert "kikuchi-2" in ds.persons["kikuchi"].distinct_from and "kikuchi" in ds.persons["kikuchi-2"].distinct_from
    with pytest.raises(ReviewError):
        merge(ds, ["person:kikuchi"], "person:kikuchi-2")  # target must be one of the refs
    with pytest.raises(ReviewError):
        merge(ds, ["person:kikuchi", "artist:you-variant"], "artist:you-variant")  # a person is never an artist
    with pytest.raises(ReviewError):
        merge(ds, ["person:cv", "character:p/yu"], "character:p/yu")  # a voice actor cannot become a character


def test_apply_reviews_reads_decisions(ds, tmp_path):
    (tmp_path / "x.yaml").write_text(
        "type: merge\nitems:\n  - {ref: 'person:kikuchi'}\n  - {ref: 'person:kikuchi-2'}\ndecision: 'merge:person:kikuchi'\n",
        encoding="utf-8",
    )
    (tmp_path / "open.yaml").write_text("type: merge\nitems: []\ndecision:\n", encoding="utf-8")
    applied = apply_reviews(ds, tmp_path)
    assert [x.path.name for x in applied] == ["x.yaml"]
    assert "kikuchi-2" not in ds.persons
    assert isinstance(ds.persons["kikuchi"], m.Person)
