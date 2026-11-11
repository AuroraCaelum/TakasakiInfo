"""Apply decisions written into ``automation/review/*.yaml`` (DESIGN.md §7.3).

Decisions:

- ``merge:<kind>:<id>``  merge every ``ref`` in the file into that entity (references are
  rewritten, the merged spellings become aliases, the merged entities are deleted). A person
  can be merged into a character credited in-story (D27)
- ``pen-name:person:<id>`` / ``former-name:person:<id>``  merge, but each merged person stays an alias with its
  names (a pen name / former name) and their credits keep printing it (``credited_name``, D58)
- ``distinct``           the refs are different entities (``distinct_from`` is recorded)
- ``kind:<artist kind>`` reclassify an artist (classify items)
- ``rule``               apply the default rule (latin-ko: ko = ja)
- ``keep:<status>``      keep the value as an approved exception (latin-ko), status official|established
- ``pick:<n>`` / ``none`` choose the YouTube Music album of a ``ytm-album`` item (``pick:e1=1,e2=2`` per edition)
- ``approve``            accept a ``new-names`` file from an official-site import: each item's values (as edited
  in the file) are written to its entity with the item's status, replacing the draft
- ``approve``            accept a ``kana`` file: each item's reading is written to its person, character, work or
  recording with the item's evidence (``names.kana`` / ``title.kana``); nothing else on the entity changes (D58)
- ``done``               the fix was made by hand in data/; just close the item
"""

from __future__ import annotations

import datetime as dt
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
    role = p.role
    if src[0] == "character" and role == src[1]:
        role = dst[1]
    if p.ref != src:
        return p if role == p.role else p.model_copy(update={"role": role})
    if role is not None and dst[0] != "person":
        raise ReviewError(f"person:{src[1]} sings in a role, cannot merge it into {dst[0]}:{dst[1]}")
    # a featured guest or a part of a joint name stays one (D48)
    return m.Performer(**{dst[0]: dst[1]}, role=role, featured=p.featured, joint=p.joint)


def merge(ds: Dataset, refs: list[str], target: str, credited: str | None = None) -> str:
    """Merge every ref into ``target``. ``credited`` (``pen_name`` | ``former``, persons only) keeps each merged
    person as an alias with its names, and their credits keep printing that name (D58)."""
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
        if src[0] == "person" and dst[0] == "artist":
            raise ReviewError(f"cannot merge person {ref} into {target}")
        ent = _table(ds, src[0]).get(src[1])
        if ent is None:
            raise ReviewError(f"unknown {ref!r}")
        if credited and not (src[0] == dst[0] == "person"):
            raise ReviewError(f"{credited} merges a person into a person, not {ref} into {target}")
        _rewrite_credits(ds, src, dst, ent.names.ja if credited else None)
        _rewrite_performer_refs(ds, src, dst)
        if src[0] == "person":
            _rewrite_casting(ds, src[1], dst)
        if credited:
            tgt.aliases.append(m.Alias(text=ent.names.ja, kind=credited, names=ent.names.model_copy(),
                                       note=f"merged from person:{src[1]}"))
        elif hasattr(tgt, "aliases"):
            for lang in ("ja", "rom", "ko"):
                text = getattr(ent.names, lang)
                if text and text != getattr(tgt.names, lang) and all(a.text != text for a in tgt.aliases):
                    tgt.aliases.append(m.Alias(text=text, kind="variant"))
        del _table(ds, src[0])[src[1]]
        merged.append(ref)
    return f"merged {merged} into {target}"


def _rewrite_credits(ds: Dataset, src: tuple[str, str], dst: tuple[str, str], credited: str | None = None) -> None:
    """Credits name a person or a character (D27), so a person can be merged into a character. With ``credited``
    the rewritten credits keep printing that name (a pen name or former name, D58)."""

    def fix(credits: list[m.Credit]) -> None:
        for c in credits:
            if c.ref != src:
                continue
            if dst[0] not in ("person", "character"):
                raise ReviewError(f"{src[0]}:{src[1]} is credited, cannot merge it into {dst[0]}:{dst[1]}")
            c.person, c.character = (dst[1], None) if dst[0] == "person" else (None, dst[1])
            if credited:
                c.credited_name = credited

    for w in ds.works.values():
        fix(w.credits.lyricist)
        fix(w.credits.composer)
        for r in w.recordings:
            fix(r.arranger)
            fix(r.strings_arranger)
            fix(r.brass_arranger)
            if r.credits_override:
                fix(r.credits_override.lyricist)
                fix(r.credits_override.composer)


def _rewrite_casting(ds: Dataset, src: str, dst: tuple[str, str]) -> None:
    for c in ds.characters.values():
        for cast in c.casting:
            if cast.person == src:
                if dst[0] != "person":
                    raise ReviewError(f"person:{src} is a voice actor of {c.id}, cannot merge it into {dst[0]}:{dst[1]}")
                cast.person = dst[1]


def _rewrite_performer_refs(ds: Dataset, src: tuple[str, str], dst: tuple[str, str]) -> None:
    for w in ds.works.values():
        for r in w.recordings:
            r.performers = [_rewrite_performer(p, src, dst) for p in r.performers]
    for rel in ds.releases.values():
        rel.artist_credit = [_rewrite_performer(p, src, dst) for p in rel.artist_credit]
    for c in ds.concerts.values():
        c.cast = [_rewrite_performer(p, src, dst) for p in c.cast]
        for s in c.stops:
            for perf in s.performances:
                perf.cast = [_rewrite_performer(p, src, dst) for p in perf.cast]
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


def _kana_evidence(it: dict[str, Any], today: dt.date) -> m.Evidence:
    return m.Evidence(status=m.Status(it.get("status") or "derived"), source=it.get("source") or None,
                      checked=today if it.get("source") else None, note=it.get("note") or None)


def approve_kana(ds: Dataset, doc: dict[str, Any], today: dt.date) -> str:
    """Decision ``approve`` on a ``kana`` file (D58). Only the reading and its evidence are written.

    - ``person:``/``character:`` items: ``family_kana`` + ``given_kana`` fill the name parts and make ``names.kana``
      (D28 spacing); without them (activity names, names printed with ・) only ``names.kana`` is set
    - ``artist:`` items: ``names.kana``
    - ``work:`` items: ``title.kana``
    - ``recording:<work>#<id>`` items: ``suffix_kana`` is appended to the work's reading as it stands when the
      file is applied (so ``KANA-versions`` follows ``KANA-songs-*``); an item with ``kana`` only sets it as given
    """
    from .text import join_kana_name

    done = 0
    for it in doc.get("items", []):
        ref = str(it.get("ref") or "")
        kind, _, ident = ref.partition(":")
        if it.get("pending"):
            raise ReviewError(f"{ref}: still pending ({it['pending']}); resolve it and remove `pending`, or remove the item")
        ev = _kana_evidence(it, today)
        if kind in ("person", "character"):
            ent = _table(ds, kind)[ident]
            fam, giv = it.get("family_kana"), it.get("given_kana")
            if bool(fam) != bool(giv):
                raise ReviewError(f"{ref}: family_kana and given_kana go together")
            if fam:
                if ent.family_name is None or ent.given_name is None:
                    raise ReviewError(f"{ref}: family_kana/given_kana on a name without a family/given split")
                ent.family_name.kana, ent.given_name.kana = fam, giv
                kana = it.get("kana") or join_kana_name(fam, giv)
            else:
                kana = it.get("kana")
            if not kana:
                raise ReviewError(f"{ref}: no kana")
            ent.names.kana = kana
            ent.evidence["names.kana"] = ev
        elif kind == "artist":  # group and unit names: the reading of the whole name only
            if not it.get("kana"):
                raise ReviewError(f"{ref}: no kana")
            ent = ds.artists[ident]
            ent.names.kana = it["kana"]
            ent.evidence["names.kana"] = ev
        elif kind == "work":
            if not it.get("kana"):
                raise ReviewError(f"{ref}: no kana")
            ent = ds.works[ident]
            ent.title.kana = it["kana"]
            ent.evidence["title.kana"] = ev
        elif kind == "recording":
            work, rec = ds.recording(ident)
            if rec.title is None:
                raise ReviewError(f"{ref}: the recording has no title of its own; its reading is the work's")
            if "suffix_kana" in it:
                if not work.title.kana:
                    raise ReviewError(f"{ref}: work {work.id} has no kana yet to add {it['suffix_kana']!r} to")
                kana = work.title.kana + str(it["suffix_kana"] or "")
            else:
                kana = it.get("kana")
            if not kana:
                raise ReviewError(f"{ref}: no kana")
            rec.title.kana = kana
            rec.evidence["title.kana"] = ev
        else:
            raise ReviewError(f"unsupported ref {ref!r} in a kana file")
        done += 1
    return f"set {done} readings"


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
            elif decision.startswith(("pen-name:", "former-name:")):
                how, _, target = decision.partition(":")
                msg = merge(ds, refs, target, credited="pen_name" if how == "pen-name" else "former")
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
            elif doc.get("type") == "ytm-album":
                from .ytmusic import apply_matches, matches_from_review

                rid, matches = matches_from_review(doc, decision)
                out = apply_matches(None, ds.releases[rid], matches, dt.date.today().isoformat())
                msg = f"set YouTube Music ids on {rid} (+{out.added}, {out.replaced} replaced)"
            elif doc.get("type") == "new-names" and decision == "approve":
                from .official import approve_names

                msg = approve_names(ds, doc, dt.date.today())
            elif doc.get("type") == "kana" and decision == "approve":
                msg = approve_kana(ds, doc, dt.date.today())
            elif decision == "done":
                msg = "closed (fixed by hand)"
            else:
                raise ReviewError(f"unknown decision {decision!r}")
        except (ReviewError, KeyError, ValueError) as e:
            raise ReviewError(f"{path.name}: {e}") from e
        applied.append(Applied(path, msg))
    return applied
