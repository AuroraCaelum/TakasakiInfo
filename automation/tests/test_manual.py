"""Releases entered by hand (D53): an entry of automation/manual/releases.yaml read like an official page."""

import datetime as dt

from takasaki import manual
from takasaki.importer import Performers


def test_an_entry_reads_like_a_page():
    e = {"project": "liella", "source": "https://catalog.bandainamcomusiclive.co.jp/release/84139/",
         "sources": ["https://www.lovelive-anime.jp/yuigaoka/news/"], "title": "Liella! CLUB CD SET 2024",
         "date": "2024-03-27", "type": "album", "artist": "Liella!", "smartlink": "https://lnk.to/x",
         "editions": [{"label": "CD", "catalog": "LACA-25100", "media": "CD", "date": "2024-04-01"}],
         "discs": [{"tracks": [{"title": "Song", "singers": "澁谷かのん(CV.伊達さゆり)", "credits": "作詞：宮嶋淳子 作曲：大畑拓也"},
                               "Song（Off Vocal）"]},
                   {"tracks": [{"title": "Drama", "drama": True}, {"title": "Other", "recording": "liella/other#original"}]}]}
    obs = manual.observation(e)
    assert (obs.url, obs.title, obs.release_date, obs.type) == (e["source"], e["title"], dt.date(2024, 3, 27), "album")
    assert obs.urls == [e["source"], "https://www.lovelive-anime.jp/yuigaoka/news/"] and obs.links == {"smartlink": "https://lnk.to/x"}
    assert obs.performers == Performers("Liella!", None)
    assert [(x.label, x.catalog, x.media) for x in obs.editions] == [("CD", "LACA-25100", "CD")]
    song, off, drama, other = obs.tracks
    assert (song.no, song.disc, song.printed) == (1, 1, "Song") and song.performers.members == [("澁谷かのん", "伊達さゆり")]
    assert [c.name for c in song.credits["lyricist"]] == ["宮嶋淳子"]
    assert (off.no, off.performers, off.credits) == (2, None, {})
    assert (drama.no, drama.disc, drama.drama) == (1, 2, True)
    assert other.recording == "liella/other#original"


def test_live_takes_named_works_and_a_cd_without_a_track_list():
    e = {"project": "aqours", "source": "https://catalog/1/", "title": "LIVE CD", "date": "2025-10-01", "type": "live_album",
         "tracks": [{"title": "青空Jumping Heart", "singers": "Aqours", "version": "Finale Ver.",
                     "live": {"concert": "aqours/aqours-finale", "date": "2025-06-21"}},
                    {"title": "Dye the sky.", "work": "external/dye-the-sky"}]}
    take, named = manual.observation(e).tracks
    assert (take.live.concert, str(take.live.date), take.version) == ("aqours/aqours-finale", "2025-06-21", "Finale Ver.")
    assert named.work == "external/dye-the-sky" and named.live is None
    assert manual.observation({**e, "tracks": None, "type": "drama_cd"}).tracks == []


def test_a_members_version_label():
    from takasaki.importer import version_labels

    assert version_labels("9人Ver.") == ("9-member-ver", "9人Ver.", "9-Member Ver.", "9인 Ver.")
