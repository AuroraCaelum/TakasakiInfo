"""Length, key, tempo and mood of recordings (D61)."""

import datetime as dt
import json

import pytest

from takasaki import model as m
from takasaki.audio import (
    MOOD_RULES, MOODS, Candidate, apply_audio, decide, effective_audio, match_audio, moods, parse_audio, parse_key,
    representative, tempo_checks, ytm_durations,
)
from takasaki.build_v1 import recording_view
from takasaki.store import Dataset
from takasaki.validate import validate


def _names(ja: str, rom: str | None = None) -> m.Names:
    return m.Names(ja=ja, rom=rom or ja, ko=rom or ja)


def _ds() -> Dataset:
    ds = Dataset()
    ds.meta = m.Meta(db_last_update="2026-11-14T00:00:00Z", schema_version="1.0.0")
    ds.projects["p"] = m.Project(id="p", names=_names("P"))
    ds.artists["aqours"] = m.Artist(id="aqours", kind="group", names=_names("Aqours"))
    ds.works["p/w"] = m.Work(id="p/w", project="p", title=_names("未熟DREAMER", "Mijuku DREAMER"), recordings=[
        m.Recording(id="original", performers=[m.Performer(artist="aqours")]),
        m.Recording(id="off-vocal", kind="off_vocal", version="Off Vocal", instrumental_of="original",
                    title=_names("未熟DREAMER (Off Vocal)")),
    ])
    ds.releases["p/2016-s"] = m.Release(
        id="p/2016-s", title=_names("夢で夜空を照らしたい／未熟DREAMER"), projects=["p"], release_date=dt.date(2016, 9, 14),
        artist_credit=[m.Performer(artist="aqours")],
        discs=[m.Disc(tracks=[m.Track(no=1, recording="p/w#original"), m.Track(no=2, recording="p/w#off-vocal")])],
        streaming=[m.Streaming(browse_id="MPREb_x", tracks={"1-1": "vidA", "1-2": "vidB"})])
    return ds


def test_key_parsing_and_model():
    assert parse_key("F♯m") == "F#m"
    assert parse_key("B♭") == "Bb"
    assert parse_key("Em") == "Em"
    assert parse_key("C minor") == "Cm"
    assert parse_key("H") is None and parse_key(None) is None
    with pytest.raises(ValueError):
        m.Audio(key="F#major")
    a = parse_audio({"tempo": "160", "time_sig": "4/4", "key_of": "F", "danceability": 62})
    assert a == m.Audio(key="F", bpm=160, time_signature="4/4")  # the source's other ratings are not kept
    assert parse_audio({"tempo": None, "key_of": ""}) is None


def test_moods_follow_the_rules():
    assert set(MOOD_RULES) == set(MOODS)
    assert moods(m.Audio(key="F", bpm=160)) == ["upbeat", "bright"]
    assert moods(m.Audio(key="Am", bpm=80)) == ["slow", "wistful"]
    assert moods(m.Audio(bpm=120)) == []  # nothing the source lacks makes a label
    assert moods(None) == []


def test_off_vocal_takes_its_vocal_recordings_values_and_the_work_its_representative():
    ds = _ds()
    w = ds.works["p/w"]
    ev = m.Evidence(status=m.Status.established, source="https://getsongbpm.com/song/x")
    w.recordings[0].audio, w.recordings[0].evidence["audio"] = m.Audio(key="F", bpm=160), ev
    a, src = effective_audio(w, w.recordings[1])
    assert a.bpm == 160 and src is w.recordings[0]
    assert representative(w) is w.recordings[0]
    rows = {r["id"]: r for r in recording_view(ds)}
    assert rows["p/w#original"]["representative"] and not rows["p/w#off-vocal"]["representative"]
    assert rows["p/w#off-vocal"]["audio"] == {"key": "F", "bpm": 160, "mood": ["upbeat", "bright"], "from": "p/w#original"}
    # a live recording is not the representative
    live = m.Work(id="p/l", project="p", title=_names("x"), recordings=[
        m.Recording(id="live", live=m.LiveOf(concert="c")), m.Recording(id="original")])
    assert representative(live).id == "original"
    bgm = m.Work(id="p/b", project="p", kind="bgm", title=_names("x"), recordings=[m.Recording(id="o", kind="instrumental")])
    assert representative(bgm).id == "o"


def test_e17_pairs_values_with_evidence():
    ds = _ds()
    rec = ds.works["p/w"].recordings[0]
    rec.duration = 351
    assert "E17" in [f.rule for f in validate(ds)]
    rec.evidence["duration"] = m.Evidence(status=m.Status.official, source="https://music.youtube.com/browse/MPREb_x")
    assert "E17" not in [f.rule for f in validate(ds)]
    rec.evidence["audio"] = m.Evidence(status=m.Status.established)
    assert "E17" in [f.rule for f in validate(ds)]


def test_duration_from_cached_albums_and_tolerance(tmp_path):
    ds = _ds()
    (tmp_path / "album").mkdir()
    import hashlib

    p = tmp_path / "album" / (hashlib.sha1(b"MPREb_x").hexdigest() + ".json")
    p.write_text(json.dumps({"tracks": [{"video_id": "vidA", "duration": 351}, {"video_id": "vidB", "duration": 350}]}))
    got = ytm_durations(ds, tmp_path)
    assert got["p/w#original"][0].seconds == 351 and got["p/w#off-vocal"][0].seconds == 350
    yt = lambda s, d: Candidate(s, "youtube_music", "u", "r", d)  # noqa: E731
    assert decide([yt(351, "2016-09-14"), yt(352, "2018-01-01")]).day == "2016-09-14"  # the earliest release's
    assert decide([yt(284, "2021"), yt(287, "2025")]) is None  # wider than the tolerance: review
    assert decide([Candidate(300, "deezer", "u", "r", "2016"), Candidate(301, "itunes", "u", "r", "2020")]).source == "itunes"


class FakeGSB:
    def __init__(self, hits):
        self.hits = hits

    def search(self, title, artist):
        return self.hits

    def song(self, song_id):
        return None


def _hit(i, title="未熟DREAMER", artist="Aqours", tempo=160, key="F", album="夢で夜空を照らしたい / 未熟DREAMER"):
    return {"id": i, "title": title, "uri": f"https://getsongbpm.com/song/{i}", "artist": {"name": artist},
            "album": {"title": album}, "tempo": str(tempo), "key_of": key, "time_sig": "4/4"}


def test_getsongbpm_matching():
    ds = _ds()
    w = ds.works["p/w"]
    rec = w.recordings[0]
    # same title and a singer's name: matched; another artist's song of the same title is not
    mt = match_audio(FakeGSB([_hit("a"), _hit("b", artist="QWER", tempo=91)]), ds, w, rec)
    assert mt.audio == m.Audio(key="F", bpm=160, time_signature="4/4") and mt.url.endswith("/a")
    # two hits with the same values are one
    assert match_audio(FakeGSB([_hit("a"), _hit("c")]), ds, w, rec).audio is not None
    # different values: review, with both candidates
    mt = match_audio(FakeGSB([_hit("a"), _hit("c", tempo=80)]), ds, w, rec)
    assert mt.audio is None and len(mt.candidates) == 2
    # a version's title must match with its version
    assert match_audio(FakeGSB([_hit("d", title="未熟DREAMER (渡辺 曜 Solo Ver.)")]), ds, w, rec).audio is None
    apply_audio(ds, "p/w#original", m.Audio(key="F", bpm=160), "https://getsongbpm.com/song/a", dt.date(2026, 11, 14))
    assert rec.evidence["audio"].status == m.Status.established


def test_tempo_checks_flag_versions_of_one_arrangement_that_disagree():
    ds = _ds()
    w = ds.works["p/w"]
    w.recordings.append(m.Recording(id="solo", version="Solo Ver.", audio=m.Audio(key="F", bpm=80)))
    w.recordings[0].audio = m.Audio(key="F", bpm=160)
    items = tempo_checks(ds)
    assert len(items) == 1 and items[0]["ref"] == "work:p/w"
    w.recordings[2].audio = m.Audio(key="F", bpm=161)
    assert tempo_checks(ds) == []
