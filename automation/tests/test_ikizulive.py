import datetime as dt

import pytest
from ruamel.yaml import YAML

from takasaki import ikizulive as ik
from takasaki import model as m
from takasaki.official import approve_names, item_values
from takasaki.review import apply_reviews
from takasaki.store import Dataset

URL = "https://www.lovelive-anime.jp/lovehigh/music/detail.php?p=01_9999"


# --- parser (synthetic pages in the site's layout; raw pages are never committed, D9) ------------


def test_credit_line_formats():
    c = ik.parse_credit_line("作詞：畑 亜貴　作曲/編曲：光増ハジメ (FirstCall)")
    assert [(x.name, x.affiliation) for x in c["lyricist"]] == [("畑 亜貴", None)]
    assert [(x.name, x.affiliation) for x in c["arranger"]] == [("光増ハジメ", "FirstCall")]
    # spaces around the colon, full-width parentheses, several people
    c = ik.parse_credit_line("作詞 : 新谷風太 作曲／編曲 : 小高光太郎・谷ナオキ（Arte Refact）")
    assert [x.name for x in c["lyricist"]] == ["新谷風太"]
    assert [(x.name, x.affiliation) for x in c["composer"]] == [("小高光太郎", None), ("谷ナオキ", "Arte Refact")]
    with pytest.raises(ik.ParseError):
        ik.parse_credit_line("作詞：A 歌：B")


def test_performer_blocks():
    p = ik.parse_performers(["いきづらい部！", "高橋ポルカ(CV.綾咲穂音) , 麻布麻衣(CV.遠藤璃菜) ,", "五桐 玲(CV.宮野 芹)"])
    assert (p.artist, p.group) == ("いきづらい部！", None)
    assert p.members == [("高橋ポルカ", "綾咲穂音"), ("麻布麻衣", "遠藤璃菜"), ("五桐 玲", "宮野 芹")]
    p = ik.parse_performers(["CHAKI！ from いきづらい部！", "高橋ポルカ(CV.綾咲穂音) , 麻布麻衣(CV.遠藤璃菜)"])
    assert (p.artist, p.group, len(p.members)) == ("CHAKI！", "いきづらい部！", 2)
    p = ik.parse_performers(["麻布麻衣(CV.遠藤璃菜) , 調布のりこ(CV.瀬古梨愛) from いきづらい部！"])
    assert (p.artist, p.group, [c for c, _ in p.members]) == (None, "いきづらい部！", ["麻布麻衣", "調布のりこ"])
    assert ik.parse_performers(["アーティスト：いきづらい部！"]).artist == "いきづらい部！"


def _detail(*, title: str = "「Song A」", artist: list[str], catalog: list[str], content: list[str]) -> str:
    rows = ["いきづらい部！ 9th Single", title, "2026.12.01 Release", "アーティスト", *artist,
            "発売日", "2026年12月01日（火） ※各種音楽配信サービスでは12月8日(火)配信開始予定です。",
            "品番", *catalog, "価格", "1,000円", "収録内容", *content,
            "■楽曲配信：https://lnk.to/LACM-29999", "BACK"]
    return "<html><!--Music-->" + "".join(f"<p>{r}</p>\n" for r in rows) + "<!--Footer--></html>"


def test_detail_page():
    html = _detail(
        artist=["いきづらい部！", "高橋ポルカ(CV.綾咲穂音) , 麻布麻衣(CV.遠藤璃菜)"],
        catalog=["【初回生産限定盤】", "LACM-39999［CD+BD+グッズ］", "【通常盤】", "LACM-29999［CDのみ］"],
        content=["【収録内容（CD共通）】", "01. Song A", "作詞：畑 亜貴　作曲/編曲：光増ハジメ (FirstCall)",
                 "02. Song A (高橋ポルカ Solo Ver.)", "作詞：畑 亜貴　作曲/編曲：光増ハジメ (FirstCall)",
                 "03. Song A (Off Vocal)", "【Blu-ray】", "01. MV"],
    )
    r = ik.parse_detail(html, URL)
    assert (r.title, r.release_date, r.page_id) == ("Song A", dt.date(2026, 12, 1), "01_9999")
    assert r.note == "各種音楽配信サービスでは12月8日(火)配信開始予定です。"
    assert [(e.label, e.catalog, ik._media(e.media)) for e in r.editions] == [
        ("初回生産限定盤", "LACM-39999", ["CD", "BD"]), ("通常盤", "LACM-29999", ["CD"])]
    assert [t.title for t in r.tracks] == ["Song A", "Song A (高橋ポルカ Solo Ver.)", "Song A (Off Vocal)"]  # video tracks left out
    assert r.links == {"楽曲配信": "https://lnk.to/LACM-29999"}
    with pytest.raises(ik.ParseError):
        ik.parse_detail("<html><!--Music--><p>nothing</p><!--Footer--></html>", URL)


# --- importer -----------------------------------------------------------------------


@pytest.fixture
def ds() -> Dataset:
    ds = Dataset()
    ds.meta = m.Meta(schema_version="1", db_last_update="2026-01-01T00:00:00Z")
    ds.layout = m.LegacyLayout(integrated_order=["Muse"], albums={}, members={}, concerts={})
    ds.projects["ikizulive"] = m.Project(id="ikizulive", names=m.Names(ja="イキヅライブ！"))
    ds.persons["aki-hata"] = m.Person(id="aki-hata", names=m.Names(ja="畑 亜貴", rom="Aki Hata", ko="하타 아키"))
    return ds


def _site() -> ik.Site:
    perf = ik.Performers("いきづらい部！", None, [("高橋ポルカ", "綾咲穂音")])
    tracks = [ik.TrackObs(1, "ヒミツミチ", credits={"lyricist": [ik.CreditName("畑 亜貴")],
                                                 "composer": [ik.CreditName("Yuta Sakai")],
                                                 "arranger": [ik.CreditName("Yuta Sakai")]}),
              ik.TrackObs(2, "ヒミツミチ (高橋ポルカ Solo Ver.)"),
              ik.TrackObs(3, "ヒミツミチ (Off Vocal)")]
    rel = ik.ReleaseObs(URL, "いきづらい部！ 1st Single", "ヒミツミチ", dt.date(2025, 7, 30), perf,
                        [ik.EditionObs("初回生産限定盤", "LACM-30001", "CD+グッズ"), ik.EditionObs("通常盤", "LACM-20001", "CDのみ")],
                        tracks, {"楽曲配信": "https://lnk.to/x"})
    return ik.Site([ik.MemberObs("高橋ポルカ", "Takahashi Polka", "1年生", "綾咲穂音", "Ayasaki Honon")], [rel], "https://x/member/")


def _fill(review_dir, file, values):
    y = YAML(typ="safe")
    doc = y.load((review_dir / file).read_text(encoding="utf-8"))
    for it in doc["items"]:
        it.update(values[it["printed"]])
    (review_dir / file).write_text(__import__("json").dumps(doc, ensure_ascii=False), encoding="utf-8")


def test_import_waits_for_names_then_creates_drafts_and_approves(ds, tmp_path):
    today = dt.date(2026, 10, 18)
    rep = ik.import_site(ds, _site(), tmp_path, today)
    # first run: unknown names become review items; nothing that needs them is created
    assert any("ヒミツミチ" in p for p in rep.pending) and not ds.releases
    assert "yuta-sakai" in ds.persons  # a Latin name needs no reading: rom = ko = ja
    _fill(tmp_path, "IKZ-members.yaml", {
        "綾咲穂音": {"family_name": {"ja": "綾咲", "rom": "Ayasaki", "ko": "아야사키"}, "given_name": {"ja": "穂音", "rom": "Honon", "ko": "호논"}},
        "高橋ポルカ": {"family_name": {"ja": "高橋", "rom": "Takahashi", "ko": "타카하시"}, "given_name": {"ja": "ポルカ", "rom": "Polka", "ko": "폴카"}},
    })
    _fill(tmp_path, "IKZ-artists.yaml", {"いきづらい部！": {"names": {"ja": "いきづらい部！", "rom": "Ikizurai-bu!", "ko": "이키즈라이부!"}}})
    _fill(tmp_path, "IKZ-titles.yaml", {"ヒミツミチ": {"title": {"ja": "ヒミツミチ", "rom": "Himitsu Michi", "ko": "비밀 길"}}})
    rep = ik.import_site(ds, _site(), tmp_path, today)
    assert not rep.pending and not rep.conflicts
    rel = ds.releases["ikizulive/2025-himitsu-michi"]
    assert [e.media for e in rel.editions] == [["CD"], ["CD"]] and rel.label == "Lantis"
    work = ds.works["ikizulive/himitsu-michi"]
    assert [r.id for r in work.recordings] == ["original", "polka-takahashi-solo-ver", "off-vocal"]
    solo = work.recordings[1]
    assert solo.title.ja == "ヒミツミチ (高橋ポルカ Solo Ver.)" and solo.title.ko == "비밀 길 (타카하시 폴카 Solo Ver.)"
    assert work.recordings[2].instrumental_of == "original" and work.recordings[2].arranger == work.recordings[0].arranger
    assert ds.characters["ikizulive/polka-takahashi"].names.ja == "高橋ポルカ"  # D28: kana given name, no space
    assert ds.persons["honon-ayasaki"].names.ja == "綾咲 穂音"
    assert ds.characters["ikizulive/polka-takahashi"].evidence["names"].status == m.Status.draft
    assert [e.release for e in ds.layout.albums["Ikizulive"].entries] == [rel.id]
    # a second run changes nothing
    assert ik.import_site(ds, _site(), tmp_path, today).updated == []
    # approve: drafts take the item's status
    assert apply_reviews(ds, tmp_path) == []  # no decision yet → nothing applied
    for f in ("IKZ-members.yaml", "IKZ-artists.yaml", "IKZ-titles.yaml", "IKZ-persons.yaml"):
        if (tmp_path / f).exists():
            doc = YAML(typ="safe").load((tmp_path / f).read_text(encoding="utf-8"))
            approve_names(ds, doc, today)
    assert ds.characters["ikizulive/polka-takahashi"].evidence["names"].status == m.Status.derived
    assert ds.works["ikizulive/himitsu-michi"].evidence["title"].status == m.Status.derived


def test_item_values_composes_names_and_reports_gaps():
    item = {"kind": "person", "family_name": {"ja": "公野", "rom": "Kimino", "ko": "키미노"},
            "given_name": {"ja": "櫻子", "rom": "Sakurako", "ko": "사쿠라코"}, "names": {"ja": "", "rom": "", "ko": ""}}
    n = item_values(item)["names"]
    assert (n.ja, n.rom, n.ko) == ("公野 櫻子", "Sakurako Kimino", "키미노 사쿠라코")
    with pytest.raises(ValueError, match="ko"):
        item_values({"kind": "person", "names": {"ja": "こむぎ", "rom": "Komugi", "ko": ""}})
