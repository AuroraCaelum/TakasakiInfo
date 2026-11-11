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


def test_a_merged_guest_stays_featured(ds):
    # D48: the featured flag belongs to the credit, not to the entity merged away
    ds.artists["g"] = m.Artist(id="g", kind="group", names=_names("G", "G", "G"))
    ds.works["p/song"].recordings[0].performers = [m.Performer(artist="g"), m.Performer(artist="you-variant", featured=True)]
    merge(ds, ["artist:you-variant", "character:p/you"], "character:p/you")
    assert ds.works["p/song"].recordings[0].performers[1] == m.Performer(character="p/you", featured=True)


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


def test_a_partial_import_adds_to_the_uses_a_site_import_listed(tmp_path):
    # D53: the hand entries and schedule files add uses; an import of the whole site lists them afresh
    from takasaki.official import NameReviews

    site = NameReviews(tmp_path, "muse")
    site.item("MUS-titles.yaml", "work", "朝練", {"title": {"ja": "朝練"}}, "release.php#cd23 #1-8")
    site.save()
    hand = NameReviews(tmp_path, "muse", partial=True)
    hand.note_use("MUS-titles.yaml", "work", "朝練", "manual #1")
    hand.save()
    assert NameReviews(tmp_path, "muse", partial=True).doc("MUS-titles.yaml")["items"][0]["used_in"] == [
        "release.php#cd23 #1-8", "manual #1"]
    assert NameReviews(tmp_path, "muse").doc("MUS-titles.yaml")["items"][0]["used_in"] == []


def test_kana_approve_writes_only_the_readings(ds, tmp_path):
    # D58: a kana file sets names.kana / title.kana and their evidence, nothing else
    ds.persons["hata"] = m.Person(id="hata", names=_names("畑 亜貴", "Aki Hata", "하타 아키"),
                                  family_name=_names("畑", "Hata", "하타"), given_name=_names("亜貴", "Aki", "아키"),
                                  evidence={"names.ja": m.Evidence(status=m.Status.official, source="https://a")})
    ds.characters["p/emma"] = m.Character(id="p/emma", project="p", names=_names("エマ・ヴェルデ", "Emma Verde", "엠마 베르데"),
                                          family_name=_names("ヴェルデ", "Verde", "베르데"),
                                          given_name=_names("エマ", "Emma", "엠마"))
    song = ds.works["p/song"]
    song.recordings.append(m.Recording(id="off-vocal", kind="off_vocal", title=_names("曲 (Off Vocal)", "Kyoku (Off Vocal)", "곡 (Off Vocal)")))
    (tmp_path / "KANA-persons.yaml").write_text(
        "type: kana\ndecision: approve\nitems:\n"
        "  - {ref: 'person:hata', family_kana: はた, given_kana: あき, status: established, source: 'https://w', note: 위키백과}\n"
        "  - {ref: 'character:p/emma', kana: エマ・ヴェルデ, status: official, source: 'https://o'}\n",
        encoding="utf-8")
    (tmp_path / "KANA-songs.yaml").write_text(
        "type: kana\ndecision: approve\nitems:\n  - {ref: 'work:p/song', kana: きょく}\n  - {ref: 'artist:you-variant', kana: わたなべ よう}\n",
        encoding="utf-8")
    (tmp_path / "KANA-versions.yaml").write_text(
        "type: kana\ndecision: approve\nitems:\n  - {ref: 'recording:p/song#off-vocal', suffix_kana: ' (オフボーカル)'}\n",
        encoding="utf-8")
    apply_reviews(ds, tmp_path)
    hata = ds.persons["hata"]
    assert (hata.names.kana, hata.family_name.kana, hata.given_name.kana) == ("はた あき", "はた", "あき")
    assert hata.evidence["names.kana"].status == m.Status.established and "names.ja" in hata.evidence
    emma = ds.characters["p/emma"]
    assert emma.names.kana == "エマ・ヴェルデ" and emma.family_name.kana is None
    assert song.title.kana == "きょく" and song.evidence["title.kana"].status == m.Status.derived
    assert song.recordings[1].title.kana == "きょく (オフボーカル)"
    assert ds.artists["you-variant"].names.kana == "わたなべ よう" and "names.kana" in ds.artists["you-variant"].evidence


def test_kana_errors(ds, tmp_path):
    (tmp_path / "KANA-versions.yaml").write_text(
        "type: kana\ndecision: approve\nitems:\n  - {ref: 'recording:p/song#original', suffix_kana: ' (x)'}\n",
        encoding="utf-8")
    with pytest.raises(ReviewError, match="no title of its own"):
        apply_reviews(ds, tmp_path)
    (tmp_path / "KANA-versions.yaml").write_text(
        "type: kana\ndecision: approve\nitems:\n  - {ref: 'person:cv', family_kana: さいとう}\n", encoding="utf-8")
    with pytest.raises(ReviewError, match="go together"):
        apply_reviews(ds, tmp_path)


def test_kana_pending_items_are_not_applied(ds, tmp_path):
    (tmp_path / "KANA-songs-check.yaml").write_text(
        "type: kana\ndecision: approve\nitems:\n  - {ref: 'work:p/song', kana: きょく, pending: 읽기 확인}\n", encoding="utf-8")
    with pytest.raises(ReviewError, match="still pending"):
        apply_reviews(ds, tmp_path)
    assert ds.works["p/song"].title.kana is None


def test_pen_name_merge_keeps_the_printed_name(ds, tmp_path):
    # D58: 木村 有希 is a pen name of 園田 健太郎; the credit still prints 木村 有希
    ds.persons["sonoda"] = m.Person(id="sonoda", names=_names("園田 健太郎", "Kentaro Sonoda", "소노다 켄타로"))
    ds.persons["kimura"] = m.Person(id="kimura", names=m.Names(ja="木村 有希", kana="きむら ゆうき", rom="Yuki Kimura", ko="키무라 유키"))
    ds.works["p/song"].credits.composer = [m.Credit(person="kimura")]
    (tmp_path / "pen.yaml").write_text(
        "type: merge\nitems:\n  - {ref: 'person:sonoda'}\n  - {ref: 'person:kimura'}\ndecision: 'pen-name:person:sonoda'\n",
        encoding="utf-8")
    apply_reviews(ds, tmp_path)
    assert "kimura" not in ds.persons
    c = ds.works["p/song"].credits.composer[0]
    assert (c.person, c.credited_name) == ("sonoda", "木村 有希")
    alias = ds.persons["sonoda"].aliases[0]
    assert alias.kind == "pen_name" and alias.names.kana == "きむら ゆうき"
    assert render_credits(ds, [c]) == ["木村 有希", "Yuki Kimura", "키무라 유키"]
    m.Person.model_validate(ds.persons["sonoda"].model_dump(by_alias=True))
