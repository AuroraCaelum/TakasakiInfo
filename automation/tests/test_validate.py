import pytest

from takasaki import model as m
from takasaki.build_legacy import render_credits, render_performers
from takasaki.store import Dataset
from takasaki.validate import validate


def _names(ja: str, rom: str, ko: str) -> m.Names:
    return m.Names(ja=ja, rom=rom, ko=ko)


def _ds(character: m.Character | None = None, recordings: list[m.Recording] | None = None) -> Dataset:
    ds = Dataset()
    ds.projects["p"] = m.Project(id="p", names=_names("P", "P", "P"))
    ds.persons["a"] = m.Person(id="a", names=_names("畑亜貴", "Aki Hata", "하타 아키"))
    if character:
        ds.characters[character.id] = character
    ds.works["p/w"] = m.Work(id="p/w", project="p", title=_names("曲", "Kyoku", "곡"), recordings=recordings or [])
    return ds


def _rules(ds: Dataset) -> list[str]:
    return [f.rule for f in validate(ds)]


def _you(**kw) -> m.Character:
    return m.Character(id="p/you", project="p", names=_names("渡辺 曜", "You Watanabe", "와타나베 요우"), **kw)


def test_name_parts_match_the_full_name():
    ok = _you(family_name=_names("渡辺", "Watanabe", "와타나베"), given_name=_names("曜", "You", "요우"))
    assert "E12" not in _rules(_ds(ok))
    # order is free per language (rom is given-family, ja/ko family-given); ・ is ignored
    emma = m.Character(id="p/emma", project="p", names=_names("エマ・ヴェルデ", "Emma Verde", "엠마 베르데"),
                       family_name=_names("ヴェルデ", "Verde", "베르데"), given_name=_names("エマ", "Emma", "엠마"))
    assert "E12" not in _rules(_ds(emma))
    wrong = _you(family_name=_names("渡辺", "Watanabe", "와타나베"), given_name=_names("陽", "You", "요우"))
    assert "E12" in _rules(_ds(wrong))
    half = _you(family_name=_names("渡辺", "Watanabe", "와타나베"))
    assert "E12" in _rules(_ds(half))


def test_japanese_spacing_rule():
    # D28: a space only when both parts are kanji; readings always take a space
    parts = {"family_name": _names("渡辺", "Watanabe", "와타나베"), "given_name": _names("曜", "You", "요우")}
    unspaced = m.Character(id="p/you", project="p", names=_names("渡辺曜", "You Watanabe", "와타나베 요우"), **parts)
    assert "E12" in _rules(_ds(unspaced))
    kasumi = dict(id="p/kasumi", project="p", family_name=_names("中須", "Nakasu", "나카스"),
                  given_name=_names("かすみ", "Kasumi", "카스미"))
    assert "E12" not in _rules(_ds(m.Character(names=_names("中須かすみ", "Kasumi Nakasu", "나카스 카스미"), **kasumi)))
    assert "E12" in _rules(_ds(m.Character(names=_names("中須 かすみ", "Kasumi Nakasu", "나카스 카스미"), **kasumi)))
    reading = _you(**parts)
    reading.names.kana, reading.family_name.kana, reading.given_name.kana = "わたなべよう", "わたなべ", "よう"
    assert "E12" in _rules(_ds(reading))
    reading.names.kana = "わたなべ よう"
    assert "E12" not in _rules(_ds(reading))
    # all-kana names follow the official notation, spaced or not
    for ja in ("サイトウリョースケ", "サイトウ リョースケ"):
        ds = _ds()
        ds.persons["rs"] = m.Person(id="rs", names=_names(ja, "Ryosuke Saito", "사이토 료스케"),
                                    family_name=_names("サイトウ", "Saito", "사이토"), given_name=_names("リョースケ", "Ryosuke", "료스케"))
        assert not [f for f in validate(ds) if f.rule == "E12" and "rs" in f.where]


def test_japanese_name_without_split_warns():
    ds = _ds()
    assert "W15" in _rules(ds)  # 畑亜貴 has no family/given split
    ds.persons["a"].family_name, ds.persons["a"].given_name = _names("畑", "Hata", "하타"), _names("亜貴", "Aki", "아키")
    ds.persons["a"].names.ja = "畑 亜貴"
    assert "W15" not in _rules(ds) and "E12" not in _rules(ds)


def test_person_in_a_role_renders_as_cast_credit():
    # D29: musical cast sing as persons in a role
    ds = _ds(m.Character(id="p/rurika", project="p", names=_names("椿ルリカ", "Rurika Tsubaki", "츠바키 루리카")))
    ds.persons["mh"] = m.Person(id="mh", names=_names("堀内まり菜", "Marina Horiuchi", "호리우치 마리나"))
    perf = m.Performer(person="mh", role="p/rurika")
    assert render_performers(ds, [perf, m.Performer(person="a")]) == [
        "堀内まり菜（椿ルリカ役）;畑亜貴", "Marina Horiuchi(as Rurika Tsubaki);Aki Hata", "호리우치 마리나(츠바키 루리카 역);하타 아키"
    ]
    rec = m.Recording(id="original", performers=[m.Performer(person="mh", role="p/none")])
    assert "E2" in _rules(_ds(recordings=[rec]))


def test_performer_refs():
    with pytest.raises(ValueError):
        m.Performer(character="p/x", role="p/y")  # role is only for a person
    with pytest.raises(ValueError):
        m.Performer(person="a", artist="b")


def test_empty_credits_warn_only_for_vocal():
    # D25: "not applicable" is an empty list, so drama and instrumental recordings stay quiet
    drama = m.Recording(id="main", kind="drama")
    inst = m.Recording(id="instrumental", kind="instrumental", arranger=[m.Credit(person="a")])
    assert "W14" not in _rules(_ds(recordings=[drama, inst]))
    vocal = m.Recording(id="original", performers=[m.Performer(character="p/you")], arranger=[m.Credit(person="a")])
    assert "W14" in _rules(_ds(_you(), recordings=[vocal]))  # work has no lyricist / composer


def test_empty_credits_render_as_empty_cells():
    ds = _ds()
    assert render_credits(ds, []) == ["", "", ""]
    assert render_performers(ds, []) == ["", "", ""]


def test_credit_may_name_a_character():
    rec = m.Recording(id="original", arranger=[m.Credit(character="p/you")])
    assert "E2" not in _rules(_ds(_you(), recordings=[rec]))
    assert "E2" in _rules(_ds(recordings=[rec]))  # unknown character


def test_affiliation_by_language():
    # D31: an affiliation printed in every language column needs per-language names when it is Japanese script
    ds = _ds()
    ds.persons["mito"] = m.Person(id="mito", names=_names("ミト", "Mito", "미토"))
    band = m.Credit(person="mito", affiliation=m.Names(ja="クラムボン", rom="clammbon", ko="clammbon"))
    assert render_credits(ds, [band]) == ["ミト(クラムボン)", "Mito(clammbon)", "미토(clammbon)"]
    assert render_credits(ds, [m.Credit(person="a", affiliation="FirstCall")])[1] == "Aki Hata(FirstCall)"
    rec = m.Recording(id="original", arranger=[m.Credit(person="mito", affiliation="クラムボン")])
    ds.works["p/w"].recordings = [rec]
    assert "E6" in _rules(ds)


def test_no_padding_in_names():
    ds = _ds()
    ds.works["p/w"].title.rom = "Kyoku "
    assert "E13" in _rules(ds)


def test_note_is_built_from_parts():
    # M3: Disc.N / Drama Part / Link is from are derived; the album and the track keep only their own text
    from takasaki.build_legacy import render_note

    la = m.LegacyAlbum(title="CHRONICLE", note=None, flatten_discs=True)
    drama, vocal = m.Recording(id="main", kind="drama"), m.Recording(id="original")
    assert render_note(la, 2, vocal, m.Track(recording="w#original", note="（第1話挿入歌）"), None) == "Disc.2, （第1話挿入歌）"
    single = m.LegacyAlbum(title="S", note="CYaRon! 1st Single")
    assert render_note(single, 1, drama, m.Track(recording="w#main"), None) == "Drama Part, CYaRon! 1st Single"
    bd = m.LegacyAlbum(title="BD", note="TVA1 BD Vol.1")
    assert render_note(bd, 1, vocal, m.Track(recording="w#original"), "CHRONICLE") == "TVA1 BD Vol.1, Link is from the [CHRONICLE]"


def test_notes_do_not_repeat_derived_parts():
    ds = _ds(recordings=[m.Recording(id="original")])
    ds.releases["p/r"] = m.Release(id="p/r", title=_names("R", "R", "R"), projects=["p"],
                                   discs=[m.Disc(tracks=[m.Track(no=1, recording="p/w#original", note="Drama Part")])])
    assert "E14" in _rules(ds)


def test_release_titles_come_from_song_titles():
    # D39: rom and ko of "A／B" come from the song titles (any slash, width-insensitive); all-Latin titles are their own
    from takasaki.build_legacy import release_title

    ds = _ds(recordings=[m.Recording(id="original")])
    ds.works["p/x"] = m.Work(id="p/x", project="p", title=_names("Go!!リスタート", "Go!! Restart", "Go!! 리스타트"),
                             recordings=[m.Recording(id="original")])
    tracks = [m.Track(no=1, recording="p/w#original"), m.Track(no=2, recording="p/x#original")]

    def rel(ja: str, **names: str) -> m.Release:
        ds.releases["p/r"] = m.Release(id="p/r", title=m.Names(ja=ja, **names), projects=["p"], discs=[m.Disc(tracks=tracks)])
        return ds.releases["p/r"]

    assert release_title(ds, rel("曲／Go！！リスタート")) == (_names("曲／Go！！リスタート", "Kyoku / Go!! Restart", "곡 / Go!! 리스타트"), ["rom", "ko"])
    assert release_title(ds, rel("TVA1 BD Vol.1")) == (_names("TVA1 BD Vol.1", "TVA1 BD Vol.1", "TVA1 BD Vol.1"), ["rom", "ko"])
    assert release_title(ds, rel("曲", rom="Official")) == (_names("曲", "Official", "곡"), ["ko"])  # a stored value wins
    assert "W17" not in _rules(ds)
    rel("リエラのうた")
    assert [f.message for f in validate(ds) if f.rule == "W17"] == ["title 'リエラのうた' has no rom/ko"]


def test_draft_values_are_not_output():
    # E3 (§4.4): a draft on anything the legacy files print blocks the merge; announced releases are not printed (§7.4)
    from takasaki.build_legacy import build_legacy

    ds = _ds(recordings=[m.Recording(id="original", performers=[m.Performer(person="a")])])
    ds.works["p/w"].evidence["title.ko"] = m.Evidence(status=m.Status.draft, note="번역안")
    ds.releases["p/r"] = m.Release(id="p/r", title=_names("R", "R", "R"), projects=["p"],
                                   discs=[m.Disc(tracks=[m.Track(no=1, recording="p/w#original")])],
                                   legacy=m.ReleaseLegacy(category="P", albums=[m.LegacyAlbum(title="R")]))
    ds.meta = m.Meta(schema_version="1", db_last_update="x")
    ds.layout = m.LegacyLayout(integrated_order=["P"], albums={"P": m.LayoutAlbumsFile(entries=[m.LayoutAlbumEntry(release="p/r")])},
                               members={}, concerts={})
    assert "E3" in _rules(ds)
    ds.releases["p/r"].status = "announced"
    assert "E3" not in _rules(ds)
    assert build_legacy(ds)["albums/P/P.csv"].decode("utf-8-sig").count("\r\n") == 0  # header only


def test_w16_flags_official_fields_sourced_elsewhere():
    from takasaki.validate import official_first

    ds = Dataset()
    wiki = m.Evidence(status=m.Status.established, source="https://ja.wikipedia.org/wiki/X")
    namu = m.Evidence(status=m.Status.established, source="https://namu.wiki/w/X")
    off = m.Evidence(status=m.Status.official, source="https://www.lovelive-anime.jp/hasunosora/member/07/")
    ds.persons["a"] = m.Person(id="a", names=m.Names(ja="甲", rom="Ko", ko="고"),
                               evidence={"names.ja": wiki, "names.ko": namu, "names.rom": wiki})
    ds.artists["u"] = m.Artist(id="u", kind="unit", names=m.Names(ja="U", rom="U", ko="U"),
                               evidence={"lineups": wiki, "names": off})
    w16 = sorted(f.where + " " + f.message.split()[0] for f in validate(ds) if f.rule == "W16")
    assert w16 == ["artist:u lineups", "person:a names.ja"]  # ko and a person's own rom are not official-first
    assert not official_first("work", "same_recording") and official_first("release", "tracks")
    ds.artists["u"].evidence["lineups"] = wiki.model_copy(update={"note": "공식 멤버 페이지가 갱신되지 않아 위키가 공식보다 최신"})
    assert [f.where for f in validate(ds) if f.rule == "W16"] == ["person:a"]


def test_w15_skips_activity_names_with_a_recorded_reason():
    ds = Dataset()
    ds.persons["pen"] = m.Person(id="pen", names=m.Names(ja="吸血亭 賛美", rom="Kyuketsutei Zabi", ko="큐우케츠테이 자비"))
    assert [f.rule for f in validate(ds)] == ["W15"]
    ds.persons["pen"].evidence["name_parts"] = m.Evidence(status=m.Status.derived, note="활동명이라 성·이름 없음")
    assert [f.rule for f in validate(ds)] == []
