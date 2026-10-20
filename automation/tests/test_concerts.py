"""Fandom set lists and the concert schedule import (§7.7, D47)."""

import datetime as dt

import pytest

from takasaki import concerts, fandom
from takasaki import model as m
from takasaki.store import Dataset

PAGE = """{{Nihongo|'''Love Live! Sunshine!! Aqours 2nd LoveLive!'''|ラブライブ！サンシャイン!! Aqours 2nd LoveLive!}} was a concert.
==Performers==
*Aqours
==Set Lists==
==='''Nagoya'''===
{{Aqours Tab|<tabber>
Day 1=
#'''Opening'''
#[[HAPPY PARTY TRAIN]] by [[Aqours]]
#{{Nihongo|[[Yuuki wa Doko ni? Kimi no Mune ni!]]|勇気はどこに？君の胸に！}} by Aqours (short version)
#'''MC'''
#{{Nihongo|[[Suisai Sekai|Suisai Sekai (104th Class Ver.)]]|水彩世界（104期 Ver.）}} by [[Cerise Bouquet]]
#'''Medley Part'''
#*[[Mijuku DREAMER]] by Aqours (Chika Takami, Riko Sakurauchi)
#[[Saint Snow Song]] (セイントスノーの歌) by Saint Snow
#{{Nihongo|Kyouki Ranbu|俠気乱舞}} by Tokyo Philharmonic Orchestra
#'''ENCORE'''
#[[Duo]] by [[Ruri&To]]
|-|
Day 2=
##[[HAPPY PARTY TRAIN]] by [[Aqours]]
</tabber>}}
==Gallery==
#[[Not a song]] by nobody
"""


def test_the_tabs_and_items():
    tabs = fandom.parse_setlists(PAGE)
    assert [(t.section, t.name, len(t.items)) for t in tabs] == [("Nagoya", "Day 1", 11), ("Nagoya", "Day 2", 1)]
    items = tabs[0].items
    assert [i.kind for i in items] == ["video", "song", "song", "mc", "song", "other", "song", "song", "song", "encore", "song"]
    assert (items[2].title, items[2].ja, items[2].version, items[2].singers) == (
        "Yuuki wa Doko ni? Kimi no Mune ni!", "勇気はどこに？君の胸に！", "short version", ["Aqours"])
    assert (items[4].title, items[4].ja) == ("Suisai Sekai", "水彩世界（104期 Ver.）")  # the article, not its label
    assert items[6].singers == ["Aqours"]  # the group with its members in brackets
    assert (items[7].ja, items[7].linked) == ("セイントスノーの歌", True)
    assert items[8].linked is False
    assert items[10].by == "Ruri&To"


def _ds() -> Dataset:
    ds = Dataset()
    ds.artists["aqours"] = m.Artist(id="aqours", kind="group", projects=["aqours"], names=m.Names(ja="Aqours", rom="Aqours"))
    ds.artists["ruri-to"] = m.Artist(id="ruri-to", kind="unit", projects=["hasunosora"], names=m.Names(ja="Ruri&To", rom="Ruri&To"))
    ds.artists["cerise-bouquet"] = m.Artist(id="cerise-bouquet", kind="unit", projects=["hasunosora"],
                                            names=m.Names(ja="スリーズブーケ", rom="Cerise Bouquet"))
    for wid, ja, rom, recs in [
        ("aqours/happy-party-train", "HAPPY PARTY TRAIN", "HAPPY PARTY TRAIN", []),
        ("aqours/yuki-wa-doko-ni", "勇気はどこに？君の胸に！", "Yuki wa Doko ni? Kimi no Mune ni!", []),  # Yuki, not Yuuki
        ("hasunosora/suisai-sekai", "水彩世界", "Suisai Sekai",
         [m.Recording(id="104th", version="104期 Ver.", title=m.Names(ja="水彩世界（104期 Ver.）"))]),
        ("aqours/mijuku-dreamer", "未熟DREAMER", "Mijuku DREAMER", []),
        ("hasunosora/duo", "Duo", "Duo", []),
    ]:
        ds.works[wid] = m.Work(id=wid, project=wid.split("/")[0], title=m.Names(ja=ja, rom=rom),
                               recordings=[m.Recording(id="original"), *recs])
    return ds


def test_songs_resolve_to_works_and_singers():
    ds = _ds()
    items, unresolved = concerts.setlist(fandom.parse_setlists(PAGE)[0].items, concerts.Resolver(ds), ["aqours"])
    assert items[0] == m.SetlistItem(type="video", label="Opening")
    assert items[2].work == "aqours/yuki-wa-doko-ni"  # the long vowel is forgiven
    assert items[2].version == "short version"
    assert items[3] == m.SetlistItem(type="mc")  # numbered by the legacy builder
    assert (items[4].work, items[4].recording, items[4].version) == ("hasunosora/suisai-sekai", "hasunosora/suisai-sekai#104th", None)
    assert items[4].performers == [m.Performer(artist="cerise-bouquet")]
    assert items[5] == m.SetlistItem(type="other", label="Medley Part")
    assert items[9] == m.SetlistItem(type="encore", label="Encore")
    assert items[10].performers == [m.Performer(artist="ruri-to")]  # one unit, not "Ruri" and "To"
    assert [u["title_raw"] for u in unresolved] == ["セイントスノーの歌", "俠気乱舞"]
    assert items[7].title_raw == "セイントスノーの歌" and items[7].work is None


def test_lines_the_wiki_writes_oddly():
    items = fandom.parse_setlists("==Set Lists==\n" + "\n".join([
        "#3[[Guilty Eyes Fever]] by Guilty Kiss",  # a stray digit before the link
        "#{{w|Santa Claus Is Comin' to Town|Santa ga Machi ni Yattekuru}} (サンタが街にやってくる) by Nijigasaki High School Idol Club",
        "#{{Nihongo|Hajimari no Asa (Main Theme|始まりの朝（メインテーマ）}} by Tokyo Philharmonic Orchestra",  # no closing bracket
        "#{{Nihongo|[[Private Wars]] / Zetsubou|Private Wars / 絶望}} by Tokyo Philharmonic Orchestra",  # two songs
        "#Shine!! Short Ver. by Cinderella Girls",
    ]))[0].items
    assert [(i.title, i.ja, i.version) for i in items] == [
        ("Guilty Eyes Fever", None, None), ("Santa ga Machi ni Yattekuru", "サンタが街にやってくる", None),
        ("Hajimari no Asa (Main Theme)", "始まりの朝（メインテーマ）", None), ("Private Wars", "Private Wars", None),
        ("Zetsubou", "絶望", None), ("Shine!!", None, "Short Ver.")]
    assert items[4].singers == ["Tokyo Philharmonic Orchestra"]
    # what the wiki writes wrong is corrected by title (TITLE_FIXES)
    fixed = concerts._fixed(fandom.parse_item("#{{Nihongo|Ima Shiknai Shunkan o|今しかない瞬間を}} by noctchill"))
    assert (fixed.title, fixed.ja) == ("Ima Shika Nai Shunkan o", "今しかない瞬間を")


def test_a_guest_after_feat_is_featured():
    # D48: Aqours and the featured 初音ミク, not one joint artist; "with" joins singers as before
    ds = _ds()
    ds.characters["external/miku"] = m.Character(id="external/miku", project="external",
                                                 names=m.Names(ja="初音ミク", rom="Hatsune Miku"))
    page = "==Set Lists==\n#[[HAPPY PARTY TRAIN]] by [[Aqours]] feat. [[Hatsune Miku]]\n#[[Duo]] by Aqours with Cerise Bouquet\n"
    items, _ = concerts.setlist(fandom.parse_setlists(page)[0].items, concerts.Resolver(ds), ["aqours"])
    assert items[0].performers == [m.Performer(artist="aqours"), m.Performer(character="external/miku", featured=True)]
    assert items[1].performers == [m.Performer(artist="aqours"), m.Performer(artist="cerise-bouquet")]


def _concert(status: str) -> m.Concert:
    return m.Concert(id="aqours/aqours-2nd", projects=["aqours"], status=status, title=m.Names(ja="Aqours 2nd"),  # type: ignore[arg-type]
                     external_ids={"fandom": "Aqours 2nd"},
                     stops=[m.Stop(id="1-aichi", city="aichi", venue="hall", performances=[
                         m.Performance(date=dt.date(2017, 8, 5), external_ids={"fandom": "Nagoya|Day 1"}),
                         m.Performance(date=dt.date(2017, 8, 6), external_ids={"fandom": "Nagoya|Day 2"},
                                       setlist=[m.SetlistItem(work="aqours/mijuku-dreamer")])])])


def test_a_performed_concert_takes_the_list_and_a_settled_one_reports_it(tmp_path):
    ds = _ds()
    ds.concerts["aqours/aqours-2nd"] = _concert("performed")
    r = concerts.import_setlists(ds, {"Aqours 2nd": PAGE}, tmp_path, dt.date(2026, 10, 20))
    day1, day2 = ds.concerts["aqours/aqours-2nd"].stops[0].performances
    assert len(day1.setlist) == 11 and [x.work for x in day2.setlist] == ["aqours/happy-party-train"]
    ev = ds.concerts["aqours/aqours-2nd"].evidence["setlist.2017-08-05"]
    assert ev.status == m.Status.draft and ev.source.endswith("/wiki/Aqours_2nd")
    assert len(r.updated) == 2 and (tmp_path / "LIV-setlist-songs.yaml").exists()  # the unresolved songs
    assert not concerts.import_setlists(ds, {"Aqours 2nd": PAGE}, tmp_path, dt.date(2026, 10, 21)).updated  # idempotent

    ds.concerts["aqours/aqours-2nd"] = _concert("settled")
    r = concerts.import_setlists(ds, {"Aqours 2nd": PAGE}, tmp_path, dt.date(2026, 10, 20))
    assert [x.work for x in ds.concerts["aqours/aqours-2nd"].stops[0].performances[1].setlist] == ["aqours/mijuku-dreamer"]
    assert any("2017-08-06" in c and "aqours/mijuku-dreamer → aqours/happy-party-train" in c for c in r.conflicts)


def test_a_schedule_creates_the_concert_its_venues_and_review_items(tmp_path):
    ds = Dataset()
    ds.cities["aichi"] = m.City(id="aichi", names=m.Names(rom="Aichi"))
    entry = {"fandom": "Aqours 2nd", "id": "aqours/aqours-2nd", "projects": ["aqours"],
             "title_ja": "ラブライブ！サンシャイン!! Aqours 2nd LoveLive! HAPPY PARTY TRAIN TOUR",
             "title_source": "https://www.lovelive-anime.jp/uranohoshi/sp_2ndlive.php",
             "stops": [{"id": "1-aichi", "city": {"id": "aichi"}, "venue": {"ja": "日本ガイシホール", "rom": "Nippon Gaishi Hall"},
                        "source": "https://www.lovelive-anime.jp/uranohoshi/sp_2ndlive.php",
                        "performances": [{"date": dt.date(2017, 8, 5), "label": "Day.1", "fandom": [{"section": "Nagoya", "tab": "Day 1"}]},
                                         {"date": dt.date(2017, 8, 6), "label": "Day.2", "fandom": [{"section": "Nagoya", "tab": "Day 2"}]}]},
                       {"id": "2-online", "city": None, "venue": {"online": True},
                        "source": "https://love-live.fandom.com/wiki/Aqours_2nd",
                        "performances": [{"date": dt.date(2017, 9, 1), "fandom": []}]}]}
    r = concerts.import_schedule(ds, [entry], tmp_path, dt.date(2026, 10, 20))
    c = ds.concerts["aqours/aqours-2nd"]
    assert c.status == "performed" and c.external_ids == {"fandom": "Aqours 2nd"}
    assert c.title.rom == "Love Live! Sunshine!! Aqours 2nd LoveLive! HAPPY PARTY TRAIN TOUR"
    assert c.title.ko == "러브 라이브! 선샤인!! Aqours 2nd LoveLive! HAPPY PARTY TRAIN TOUR"
    aichi, online = c.stops
    assert aichi.venue == "nippon-gaishi-hall" and ds.venues["nippon-gaishi-hall"].evidence["names"].status == m.Status.draft
    assert [(p.label, p.external_ids) for p in aichi.performances] == [(None, {"fandom": "Nagoya|Day 1"}), (None, {"fandom": "Nagoya|Day 2"})]
    assert (online.city, online.venue) == (None, None)
    assert c.evidence["schedule.1-aichi"].status == m.Status.official
    assert c.evidence["schedule.2-online"].status == m.Status.established
    assert r.created and (tmp_path / "LIV-concerts.yaml").exists() and (tmp_path / "LIV-venues.yaml").exists()


def test_an_announced_concert_and_the_cast_of_each_show(tmp_path):
    # §4.6: the concert's cast is every show's unless a show lists its own; a guest is featured
    ds = Dataset()
    ds.cities["aichi"] = m.City(id="aichi", names=m.Names(rom="Aichi"))
    ds.venues["dome"] = m.Venue(id="dome", city="aichi", names=m.Names(ja="バンテリンドーム ナゴヤ", rom="Vantelin Dome Nagoya"))
    page = "https://www.lovelive-anime.jp/special/live/live_detail.php?p=15th_lovelivefest"
    entry = {"id": "muse/fest", "projects": ["muse", "musical"], "status": "announced",
             "title_ja": "LoveLive! Series 15th Anniversary ラブライブ！フェス", "title_source": page,
             "stops": [{"id": "1-aichi", "city": {"id": "aichi"}, "venue": {"ja": "バンテリンドーム ナゴヤ"}, "source": page,
                        "performances": [{"date": dt.date(2026, 11, 14)}, {"date": dt.date(2026, 11, 15)}]}],
             "cast": [{"character": "muse/honoka-kosaka"}, {"person": "marina-horiuchi", "role": "musical/rurika", "featured": True}],
             "shows": [{"date": dt.date(2026, 11, 15), "cast": [{"character": "muse/honoka-kosaka"}]}],
             "cast_source": page}
    concerts.import_schedule(ds, [entry], tmp_path, dt.date(2026, 10, 20))
    c = ds.concerts["muse/fest"]
    assert c.status == "announced" and c.external_ids == {} and c.stops[0].venue == "dome"
    assert [p.ref for p in c.cast] == [("character", "muse/honoka-kosaka"), ("person", "marina-horiuchi")] and c.cast[1].featured
    day1, day2 = c.stops[0].performances
    assert day1.cast == [] and [p.ref for p in day2.cast] == [("character", "muse/honoka-kosaka")]
    assert c.evidence["cast"].status == m.Status.official

    # an existing concert gets the cast only
    existing = {"existing": "muse/fest", "cast": [{"character": "muse/kotori-minami"}], "cast_source": page}
    r = concerts.import_schedule(ds, [existing], tmp_path, dt.date(2026, 10, 21))
    assert [p.character for p in c.cast] == ["muse/kotori-minami"] and r.updated
    with pytest.raises(ValueError):  # a show the concert does not have
        concerts.import_schedule(ds, [existing | {"shows": [{"date": dt.date(2026, 1, 1), "cast": []}]}], tmp_path,
                                 dt.date(2026, 10, 21))


def test_cast_refs_are_checked_and_listed_per_show(tmp_path):
    import sqlite3

    from takasaki.build_sqlite import build_sqlite
    from takasaki.validate import validate

    ds = Dataset(meta=m.Meta(schema_version="1", db_last_update="2026-10-20T00:00:00Z"))
    ds.projects["muse"] = m.Project(id="muse", names=m.Names(ja="μ's"))
    ds.characters["muse/honoka"] = m.Character(id="muse/honoka", project="muse", names=m.Names(ja="高坂 穂乃果"))
    shows = [m.Performance(date=dt.date(2026, 11, 14)),
             m.Performance(date=dt.date(2026, 11, 15), cast=[m.Performer(character="muse/nobody")])]
    ds.concerts["muse/fest"] = m.Concert(id="muse/fest", projects=["muse"], status="announced", title=m.Names(ja="フェス"),
                                         cast=[m.Performer(character="muse/honoka")], stops=[m.Stop(id="1", performances=shows)])
    assert [f.message for f in validate(ds) if f.rule == "E2"] == ["unknown character 'muse/nobody'"]
    shows[1].cast = []
    build_sqlite(ds, tmp_path / "t.sqlite")
    con = sqlite3.connect(tmp_path / "t.sqlite")
    assert con.execute("select performance, character from cast_member order by performance").fetchall() == [
        (1, "muse/honoka"), (2, "muse/honoka")]


def test_approving_the_names(tmp_path):
    from ruamel.yaml import YAML

    from takasaki.official import approve_names

    ds = Dataset()
    entry = {"fandom": "X", "id": "aqours/x", "projects": ["aqours"], "title_ja": "ラブライブ！サンシャイン!! Aqours ～永久stage～",
             "title_en": "Love Live! Sunshine!! Aqours ～Eikyuu stage～", "title_source": "https://www.lovelive-anime.jp/x",
             "stops": [{"city": {"id": "saitama", "rom": "Saitama", "ja": "埼玉", "ko": "사이타마"},
                        "venue": {"ja": "ベルーナドーム", "rom": "Belluna Dome", "ko": "벨루나 돔"},
                        "source": "https://www.lovelive-anime.jp/x", "performances": [{"date": dt.date(2025, 6, 21)}]}]}
    concerts.import_schedule(ds, [entry], tmp_path, dt.date(2026, 10, 20))
    c = ds.concerts["aqours/x"]
    assert (c.title.rom, c.title.ko) == ("Love Live! Sunshine!! Aqours ~Eikyuu stage~", None)  # Japanese in the title: ko to fill
    doc = YAML(typ="safe").load((tmp_path / "LIV-concerts.yaml").read_text(encoding="utf-8"))
    doc["items"][0]["title"]["ko"] = "러브 라이브! 선샤인!! Aqours ~영구 stage~"
    approve_names(ds, doc, dt.date(2026, 10, 21))
    assert c.title.ko == "러브 라이브! 선샤인!! Aqours ~영구 stage~" and c.evidence["title"].status == m.Status.derived
    venues = YAML(typ="safe").load((tmp_path / "LIV-venues.yaml").read_text(encoding="utf-8"))
    assert {i["kind"] for i in venues["items"]} == {"city", "venue"}
    approve_names(ds, venues, dt.date(2026, 10, 21))
    assert ds.venues["belluna-dome"].evidence["names"].status == m.Status.derived
    assert ds.cities["saitama"].names.ko == "사이타마"


def test_a_game_is_a_marker_and_a_soundtrack_cue_is_a_work():
    # D50: a sports festival's games are listed under their marker without singers; a BGM cue is a work too
    ds = _ds()
    ds.works["muse/zetsubou"] = m.Work(id="muse/zetsubou", kind="bgm", project="muse", title=m.Names(ja="（絶望）", rom="(Zetsubou)"),
                                       external_ids={"fandom": "Zetsubou"}, recordings=[])
    page = "==Set Lists==\n" + "\n".join([
        "#'''Competition'''",
        "#*{{Nihongo|1.2.3! Tsunahiki|1.2.3！綱引き}}",
        "#*[[Mijuku DREAMER]] by Aqours",  # a song under the marker stays a song
        "#{{Nihongo|Zetsubou|絶望}} by Tokyo Philharmonic Orchestra",
        "#Rat A Tat!!! TV Size by Million Live!",
    ])
    tab = fandom.parse_setlists(page)[0]
    assert [(i.kind, i.title, i.version) for i in tab.items] == [
        ("other", "Competition", None), ("other", "1.2.3！綱引き", None), ("song", "Mijuku DREAMER", None),
        ("song", "Zetsubou", None), ("song", "Rat A Tat!!!", "TV Size")]
    items, unresolved = concerts.setlist(tab.items, concerts.Resolver(ds), ["muse"])
    assert items[3].work == "muse/zetsubou" and [u["title_raw"] for u in unresolved] == ["Rat A Tat!!!"]
