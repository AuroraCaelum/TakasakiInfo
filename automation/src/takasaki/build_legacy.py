"""Generate the legacy files (DESIGN.md §10.1) from the canonical dataset.

The output format reproduces the retired ``tools/Process.py`` byte for byte:
CSV with BOM + CRLF and no trailing newline, JSON with tab indent (concerts use
four spaces), ``ensure_ascii=False`` and no trailing newline.
"""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import model as m
from .store import Dataset
from .text import is_latin, match_key, render_credit_name

ALBUM_HEADER = [
    "Album", "Track", "日本語", "Romaji", "한국어", "歌", "Singer", "가수", "作詞", "Lyrics", "작사",
    "作曲", "Compose", "작곡", "編曲", "Arrange", "편곡", "Release", "Link", "Category", "Note", "発音",
]
MEMBER_HEADER = ["日本語", "Romaji", "한국어", "声優", "Seiyuu", "성우", "Unit"]
LANGS = ("ja", "rom", "ko")
YT = "https://youtu.be/"


@dataclass(frozen=True)
class TrackRef:
    release: str
    edition: str | None
    disc: int
    pos: int


@dataclass
class Row:
    ref: TrackRef
    cells: list[str]


# --- track selection and links ------------------------------------------------


def edition_tracks(rel: m.Release, edition: str | None, disc_no: int | None = None) -> list[tuple[int, int, m.Track]]:
    out: list[tuple[int, int, m.Track]] = []
    for disc in rel.discs:
        if disc_no is not None and disc.disc != disc_no:
            continue
        if disc.editions != "all" and edition not in disc.editions:
            continue
        for pos, track in enumerate(disc.tracks, 1):
            out.append((disc.disc, pos, track))
    return out


def own_video(rel: m.Release, edition: str | None, disc: int, pos: int) -> str | None:
    """The track's own video. No edition (a legacy album that stands for the whole release) takes
    the first streaming entry that has the track, whichever editions it lists."""
    key = f"{disc}-{pos}"
    for s in rel.streaming:
        if s.platform != "youtube_music":
            continue
        if s.editions and edition is not None and edition not in s.editions:
            continue
        if key in s.tracks:
            return s.tracks[key]
    return None


def edition_ids(rel: m.Release) -> list[str | None]:
    return [e.id for e in rel.editions] or [None]


def main_videos(ds: Dataset) -> dict[str, str]:
    """Main URL per recording: the earliest-released track that has its own URL (D2).

    Ties: originals before compilations, then edition order, then release id and position.
    """
    candidates: dict[str, list[tuple[Any, ...]]] = {}
    for rel in ds.releases.values():
        for ed_index, ed in enumerate(edition_ids(rel)):
            ed_date = next((e.release_date for e in rel.editions if e.id == ed and e.release_date), None)
            day = (ed_date or rel.release_date)
            day_key = day.isoformat() if day else "9999-12-31"
            for disc, pos, track in edition_tracks(rel, ed):
                vid = own_video(rel, ed, disc, pos)
                if vid:
                    key = (day_key, rel.type == "compilation", ed_index, rel.id, disc, pos, vid)
                    candidates.setdefault(track.recording, []).append(key)
    return {rec: min(keys)[-1] for rec, keys in candidates.items()}


# --- rendering ----------------------------------------------------------------


def _names_of(ds: Dataset, perf: m.Performer) -> m.Names:
    if perf.artist:
        return ds.artists[perf.artist].names
    if perf.person:
        return ds.persons[perf.person].names
    return ds.characters[perf.character].names  # type: ignore[index]


def _join(values: list[str]) -> str:
    return ";".join(values)


def render_performers(ds: Dataset, performers: list[m.Performer]) -> list[str]:
    out = []
    for lang in LANGS:
        parts = []
        for p in performers:
            name = getattr(_names_of(ds, p), lang) or ""
            role = getattr(ds.characters[p.role].names, lang) if p.role else None
            parts.append(render_credit_name(name, lang, role=role) if role else name)
        out.append(_join(parts))
    return out


def _credit_names(ds: Dataset, c: m.Credit) -> m.Names:
    if c.person:
        return ds.persons[c.person].names
    return ds.characters[c.character].names  # type: ignore[index]


def render_credits(ds: Dataset, credits: list[m.Credit]) -> list[str]:
    out = []
    for lang in LANGS:
        parts = []
        for c in credits:
            name = getattr(_credit_names(ds, c), lang) or ""
            role = getattr(c.role, lang) if c.role else None
            parts.append(render_credit_name(name, lang, c.affiliation_in(lang), role, c.fullwidth))
        out.append(_join(parts))
    return out


def track_title(work: m.Work, rec: m.Recording, track: m.Track) -> tuple[m.Names, str]:
    base = rec.title or work.title
    kana = base.kana or ""
    if track.title_as_printed:
        return track.title_as_printed, kana
    return base, kana


_TITLE_SEP = re.compile(r"\s*[/／]\s*")


def release_title(ds: Dataset, rel: m.Release) -> tuple[m.Names, list[str]]:
    """The release title in every language, and the languages filled here (D39). A stored value
    wins. A title made of the release's song titles ("A / B") takes their rom and ko, joined with
    " / "; an all-Latin title is its own rom and ko (§5.3, §5.4: Latin text stays)."""
    t = rel.title
    if not t.ja or (t.rom and t.ko):
        return t, []
    works = {match_key(w.title.ja): w for w in (ds.recording(tr.recording)[0] for d in rel.discs for tr in d.tracks)}
    parts = [t.ja] if match_key(t.ja) in works else _TITLE_SEP.split(t.ja)
    derived: dict[str, str] = {}
    if all(match_key(p) in works for p in parts):
        for lang in ("rom", "ko"):
            vals = [getattr(works[match_key(p)].title, lang) for p in parts]
            if all(vals):
                derived[lang] = " / ".join(vals)  # type: ignore[arg-type]
    elif is_latin(t.ja):
        derived = dict.fromkeys(("rom", "ko"), unicodedata.normalize("NFKC", t.ja))
    filled = [lang for lang in derived if not getattr(t, lang)]
    return t.model_copy(update={lang: derived[lang] for lang in filled}), filled


def video_owners(ds: Dataset) -> dict[str, str]:
    """Video id -> title of the legacy album whose track owns it (for "Link is from the [...]")."""
    owners: dict[str, str] = {}
    for rel in ds.releases.values():
        # a release kept only as a link source (not in the legacy files) is named by its title
        albums = rel.legacy.albums or [m.LegacyAlbum(title=rel.title.ja or rel.id)]
        for la in albums:
            for disc, pos, _ in edition_tracks(rel, la.edition, la.disc):
                vid = own_video(rel, la.edition, disc, pos)
                if vid:
                    owners.setdefault(vid, la.title)
    return owners


def render_note(la: m.LegacyAlbum, disc: int, rec: m.Recording, track: m.Track, link_from: str | None) -> str:
    parts = [
        f"Disc.{disc}" if la.flatten_discs else None,
        "Drama Part" if rec.kind == "drama" else None,
        la.note,
        track.note,
        f"Link is from the [{link_from}]" if link_from else None,
    ]
    return ", ".join(p for p in parts if p)


def render_album_rows(ds: Dataset, group: str, mains: dict[str, str], owners: dict[str, str]) -> list[Row]:
    assert ds.layout is not None
    rows: list[Row] = []
    for entry in ds.layout.albums[group].entries:
        rel = ds.releases[entry.release]
        if rel.status == "announced":  # §7.4: announced releases are left out of the legacy files
            continue
        la = rel.legacy.albums[entry.album]
        ed_date = next((e.release_date for e in rel.editions if e.id == la.edition and e.release_date), None)
        day = ed_date or rel.release_date
        for running, (disc, pos, track) in enumerate(edition_tracks(rel, la.edition, la.disc), 1):
            work, rec = ds.recording(track.recording)
            title, kana = track_title(work, rec, track)
            credits = rec.credits_override or work.credits
            own = own_video(rel, la.edition, disc, pos)
            vid = own or mains.get(track.recording)
            number = running if la.flatten_discs else track.no
            cells = [
                la.title,
                "" if number is None else str(number),
                title.ja or "", title.rom or "", title.ko or "",
                *render_performers(ds, rec.performers),
                *render_credits(ds, credits.lyricist),
                *render_credits(ds, credits.composer),
                *render_credits(ds, rec.all_arrangers()),
                day.isoformat() if day else "",
                YT + vid if vid else "NA",
                track.category if track.category is not None
                else entry.category if entry.category is not None
                else (rel.legacy.category or ""),
                render_note(la, disc, rec, track, owners.get(vid) if vid and not own else None),
                kana,
            ]
            rows.append(Row(TrackRef(rel.id, la.edition, disc, pos), cells))
    return rows


# --- serialisation ------------------------------------------------------------


def write_csv(header: list[str], rows: list[list[str]], bom: bool) -> bytes:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\r\n").writerows([header, *rows])
    text = buf.getvalue()
    if text.endswith("\r\n"):
        text = text[:-2]
    return (("﻿" if bom else "") + text).encode("utf-8")


def _multi(cells: list[str], i: int) -> Any:
    ja, rom, ko = cells[i], cells[i + 1], cells[i + 2]
    if ";" in ja:
        js, rs, ks = ja.split(";"), rom.split(";"), ko.split(";")
        return [{"ja": js[k], "rom": rs[k], "ko": ks[k]} for k in range(len(js))]
    return {"ja": ja, "rom": rom, "ko": ko}


def _people(c: list[str]) -> dict[str, Any]:
    return {
        "artist": _multi(c, 5),
        "lyricist": _multi(c, 8),
        "composer": _multi(c, 11),
        "arranger": _multi(c, 14),
    }


def integrated_entry(c: list[str]) -> dict[str, Any]:
    return {
        "title": {"ja": c[2], "rom": c[3], "ko": c[4]},
        **_people(c),
        "album": c[0], "track": c[1], "release": c[17], "link": c[18],
        "category": c[19], "note": c[20], "pronunciation": c[21],
    }


def song_entry(c: list[str]) -> dict[str, Any]:
    return {
        "title": {"ja": c[2], "rom": c[3], "ko": c[4]},
        **_people(c),
        "album": c[0], "track": c[1], "release": c[17], "link": c[18],
        "note": c[20], "pronunciation": c[21],
    }


def album_song_entry(c: list[str]) -> dict[str, Any]:
    return {
        "track": c[1],
        "title": {"ja": c[2], "rom": c[3], "ko": c[4]},
        **_people(c),
        "link": c[18], "note": c[20], "pronunciation": c[21],
    }


def albums_json(rows: list[list[str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for c in rows:
        if not out or out[-1]["album"] != c[0]:
            out.append({"album": c[0], "release": c[17], "songs": []})
        out[-1]["songs"].append(album_song_entry(c))
    return out


def is_song(c: list[str]) -> bool:
    return "Off Vocal" not in c[2] and "Drama Part" not in c[20]


def dump_json(obj: Any, indent: Any = "\t") -> bytes:
    return json.dumps(obj, ensure_ascii=False, indent=indent).encode("utf-8")


def render_members(ds: Dataset, group: str) -> bytes:
    assert ds.layout is not None
    f = ds.layout.members[group]
    rows = []
    for r in f.rows:
        ch = ds.characters[r.character]
        cv = [ds.persons[c.person].names for c in ch.casting]
        unit = ds.artists[r.unit].names.ja if r.unit else ""
        rows.append([
            ch.names.ja or "", ch.names.rom or "", ch.names.ko or "",
            _join([n.ja or "" for n in cv]), _join([n.rom or "" for n in cv]), _join([n.ko or "" for n in cv]),
            unit or "",
        ])
    return write_csv(MEMBER_HEADER, rows, f.bom)


def _city_label(ds: Dataset, stop: m.Stop) -> str:
    rom = ds.cities[stop.city].names.rom or ""
    return f"{rom} ({stop.label})" if stop.label else rom


def setlist_strings(ds: Dataset, perf: m.Performance) -> list[str]:
    out = []
    counters = {"mc": 0, "video": 0}
    for item in perf.setlist:
        if item.type == "song":
            if item.title_raw is not None:
                out.append(item.title_raw)
            elif item.recording:
                work, rec = ds.recording(item.recording)
                out.append((rec.title or work.title).ja or "")
            else:
                out.append(ds.works[item.work].title.ja or "")  # type: ignore[index]
            continue
        if item.label is not None:
            out.append("::" + item.label)
            continue
        counters[item.type] = counters.get(item.type, 0) + 1
        prefix = {"mc": "MC", "video": "VID"}[item.type]
        out.append(f"::{prefix}{counters[item.type]}")
    return out


def render_concert(ds: Dataset, c: m.Concert) -> dict[str, Any]:
    dates = [p.date for s in c.stops for p in s.performances]
    return {
        "eventCode": c.legacy.event_code,
        "title": {"ja": c.title.ja, "rom": c.title.rom, "ko": c.title.ko},
        "date_range": [min(dates).isoformat(), max(dates).isoformat()],
        "sights": [
            {
                "city": _city_label(ds, s),
                "date": [p.date.isoformat() for p in s.performances],
                "venue": {lang: getattr(ds.venues[s.venue].names, lang) for lang in LANGS},
            }
            for s in c.stops
        ],
        "events": [
            {"city": _city_label(ds, s), "date": p.date.isoformat(), "setlist": setlist_strings(ds, p)}
            for s in c.stops
            for p in s.performances
        ],
    }


def build_legacy(ds: Dataset) -> dict[str, bytes]:
    """Return {repo-relative path: file bytes} for every legacy file."""
    assert ds.layout is not None and ds.meta is not None
    out: dict[str, bytes] = {}
    mains = main_videos(ds)
    owners = video_owners(ds)
    integrated: list[Row] = []
    seen: set[TrackRef] = set()
    for group in ds.layout.integrated_order:
        if group not in ds.layout.albums:
            continue
        rows = render_album_rows(ds, group, mains, owners)
        cells = [r.cells for r in rows]
        out[f"albums/{group}/{group}.csv"] = write_csv(ALBUM_HEADER, cells, ds.layout.albums[group].bom)
        out[f"albums/{group}/{group}.json"] = dump_json(albums_json(cells))
        out[f"songs/{group}/{group}.json"] = dump_json([song_entry(c) for c in cells if is_song(c)])
        for r in rows:
            if r.ref not in seen:  # a release listed in several group files appears once (§10.1)
                seen.add(r.ref)
                integrated.append(r)
    integrated.sort(key=lambda r: r.cells[17])
    out["TakasakiInfo.json"] = dump_json(
        {"dbLastUpdate": ds.meta.db_last_update, "data": [integrated_entry(r.cells) for r in integrated]}
    )
    for group in ds.layout.members:
        out[f"members/{group}.csv"] = render_members(ds, group)
    for group, ids in ds.layout.concerts.items():
        out[f"concerts/{group}/{group}.json"] = dump_json([render_concert(ds, ds.concerts[i]) for i in ids], indent=4)
    return out


def write_outputs(files: dict[str, bytes], root: Path) -> list[str]:
    changed = []
    for rel, data in sorted(files.items()):
        path = root / rel
        if path.exists() and path.read_bytes() == data:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        changed.append(rel)
    return changed
