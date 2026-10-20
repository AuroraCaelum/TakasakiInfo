"""YouTube Music adapter without the network: a fake client stands in for ytmusicapi."""

from takasaki import model as m
from takasaki.store import Dataset
from takasaki.ytmusic import align, apply_matches, matches_from_review, plan_release, review_doc


def _names(ja: str) -> m.Names:
    return m.Names(ja=ja, rom=ja, ko=ja)


class FakeClient:
    def __init__(self, albums: dict[str, dict], search: dict[str, list[str]] | None = None, dead: set[str] = frozenset()):
        self.albums, self.search, self.dead = albums, search or {}, dead

    def album(self, browse_id: str) -> dict:
        return self.albums[browse_id]

    def search_albums(self, query: str) -> list[dict]:
        return [{"browse_id": b} for b in self.search.get(query, list(self.albums))]

    def artist_albums(self, names: m.Names) -> list[dict]:
        return []

    def status(self, video_id: str) -> str:
        return "UNPLAYABLE" if video_id in self.dead else "OK"


def _album(title: str, *tracks: tuple[str, str]) -> dict:
    return {"title": title, "year": "2020", "tracks": [{"title": t, "video_id": v, "available": True} for t, v in tracks]}


def _ds(editions: list[m.Edition] | None = None, streaming: list[m.Streaming] | None = None) -> Dataset:
    ds = Dataset()
    ds.projects["p"] = m.Project(id="p", names=_names("P"))
    for slug, title in [("a", "曲A"), ("b", "曲B")]:
        ds.works[f"p/{slug}"] = m.Work(id=f"p/{slug}", project="p", title=_names(title), recordings=[
            m.Recording(id="original"),
            m.Recording(id="off-vocal", kind="off_vocal", title=_names(f"{title} (Off Vocal)")),
        ])
    tracks = [m.Track(no=i, recording=r) for i, r in enumerate(["p/a#original", "p/b#original", "p/a#off-vocal", "p/b#off-vocal"], 1)]
    ds.releases["p/r"] = m.Release(id="p/r", title=_names("曲A / 曲B"), projects=["p"], release_date=None,
                                   editions=editions or [], discs=[m.Disc(tracks=tracks)], streaming=streaming or [])
    return ds


def test_align_in_order_and_version_markers():
    rows = ["One More Sunshine Story (Album Version)", "曲B", "曲B (Off Vocal)"]
    # the album may omit a version marker the release prints; an exact match wins over a marker match
    assert align(["One More Sunshine Story", "曲B (Off Vocal)"], rows) == [(0, 0), (1, 2)]
    assert align(["曲B", "曲B"], rows) == [(0, 1)]  # a later album track cannot reuse a row


def test_single_album_is_applied_and_dead_ids_replaced():
    ds = _ds(streaming=[m.Streaming(tracks={"1-1": "deadA"})])
    client = FakeClient({"MPREb_1": _album("曲A / 曲B", ("曲A", "newA"), ("曲B", "newB"))}, dead={"deadA"})
    rel = ds.releases["p/r"]
    matches, ok = plan_release(client, ds, rel)
    assert ok
    out = apply_matches(client, rel, matches, "2026-10-17")
    assert (out.added, out.replaced) == (1, 1)
    assert rel.streaming[0].tracks == {"1-1": "newA", "1-2": "newB"} and rel.streaming[0].browse_id == "MPREb_1"


def test_quotes_dots_and_soundtrack_notes():
    # the official lists print curly quotes and ・・・; YouTube Music straight quotes, … and the soundtrack's note
    rows = ["KOKORO Magic “A to Z”", "僕らの走ってきた道は・・・", "START:DASH!!"]
    album = ['KOKORO Magic "A to Z" (国木田花丸 Solo Ver.)', "僕らの走ってきた道は… (黒澤ルビィ Solo Ver.)", "START:DASH!! [第13話挿入歌]"]
    assert align(album, rows) == [(0, 0), (1, 1), (2, 2)]


def test_albums_of_the_same_songs_are_told_apart_by_title():
    # 永久hours Solo Concert starring …: every member's album has the same songs
    ds = _ds()
    rel = ds.releases["p/r"]
    rel.title = _names("Solo Concert starring A")
    client = FakeClient({"MPREb_b": _album("Solo Concert starring B", ("曲A", "bA"), ("曲B", "bB")),
                         "MPREb_a": _album("Solo Concert starring A", ("曲A", "aA"), ("曲B", "aB"))})
    matches, ok = plan_release(client, ds, rel)
    assert ok and matches[0].chosen.browse_id == "MPREb_a"


def test_a_reissue_has_no_album_of_its_own():
    # μ's 2024 L-jacket reissues: the same recordings, the album is the 2010 single's; the reissue takes its main URL
    import datetime as dt
    ds = _ds()
    old = ds.releases["p/r"]
    old.release_date = dt.date(2010, 1, 1)
    new = old.model_copy(update={"id": "p/r2", "release_date": dt.date(2024, 3, 27)}, deep=True)
    ds.releases["p/r2"] = new
    client = FakeClient({"MPREb_1": _album("曲A / 曲B", ("曲A", "vA"), ("曲B", "vB"))})
    claimed: dict[str, str] = {}
    for rel in (old, new):  # oldest first, as the command runs
        matches, ok = plan_release(client, ds, rel, claimed)
        assert ok
        apply_matches(client, rel, matches, "2026-10-21")
    assert old.streaming[0].browse_id == "MPREb_1" and new.streaming == []
    assert matches[0].reason == "reissue of p/r"
    # a reissue that took the album in an earlier run gives it up
    new.streaming = [m.Streaming(browse_id="MPREb_1", tracks={"1-1": "vA", "1-2": "vB"})]
    matches, ok = plan_release(client, ds, new)
    apply_matches(client, new, matches, "2026-10-21")
    assert ok and new.streaming == []


def test_live_stored_id_is_kept():
    ds = _ds(streaming=[m.Streaming(tracks={"1-1": "liveA"})])
    client = FakeClient({"MPREb_1": _album("曲A / 曲B", ("曲A", "newA"), ("曲B", "newB"))})
    rel = ds.releases["p/r"]
    out = apply_matches(client, rel, plan_release(client, ds, rel)[0], "2026-10-17")
    assert rel.streaming[0].tracks["1-1"] == "liveA" and out.kept_live
    assert review_doc(rel, [], out.kept_live)["type"] == "ytm-change"


def test_edition_labels_and_siblings():
    eds = [m.Edition(id="e1", label=_names("上原歩夢盤")), m.Edition(id="e2", label=_names("中須かすみ盤"))]
    ds = _ds(editions=eds)
    # only the second edition is on YouTube Music: the first must not take an album named after the second
    client = FakeClient({"MPREb_k": _album("曲A / 曲B【中須かすみ盤】", ("曲A", "kA"), ("曲B", "kB"))})
    rel = ds.releases["p/r"]
    matches, ok = plan_release(client, ds, rel)
    assert ok and matches[0].chosen is None and matches[0].reason == "sibling" and matches[1].chosen
    apply_matches(client, rel, matches, "2026-10-17")
    assert [(s.editions, s.browse_id) for s in rel.streaming] == [(["e2"], "MPREb_k")]


def test_ambiguous_release_goes_to_review_and_applies_offline():
    ds = _ds()
    client = FakeClient({"MPREb_1": _album("x", ("曲A", "1A"), ("曲B", "1B")), "MPREb_2": _album("y", ("曲A", "2A"), ("曲B", "2B"))})
    rel = ds.releases["p/r"]
    matches, ok = plan_release(client, ds, rel)
    assert not ok
    doc = review_doc(rel, matches)
    pick = next(c["n"] for c in doc["items"][0]["candidates"] if c["browse_id"] == "MPREb_2")
    rid, picked = matches_from_review(doc, f"pick:{pick}")
    apply_matches(None, ds.releases[rid], picked, "2026-10-17")
    assert rel.streaming[0].tracks == {"1-1": "2A", "1-2": "2B"}


def test_one_song_single_is_not_the_cd():
    ds = _ds()
    client = FakeClient({"MPREb_s": _album("曲A", ("曲A", "sA"))})  # every album track is in the release, but 曲B is missing
    matches, ok = plan_release(client, ds, ds.releases["p/r"])
    assert not ok and matches[0].chosen is None


def test_album_labelled_for_another_edition_is_refused_even_alone():
    ds = _ds(editions=[m.Edition(id="e1", label=_names("虹ヶ咲学園スクールアイドル同好会盤"))])
    client = FakeClient({"MPREb_l": _album("曲A / 曲B【Liella!盤】", ("曲A", "lA"), ("曲B", "lB"))})
    matches, ok = plan_release(client, ds, ds.releases["p/r"])
    assert not ok and matches[0].chosen is None
