"""Length, key, tempo and mood of recordings (DESIGN.md D61).

- **Length** (`Recording.duration`): the label's own distribution metadata. First the YouTube Music albums
  already matched to releases (``.cache/ytm/album/``, no network); for a recording none of them has, the
  release's album on iTunes (Apple Music) and Deezer. Values within ``TOLERANCE`` seconds of each other are
  one value (the earliest release's is kept); a wider spread goes to a ``duration`` review item.
- **Key and tempo** (`Recording.audio`): ReccoBeats' free API. A recording is matched to Spotify tracks
  through its singers' track lists (title, version, length); agreeing tracks give the value, disagreeing ones
  go to an ``audio`` review item. Time signature has no source and stays empty.
- **Mood** is not stored: the builders make it from the stored analysis by the rules in ``MOODS``.

An off vocal or instrumental takes the key and tempo of the vocal recording it is the instrumental of; its
length is its own. A work is shown with the values of its representative recording.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import model as m
from .build_legacy import edition_ids, edition_tracks, own_video, track_title
from .store import Dataset
from .text import match_key

TOLERANCE = 2  # seconds: the same master as distributed on different albums or services
YTM_ALBUM = "https://music.youtube.com/browse/"
NOTE_DURATION = "레이블 배포 메타데이터의 재생 시간(D61)"
NOTE_AUDIO = "공식 미게재. ReccoBeats 분석값(Spotify 트랙으로 맞춤, D61)"


# --- scope, inheritance, representative ---------------------------------------


def in_scope(work: m.Work, rec: m.Recording) -> bool:
    """Songs and soundtrack cues; not drama tracks (D61)."""
    return work.kind in ("song", "bgm") and rec.kind in ("vocal", "off_vocal", "instrumental")


def wants_audio(work: m.Work, rec: m.Recording) -> bool:
    """A recording that gets its own key and tempo: not one that takes them from its vocal recording."""
    return in_scope(work, rec) and not rec.instrumental_of


def effective_audio(work: m.Work, rec: m.Recording) -> tuple[m.Audio | None, m.Recording]:
    """The recording's key and tempo, and the recording they belong to: its own, or for an off vocal or
    instrumental without its own, those of `instrumental_of`."""
    if rec.audio is None and rec.instrumental_of:
        src = next((r for r in work.recordings if r.id == rec.instrumental_of), None)
        if src is not None and src.audio is not None:
            return src.audio, src
    return rec.audio, rec


def representative(work: m.Work) -> m.Recording | None:
    """The recording a work is shown with: the first studio vocal recording, for a cue the first instrumental."""
    order = ("instrumental", "vocal") if work.kind == "bgm" else ("vocal", "instrumental")
    for kind in order:
        for r in work.recordings:
            if r.kind == kind and not r.live:
                return r
    return work.recordings[0] if work.recordings else None


# --- mood ----------------------------------------------------------------------

# label -> (names, rule). Rules read the stored analysis only; a value the source lacks makes no label (D61).
MOODS: dict[str, tuple[m.Names, Callable[[m.Audio], bool]]] = {
    "upbeat": (m.Names(ja="アップテンポ", rom="Upbeat", ko="경쾌한"), lambda a: a.bpm is not None and a.bpm >= 140),
    "slow": (m.Names(ja="スロー", rom="Slow", ko="느린"), lambda a: a.bpm is not None and a.bpm < 100),
    "bright": (m.Names(ja="明るい", rom="Bright", ko="밝은"), lambda a: a.key is not None and not a.key.endswith("m")),
    "wistful": (m.Names(ja="切ない", rom="Wistful", ko="애틋한"), lambda a: a.key is not None and a.key.endswith("m")),
}


# the rules in words, for the README (a test keeps the keys equal to MOODS')
MOOD_RULES = {
    "upbeat": "`bpm` 140 or more",
    "slow": "`bpm` under 100",
    "bright": "a major key",
    "wistful": "a minor key",
}


def moods(a: m.Audio | None) -> list[str]:
    return [k for k, (_, rule) in MOODS.items() if a is not None and rule(a)]


# --- fetching ------------------------------------------------------------------


class Http:
    """GET JSON with a file cache under ``.cache/<name>/`` and a pause between network requests."""

    def __init__(self, cache_dir: Path, pause: float, offline: bool = False) -> None:
        self.cache_dir, self.pause, self.offline = cache_dir, pause, offline
        self._last = 0.0

    def get(self, url: str, headers: dict[str, str] | None = None, cache_key: str | None = None) -> Any:
        path = self.cache_dir / (hashlib.sha1((cache_key or url).encode()).hexdigest() + ".json")
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        if self.offline:
            return None
        wait = self.pause - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url, headers={"User-Agent": "TakasakiInfo-data/1.0", **(headers or {})})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                if e.code in (403, 429, 500, 502, 503) and attempt < 3:
                    time.sleep(2 ** (attempt + 2))
                    continue
                if e.code in (400, 404):  # not found, or a query the service cannot take: no result
                    data = None
                    break
                raise
            except (urllib.error.URLError, TimeoutError):
                if attempt == 3:
                    raise
                time.sleep(2 ** (attempt + 1))
        self._last = time.monotonic()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8", newline="\n")
        return data


# --- length --------------------------------------------------------------------


@dataclass
class Candidate:
    seconds: int
    source: str  # youtube_music, itunes, deezer
    url: str
    release: str
    day: str  # release date of the edition, for picking the earliest

    def as_item(self) -> dict[str, Any]:
        return {"seconds": self.seconds, "length": f"{self.seconds // 60}:{self.seconds % 60:02d}", "source": self.source,
                "url": self.url, "release": self.release}


def _rid(work: m.Work, rec: m.Recording) -> str:
    return f"{work.id}#{rec.id}"


def _occurrences(ds: Dataset) -> list[tuple[m.Release, str | None, int, int, m.Track, str]]:
    """Every (release, edition, disc, position, track, day) of a released release."""
    out = []
    for rel in ds.releases.values():
        if rel.status == "announced":
            continue
        for ed in edition_ids(rel):
            ed_date = next((e.release_date for e in rel.editions if e.id == ed and e.release_date), None)
            day = ed_date or rel.release_date
            for disc, pos, t in edition_tracks(rel, ed):
                out.append((rel, ed, disc, pos, t, day.isoformat() if day else "9999-12-31"))
    return out


def ytm_durations(ds: Dataset, ytm_cache: Path) -> dict[str, list[Candidate]]:
    """Durations of the tracks' own YouTube Music videos, from the cached albums of the releases' streaming entries."""
    by_vid: dict[str, tuple[int, str]] = {}
    for rel in ds.releases.values():
        for s in rel.streaming:
            if not s.browse_id:
                continue
            p = ytm_cache / "album" / (hashlib.sha1(s.browse_id.encode()).hexdigest() + ".json")
            if not p.exists():
                continue
            for t in json.loads(p.read_text(encoding="utf-8")).get("tracks", []):
                if t.get("video_id") and t.get("duration"):
                    by_vid[t["video_id"]] = (int(t["duration"]), s.browse_id)
    out: dict[str, list[Candidate]] = {}
    for rel, ed, disc, pos, t, day in _occurrences(ds):
        vid = own_video(rel, ed, disc, pos)
        if vid and vid in by_vid:
            sec, browse = by_vid[vid]
            c = Candidate(sec, "youtube_music", YTM_ALBUM + browse, rel.id, day)
            if not any(x.url == c.url and x.seconds == sec for x in out.get(t.recording, [])):
                out.setdefault(t.recording, []).append(c)
    return out


def _album_key(title: str) -> str:
    """An album title as the stores print it, without their " - EP" / " - Single" suffix."""
    for suffix in (" - EP", " - Single", " - Album"):
        title = title.removesuffix(suffix)
    title = re.sub(r"\s*【[^【】]*盤】\s*$", "", title)  # an edition's album (`【第3話盤】`): its tracks are matched by title
    return match_key(title)


def _titles(ds: Dataset, t: m.Track) -> set[str]:
    work, rec = ds.recording(t.recording)
    printed, _ = track_title(work, rec, t)
    base = rec.title or work.title
    return {match_key(x) for x in (printed.ja, printed.rom, base.ja, base.rom) if x}


def itunes_durations(http: Http, ds: Dataset, rel: m.Release, wanted: set[str]) -> dict[str, Candidate]:
    """The release's album in the Japanese iTunes Store, its tracks matched by title."""
    if not rel.title.ja:
        return {}
    res = http.get("https://itunes.apple.com/search?" + urllib.parse.urlencode(
        {"country": "JP", "entity": "album", "limit": 25, "term": rel.title.ja}))
    albums = [a for a in (res or {}).get("results", []) if _album_key(a.get("collectionName", "")) == match_key(rel.title.ja)]
    if rel.release_date and len(albums) > 1:
        same_day = [a for a in albums if a.get("releaseDate", "")[:10] == rel.release_date.isoformat()]
        albums = same_day or albums
    out: dict[str, Candidate] = {}
    day = rel.release_date.isoformat() if rel.release_date else "9999-12-31"
    for a in albums[:3]:
        look = http.get(f"https://itunes.apple.com/lookup?id={a['collectionId']}&entity=song&country=JP")
        tracks = [x for x in (look or {}).get("results", []) if x.get("wrapperType") == "track" and x.get("trackTimeMillis")]
        names: dict[str, list[dict[str, Any]]] = {}
        for x in tracks:
            names.setdefault(match_key(x["trackName"]), []).append(x)
        for d in rel.discs:
            for t in d.tracks:
                if t.recording not in wanted or t.recording in out:
                    continue
                hits = [x for k in _titles(ds, t) for x in names.get(k, [])]
                if len({x["trackId"] for x in hits}) == 1:
                    out[t.recording] = Candidate(round(hits[0]["trackTimeMillis"] / 1000), "itunes",
                                                 a.get("collectionViewUrl", "").split("?")[0], rel.id, day)
    return out


def deezer_durations(http: Http, ds: Dataset, rel: m.Release, wanted: set[str]) -> dict[str, Candidate]:
    """The release's album on Deezer: same release date and track count, tracks matched by position and title.
    Deezer often prints Japanese titles romanized, so the title check takes ja or rom."""
    if not rel.release_date:
        return {}
    out: dict[str, Candidate] = {}
    queries = [q for q in (rel.title.ja, rel.title.rom) if q]
    seen: set[int] = set()
    for q in queries:
        res = http.get("https://api.deezer.com/search/album?" + urllib.parse.urlencode({"q": q, "limit": 25}))
        for a in (res or {}).get("data", []):
            if a["id"] in seen:
                continue
            seen.add(a["id"])
            alb = http.get(f"https://api.deezer.com/album/{a['id']}")
            if not alb or alb.get("release_date") != rel.release_date.isoformat():
                continue
            dz = (alb.get("tracks") or {}).get("data", [])
            for ed in edition_ids(rel):
                ours = edition_tracks(rel, ed)
                if len(ours) != len(dz):
                    continue
                for (_, _, t), x in zip(ours, dz):
                    if t.recording in wanted and t.recording not in out and match_key(x.get("title", "")) in _titles(ds, t):
                        out[t.recording] = Candidate(int(x["duration"]), "deezer", alb.get("link", ""), rel.id,
                                                     rel.release_date.isoformat())
    return out


@dataclass
class DurationPlan:
    values: dict[str, Candidate] = field(default_factory=dict)  # recording -> chosen candidate
    conflicts: dict[str, list[Candidate]] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)


def decide(cands: list[Candidate]) -> Candidate | None:
    """One value when every candidate is within TOLERANCE: YouTube Music first, then iTunes, then Deezer, each
    the earliest release's. None when they spread wider."""
    if not cands:
        return None
    secs = [c.seconds for c in cands]
    if max(secs) - min(secs) > TOLERANCE:
        return None
    rank = {"youtube_music": 0, "itunes": 1, "deezer": 2}
    return min(cands, key=lambda c: (rank[c.source], c.day, c.release))


def plan_durations(ds: Dataset, ytm_cache: Path, shops: tuple[Http, Http] | None, log: Callable[[str], None] = print,
                   only: set[str] | None = None) -> DurationPlan:
    """Choose a length for every recording in scope that has none. ``shops`` (iTunes, Deezer clients) are asked
    only about recordings no YouTube Music album has; without them those recordings stay missing."""
    targets = {_rid(w, r) for w in ds.works.values() for r in w.recordings
               if in_scope(w, r) and r.duration is None and (only is None or _rid(w, r) in only)}
    ytm = ytm_durations(ds, ytm_cache)
    cands: dict[str, list[Candidate]] = {rid: list(ytm[rid]) for rid in targets if rid in ytm}
    rest = targets - set(cands)
    if shops and rest:
        itunes, deezer = shops
        rels = sorted({rel.id for rel, *_ in [o for o in _occurrences(ds) if o[4].recording in rest]})
        for i, rid in enumerate(rels, 1):
            rel = ds.releases[rid]
            wanted = {t.recording for d in rel.discs for t in d.tracks} & rest
            found = itunes_durations(itunes, ds, rel, wanted)
            found_dz = deezer_durations(deezer, ds, rel, wanted)
            for rec_id, c in list(found.items()) + list(found_dz.items()):
                cands.setdefault(rec_id, []).append(c)
            log(f"  [{i}/{len(rels)}] {rid}: iTunes {len(found)}, Deezer {len(found_dz)} of {len(wanted)}")
    plan = DurationPlan()
    for rid in sorted(targets):
        cs = cands.get(rid, [])
        chosen = decide(cs)
        if chosen:
            plan.values[rid] = chosen
        elif cs:
            plan.conflicts[rid] = cs
        else:
            plan.missing.append(rid)
    return plan


def apply_duration(ds: Dataset, rid: str, c: Candidate, today: dt.date, note: str = NOTE_DURATION) -> None:
    _, rec = ds.recording(rid)
    rec.duration = c.seconds
    rec.evidence["duration"] = m.Evidence(status=m.Status.official, source=c.url, checked=today, note=note)


def duration_review(ds: Dataset, rid: str, cands: list[Candidate]) -> dict[str, Any]:
    work, rec = ds.recording(rid)
    title = (rec.title or work.title).ja
    return {
        "type": "duration",
        "ref": f"recording:{rid}",
        "title": title,
        "reason": f"앨범·서비스마다 재생 시간이 {TOLERANCE}초 넘게 다르다. 같은 음원이면 `pick:<n>`(대표 발매물의 값), "
                  "다른 음원이 하나로 묶였거나 videoId가 잘못 붙었으면 data/를 고친 뒤 `done`",
        "candidates": [c.as_item() | {"n": i} for i, c in enumerate(sorted(cands, key=lambda c: (c.day, c.release)), 1)],
        "decision": None,
    }


def apply_duration_review(ds: Dataset, doc: dict[str, Any], decision: str, today: dt.date) -> str:
    rid = str(doc["ref"]).removeprefix("recording:")
    if decision == "none":
        return f"left {rid} without a length"
    n = int(decision.removeprefix("pick:"))
    item = next(c for c in doc["candidates"] if int(c["n"]) == n)
    c = Candidate(int(item["seconds"]), item["source"], item["url"], item["release"], "")
    apply_duration(ds, rid, c, today, NOTE_DURATION + f"; 리뷰에서 {item['release']}의 값을 고름")
    return f"set {rid} duration {c.seconds}s"


# --- key and tempo (ReccoBeats) --------------------------------------------------

RB_API = "https://api.reccobeats.com/v1/"
NOTES = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")  # pitch class -> tonic, as keys are usually written


def feature_audio(f: dict[str, Any]) -> m.Audio | None:
    """ReccoBeats' audio features (`key` a pitch class or -1, `mode` 1 major / 0 minor, `tempo`) as the model's."""
    key = f.get("key")
    tonic = NOTES[key] + ("" if f.get("mode") == 1 else "m") if isinstance(key, int) and 0 <= key < 12 else None
    tempo = f.get("tempo")
    bpm = round(tempo) if isinstance(tempo, (int, float)) and tempo > 0 else None
    return m.Audio(key=tonic, bpm=bpm) if (tonic or bpm) else None


class ReccoBeats:
    """ReccoBeats' free API (no key; free for personal and commercial use, not to be overloaded). Its track
    metadata is Spotify's; the analysis is its own. Responses are cached under ``.cache/reccobeats/``."""

    def __init__(self, cache_dir: Path, offline: bool = False) -> None:
        self.http = Http(cache_dir, pause=0.5, offline=offline)

    def _get(self, path: str, **q: Any) -> Any:
        return self.http.get(RB_API + path + ("?" + urllib.parse.urlencode(q, doseq=True) if q else ""))

    def artists(self, name: str) -> list[dict[str, Any]]:
        return (self._get("artist/search", searchText=name, size=50) or {}).get("content", [])

    def artist_tracks(self, artist_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        page = 0
        while True:
            res = self._get(f"artist/{artist_id}/track", size=50, page=page) or {}
            out += res.get("content", [])
            page += 1
            if page >= int(res.get("totalPages") or 0) or page >= 40:
                return out

    def features(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for i in range(0, len(ids), 40):
            for f in (self._get("audio-features", ids=sorted(ids[i:i + 40])) or {}).get("content", []):
                out[f["id"]] = f
        return out


def _singers(ds: Dataset, rec: m.Recording) -> list[tuple[str, list[str]]]:
    """Each singer of the recording as (ref, its names): a character sung by a cast member counts as the character."""
    out = []
    for p in rec.performers:
        kind, ident = ("character", p.role) if p.role else p.ref
        ent = ds.table(kind)[ident]
        out.append((f"{kind}:{ident}", [x for x in (ent.names.ja, ent.names.rom) if x]))
    return out


def _performer_names(ds: Dataset, rec: m.Recording) -> list[str]:
    return [n for _, names in _singers(ds, rec) for n in names]


def _contains_name(artists: str, names: list[str]) -> bool:
    keys = {match_key(n, person=True) for n in names} - {""}
    return any(k in artists for k in keys)


def _split_title(title: str) -> tuple[str, str]:
    """A Spotify title as (base, version): `X - 松浦果南 Solo Ver.`, `X (TV size)`."""
    base, sep, suffix = title.partition(" - ")
    if not sep:
        from .text import split_version

        base, ver = split_version(title)
        return base, ver or ""
    return base, suffix


def track_matches(ds: Dataset, work: m.Work, rec: m.Recording, t: dict[str, Any]) -> bool:
    """A Spotify track (as ReccoBeats lists it) is this recording: every singer is credited, the title is the
    work's (or the recording's own), and the length is within TOLERANCE when the recording has one. A group's
    recording without a version takes no track with a version, so a member's solo version of it is not taken."""
    artists = " ".join(match_key(a.get("name", ""), person=True) for a in t.get("artists", []))
    singers = _singers(ds, rec)
    if not singers or not all(_contains_name(artists, names) for _, names in singers):
        return False
    title = t.get("trackTitle") or ""
    base, version = _split_title(title)
    works = {match_key(x) for x in (work.title.ja, work.title.rom) if x}
    own = {match_key(x) for x in ((rec.title.ja, rec.title.rom) if rec.title else ()) if x}
    if match_key(title) not in own and match_key(base) not in works:
        return False
    plain = rec.version is None and rec.title is None
    if version and plain and all(ref.startswith("artist:") for ref, _ in singers):
        return False
    if rec.duration and abs((t.get("durationMs") or 0) / 1000 - rec.duration) > TOLERANCE:
        return False
    return True


@dataclass
class AudioMatch:
    rid: str
    audio: m.Audio | None = None
    url: str | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""


def resolve_artists(client: ReccoBeats, ds: Dataset, singers: set[str], log: Callable[[str], None] = print) -> dict[str, set[str]]:
    """ReccoBeats artist ids for each singer ref: every artist whose name contains the singer's (a character's
    artist name carries its voice actor, `鐘 嵐珠 (CV.法元明菜)`, and duets list several characters)."""
    out: dict[str, set[str]] = {}
    for i, ref in enumerate(sorted(singers), 1):
        kind, ident = ref.split(":", 1)
        ent = ds.table(kind)[ident]
        names = [x for x in (ent.names.ja, ent.names.rom) if x]
        queries = list(dict.fromkeys(names + [n.replace(" ", "") for n in names]))
        ids: set[str] = set()
        for q in queries:
            for a in client.artists(q):
                if _contains_name(match_key(a.get("name", ""), person=True), names):
                    ids.add(a["id"])
        out[ref] = ids
        if i % 25 == 0:
            log(f"  artists {i}/{len(singers)}")
    return out


def agreeing(found: list[tuple[dict[str, Any], m.Audio]]) -> list[list[tuple[dict[str, Any], m.Audio]]]:
    """Tracks grouped by value (same key, tempo within 1), largest group first."""
    groups: list[list[tuple[dict[str, Any], m.Audio]]] = []
    for t, a in found:
        g = next((g for g in groups if g[0][1].key == a.key
                  and (g[0][1].bpm is None) == (a.bpm is None) and abs((g[0][1].bpm or 0) - (a.bpm or 0)) <= 1), None)
        if g is None:
            groups.append([(t, a)])
        else:
            g.append((t, a))
    return sorted(groups, key=len, reverse=True)


def plan_audio(client: ReccoBeats, ds: Dataset, targets: list[tuple[m.Work, m.Recording]],
               log: Callable[[str], None] = print) -> list[AudioMatch]:
    """Match each recording to Spotify tracks through its singers' track lists, then read their analysis.
    Tracks of one recording that agree (same key, tempo within 1) give its value; disagreeing ones go to review."""
    singers = {ref for _, r in targets for ref, _ in _singers(ds, r)}
    artist_ids = resolve_artists(client, ds, singers, log)
    tracks: dict[str, dict[str, Any]] = {}
    by_artist: dict[str, list[str]] = {}
    for i, aid in enumerate(sorted({a for ids in artist_ids.values() for a in ids}), 1):
        ts = client.artist_tracks(aid)
        by_artist[aid] = [t["id"] for t in ts]
        tracks.update({t["id"]: t for t in ts})
        if i % 50 == 0:
            log(f"  track lists {i}")
    matched: dict[str, list[str]] = {}
    for w, r in targets:
        pool = {tid for ref, _ in _singers(ds, r) for aid in artist_ids.get(ref, ()) for tid in by_artist.get(aid, [])}
        matched[_rid(w, r)] = sorted(tid for tid in pool if track_matches(ds, w, r, tracks[tid]))
    feats = client.features(sorted({t for ts in matched.values() for t in ts}))
    out = []
    for w, r in targets:
        rid = _rid(w, r)
        found = [(tracks[t], feature_audio(feats[t])) for t in matched[rid] if t in feats]
        found = [(t, a) for t, a in found if a is not None]
        if not matched[rid]:
            out.append(AudioMatch(rid, reason="no track"))
            continue
        if not found:
            out.append(AudioMatch(rid, reason="no analysis"))
            continue
        cands = [{"n": i, "url": t.get("href"), "title": t.get("trackTitle"),
                  "artist": ", ".join(a.get("name", "") for a in t.get("artists", [])),
                  "seconds": round((t.get("durationMs") or 0) / 1000), **a.model_dump(exclude_none=True)}
                 for i, (t, a) in enumerate(found, 1)]
        groups = agreeing(found)
        best = groups[0]
        # every track agrees; or, of three or more, more than half do (the rest another master or a misreading)
        if len(groups) == 1 or (len(found) >= 3 and 2 * len(best) > len(found)):
            t, a = best[0]
            out.append(AudioMatch(rid, a, RB_API + "audio-features?ids=" + t["id"], cands,
                                  reason="" if len(groups) == 1 else f"{len(best)}/{len(found)} tracks"))
        else:
            out.append(AudioMatch(rid, candidates=cands, reason="tracks differ"))
    return out


def apply_audio(ds: Dataset, rid: str, a: m.Audio, url: str | None, today: dt.date, note: str = NOTE_AUDIO) -> None:
    _, rec = ds.recording(rid)
    rec.audio = a
    rec.evidence["audio"] = m.Evidence(status=m.Status.established, source=url, checked=today, note=note)


def search_links(title: str, artist: str | None = None) -> dict[str, str]:
    """Pages a person can check a key or tempo against (opened by hand; their sites are not crawled)."""
    return {"keytube": f"https://keytube.net/search?q={urllib.parse.quote(title)}",
            "chordwiki": f"https://ja.chordwiki.org/search.html?t={urllib.parse.quote(title)}"}


def audio_review(ds: Dataset, mt: AudioMatch) -> dict[str, Any]:
    work, rec = ds.recording(mt.rid)
    title = (rec.title or work.title).ja or ""
    return {
        "type": "audio",
        "ref": f"recording:{mt.rid}",
        "title": title,
        "reason": "이 음원으로 맞춘 Spotify 트랙이 여럿이고 분석값이 다르다. 맞는 것을 `pick:<n>`, 판단할 수 없으면 `none`",
        "check": search_links(title),
        "candidates": mt.candidates,
        "decision": None,
    }


def apply_audio_review(ds: Dataset, doc: dict[str, Any], decision: str, today: dt.date) -> str:
    rid = str(doc["ref"]).removeprefix("recording:")
    if decision == "none":
        return f"left {rid} without key and tempo"
    n = int(decision.removeprefix("pick:"))
    item = next(c for c in doc["candidates"] if int(c["n"]) == n)
    a = m.Audio.model_validate({k: item[k] for k in ("key", "bpm", "time_signature") if k in item})
    url = str(item["url"]) if item.get("url") else None
    apply_audio(ds, rid, a, url, today, NOTE_AUDIO + "; 리뷰에서 고름")
    return f"set {rid} key/tempo"


def _arrangements(w: m.Work) -> list[list[m.Recording]]:
    """A work's studio vocal recordings with key and tempo, grouped by arranger: versions over one backing track."""
    groups: dict[tuple[str, ...], list[m.Recording]] = {}
    for r in w.recordings:
        if r.audio and r.audio.bpm and not r.live and r.kind == "vocal":
            groups.setdefault(tuple(sorted(str(c.ref) for c in r.arranger)), []).append(r)
    return list(groups.values())


def harmonize(ds: Dataset, today: dt.date) -> list[str]:
    """Versions over one backing track (a member's solo version, a TV size) share its key and tempo; the analysis
    of each mix can still read another key or half the tempo. Where two thirds or more of three or more versions
    agree, the others take that value (`derived`, the analysed value kept in the note). Returns what changed."""
    changed = []
    for w in sorted(ds.works.values(), key=lambda w: w.id):
        for recs in _arrangements(w):
            if len(recs) < 3:
                continue
            groups = agreeing([({}, r.audio) for r in recs if r.audio])
            best = groups[0][0][1]
            agree = [r for r in recs if r.audio and r.audio.key == best.key and abs((r.audio.bpm or 0) - (best.bpm or 0)) <= 1]
            if len(groups) == 1 or 3 * len(agree) < 2 * len(recs):
                continue
            for r in recs:
                if r in agree or r.audio is None:
                    continue
                was = r.audio
                ev = r.evidence.get("audio")
                r.audio = m.Audio(key=best.key, bpm=best.bpm, time_signature=was.time_signature)
                r.evidence["audio"] = m.Evidence(
                    status=m.Status.derived, source=ev.source if ev else None, checked=today,
                    note=f"같은 편곡 음원 {len(agree)}/{len(recs)}개의 값으로 맞춤. 이 음원의 분석값은 {was.key} {was.bpm} BPM(D61)")
                changed.append(f"{w.id}#{r.id}")
    return changed


def tempo_checks(ds: Dataset) -> list[dict[str, Any]]:
    """Recordings of one work whose tempo or key disagree although they share the arrangement (a member's
    version, a re-recording by another generation): the analysis may have read one at half or double time.
    One item per work, for a person to check by ear or against the pages in `check`."""
    out = []
    for w in sorted(ds.works.values(), key=lambda w: w.id):
        for recs in _arrangements(w):
            bpms = {r.audio.bpm for r in recs if r.audio and r.audio.bpm}
            keys = {r.audio.key for r in recs if r.audio and r.audio.key}
            if len(recs) > 1 and (max(bpms) - min(bpms) > TOLERANCE or len(keys) > 1):
                out.append({
                    "ref": f"work:{w.id}",
                    "title": w.title.ja,
                    "recordings": [{"recording": f"{w.id}#{r.id}", "version": r.version, "key": r.audio.key,
                                    "bpm": r.audio.bpm} for r in recs if r.audio],
                    "check": search_links(w.title.ja or "", None),
                })
    return out


def run_progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)
