import datetime as dt

import pytest

from takasaki import hasunosora as hs
from takasaki import importer as imp
from takasaki import model as m
from takasaki.store import Dataset

URL = "https://www.lovelive-anime.jp/hasunosora/music/cd/?p=01_9999"


# --- parser (synthetic pages in the site's layout; raw pages are never committed, D9) ------------


def _page(*, lead: str = "スリーズブーケ 9thシングル", main: str = "Song A", category: str = "CD",
          blocks: list[tuple[str, list[str]]], tail: str = "") -> str:
    spec = "".join(f'<div class="spec--block"><h4>{h}</h4><div class="spec--block__text">{"<br />".join(rows)}</div></div>'
                   for h, rows in blocks)
    return (f'<h3 class="head--title"><span class="head--title__lead">{lead}</span><span class="head--title__main">{main}</span></h3>'
            f'<p class="head--date">2026.12.01</p><p class="head--category"><span>{category}</span></p>'
            f'<div class="detail__content">{spec}{tail}<p>BACK</p></div><footer>OFFICIAL X</footer>')


def test_detail_page():
    html = _page(main="～Star Memories～ Otomune Kozue【初回限定盤】", blocks=[
        ("アーティスト", ["スリーズブーケ", "［日野下花帆(CV.楡井希実)、百生吟子(CV.櫻井陽菜)］", "＆", "DOLLCHESTRA［村野さやか(CV.野中ここな)］"]),
        ("発売日", ["2026年12月1日（火）", "※各種音楽配信サービスでは12月8日(火)配信開始予定です。"]),
        ("価格", ["LACA-39123～4/￥4,950（10%税込）"]),
        ("CD", ["[Disc.1]", "01.Song A", "歌：スリーズブーケ＆DOLLCHESTRA", "作詞：ケリー", "作曲・編曲：本田正樹（Dream Monster）",
                "弦編曲：真部 裕", "※「Fes×LIVE」楽曲", "02．Song A（Off Vocal）", "[Disc.2]", "Song B",
                "歌：乙宗 梢(CV.花宮初奈)", "作詞： ケリー"]),
        ("Blu-ray", ["・Archive"]),
    ], tail='<div class="tokutenbox"><a class="link" href="https://lnk.to/LACA-39123d">●各種音楽配信サービスはこちら</a></div>')
    p = hs.parse_page(html, URL)
    assert (p.title, p.edition, p.release_date, p.catalog, p.media) == (
        "～Star Memories～ Otomune Kozue", "初回限定盤", dt.date(2026, 12, 1), "LACA-39123~4", "2CD+BD")
    assert p.note == "各種音楽配信サービスでは12月8日(火)配信開始予定です。" and p.smartlink == "https://lnk.to/LACA-39123d"
    assert p.performers.artists == ["スリーズブーケ", "DOLLCHESTRA"]
    assert [(t.disc, t.no, t.title) for t in p.tracks] == [(1, 1, "Song A"), (1, 2, "Song A（Off Vocal）"), (2, 1, "Song B")]
    a = p.tracks[0]
    assert a.performers.artists == ["スリーズブーケ", "DOLLCHESTRA"]
    assert set(a.credits) == {"lyricist", "composer", "arranger"}  # 弦編曲 is dropped
    assert [(c.name, c.affiliation) for c in a.credits["arranger"]] == [("本田正樹", "Dream Monster")]
    assert p.tracks[2].performers.members == [("乙宗 梢", "花宮初奈")]  # a disc's first track printed without its number
    with pytest.raises(imp.ParseError):  # an unknown line inside a track is not guessed
        hs.parse_page(_page(blocks=[("発売日", ["2026年12月1日"]), ("CD", ["01.Song A", "キミとアイドル"])]), URL)


def test_credit_names_and_misprints():
    c = imp.parse_credit_line("作曲：Fi’Ne, Yuqui-lah")  # two people joined by a comma
    assert [x.name for x in c["composer"]] == ["Fi’Ne", "Yuqui-lah"]
    c = imp.parse_credit_line("作曲：Hiroki Sagawa (Relic Lyric, inc.) 、武田城以")  # the comma of an affiliation stays
    assert [(x.name, x.affiliation) for x in c["composer"]] == [("Hiroki Sagawa", "Relic Lyric, inc."), ("武田城以", None)]
    html = _page(blocks=[("アーティスト", ["Edel Note"]), ("発売日", ["2025年3月26日"]),
                         ("CD", ["01.Retrofuture", "04.Retrofutur（Off Vocal）"])])
    p = hs.parse_page(html, "https://www.lovelive-anime.jp/hasunosora/music/36/")
    assert [t.title for t in p.tracks] == ["Retrofuture", "Retrofuture（Off Vocal）"]  # TRACK_FIXES


def test_singers():
    assert hs.parse_singers("Ruri&To").artist == "Ruri&To"  # a half-width & belongs to the name
    assert hs.parse_singers("スリーズブーケ＆DOLLCHESTRA").artists == ["スリーズブーケ", "DOLLCHESTRA"]
    assert hs.parse_singers("村野さやか（CV. 野中ここな）").members == [("村野さやか", "野中ここな")]


@pytest.mark.parametrize("kw,reason", [
    ({"blocks": [("アーティスト", ["V.A."]), ("発売日", ["2026年1月14日"]), ("CD", ["01.X", "キミとアイドル"])]}, "V.A."),
    ({"blocks": [("アーティスト", ["音楽：藤澤慶昌／蓮ノ空女学院スクールアイドルクラブ"]), ("発売日", ["2026年7月22日"]), ("CD", ["01. 録画開始！"])]},
     "soundtrack"),
    ({"category": "Blu-ray", "blocks": [("発売日", ["2026年1月1日"])]}, "video"),
    ({"main": "タイトル未定", "blocks": [("発売日", ["2026年12月30日"]), ("仕様", ["新規楽曲4曲＋Off Vocalを収録予定"])]}, "announced"),
])
def test_pages_left_out(kw, reason):
    assert reason in hs.parse_page(_page(**kw), URL).skip


def test_editions_are_one_release():
    def page(url, edition, media):
        p = hs.PageObs(url, "102nd Graduation Album", "X", edition, "CD", dt.date(2025, 6, 4), imp.Performers("A", None),
                       None, media, [imp.TrackObs(1, "Song A")])
        return p
    rels, notes = hs.group_pages([page(URL + "1", "通常盤", "2CD"), page(URL + "0", "初回限定盤", "2CD+BD")])
    assert len(rels) == 1 and not notes
    r = rels[0]
    assert [e.label for e in r.editions] == ["初回限定盤", "通常盤"] and r.url == URL + "0" and r.pages == [URL + "0", URL + "1"]
    assert r.type == "album"


def test_version_labels():
    assert imp.version_labels("104期 Ver.") == ("104th-ver", "104期 Ver.", "104th Ver.", "104기 Ver.")
    assert imp.version_labels("104期Ver.")[1] == "104期 Ver."  # one notation however the page spaces it
    assert imp.version_labels("104期NEW Ver.") == ("104th-new-ver", "104期NEW Ver.", "104th NEW Ver.", "104기 NEW Ver.")
    assert imp.version_labels("102期 Ver.")[2] == "102nd Ver." and imp.version_labels("SAKURA Ver.")[0] == "sakura-ver"
    assert imp.version_labels("麻布麻衣 Solo Ver.") is None


# --- importer -----------------------------------------------------------------------


@pytest.fixture
def ds() -> Dataset:
    ds = Dataset()
    ds.meta = m.Meta(schema_version="1", db_last_update="2026-01-01T00:00:00Z")
    ds.layout = m.LegacyLayout(integrated_order=["Hasunosora"], albums={}, members={}, concerts={})
    ds.projects["hasunosora"] = m.Project(id="hasunosora", names=m.Names(ja="蓮ノ空"))
    ds.persons["kelly"] = m.Person(id="kelly", names=m.Names(ja="ケリー", rom="Kelly", ko="케리"))
    ds.artists["cb"] = m.Artist(id="cb", kind="unit", projects=["hasunosora"], names=m.Names(ja="スリーズブーケ", rom="Cerise Bouquet", ko="스리즈 부케"))
    ds.artists["hasu"] = m.Artist(id="hasu", kind="group", projects=["hasunosora"], names=m.Names(ja=hs.GROUP, rom="Hasunosora", ko="하스노소라"))
    ds.characters["hasunosora/kozue-otomune"] = m.Character(id="hasunosora/kozue-otomune", project="hasunosora",
                                                            names=m.Names(ja="乙宗 梢", rom="Kozue Otomune", ko="오토무네 코즈에"))
    legacy = m.Evidence(status=m.Status.legacy, source="migration:legacy")
    ds.works["hasunosora/song-a"] = m.Work(id="hasunosora/song-a", project="hasunosora", title=m.Names(ja="Song A", rom="Song A", ko="Song A"),
                                           credits=m.WorkCredits(lyricist=[m.Credit(person="kelly")]),
                                           recordings=[m.Recording(id="original", performers=[m.Performer(artist="cb")],
                                                                   arranger=[m.Credit(person="kelly")]),
                                                       m.Recording(id="off-vocal", kind="off_vocal", version="Off Vocal",
                                                                   title=m.Names(ja="Song A (Off Vocal)", kana="そんぐ (オフボーカル)"),
                                                                   instrumental_of="original")])
    ds.releases["hasunosora/2023-song-a"] = m.Release(
        id="hasunosora/2023-song-a", title=m.Names(ja="Song A"), projects=["hasunosora"], release_date=dt.date(2023, 3, 1),
        discs=[m.Disc(tracks=[m.Track(no=1, recording="hasunosora/song-a#original", note="tie-in")])],
        legacy=m.ReleaseLegacy(category="Hasunosora", albums=[m.LegacyAlbum(title="Song A")]), evidence={"tracks": legacy})
    return ds


def _obs(url, title, date, tracks, perf=None, **kw):
    return imp.ReleaseObs(url, "スリーズブーケ 1stシングル", title, date, perf or imp.Performers("スリーズブーケ", None),
                          [imp.EditionObs(None, kw.pop("catalog", None), "CD")], tracks, {}, None, kw.pop("type", "single"))


def _credits():
    return {"lyricist": [imp.CreditName("ケリー")], "arranger": [imp.CreditName("ケリー")]}


def test_migrated_release_gets_the_page_facts_and_keeps_its_tracks(ds, tmp_path):
    site = imp.Site([], [_obs(URL, "Song A", dt.date(2023, 3, 1), [imp.TrackObs(1, "Song A", credits=_credits())], catalog="LACM-1")],
                    "https://x/member/")
    for _ in range(2):  # a second run, now that the release has its official link, still only compares
        rep = hs.import_site(ds, site, tmp_path, dt.date(2026, 10, 19))
        assert not rep.conflicts and not rep.created
        rel = ds.releases["hasunosora/2023-song-a"]
        assert rel.links == {"official": URL} and rel.type == "single" and rel.label == "Lantis"
        assert [e.catalog for e in rel.editions] == ["LACM-1"] and rel.artist_credit == [m.Performer(artist="cb")]
        assert rel.discs[0].tracks[0].note == "tie-in"  # never rewritten
        assert rel.evidence["tracks"].status == m.Status.official and rel.evidence["tracks"].note == imp.CHECKED_LEGACY
    assert ds.artists["cb"].lineups == []  # Hasunosora keeps its dated lineups (D33)


def test_versions_solos_and_their_instrumentals(ds, tmp_path):
    kozue = imp.Performers(None, None, [("乙宗 梢", "花宮初奈")])
    site = imp.Site([], [
        _obs(URL + "1", "Song A", dt.date(2024, 4, 1), [
            imp.TrackObs(1, "Song A (104期 Ver.)", credits=_credits()),
            imp.TrackObs(2, "Song A（104期 Ver.）（Off Vocal）")]),
        _obs(URL + "2", "Song A", dt.date(2025, 6, 4), [imp.TrackObs(1, "Song A", kozue, credits=_credits()),
                                                         imp.TrackObs(1, "Song A（Off Vocal）", disc=2)], kozue, type="album"),
    ], "https://x/member/")
    rep = hs.import_site(ds, site, tmp_path, dt.date(2026, 10, 19))
    assert not rep.conflicts
    recs = {r.id: r for r in ds.works["hasunosora/song-a"].recordings}
    assert recs["104th-ver"].title == m.Names(ja="Song A (104期 Ver.)", rom="Song A (104th Ver.)", ko="Song A (104기 Ver.)")
    off = recs["104th-ver-off-vocal"]
    assert off.instrumental_of == "104th-ver" and off.title.ja == "Song A (104期 Ver.) (Off Vocal)"
    assert recs["kozue-otomune-solo"].performers == [m.Performer(character="hasunosora/kozue-otomune")]
    assert recs["original"].performers == [m.Performer(artist="cb")]  # the group recording is untouched
    assert recs["off-vocal"].title.kana == "そんぐ (オフボーカル)"  # a stored title keeps its reading
    album = next(r for r in ds.releases.values() if r.type == "album")
    assert [(d.disc, [t.recording.split("#")[1] for t in d.tracks]) for d in album.discs] == [
        (1, ["kozue-otomune-solo"]), (2, ["off-vocal"])]
