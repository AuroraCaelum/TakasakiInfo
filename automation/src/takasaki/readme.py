"""The repository README (DESIGN.md §10.3).

The prose lives in ``templates/README.md``; everything that follows the data is filled in here from
``data/`` and the freshly built legacy files: the Database Status table, counts and badges, upcoming
releases, the file-name and category lists, the JSON examples and the Disclaimer. The v1 schema tables
are made from the model, with its field docstrings as the descriptions. ``takasaki build`` writes it
with the legacy files and ``takasaki check`` (E8) compares it like any other output.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import types
import urllib.parse
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from . import model as m
from .build_legacy import edition_tracks
from .build_v1 import RECORDING_FIELDS, TRACK_FIELDS, release_dump
from .store import LAYOUT, Dataset

TEMPLATE = Path(__file__).parent / "templates" / "README.md"
REPO = "https://github.com/AuroraCaelum/TakasakiInfo"
CDN = "https://d1zzovwupaegwb.cloudfront.net"  # the public endpoint until a custom domain (D19)
RIGHTS_HOLDERS = ["SUNRISE", "Bandai Namco Filmworks Inc.", "Lantis", "Bushiroad"]


def _badge(label: str, message: str, color: str) -> str:
    esc = lambda s: urllib.parse.quote(s.replace("-", "--").replace("_", "__"), safe="")  # noqa: E731
    return f"https://img.shields.io/badge/{esc(label)}-{esc(message)}-{color}?style=flat-square"


def _project(ds: Dataset, group: str) -> m.Project | None:
    return next((p for p in ds.projects.values() if p.legacy and p.legacy.file == group), None)


def _load(files: dict[str, bytes], rel: str) -> Any:
    return json.loads(files[rel]) if rel in files else None


def _pct(n: int, d: int) -> str:
    return f"{round(100 * n / d)}%" if d else "—"


def _status(ds: Dataset, files: dict[str, bytes]) -> tuple[str, dict[str, int]]:
    assert ds.layout is not None
    rows = ["| Project | Latest release | Albums | Tracks | Streaming links | Files |",
            "| :-- | :-: | --: | --: | --: | :-- |"]
    total = {"albums": 0, "tracks": 0, "linked": 0}
    for g in ds.layout.integrated_order:
        p = _project(ds, g)
        name = (p.names.rom if p else None) or g
        albums = _load(files, f"albums/{g}/{g}.json") or []
        tracks = [s for a in albums for s in a["songs"]]
        linked = sum(1 for s in tracks if s["link"] != "NA")
        links = []
        if albums:
            links.append(f"Albums [CSV](albums/{g}/{g}.csv) · [JSON](albums/{g}/{g}.json)")
            links.append(f"Songs [JSON](songs/{g}/{g}.json)")
        if f"members/{g}.csv" in files:
            links.append(f"Members [CSV](members/{g}.csv)")
        if f"concerts/{g}/{g}.json" in files:
            links.append(f"Concerts [JSON](concerts/{g}/{g}.json)")
        if not albums:
            links.append("*songs & albums planned*")
        latest = max((a["release"] for a in albums if a["release"]), default="—")
        rows.append(f"| **{name}** | {latest} | {len(albums) or '—'} | {len(tracks) or '—'} | "
                    f"{_pct(linked, len(tracks)) if tracks else '—'} | {' · '.join(links)} |")
        total["albums"] += len(albums)
        total["tracks"] += len(tracks)
        total["linked"] += linked
    return "\n".join(rows), total


def _upcoming(ds: Dataset) -> str:
    assert ds.layout is not None
    out = []
    for g, f in ds.layout.albums.items():
        for e in f.entries:
            rel = ds.releases[e.release]
            if rel.status == "announced":
                p = _project(ds, g)
                out.append(f"**{rel.title.ja}** ({(p.names.rom if p else None) or g}, {rel.release_date})")
    return ("> [!TIP]\n> Coming up, listed once released: " + "; ".join(sorted(set(out)))) if out else ""


def _songs(ds: Dataset) -> int:
    """Distinct songs (works) in the legacy files."""
    assert ds.layout is not None
    seen = set()
    for f in ds.layout.albums.values():
        for e in f.entries:
            rel = ds.releases[e.release]
            if rel.status == "announced" or e.album >= len(rel.legacy.albums):
                continue
            la = rel.legacy.albums[e.album]
            for _, _, t in edition_tracks(rel, la.edition, la.disc):
                work, _ = ds.recording(t.recording)
                if work.kind == "song":
                    seen.add(work.id)
    return len(seen)


def _files(ds: Dataset, lang: str) -> str:
    assert ds.layout is not None
    lines = []
    for g in ds.layout.integrated_order:
        p = _project(ds, g)
        name = getattr(p.names, lang) if p else None
        lines.append(f"  - {name or g} → `{g}`")
    return "\n".join(lines)


def _example(obj: Any) -> str:
    text = json.dumps([obj], ensure_ascii=False, indent=2)
    return "```jsonc\n" + text[: text.rfind("]")].rstrip() + ",\n  // …\n]\n```"


def _song_example(files: dict[str, bytes]) -> str:
    songs = _load(files, "songs/Nijigaku/Nijigaku.json") or next(
        (json.loads(b) for rel, b in sorted(files.items()) if rel.startswith("songs/")), [])
    return _example(next((s for s in songs if s["title"]["ja"] == "ヤダ！"), songs[0] if songs else {}))


def _album_example(files: dict[str, bytes]) -> str:
    albums = _load(files, "albums/Liella/Liella.json") or []
    album = dict(albums[0]) if albums else {}
    text = _example({**album, "songs": album.get("songs", [])[:1]} if album else {})
    # a comment for the elided tracks of the album too
    return text.replace("\n      }\n    ]\n  },", "\n      },\n      // …\n    ]\n  },", 1)


def _concert_example(files: dict[str, bytes]) -> str:
    concerts = _load(files, "concerts/Liella/Liella.json") or []
    if not concerts:
        return ""
    c = concerts[0]
    trimmed = {**c, "sights": c["sights"][:1], "events": [{**c["events"][0], "setlist": c["events"][0]["setlist"][:3]}]}
    return _example(trimmed)


# --- v1 schema ----------------------------------------------------------------

SCHEMA_ORDER = ["release", "work", "person", "character", "artist", "project", "concert", "venue", "city"]
COMMON: list[type[BaseModel]] = [m.Names, m.Evidence]  # described once, ahead of the files that use them
EXAMPLE_RELEASE = "ikizulive/2025-homerun-queen"  # two editions, catalog numbers, one album for both, a smart link
_SCALARS = {str: "string", int: "integer", bool: "boolean", dt.date: "date"}


def _variants(ann: Any) -> list[Any]:
    """The types of an annotation, without None."""
    if get_origin(ann) in (Union, types.UnionType):
        return [a for a in get_args(ann) if a is not type(None)]
    return [ann]


def _is_model(a: Any) -> bool:
    return isinstance(a, type) and issubclass(a, BaseModel)


def _nested(ann: Any) -> list[type[BaseModel]]:
    out: list[type[BaseModel]] = []
    for a in _variants(ann):
        if get_origin(a) in (list, dict):
            out += _nested(get_args(a)[-1])
        elif _is_model(a):
            out.append(a)
    return out


def _choices(ann: Any) -> list[str]:
    for a in _variants(ann):
        if get_origin(a) is Literal and len(get_args(a)) > 1:
            return [str(v) for v in get_args(a)]
        if isinstance(a, type) and issubclass(a, Enum):
            return [e.value for e in a]
    return []


def _type(ann: Any) -> str:
    parts = []
    for a in _variants(ann):
        origin = get_origin(a)
        if origin is list:
            parts.append(_type(get_args(a)[0]) + "[]")
        elif origin is dict:
            parts.append("map of " + _type(get_args(a)[1]))
        elif origin is Literal:
            values = get_args(a)
            parts.append(f'`"{values[0]}"`' if len(values) == 1 else "string")
        elif _is_model(a):
            parts.append(f"**{a.__name__}**")
        elif isinstance(a, type) and issubclass(a, Enum):
            parts.append("string")
        else:
            parts.append(_SCALARS[a])
    return " or ".join(parts)


def _default(f: FieldInfo) -> str:
    if f.is_required():
        return "*required*"
    value = f.get_default(call_default_factory=True)
    if value is None:
        return "—"
    if isinstance(value, BaseModel):
        return "empty"
    return f"`{json.dumps(value, ensure_ascii=False)}`"


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def _model_table(cls: type[BaseModel], home: dict[type[BaseModel], str], here: str) -> str:
    rows = ["| Field | Type | Default | Description |", "| :-- | :-- | :-- | :-- |"]
    for name, f in cls.model_fields.items():
        desc = f.description or ""
        if choices := _choices(f.annotation):
            desc += " One of " + ", ".join(f"`{c}`" for c in choices) + "."
        kind = _type(f.annotation)
        elsewhere = sorted({home[c] for c in _nested(f.annotation) if c not in COMMON and home.get(c) != here})
        if elsewhere:  # an object described under another file
            kind += " (see " + ", ".join(f"`{w}`" for w in elsewhere) + ")"
        rows.append(f"| `{f.alias or name}` | {kind} | {_default(f)} | {_cell(desc)} |")
    return "\n".join(rows)


def _view_table(fields: dict[str, tuple[str, str]]) -> str:
    rows = ["| Field | Type | Description |", "| :-- | :-- | :-- |"]
    rows += [f"| `{k}` | {t} | {_cell(d)} |" for k, (t, d) in fields.items()]
    return "\n".join(rows)


def _details(summary: str, body: list[str]) -> str:
    return "<details>\n<summary>" + summary + "</summary>\n\n" + "\n\n".join(body) + "\n\n</details>"


def v1_schema() -> str:
    """The v1 schema section: a table per entity file and its nested objects, then the two views. Every
    nested object is described under the first file that has it; other files name that file."""
    home: dict[type[BaseModel], str] = {cls: "common" for cls in COMMON}
    owned: dict[str, list[tuple[type[BaseModel], str]]] = {}  # file -> its nested objects, with where they are used
    for kind in SCHEMA_ORDER:
        sub, cls, _ = LAYOUT[kind]
        here = f"{sub}.json"
        owned[here] = []
        queue = [cls]
        while queue:
            parent = queue.pop(0)
            for name, f in parent.model_fields.items():
                for child in _nested(f.annotation):
                    if child not in home:
                        home[child] = here
                        owned[here].append((child, f"{parent.__name__} `{f.alias or name}`"))
                        queue.append(child)
    missing = [f"{c.__name__}.{n}" for c in [*home, *(LAYOUT[k][1] for k in SCHEMA_ORDER)]
               for n, f in c.model_fields.items() if not f.description]
    if missing:
        raise ValueError(f"model fields without a docstring (their description in the v1 schema): {sorted(set(missing))}")

    blocks = [_details("Common objects: <b>Names</b>, <b>Evidence</b>",
                       [f"**{c.__name__}**: {c.__doc__}\n\n{_model_table(c, home, 'common')}" for c in COMMON])]
    for kind in SCHEMA_ORDER:
        sub, cls, _ = LAYOUT[kind]
        here = f"{sub}.json"
        body = [_model_table(cls, home, here)]
        body += [f"**{c.__name__}** (in {used})\n\n{_model_table(c, home, here)}" for c, used in owned[here]]
        title = ", ".join(f"<b>{c.__name__}</b>" for c in [cls, *(c for c, _ in owned[here])])
        blocks.append(_details(f"<code>{here}</code>: {title}", body))
    refs = ("A **ref** is a reference with the names it points to: `{\"ref\": \"<kind>:<id>\", \"names\": {…}}`, "
            "plus `role`, `featured` and `joint` for a singer or `affiliation`, `fullwidth` and `role` for a credit "
            "when they are set. A value that is not known is null.")
    blocks.append(_details("<code>tracks.json</code>: one row per track of each edition, with its credits and link",
                           [refs, _view_table(TRACK_FIELDS)]))
    blocks.append(_details("<code>recordings.json</code>: one row per recording, with its credits and main link",
                           [_view_table(RECORDING_FIELDS)]))
    return "\n\n".join(blocks)


def _release_example(ds: Dataset) -> str:
    rel = ds.releases.get(EXAMPLE_RELEASE) or next(iter(ds.releases.values()))
    text = json.dumps(release_dump(ds, rel), ensure_ascii=False, indent=2)
    return "```json\n" + text + "\n```"


def _disclaimer(ds: Dataset, lang: str) -> str:
    assert ds.layout is not None
    order = [p for g in ds.layout.integrated_order if (p := _project(ds, g))]
    order += [p for p in ds.projects.values() if p not in order]
    lines = []
    for p in order:
        own = [c.text for c in p.copyright if c.lang == lang] or [c.text for c in p.copyright]  # no notice in this language
        lines += [t for t in own if t not in lines]
    return "\n".join(f"> {t}<br>" for t in lines).removesuffix("<br>")


def readme_values(ds: Dataset, files: dict[str, bytes]) -> dict[str, str]:
    assert ds.meta is not None and ds.layout is not None
    table, total = _status(ds, files)
    integrated = (_load(files, "TakasakiInfo.json") or {}).get("data", [])
    no_kana = sum(1 for r in integrated if not r.get("pronunciation"))
    day = ds.meta.db_last_update[:10]
    planned = [((p.names.rom if (p := _project(ds, g)) else None) or g)
               for g in ds.layout.integrated_order if g not in ds.layout.albums]
    groups = [g for g in ds.layout.integrated_order if g in ds.layout.albums]
    return {
        "UPDATED": day,
        "BADGE_DATA": _badge("data updated", day, "e4007f"),
        "BADGE_TRACKS": _badge("tracks", f"{len(integrated):,}", "5d9cec"),
        "BADGE_FORMATS": _badge("formats", "CSV · JSON · SQLite", "555"),
        "STATUS_TABLE": table,
        "UPCOMING": _upcoming(ds),
        "TRACKS": f"{len(integrated):,}",
        "ALBUMS": f"{total['albums']:,}",
        "SONGS": f"{_songs(ds):,}",
        "PEOPLE": f"{len(ds.persons):,}",
        "CHARACTERS": f"{len(ds.characters):,}",
        "LINKED": _pct(sum(1 for r in integrated if r["link"] != "NA"), len(integrated)),
        "NO_KANA": f"{no_kana:,}",
        # the groups whose songs are not in yet; nothing once every group is
        "NOT_IN_YET": f" Not in yet: songs and albums of {', '.join(planned)}." if planned else "",
        "FILES_EN": _files(ds, "rom"),
        "FILES_KO": _files(ds, "ko"),
        "FILES_JA": _files(ds, "ja"),
        "CATEGORIES": ", ".join(f"`{g}`" for g in groups + ["Others"]),
        "SONG_EXAMPLE": _song_example(files),
        "ALBUM_EXAMPLE": _album_example(files),
        "CONCERT_EXAMPLE": _concert_example(files),
        "V1_SCHEMA": v1_schema(),
        "RELEASE_EXAMPLE": _release_example(ds),
        "DISCLAIMER_EN": _disclaimer(ds, "en"),
        "DISCLAIMER_JA": _disclaimer(ds, "ja"),
        "RIGHTS_EN": ", ".join(RIGHTS_HOLDERS[:-1]) + ", and " + RIGHTS_HOLDERS[-1],
        "RIGHTS_KO": ", ".join(RIGHTS_HOLDERS),
        "RIGHTS_JA": "、".join(RIGHTS_HOLDERS),
        "CDN": CDN,
        "REPO": REPO,
    }


def render_readme(ds: Dataset, files: dict[str, bytes]) -> bytes:
    text = TEMPLATE.read_text(encoding="utf-8")
    for key, value in readme_values(ds, files).items():
        text = text.replace("{{" + key + "}}", value)
    left = sorted(set(re.findall(r"\{\{[A-Z_]+\}\}", text)))
    if left:
        raise ValueError(f"README template placeholders without a value: {left}")
    return text.encode("utf-8")


def build_outputs(ds: Dataset) -> dict[str, bytes]:
    """Every file `takasaki build` writes into the repository: the legacy files and the README."""
    from .build_legacy import build_legacy

    files = build_legacy(ds)
    files["README.md"] = render_readme(ds, files)
    return files
