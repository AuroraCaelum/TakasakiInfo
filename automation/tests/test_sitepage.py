"""The music pages of the older project sites and the check of migrated releases (D41)."""

import datetime as dt

import pytest

from takasaki import importer as imp
from takasaki import model as m
from takasaki.nijigasaki import parse_page as niji_page
from takasaki.aqours import parse_page as aqours_page
from takasaki.musical import parse_page as musical_page
from takasaki.store import Dataset

NIJI = """
<div class="box" id="cd04">
<div class="title"><p><span>虹ヶ咲学園スクールアイドル同好会 1stアルバム</span>
 Love U my friends <span>【上原歩夢盤】</span></p></div>
<dl class="spec">
<dt>【アーティスト】</dt><dd>虹ヶ咲学園スクールアイドル同好会</dd>
<dt>【発売日】</dt><dd>2019年10月2日(水)</dd>
<dt>【価格】</dt><dd>LACA-15800 / ￥3,000(tax out)</dd>
<dt>【収録内容】</dt><dd><p class="media">[Disc1]</p><ul class="track">
<li>01.TOKIMEKI Runners<dl><dt>歌：</dt><dd>上原歩夢(CV.大西亜玖璃)</dd>
<dt>作詞：</dt><dd>畑 亜貴</dd><dt>作曲・編曲：</dt><dd>矢鴇つかさ(Arte Refact)</dd>
<dt>弦編曲：</dt><dd>真部 裕</dd></dl></li>
<li>02.かすみのトキメキ<ruby>祝祭<rt>カーニバル</rt></ruby>！</li>
<li>03.TOKIMEKI Runners(Off Vocal)</li></ul></dd></dl>
<div class="tokutenbox"><p class="tokutentitle">初回生産分限定封入特典</p><ul><li>01.メンバーカード</li></ul></div>
</div>
"""

AQOURS = """
<a id="cd13"></a><div class="box"><div class="llbox"><p><span>Aqours 3rd シングル<br></span>HAPPY PARTY TRAIN</p></div>
<div class="text">【タイトル】<br>HAPPY PARTY TRAIN<br><br>【発売日】<br>2017年4月5日（水）<br><br>
【アーティスト】<br>Aqours<br>高海千歌(CV.伊波杏樹) , 桜内梨子(CV.逢田梨香子)<br><br>
【価格】<br>【Ｂ Ｄ付】LACM-14590／￥3,000(tax out)<br><br>【収録内容】<br>■収録曲<br>
Disc.1<br>
01. HAPPY PARTY TRAIN<br><span class="uta">作詞：畑 亜貴／作曲：渡辺拓也　編曲：EFFY</span><br>
02. Step! ZERO to ONE<br><span class="uta">作詞：畑 亜貴 作編曲：高田 暁</span><br>
03. HAPPY PARTY TRAIN<span class="uta">(Off Vocal)</span><br>
Disc.2 ：スペシャルCD<br>
01. 君のこころは輝いてるかい？（Aqours 1st Single）<br><span class="uta">歌：高海千歌(CV.伊波杏樹) , 桜内梨子(CV.逢田梨香子)<br>
　　渡辺 曜(CV.斉藤朱夏)</span><br>
【初回生産特典】<br>01. カード<br></div></div>
"""

MUSICAL = """
<div class="box" id="cd02"><div class="title"><p><span class="subname">CDアルバム</span>『スクールアイドルミュージカル』</p></div>
<dl class="spec"><dt>【発売日】</dt><dd>2023年5月10日(水)</dd><dt>【収録内容】</dt><dd>第一幕<ul class="track">
<li>01.オーバーチュア(instrumental)<dl><dt>作曲・編曲：</dt><dd>小島良太</dd></dl></li>
<li>02.伝統の系譜<dl><dt>歌：</dt><dd><span>堀内まり菜（椿 ルリカ役）、</span><span>蒼乃夕妃（椿 マドカ役）</span><br>
大原万由子、<span>金子 楓</span></dd></dl></li></ul>第二幕</dd></dl></div>
"""


def test_a_nijigasaki_block():
    [b] = niji_page(NIJI, "https://x/cd.php")
    assert (b.url, b.title, b.edition, b.release_date) == ("https://x/cd.php#cd04", "Love U my friends", "上原歩夢盤",
                                                         dt.date(2019, 10, 2))
    assert [t.title for t in b.tracks] == ["TOKIMEKI Runners", "かすみのトキメキ祝祭！", "TOKIMEKI Runners(Off Vocal)"]
    first = b.tracks[0]
    assert first.performers.members == [("上原歩夢", "大西亜玖璃")]
    assert [c.name for c in first.credits["lyricist"]] == ["畑 亜貴"]
    assert [(c.name, c.affiliation) for c in first.credits["arranger"]] == [("矢鴇つかさ", "Arte Refact")]
    assert [c.name for c in first.credits["strings_arranger"]] == ["真部 裕"]  # a role of its own (D42)


def test_an_aqours_block_with_inline_credits():
    [b] = aqours_page(AQOURS, "https://x/cd.php")
    assert (b.title, b.release_date) == ("HAPPY PARTY TRAIN", dt.date(2017, 4, 5))
    assert [(t.disc, t.no, t.title) for t in b.tracks] == [
        (1, 1, "HAPPY PARTY TRAIN"), (1, 2, "Step! ZERO to ONE"), (1, 3, "HAPPY PARTY TRAIN(Off Vocal)"),
        (2, 1, "君のこころは輝いてるかい？")]  # the annotation of a compilation is not part of the title
    assert [c.name for c in b.tracks[0].credits["composer"]] == ["渡辺拓也"]  # "作詞：…／作曲：…"
    assert [c.name for c in b.tracks[1].credits["arranger"]] == ["高田 暁"]  # 作編曲
    assert [n for n, _ in b.tracks[3].performers.members] == ["高海千歌", "桜内梨子", "渡辺 曜"]


def test_a_musical_cast():
    [b] = musical_page(MUSICAL, "https://x/music.php")
    assert b.title == "スクールアイドルミュージカル"
    overture, keifu = b.tracks
    assert overture.title == "オーバーチュア(instrumental)" and overture.performers is None
    assert keifu.performers.cast and keifu.performers.members == [
        ("椿 ルリカ", "堀内まり菜"), ("椿 マドカ", "蒼乃夕妃"), ("", "大原万由子"), ("", "金子 楓")]


def test_credit_lines():
    assert {k: [c.name for c in v] for k, v in imp.parse_credit_line("作曲：酒井拓也（Arte Refact）編曲：脇 眞富").items()} == {
        "composer": ["酒井拓也"], "arranger": ["脇 眞富"]}
    assert [c.name for c in imp.parse_credit_line("作詞・作曲：R・O・N")["lyricist"]] == ["R・O・N"]
    assert set(imp.parse_credit_line("作曲／編曲：EFFY")) == {"composer", "arranger"}
    okuma = imp.parse_credit_line("編曲：大熊淳生（Arte Refact）、光増ハジメ (FirstCall)")["arranger"]
    assert [(c.name, c.affiliation, c.fullwidth) for c in okuma] == [
        ("大熊淳生", "Arte Refact", True), ("光増ハジメ", "FirstCall", False)]  # the brackets as printed (D42)
    both = imp.parse_credit_line("編曲：EFFY　弦管編曲：真部 裕")  # strings and brass by one arranger (D42)
    assert {k: [c.name for c in v] for k, v in both.items()} == {
        "arranger": ["EFFY"], "strings_arranger": ["真部 裕"], "brass_arranger": ["真部 裕"]}


# --- the check of a migrated release ------------------------------------------------

URL = "https://www.lovelive-anime.jp/nijigasaki/cd.php#cd04"
SPEC = imp.Spec(project="p", group_name="グループ", legacy_group="P", review_prefix="P", lineups_from_site=False,
                check_only=True)
MIGRATED = m.Evidence(status=m.Status.legacy, source=m.MIGRATED)


@pytest.fixture
def ds() -> Dataset:
    ds = Dataset()
    ds.meta = m.Meta(schema_version="1", db_last_update="2026-01-01T00:00:00Z")
    ds.layout = m.LegacyLayout(integrated_order=["P"], albums={}, members={}, concerts={})
    for pid, ja in (("hata", "畑 亜貴"), ("effy", "EFFY"), ("manabe", "真部 裕"), ("ito", "伊波杏樹")):
        ds.persons[pid] = m.Person(id=pid, names=m.Names(ja=ja, rom=ja, ko=ja), evidence={"names": MIGRATED})
    ds.artists["g"] = m.Artist(id="g", kind="group", projects=["p"], names=m.Names(ja="グループ"))
    ds.characters["p/chika"] = m.Character(id="p/chika", project="p", names=m.Names(ja="高海千歌"),
                                           casting=[m.Casting(person="ito")])
    credits = m.WorkCredits(lyricist=[m.Credit(person="hata")], composer=[m.Credit(person="effy")])
    ds.works["p/a"] = m.Work(id="p/a", project="p", title=m.Names(ja="Song A"), credits=credits, evidence={"credits": MIGRATED},
                             recordings=[
                                 m.Recording(id="original", performers=[m.Performer(artist="g")],
                                             arranger=[m.Credit(person="effy"), m.Credit(person="manabe")],
                                             evidence={"credits": MIGRATED}),
                                 m.Recording(id="off-vocal", kind="off_vocal", version="Off Vocal", instrumental_of="original",
                                             performers=[m.Performer(artist="g")],
                                             arranger=[m.Credit(person="effy"), m.Credit(person="manabe")],
                                             evidence={"credits": MIGRATED}),
                                 m.Recording(id="chika-takami-solo-ver", version="高海千歌 Solo Ver.",
                                             performers=[m.Performer(character="p/chika")],
                                             arranger=[m.Credit(person="effy"), m.Credit(person="manabe")],
                                             evidence={"credits": MIGRATED})])
    tracks = ["p/a#original", "p/a#off-vocal", "p/a#chika-takami-solo-ver"]
    ds.releases["p/2020-a"] = m.Release(
        id="p/2020-a", title=m.Names(ja="Song A"), projects=["p"], release_date=dt.date(2020, 1, 1),
        discs=[m.Disc(tracks=[m.Track(no=i, recording=r) for i, r in enumerate(tracks, 1)])],
        legacy=m.ReleaseLegacy(category="P", albums=[m.LegacyAlbum(title="Song A")]), evidence={"tracks": MIGRATED})
    return ds


def _obs(tracks, perf=None):
    return imp.ReleaseObs(URL, "", "Song A", dt.date(2020, 1, 1), perf or imp.Performers("グループ", None),
                          [imp.EditionObs(None, "LACM-1", "CD")], tracks, {})


def test_the_check_cites_the_page_for_what_it_prints(ds, tmp_path):
    credits = {"lyricist": [imp.CreditName("畑亜貴")], "composer": [imp.CreditName("EFFY")],
               "arranger": [imp.CreditName("EFFY")], "strings_arranger": [imp.CreditName("真部 裕")]}
    site = imp.Site([], [_obs([imp.TrackObs(1, "Song A", credits=credits), imp.TrackObs(2, "Song A (Off Vocal)"),
                               imp.TrackObs(3, "Song A（高海千歌 Solo Ver.）")])], "https://x/member/")
    rep = imp.import_site(ds, site, tmp_path, dt.date(2026, 10, 19), SPEC)
    assert not rep.conflicts and not rep.created
    work = ds.works["p/a"]
    recs = {r.id: r.evidence["credits"] for r in work.recordings}
    assert work.evidence["credits"].source == URL and work.evidence["credits"].status == m.Status.official
    assert recs["original"].source == URL and recs["original"].note is None
    # the legacy files mixed the 弦編曲 into the arranger list: the check splits it into its roles (D42),
    # and the Off Vocal and the solo version follow their vocal
    for r in work.recordings:
        assert ([c.person for c in r.arranger], [c.person for c in r.strings_arranger]) == (["effy"], ["manabe"]), r.id
    assert recs["off-vocal"].source == URL  # its arranger is its vocal's
    # the solo version prints neither credits nor a "歌：" line: its singer is in the version, under the credits of X
    assert recs["chika-takami-solo-ver"].status == m.Status.official and recs["chika-takami-solo-ver"].source == URL
    assert ds.releases["p/2020-a"].evidence["tracks"].note == imp.CHECKED_TRACKS
    # the names the page printed: ja is cited, rom and ko wait for their own sources; a Latin name is itself
    hata = ds.persons["hata"].evidence
    assert hata["names.ja"].source == URL and hata["names.ja"].note == "공식 표기 '畑亜貴' (띄어쓰기는 D28)"
    assert hata["names.rom"] == MIGRATED and "names" not in hata
    assert ds.persons["effy"].evidence["names.ko"].status == m.Status.derived
    assert not (tmp_path / "P-artists.yaml").exists()  # a check never creates review items


def test_a_solo_album_without_credits_borrows_the_arrangement(ds, tmp_path):
    solo = "https://www.lovelive-anime.jp/nijigasaki/cd.php#cd40"
    ds.releases["p/2020-solo"] = m.Release(
        id="p/2020-solo", title=m.Names(ja="Solo"), projects=["p"], release_date=dt.date(2020, 8, 1),
        discs=[m.Disc(tracks=[m.Track(no=1, recording="p/a#chika-takami-solo-ver")])],
        legacy=m.ReleaseLegacy(category="P", albums=[m.LegacyAlbum(title="Solo")]), evidence={"tracks": MIGRATED})
    credits = {"lyricist": [imp.CreditName("畑 亜貴")], "composer": [imp.CreditName("EFFY")],
               "arranger": [imp.CreditName("EFFY")], "strings_arranger": [imp.CreditName("真部 裕")]}
    site = imp.Site([], [
        _obs([imp.TrackObs(1, "Song A", credits=credits), imp.TrackObs(2, "Song A (Off Vocal)")]),
        imp.ReleaseObs(solo, "", "Solo", dt.date(2020, 8, 1), imp.Performers(None, None, [("高海千歌", "伊波杏樹")]),
                       [], [imp.TrackObs(1, "Song A")], {})], "https://x/member/")
    imp.import_site(ds, site, tmp_path, dt.date(2026, 10, 19), SPEC)
    ev = next(r for r in ds.works["p/a"].recordings if r.id == "chika-takami-solo-ver").evidence["credits"]
    assert ev.status == m.Status.derived and ev.source == solo and URL in (ev.note or "")
    assert ds.releases["p/2020-solo"].evidence["tracks"].source == solo


def test_the_check_reports_what_differs_and_cites_nothing_for_it(ds, tmp_path):
    credits = {"lyricist": [imp.CreditName("畑 亜貴")], "composer": [imp.CreditName("EFFY")], "arranger": [imp.CreditName("EFFY")]}
    site = imp.Site([], [_obs([imp.TrackObs(1, "Song A", credits=credits), imp.TrackObs(2, "Song A (Off Vocal)"),
                               imp.TrackObs(3, "Song A（高海千歌 Solo Ver.）"), imp.TrackObs(4, "Drama")])], "https://x/member/")
    rep = imp.import_site(ds, site, tmp_path, dt.date(2026, 10, 19), SPEC)
    assert any("tracks on cd.php#cd04 differ" in c for c in rep.conflicts)  # a fourth track the data lacks
    assert any("arranger on cd.php#cd04 differs" in c for c in rep.conflicts)  # no string arranger printed
    assert ds.releases["p/2020-a"].evidence["tracks"] == MIGRATED
    assert ds.works["p/a"].evidence["credits"].source == URL  # the tracks at their place still settle the song's credits
    assert ds.works["p/a"].recordings[0].evidence["credits"] == MIGRATED


# --- the import of the releases beyond the migrated ones (Phase 3) ---------------------

IMPORT = imp.Spec(project="p", group_name="グループ", legacy_group="P", review_prefix="P", lineups_from_site=False)


def _new(url, title, tracks, *, editions=None, pages=None, perf=None, rtype=None):
    return imp.ReleaseObs(url, "", title, dt.date(2024, 4, 24), perf or imp.Performers("グループ", None),
                          editions or [imp.EditionObs(None, "LACM-2", "CD")], tracks, {}, type=rtype,
                          edition_pages=pages or [])


def _cr():
    return {"lyricist": [imp.CreditName("畑 亜貴")], "composer": [imp.CreditName("EFFY")], "arranger": [imp.CreditName("EFFY")]}


def test_editions_with_their_own_coupling_song_get_a_disc_each(ds, tmp_path):
    a = [imp.TrackObs(1, "Song A (Off Vocal)"), imp.TrackObs(2, "Song B", credits=_cr())]
    b = [imp.TrackObs(1, "Song A (Off Vocal)"), imp.TrackObs(2, "Song C", credits=_cr())]
    url = "https://x/music/cd41.php"
    obs = _new(url, "Song A", a, editions=[imp.EditionObs("第2話盤", "LACM-3"), imp.EditionObs("通常盤", "LACM-4")],
               pages=[imp.EditionPage("第2話盤", url, a), imp.EditionPage("通常盤", url + "?2", b)])
    rep = imp.import_site(ds, imp.Site([], [obs], "https://x/member/"), tmp_path, dt.date(2026, 10, 19), IMPORT)
    assert not rep.conflicts and not rep.pending
    rel = next(r for r in ds.releases.values() if r.links.get("official") == url)
    assert [(d.editions, [t.recording for t in d.tracks]) for d in rel.discs] == [
        (["e1"], ["p/a#off-vocal", "p/song-b#original"]), (["e2"], ["p/a#off-vocal", "p/song-c#original"])]
    assert [(a.title, a.edition) for a in rel.legacy.albums] == [("Song A [第2話盤]", "e1"), ("Song A [通常盤]", "e2")]


def test_a_drama_cd_and_a_version_between_wave_dashes(ds, tmp_path):
    drama = _new("https://x/cd.php#cd57", "ドラマCD Fantasia", [imp.TrackObs(1, "Radio Drama 1"), imp.TrackObs(2, "Radio Drama 2")],
                 rtype="drama_cd")
    ds.works["p/a"].title = m.Names(ja="Song A", rom="Song A", ko="Song A")
    wave = _new("https://x/cd.php#cd33", "Song A", [imp.TrackObs(1, "Song A ～2023Ver.～", credits=_cr())])
    site = imp.Site([], [wave, drama], "https://x/member/")
    (tmp_path / "P-titles.yaml").write_text(  # the drama CD's title, named in review
        "type: new-names\nproject: p\ndecision: ''\nitems:\n  - {kind: release, printed: ドラマCD Fantasia, "
        "title: {ja: ドラマCD Fantasia, rom: Drama CD Fantasia, ko: 드라마 CD 판타지아}}\n", encoding="utf-8")
    rep = imp.import_site(ds, site, tmp_path, dt.date(2026, 10, 19), IMPORT)
    assert not rep.conflicts and not rep.pending, rep
    work = ds.works["p/radio-drama-1"]
    assert work.kind == "drama" and [(r.id, r.kind, r.performers) for r in work.recordings] == [
        ("main", "drama", [m.Performer(artist="g")])]
    rel = ds.releases["p/2024-drama-cd-fantasia"]
    assert rel.type == "drama_cd"
    ver = next(r for r in ds.works["p/a"].recordings if r.id == "2023ver")
    assert ver.title == m.Names(ja="Song A ～2023Ver.～", rom="Song A ~2023Ver.~", ko="Song A ~2023Ver.~") and ver.version == "2023Ver."


def test_a_song_of_another_project_and_a_sourced_release(ds, tmp_path):
    # LIVE with a smile! is stored under one project and sung by an artist of several
    ds.artists["all"] = m.Artist(id="all", kind="collab", projects=["q", "p"], names=m.Names(ja="みんな"))
    ds.works["q/smile"] = m.Work(id="q/smile", project="q", title=m.Names(ja="Smile"),
                                 credits=m.WorkCredits(lyricist=[m.Credit(person="hata")], composer=[m.Credit(person="effy", affiliation="FirstCall")]),
                                 recordings=[m.Recording(id="original", performers=[m.Performer(artist="all")])],
                                 evidence={"credits": m.Evidence(status=m.Status.official, source="https://x/q")})
    solo = imp.Performers(None, None, [("高海千歌", "伊波杏樹")])
    obs = _new("https://x/cd.php#cd90", "Solo Album", [imp.TrackObs(1, "Smile", credits={
        "lyricist": [imp.CreditName("畑 亜貴")], "composer": [imp.CreditName("EFFY")], "arranger": [imp.CreditName("EFFY")]})], perf=solo)
    (tmp_path / "P-titles.yaml").write_text(
        "type: new-names\nproject: p\ndecision: ''\nitems:\n  - {kind: release, printed: Solo Album, "
        "title: {ja: Solo Album, rom: Solo Album, ko: Solo Album}}\n", encoding="utf-8")
    # a migrated release whose tracks were sourced without an official link (D36): compared, never rewritten
    ds.releases["p/2020-a"].evidence["tracks"] = m.Evidence(status=m.Status.official, source=URL, note="대조 일치")
    remix = _obs([imp.TrackObs(1, "Song A REMIX")])
    rep = imp.import_site(ds, imp.Site([], [obs, remix], "https://x/member/"), tmp_path, dt.date(2026, 10, 19), IMPORT)
    assert not rep.conflicts, rep.conflicts  # the composer's affiliation as the cover album prints it is no conflict
    assert "q/smile" in ds.works and not any(w.startswith("p/smile") for w in ds.works)
    assert [r.id for r in ds.works["q/smile"].recordings] == ["original", "chika-solo"]
    rel = ds.releases["p/2020-a"]
    assert [t.recording for t in rel.discs[0].tracks][0] == "p/a#original" and rel.type == "single" and "official" not in rel.links


MUSICAL_2024 = """
<div class="box" id="cd03"><div class="title"><p><span class="subname">CDアルバム</span>後夜祭アルバム！</p></div>
<dl class="spec"><dt>【アーティスト】</dt><dd>スクールアイドルミュージカル</dd><dt>【発売日】</dt><dd>2024年8月21日(水)</dd>
<dt>【収録内容】</dt><dd>01.今すぐはじめよ！<br>堀内まり菜（椿 ルリカ役）、西田有愛（来栖トア役）、<br>金子 楓、森本めい<br>
12．夢はドコカラ<br>椿滝桜女学院高等学校スクールアイドル部<br>(堀内まり菜（椿 ルリカ役）、<br>金子楓)<br>ご注文はこちらから</dd></dl></div>
"""


def test_a_cast_printed_without_a_singers_label():
    [b] = musical_page(MUSICAL_2024, "https://x/music.php")
    first, last = b.tracks
    assert first.performers.cast and first.performers.members == [
        ("椿 ルリカ", "堀内まり菜"), ("来栖トア", "西田有愛"), ("", "金子 楓"), ("", "森本めい")]
    assert last.performers.artist == "椿滝桜女学院高等学校スクールアイドル部"  # the club, its cast in brackets
    assert last.performers.members == [("椿 ルリカ", "堀内まり菜"), ("", "金子楓")]  # and not the order link


def test_skip_reasons_and_types():
    from takasaki.sitepage import Block, release_type, skip_reason

    def block(header, title, artist, tracks=("A",)):
        return Block("u", header, title, None, dt.date(2024, 1, 1), artist, [], [imp.TrackObs(i, t) for i, t in enumerate(tracks, 1)])

    assert "soundtrack" in skip_reason(block([], "OST", ["音楽：藤澤慶昌"]))
    assert "tribute" in skip_reason(block([], "Tribute", ["V.A."]))
    assert "tracklist" in skip_reason(block([], "Songbirds", ["Liella!"], ("Songbirds", "???", "???(Off Vocal)")))
    assert skip_reason(block([], "Jellyfish", ["5yncri5e!"])) is None
    assert release_type(block(["Aqours ベストアルバム"], "Aqours CHRONICLE", [])) == "compilation"
    assert release_type(block(["主題歌ミニアルバム"], "どこにいても君は君", [])) == "mini_album"
    assert release_type(block(["ラブライブ！虹ヶ咲学園 ～放課後放送室～"], "ドラマCD 夢幻グランディオーソ", [])) == "drama_cd"
    assert release_type(block(["CatChu! 1stシングル"], "ディストーション", [])) is None  # the catalog number decides


def test_the_video_disc_ends_the_track_list():
    page = AQOURS.replace("【初回生産特典】<br>01. カード<br>", "＜Blu-ray＞　※初回限定盤のみ収録<br>01. PV<br>")
    [b] = aqours_page(page, "https://x/cd.php")
    assert [t.title for t in b.tracks][-1] == "君のこころは輝いてるかい？"


def test_a_drama_part_and_discs_numbered_on(ds, tmp_path):
    page = AQOURS.replace("03. HAPPY PARTY TRAIN<span class=\"uta\">(Off Vocal)</span><br>",
                          "03. HAPPY PARTY TRAIN<span class=\"uta\">(Off Vocal)</span><br>■ドラマパート<br>04. 浦の星の夏<br>")
    [b] = aqours_page(page, "https://x/cd.php")
    assert [(t.no, t.drama) for t in b.tracks] == [(1, False), (2, False), (3, False), (4, True), (1, False)]
    # a solo album numbered on across its discs: stored from 1 on each disc, listed on in the legacy files (D42)
    solo = imp.Performers(None, None, [("高海千歌", "伊波杏樹")])
    obs = _new("https://x/cd.php#cd57", "Solo", [imp.TrackObs(1, "Song A"), imp.TrackObs(2, "Song A", disc=2)], perf=solo)
    (tmp_path / "P-titles.yaml").write_text(
        "type: new-names\nproject: p\ndecision: ''\nitems:\n  - {kind: release, printed: Solo, title: {ja: Solo, rom: Solo, ko: Solo}}\n",
        encoding="utf-8")
    ds.works["p/a"].evidence["credits"] = ds.works["p/a"].recordings[0].evidence["credits"] = m.Evidence(
        status=m.Status.official, source=URL)
    rep = imp.import_site(ds, imp.Site([], [obs], "https://x/member/"), tmp_path, dt.date(2026, 10, 19), IMPORT)
    assert not rep.conflicts
    rel = ds.releases["p/2024-solo"]
    assert [(d.disc, [t.no for t in d.tracks]) for d in rel.discs] == [(1, [1]), (2, [1])]
    assert rel.legacy.albums[0].flatten_discs
    # the cover printed without credits is arranged as the song's credited recording (D41), as derived
    cover = next(r for r in ds.works["p/a"].recordings if r.id == "chika-solo")
    assert [c.person for c in cover.arranger] == ["effy", "manabe"] and cover.evidence["credits"].status == m.Status.derived


def test_an_artist_version_and_an_original_waiting_for_its_single(ds, tmp_path):
    ds.artists["g"].names = m.Names(ja="グループ", rom="Group", ko="그룹")
    ds.works["p/a"].title = m.Names(ja="Song A", rom="Song A", ko="Song A")
    ver = _new("https://x/cd.php#cd59", "Song A", [imp.TrackObs(1, "Song A（グループ Ver.）", credits=_cr()),
                                                   imp.TrackObs(2, "Song A（グループ Ver.）(Off Vocal)")])
    # a single credited to an artist still waiting for its name, then a solo cover of its song
    single = _new("https://x/cd.php#cd72", "New Song", [imp.TrackObs(1, "New Song", credits=_cr())],
                  perf=imp.Performers("Somebody feat. 誰か", None))
    solo = _new("https://x/cd.php#cd90", "New Song", [imp.TrackObs(1, "New Song")], perf=imp.Performers(None, None, [("高海千歌", "伊波杏樹")]))
    solo.release_date = dt.date(2025, 1, 1)
    rep = imp.import_site(ds, imp.Site([], [ver, single, solo], "https://x/member/"), tmp_path, dt.date(2026, 10, 19), IMPORT)
    recs = {r.id: r for r in ds.works["p/a"].recordings}
    assert recs["group-ver"].title == m.Names(ja="Song A (グループ Ver.)", rom="Song A (Group Ver.)", ko="Song A (그룹 Ver.)")
    assert recs["group-ver-off-vocal"].instrumental_of == "group-ver"
    assert [r.id for r in ds.works["p/new-song"].recordings] == ["chika-solo"]  # the original stays the single's
    assert any("Somebody feat. 誰か" in p for p in rep.pending)


def test_english_credits_an_own_line_version_and_a_bonus_performer():
    page = AQOURS.replace(
        "02. Step! ZERO to ONE<br><span class=\"uta\">作詞：畑 亜貴 作編曲：高田 暁</span><br>",
        "02. Step! ZERO to ONE<br>Lyric：Aki Hata<br>Music：Ken Ito , Hajime Mitsumasu(FirstCall)<br>Heavy Metal Ver.<br>"
        "Arranged by MEG , Yusuke Koshiro<br>Mixed by MEG<br>■ボーナストラック<br>03. Main theme<br><span class=\"uta\">浦の星交響楽団</span><br>"
        "・アニメーションPV DISC付き<br>04. ラジオ体操第一<br><span class=\"uta\">掛け声：高海千歌(CV.伊波杏樹)</span><br>")
    [b] = aqours_page(page, "https://x/cd.php")
    step, theme, radio = b.tracks[1:4]
    assert step.title == "Step! ZERO to ONE (Heavy Metal Ver.)"
    assert {k: [(c.name, c.affiliation) for c in v] for k, v in step.credits.items()} == {
        "lyricist": [("Aki Hata", None)], "composer": [("Ken Ito", None), ("Hajime Mitsumasu", "FirstCall")],
        "arranger": [("MEG", None), ("Yusuke Koshiro", None)]}  # "Mixed by" is not a credit we keep
    assert theme.performers.artist == "浦の星交響楽団"
    assert radio.performers.members == [("高海千歌", "伊波杏樹")]
