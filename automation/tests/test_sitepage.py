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
