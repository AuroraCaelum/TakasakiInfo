"""Apply decisions written into ``automation/review/*.yaml`` (DESIGN.md §7.3).

Decisions:

- ``merge:<kind>:<id>``  merge every ``ref`` in the file into that entity (references are
  rewritten, the merged spellings become aliases, the merged entities are deleted)
- ``distinct``           the refs are different entities (``distinct_from`` is recorded)
- ``kind:<artist kind>`` reclassify an artist (classify items)
- ``rule``               apply the default rule (latin-ko: ko = ja)
- ``keep:<status>``      keep the value as an approved exception (latin-ko), status official|established
- ``done``               the fix was made by hand in data/; just close the item
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from . import model as m
from .store import Dataset


class ReviewError(ValueError):
    pass


@dataclass
class Applied:
    path: Path
    message: str


def _split_ref(ref: str) -> tuple[str, str]:
    kind, _, ident = ref.partition(":")
    if kind not in ("person", "character", "artist") or not ident:
        raise ReviewError(f"unsupported ref {ref!r}")
    return kind, ident


def _table(ds: Dataset, kind: str) -> dict[str, Any]:
    return {"person": ds.persons, "character": ds.characters, "artist": ds.artists}[kind]


def _rewrite_performer(p: m.Performer, src: tuple[str, str], dst: tuple[str, str]) -> m.Performer:
    if p.ref != src:
        return p
    return m.Performer(**{dst[0]: dst[1]})


def merge(ds: Dataset, refs: list[str], target: str) -> str:
    dst = _split_ref(target)
    if target not in refs:
        raise ReviewError(f"merge target {target!r} is not one of the refs")
    if dst[1] not in _table(ds, dst[0]):
        raise ReviewError(f"unknown {target!r}")
    tgt = _table(ds, dst[0])[dst[1]]
    merged = []
    for ref in refs:
        if ref == target:
            continue
        src = _split_ref(ref)
        if src[0] == "person" and dst[0] != "person":
            raise ReviewError(f"cannot merge person {ref} into {target}")
        ent = _table(ds, src[0]).get(src[1])
        if ent is None:
            raise ReviewError(f"unknown {ref!r}")
        if src[0] == "person":
            _rewrite_person(ds, src[1], dst[1])
        else:
            _rewrite_performer_refs(ds, src, dst)
        if hasattr(tgt, "aliases"):
            for lang in ("ja", "rom", "ko"):
                text = getattr(ent.names, lang)
                if text and text != getattr(tgt.names, lang) and all(a.text != text for a in tgt.aliases):
                    tgt.aliases.append(m.Alias(text=text, kind="variant"))
        del _table(ds, src[0])[src[1]]
        merged.append(ref)
    return f"merged {merged} into {target}"


def _rewrite_person(ds: Dataset, src: str, dst: str) -> None:
    def fix(credits: list[m.Credit]) -> None:
        for c in credits:
            if c.person == src:
                c.person = dst

    for w in ds.works.values():
        fix(w.credits.lyricist)
        fix(w.credits.composer)
        for r in w.recordings:
            fix(r.arranger)
            if r.credits_override:
                fix(r.credits_override.lyricist)
                fix(r.credits_override.composer)
    for c in ds.characters.values():
        for cast in c.casting:
            if cast.person == src:
                cast.person = dst


def _rewrite_performer_refs(ds: Dataset, src: tuple[str, str], dst: tuple[str, str]) -> None:
    for w in ds.works.values():
        for r in w.recordings:
            r.performers = [_rewrite_performer(p, src, dst) for p in r.performers]
    for rel in ds.releases.values():
        rel.artist_credit = [_rewrite_performer(p, src, dst) for p in rel.artist_credit]
    for c in ds.concerts.values():
        for s in c.stops:
            for perf in s.performances:
                for item in perf.setlist:
                    item.performers = [_rewrite_performer(p, src, dst) for p in item.performers]
    if src[0] == "character":
        for a in ds.artists.values():
            for lu in a.lineups:
                lu.members = [dst[1] if x == src[1] else x for x in lu.members]
        if ds.layout:
            for f in ds.layout.members.values():
                for row in f.rows:
                    if row.character == src[1]:
                        row.character = dst[1]
    if src[0] == "artist" and ds.layout and dst[0] == "artist":
        for f in ds.layout.members.values():
            for row in f.rows:
                if row.unit == src[1]:
                    row.unit = dst[1]


def distinct(ds: Dataset, refs: list[str]) -> str:
    parsed = [_split_ref(r) for r in refs]
    for kind, ident in parsed:
        ent = _table(ds, kind)[ident]
        for k2, i2 in parsed:
            if k2 == kind and i2 != ident and i2 not in ent.distinct_from:
                ent.distinct_from.append(i2)
    return f"recorded {refs} as distinct"


def apply_reviews(ds: Dataset, review_dir: Path) -> list[Applied]:
    y = YAML(typ="safe")
    applied: list[Applied] = []
    for path in sorted(review_dir.glob("*.yaml")):
        doc = y.load(path.read_text(encoding="utf-8")) or {}
        decision = doc.get("decision")
        if not decision:
            continue
        decision = str(decision).strip()
        refs = [str(i["ref"]) for i in doc.get("items", []) if isinstance(i, dict) and "ref" in i]
        try:
            if decision.startswith("merge:"):
                msg = merge(ds, refs, decision.removeprefix("merge:"))
            elif decision == "distinct":
                msg = distinct(ds, refs)
            elif decision.startswith("kind:"):
                kind = decision.removeprefix("kind:")
                for ref in refs:
                    k, ident = _split_ref(ref)
                    if k != "artist":
                        raise ReviewError(f"kind: applies to artists, got {ref}")
                    ds.artists[ident] = ds.artists[ident].model_copy(update={"kind": kind})
                    m.Artist.model_validate(ds.artists[ident].model_dump(by_alias=True))
                msg = f"set kind={kind} on {refs}"
            elif decision == "rule" and doc.get("type") == "latin-ko":
                for ref in refs:
                    p = ds.persons[_split_ref(ref)[1]]
                    p.names.ko = p.names.ja
                msg = f"set ko = ja on {refs}"
            elif decision.startswith("keep:") and doc.get("type") == "latin-ko":
                status = m.Status(decision.removeprefix("keep:"))
                for ref in refs:
                    ds.persons[_split_ref(ref)[1]].evidence["names.ko"] = m.Evidence(
                        status=status, note=str(doc.get("decision_note") or "approved in review")
                    )
                msg = f"kept ko as {status.value} exception on {refs}"
            elif decision == "done":
                msg = "closed (fixed by hand)"
            else:
                raise ReviewError(f"unknown decision {decision!r}")
        except (ReviewError, KeyError, ValueError) as e:
            raise ReviewError(f"{path.name}: {e}") from e
        applied.append(Applied(path, msg))
    return applied
