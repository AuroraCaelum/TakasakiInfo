"""The μ's release page, written in several layouts, and its Blu-ray pages (D44)."""

import datetime as dt

from takasaki import muse
from takasaki.sitepage import performers_of

PAGE = """
<div class="box" id="cd14"><div class="titlebase"><p class="title_s">西木野真姫x園田海未x絢瀬絵里 トリオシングル</p>
<p class="title_m">soldier game</p></div><div class="text">
【アーティスト】<br>西木野真姫(CV.Pile),園田海未(CV.三森すずこ)＆<br>絢瀬絵里(CV.南條愛乃)<br>
【発売日】<br>2012年7月25日（水）<br>【収録内容】<br>01. soldier game<br>作詞：畑 亜貴 作曲・編曲：若林 充<br>
02. Daring!!<br>作詞：畑 亜貴 作曲・編曲：近藤圭一<br>歌：西木野真姫(CV.Pile)<br>03. soldier game(Off Vocal)<br>
04. まきうみえり、お勉強会しにきました！（ミニドラマ）<br></div></div><!-- ! END  -->
<div class="box" id="cd21"><div class="titlebase"><p class="title_s">TVアニメ『ラブライブ！』第1話挿入歌</p>
<p class="title_m">「ススメ→トゥモロウ」／「START:DASH!!」</p></div><div class="text">
歌：高坂穂乃果(CV.新田恵海)<br>南ことり(CV.内田 彩)<br>2013年2月20日発売<br>LACM-14055<br>
TVアニメ『ラブライブ！』第1話挿入歌<br>01. ススメ→トゥモロウ<br>作詞：畑 亜貴 作曲・編曲：河田貴央<br></div></div><!-- ! END  -->
<div class="box" id="cd31"><div class="titlebase"><p class="title_s">ラブライブ！ Solo Live! from μ's 高坂穂乃果</p>
<p class="title_m">orange cheers!</p></div><div class="text">歌：高坂穂乃果(CV.新田恵海)<br>4月2日発売<br>LACA-15381<br>
【収録曲】<br>01. もぎゅっと"love"で接近中！（HONOKA Mix）<br>作詞：畑 亜貴 作曲：増田達行 編曲：A-bee<br></div></div><!-- ! END  -->
<div class="box" id="cd49"><div class="titlebase"><p class="title_m">「永遠フレンズ」</p></div><div class="text">
歌：Printemps（高坂穂乃果(新田恵海)、南ことり(内田 彩)、小泉花陽(久保ユリカ)）<br>発売日：2014年11月12日<br>
税抜価格：1,200円<br>LACM-14291<br>01. 永遠フレンズ<br>作詞：畑 亜貴 作曲・編曲：EFFY<br>
02. 小夜啼鳥恋詩（ルビ：ナイチンゲールラブソング）<br></div></div><!-- ! END  -->
<div class="box" id="cd90"><div class="titlebase"><p class="title_s">μ’s 5thシングル</p>
<p class="title_m"><strong>「Wonderful Rush」【初回生産限定 Lジャケ仕様】</strong></p></div><div class="text">
【アーティスト】<br>μ’s<br>【発売日】<br>2024年3月27日（水）<br>【価格】<br>LACM-34564（CD1枚組）<br>【収録曲】<br>
1．Wonderful Rush<br>2．Oh,Love&Peace!<br></div></div><!-- ! END  -->
<div class="box" id="cd62"><div class="titlebase"><p class="title_m">Blu-ray Memorial BOX</p></div><div class="text">
発売日：2015年9月30日<br>LABX-8110～3（Blu-ray4枚組）<br>【収録内容】<br>01. オープニング<br></div></div><!-- ! END  -->
"""


def test_the_layouts_are_read_alike():
    blocks, skipped, types = muse.parse_page(PAGE, "https://x/release.php")
    trio, three, solo, printemps, reissue = blocks
    assert [n for n, _ in performers_of(trio).members] == ["西木野真姫", "園田海未", "絢瀬絵里"]
    assert [t.title for t in trio.tracks] == ["soldier game", "Daring!!", "soldier game(Off Vocal)", "まきうみえり、お勉強会しにきました！"]
    assert trio.tracks[3].drama and not trio.tracks[0].drama  # "（ミニドラマ）"
    assert (three.title, three.release_date) == ("ススメ→トゥモロウ / START:DASH!!", dt.date(2013, 2, 20))  # no labels at all
    assert [n for n, _ in performers_of(three).members] == ["高坂穂乃果", "南ことり"]  # "歌：" above the tracks
    assert (solo.title, solo.release_date) == ("ラブライブ！ Solo Live! from μ's 高坂穂乃果 orange cheers!", dt.date(2014, 4, 2))
    assert types[solo.url] == "album"
    assert performers_of(printemps).artist == "Printemps"  # its members in brackets are the unit's
    assert printemps.tracks[1].title == "小夜啼鳥恋詩"
    assert (reissue.title, reissue.edition) == ("Wonderful Rush", "初回生産限定 Lジャケ仕様")
    assert any("cd62" in s and "video" in s for s in skipped)


BD = """
<div id="bd01"><p>「ラブライブ！」Blu-ray 第1巻</p>[発売日] 2013年3月22日（金）<br>・μ's オリジナルソングCD①<br>
1.「夢なき夢は夢じゃない」（歌：高坂穂乃果）<br>2.「夢なき夢は夢じゃない」(Off Vocal)<br></div>
<div id="bd02"><p>「ラブライブ！」Blu-ray 第2巻</p>[発売日] 2013年4月24日（水）<br>●映像特典<br></div>
<div id="bd00"><p>「ラブライブ！」法人特典</p>アニブロゲーマーズ<br>○全巻購入特典<br>
Printemps（高坂穂乃果・南ことり・小泉花陽）録りおろし新曲「ぷわぷわーお！」収録CD<br></div>
"""
BOX = """＜収録曲＞<br>夢なき夢は夢じゃない<br>／高坂穂乃果(CV.新田恵海)<br>Anemone heart<br>
／南ことり(CV.内田 彩)・園田海未(CV.三森すずこ)<br>""" + "".join(f"x{i}<br>／μ's<br>" for i in range(13)) + \
    """ぷわぷわーお！<br>／Printemps<br>(高坂穂乃果(CV.新田恵海)、南ことり(CV.内田 彩)、小泉花陽(CV.久保ユリカ))<br>"""


def test_the_blu_ray_cds():
    box = muse.parse_bd_box(BOX)
    assert [n for n, _ in box[1][1].members] == ["南ことり", "園田海未"]
    vol1, vol2, full = muse.parse_bd_page(BD, "https://x/bd/tv1st/", "TVA1", box)
    assert (vol1.title, [t.title for t in vol1.tracks]) == ("TVA1 BD Vol.1", ["夢なき夢は夢じゃない", "夢なき夢は夢じゃない (Off Vocal)"])
    assert vol1.tracks[0].performers.members == [("高坂穂乃果", "")]
    # Vol.2's block does not print its CD: the box page names the song and its singers
    assert (vol2.title, vol2.tracks[0].title) == ("TVA1 BD Vol.2", "Anemone heart")
    assert (full.title, full.release_date, full.tracks[0].title) == ("TVA1 BD Full (Gamers)", dt.date(2013, 4, 24), "ぷわぷわーお！")
    assert full.performers.artist == "Printemps" and full.url.endswith("#bd00-gamers")
