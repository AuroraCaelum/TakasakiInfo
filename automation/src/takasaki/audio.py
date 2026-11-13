"""Length, key, tempo and mood of recordings (DESIGN.md D61).

- **Length** (`Recording.duration`): the label's own distribution metadata. First the YouTube Music albums
  already matched to releases (``.cache/ytm/album/``, no network); for a recording none of them has, the
  release's album on iTunes (Apple Music) and Deezer. Values within ``TOLERANCE`` seconds of each other are
  one value (the earliest release's is kept); a wider spread goes to a ``duration`` review item.
- **Key and tempo** (`Recording.audio`): GetSongBPM's API (free with a link back, which the README carries).
  Only a single unambiguous match is written; anything else goes to an ``audio`` review item.
- **Mood** is not stored: the builders make it from the stored analysis by the rules in ``MOODS``.

An off vocal or instrumental takes the key and tempo of the vocal recording it is the instrumental of; its
length is its own. A work is shown with the values of its representative recording.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
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
NOTE_AUDIO = "공식 미게재. GetSongBPM 분석값(D61)"


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
                if e.code == 404:
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


# --- key and tempo (GetSongBPM) -------------------------------------------------

GSB_API = "https://api.getsong.co/"
GSB_KEY_ENV = "TAKASAKI_GETSONGBPM_KEY"


def gsb_key(root: Path) -> str | None:
    """The API key: $TAKASAKI_GETSONGBPM_KEY, or automation/getsongbpm.key (not in git)."""
    if os.environ.get(GSB_KEY_ENV):
        return os.environ[GSB_KEY_ENV].strip()
    p = root / "automation" / "getsongbpm.key"
    return p.read_text(encoding="utf-8").strip() if p.exists() else None


_KEY_SIGNS = str.maketrans({"♯": "#", "♭": "b"})


def parse_key(v: Any) -> str | None:
    """GetSongBPM's `key_of` (`Em`, `F♯m`, `B♭`) as a model key; None when it is not one."""
    if not isinstance(v, str):
        return None
    k = v.strip().translate(_KEY_SIGNS).replace(" ", "")
    k = k.removesuffix("maj").removesuffix("major")
    if k.endswith("minor"):
        k = k.removesuffix("minor") + "m"
    return k if re.fullmatch(r"[A-G](#|b)?m?", k) else None


def _int(v: Any) -> int | None:
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return None
    return n


def parse_audio(song: dict[str, Any]) -> m.Audio | None:
    bpm = _int(song.get("tempo"))
    ts = song.get("time_sig") if isinstance(song.get("time_sig"), str) and "/" in song.get("time_sig", "") else None
    a = m.Audio(key=parse_key(song.get("key_of")), bpm=bpm if bpm and bpm > 0 else None, time_signature=ts)
    return a if (a.key or a.bpm) else None


class GetSongBPM:
    def __init__(self, api_key: str, cache_dir: Path, offline: bool = False) -> None:
        self.api_key = api_key
        self.http = Http(cache_dir, pause=1.0, offline=offline)

    def search(self, title: str, artist: str | None) -> list[dict[str, Any]]:
        lookup = f"song:{title}" + (f" artist:{artist}" if artist else "")
        kind = "both" if artist else "song"
        params = {"type": kind, "lookup": lookup, "limit": 50}
        res = self.http.get(GSB_API + "search/?" + urllib.parse.urlencode(params), headers={"X-API-KEY": self.api_key},
                            cache_key=f"search:{kind}:{lookup}")
        hits = (res or {}).get("search")
        return hits if isinstance(hits, list) else []  # "no result" comes back as {"error": ...}

    def song(self, song_id: str) -> dict[str, Any] | None:
        res = self.http.get(GSB_API + "song/?" + urllib.parse.urlencode({"id": song_id}), headers={"X-API-KEY": self.api_key},
                            cache_key=f"song:{song_id}")
        s = (res or {}).get("song")
        return s if isinstance(s, dict) else None


def _performer_names(ds: Dataset, rec: m.Recording) -> list[str]:
    out = []
    for p in rec.performers:
        kind, ident = p.ref
        ent = ds.table(kind)[ident]
        out += [x for x in (ent.names.ja, ent.names.rom) if x]
        if p.role:
            c = ds.characters[p.role]
            out += [x for x in (c.names.ja, c.names.rom) if x]
    return out


def _artist_ok(ds: Dataset, work: m.Work, rec: m.Recording, rels: list[m.Release], artist: str) -> bool:
    """The hit's artist is one of the recording's singers (or the release's credited artist): a singer's name
    appears in it, so `高海千歌 (CV.伊波杏樹)` and `Aqours` both pass."""
    a = match_key(artist, person=True)
    names = _performer_names(ds, rec)
    for rel in rels:
        for p in rel.artist_credit:
            kind, ident = p.ref
            ent = ds.table(kind)[ident]
            names += [x for x in (ent.names.ja, ent.names.rom) if x]
    if work.kind == "bgm":  # a soundtrack is credited to its composer
        for c in work.credits.composer:
            ent = ds.table(c.ref[0])[c.ref[1]]
            names += [x for x in (ent.names.ja, ent.names.rom) if x]
    keys = {match_key(n, person=True) for n in names}
    return any(k and (k in a or a in k) for k in keys)


def _search_artists(ds: Dataset, rec: m.Recording, rels: list[m.Release]) -> list[str | None]:
    """Artist names to search with, most specific first; None searches by title alone."""
    out: list[str | None] = []
    for p in rec.performers:
        ent = ds.table(p.ref[0])[p.ref[1]]
        if ent.names.ja:
            out.append(ent.names.ja)
    for rel in rels:
        for p in rel.artist_credit:
            ent = ds.table(p.ref[0])[p.ref[1]]
            if ent.names.ja:
                out.append(ent.names.ja)
    out.append(None)
    return list(dict.fromkeys(out))


@dataclass
class AudioMatch:
    rid: str
    audio: m.Audio | None = None
    url: str | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""


def match_audio(client: GetSongBPM, ds: Dataset, work: m.Work, rec: m.Recording) -> AudioMatch:
    """A hit whose title is the recording's (printed with its version) and whose artist is one of its singers.
    A live recording, and a cue, must also be on an album named like a release it is on. Hits with the same
    values are one; different values go to review."""
    rid = _rid(work, rec)
    rels = sorted({o[0].id: o[0] for o in _occurrences(ds) if o[4].recording == rid}.values(),
                  key=lambda r: (r.release_date or dt.date.max, r.id))
    title = (rec.title or work.title)
    titles = {match_key(x) for x in (title.ja, title.rom) if x}
    album_keys = {_album_key(r.title.ja) for r in rels if r.title.ja} | {_album_key(r.title.rom) for r in rels if r.title.rom}
    need_album = bool(rec.live) or work.kind == "bgm"
    hits: dict[str, dict[str, Any]] = {}
    for artist in _search_artists(ds, rec, rels):
        for h in client.search(title.ja or title.rom or "", artist):
            if match_key(h.get("title", "")) not in titles:
                continue
            if not _artist_ok(ds, work, rec, rels, (h.get("artist") or {}).get("name", "")):
                continue
            if need_album and _album_key((h.get("album") or {}).get("title", "")) not in album_keys:
                continue
            hits[str(h.get("id"))] = h
        if hits:
            break
    if not hits:
        return AudioMatch(rid, reason="no hit")
    found: list[tuple[m.Audio, dict[str, Any]]] = []
    for sid, h in hits.items():
        song = h if h.get("tempo") is not None else (client.song(sid) or h)
        a = parse_audio(song)
        if a is not None:
            found.append((a, song))
    cands = [{"n": i, "url": s.get("uri"), "artist": (s.get("artist") or {}).get("name"),
              "album": (s.get("album") or {}).get("title"), **a.model_dump(exclude_none=True)}
             for i, (a, s) in enumerate(found, 1)]
    distinct = {a.model_dump_json() for a, _ in found}
    if len(distinct) == 1:
        a, s = found[0]
        return AudioMatch(rid, a, s.get("uri"), cands)
    return AudioMatch(rid, candidates=cands, reason="hits differ" if found else "hits without key or tempo")


def apply_audio(ds: Dataset, rid: str, a: m.Audio, url: str | None, today: dt.date, note: str = NOTE_AUDIO) -> None:
    _, rec = ds.recording(rid)
    rec.audio = a
    rec.evidence["audio"] = m.Evidence(status=m.Status.established, source=url, checked=today, note=note)


def search_links(title: str, artist: str | None) -> dict[str, str]:
    """Pages a person can check a key or tempo against (opened by hand; their sites are not crawled)."""
    q = urllib.parse.quote(f"{title} {artist or ''}".strip())
    return {"getsongbpm": f"https://getsongbpm.com/search?search={q}",
            "keytube": f"https://keytube.net/search?q={urllib.parse.quote(title)}",
            "chordwiki": f"https://ja.chordwiki.org/search.html?t={urllib.parse.quote(title)}"}


def audio_review(ds: Dataset, mt: AudioMatch) -> dict[str, Any]:
    work, rec = ds.recording(mt.rid)
    title = (rec.title or work.title).ja or ""
    artist = _search_artists(ds, rec, [])[0]
    return {
        "type": "audio",
        "ref": f"recording:{mt.rid}",
        "title": title,
        "reason": f"GetSongBPM 결과가 여럿이고 값이 다르다({mt.reason}). 맞는 것을 `pick:<n>`, 없으면 `none`",
        "check": search_links(title, artist),
        "candidates": mt.candidates,
        "decision": None,
    }


def apply_audio_review(ds: Dataset, doc: dict[str, Any], decision: str, today: dt.date) -> str:
    rid = str(doc["ref"]).removeprefix("recording:")
    if decision == "none":
        return f"left {rid} without key and tempo"
    n = int(decision.removeprefix("pick:"))
    item = dict(next(c for c in doc["candidates"] if int(c["n"]) == n))
    url = item.pop("url", None)
    for k in ("n", "artist", "album"):
        item.pop(k, None)
    apply_audio(ds, rid, m.Audio.model_validate(item), url, today, NOTE_AUDIO + "; 리뷰에서 고름")
    return f"set {rid} key/tempo"


def tempo_checks(ds: Dataset) -> list[dict[str, Any]]:
    """Recordings of one work whose tempo or key disagree although they share the arrangement (a member's
    version, a re-recording by another generation): the analysis may have read one at half or double time.
    One item per work, for a person to check by ear or against the pages in `check`."""
    out = []
    for w in sorted(ds.works.values(), key=lambda w: w.id):
        groups: dict[tuple[str, ...], list[m.Recording]] = {}
        for r in w.recordings:
            if r.audio and r.audio.bpm and not r.live and r.kind == "vocal":
                groups.setdefault(tuple(sorted(str(c.ref) for c in r.arranger)), []).append(r)
        for recs in groups.values():
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
