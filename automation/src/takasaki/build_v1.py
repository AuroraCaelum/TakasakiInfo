"""v1 data files (DESIGN.md §10.2): one JSON file per entity type, flat views of tracks and
recordings, JSON Schema for the entity files, and quality metrics.

Every file is wrapped as ``{"schemaVersion", "dbLastUpdate", "count", "data"}``. v1 changes only in
backward-compatible ways (minor bumps); a breaking change becomes v2 (§10.5).
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from ruamel.yaml import YAML

from . import model as m
from .build_legacy import YT, edition_ids, edition_tracks, main_videos, own_video, release_title, track_title
from .store import LAYOUT, Dataset, _plain

V1_FORMAT = "1.0.0"


def _dump(ent: BaseModel) -> dict[str, Any]:
    data = _plain(ent.model_dump(mode="json", by_alias=True, exclude_none=True))
    return {"id": data.pop("id"), **data} if "id" in data else data


def _names(n: m.Names | None) -> dict[str, str] | None:
    return {k: v for k, v in n.model_dump().items() if v} if n else None


def _ref_names(ds: Dataset, kind: str, ident: str) -> dict[str, Any]:
    ent = ds.table(kind)[ident]
    return {"ref": f"{kind}:{ident}", "names": _names(ent.names)}


def _credit(ds: Dataset, c: m.Credit) -> dict[str, Any]:
    out = _ref_names(ds, *c.ref)
    if c.affiliation:
        out["affiliation"] = c.affiliation if isinstance(c.affiliation, str) else _names(c.affiliation)
    if c.fullwidth:
        out["fullwidth"] = True  # the official page prints 名前（所属） (D42)
    if c.role:
        out["role"] = _names(c.role)
    return out


def _performer(ds: Dataset, p: m.Performer) -> dict[str, Any]:
    out = _ref_names(ds, *p.ref)
    if p.role:
        out["role"] = _ref_names(ds, "character", p.role)
    if p.featured:
        out["featured"] = True  # the credit prints it after "feat." (D48)
    if p.joint:
        out["joint"] = True  # one of the performers of a joint name, printed joined with "・" (D48)
    return out


def _wrap(ds: Dataset, data: list[Any]) -> bytes:
    assert ds.meta is not None
    doc = {"schemaVersion": V1_FORMAT, "dbLastUpdate": ds.meta.db_last_update, "count": len(data), "data": data}
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")  # data files are compact


def track_view(ds: Dataset) -> list[dict[str, Any]]:
    """One row per (release, edition, disc, position), announced releases included (§10.2)."""
    mains = main_videos(ds)
    rows = []
    for rel in sorted(ds.releases.values(), key=lambda r: r.id):
        for ed in edition_ids(rel):
            ed_date = next((e.release_date for e in rel.editions if e.id == ed and e.release_date), None)
            day = ed_date or rel.release_date
            for disc, pos, t in edition_tracks(rel, ed):
                work, rec = ds.recording(t.recording)
                title, _ = track_title(work, rec, t)
                credits = rec.credits_override or work.credits
                own = own_video(rel, ed, disc, pos)
                vid = own or mains.get(t.recording)
                rows.append({
                    "id": f"{rel.id}@{ed or '-'}/{disc}-{pos}",
                    "release": rel.id, "edition": ed, "disc": disc, "position": pos, "no": t.no,
                    "status": rel.status, "release_date": day.isoformat() if day else None,
                    "recording": t.recording, "work": work.id, "kind": rec.kind, "version": rec.version,
                    "title": _names(title) | ({"kana": (rec.title or work.title).kana} if (rec.title or work.title).kana else {}),
                    "performers": [_performer(ds, p) for p in rec.performers],
                    "lyricist": [_credit(ds, c) for c in credits.lyricist],
                    "composer": [_credit(ds, c) for c in credits.composer],
                    "arranger": [_credit(ds, c) for c in rec.arranger],
                    "strings_arranger": [_credit(ds, c) for c in rec.strings_arranger],
                    "brass_arranger": [_credit(ds, c) for c in rec.brass_arranger],
                    "link": {"youtube_music": YT + vid if vid else None, "source": "own" if own else "main" if vid else "none"},
                    "note": t.note,
                })
    return rows


def recording_view(ds: Dataset) -> list[dict[str, Any]]:
    mains = main_videos(ds)
    out = []
    for work in sorted(ds.works.values(), key=lambda w: w.id):
        for rec in work.recordings:
            rid = f"{work.id}#{rec.id}"
            credits = rec.credits_override or work.credits
            out.append({
                "id": rid, "work": work.id, "project": work.project, "kind": rec.kind, "version": rec.version,
                "title": _names(rec.title or work.title),
                "performers": [_performer(ds, p) for p in rec.performers],
                "lyricist": [_credit(ds, c) for c in credits.lyricist],
                "composer": [_credit(ds, c) for c in credits.composer],
                "arranger": [_credit(ds, c) for c in rec.arranger],
                "strings_arranger": [_credit(ds, c) for c in rec.strings_arranger],
                "brass_arranger": [_credit(ds, c) for c in rec.brass_arranger],
                "instrumental_of": f"{work.id}#{rec.instrumental_of}" if rec.instrumental_of else None,
                "external_ids": rec.external_ids or None,
                "main_link": YT + mains[rid] if rid in mains else None,
            })
    return out


def quality(ds: Dataset, review_dir: Path | None = None) -> dict[str, Any]:
    """Quality metrics shipped with every release; the README's Database Status is built from them (§10.5)."""
    tracks = track_view(ds)
    recs = [(w, r) for w in ds.works.values() for r in w.recordings]
    vocal = [(w, r) for w, r in recs if r.kind == "vocal"]
    names = [("person", p.names) for p in ds.persons.values()] + [("character", c.names) for c in ds.characters.values()] \
        + [("artist", a.names) for a in ds.artists.values()]
    rel_titles = [release_title(ds, r)[0] for r in ds.releases.values()]
    statuses: Counter[str] = Counter(ev.status.value for _, ent in ds.iter_all() for ev in getattr(ent, "evidence", {}).values())
    open_reviews = 0
    if review_dir and review_dir.exists():
        y = YAML(typ="safe")
        open_reviews = sum(1 for p in review_dir.glob("*.yaml") if not (y.load(p.read_text(encoding="utf-8")) or {}).get("decision"))
    pct = lambda n, d: round(100 * n / d, 1) if d else None  # noqa: E731
    by_project: dict[str, dict[str, Any]] = {}
    for p in sorted(ds.projects):
        rels = [r for r in ds.releases.values() if p in r.projects]
        dates = [r.release_date for r in rels if r.release_date and r.status != "announced"]
        ptracks = [t for t in tracks if t["release"].split("/")[0] == p]
        by_project[p] = {
            "releases": len(rels),
            "tracks": len(ptracks),
            "latest_release": max(dates).isoformat() if dates else None,
            "tracks_with_link": pct(sum(1 for t in ptracks if t["link"]["youtube_music"]), len(ptracks)),
        }
    return {
        "counts": {kind: len(ds.table(kind)) for kind in LAYOUT} | {"recordings": len(recs), "tracks": len(tracks)},
        "fill": {
            "vocal_recordings_with_kana": pct(sum(1 for w, r in vocal if (r.title or w.title).kana), len(vocal)),
            "names_with_ko": pct(sum(1 for _, n in names if n.ko), len(names)),
            "names_with_rom": pct(sum(1 for _, n in names if n.rom), len(names)),
            "release_titles_with_ko": pct(sum(1 for t in rel_titles if t.ko), len(rel_titles)),
            "release_titles_with_rom": pct(sum(1 for t in rel_titles if t.rom), len(rel_titles)),
            "tracks_with_link": pct(sum(1 for t in tracks if t["link"]["youtube_music"]), len(tracks)),
            "links_own": sum(1 for t in tracks if t["link"]["source"] == "own"),
            "links_main": sum(1 for t in tracks if t["link"]["source"] == "main"),
            "links_none": sum(1 for t in tracks if t["link"]["source"] == "none"),
        },
        "evidence_status": dict(sorted(statuses.items())),
        "open_reviews": open_reviews,
        "projects": by_project,
    }


def build_v1(ds: Dataset, review_dir: Path | None = None) -> dict[str, bytes]:
    """Return {path under dist/: bytes}: ``v1/<entity>.json``, ``v1/<view>.json``, ``v1/schema/*.json``, ``v1/quality.json``."""
    out: dict[str, bytes] = {}
    for kind, (sub, cls, _) in LAYOUT.items():
        ents = sorted(ds.table(kind).values(), key=lambda e: e.id)  # type: ignore[attr-defined]
        dumps = [_dump(e) for e in ents]
        if kind == "release":  # rom and ko made from the song titles (D39)
            dumps = [d | {"title": _names(release_title(ds, e)[0])} for d, e in zip(dumps, ents)]
        out[f"v1/{sub}.json"] = _wrap(ds, dumps)
        schema = cls.model_json_schema(by_alias=True)
        schema["$id"] = f"https://github.com/AuroraCaelum/TakasakiInfo/v1/schema/{sub}.json"
        out[f"v1/schema/{sub}.json"] = json.dumps(schema, ensure_ascii=False, indent=1).encode("utf-8")
    out["v1/tracks.json"] = _wrap(ds, track_view(ds))
    out["v1/recordings.json"] = _wrap(ds, recording_view(ds))
    assert ds.meta is not None
    out["v1/quality.json"] = json.dumps({"schemaVersion": V1_FORMAT, "dbLastUpdate": ds.meta.db_last_update,
                                         **quality(ds, review_dir)}, ensure_ascii=False, indent=1).encode("utf-8")
    return out

