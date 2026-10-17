"""YouTube Music adapter (DESIGN.md §6.1, §7.2): find the album of each release edition on YouTube
Music, line its tracks up with the release, and propose the tracks' own video ids.

ytmusicapi needs a logged-in session (``automation/browser.json``, made with ``ytmusicapi browser``):
without one, Lantis albums come back unplayable and without video ids. Responses are cached under
``automation/.cache/ytm/`` so a rerun costs nothing; playability is never cached.

Rules (§6.3, §7.5): a release edition is matched only when exactly one album has every one of its
tracks in the release, in order, by title. A dead stored id is replaced (L0); a live stored id that
differs is left alone and reported as a ``change`` review item. Anything else becomes a review item
that carries the candidates' track mappings, so applying a decision needs no network.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import model as m
from .build_legacy import edition_ids, edition_tracks
from .store import Dataset
from .text import match_key

AUTH_ENV = "TAKASAKI_YTM_AUTH"
SKIP_TYPES = ("bd_bonus",)  # bonus CDs are not distributed


def default_auth(automation_dir: Path) -> Path:
    return Path(os.environ.get(AUTH_ENV) or automation_dir / "browser.json")


class Client:
    def __init__(self, auth: Path, cache_dir: Path, pause: float = 0.3) -> None:
        from ytmusicapi import YTMusic

        if not auth.exists():
            raise FileNotFoundError(f"{auth}: make it with `ytmusicapi browser` (or set {AUTH_ENV})")
        self.yt = YTMusic(str(auth), language="ja", location="JP")  # album pages with Japanese titles
        self.search_yt = YTMusic(str(auth))  # search returns nothing in the ja/JP locale
        self.cache_dir = cache_dir
        self.pause = pause
        if not self.logged_in():
            raise RuntimeError(f"{auth}: the YouTube Music session is logged out (expired cookies). "
                               "Make a new one with `ytmusicapi browser`; without it albums come back without video ids")

    def logged_in(self) -> bool:
        r = self.yt._send_request("browse", {"browseId": "FEmusic_home"})
        params = {p["key"]: p["value"] for s in r.get("responseContext", {}).get("serviceTrackingParams", []) for p in s.get("params", [])}
        return params.get("logged_in") == "1"

    def _retry(self, call: Callable[[], Any], attempts: int = 4) -> Any:
        """Retry transient network errors with backoff (§7.2 ②)."""
        import requests

        for n in range(attempts):
            try:
                return call()
            except (requests.ConnectionError, requests.Timeout):
                if n == attempts - 1:
                    raise
                time.sleep(2 ** (n + 1))

    def _cached(self, kind: str, key: str, fetch: Callable[[], Any]) -> Any:
        path = self.cache_dir / kind / (hashlib.sha1(key.encode()).hexdigest() + ".json")
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        data = self._retry(fetch)
        time.sleep(self.pause)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    def album(self, browse_id: str) -> dict[str, Any]:
        def fetch() -> dict[str, Any]:
            try:
                a = self.yt.get_album(browse_id)
            except (KeyError, IndexError, TypeError) as e:  # the album page is gone or cannot be parsed
                print(f"warn: album {browse_id} could not be read: {str(e)[:80]}", file=sys.stderr)
                return {"browse_id": browse_id, "title": None, "artists": [], "year": None, "tracks": []}
            return {
                "browse_id": browse_id,
                "title": a.get("title"),
                "artists": [x["name"] for x in a.get("artists") or []],
                "year": a.get("year"),
                "tracks": [{"title": t["title"], "video_id": t.get("videoId"), "available": t.get("isAvailable"),
                            "duration": t.get("duration_seconds")} for t in a.get("tracks") or []],
            }

        return self._cached("album", browse_id, fetch)

    def search_albums(self, query: str) -> list[dict[str, Any]]:
        def fetch() -> list[dict[str, Any]]:
            return [{"browse_id": r["browseId"], "title": r.get("title"), "year": r.get("year"),
                     "artists": [x["name"] for x in r.get("artists") or []]}
                    for r in self.search_yt.search(query, filter="albums", limit=10) if r.get("browseId")]

        return self._cached("search", query, fetch)

    def artist_albums(self, names: m.Names) -> list[dict[str, Any]]:
        """Albums and singles on the artist's channel (§7.2 ①), found by searching the rom name."""
        query = names.rom or names.ja or ""

        def fetch() -> list[dict[str, Any]]:
            wanted = {_key(n) for n in (names.rom, names.ja) if n}
            hit = next((r for r in self.search_yt.search(query, filter="artists", limit=5)
                        if any(_key(r.get("artist", "")).startswith(w) for w in wanted)), None)
            if not hit:
                return []
            try:
                artist = self.search_yt.get_artist(hit["browseId"])
            except (KeyError, IndexError, TypeError) as e:  # ytmusicapi cannot parse some channel layouts
                print(f"warn: artist channel {hit['browseId']} ({query}) could not be read: {str(e)[:80]}", file=sys.stderr)
                return []
            out = []
            for section in ("albums", "singles"):
                sec = artist.get(section) or {}
                items = sec.get("results") or []
                if sec.get("browseId") and sec.get("params"):
                    items = self.search_yt.get_artist_albums(sec["browseId"], sec["params"], limit=None)
                out += [{"browse_id": r["browseId"], "title": r.get("title"), "year": r.get("year")} for r in items if r.get("browseId")]
            return out

        return self._cached("artist", query, fetch)

    def status(self, video_id: str) -> str:
        return self._retry(lambda: self.yt.get_song(video_id)).get("playabilityStatus", {}).get("status", "UNKNOWN")


# --- matching -----------------------------------------------------------------


def _key(title: str) -> str:
    return match_key(title)


def _row_title(ds: Dataset, track: m.Track) -> str:
    work, rec = ds.recording(track.recording)
    return ((track.title_as_printed or rec.title or work.title).ja) or ""


def _plain(s: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", s).casefold().split())


def _same_title(album_title: str, row_title: str) -> bool:
    """Equal match keys, or the album omits a bracketed version marker the release prints
    (``One More Sunshine Story`` vs ``One More Sunshine Story (Album Version)``)."""
    for a in (album_title, album_title.split(" - ")[0]):  # some locales append " - <romanized>"
        if _key(a) and _key(a) == _key(row_title):
            return True
        pa, pr = _plain(a), _plain(row_title)
        for short, long in ((pa, pr), (pr, pa)):  # either side may carry the marker (Memories / Memories (澁谷かのん Ver.))
            if short and (long.startswith(short + " (") or long.startswith(short + "(")):
                if not any(x in long[len(short):] for x in _OTHER_RECORDING):
                    return True
    return False


# markers that name a different recording, never one an album would leave out of the title
_OTHER_RECORDING = ("off vocal", "instrumental", "inst", "karaoke", "カラオケ", "オフボーカル")


def align(album_titles: list[str], row_titles: list[str]) -> list[tuple[int, int]]:
    """Pair album tracks with release rows in order by title; an album track may only match a later row.
    An exact title match is preferred over a version-marker match."""
    pairs, j = [], 0
    for i, title in enumerate(album_titles):
        exact = next((jj for jj in range(j, len(row_titles)) if _key(row_titles[jj]) in {_key(title), _key(title.split(" - ")[0])}), None)
        hit = exact if exact is not None else next((jj for jj in range(j, len(row_titles)) if _same_title(title, row_titles[jj])), None)
        if hit is not None:
            pairs.append((i, hit))
            j = hit + 1
    return pairs


@dataclass
class Candidate:
    browse_id: str
    title: str
    year: str | None
    matched: int
    album_tracks: int
    tracks: dict[str, str]  # "<disc>-<pos>" -> video id
    covers_vocals: bool = True  # every vocal row of the edition is on the album (a one-song digital single is not the CD)

    @property
    def complete(self) -> bool:
        return self.matched == self.album_tracks and self.matched > 0 and self.covers_vocals


@dataclass
class EditionMatch:
    release: str
    edition: str | None
    candidates: list[Candidate] = field(default_factory=list)
    chosen: Candidate | None = None
    reason: str = ""


def _queries(ds: Dataset, rel: m.Release, edition: str | None) -> list[str]:
    performers = list(rel.artist_credit)
    if not performers and rel.discs and rel.discs[0].tracks:
        performers = ds.recording(rel.discs[0].tracks[0].recording)[1].performers[:1]
    names = []
    for p in performers:
        ent = ds.artists.get(p.artist or "") or ds.characters.get(p.character or "") or ds.persons.get(p.person or "")
        if ent and ent.names.ja:
            names.append(ent.names.ja)
    la = next((a for a in rel.legacy.albums if a.edition == edition), rel.legacy.albums[0] if rel.legacy.albums else None)
    titles = [t for t in (la.title if la else None, rel.title.ja) if t]
    titles += [t.replace("／", " / ") for t in titles if "／" in t]  # search misses titles joined with a full-width slash
    titles += [" ".join(re.sub(r"[★☆♥♡♪]", " ", t).split()) for t in titles if re.search(r"[★☆♥♡♪]", t)]  # and decoration marks
    if rel.discs and rel.discs[0].tracks:
        titles.append(_row_title(ds, rel.discs[0].tracks[0]))
    # a character name can hide the album, and members' songs are often listed under the group: try both
    group = next((ds.artists[g].names.ja for g in main_groups(ds, rel.projects) if ds.artists[g].names.ja), None)
    tags = list(dict.fromkeys(n for n in names[:1] + [group] if n))
    out = [f"{t} {n}" for t in titles for n in tags] + titles
    return list(dict.fromkeys(out))


def _label(rel: m.Release, edition: str | None) -> str:
    ed = next((e for e in rel.editions if e.id == edition), None)
    return _key(ed.label.ja) if ed and ed.label and ed.label.ja else ""


_EDITION_LABEL = re.compile(r"[【［\[]([^】］\]]*盤)[】］\]]")


def _performer_names(ds: Dataset, rel: m.Release) -> list[m.Names]:
    seen, out = set(), []
    performers = list(rel.artist_credit) + [p for d in rel.discs for t in d.tracks for p in ds.recording(t.recording)[1].performers]
    for p in performers:
        ent = ds.artists.get(p.artist or "") or ds.characters.get(p.character or "") or ds.persons.get(p.person or "")
        if ent and ent.id not in seen:
            seen.add(ent.id)
            out.append(ent.names)
    return out[:4] + [ds.artists[g].names for g in main_groups(ds, rel.projects) if g not in seen][:1]


def main_groups(ds: Dataset, projects: list[str]) -> list[str]:
    """Group artists of the projects, the one singing the most recordings first (Liella! before Sunny Passion)."""
    sung: dict[str, int] = {}
    for w in ds.works.values():
        if w.project not in projects:
            continue
        for r in w.recordings:
            for p in r.performers:
                if p.artist:
                    sung[p.artist] = sung.get(p.artist, 0) + 1
    groups = [a.id for a in ds.artists.values() if a.kind == "group" and set(a.projects) & set(projects)]
    return sorted(groups, key=lambda g: -sung.get(g, 0))


def match_edition(client: Client, ds: Dataset, rel: m.Release, edition: str | None) -> EditionMatch:
    rows = edition_tracks(rel, edition)
    row_titles = [_row_title(ds, t) for _, _, t in rows]
    em = EditionMatch(rel.id, edition)
    browse_ids: list[str] = []
    for s in rel.streaming:
        if s.browse_id and (not s.editions or edition in s.editions):
            browse_ids.append(s.browse_id)
    for q in _queries(ds, rel, edition):
        browse_ids += [r["browse_id"] for r in client.search_albums(q)[:6]]
    year = rel.release_date.year if rel.release_date else None
    for names in _performer_names(ds, rel):
        browse_ids += [a["browse_id"] for a in client.artist_albums(names)
                       if year is None or not a.get("year") or abs(int(a["year"]) - year) <= 1]
    vocal_rows = {j for j, (_, _, t) in enumerate(rows) if ds.recording(t.recording)[1].kind == "vocal"}
    for bid in dict.fromkeys(browse_ids):
        album = client.album(bid)
        pairs = align([t["title"] for t in album["tracks"]], row_titles)
        tracks = {f"{rows[j][0]}-{rows[j][1]}": album["tracks"][i]["video_id"] for i, j in pairs if album["tracks"][i]["video_id"]}
        em.candidates.append(Candidate(bid, album["title"] or "", album["year"], len(pairs), len(album["tracks"]), tracks,
                                       covers_vocals=vocal_rows <= {j for _, j in pairs}))
    # an album named after an edition other than this one (【中須かすみ盤】, 【Liella!盤】) is never this edition's
    mine = _label(rel, edition)
    complete = [c for c in em.candidates if c.complete and all(_key(lab) == mine for lab in _EDITION_LABEL.findall(c.title))]
    if not complete:
        em.reason = "no album has all of its tracks in this release"
        return em
    if _label(rel, edition):
        labelled = [c for c in complete if _label(rel, edition) in _key(c.title)]
        complete = labelled or complete
    best = max(c.matched for c in complete)
    top = [c for c in complete if c.matched == best]
    if len(top) > 1 and rel.release_date:
        dated = [c for c in top if c.year == str(rel.release_date.year)]
        top = dated or top
    if len(top) == 1:
        em.chosen = top[0]
    else:
        em.reason = f"{len(top)} albums match equally"
    return em


# --- applying -------------------------------------------------------------------


@dataclass
class Outcome:
    release: str
    applied: bool = False
    added: int = 0
    replaced: int = 0
    kept_live: list[str] = field(default_factory=list)  # keys whose live stored id differs from the album
    review: list[EditionMatch] = field(default_factory=list)


def plan_release(client: Client, ds: Dataset, rel: m.Release) -> tuple[list[EditionMatch], bool]:
    """Match every edition. An edition with no album of its own, while another edition with the same
    track list has one, simply has no own ids: its rows fall back to the main URL (D2)."""
    matches = [match_edition(client, ds, rel, ed) for ed in edition_ids(rel)]
    for mt in matches:
        if mt.chosen or not mt.reason.startswith("no album"):
            continue
        mine = [t.recording for _, _, t in edition_tracks(rel, mt.edition)]
        if any(o.chosen and [t.recording for _, _, t in edition_tracks(rel, o.edition)] == mine for o in matches if o is not mt):
            mt.reason = "sibling"  # no album for this edition; another edition with the same tracks has one
    if not rel.streaming and all(not mt.chosen and max((c.matched for c in mt.candidates), default=0) == 0 for mt in matches):
        for mt in matches:
            mt.reason = "absent"  # not on YouTube Music and nothing stored: nothing to do
    return matches, all(mt.chosen or mt.reason in ("sibling", "absent") for mt in matches)


def apply_matches(client: Client | None, rel: m.Release, matches: list[EditionMatch], checked: str) -> Outcome:
    """Rebuild ``rel.streaming`` from the chosen albums. Editions on the same album share one entry.
    Without a client (a person picked the album in review) differing stored ids are replaced."""
    out = Outcome(rel.id)
    by_album: dict[str, tuple[Candidate, list[str | None]]] = {}
    if all(mt.reason == "absent" for mt in matches):
        out.applied = False
        return out
    for mt in matches:
        if mt.chosen is None:  # "sibling": no own ids
            continue
        by_album.setdefault(mt.chosen.browse_id, (mt.chosen, []))[1].append(mt.edition)
    old = {(ed, k): v for s in rel.streaming for ed in (s.editions or [None]) for k, v in s.tracks.items()}
    entries = []
    for cand, eds in by_album.values():
        tracks = dict(cand.tracks)
        for ed in eds:
            for k, new in cand.tracks.items():
                prev = old.get((ed, k)) or old.get((None, k))
                if prev is None:
                    out.added += 1
                elif prev != new:
                    if client is not None and client.status(prev) == "OK":
                        tracks[k] = prev
                        out.kept_live.append(f"{ed or '-'}/{k}: {prev} (album has {new})")
                    else:
                        out.replaced += 1
        # editions sharing one album are listed explicitly (§4.2); a release without editions uses []
        entries.append(m.Streaming(editions=[e for e in eds if e is not None], browse_id=cand.browse_id, tracks=tracks))
    rel.streaming = entries
    if not entries:
        rel.evidence.pop("streaming", None)
        out.applied = True
        return out
    rel.evidence["streaming"] = m.Evidence(
        status=m.Status.established, source="https://music.youtube.com/browse/" + (entries[0].browse_id or ""),
        checked=dt.date.fromisoformat(checked),
        note="YouTube Music 어댑터: 앨범 트랙을 순서·제목으로 대조. 죽은 videoId는 교체, 살아 있는 값은 유지",
    )
    out.applied = True
    return out


def review_doc(rel: m.Release, matches: list[EditionMatch], kept_live: list[str] | None = None) -> dict[str, Any]:
    if kept_live:
        return {"type": "ytm-change", "title": f"YouTube Music: 살아 있는 기존 videoId가 앨범과 다름: {rel.id}",
                "note": "§6.3: 자동으로 덮어쓰지 않았다. 앨범 값으로 바꾸려면 data/를 고치고 done",
                "items": [{"release": rel.id, "keys": kept_live}], "decision": None}
    items = []
    for mt in matches:
        items.append({
            "release": rel.id, "edition": mt.edition, "reason": mt.reason or None,
            "candidates": [{"n": n, "browse_id": c.browse_id, "title": c.title, "year": c.year,
                            "matched": f"{c.matched}/{c.album_tracks}", "tracks": c.tracks}
                           for n, c in enumerate(sorted(mt.candidates, key=lambda c: (-c.complete, -c.matched))[:5], 1)],
        })
    return {"type": "ytm-album", "title": f"YouTube Music 앨범을 정하지 못함: {rel.id}",
            "note": "decision: pick:<edition>=<n>[,<edition>=<n>] (에디션이 없으면 pick:<n>), 또는 none(스트리밍 없음)",
            "items": items, "decision": None}


def matches_from_review(doc: dict[str, Any], decision: str) -> tuple[str, list[EditionMatch]]:
    """Rebuild the matches a ``ytm-album`` review item recorded, with the picked candidates chosen.
    ``pick:<n>`` or ``pick:<edition>=<n>,…``; an edition left out (or ``none``) gets no own ids."""
    items = doc.get("items") or []
    release = str(items[0]["release"])
    picks: dict[str | None, int] = {}
    if decision.startswith("pick:"):
        for part in decision.removeprefix("pick:").split(","):
            ed, _, n = part.rpartition("=")
            picks[ed or None] = int(n)
    elif decision != "none":
        raise ValueError(f"unknown ytm-album decision {decision!r}")
    out = []
    for item in items:
        ed = item.get("edition")
        mt = EditionMatch(release, ed, reason="none")
        n = picks.get(ed, picks.get(None) if len(items) == 1 else None)
        if n is not None:
            c = next(c for c in item["candidates"] if c["n"] == n)
            matched, total = (int(x) for x in str(c["matched"]).split("/"))
            mt.chosen = Candidate(c["browse_id"], c.get("title") or "", c.get("year"), matched, total, dict(c["tracks"]))
        out.append(mt)
    return release, out
