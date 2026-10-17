"""Validation rules (DESIGN.md §8). Errors block merging; warnings are reported in the PR.

Entities that belong to an open review item (``automation/review/*.yaml``) are
reported as warnings instead of errors: the review item is the pending fix.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from ruamel.yaml import YAML

from . import model as m
from .build_legacy import edition_ids, edition_tracks, own_video
from .store import Dataset
from .text import has_kana, has_kana_or_kanji, has_kanji, join_ja_name, join_kana_name, match_key


@dataclass
class Finding:
    rule: str
    level: str  # "error" | "warn"
    where: str
    message: str

    def __str__(self) -> str:
        return f"[{self.rule}] {self.where}: {self.message}"


def _bare(name: str) -> str:
    """A name without separators, for comparing it with its family/given parts."""
    return name.replace(" ", "").replace("　", "").replace("・", "")


def open_review_refs(review_dir: Path) -> set[str]:
    refs: set[str] = set()
    if not review_dir.exists():
        return refs
    y = YAML(typ="safe")
    for path in review_dir.glob("*.yaml"):
        doc = y.load(path.read_text(encoding="utf-8")) or {}
        if doc.get("decision"):
            continue
        for item in doc.get("items", []):
            for key in ("ref", "release", "recording"):
                if isinstance(item, dict) and key in item:
                    refs.add(str(item[key]))
    return refs


def validate(ds: Dataset, review_dir: Path | None = None) -> list[Finding]:
    pending = open_review_refs(review_dir) if review_dir else set()
    out: list[Finding] = []

    def add(rule: str, where: str, msg: str, refs: tuple[str, ...] = ()) -> None:
        level = "error" if rule.startswith("E") else "warn"
        if level == "error" and refs and any(r in pending for r in refs):
            level = "warn"
            msg += " (open review item)"
        out.append(Finding(rule, level, where, msg))

    # E2: references
    def need(table: dict, ident: str | None, where: str, what: str) -> None:
        if ident is not None and ident not in table:
            add("E2", where, f"unknown {what} {ident!r}")

    def perf(p: m.Performer, where: str) -> None:
        need(ds.artists, p.artist, where, "artist")
        need(ds.characters, p.character, where, "character")
        need(ds.persons, p.person, where, "person")
        need(ds.characters, p.role, where, "character (role)")

    def creds(cs: list[m.Credit], where: str) -> None:
        for c in cs:
            need(ds.persons, c.person, where, "person")
            need(ds.characters, c.character, where, "character")

    for c in ds.characters.values():
        need(ds.projects, c.project, f"character:{c.id}", "project")
        for cast in c.casting:
            need(ds.persons, cast.person, f"character:{c.id}", "person")
    for a in ds.artists.values():
        for p in a.projects:
            need(ds.projects, p, f"artist:{a.id}", "project")
        for lu in a.lineups:
            for mem in lu.members:
                need(ds.characters, mem, f"artist:{a.id}", "character")
    for w in ds.works.values():
        need(ds.projects, w.project, f"work:{w.id}", "project")
        creds(w.credits.lyricist + w.credits.composer, f"work:{w.id}")
        ids = {r.id for r in w.recordings}
        for r in w.recordings:
            where = f"recording:{w.id}#{r.id}"
            for p in r.performers:
                perf(p, where)
            creds(r.arranger, where)
            if r.credits_override:
                creds(r.credits_override.lyricist + r.credits_override.composer, where)
            if r.instrumental_of and r.instrumental_of not in ids:
                add("E2", where, f"instrumental_of {r.instrumental_of!r} is not a recording of this work")
    for rel in ds.releases.values():
        for p in rel.projects:
            need(ds.projects, p, f"release:{rel.id}", "project")
        eds = {e.id for e in rel.editions}
        for d in rel.discs:
            if d.editions != "all":
                for e in d.editions:
                    if e not in eds:
                        add("E2", f"release:{rel.id}", f"disc {d.disc} names unknown edition {e!r}")
            for t in d.tracks:
                try:
                    ds.recording(t.recording)
                except KeyError:
                    add("E2", f"release:{rel.id}", f"unknown recording {t.recording!r}")
        for la in rel.legacy.albums:
            if la.edition and la.edition not in eds:
                add("E2", f"release:{rel.id}", f"legacy album names unknown edition {la.edition!r}")
    for c in ds.concerts.values():
        for s in c.stops:
            need(ds.cities, s.city, f"concert:{c.id}", "city")
            need(ds.venues, s.venue, f"concert:{c.id}", "venue")
            for p in s.performances:
                for item in p.setlist:
                    where = f"concert:{c.id} {p.date}"
                    need(ds.works, item.work, where, "work")
                    if item.recording:
                        try:
                            ds.recording(item.recording)
                        except KeyError:
                            add("E2", where, f"unknown recording {item.recording!r}")
                    if item.type == "song" and not (item.work or item.recording):
                        add("E9", where, f"setlist song not resolved to a work: {item.title_raw!r}",
                            refs=(f"concert:{c.id}",))
    if ds.layout:
        for group, f in ds.layout.albums.items():
            for e in f.entries:
                if e.release not in ds.releases:
                    add("E2", f"layout:albums/{group}", f"unknown release {e.release!r}")
                elif e.album >= len(ds.releases[e.release].legacy.albums):
                    add("E2", f"layout:albums/{group}", f"{e.release} has no legacy album #{e.album}")
        for group, mf in ds.layout.members.items():
            for r in mf.rows:
                need(ds.characters, r.character, f"layout:members/{group}", "character")
                need(ds.artists, r.unit, f"layout:members/{group}", "artist")
        for group, ids in ds.layout.concerts.items():
            for i in ids:
                need(ds.concerts, i, f"layout:concerts/{group}", "concert")

    # E4 / W1: one person per name
    by_key: dict[str, list[str]] = defaultdict(list)
    for p in ds.persons.values():
        k = match_key(p.names.ja, person=True)
        if k:
            by_key[k].append(p.id)
    for k, ids in by_key.items():
        if len(ids) > 1:
            distinct = all(b in ds.persons[a].distinct_from or a in ds.persons[b].distinct_from
                           for a in ids for b in ids if a != b)
            if not distinct:
                add("E4", "persons", f"same name key for {ids}", refs=tuple(f"person:{i}" for i in ids))

    # E5: track numbering
    for rel in ds.releases.values():
        for d in rel.discs:
            nos = [t.no for t in d.tracks]
            if any(n is None for n in nos):
                add("W5", f"release:{rel.id}", f"disc {d.disc} has tracks without a number")
            elif nos != list(range(1, len(nos) + 1)):
                add("E5", f"release:{rel.id}", f"disc {d.disc} track numbers are {nos}, expected 1..{len(nos)}")

    # E6 / E7: scripts
    named = (
        [(f"person:{p.id}", p.names) for p in ds.persons.values()]
        + [(f"character:{c.id}", c.names) for c in ds.characters.values()]
        + [(f"artist:{a.id}", a.names) for a in ds.artists.values()]
    )
    for ref, n in named:
        if has_kana_or_kanji(n.rom):
            add("E6", ref, f"rom contains kana/kanji: {n.rom!r}", refs=(ref,))
        if has_kana(n.ko):
            add("E6", ref, f"ko contains kana: {n.ko!r}", refs=(ref,))
    # an affiliation is printed in every language column, so a Japanese-script one needs per-language names (D31)
    for w in ds.works.values():
        lists = [w.credits.lyricist, w.credits.composer] + [r.arranger for r in w.recordings]
        lists += [cs for r in w.recordings if r.credits_override for cs in (r.credits_override.lyricist, r.credits_override.composer)]
        for c in (c for cs in lists for c in cs):
            rom, ko = c.affiliation_in("rom"), c.affiliation_in("ko")
            if has_kana_or_kanji(rom) or has_kana(ko):
                add("E6", f"work:{w.id}", f"affiliation {c.affiliation!r} has Japanese script in rom/ko; give it per-language names")
    for p in ds.persons.values():
        ko_ev = p.evidence.get("names.ko")
        approved = ko_ev is not None and ko_ev.status in (m.Status.official, m.Status.established)
        if p.native_script == "latin" and p.names.ko != p.names.ja and not approved:
            add("E7", f"person:{p.id}", f"Latin-native name has ko {p.names.ko!r} (expected {p.names.ja!r})",
                refs=(f"person:{p.id}",))

    # E12 / W15: name parts and Japanese name spacing (D26, D28)
    split_names = (
        [(f"person:{p.id}", p) for p in ds.persons.values()]
        + [(f"character:{c.id}", c) for c in ds.characters.values()]
    )
    for where, ent in split_names:
        n = ent.names
        if ent.family_name is None and ent.given_name is None:
            if has_kanji(n.ja) and n.rom and len(n.rom.split()) == 2:
                add("W15", where, f"Japanese name without family/given split: {n.ja!r}")
            continue
        fam, giv = ent.family_name or m.Names(), ent.given_name or m.Names()
        for lang in ("ja", "kana", "rom", "ko"):
            full, f, g = getattr(n, lang), getattr(fam, lang), getattr(giv, lang)
            if f is None and g is None:
                continue
            if not (f and g and full) or _bare(full) not in (_bare(f + g), _bare(g + f)):
                add("E12", where, f"{lang}: family {f!r} + given {g!r} does not make {full!r}", refs=(where,))
            elif lang == "ja" and "・" not in full and (has_kanji(f) or has_kanji(g)) and full != join_ja_name(f, g):
                # all-kana names follow the official notation, so only names with kanji are checked
                add("E12", where, f"ja {full!r} breaks the spacing rule (expected {join_ja_name(f, g)!r})", refs=(where,))
            elif lang == "kana" and full != join_kana_name(f, g):
                add("E12", where, f"kana {full!r} needs a space (expected {join_kana_name(f, g)!r})", refs=(where,))

    # E13: no leading/trailing whitespace in names and titles (it leaks into the legacy cells)
    def padded(where: str, n: m.Names | None) -> None:
        for lang, v in (n.model_dump().items() if n else ()):
            if v and v != v.strip():
                add("E13", where, f"{lang} has leading/trailing whitespace: {v!r}")

    for kind, ent in ds.iter_all():
        for attr in ("names", "title", "family_name", "given_name"):
            padded(f"{kind}:{ent.id}", getattr(ent, attr, None))
    for w in ds.works.values():
        for r in w.recordings:
            padded(f"recording:{w.id}#{r.id}", r.title)

    # E14: notes hold only what the builder cannot derive (M3)
    derived = ("Drama Part", "Link is from", "Disc.")
    for rel in ds.releases.values():
        texts = [(f"release:{rel.id} legacy album {la.title!r}", la.note) for la in rel.legacy.albums]
        texts += [(f"release:{rel.id} track {t.no}", t.note) for d in rel.discs for t in d.tracks]
        for where, text in texts:
            hit = next((x for x in derived if text and x in text), None)
            if hit:
                add("E14", where, f"note repeats the derived part {hit!r}: {text!r}")

    # E11: one owner per YouTube video
    owners: dict[str, list[str]] = defaultdict(list)
    for rel in ds.releases.values():
        for ed in edition_ids(rel):
            for disc, pos, _ in edition_tracks(rel, ed):
                vid = own_video(rel, ed, disc, pos)
                if vid:
                    owners[vid].append(f"{rel.id}@{ed or '-'}/{disc}-{pos}")
    for vid, where in owners.items():
        releases = {w.split("@")[0] for w in where}
        shared_entry = len(releases) == 1 and any(
            len(s.editions) > 1 or not s.editions for s in ds.releases[releases.pop()].streaming if vid in s.tracks.values()
        )
        positions = {w.split("@")[1].split("/")[1] for w in where}
        if len(where) > 1 and not (shared_entry and len(positions) == 1):
            add("E11", vid, f"video used by several tracks: {where}")

    # W8: pronunciation
    missing = sum(1 for w in ds.works.values() for r in w.recordings
                  if r.kind in ("vocal",) and not ((r.title or w.title).kana))
    if missing:
        add("W8", "recordings", f"{missing} vocal recordings have no pronunciation (kana)")

    # W14: empty credits. "Not applicable" is an empty list (D25), so only vocal recordings are
    # expected to have every role filled; an empty one there is missing data.
    empty = []
    for w in ds.works.values():
        for r in w.recordings:
            if r.kind != "vocal":
                continue
            credits = r.credits_override or w.credits
            roles = {"performers": r.performers, "lyricist": credits.lyricist,
                     "composer": credits.composer, "arranger": r.arranger}
            gaps = [k for k, v in roles.items() if not v]
            if gaps:
                empty.append(f"{w.id}#{r.id} ({', '.join(gaps)})")
    if empty:
        add("W14", "recordings", f"{len(empty)} vocal recordings have empty credits, e.g. {empty[:3]}")
    return out
