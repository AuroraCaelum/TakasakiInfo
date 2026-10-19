"""Official-site importer shared by the project adapters (DESIGN.md §6.1, §7.2 ③).

A project adapter (``ikizulive``, ``hasunosora``) reads its site into the observations below and
describes the project in a ``Spec``. The importer resolves what was read against ``data/`` and
upserts the project's characters, artists, works and releases. A name that is not in the dictionary
yet (new staff, members, units, song titles) goes to a ``new-names`` review file first: its readings
are filled in there, the next run creates the entity as a draft, and ``takasaki review apply``
approves it (E3 keeps drafts out of the legacy files until then).

A release migrated from the legacy files has no official link yet. The importer finds it by date
and title, adds what the page knows (link, type, label, editions, artist credit) and compares the
tracks instead of rewriting them.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import model as m
from .official import NameReviews, item_values
from .store import Dataset
from .text import is_latin, match_key, slugify, split_version


class ParseError(ValueError):
    pass


# --- credits ----------------------------------------------------------------------

ROLE = {"作詞": "lyricist", "作曲": "composer", "編曲": "arranger"}
# string arrangements: the legacy files only ever had the main arranger, so they are left out
IGNORED_ROLES = {"弦編曲"}
_ROLE_WORD = r"(?:弦編曲|作詞|作曲|編曲)"
_ROLES = rf"{_ROLE_WORD}(?:\s*[／/・]\s*{_ROLE_WORD})*"
_AFFILIATION = re.compile(r"^(.*?)\s*[（(]([^()（）]+)[)）]$")


@dataclass
class CreditName:
    name: str
    affiliation: str | None = None


def parse_credit_line(line: str) -> dict[str, list[CreditName]]:
    """``作詞：畑 亜貴　作曲/編曲：光増ハジメ (FirstCall)`` → {lyricist: [畑 亜貴], composer/arranger: [光増ハジメ (FirstCall)]}.
    Roles may also be joined with ``・`` (``作曲・編曲：…``); ``弦編曲`` is read and dropped."""
    out: dict[str, list[CreditName]] = {}
    # a name may contain spaces, so segments are split only before "<roles>："
    for seg in re.split(rf"\s+(?={_ROLES}\s*[：:])", line.strip()):
        mt = re.match(rf"^({_ROLES})\s*[：:]\s*(.+)$", seg)
        if not mt:
            raise ParseError(f"not a credit segment: {seg!r} in {line!r}")
        roles = [r.strip() for r in re.split(r"[／/・]", mt.group(1))]
        if re.search(r"[：:]", mt.group(2)):  # a label this parser does not know ("歌：…")
            raise ParseError(f"unknown credit label in {seg!r}")
        names = []
        for part in _split_names(mt.group(2).strip()):
            am = _AFFILIATION.match(part.strip())
            if am:
                names.append(CreditName(am.group(1).strip(), am.group(2).strip().replace("’", "'")))
            else:
                names.append(CreditName(part.strip()))
        for r in roles:
            if r not in IGNORED_ROLES:
                out[ROLE[r]] = names
    return out


def _split_names(text: str) -> list[str]:
    """Names joined by ``・``, ``、``, ``&`` or ``,`` (``Fi’Ne, Yuqui-lah``); a comma inside an
    affiliation stays (``Hiroki Sagawa (Relic Lyric, inc.)``)."""
    out, cur, depth = [], "", 0
    for ch in text:
        if ch in "(（":
            depth += 1
        elif ch in ")）":
            depth -= 1
        if depth == 0 and ch in "・、&＆,，":
            out.append(cur)
            cur = ""
        else:
            cur += ch
    return [p.strip() for p in out + [cur] if p.strip()]


def is_credit_line(line: str) -> bool:
    return re.match(rf"^{_ROLES}\s*[：:]", line) is not None


# --- observations ---------------------------------------------------------------------


@dataclass
class Performers:
    artist: str | None  # "いきづらい部！", "CHAKI！"; None for a list of members only
    group: str | None  # "いきづらい部！" when the line says "… from いきづらい部！"
    members: list[tuple[str, str]] = field(default_factory=list)  # (character, voice actress) as printed
    artists: list[str] = field(default_factory=list)  # several artists credited together ("A＆B＆C")


@dataclass
class TrackObs:
    no: int
    title: str
    performers: Performers | None = None
    credits: dict[str, list[CreditName]] = field(default_factory=dict)
    disc: int = 1


@dataclass
class EditionObs:
    label: str | None
    catalog: str | None
    media: str | None = None  # as printed: "CD+BD+グッズ", "CDのみ", "配信"


@dataclass
class ReleaseObs:
    url: str
    series: str
    title: str
    release_date: dt.date
    performers: Performers
    editions: list[EditionObs]
    tracks: list[TrackObs]
    links: dict[str, str]
    note: str | None = None  # e.g. "各種音楽配信サービスでは9月3日(水)配信開始予定です。"
    type: str | None = None  # release type when the page says it (else read from the catalog number)
    urls: list[str] = field(default_factory=list)  # every page of the release (one per edition), url first

    @property
    def page_id(self) -> str:
        return page_id(self.url)

    @property
    def pages(self) -> list[str]:
        return self.urls or [self.url]


def page_id(url: str) -> str:
    """``…?p=01_4741`` → ``01_4741``; ``…/music/27/`` → ``27``."""
    return url.rsplit("=", 1)[-1] if "=" in url else url.rstrip("/").rsplit("/", 1)[-1]


@dataclass
class MemberObs:
    name: str  # as printed (official notation)
    rom_family_first: str  # "Takahashi Polka"
    grade: str | None
    cv: str
    cv_rom_family_first: str


@dataclass
class Site:
    members: list[MemberObs]
    releases: list[ReleaseObs]  # oldest first
    member_url: str
    skipped: list[str] = field(default_factory=list)  # pages left out while collecting, with the reason


@dataclass(frozen=True)
class Spec:
    """What the importer needs to know about a project."""

    project: str
    group_name: str  # the project's group as printed ("いきづらい部！")
    legacy_group: str  # its legacy category and file (D3)
    review_prefix: str  # new-names files: "<prefix>-members.yaml", "-artists", "-persons", "-titles"
    skip: dict[str, str] = field(default_factory=dict)  # page id -> why the release is left to a later phase
    lineups_from_site: bool = True  # False keeps the dated lineups in data/ (Hasunosora, D33)

    def review_file(self, kind: str) -> str:
        part = {"member": "members", "character": "members", "artist": "artists", "person": "persons",
                "work": "titles", "release": "titles"}[kind]
        return f"{self.review_prefix}-{part}.yaml"


@dataclass
class Report:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)  # names whose readings are not filled in yet
    conflicts: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _media(printed: str | None) -> list[str]:
    if (printed or "").strip() == "配信":
        return ["digital"]
    out: list[str] = []
    for part in re.split(r"[+＋]", (printed or "").replace("のみ", "")):
        mt = re.fullmatch(r"(\d*)\s*(CD|BD|DVD)", part.strip())
        if mt:
            out += [mt.group(2)] * int(mt.group(1) or 1)
    return out


def _split_ja(printed: str, family_rom: str) -> tuple[str, str] | None:
    """Family/given split of a printed name when the notation shows it: a space, or the boundary
    between a kanji family name and a kana given name. All-kanji names without a space need a reader."""
    if " " in printed:
        fam, giv = printed.split(" ", 1)
        return fam, giv
    mt = re.fullmatch(r"([㐀-鿿々ヶ]+)([぀-ゟ゠-ヿ]+)", printed)
    return (mt.group(1), mt.group(2)) if mt else None


def _rom_title(s: str) -> str:
    return unicodedata.normalize("NFKC", s) if is_latin(s) else ""


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


_TERM_VER = re.compile(r"^(\d+)期\s*([A-Za-z]*)\s*Ver\.?$")  # "104期 Ver.", "104期NEW Ver." (Hasunosora school years)
_TITLE_SEP = re.compile(r"\s*[/／]\s*")


def version_labels(ver: str) -> tuple[str, str, str, str] | None:
    """(recording id, ja, rom, ko) of a version label the importer knows: ``104期 Ver.`` is
    ``104th Ver.`` / ``104기 Ver.`` and ``104期NEW Ver.`` is ``104th NEW Ver.`` (Fandom track lists,
    D38); an all-Latin label is the same in every language. The Japanese is written one way, however
    the page spaces it."""
    tm = _TERM_VER.match(ver)
    if tm:
        n, extra = int(tm.group(1)), tm.group(2)
        rom = f"{_ordinal(n)} {extra} Ver." if extra else f"{_ordinal(n)} Ver."
        return slugify(rom), f"{n}期{extra} Ver." if extra else f"{n}期 Ver.", rom, f"{n}기 {extra} Ver." if extra else f"{n}기 Ver."
    if is_latin(ver):
        label = unicodedata.normalize("NFKC", ver)
        return slugify(label), label, label, label
    return None


def _suffixed(n: m.Names, suffix: str, rom: str | None = None, ko: str | None = None) -> m.Names:
    rom, ko = rom if rom is not None else suffix, ko if ko is not None else suffix
    return m.Names(ja=n.ja + suffix if n.ja else None, rom=n.rom + rom if n.rom else None, ko=n.ko + ko if n.ko else None)


class Importer:
    def __init__(self, ds: Dataset, reviews: NameReviews, today: dt.date, spec: Spec,
                 member_names: set[str] = frozenset()) -> None:  # type: ignore[assignment]
        self.ds, self.reviews, self.today, self.spec = ds, reviews, today, spec
        self.member_keys = {match_key(n) for n in member_names}
        self.page: str | None = None  # the release page being read
        self.report = Report()

    # names ------------------------------------------------------------------------

    def _find_person(self, printed: str) -> str | None:
        key = match_key(printed, person=True)
        for p in self.ds.persons.values():
            if key in {match_key(n, person=True) for n in [p.names.ja, p.names.rom, *(a.text for a in p.aliases)] if n}:
                return p.id
        return None

    def _find(self, kind: str, printed: str) -> str | None:
        key, project = match_key(printed), self.spec.project
        if kind == "character":
            hits = [c.id for c in self.ds.characters.values() if c.project == project and match_key(c.names.ja) == key]
        elif kind == "artist":
            hits = [a.id for a in self.ds.artists.values() if project in a.projects and match_key(a.names.ja) == key]
        elif kind == "work":
            hits = [w.id for w in self.ds.works.values() if w.project == project and match_key(w.title.ja) == key]
        else:
            raise ValueError(kind)
        return hits[0] if hits else None

    def resolve(self, kind: str, printed: str, *, file: str, seed: dict[str, Any] | None = None,
                used_in: str | None = None) -> str | None:
        """Entity id for a printed name: from the dictionary, else from its review item (created
        as a draft once the readings are filled in). None while the item is still pending."""
        found = self._find_person(printed) if kind == "person" else self._find(kind, printed)
        if found:
            self.reviews.note_use(file, kind, printed, used_in)  # a draft created earlier keeps collecting its uses
            return found
        item = self.reviews.item(file, kind, printed, seed or {}, used_in)
        if item.get("ref"):
            ref_kind, _, ident = str(item["ref"]).partition(":")
            if ident in self.ds.table(ref_kind):
                return ident
        try:
            values = item_values(item)
        except (KeyError, ValueError) as e:
            self.report.pending.append(f"{kind} {printed}: {e}")
            return None
        return self._create(kind, item, values, file)

    def _create(self, kind: str, item: dict[str, Any], values: dict[str, Any], file: str) -> str:
        draft = {"status": m.Status.draft, "source": f"automation/review/{file}", "note": "승인 대기 (new-names 리뷰)"}
        if kind == "work":
            rom = values["title"].rom
        else:
            rom = values["names"].rom
        ident = item.get("id") or self._slug_id(kind, rom)
        if ident in self.ds.table(kind):
            raise ValueError(f"{kind} id {ident!r} already exists; set `id:` on the review item for {item['printed']!r}")
        project = self.spec.project
        if kind == "person":
            ent: Any = m.Person(id=ident, **values, evidence={"names": m.Evidence(**draft)})
            if item.get("name_parts") and not values.get("family_name"):
                ent.evidence["name_parts"] = m.Evidence(status=m.Status.derived, note=str(item["name_parts"]))
        elif kind == "character":
            ent = m.Character(id=ident, project=project, **values, evidence={"names": m.Evidence(**draft)})
        elif kind == "artist":
            ent = m.Artist(id=ident, kind=item.get("artist_kind", "unit"), projects=[project], **values,
                           evidence={"names": m.Evidence(**draft)})
        elif kind == "work":
            ent = m.Work(id=ident, project=project, title=values["title"], recordings=[],
                         evidence={"title": m.Evidence(**draft)})
        else:
            raise ValueError(kind)
        self.ds.table(kind)[ident] = ent
        item["ref"] = f"{kind}:{ident}"
        self.report.created.append(f"{kind}:{ident}")
        return ident

    def _slug_id(self, kind: str, rom: str | None) -> str:
        if not rom:
            raise ValueError("rom is needed for the id")
        return f"{self.spec.project}/{slugify(rom)}" if kind in ("character", "work") else slugify(rom)

    # members ----------------------------------------------------------------------

    def members(self, site: Site) -> list[str | None]:
        out = []
        file = self.spec.review_file("member")
        for mem in site.members:
            fam_rom, giv_rom = mem.cv_rom_family_first.split(" ", 1)
            split = _split_ja(mem.cv, fam_rom)
            cv = self.resolve("person", mem.cv, file=file, used_in=f"CV of {mem.name}", seed={
                "family_name": {"ja": split[0] if split else "", "rom": fam_rom},
                "given_name": {"ja": split[1] if split else "", "rom": giv_rom},
                "source": site.member_url,
            })
            fam_rom, giv_rom = mem.rom_family_first.split(" ", 1)
            split = _split_ja(mem.name, fam_rom)
            ch = self.resolve("character", mem.name, file=file, used_in=f"member page ({mem.grade})", seed={
                "family_name": {"ja": split[0] if split else "", "rom": fam_rom},
                "given_name": {"ja": split[1] if split else "", "rom": giv_rom},
                "source": site.member_url,
            })
            if ch and cv:
                char = self.ds.characters[ch]
                if not any(c.person == cv for c in char.casting):
                    char.casting.append(m.Casting(person=cv))
                    char.evidence.setdefault("casting", m.Evidence(status=m.Status.official, source=site.member_url,
                                                                    checked=self.today))
            out.append(ch)
        return out

    def character(self, printed: str) -> str | None:
        return self._find("character", printed)

    def artist(self, printed: str, *, artist_kind: str = "unit", used_in: str | None = None, source: str | None = None) -> str | None:
        seed: dict[str, Any] = {"artist_kind": artist_kind, "source": source or ""}
        if is_latin(printed):
            rom = unicodedata.normalize("NFKC", printed)
            seed["names"] = {"ja": printed, "rom": rom, "ko": rom}
        else:
            seed["names"] = {"ja": printed, "rom": "", "ko": ""}
        return self.resolve("artist", printed, file=self.spec.review_file("artist"), seed=seed, used_in=used_in)

    # credits ----------------------------------------------------------------------

    def credits(self, names: list[CreditName], used_in: str, source: str) -> list[m.Credit] | None:
        out: list[m.Credit | None] = []
        for c in names:
            seed: dict[str, Any] = {"source": source}
            if is_latin(c.name):
                seed |= {"names": {"ja": c.name, "rom": c.name, "ko": c.name}, "native_script": "latin"}
            pid = self.resolve("person", c.name, file=self.spec.review_file("person"), seed=seed, used_in=used_in)
            out.append(m.Credit(person=pid, affiliation=c.affiliation) if pid else None)
        return None if None in out else out  # every name is looked up, so one run lists them all

    # works and releases -----------------------------------------------------------

    def performers(self, p: Performers, group_id: str | None, used_in: str | None = None) -> list[m.Performer] | None:
        names = p.artists or ([p.artist] if p.artist else [])
        if names:
            group_key = match_key(self.spec.group_name)
            ids = [group_id if match_key(n) == group_key else self.artist(n, used_in=used_in, source=self.page) for n in names]
            return [m.Performer(artist=a) for a in ids] if all(ids) else None
        chars = [self.character(name) for name, _ in p.members]
        if not all(chars):
            strangers = [name for name, _ in p.members if match_key(name) not in self.member_keys]
            if strangers:  # otherwise the member is only waiting for review
                self.report.conflicts.append(f"not on the member page: {strangers}")
            return None
        return [m.Performer(character=c) for c in chars]

    def _legacy_match(self, obs: ReleaseObs) -> m.Release | None:
        """A migrated release (no official link yet) with the same date and title."""
        key = match_key(obs.title)
        for rel in self.ds.releases.values():
            if self.spec.project in rel.projects and "official" not in rel.links and rel.release_date == obs.release_date \
                    and (match_key(rel.title.ja) == key or any(match_key(a.title) == key for a in rel.legacy.albums)):
                return rel
        return None

    def _known(self, obs: ReleaseObs) -> m.Release | None:
        pages = set(obs.pages)
        return next((r for r in self.ds.releases.values() if r.links.get("official") in pages), None) or self._legacy_match(obs)

    def release(self, obs: ReleaseObs, group_id: str | None) -> None:
        self.page = obs.url
        known = self._known(obs)
        if known is not None and _migrated(known):
            self._check_legacy(known, obs, group_id)
            return
        placed: list[tuple[int, m.Track]] = []  # (disc, track)
        release_perf = self.performers(obs.performers, group_id, obs.page_id)
        complete = release_perf is not None
        title_item = None
        song_keys = {match_key(_song(t.title)[0]) for t in obs.tracks}
        if known is None and not all(match_key(p) in song_keys for p in _TITLE_SEP.split(obs.title)):
            # a title that is not made of song titles is named in review (its rom gives the id)
            latin = _rom_title(obs.title)  # an all-Latin title is its own rom and ko (D39)
            title_item = self.reviews.item(self.spec.review_file("release"), "release", obs.title,
                                           {"title": {"ja": obs.title, "rom": latin, "ko": latin}, "source": obs.url}, obs.page_id)
            try:
                item_values(title_item)
            except (KeyError, ValueError) as e:
                self.report.pending.append(f"release {obs.title}: {e}")
                complete = False
        vocal_of: dict[str, m.Recording] = {}
        for t in obs.tracks:
            base, ver, inner = _song(t.title)
            used = f"{obs.page_id} #{t.disc}-{t.no}" if t.disc > 1 or any(x.disc > 1 for x in obs.tracks) else f"{obs.page_id} #{t.no}"
            wid = self.resolve("work", base, file=self.spec.review_file("work"), used_in=used,
                               seed={"title": {"ja": base, "rom": _rom_title(base), "ko": _rom_title(base)},
                                     "source": obs.url})
            perf = self.performers(t.performers, group_id, used) if t.performers else release_perf
            credits = {role: self.credits(names, f"{base}: {role}", obs.url) for role, names in t.credits.items()}
            if wid is None or perf is None or any(v is None for v in credits.values()):
                complete = False
                continue
            if not complete and ver == "Off Vocal":
                continue  # its vocal track is waiting for names too
            work = self.ds.works[wid]
            rec = self.recording(work, ver, perf, credits, obs, vocal_of, inner)
            if rec is None:
                complete = False
                continue
            placed.append((t.disc, m.Track(no=t.no, recording=f"{wid}#{rec.id}")))
        if not complete:
            self.report.skipped.append(f"{obs.page_id} {obs.title}: waiting for names")
            return
        self._upsert_release(obs, placed, release_perf or [], title_item)

    def recording(self, work: m.Work, ver: str | None, perf: list[m.Performer], credits: dict[str, list[m.Credit] | None],
                  obs: ReleaseObs, vocal_of: dict[str, m.Recording], inner: str | None = None) -> m.Recording | None:
        lyr, comp, arr = credits.get("lyricist"), credits.get("composer"), credits.get("arranger")
        src = m.Evidence(status=m.Status.official, source=obs.url, checked=self.today)
        if lyr is not None or comp is not None:
            new = m.WorkCredits(lyricist=lyr or [], composer=comp or [])
            if not work.credits.lyricist and not work.credits.composer:
                work.credits = new
                work.evidence["credits"] = src
            elif not _same_credits(work.credits.lyricist, new.lyricist) or not _same_credits(work.credits.composer, new.composer):
                self.report.conflicts.append(f"{work.id}: credits on {obs.page_id} differ from the stored ones")
        if ver == "Off Vocal":
            if inner:
                labels = version_labels(inner)
                vocal = next((r for r in work.recordings if labels and r.id == labels[0]), None)
            else:
                vocal = vocal_of.get(work.id) or next((r for r in work.recordings if r.id == "original"), None)
            if vocal is None:
                self.report.conflicts.append(f"{work.id}: Off Vocal without a vocal recording on {obs.page_id}")
                return None
            rid = "off-vocal" if vocal.id == "original" else f"{vocal.id}-off-vocal"
            title = _suffixed(vocal.title or work.title, " (Off Vocal)")
            fields: dict[str, Any] = {"kind": "off_vocal", "title": title, "version": "Off Vocal", "instrumental_of": vocal.id,
                                      "arranger": arr if arr is not None else vocal.arranger}
            return self._upsert_recording(work, rid, fields, src)
        if ver is None:
            rid, fields = "original", {"performers": perf, "arranger": arr or []}
        elif ver.endswith(" Solo Ver."):
            cid = self.character(ver.removesuffix(" Solo Ver."))
            if cid is None:
                self.report.conflicts.append(f"{work.id}: unknown member in version {ver!r}")
                return None
            ch = self.ds.characters[cid]
            rid = cid.split("/", 1)[1] + "-solo-ver"
            # ja keeps the version as printed ("麻布麻衣 Solo Ver."); rom and ko name the member
            title = m.Names(ja=f"{work.title.ja} ({ver})",
                            rom=f"{work.title.rom} ({ch.names.rom} Solo Ver.)" if work.title.rom and ch.names.rom else None,
                            ko=f"{work.title.ko} ({ch.names.ko} Solo Ver.)" if work.title.ko and ch.names.ko else None)
            fields = {"title": title, "version": ver, "performers": perf, "arranger": arr or []}
        else:
            labels = version_labels(ver)
            if labels is None:
                self.report.conflicts.append(f"{work.id}: unhandled version {ver!r} on {obs.page_id}")
                return None
            rid, ja, rom, ko = labels
            fields = {"title": _suffixed(work.title, f" ({ja})", f" ({rom})", f" ({ko})"), "version": ja,
                      "performers": perf, "arranger": arr or []}
        rec = next((r for r in work.recordings if r.id == rid), None)
        if rec is not None and rec.performers and rec.performers != perf:
            # the same song by other singers: a solo of a group song (a graduation album) is its own recording
            if len(perf) == 1 and perf[0].character:
                rid = f"{rid}-{perf[0].character.split('/', 1)[1]}" if ver else f"{perf[0].character.split('/', 1)[1]}-solo"
                rec = next((r for r in work.recordings if r.id == rid), None)
            else:
                self.report.conflicts.append(f"{work.id}#{rid}: performers on {obs.page_id} differ from the stored ones")
                return None
        rec = self._upsert_recording(work, rid, fields, src)
        if ver is None and rid == "original":
            vocal_of[work.id] = rec
        return rec

    def _upsert_recording(self, work: m.Work, rid: str, fields: dict[str, Any], src: m.Evidence) -> m.Recording:
        rec = next((r for r in work.recordings if r.id == rid), None)
        if rec is None:
            rec = m.Recording(id=rid, **fields, evidence={"credits": src})
            work.recordings.append(rec)
            return rec
        for k, v in fields.items():
            if k == "arranger" and not v:
                continue  # a page without credits (the unit album's repeats) keeps what was read before
            if k in ("title", "version") and getattr(rec, k):
                continue  # a stored title keeps its reading (kana) and the notation chosen first
            if k == "arranger" and rec.arranger and not _same_credits(rec.arranger, v):
                self.report.conflicts.append(f"{work.id}#{rid}: arranger on {self.page and page_id(self.page)} differs from the stored one")
                continue
            setattr(rec, k, v)
        return rec

    def _rtype(self, obs: ReleaseObs) -> str:
        if obs.type:
            return obs.type
        catalog = next((e.catalog for e in obs.editions if e.catalog), "") or ""
        return "digital_single" if catalog.startswith("LZC") else "album" if catalog.startswith("LACA") else "single"

    def _editions(self, obs: ReleaseObs, rtype: str) -> list[m.Edition]:
        def media(e: EditionObs) -> list[str]:
            return _media(e.media) or (["digital"] if rtype == "digital_single" else [])

        if len(obs.editions) == 1:
            e = obs.editions[0]
            return [m.Edition(id="e1", label=m.Names(ja=e.label) if e.label else None, catalog=e.catalog, media=media(e))]
        return [m.Edition(id=f"e{i}", label=m.Names(ja=e.label) if e.label else None, catalog=e.catalog, media=media(e))
                for i, e in enumerate(obs.editions, 1)]

    def _links(self, obs: ReleaseObs) -> dict[str, str]:
        smart = obs.links.get("楽曲配信") or obs.links.get("smartlink")
        return {"official": obs.url} | ({"smartlink": smart} if smart else {})

    def _check_legacy(self, rel: m.Release, obs: ReleaseObs, group_id: str | None) -> None:
        """A migrated release seen on the official page: add what the page knows, compare the tracks."""
        stored = [(d.disc, t.no, self.ds.recording(t.recording)[0]) for d in rel.discs for t in d.tracks]
        printed = [(t.disc, t.no, split_version(t.title)[0]) for t in obs.tracks]
        same = [(d, n, match_key(w.title.ja)) for d, n, w in stored] == [(d, n, match_key(b)) for d, n, b in printed]
        if not same:
            self.report.conflicts.append(f"{rel.id}: tracks on {obs.page_id} differ from the stored ones")
        src = m.Evidence(status=m.Status.official, source=obs.url, checked=self.today)
        rtype = self._rtype(obs)
        if rel.type == "unclassified":
            rel.type = rtype  # type: ignore[assignment]
        catalogs = [e.catalog for e in obs.editions if e.catalog]
        if rel.label is None and catalogs and catalogs[0].startswith("LA"):
            rel.label = "Lantis"
        if not rel.editions:
            rel.editions = self._editions(obs, rtype)
        else:  # fill what the stored editions miss, edition by edition (same label, or the only one)
            for i, ed in enumerate(rel.editions):
                e = next((x for x in obs.editions if x.label and ed.label and match_key(x.label) == match_key(ed.label.ja)), None)
                e = e or (obs.editions[i] if len(obs.editions) == len(rel.editions) else None)
                if e is not None:
                    ed.catalog = ed.catalog or e.catalog
                    ed.media = ed.media or _media(e.media)
        if not rel.artist_credit:
            perf = self.performers(obs.performers, group_id, obs.page_id)
            if perf:
                rel.artist_credit = perf
        rel.links = self._links(obs) | rel.links
        rel.evidence["editions"] = src
        if same:
            rel.evidence["tracks"] = src.model_copy(update={"note": CHECKED_LEGACY})
        if obs.note:
            rel.evidence["release_date"] = src.model_copy(update={"note": obs.note})

    def _upsert_release(self, obs: ReleaseObs, placed: list[tuple[int, m.Track]], perf: list[m.Performer],
                        item: dict[str, Any] | None) -> None:
        tracks = [t for _, t in placed]
        pages = set(obs.pages)
        rel = next((r for r in self.ds.releases.values() if r.links.get("official") in pages), None)
        rtype = self._rtype(obs)
        editions = self._editions(obs, rtype)
        links = self._links(obs)
        status = "announced" if obs.release_date > self.today else "released"
        src = m.Evidence(status=m.Status.official, source=obs.url, checked=self.today)
        evidence = {"tracks": src, "editions": src}
        if obs.note:
            evidence["release_date"] = src.model_copy(update={"note": obs.note})
        discs = _discs(placed)
        catalogs = [e.catalog for e in obs.editions if e.catalog]
        label = "Lantis" if catalogs and catalogs[0].startswith("LA") else None
        if rel is None:  # an existing release keeps its title
            if item is not None:
                title = item_values(item)["title"]
            else:  # song titles: their rom gives the id
                works = {match_key(self.ds.recording(t.recording)[0].title.ja): self.ds.recording(t.recording)[0] for t in tracks}
                title = m.Names(ja=obs.title, rom=" / ".join(works[match_key(p)].title.rom or "" for p in _TITLE_SEP.split(obs.title)))
            ident = f"{self.spec.project}/{obs.release_date.year}-{slugify(title.rom or '')}"
            if ident in self.ds.releases:
                raise ValueError(f"release id {ident!r} already exists ({obs.url})")
            if item is not None:  # a title that is not made of song titles was named in review
                item["ref"] = f"release:{ident}"
                evidence["title"] = m.Evidence(status=m.Status.draft, source=f"automation/review/{self.spec.review_file('release')}",
                                               note="승인 대기 (new-names 리뷰)")
            rel = m.Release(id=ident, type=rtype, status=status, title=title if item is not None else m.Names(ja=title.ja),
                            projects=[self.spec.project], artist_credit=perf, label=label, release_date=obs.release_date,
                            editions=editions, discs=discs, links=links,
                            legacy=m.ReleaseLegacy(category=self.spec.legacy_group, albums=[m.LegacyAlbum(title=obs.title)]),
                            evidence=evidence)
            self.ds.releases[ident] = rel
            self.report.created.append(f"release:{ident}")
            return
        before = rel.model_dump()
        rel.type, rel.artist_credit, rel.release_date, rel.editions = rtype, perf, obs.release_date, editions  # type: ignore[assignment]
        rel.discs = discs
        rel.links = rel.links | links
        if rel.status != "verified":
            rel.status = status
        if rel.model_dump() != before:
            rel.evidence |= evidence

    # artists and layout ------------------------------------------------------------

    def lineups(self, site: Site, group_id: str, members: list[str]) -> None:
        group = self.ds.artists[group_id]
        if not group.lineups or group.lineups[-1].members != members:
            group.lineups = [m.Lineup(members=members)]
            group.evidence["lineups"] = m.Evidence(status=m.Status.official, source=site.member_url, checked=self.today)
        group_key = match_key(self.spec.group_name)
        for obs in site.releases:
            p = obs.performers
            if not p.artist or match_key(p.artist) == group_key or not p.members:
                continue
            aid = self._find("artist", p.artist)
            chars = [self.character(n) for n, _ in p.members]
            if aid is None or not all(chars):
                continue
            art = self.ds.artists[aid]
            if not art.lineups or art.lineups[-1].members != chars:
                art.lineups = [m.Lineup(members=chars)]  # type: ignore[list-item]
                art.evidence["lineups"] = m.Evidence(status=m.Status.official, source=obs.url, checked=self.today)

    def layout(self, members: list[str]) -> None:
        lay = self.ds.layout
        assert lay is not None
        group = self.spec.legacy_group
        if group not in lay.integrated_order:
            lay.integrated_order.append(group)
        albums = lay.albums.setdefault(group, m.LayoutAlbumsFile(entries=[]))
        have = {e.release for e in albums.entries}
        rels = sorted((r for r in self.ds.releases.values() if self.spec.project in r.projects and r.legacy.albums),
                      key=lambda r: (r.release_date or dt.date.max, r.id))
        for rel in rels:
            if rel.id not in have:
                albums.entries.append(m.LayoutAlbumEntry(release=rel.id))
        if members:
            rows = lay.members.setdefault(group, m.LayoutMembersFile(rows=[]))
            known = {r.character for r in rows.rows}
            rows.rows += [m.LayoutMemberRow(character=c) for c in members if c not in known]


def _song(title: str) -> tuple[str, str | None, str | None]:
    """(song title, version, version inside an Off Vocal): ``X（104期NEW Ver.）（Off Vocal）`` →
    (X, Off Vocal, 104期NEW Ver.), the instrumental of a version."""
    base, ver = split_version(title)
    inner = None
    if ver == "Off Vocal":
        base, inner = split_version(base)
    return base, ver, inner


def _same_credits(a: list[m.Credit], b: list[m.Credit]) -> bool:
    """The same people in the same order; affiliations compared by match key ("Jazzin'park" = "Jazzin’park")."""
    def key(c: m.Credit) -> tuple[Any, ...]:
        aff = c.affiliation if isinstance(c.affiliation, str) or c.affiliation is None else c.affiliation.ja
        return (c.person, c.character, match_key(aff))

    return [key(c) for c in a] == [key(c) for c in b]


def _discs(placed: list[tuple[int, m.Track]]) -> list[m.Disc]:
    by_disc: dict[int, list[m.Track]] = {}
    for disc, t in placed:
        by_disc.setdefault(disc, []).append(t)
    return [m.Disc(disc=n, tracks=ts) for n, ts in sorted(by_disc.items())]


# the tracks evidence of a migrated release whose tracklist the official page confirmed
CHECKED_LEGACY = "레거시 트랙리스트를 공식 페이지와 대조함 (같음)"


def _migrated(rel: m.Release) -> bool:
    """A release that came from the legacy files: its tracks are compared, never rewritten."""
    ev = rel.evidence.get("tracks")
    return "official" not in rel.links or ev is None or ev.status == m.Status.legacy or ev.note == CHECKED_LEGACY


def import_site(ds: Dataset, site: Site, review_dir: Path, today: dt.date, spec: Spec) -> Report:
    """Upsert everything read from the site. Names still waiting in a review file leave the
    releases that use them out; the review files are written back with what was found."""
    reviews = NameReviews(review_dir, spec.project)
    known_members = {mem.name for mem in site.members} | {c.names.ja for c in ds.characters.values()
                                                          if c.project == spec.project and c.names.ja}
    imp = Importer(ds, reviews, today, spec, known_members)
    before = {f"{kind}:{ent.id}": ent.model_dump() for kind, ent in ds.iter_all()}  # type: ignore[attr-defined]
    layout_before = ds.layout.model_dump() if ds.layout else None
    members = imp.members(site)
    group_id = imp.artist(spec.group_name, artist_kind="group", used_in="member page", source=site.member_url)
    for obs in site.releases:  # also when names are pending, so that one run lists every new name
        imp.release(obs, group_id)
    if group_id and all(members):
        if spec.lineups_from_site:
            imp.lineups(site, group_id, members)  # type: ignore[arg-type]
        imp.layout(members)  # type: ignore[arg-type]
    reviews.save()
    created = set(imp.report.created)
    imp.report.updated = [ref for kind, ent in ds.iter_all()
                          if (ref := f"{kind}:{ent.id}") in before and before[ref] != ent.model_dump() and ref not in created]  # type: ignore[attr-defined]
    if ds.layout and ds.layout.model_dump() != layout_before:
        imp.report.updated.append("legacy layout")
    imp.report.skipped += site.skipped + [f"{k} {v}" for k, v in spec.skip.items()]
    return imp.report
