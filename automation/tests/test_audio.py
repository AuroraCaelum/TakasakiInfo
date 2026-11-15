"""Length, key, tempo and mood of recordings (D61)."""

import datetime as dt
import json

import pytest

from takasaki import model as m
from takasaki.audio import (
    MOOD_RULES, MOODS, Candidate, apply_audio, decide, effective_audio, feature_audio, moods, plan_audio,
    harmonize, representative, tempo_checks, track_matches, ytm_durations,
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


def test_key_from_reccobeats_features():
    # pitch class and mode; the source's other ratings (energy, valence, …) are not kept
    assert feature_audio({"key": 5, "mode": 1, "tempo": 79.991, "energy": 0.6}) == m.Audio(key="F", bpm=80)
    assert feature_audio({"key": 6, "mode": 0, "tempo": 168.2}) == m.Audio(key="F#m", bpm=168)
    assert feature_audio({"key": 10, "mode": 1, "tempo": 0}) == m.Audio(key="Bb")
    assert feature_audio({"key": -1, "mode": 1, "tempo": 0}) is None
    with pytest.raises(ValueError):
        m.Audio(key="F#major")


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


def _track(i, title="未熟DREAMER", artist="Aqours", seconds=351):
    return {"id": i, "trackTitle": title, "artists": [{"name": artist}], "durationMs": seconds * 1000,
            "href": f"https://open.spotify.com/track/{i}"}


class FakeRB:
    def __init__(self, tracks, feats):
        self.tracks, self.feats = tracks, feats

    def artists(self, name):
        return [{"id": "a1", "name": "Aqours"}, {"id": "a2", "name": "Saint Aqours Snow"}] if name == "Aqours" else []

    def artist_tracks(self, artist_id):
        return self.tracks if artist_id == "a1" else []

    def features(self, ids):
        return {i: self.feats[i] for i in ids if i in self.feats}


def test_reccobeats_matching():
    ds = _ds()
    w = ds.works["p/w"]
    rec = w.recordings[0]
    rec.duration = 351
    ok = lambda t: track_matches(ds, w, rec, t)  # noqa: E731
    assert ok(_track("a"))
    assert not ok(_track("b", artist="QWER"))  # another artist's song of the same title
    assert not ok(_track("c", seconds=247))  # another master (a live version)
    # a member's solo version is not the group's recording
    assert not ok(_track("d", title="未熟DREAMER - 渡辺 曜 Solo Ver.", artist="渡辺 曜 (CV.斉藤朱夏) from Aqours"))
    solo = m.Recording(id="you", performers=[m.Performer(character="p/you")], duration=350)
    ds.characters["p/you"] = m.Character(id="p/you", project="p", names=m.Names(ja="渡辺 曜", rom="You Watanabe"))
    assert track_matches(ds, w, solo, _track("d", title="未熟DREAMER - 渡辺 曜 Solo Ver.",
                                              artist="渡辺 曜 (CV.斉藤朱夏) from Aqours", seconds=350))
    # agreeing tracks give the value; disagreeing ones go to review
    f = {"a": {"id": "a", "key": 5, "mode": 1, "tempo": 160.2}, "e": {"id": "e", "key": 5, "mode": 1, "tempo": 159.8}}
    [mt] = plan_audio(FakeRB([_track("a"), _track("e")], f), ds, [(w, rec)], log=lambda s: None)
    assert mt.audio == m.Audio(key="F", bpm=160) and mt.url.endswith("ids=a")
    f["e"] = {"id": "e", "key": 5, "mode": 1, "tempo": 80.0}
    [mt] = plan_audio(FakeRB([_track("a"), _track("e")], f), ds, [(w, rec)], log=lambda s: None)
    assert mt.audio is None and len(mt.candidates) == 2
    # of three or more, a value more than half agree on is taken
    f["g"] = {"id": "g", "key": 5, "mode": 1, "tempo": 160.4}
    [mt] = plan_audio(FakeRB([_track("a"), _track("e"), _track("g")], f), ds, [(w, rec)], log=lambda s: None)
    assert mt.audio == m.Audio(key="F", bpm=160) and mt.reason == "2/3 tracks"
    [mt] = plan_audio(FakeRB([], {}), ds, [(w, rec)], log=lambda s: None)
    assert mt.reason == "no track"
    apply_audio(ds, "p/w#original", m.Audio(key="F", bpm=160), "https://api.reccobeats.com/v1/audio-features?ids=a",
                dt.date(2026, 11, 15))
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


def test_versions_of_one_arrangement_take_the_value_two_thirds_agree_on():
    ds = _ds()
    w = ds.works["p/w"]
    ev = m.Evidence(status=m.Status.established, source="https://api.reccobeats.com/v1/audio-features?ids=x")
    w.recordings[0].audio, w.recordings[0].evidence["audio"] = m.Audio(key="F", bpm=160), ev
    for i, a in enumerate([m.Audio(key="F", bpm=161), m.Audio(key="Dm", bpm=80)]):
        w.recordings.append(m.Recording(id=f"s{i}", audio=a, evidence={"audio": ev}))
    assert harmonize(ds, dt.date(2026, 11, 15)) == ["p/w#s1"]
    fixed = w.recordings[3]
    assert fixed.audio == m.Audio(key="F", bpm=160) and fixed.evidence["audio"].status == m.Status.derived
    assert "Dm 80" in fixed.evidence["audio"].note and tempo_checks(ds) == []
    # half and half: left for a person
    w.recordings[3].audio = m.Audio(key="Dm", bpm=80)
    w.recordings.append(m.Recording(id="s2", audio=m.Audio(key="Dm", bpm=80), evidence={"audio": ev}))
    assert harmonize(ds, dt.date(2026, 11, 15)) == [] and len(tempo_checks(ds)) == 1
