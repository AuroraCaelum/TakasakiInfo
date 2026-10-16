"""One-time migration of the legacy files into the canonical dataset (DESIGN.md §12, M1–M6).

Principle: lossless first. Entity identity is the exact (ja, rom, ko) triple, so
spelling variants become separate entities plus a review item instead of being
merged by guesswork (§5.6, appendix A-1). The only output changes are the ones
the design already approved:

- pronunciation unified per recording (§10.1 #3)
- affiliation rendered as ``名前(所属)`` (D10)
- duplicate rows removed from TakasakiInfo.json (§10.1 #1)
- one owner per YouTube URL + main-URL fallback for identical audio only (D2, §10.1 #4–#5)
- concert setlist titles rendered from the recording they resolve to
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import model as m
from .store import Dataset
from .text import (
    LANGS, is_latin, match_key, nfc, note_version, parse_credit, recording_kind, slugify, split_version,
)

# (legacy file group, project id, legacy category) in tools/Process.py order
GROUPS = [
    ("Muse", "muse", "Muse"),
    ("Aqours", "aqours", "Aqours"),
    ("Nijigaku", "nijigasaki", "Nijigasaki"),
    ("Liella", "liella", "Liella"),
    ("Hasunosora", "hasunosora", "Hasunosora"),
    ("Musical", "musical", "Musical"),
]
GROUP_ARTISTS = {"Aqours", "虹ヶ咲学園スクールアイドル同好会", "Liella!", "蓮ノ空女学院スクールアイドルクラブ", "μ's", "μ’s"}
_EDITION = re.compile(r"^(?P<base>.+?)\s*(?:【(?P<a>[^】]+)】|［(?P<b>[^］]+盤)］|\[(?P<c>[^\]]+盤)\]|（(?P<d>[^）]+盤)）|\((?P<e>[^)]+盤)\))$")
_DISC = re.compile(r"^(?P<base>.+?)\s*\[Disc (?P<n>\d+)\]$")
LEGACY = m.Evidence(status=m.Status.legacy, source="migration:legacy")


@dataclass
class Change:
    kind: str
    where: str
    detail: str


@dataclass
class Review:
    kind: str
    title: str
    items: list[dict[str, Any]]
    note: str = ""


@dataclass
class MigrationResult:
    ds: Dataset
    changes: list[Change] = field(default_factory=list)
    reviews: list[Review] = field(default_factory=list)


class Ids:
    def __init__(self) -> None:
        self.used: set[str] = set()

    def make(self, base: str, fallback: str) -> str:
        base = base or fallback
        ident, n = base, 2
        while ident in self.used:
            ident, n = f"{base}-{n}", n + 1
        self.used.add(ident)
        return ident


def _short_slug(s: str, limit: int = 60) -> str:
    slug = slugify(s)
    if len(slug) <= limit:
        return slug
    cut = slug[:limit]
    return cut.rsplit("-", 1)[0] if "-" in cut else cut


def read_csv_rows(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f))


def _triple(cells: list[str], i: int) -> list[dict[str, str]]:
    if not any(cells[i:i + 3]):
        return []
    parts = [cells[i + k].split(";") for k in range(3)]
    if len({len(p) for p in parts}) != 1:
        raise ValueError(f"ja/rom/ko counts differ: {cells[i:i + 3]}")
    return [{lang: nfc(parts[k][n]) for k, lang in enumerate(LANGS)} for n in range(len(parts[0]))]


class Migrator:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.ds = Dataset()
        self.res = MigrationResult(self.ds)
        self.ids = {k: Ids() for k in ("person", "character", "artist", "work", "release", "city", "venue", "concert")}
        self.person_by_triple: dict[tuple[str, str, str], str] = {}
        self.char_by_triple: dict[tuple[str, str, str], str] = {}
        self.artist_by_triple: dict[tuple[str, str, str], str] = {}
        self.unit_by_ja: dict[str, str] = {}
        self.today = dt.date.today()

    # --- people -------------------------------------------------------------

    def person(self, names: dict[str, str]) -> str:
        key = (names["ja"], names["rom"], names["ko"])
        if key in self.person_by_triple:
            return self.person_by_triple[key]
        pid = self.ids["person"].make(slugify(names["rom"]) or slugify(names["ja"]), "person")
        self.ds.persons[pid] = m.Person(
            id=pid,
            names=m.Names(**names),
            native_script="latin" if is_latin(names["ja"]) else "ja",
            evidence={"names": LEGACY},
        )
        self.person_by_triple[key] = pid
        return pid

    def credits(self, cells: list[str], i: int, where: str) -> list[m.Credit]:
        out = []
        for parts in _triple(cells, i):
            names, aff, role, normalised = parse_credit(parts)
            if normalised:
                self.res.changes.append(Change("affiliation-format", where, f"{parts['rom']!r} → 名前(所属) (D10)"))
            out.append(m.Credit(person=self.person(names), affiliation=aff, role=m.Names(**role) if role else None))
        return out

    def performers(self, cells: list[str], project: str) -> list[m.Performer]:
        out = []
        for parts in _triple(cells, 5):
            key = (parts["ja"], parts["rom"], parts["ko"])
            if key in self.char_by_triple:
                out.append(m.Performer(character=self.char_by_triple[key]))
                continue
            if key not in self.artist_by_triple and parts["ja"] in self.unit_by_ja:
                uid = self.unit_by_ja.pop(parts["ja"])  # first full triple claims the unit from members/*.csv
                self.ds.artists[uid].names = m.Names(**parts)
                self.artist_by_triple[key] = uid
            if key not in self.artist_by_triple:
                aid = self.ids["artist"].make(slugify(parts["rom"]) or slugify(parts["ja"]), "artist")
                kind = "group" if parts["ja"] in GROUP_ARTISTS else "unclassified"
                self.ds.artists[aid] = m.Artist(id=aid, kind=kind, names=m.Names(**parts), evidence={"names": LEGACY})
                self.artist_by_triple[key] = aid
            aid = self.artist_by_triple[key]
            art = self.ds.artists[aid]
            if project not in art.projects:
                art.projects.append(project)
            out.append(m.Performer(artist=aid))
        return out

    # --- members ------------------------------------------------------------

    def import_members(self) -> dict[str, m.LayoutMembersFile]:
        layout: dict[str, m.LayoutMembersFile] = {}
        for group, project, _ in GROUPS:
            path = self.root / "members" / f"{group}.csv"
            if not path.exists():
                continue
            raw = path.read_bytes()
            rows = read_csv_rows(path)
            assert rows[0] == ["日本語", "Romaji", "한국어", "声優", "Seiyuu", "성우", "Unit"], path
            out_rows = []
            for r in rows[1:]:
                names = {lang: nfc(r[k]) for k, lang in enumerate(LANGS)}
                cid = self.ids["character"].make(f"{project}/{slugify(names['rom']) or 'character'}", f"{project}/character")
                casting = [m.Casting(person=self.person(p)) for p in _triple(r, 3)]
                self.ds.characters[cid] = m.Character(
                    id=cid, project=project, names=m.Names(**names), casting=casting, evidence={"names": LEGACY}
                )
                self.char_by_triple[(names["ja"], names["rom"], names["ko"])] = cid
                unit_id = None
                if r[6]:
                    unit_id = self.unit_by_ja.get(r[6]) or next(
                        (a.id for a in self.ds.artists.values() if a.kind == "unit" and a.names.ja == r[6]), None
                    )
                    if unit_id is None:
                        unit_id = self.ids["artist"].make(slugify(r[6]) or f"{project}-unit", f"{project}-unit")
                        self.ds.artists[unit_id] = m.Artist(
                            id=unit_id, kind="unit", projects=[project], names=m.Names(ja=nfc(r[6])),
                            lineups=[m.Lineup(members=[])], evidence={"names": LEGACY},
                        )
                        self.unit_by_ja[r[6]] = unit_id
                    self.ds.artists[unit_id].lineups[0].members.append(cid)
                out_rows.append(m.LayoutMemberRow(character=cid, unit=unit_id))
            layout[group] = m.LayoutMembersFile(bom=raw.startswith(b"\xef\xbb\xbf"), rows=out_rows)
        return layout

    # --- albums -------------------------------------------------------------

    def import_albums(self) -> dict[str, m.LayoutAlbumsFile]:
        # legacy albums = runs of consecutive rows with the same album name (and date)
        files: dict[str, list[tuple[str, list[list[str]]]]] = {}
        boms: dict[str, bool] = {}
        for group, project, _ in GROUPS:
            path = self.root / "albums" / group / f"{group}.csv"
            if not path.exists():
                continue
            boms[group] = path.read_bytes().startswith(b"\xef\xbb\xbf")
            rows = read_csv_rows(path)
            header = rows[0]
            assert header[0] == "Album" and len(header) == 22, path
            runs: list[tuple[str, list[list[str]]]] = []
            for r in rows[1:]:
                r = [nfc(c) for c in r]
                if runs and runs[-1][0] == r[0] and runs[-1][1][-1][17] == r[17]:
                    runs[-1][1].append(r)
                else:
                    runs.append((r[0], [r]))
            files[group] = runs

        rec_by_key: dict[tuple[Any, ...], str] = {}
        work_by_key: dict[tuple[Any, ...], str] = {}
        pron_votes: dict[str, Counter[str]] = defaultdict(Counter)
        release_by_sig: dict[tuple[Any, ...], str] = {}
        layout: dict[str, m.LayoutAlbumsFile] = {}
        self._videos: list[tuple[str, str | None, int, int, str]] = []  # (release, edition, disc, pos, vid)

        for group, project, category in GROUPS:
            if group not in files:
                continue
            entries: list[m.LayoutAlbumEntry] = []
            runs = files[group]
            i = 0
            while i < len(runs):
                name, rows = runs[i]
                # group consecutive edition / disc runs of one release
                members = [(name, rows)]
                em, dm = _EDITION.match(name), _DISC.match(name)
                if em or dm:
                    base = (em or dm)["base"]  # type: ignore[index]
                    j = i + 1
                    while j < len(runs):
                        n2 = runs[j][0]
                        m2 = (_EDITION if em else _DISC).match(n2)
                        if not (m2 and m2["base"] == base and runs[j][1][0][17] == rows[0][17]):
                            break
                        members.append(runs[j])
                        j += 1
                else:
                    base = name
                    j = i + 1
                sig = (base, rows[0][17], tuple(tuple(c[:19] + c[20:]) for _, rs in members for c in rs))
                if sig in release_by_sig:  # same release already listed by another group file
                    rid = release_by_sig[sig]
                    rel = self.ds.releases[rid]
                    for k, (n, rs) in enumerate(members):
                        cat = rs[0][19]
                        entries.append(m.LayoutAlbumEntry(
                            release=rid, album=k, category=cat if cat != rel.legacy.category else None
                        ))
                    i = j
                    continue
                rid = self._new_release(project, category, base, members, em is not None, dm is not None,
                                        rec_by_key, work_by_key, pron_votes)
                release_by_sig[sig] = rid
                for k in range(len(members)):
                    entries.append(m.LayoutAlbumEntry(release=rid, album=k))
                i = j
            layout[group] = m.LayoutAlbumsFile(bom=boms[group], entries=entries)

        self._apply_pron(pron_votes)
        self._assign_video_owners()
        return layout

    def _new_release(self, project, category, base, members, is_edition, is_disc,
                     rec_by_key, work_by_key, pron_votes) -> str:
        first = members[0][1][0]
        day = dt.date.fromisoformat(first[17]) if first[17] else None
        rid = self.ids["release"].make(f"{project}/{day.year if day else 'undated'}-{self._release_slug(base, members)}", f"{project}/release")
        editions: list[m.Edition] = []
        legacy_albums: list[m.LegacyAlbum] = []
        per_edition_tracks: list[tuple[str | None, int, list[m.Track], list[str]]] = []
        cats = Counter(c[19] for _, rs in members for c in rs)
        default_cat = cats.most_common(1)[0][0]
        for k, (name, rows) in enumerate(members):
            ed_id, disc_no = None, 1
            if is_edition:
                em = _EDITION.match(name)
                label = next(g for g in em.groups()[1:] if g)  # type: ignore[union-attr]
                ed_id = f"e{k + 1}"
                editions.append(m.Edition(id=ed_id, label=m.Names(ja=label)))
            elif is_disc:
                disc_no = int(_DISC.match(name)["n"])  # type: ignore[index]
            legacy_albums.append(m.LegacyAlbum(title=name, edition=ed_id, disc=disc_no if is_disc else None))
            tracks, vids = [], []
            for row in rows:
                where = f"{name} #{row[1]}"
                ref = self._recording(project, row, where, rec_by_key, work_by_key, pron_votes)
                tracks.append(m.Track(
                    no=int(row[1]) if row[1] else None,
                    recording=ref,
                    note=row[20] or None,
                    category=row[19] if row[19] != default_cat else None,
                ))
                vids.append(row[18])
            per_edition_tracks.append((ed_id, disc_no, tracks, vids))

        discs: list[m.Disc] = []
        sigs = [[t.model_dump() for t in tr] for _, _, tr, _ in per_edition_tracks]
        if is_edition and all(s == sigs[0] for s in sigs):
            discs.append(m.Disc(disc=1, editions="all", tracks=per_edition_tracks[0][2]))
        else:
            for ed_id, disc_no, tracks, _ in per_edition_tracks:
                discs.append(m.Disc(disc=disc_no, editions=[ed_id] if ed_id else "all", tracks=tracks))

        streaming: list[m.Streaming] = []
        for ed_id, disc_no, tracks, vids in per_edition_tracks:
            entry: dict[str, str] = {}
            for pos, url in enumerate(vids, 1):
                if url and url != "NA":
                    vid = url.removeprefix("https://youtu.be/")
                    assert vid != url, url
                    entry[f"{disc_no}-{pos}"] = vid
                    self._videos.append((rid, ed_id, disc_no, pos, vid))
            if entry:
                streaming.append(m.Streaming(editions=[ed_id] if ed_id else [], tracks=entry))

        rtype = "drama_cd" if "ドラマCD" in base else "bd_bonus" if "BD" in base else "unclassified"
        self.ds.releases[rid] = m.Release(
            id=rid, type=rtype, title=m.Names(ja=base), projects=[project], release_date=day,
            editions=editions, discs=discs, streaming=streaming,
            legacy=m.ReleaseLegacy(category=default_cat, albums=legacy_albums),
            evidence={"tracks": LEGACY},
        )
        return rid

    def _release_slug(self, base: str, members) -> str:
        if is_latin(base) and slugify(base):
            return _short_slug(base)
        lead = match_key(re.split(r"\s*[/／]\s*", base)[0])
        for _, rows in members:
            for r in rows:
                if match_key(r[2]) == lead and r[3]:
                    return _short_slug(r[3])
        if len(slugify(base)) >= 4:  # Latin part of a mixed title: "…Aqours CHRONICLE (2015~2017)"
            return _short_slug(base)
        day = members[0][1][0][17]
        return day[5:].replace("-", "") if day else ""

    def _recording(self, project, row, where, rec_by_key, work_by_key, pron_votes) -> str:
        kind = recording_kind(row[2], row[20])
        performers = self.performers(row, project)
        lyricist = self.credits(row, 8, where)
        composer = self.credits(row, 11, where)
        arranger = self.credits(row, 14, where)
        title = {lang: row[2 + k] for k, lang in enumerate(LANGS)}
        nv = note_version(row[20])
        cred_key = lambda cs: tuple((c.person, c.affiliation, tuple(c.role.model_dump().values()) if c.role else None) for c in cs)  # noqa: E731
        rkey = (tuple(title.values()), tuple(p.ref for p in performers), cred_key(lyricist), cred_key(composer),
                cred_key(arranger), kind, nv)
        if rkey in rec_by_key:
            ref = rec_by_key[rkey]
            pron_votes[ref][row[21]] += 1
            return ref

        base_ja, ver = split_version(title["ja"])
        base = {"ja": base_ja}
        for lang in ("rom", "ko"):
            base[lang] = split_version(title[lang])[0] if ver else title[lang]
        wkind = "drama" if kind == "drama" else "song"
        wkey = (project if wkind == "drama" else None, base_ja, cred_key(lyricist), cred_key(composer), wkind)
        wid = work_by_key.get(wkey)
        if wid is None:
            wid = self.ids["work"].make(f"{project}/{_short_slug(base['rom']) or _short_slug(base_ja)}", f"{project}/work")
            self.ds.works[wid] = m.Work(
                id=wid, kind=wkind, project=project, title=m.Names(**base),
                credits=m.WorkCredits(lyricist=lyricist, composer=composer), recordings=[],
                evidence={"credits": LEGACY},
            )
            work_by_key[wkey] = wid
        work = self.ds.works[wid]
        version = ver or nv
        local = {"off_vocal": "off-vocal", "instrumental": "instrumental", "drama": "main"}.get(kind, "original")
        if version and kind == "vocal":
            local = slugify(split_version(title["rom"])[1] or "") or slugify(version) or local
        used = {r.id for r in work.recordings}
        rec_id, n = local, 2
        while rec_id in used:
            rec_id, n = f"{local}-{n}", n + 1
        rec = m.Recording(
            id=rec_id, kind=kind, title=m.Names(**title), version=version,
            performers=performers, arranger=arranger, evidence={"credits": LEGACY},
        )
        if kind in ("off_vocal", "instrumental"):
            vocal = next((r for r in work.recordings if r.kind == "vocal"), None)
            rec.instrumental_of = vocal.id if vocal else None
        work.recordings.append(rec)
        ref = f"{wid}#{rec_id}"
        rec_by_key[rkey] = ref
        pron_votes[ref][row[21]] += 1
        return ref

    def _apply_pron(self, votes: dict[str, Counter[str]]) -> None:
        """One pronunciation per recording; an empty value loses to a filled one (§10.1 #3)."""
        for ref, counter in votes.items():
            filled = [(n, p) for p, n in counter.items() if p]
            kana = max(filled)[1] if filled else ""
            if len(counter) > 1:
                self.res.changes.append(Change("pronunciation", ref, f"{dict(counter)} → {kana!r}"))
            if len(filled) > 1:
                self.res.reviews.append(Review("pronunciation", f"발음 충돌: {ref}", [{"votes": dict(counter)}]))
            _, rec = self.ds.recording(ref)
            rec.title.kana = kana  # type: ignore[union-attr]
        # drop recording titles identical to the work title
        for work in self.ds.works.values():
            vocal = next((r for r in work.recordings if r.title and r.title.ja == work.title.ja), None)
            work.title.kana = vocal.title.kana if vocal and vocal.title else None
            for rec in work.recordings:
                if rec.title == work.title:
                    rec.title = None

    def _assign_video_owners(self) -> None:
        """Each video id is stored on one track only; other tracks get it back through the
        main-URL fallback when they are the same recording (D2, DESIGN.md §4.2)."""
        by_vid: dict[str, list[tuple[str, str | None, int, int]]] = defaultdict(list)
        for rid, ed, disc, pos, vid in self._videos:
            by_vid[vid].append((rid, ed, disc, pos))
        for vid, uses in by_vid.items():
            if len(uses) < 2:
                continue
            def rec_of(u):
                rel = self.ds.releases[u[0]]
                for d in rel.discs:
                    if d.disc == u[2] and (d.editions == "all" or u[1] in d.editions):
                        return d.tracks[u[3] - 1].recording
                raise KeyError(u)
            def order(u):
                rel = self.ds.releases[u[0]]
                ed_index = [e.id for e in rel.editions].index(u[1]) if u[1] else 0
                # latest release owns a URL shared across releases; within a release the
                # first edition and lowest track own it
                return (-(rel.release_date or dt.date.min).toordinal(), u[0], ed_index, u[2], u[3])
            owner = min(uses, key=order)
            same_recording = len({rec_of(u) for u in uses}) == 1
            for u in uses:
                if u == owner:
                    continue
                rel = self.ds.releases[u[0]]
                for s in rel.streaming:
                    if (not s.editions or u[1] in s.editions) and s.tracks.get(f"{u[2]}-{u[3]}") == vid:
                        del s.tracks[f"{u[2]}-{u[3]}"]
                where = f"{rel.title.ja} {u[1] or ''} {u[2]}-{u[3]} ({rec_of(u)})"
                if same_recording:
                    self.res.changes.append(Change("video-owner", where, f"{vid}: main URL fallback from {owner[0]}"))
                else:
                    self.res.changes.append(Change("video-cleared", where, f"{vid} belongs to {rec_of(owner)} (E11)"))
        for rel in self.ds.releases.values():
            rel.streaming = [s for s in rel.streaming if s.tracks]

    # --- concerts -----------------------------------------------------------

    def import_concerts(self) -> dict[str, list[str]]:
        layout: dict[str, list[str]] = {}
        title_index: dict[str, list[str]] = defaultdict(list)
        key_index: dict[str, list[str]] = defaultdict(list)
        work_index: dict[str, list[str]] = defaultdict(list)
        for work in self.ds.works.values():
            work_index[match_key(work.title.ja)].append(work.id)
            for rec in work.recordings:
                t = (rec.title or work.title).ja or ""
                ref = f"{work.id}#{rec.id}"
                title_index[t].append(ref)
                key_index[match_key(t)].append(ref)
        venue_by_triple: dict[tuple[Any, ...], str] = {}
        for group, project, _ in GROUPS:
            path = self.root / "concerts" / group / f"{group}.json"
            if not path.exists():
                continue
            ids = []
            for c in json.loads(path.read_text(encoding="utf-8")):
                cid = self.ids["concert"].make(f"{project}/{slugify(c['eventCode'])}", f"{project}/concert")
                stops = []
                events = iter(c["events"])
                for k, s in enumerate(c["sights"]):
                    cm = re.match(r"^(?P<city>.+?) \((?P<label>.+)\)$", s["city"])
                    city_name, label = (cm["city"], cm["label"]) if cm else (s["city"], None)
                    city_id = slugify(city_name)
                    self.ds.cities.setdefault(city_id, m.City(id=city_id, names=m.Names(rom=city_name)))
                    vt = tuple(s["venue"][lang] for lang in LANGS)
                    if vt not in venue_by_triple:
                        vid = self.ids["venue"].make(_short_slug(s["venue"]["rom"]), "venue")
                        self.ds.venues[vid] = m.Venue(id=vid, city=city_id, names=m.Names(**s["venue"]))
                        venue_by_triple[vt] = vid
                    perfs = []
                    for day in s["date"]:
                        ev = next(events)
                        if (ev["city"], ev["date"]) != (s["city"], day):
                            raise ValueError(f"{path}: events are not in sights order at {ev['city']} {ev['date']}")
                        items = [self._setlist_item(t, project, title_index, key_index, work_index, f"{cid} {day}")
                                 for t in ev["setlist"]]
                        perfs.append(m.Performance(date=dt.date.fromisoformat(day), setlist=items))
                    stops.append(m.Stop(id=f"{k + 1}-{city_id}", city=city_id, label=label,
                                        venue=venue_by_triple[vt], performances=perfs))
                self.ds.concerts[cid] = m.Concert(
                    id=cid, projects=[project], title=m.Names(**c["title"]), stops=stops,
                    legacy=m.ConcertLegacy(event_code=c["eventCode"]), evidence={"setlist": LEGACY},
                )
                ids.append(cid)
            layout[group] = ids
        return layout

    def _setlist_item(self, text, project, title_index, key_index, work_index, where) -> m.SetlistItem:
        if text.startswith("::"):
            marker = text[2:]
            mm = re.fullmatch(r"(MC|VID)(\d+)", marker)
            if mm:
                return m.SetlistItem(type="mc" if mm[1] == "MC" else "video")  # label set by fix_marker_labels
            kind = {"Encore": "encore", "Double Encore": "double_encore"}.get(marker)
            if kind is None:
                kind = "talk" if "Talk" in marker else "mc" if "MC" in marker else "other"
            return m.SetlistItem(type=kind, label=marker)

        def pick(refs: list[str]) -> str | None:
            in_project = [r for r in refs if self.ds.works[r.split("#")[0]].project == project]
            refs = in_project or refs
            return refs[0] if len(set(refs)) == 1 else None

        exact = title_index.get(text, [])
        ref = pick(exact) if exact else None
        if ref is None and not exact:
            ref = pick(key_index.get(match_key(text), []))
            if ref:
                work, rec = self.ds.recording(ref)
                shown = (rec.title or work.title).ja
                if shown != text:
                    self.res.changes.append(Change("setlist-title", where, f"{text!r} → {shown!r}"))
        if ref:
            return m.SetlistItem(work=ref.split("#")[0], recording=ref)
        works = work_index.get(match_key(text), [])
        if len(set(works)) == 1 and self.ds.works[works[0]].title.ja == text:
            return m.SetlistItem(work=works[0])
        cid = where.split(" ")[0]
        self.res.reviews.append(Review(
            "setlist", f"세트리스트 곡 해석 실패: {text}", [{"ref": f"concert:{cid}", "where": where}],
            note="음반 데이터에 아직 없는 곡이면 Work를 먼저 만들고(§4.6, 음원 없이) 이 항목을 연결",
        ))
        return m.SetlistItem(title_raw=text)

    # --- numbering check for MC/VID markers -----------------------------------

    def fix_marker_labels(self, root_concerts: dict[str, list[str]]) -> None:
        """Numbered markers are regenerated by position; keep the literal label wherever the
        original numbering is not 1, 2, 3… so the output stays identical."""
        for group, ids in root_concerts.items():
            raw = json.loads((self.root / "concerts" / group / f"{group}.json").read_text(encoding="utf-8"))
            for cid, c in zip(ids, raw):
                events = iter(c["events"])
                for stop in self.ds.concerts[cid].stops:
                    for perf in stop.performances:
                        original = next(events)["setlist"]
                        counters: Counter[str] = Counter()
                        for item, text in zip(perf.setlist, original):
                            if item.type in ("mc", "video") and item.label is None:
                                counters[item.type] += 1
                                prefix = "MC" if item.type == "mc" else "VID"
                                if text != f"::{prefix}{counters[item.type]}":
                                    item.label = text[2:]

    # --- projects -----------------------------------------------------------

    def projects(self) -> None:
        def cr(en: str, ja: str) -> list[m.Copyright]:
            return [m.Copyright(text=en, lang="en", source="README.md"), m.Copyright(text=ja, lang="ja", source="README.md")]
        defs = [
            ("muse", m.Names(ja="μ’s", rom="μ’s", ko="μ’s"), "Muse", "Muse",
             cr("©2013 Project Love Live!", "©2013 プロジェクトラブライブ！")),
            ("aqours", m.Names(ja="Aqours", rom="Aqours", ko="Aqours"), "Aqours", "Aqours",
             cr("©2017 Project Love Live! Sunshine!!", "©2017 プロジェクトラブライブ！サンシャイン!!")),
            ("nijigasaki", m.Names(ja="虹ヶ咲学園スクールアイドル同好会", rom="Nijigasaki High School Idol Club", ko="니지가사키 학원 스쿨 아이돌 동호회"),
             "Nijigasaki", "Nijigaku",
             cr("©2022 Project Love Live! Nijigasaki High School Idol Club", "©2022 プロジェクトラブライブ！虹ヶ咲学園スクールアイドル同好会")),
            ("liella", m.Names(ja="Liella!", rom="Liella!", ko="Liella!"), "Liella", "Liella",
             cr("©2022 Project Love Live! Superstar!!", "©2022 プロジェクトラブライブ！スーパースター!!")),
            ("hasunosora", m.Names(ja="蓮ノ空女学院スクールアイドルクラブ", rom="Hasunosora Girls' High School Idol Club", ko="하스노소라 여학원 스쿨 아이돌 클럽"),
             "Hasunosora", "Hasunosora",
             cr("©Project Love Live! Hasunosora Jogakuin School Idol Club", "©プロジェクトラブライブ！蓮ノ空女学院スクールアイドルクラブ")),
            ("musical", m.Names(ja="スクールアイドルミュージカル", rom="School Idol Musical", ko="스쿨 아이돌 뮤지컬"), "Musical", "Musical",
             cr("©Project Love Live! School Idol Musical", "©プロジェクトラブライブ！スクールアイドルミュージカル")),
        ]
        for pid, names, category, file, copyright in defs:
            self.ds.projects[pid] = m.Project(
                id=pid, names=names, legacy=m.ProjectLegacy(category=category, file=file), copyright=copyright,
                evidence={"names": LEGACY},
            )
        self.ds.projects["ikizulive"] = m.Project(
            id="ikizulive",
            names=m.Names(ja="イキヅライブ！ LOVELIVE! BLUEBIRD", rom="Ikizulive! LOVELIVE! BLUEBIRD", ko="이키즈라이부! LOVELIVE! BLUEBIRD"),
            legacy=m.ProjectLegacy(category="Ikizulive", file="Ikizulive"),
            copyright=[m.Copyright(text="©プロジェクトイキヅライブ！", lang="ja",
                                   source="https://www.lovelive-anime.jp/lovehigh/", checked=dt.date(2026, 10, 15))],
            official={"site": "https://www.lovelive-anime.jp/lovehigh/", "youtube": "https://www.youtube.com/@ikizulive",
                      "x": "https://x.com/ikizulive_staff"},
            evidence={"names.ja": m.Evidence(status=m.Status.official, source="https://www.lovelive-anime.jp/lovehigh/",
                                             checked=dt.date(2026, 10, 15)),
                      "names.ko": m.Evidence(status=m.Status.derived, note="결정 D15 (우선 확정)")},
        )

    # --- review items ---------------------------------------------------------

    def collect_reviews(self) -> None:
        ds = self.ds
        # person / character / artist spelling variants that look like the same entity (§5.6, A-1)
        named: list[tuple[str, str, m.Names]] = (
            [("person", p.id, p.names) for p in ds.persons.values()]
            + [("character", c.id, c.names) for c in ds.characters.values()]
            + [("artist", a.id, a.names) for a in ds.artists.values()]
        )
        parent = {f"{k}:{i}": f"{k}:{i}" for k, i, _ in named}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for field_name in ("ja", "rom"):
            seen: dict[str, str] = {}
            for k, i, n in named:
                key = match_key(getattr(n, field_name), person=True)
                if not key:
                    continue
                node = f"{k}:{i}"
                if key in seen:
                    parent[find(node)] = find(seen[key])
                else:
                    seen[key] = node
        clusters: dict[str, list[str]] = defaultdict(list)
        for k, i, _ in named:
            clusters[find(f"{k}:{i}")].append(f"{k}:{i}")
        lookup = {f"{k}:{i}": n for k, i, n in named}
        for members in clusters.values():
            if len(members) < 2:
                continue
            items = [{"ref": ref, "ja": lookup[ref].ja, "rom": lookup[ref].rom, "ko": lookup[ref].ko} for ref in sorted(members)]
            self.res.reviews.append(Review(
                "merge", "동일 대상 후보: " + " / ".join(dict.fromkeys(x["ja"] for x in items)), items,
                note="같은 대상이면 정규 표기를 고르고 병합(decision: merge:<ref>), 다르면 distinct",
            ))
        for a in ds.artists.values():
            if a.kind == "unclassified":
                self.res.reviews.append(Review(
                    "classify", f"아티스트 분류: {a.names.ja}", [{"ref": f"artist:{a.id}", "projects": a.projects}],
                    note="group | unit | solo | cross_unit | collab | special, 또는 캐릭터로 변경",
                ))
        affs = Counter()
        for w in ds.works.values():
            for c in [*w.credits.lyricist, *w.credits.composer, *(x for r in w.recordings for x in r.arranger)]:
                if c.affiliation:
                    affs[c.affiliation] += 1
        keys: dict[str, list[str]] = defaultdict(list)
        for a in affs:
            keys[match_key(a)].append(a)
        for variants in keys.values():
            if len(variants) > 1:
                self.res.reviews.append(Review("affiliation", "소속 표기 변형: " + " / ".join(variants),
                                               [{"text": v, "count": affs[v]} for v in variants]))
        for p in ds.persons.values():
            if p.native_script == "latin" and p.names.ko != p.names.ja:
                self.res.reviews.append(Review(
                    "latin-ko", f"라틴 원어 이름의 ko 표기: {p.names.ja} → {p.names.ko}", [{"ref": f"person:{p.id}"}],
                    note="§5.4: 라틴 원어 이름은 ko도 원문 유지. 예외로 둘 공식·관용 근거가 있으면 evidence names.ko에 기록",
                ))
        for rel in ds.releases.values():
            missing = [t.recording for d in rel.discs for t in d.tracks if t.no is None]
            if missing:
                self.res.reviews.append(Review("legacy-row", f"앨범명·트랙 번호 누락: {rel.id}",
                                               [{"release": rel.id, "recordings": missing}]))

    def run(self) -> MigrationResult:
        self.projects()
        members_layout = self.import_members()
        albums_layout = self.import_albums()
        concerts_layout = self.import_concerts()
        self.fix_marker_labels(concerts_layout)
        self.collect_reviews()
        self.ds.layout = m.LegacyLayout(
            integrated_order=[g for g, _, _ in GROUPS],
            albums=albums_layout, members=members_layout, concerts=concerts_layout,
        )
        self.ds.meta = m.Meta(schema_version="0.1.0",
                              db_last_update=dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
        return self.res


def migrate(root: Path) -> MigrationResult:
    return Migrator(root).run()
