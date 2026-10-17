from takasaki.text import (
    has_kana, join_ja_name, match_key, note_version, parse_credit, recording_kind, render_credit_name, slugify,
    split_version,
)


def test_match_key_ignores_width_spacing_and_punctuation():
    assert match_key("Trick ＆ Cute") == match_key("Trick & Cute")
    assert match_key("LIVE with a smile! (Liella! ver.)") == match_key("LIVE with a smile! (Liella! Ver.)")
    assert match_key("渡辺 曜", person=True) == match_key("渡辺曜", person=True)
    assert match_key("イワツボコーダイ", person=True) == match_key("いわつぼこーだい", person=True)
    assert match_key("菊池博人") != match_key("菊地博人")  # one-kanji differences are never folded (§5.6)


def test_parse_credit_affiliation_and_d10_spacing():
    names, aff, role, normalised = parse_credit(
        {"ja": "光増ハジメ(FirstCall)", "rom": "Hajime Mitsumasu(FirstCall)", "ko": "미츠마스 하지메(FirstCall)"}
    )
    assert names == {"ja": "光増ハジメ", "rom": "Hajime Mitsumasu", "ko": "미츠마스 하지메"}
    assert (aff, role, normalised) == ("FirstCall", None, False)
    _, aff, _, normalised = parse_credit(
        {"ja": "久保田真悟(Jazzin'park)", "rom": "Singo Kubota (Jazzin'park)", "ko": "쿠보타 신고(Jazzin'park)"}
    )
    assert aff == "Jazzin'park" and normalised
    assert render_credit_name("Singo Kubota", "rom", "Jazzin'park") == "Singo Kubota(Jazzin'park)"


def test_parse_credit_role_round_trips():
    parts = {"ja": "堀内まり菜（椿 ルリカ役）", "rom": "Marina Horiuchi(as Rurika Tsubaki)", "ko": "호리우치 마리나(츠바키 루리카 역)"}
    names, aff, role, _ = parse_credit(parts)
    assert aff is None and role == {"ja": "椿 ルリカ", "rom": "Rurika Tsubaki", "ko": "츠바키 루리카"}
    assert all(render_credit_name(names[l], l, role=role[l]) == parts[l] for l in parts)


def test_parse_credit_mismatched_parenthesis_stays_raw():
    parts = {"ja": "A(x)", "rom": "A(y)", "ko": "A(x)"}
    assert parse_credit(parts) == (parts, None, None, False)


def test_versions_and_kinds():
    assert split_version("Landing action Yeah!! (高海千歌 Solo Ver.)") == ("Landing action Yeah!!", "高海千歌 Solo Ver.")
    assert split_version("始まりは君の空 (Off Vocal)") == ("始まりは君の空", "Off Vocal")
    assert split_version("L！ L！ L！ (Love the Life We Live)") == ("L！ L！ L！ (Love the Life We Live)", None)
    assert recording_kind("X (Off Vocal)", "") == "off_vocal"
    assert recording_kind("X", "Drama Part, ラブライブ！") == "drama"
    assert note_version("Disc.1, 9 Members Ver.") == "9 Members Ver."
    assert note_version("DiverDiva 1st") is None


def test_slug_and_scripts():
    assert slugify("Ceras Y. Lilienfeld") == "ceras-y-lilienfeld"
    assert slugify("Café ∞") == "cafe"
    assert not has_kana("R・O・N")  # the katakana middle dot is punctuation
    assert has_kana("ラブライブ")


def test_japanese_name_spacing():
    # D28: space only between two all-kanji parts
    assert join_ja_name("渡辺", "曜") == "渡辺 曜"
    assert join_ja_name("中﨑", "花音") == "中﨑 花音"  # compatibility ideograph
    assert join_ja_name("光増", "ハジメ") == "光増ハジメ"
    assert join_ja_name("桜小路", "きな子") == "桜小路きな子"
    assert join_ja_name("ペイトン", "尚未") == "ペイトン尚未"
