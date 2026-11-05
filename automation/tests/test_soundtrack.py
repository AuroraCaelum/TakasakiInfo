"""Soundtracks (D53): the printed track titles, the label's catalog page and Fandom's track lines."""

from takasaki import soundtrack as st
from takasaki.importer import Performers


def test_a_printed_title_is_taken_apart():
    # the cue code and the theme note are notes; the size in the note is the version
    p = st.read_title("僕らは今のなかで【TVアニメ1期オープニングテーマ(TVサイズ)】")
    assert (p.base, p.version, p.notes) == ("僕らは今のなかで", "TVサイズ", ["TVアニメ1期オープニングテーマ"])
    assert st.read_title("大変です！！！ [LM01]").notes == ["LM01"]
    assert (st.read_title("ユメノトビラ（TVサイズ）").version, st.read_title("ユメノトビラ（TVサイズ）").tail) == ("TVサイズ", "（TVサイズ）")
    assert st.read_title("友情ノーチェンジ（BGM）").notes == ["BGM"]  # a song played as BGM
    assert st.read_title("Tiny Stars（第3話Ver.）").version == "第3話Ver."
    p = st.read_title("未熟DREAMER ～ピアノアレンジVer.～")
    assert (p.base, p.version, p.wave) == ("未熟DREAMER", "ピアノアレンジVer.", True)
    assert st.read_title("色とりどりの虹 EDM ver.").version == "EDM ver."
    assert st.read_title("Dream Believers（Off Vocal）").off_vocal
    assert st.read_title("秘密のノート ※未使用音源").notes == ["未使用音源"]


def test_album_titles_and_title_case():
    assert st.album_title("TVアニメ『ラブライブ！』オリジナルサウンドトラック「Notes of School Idol Days」") == "Notes of School Idol Days"
    assert st.title_case("kimi no kokoro wa kagayaiteru kai") == "Kimi no Kokoro wa Kagayaiteru Kai"
    assert st.title_case("ZENKAI NO TEST") == "ZENKAI NO TEST"  # written in capitals on purpose


def test_the_catalog_page_gives_each_track_its_singers_and_latin_title():
    rows = ["LACA-9281", "2013/02/27", "ALBUM", "Lantis", "オリジナルサウンドトラック", "Original Soundtrack",
            "DISC 1", "1.", "始まりの朝 (メインテーマ)", "2.", "僕らは今のなかで (TVサイズ)", "μ's",
            "DISC 1", "1.", "Hajimari no Asa (Main Theme)", "2.", "Bokura wa Ima no Naka de (TV Size)", "μ's"]
    album = st.read_catalog("".join(f"<p>{r}</p>" for r in rows), "https://catalog/62812/")
    assert (album.catalog, album.title_en) == ("LACA-9281", "Original Soundtrack")
    cue, song = album.discs[0]
    assert (cue.ja, cue.singers, cue.en) == ("始まりの朝 (メインテーマ)", None, "Hajimari no Asa (Main Theme)")
    assert (song.singers, song.en) == ("μ's", "Bokura wa Ima no Naka de (TV Size)")
    assert album.track(1, 1) is song and album.track(2, 0) is None


def test_catalog_singers():
    assert st.catalog_singers("Liella!") == Performers("Liella!", None)
    p = st.catalog_singers("高坂穂乃果(CV.新田恵海) from μ's/南ことり(CV.内田 彩) from μ's")
    assert p.members == [("高坂穂乃果", "新田恵海"), ("南ことり", "内田 彩")]
    assert st.catalog_singers("A-RISE (綺羅ツバサ(CV.桜川めぐ)、統堂英玲奈(CV.松永真穂))") == Performers("A-RISE", None)


def test_fandom_track_lines():
    t = st._fandom_line("#{{Nihongo|Taihen desu!!!|大変です！！！}} (LM01)")
    assert (t.rom, t.ja, t.link) == ("Taihen desu!!!", "大変です！！！", None)
    t = st._fandom_line("#{{Nihongo|[[Bokura wa Ima no Naka de]] (TV Size)|僕らは今のなかで (TVサイズ)}} by [[μ's]]")
    assert (t.link, t.by) == ("Bokura wa Ima no Naka de", ["μ's"])
