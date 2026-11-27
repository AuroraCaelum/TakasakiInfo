"""The repository READMEs (DESIGN.md §10.3): ``README.md`` in English, and ``README.ko.md`` and
``README.ja.md`` that its language links open.

The prose lives in ``templates/README*.md``; everything that follows the data is filled in here from
``data/`` and the freshly built legacy files: the Database Status table, counts and badges, upcoming
releases, the file-name and category lists, the JSON examples and the Disclaimer. The DB schema tables
are made from the model, with its field docstrings as the descriptions. ``takasaki build`` writes them
with the legacy files and ``takasaki check`` (E8) compares them like any other output.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import types
import urllib.parse
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from . import model as m
from .build_legacy import edition_tracks
from .build_v1 import RECORDING_FIELDS, TRACK_FIELDS, release_dump
from .store import LAYOUT, Dataset

TEMPLATES = Path(__file__).parent / "templates"
READMES = {"README.md": "en", "README.ko.md": "ko", "README.ja.md": "ja"}  # English, and the pages its language links open
NAME_LANG = {"en": "rom", "ko": "ko", "ja": "ja"}  # the project names each README shows
# the generated text of each README in its language (the prose is in the templates)
TEXT: dict[str, dict[str, str]] = {
    "en": {
        "status_head": "| Project | Latest release | Albums | Tracks | Streaming links | Files |",
        "albums": "Albums", "songs": "Songs", "members": "Members", "concerts": "Concerts",
        "planned": "*songs & albums planned*", "upcoming": "Coming up, listed once released: ",
        "not_in_yet": " Not in yet: songs and albums of {}.",
        "badge_data": "data updated", "badge_tracks": "tracks", "badge_formats": "formats",
        "field_head": "| Field | Type | Default | Description |", "view_head": "| Field | Type | Description |",
        "required": "*required*", "empty": "empty", "see": " (see {})", "common": "Common objects", "in": " (in {})",
        "refs": "A **ref** is a reference with the names it points to: `{\"ref\": \"<kind>:<id>\", \"names\": {…}}`, "
                "plus `role`, `featured` and `joint` for a singer or `affiliation`, `fullwidth` and `role` for a credit "
                "when they are set. A credit printed under a pen name or former name has `credited_name`, and its "
                "`names` are that name's. A value that is not known is null.",
        "tracks": "one row per track of each edition, with its credits and link",
        "recordings": "one row per recording, with its credits and main link",
        "mood_head": "| Label | ja | rom | ko | When |",
    },
    "ko": {
        "status_head": "| 프로젝트 | 최신 발매 | 앨범 | 트랙 | 스트리밍 링크 | 파일 |",
        "albums": "음반", "songs": "곡", "members": "멤버", "concerts": "공연",
        "planned": "*곡·음반 추가 예정*", "upcoming": "발매 예정(발매되면 목록에 들어감): ",
        "not_in_yet": " 아직 들어오지 않은 것: {}의 곡과 음반.",
        "badge_data": "데이터 갱신", "badge_tracks": "트랙", "badge_formats": "형식",
        "field_head": "| 필드 | 타입 | 기본값 | 설명 |", "view_head": "| 필드 | 타입 | 설명 |",
        "required": "*필수*", "empty": "빈 객체", "see": " ({} 참고)", "common": "공통 객체", "in": " ({}에서 씀)",
        "refs": "**ref**는 가리키는 대상과 그 이름을 함께 담은 참조입니다: `{\"ref\": \"<종류>:<id>\", \"names\": {…}}`. "
                "값이 있으면 가수에는 `role`, `featured`, `joint`가, 크레딧에는 `affiliation`, `fullwidth`, `role`이 더 붙습니다. "
                "필명이나 예전 이름으로 실린 크레딧에는 `credited_name`이 있고, `names`는 그 이름의 것입니다. 모르는 값은 null입니다.",
        "tracks": "에디션의 트랙마다 한 행. 크레딧과 링크 포함",
        "recordings": "음원마다 한 행. 크레딧과 대표 링크 포함",
        "mood_head": "| 라벨 | ja | rom | ko | 조건 |",
    },
    "ja": {
        "status_head": "| プロジェクト | 最新リリース | アルバム | トラック | ストリーミングリンク | ファイル |",
        "albums": "アルバム", "songs": "曲", "members": "メンバー", "concerts": "ライブ",
        "planned": "*曲・アルバムは追加予定*", "upcoming": "発売予定（発売後に一覧に入ります）: ",
        "not_in_yet": " まだ入っていないもの: {}の曲とアルバム。",
        "badge_data": "データ更新", "badge_tracks": "トラック", "badge_formats": "形式",
        "field_head": "| フィールド | 型 | 既定値 | 説明 |", "view_head": "| フィールド | 型 | 説明 |",
        "required": "*必須*", "empty": "空のオブジェクト", "see": "（{} を参照）", "common": "共通オブジェクト",
        "in": "（{} で使用）",
        "refs": "**ref** は参照先とその名前をまとめた参照です: `{\"ref\": \"<種類>:<id>\", \"names\": {…}}`。"
                "値があれば、歌手には `role`、`featured`、`joint` が、クレジットには `affiliation`、`fullwidth`、`role` が付きます。"
                "筆名や旧名で載ったクレジットには `credited_name` があり、`names` はその名前のものです。不明な値は null です。",
        "tracks": "形態のトラックごとに1行。クレジットとリンク付き",
        "recordings": "音源ごとに1行。クレジットと代表リンク付き",
        "mood_head": "| ラベル | ja | rom | ko | 条件 |",
    },
}
# the mood rules in words (`audio.MOOD_RULES` is the English; a test keeps the keys equal)
MOOD_RULES_TEXT = {
    "ko": {"upbeat": "`bpm` 140 이상", "slow": "`bpm` 100 미만", "bright": "장조", "wistful": "단조"},
    "ja": {"upbeat": "`bpm` 140以上", "slow": "`bpm` 100未満", "bright": "長調", "wistful": "短調"},
}
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


def _status(ds: Dataset, files: dict[str, bytes], lang: str = "en") -> tuple[str, dict[str, int]]:
    assert ds.layout is not None
    w = TEXT[lang]
    rows = [w["status_head"], "| :-- | :-: | --: | --: | --: | :-- |"]
    total = {"albums": 0, "tracks": 0, "linked": 0}
    for g in ds.layout.integrated_order:
        p = _project(ds, g)
        name = (getattr(p.names, NAME_LANG[lang]) if p else None) or g
        albums = _load(files, f"albums/{g}/{g}.json") or []
        tracks = [s for a in albums for s in a["songs"]]
        linked = sum(1 for s in tracks if s["link"] != "NA")
        links = []
        if albums:
            links.append(f"{w['albums']} [CSV](albums/{g}/{g}.csv) · [JSON](albums/{g}/{g}.json)")
            links.append(f"{w['songs']} [JSON](songs/{g}/{g}.json)")
        if f"members/{g}.csv" in files:
            links.append(f"{w['members']} [CSV](members/{g}.csv)")
        if f"concerts/{g}/{g}.json" in files:
            links.append(f"{w['concerts']} [JSON](concerts/{g}/{g}.json)")
        if not albums:
            links.append(w["planned"])
        latest = max((a["release"] for a in albums if a["release"]), default="—")
        rows.append(f"| **{name}** | {latest} | {len(albums) or '—'} | {len(tracks) or '—'} | "
                    f"{_pct(linked, len(tracks)) if tracks else '—'} | {' · '.join(links)} |")
        total["albums"] += len(albums)
        total["tracks"] += len(tracks)
        total["linked"] += linked
    return "\n".join(rows), total


def _upcoming(ds: Dataset, lang: str = "en") -> str:
    assert ds.layout is not None
    out = []
    for g, f in ds.layout.albums.items():
        for e in f.entries:
            rel = ds.releases[e.release]
            if rel.status == "announced":
                p = _project(ds, g)
                out.append(f"**{rel.title.ja}** ({(getattr(p.names, NAME_LANG[lang]) if p else None) or g}, {rel.release_date})")
    return ("> [!TIP]\n> " + TEXT[lang]["upcoming"] + "; ".join(sorted(set(out)))) if out else ""


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


# --- DB schema ----------------------------------------------------------------

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
        if origin is Annotated:  # a constrained scalar (Birthday) is shown as its base type
            parts.append(_type(get_args(a)[0]))
        elif origin is list:
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


def _default(f: FieldInfo, lang: str = "en") -> str:
    if f.is_required():
        return TEXT[lang]["required"]
    value = f.get_default(call_default_factory=True)
    if value is None:
        return "—"
    if isinstance(value, BaseModel):
        return TEXT[lang]["empty"]
    return f"`{json.dumps(value, ensure_ascii=False)}`"


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def _model_table(cls: type[BaseModel], home: dict[type[BaseModel], str], here: str, lang: str = "en") -> str:
    rows = [TEXT[lang]["field_head"], "| :-- | :-- | :-- | :-- |"]
    for name, f in cls.model_fields.items():
        desc = f.description or ""
        if choices := _choices(f.annotation):
            desc += " One of " + ", ".join(f"`{c}`" for c in choices) + "."
        kind = _type(f.annotation)
        elsewhere = sorted({home[c] for c in _nested(f.annotation) if c not in COMMON and home.get(c) != here})
        if elsewhere:  # an object described under another file
            kind += TEXT[lang]["see"].format(", ".join(f"`{w}`" for w in elsewhere))
        rows.append(f"| `{f.alias or name}` | {kind} | {_default(f, lang)} | {_cell(desc)} |")
    return "\n".join(rows)


def _view_table(fields: dict[str, tuple[str, str]], lang: str = "en") -> str:
    rows = [TEXT[lang]["view_head"], "| :-- | :-- | :-- |"]
    rows += [f"| `{k}` | {t} | {_cell(d)} |" for k, (t, d) in fields.items()]
    return "\n".join(rows)


def _details(summary: str, body: list[str]) -> str:
    return "<details>\n<summary>" + summary + "</summary>\n\n" + "\n\n".join(body) + "\n\n</details>"


def db_schema(lang: str = "en") -> str:
    """The DB schema section: a table per entity file and its nested objects, then the two views. Every
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
        raise ValueError(f"model fields without a docstring (their description in the DB schema): {sorted(set(missing))}")

    w = TEXT[lang]
    blocks = [_details(f"{w['common']}: <b>Names</b>, <b>Evidence</b>",
                       [f"**{c.__name__}**: {c.__doc__}\n\n{_model_table(c, home, 'common', lang)}" for c in COMMON])]
    for kind in SCHEMA_ORDER:
        sub, cls, _ = LAYOUT[kind]
        here = f"{sub}.json"
        body = [_model_table(cls, home, here, lang)]
        body += [f"**{c.__name__}**{w['in'].format(used)}\n\n{_model_table(c, home, here, lang)}" for c, used in owned[here]]
        title = ", ".join(f"<b>{c.__name__}</b>" for c in [cls, *(c for c, _ in owned[here])])
        blocks.append(_details(f"<code>{here}</code>: {title}", body))
    blocks.append(_details(f"<code>tracks.json</code>: {w['tracks']}", [w["refs"], _view_table(TRACK_FIELDS, lang)]))
    blocks.append(_details(f"<code>recordings.json</code>: {w['recordings']}", [_view_table(RECORDING_FIELDS, lang)]))
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


def _moods(lang: str = "en") -> str:
    """The mood labels of `recordings.json` with their names and rules (D61)."""
    from .audio import MOOD_RULES, MOODS

    rules = MOOD_RULES_TEXT.get(lang, MOOD_RULES)
    rows = [TEXT[lang]["mood_head"], "| :-- | :-- | :-- | :-- | :-- |"]
    rows += [f"| `{k}` | {n.ja} | {n.rom} | {n.ko} | {rules[k]} |" for k, (n, _) in MOODS.items()]
    return "\n".join(rows)


def readme_values(ds: Dataset, files: dict[str, bytes], lang: str = "en") -> dict[str, str]:
    assert ds.meta is not None and ds.layout is not None
    w = TEXT[lang]
    table, total = _status(ds, files, lang)
    integrated = (_load(files, "TakasakiInfo.json") or {}).get("data", [])
    no_kana = sum(1 for r in integrated if not r.get("pronunciation"))
    day = ds.meta.db_last_update[:10]
    planned = [((getattr(p.names, NAME_LANG[lang]) if (p := _project(ds, g)) else None) or g)
               for g in ds.layout.integrated_order if g not in ds.layout.albums]
    groups = [g for g in ds.layout.integrated_order if g in ds.layout.albums]
    return {
        "UPDATED": day,
        "BADGE_DATA": _badge(w["badge_data"], day, "e4007f"),
        "BADGE_TRACKS": _badge(w["badge_tracks"], f"{len(integrated):,}", "5d9cec"),
        "BADGE_FORMATS": _badge(w["badge_formats"], "CSV · JSON · SQLite", "555"),
        "STATUS_TABLE": table,
        "UPCOMING": _upcoming(ds, lang),
        "TRACKS": f"{len(integrated):,}",
        "ALBUMS": f"{total['albums']:,}",
        "SONGS": f"{_songs(ds):,}",
        "PEOPLE": f"{len(ds.persons):,}",
        "CHARACTERS": f"{len(ds.characters):,}",
        "LINKED": _pct(sum(1 for r in integrated if r["link"] != "NA"), len(integrated)),
        "NO_KANA": f"{no_kana:,}",
        # the groups whose songs are not in yet; nothing once every group is
        "NOT_IN_YET": w["not_in_yet"].format(", ".join(planned)) if planned else "",
        "FILES": _files(ds, NAME_LANG[lang]),
        "CATEGORIES": ", ".join(f"`{g}`" for g in groups + ["Others"]),
        "SONG_EXAMPLE": _song_example(files),
        "ALBUM_EXAMPLE": _album_example(files),
        "CONCERT_EXAMPLE": _concert_example(files),
        "SCHEMA": db_schema(lang),
        "MOODS": _moods(lang),
        "RELEASE_EXAMPLE": _release_example(ds),
        "DISCLAIMER": _disclaimer(ds, "ja" if lang == "ja" else "en"),
        "RIGHTS": {"en": ", ".join(RIGHTS_HOLDERS[:-1]) + ", and " + RIGHTS_HOLDERS[-1],
                   "ko": ", ".join(RIGHTS_HOLDERS), "ja": "、".join(RIGHTS_HOLDERS)}[lang],
        "CDN": CDN,
        "REPO": REPO,
    }


def render_readme(ds: Dataset, files: dict[str, bytes]) -> dict[str, bytes]:
    out = {}
    for name, lang in READMES.items():
        values = readme_values(ds, files, lang)
        text = (TEMPLATES / name).read_text(encoding="utf-8")
        for key, value in values.items():
            text = text.replace("{{" + key + "}}", value)
        left = sorted(set(re.findall(r"\{\{[A-Z_]+\}\}", text)))
        if left:
            raise ValueError(f"{name} template placeholders without a value: {left}")
        out[name] = text.encode("utf-8")
    return out


def build_outputs(ds: Dataset) -> dict[str, bytes]:
    """Every file `takasaki build` writes into the repository: the legacy files, the READMEs and the API's
    OpenAPI document."""
    from .build_legacy import build_legacy
    from .openapi import OUTPUT, render_openapi

    files = build_legacy(ds)
    files |= render_readme(ds, files)
    files[OUTPUT] = render_openapi()
    return files
