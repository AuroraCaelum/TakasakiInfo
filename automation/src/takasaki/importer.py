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
from .text import halfwidth, is_latin, match_key, slugify, split_version, wave_version


class ParseError(ValueError):
    pass


# --- credits ----------------------------------------------------------------------

# string and brass arrangements are roles of their own beside 編曲 (D42); 弦管編曲 is both
ROLE = {"作詞": "lyricist", "作曲": "composer", "編曲": "arranger", "弦編曲": "strings_arranger",
        "ストリングスアレンジ": "strings_arranger", "管編曲": "brass_arranger",
        "菅編曲": "brass_arranger"}  # a misprint of 管編曲 (Liella! 1st album 「みてろ！」, yuigaoka cd16/cd17)
ARRANGERS = ("arranger", "strings_arranger", "brass_arranger")
_ROLE_WORD = r"(?:弦管編曲|弦編曲|管編曲|菅編曲|ストリングスアレンジ|作編曲|作詞|作曲|編曲)"
# "作編曲：高田 暁" (the early Aqours pages), "弦管編曲：真部 裕"
_COMBINED = {"作編曲": ["作曲", "編曲"], "弦管編曲": ["弦編曲", "管編曲"]}
_ROLES = rf"{_ROLE_WORD}(?:\s*[／/・]\s*{_ROLE_WORD})*"
_AFFILIATION = re.compile(r"^(.*?)\s*[（(]([^()（）]+)[)）]$")


@dataclass
class CreditName:
    name: str
    affiliation: str | None = None
    fullwidth: bool = False  # the affiliation in full-width brackets, 名前（所属） (D42)


def parse_credit_line(line: str) -> dict[str, list[CreditName]]:
    """``作詞：畑 亜貴　作曲/編曲：光増ハジメ (FirstCall)`` → {lyricist: [畑 亜貴], composer/arranger: [光増ハジメ (FirstCall)]}.
    Roles may also be joined with ``・`` (``作曲・編曲：…``); ``弦編曲`` is ``strings_arranger``, ``管編曲``
    ``brass_arranger`` and ``弦管編曲`` both."""
    out: dict[str, list[CreditName]] = {}
    # a name may contain spaces, so segments are split only before "<roles>：", after a space, a
    # slash ("作詞：畑 亜貴／作曲：…", not the "作曲／編曲：" of joined roles) or an affiliation's bracket
    for seg in re.split(rf"(?<![・／/])\s+(?={_ROLES}\s*[：:])|(?<![詞曲])\s*[／/]\s*(?={_ROLES}\s*[：:])|(?<=[)）])(?={_ROLES}\s*[：:])",
                        line.strip()):
        mt = re.match(rf"^({_ROLES})\s*[：:]\s*(.+)$", seg)
        if not mt:
            raise ParseError(f"not a credit segment: {seg!r} in {line!r}")
        roles = [r for word in re.split(r"[／/・]", mt.group(1)) for r in _COMBINED.get(word.strip(), [word.strip()])]
        if re.search(r"[：:]", mt.group(2)):  # a label this parser does not know ("歌：…")
            raise ParseError(f"unknown credit label in {seg!r}")
        names = []
        for part in _split_names(mt.group(2).strip().rstrip("／/").strip()):
            am = _AFFILIATION.match(part.strip())
            if am:
                names.append(CreditName(am.group(1).strip(), am.group(2).strip().replace("’", "'"), part.strip().endswith("）")))
            else:
                names.append(CreditName(part.strip()))
        for r in roles:
            out[ROLE[r]] = names
    return out


def _split_names(text: str) -> list[str]:
    """Names joined by ``・``, ``、``, ``&`` or ``,`` (``Fi’Ne, Yuqui-lah``); a comma inside an
    affiliation stays (``Hiroki Sagawa (Relic Lyric, inc.)``)."""
    text = re.sub(r"\b([A-Z])・(?=[A-Z]\b)", "\\1\x00", text)  # "R・O・N" is one name
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
    return [p.strip().replace("\x00", "・") for p in out + [cur] if p.strip()]


def is_credit_line(line: str) -> bool:
    return re.match(rf"^{_ROLES}\s*[：:]", line) is not None


# --- observations ---------------------------------------------------------------------


@dataclass
class Performers:
    artist: str | None  # "いきづらい部！", "CHAKI！"; None for a list of members only
    group: str | None  # "いきづらい部！" when the line says "… from いきづらい部！"
    members: list[tuple[str, str]] = field(default_factory=list)  # (character, voice actress) as printed
    artists: list[str] = field(default_factory=list)  # several artists credited together ("A＆B＆C")
    # a stage cast: the members are (role, actor) and the actors sing ("堀内まり菜（椿 ルリカ役）", D29);
    # an ensemble member has no role
    cast: bool = False


_FEAT = re.compile(r"\s+(?:feat\.|featuring)\s+", re.I)


def split_featured(names: list[str]) -> tuple[list[str], list[str]]:
    """``Aqours feat. 初音ミク`` → ``(["Aqours"], ["初音ミク"])``: the guest after ``feat.`` is a
    performer of its own, marked ``featured``, not part of a joint artist name (D48)."""
    main, guests = [], []
    for n in names:
        head, *rest = _FEAT.split(n)
        main.append(head.strip())
        guests += [g.strip() for g in rest if g.strip()]
    return main, guests


@dataclass
class TrackObs:
    no: int
    title: str
    performers: Performers | None = None
    credits: dict[str, list[CreditName]] = field(default_factory=dict)
    disc: int = 1
    drama: bool = False  # under a drama or radio part of the track list ("■ドラマパート", "■録り下ろしラジオ")


@dataclass
class EditionObs:
    label: str | None
    catalog: str | None
    media: str | None = None  # as printed: "CD+BD+グッズ", "CDのみ", "配信"


@dataclass
class EditionPage:
    """One edition's own page, when the editions of a release have different track lists."""

    label: str | None
    url: str
    tracks: list[TrackObs]


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
    edition_pages: list[EditionPage] = field(default_factory=list)  # each edition with its tracks (sitepage)
    alt_titles: list[str] = field(default_factory=list)  # other ways the page names it (matched to the legacy title)

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
    legacy_file: str | None = None  # the file (layout group) when it is named otherwise: Nijigasaki → Nijigaku
    skip: dict[str, str] = field(default_factory=dict)  # page id -> why the release is left to a later phase
    lineups_from_site: bool = True  # False keeps the dated lineups in data/ (Hasunosora, D33)
    # page id -> every project of a cross-project release this adapter imports (Bring the LOVE！, AiScReam):
    # the release lists them all, its legacy category is Others (D6) and every project's legacy file lists it
    cross: dict[str, list[str]] = field(default_factory=dict)
    # False when group_name names the work, not an artist (the musical: its CDs credit
    # 「スクールアイドルミュージカル」, and the cast sings each track)
    group_artist: bool = True
    # True only checks the releases already in data/ against the site (D41); releases and names the
    # site has beyond them are listed as skipped, for a later catch-up
    check_only: bool = False

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
    return halfwidth(unicodedata.normalize("NFKC", s)) if is_latin(s) else ""


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
        self.singers: set[str] = set()  # the artists the track being read names (match keys)
        self.report = Report()
        self.doubts: list[tuple[list[tuple[dict[str, m.Evidence], str]], str]] = []
        # what each page settled of a recording, put together by _settle: (work id, recording id) -> evidence
        self.verified: dict[tuple[str, str], str] = {}  # arranger and singers on one page (its address)
        self.arranged_on: dict[tuple[str, str], m.Evidence] = {}  # the arranger only
        self.arranged_as: dict[tuple[str, str], dict[str, list[m.Credit] | None]] = {}  # ... as that page printed it
        self.sung_on: dict[tuple[str, str], m.Evidence] = {}  # the singers only, no credits printed
        self.listed: dict[tuple[str, str], m.Evidence] = {}  # an Off Vocal or instrumental the page lists
        # names the checked pages printed: (kind, id) -> (as printed, page)
        self.seen: dict[tuple[str, str], tuple[str, str]] = {}
        self.page_url: str | None = None
        # the first release on the site of each song (its match key): that release's recording is the original
        self.first_on: dict[str, dt.date] = {}

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
            if not hits and self.page and page_id(self.page) in self.spec.cross:  # a member of another project
                hits = [c.id for c in self.ds.characters.values() if c.project in self.spec.cross[page_id(self.page)]
                        and match_key(c.names.ja) == key]
                hits = hits if len(hits) == 1 else []
        elif kind == "artist":
            hits = [a.id for a in self.ds.artists.values() if project in a.projects and match_key(a.names.ja) == key]
            if not hits:  # another project's group singing on this project's release (the split single's Liella!)
                hits = [a.id for a in self.ds.artists.values() if match_key(a.names.ja) == key]
                hits = hits if len(hits) == 1 else []
        elif kind == "work":
            hits = [w.id for w in self.ds.works.values() if w.project == project and match_key(w.title.ja) == key]
            if not hits:  # a song stored under another project, sung by an artist of this one (LIVE with a smile!)
                hits = [w.id for w in self.ds.works.values() if match_key(w.title.ja) == key
                        and any(p.artist and project in self.ds.artists[p.artist].projects for r in w.recordings for p in r.performers)]
            if not hits and self.singers:  # ... or by the artist the track names (the split single's Liella!)
                hits = [w.id for w in self.ds.works.values() if match_key(w.title.ja) == key
                        and any(p.artist and match_key(self.ds.artists[p.artist].names.ja) in self.singers
                                for r in w.recordings for p in r.performers)]
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
            out.append(m.Credit(person=pid, affiliation=c.affiliation, fullwidth=c.fullwidth) if pid else None)
        return None if None in out else out  # every name is looked up, so one run lists them all

    # works and releases -----------------------------------------------------------

    def _find_guest(self, printed: str) -> m.Performer | None:
        """A featured guest (D48) in the dictionary: an artist or a character of any project (one
        from outside the series is under ``external``), else a person."""
        key = match_key(printed)
        hits = [("artist", a.id) for a in self.ds.artists.values() if match_key(a.names.ja) == key] \
            or [("character", c.id) for c in self.ds.characters.values() if match_key(c.names.ja) == key]
        if hits:
            return m.Performer(**{hits[0][0]: hits[0][1]}, featured=True)
        pid = self._find_person(printed)
        return m.Performer(person=pid, featured=True) if pid else None

    def _guest(self, printed: str, used_in: str | None) -> m.Performer | None:
        found = self._find_guest(printed)
        if found:
            kind = found.ref[0]
            self.reviews.note_use(self.spec.review_file(kind), kind, printed, used_in)
            return found
        aid = self.artist(printed, artist_kind="solo", used_in=used_in, source=self.page)  # a new name: reviewed as an artist
        return m.Performer(artist=aid, featured=True) if aid else None

    def performers(self, p: Performers, group_id: str | None, used_in: str | None = None) -> list[m.Performer] | None:
        names, guests = split_featured(p.artists or ([p.artist] if p.artist else []))
        featured = [self._guest(g, used_in) for g in guests]
        sung = self._sung_by(p, names, group_id, used_in)
        return None if sung is None or None in featured else sung + featured  # type: ignore[operator]

    def _with_joint(self, names: list[str]) -> list[tuple[str, bool]]:
        """The artist names a credit prints, each with whether it is part of a joint name (D48).
        ``Aqours・虹ヶ咲学園スクールアイドル同好会・Liella!`` is split into its artists when the whole
        is no artist of its own and every part is one (``R・O・N`` stays a name)."""
        group_key = match_key(self.spec.group_name)
        out: list[tuple[str, bool]] = []
        for n in names:
            parts = [x.strip() for x in n.split("・")]
            joint = len(parts) > 1 and not self._find("artist", n) \
                and all(match_key(x) == group_key or self._find("artist", x) for x in parts)
            out += [(x, True) for x in parts] if joint else [(n, False)]
        return out

    def _sung_by(self, p: Performers, names: list[str], group_id: str | None, used_in: str | None) -> list[m.Performer] | None:
        group_key = match_key(self.spec.group_name)
        named = self._with_joint(names)
        if not self.spec.group_artist:
            named = [(n, j) for n, j in named if match_key(n) != group_key]
        if named:
            ids = [group_id if match_key(n) == group_key else self.artist(n, used_in=used_in, source=self.page) for n, _ in named]
            return [m.Performer(artist=a, joint=j) for a, (_, j) in zip(ids, named)] if all(ids) else None
        if p.cast:
            return self._cast(p, used_in)
        chars = [self.character(name) for name, _ in p.members]
        if not all(chars):
            strangers = [name for name, _ in p.members if match_key(name) not in self.member_keys]
            if strangers:  # otherwise the member is only waiting for review
                self.report.conflicts.append(f"not on the member page: {strangers}")
            return None
        return [m.Performer(character=c) for c in chars]

    def _cast(self, p: Performers, used_in: str | None) -> list[m.Performer] | None:
        """A stage cast (D29): each actor sings in a role (a character of the project), an ensemble
        member without one. An actor new in a role is added to the character's casting."""
        out: list[m.Performer] = []
        for role, actor in p.members:
            pid = self.resolve("person", actor, file=self.spec.review_file("person"), seed={"source": self.page or ""},
                               used_in=used_in)
            cid = self.character(role) if role else None
            if role and cid is None:
                self.report.conflicts.append(f"role {role!r} of {actor} on {self.page and page_id(self.page)} is not a character")
                return None
            if pid is None:
                continue
            if cid:
                char = self.ds.characters[cid]
                if not any(c.person == pid for c in char.casting):
                    char.casting.append(m.Casting(person=pid))
                    char.evidence.setdefault("casting", m.Evidence(status=m.Status.official, source=self.page, checked=self.today))
            out.append(m.Performer(person=pid, role=cid))
        return out if len(out) == len(p.members) else None

    def _legacy_match(self, obs: ReleaseObs) -> m.Release | None:
        """A migrated release (no official link yet) with the same date and title."""
        keys = {match_key(t) for t in [obs.title, *obs.alt_titles]}
        for rel in self.ds.releases.values():
            if self.spec.project in rel.projects and "official" not in rel.links and rel.release_date == obs.release_date \
                    and (match_key(rel.title.ja) in keys or any(match_key(a.title) in keys for a in rel.legacy.albums)):
                return rel
        return None

    def _known(self, obs: ReleaseObs) -> m.Release | None:
        pages = set(obs.pages)
        return next((r for r in self.ds.releases.values() if r.links.get("official") in pages), None) or self._legacy_match(obs)

    def release(self, obs: ReleaseObs, group_id: str | None) -> None:
        self.page = obs.url
        known = self._known(obs)
        if known is not None and not _unsourced(known) and (self.spec.check_only or "official" not in known.links):
            self._check_sourced(known, obs, group_id)  # its tracks were sourced already (D36)
            if not self.spec.check_only:  # a migrated release: the page adds what it knows, the tracks stay
                self._fill_release(known, obs, group_id, m.Evidence(status=m.Status.official, source=obs.url, checked=self.today))
            return
        if known is not None and _migrated(known):
            self._check_legacy(known, obs, group_id)
            return
        if self.spec.check_only:
            if known is None:
                self.report.skipped.append(f"{obs.page_id} {obs.title}: not in data/ yet")
            return
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
        drama_cd = self._rtype(obs) == "drama_cd"
        vocal_of: dict[str, m.Recording] = {}
        on_release: dict[str, str] = {}  # the songs found for this release's tracks: its Off Vocals are theirs
        placed_by: list[tuple[str | None, list[tuple[int, m.Track]]]] = []  # (edition label, [(disc, track)])
        for label, tracks, url in _edition_tracks(obs):
            placed: list[tuple[int, m.Track]] = []
            where = f"{page_id(url)}【{label}】" if label else obs.page_id  # an edition's songs are on its own page
            for t in tracks:
                base, ver, inner = _song(t.title)
                sung = t.performers or obs.performers
                main, guests = split_featured(sung.artists or ([sung.artist] if sung.artist else []))
                self.singers = {match_key(n) for n, _ in self._with_joint(main + guests)}
                used = f"{where} #{t.disc}-{t.no}" if t.disc > 1 or any(x.disc > 1 for x in tracks) else f"{where} #{t.no}"
                wid = on_release.get(match_key(base)) or self.resolve(
                    "work", base, file=self.spec.review_file("work"), used_in=used,
                    seed={"title": {"ja": base, "rom": _rom_title(base), "ko": _rom_title(base)}, "source": url})
                if wid:
                    on_release.setdefault(match_key(base), wid)
                perf = self.performers(t.performers, group_id, used) if t.performers else release_perf
                credits = {role: self.credits(names, f"{base}: {role}", url) for role, names in t.credits.items()}
                if wid is None or perf is None or any(v is None for v in credits.values()):
                    complete = False
                    continue
                if not complete and ver == "Off Vocal":
                    continue  # its vocal track is waiting for names too
                work = self.ds.works[wid]
                if (drama_cd or t.drama) and not t.credits and ver is None:  # a drama track: no credits, the cast as performers
                    if not work.recordings:
                        work.kind = "drama"  # type: ignore[assignment]
                    rec = self._upsert_recording(work, "main", {"kind": "drama", "performers": perf},
                                                 m.Evidence(status=m.Status.official, source=url, checked=self.today))
                else:
                    rec = self.recording(work, ver, perf, credits, obs, vocal_of, inner,
                                         t.title[len(base):].strip() if wave_version(t.title) else None, source=url)
                if rec is None:
                    complete = False
                    continue
                placed.append((t.disc, m.Track(no=t.no, recording=f"{wid}#{rec.id}")))
            placed_by.append((label, placed))
        if not complete:
            self.report.skipped.append(f"{obs.page_id} {obs.title}: waiting for names")
            return
        self._upsert_release(obs, placed_by, release_perf or [], title_item)

    def recording(self, work: m.Work, ver: str | None, perf: list[m.Performer], credits: dict[str, list[m.Credit] | None],
                  obs: ReleaseObs, vocal_of: dict[str, m.Recording], inner: str | None = None,
                  printed: str | None = None, source: str | None = None) -> m.Recording | None:
        """``printed``: the version as the title prints it when not in round brackets (``～2023Ver.～``,
        ``[YOU & I edit]``): the recording's title keeps that notation, half-width in rom and ko.
        ``source``: the page the track is on, an edition's own page when the editions differ."""
        lyr, comp = credits.get("lyricist"), credits.get("composer")
        arranged = {k: credits.get(k) or [] for k in ARRANGERS}  # 編曲, 弦編曲, 管編曲 (D42)
        source = source or obs.url
        src = m.Evidence(status=m.Status.official, source=source, checked=self.today)
        if lyr is not None or comp is not None:
            new = m.WorkCredits(lyricist=lyr or [], composer=comp or [])
            if not work.credits.lyricist and not work.credits.composer:
                work.credits = new
                work.evidence["credits"] = src
            elif not _same_credits(work.credits.lyricist, new.lyricist) or not _same_credits(work.credits.composer, new.composer):
                if _refs(work.credits.lyricist) != _refs(new.lyricist) or _refs(work.credits.composer) != _refs(new.composer):
                    self.report.conflicts.append(f"{work.id}: credits on {obs.page_id} differ from the stored ones")
                # else the same people with other affiliations (a cover album prints its own): the stored ones stay
            elif work.evidence.get("credits") is not None and work.evidence["credits"].source == source:
                _printed_as(work.credits.lyricist, new.lyricist)
                _printed_as(work.credits.composer, new.composer)
        if ver == "Off Vocal":
            if inner:
                labels = version_labels(inner) or self._artist_version(inner)
                vocal = next((r for r in work.recordings if labels and r.id == labels[0]), None)
            else:
                vocal = vocal_of.get(work.id) or next((r for r in work.recordings if r.id == "original"), None)
            if vocal is None:
                self.report.conflicts.append(f"{work.id}: Off Vocal without a vocal recording on {obs.page_id}")
                return None
            rid = "off-vocal" if vocal.id == "original" else f"{vocal.id}-off-vocal"
            title = _suffixed(vocal.title or work.title, " (Off Vocal)")
            # an Off Vocal printed without credits is arranged as its vocal
            own = credits.get("arranger") is not None
            fields: dict[str, Any] = {"kind": "off_vocal", "title": title, "version": "Off Vocal", "instrumental_of": vocal.id,
                                      **{k: arranged[k] if own else getattr(vocal, k) for k in ARRANGERS}}
            return self._upsert_recording(work, rid, fields, src)
        if ver is None and not any(r.id == "original" for r in work.recordings) \
                and self.first_on.get(match_key(work.title.ja), obs.release_date) < obs.release_date:
            # the song's first release is still waiting for names: a later cover (a solo album) does not
            # take its place as the original
            if not (len(perf) == 1 and perf[0].character):
                self.report.conflicts.append(f"{work.id}: first released before {obs.page_id}, which waits for it")
                return None
            rid = f"{perf[0].character.split('/', 1)[1]}-solo"
            return self._upsert_recording(work, rid, {"performers": perf, **arranged}, src)
        if ver is None:
            rid, fields = "original", {"performers": perf, **arranged}
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
            fields = {"title": title, "version": ver, "performers": perf, **arranged}
        else:
            labels = version_labels(ver) or self._artist_version(ver)
            if labels is None:
                self.report.conflicts.append(f"{work.id}: unhandled version {ver!r} on {obs.page_id}")
                return None
            rid, ja, rom, ko = labels
            sep = "" if printed and printed.startswith("[") else " "
            title = _suffixed(work.title, f"{sep}{printed}", halfwidth(f"{sep}{printed}"), halfwidth(f"{sep}{printed}")) if printed \
                else _suffixed(work.title, f" ({ja})", f" ({rom})", f" ({ko})")
            fields = {"title": title, "version": ja,
                      "performers": perf, **arranged}
        rec = next((r for r in work.recordings if r.id == rid), None)
        group_take = False
        if rec is not None and rec.performers and perf and rec.performers != perf:
            # the same song by other singers: a solo of a group song (a graduation album) is its own recording
            if len(perf) == 1 and perf[0].character:
                rid = f"{rid}-{perf[0].character.split('/', 1)[1]}" if ver else f"{perf[0].character.split('/', 1)[1]}-solo"
                rec = next((r for r in work.recordings if r.id == rid), None)
            elif ver is None and len(perf) == 1 and perf[0].artist:
                # ... and the whole group singing a song first sung by some of its members (START:DASH!! by
                # the three, then by μ's): a recording named after the group, with its own Off Vocal
                rid, group_take = perf[0].artist, True
                rec = next((r for r in work.recordings if r.id == rid), None)
            else:
                self.report.conflicts.append(f"{work.id}#{rid}: performers on {obs.page_id} differ from the stored ones")
                return None
        rec = self._upsert_recording(work, rid, fields, src)
        if ver is None and (rid == "original" or group_take):
            vocal_of[work.id] = rec
        return rec

    def _artist_version(self, ver: str) -> tuple[str, str, str, str] | None:
        """(recording id, ja, rom, ko) of a version named after an artist of the project:
        ``虹ヶ咲学園スクールアイドル同好会 Ver.`` is ``Nijigasaki High School Idol Club Ver.`` (as LIVE with a smile!)."""
        mt = re.fullmatch(r"(.+?)\s*Ver\.?", ver)
        aid = self._find("artist", mt.group(1)) if mt else None
        if aid is None:
            return None
        n = self.ds.artists[aid].names
        if not n.rom or not n.ko:
            return None
        return f"{slugify(n.rom)}-ver", f"{mt.group(1)} Ver.", f"{n.rom} Ver.", f"{n.ko} Ver."  # type: ignore[union-attr]

    def _upsert_recording(self, work: m.Work, rid: str, fields: dict[str, Any], src: m.Evidence) -> m.Recording:
        rec = next((r for r in work.recordings if r.id == rid), None)
        if rec is None:
            rec = m.Recording(id=rid, **fields, evidence={"credits": src})
            work.recordings.append(rec)
            return rec
        for k, v in fields.items():
            if k in ARRANGERS and not v:
                continue  # a page without credits (the unit album's repeats) keeps what was read before
            if k == "performers" and not v and rec.performers:
                continue  # ... nor erases singers a page left out
            if k in ("title", "version") and getattr(rec, k):
                continue  # a stored title keeps its reading (kana) and the notation chosen first
            if k in ARRANGERS and getattr(rec, k) and not _same_credits(getattr(rec, k), v):
                self.report.conflicts.append(f"{work.id}#{rid}: {k} on {self.page and page_id(self.page)} differs from the stored one")
                continue
            if k in ARRANGERS and getattr(rec, k) and (rec.evidence.get("credits") or src).source != src.source:
                continue  # printed as the page it is cited to (D42)
            setattr(rec, k, v)
        return rec

    def _rtype(self, obs: ReleaseObs) -> str:
        if obs.type:
            return obs.type
        if "ドラマCD" in obs.title:
            return "drama_cd"
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
        """A migrated release seen on the official page: add what the page knows, compare the tracks
        (edition by edition when the editions have different track lists) and the credits."""
        src = m.Evidence(status=m.Status.official, source=obs.url, checked=self.today)
        rel.links = self._links(obs) | rel.links
        if not self.spec.check_only:  # a check only sources what is stored (D41)
            self._fill_release(rel, obs, group_id, src)
        # (stored tracks, printed tracks, page) to compare: the whole release, or each edition
        pairs: list[tuple[list[m.Track], list[TrackObs], str]] = []
        if any(d.editions != "all" for d in rel.discs) and obs.edition_pages:
            for ed in rel.editions:
                page = next((p for p in obs.edition_pages
                             if p.label and ed.label and match_key(p.label) == match_key(ed.label.ja)), None)
                if page is None:
                    self.report.conflicts.append(f"{rel.id}: edition {ed.label and ed.label.ja!r} not on the page")
                    return
                stored = [t for d in rel.discs if d.editions == "all" or ed.id in d.editions for t in d.tracks]
                pairs.append((stored, page.tracks, page.url))
        else:
            pairs.append(([t for d in rel.discs for t in d.tracks], obs.tracks, obs.url))
        notes = [self._same_tracks(rel, stored, printed, page) for stored, printed, page in pairs]
        if None not in notes:
            rel.evidence["tracks"] = src.model_copy(update={"note": next((n for n in notes if n != CHECKED_TRACKS), CHECKED_TRACKS)})
        self._check_pairs(pairs, obs, group_id, src)

    def _check_pairs(self, pairs: list[tuple[list[m.Track], list[TrackObs], str]], obs: ReleaseObs,
                     group_id: str | None, src: m.Evidence) -> None:
        """The credits of the tracks a page prints at the same place under the same title, also when
        the track lists differ elsewhere (a missing drama track, a remix album's other tracks)."""
        for stored, printed, page in pairs:
            same = []
            for i, (t, p) in enumerate(zip(stored, printed)):
                work, rec = self.ds.recording(t.recording)
                if (t.no in (None, p.no, i + 1) or p.no == i + 1) and _same_title(work, split_version(p.title)[0]):
                    same.append(((work, rec), p))
            self._check_credits(same, obs.performers, group_id, src.model_copy(update={"source": page}))

    def _check_sourced(self, rel: m.Release, obs: ReleaseObs, group_id: str | None) -> None:
        """A release whose tracks were sourced before (D36): its page may still settle the credits
        of recordings it shares with migrated releases. Nothing of the release itself changes."""
        src = m.Evidence(status=m.Status.official, source=obs.url, checked=self.today)
        if any(d.editions != "all" for d in rel.discs):
            return
        self._check_pairs([([t for d in rel.discs for t in d.tracks], obs.tracks, obs.url)], obs, group_id, src)

    def _fill_release(self, rel: m.Release, obs: ReleaseObs, group_id: str | None, src: m.Evidence) -> None:
        """What the official page adds to a migrated release: type, label, editions, artist (D40)."""
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
        if obs.editions:
            rel.evidence["editions"] = src
        if obs.note:
            rel.evidence["release_date"] = src.model_copy(update={"note": obs.note})

    def _same_tracks(self, rel: m.Release, stored: list[m.Track], printed: list[TrackObs], page: str) -> str | None:
        """The tracks evidence note when the stored tracks are the printed ones, else None (a conflict)."""
        works = [self.ds.recording(t.recording)[0] for t in stored]

        def same(i: int) -> bool:
            # numbered as printed, or running on where the page starts each disc again (or the reverse)
            numbered = stored[i].no in (None, printed[i].no, i + 1) or printed[i].no == i + 1
            return numbered and _same_title(works[i], split_version(printed[i].title)[0])

        n = min(len(stored), len(printed))
        first = next((i for i in range(n) if not same(i)), n)
        if first == n and len(stored) < len(printed) and printed[n].disc > printed[n - 1].disc:
            # the stored release is the page's first discs; the rest belong to a special edition
            # (the memorial CDs of a CLUB CD SET's BLACK EDITION)
            return f"{CHECKED_TRACKS}. 공식 페이지의 디스크 {printed[n].disc}~{printed[-1].disc}({len(printed) - n}트랙)는 저장하지 않음"
        if first == n and len(stored) == len(printed):
            if any(t.no not in (None, p.no) for t, p in zip(stored, printed)):
                return f"{CHECKED_TRACKS}. 공식 페이지는 디스크 {printed[-1].disc}장으로 나눠 트랙 번호를 매김"
            return CHECKED_TRACKS
        self.report.conflicts.append(
            f"{rel.id}: tracks on {page_id(page)} differ from the stored ones ({len(stored)} stored, {len(printed)} "
            f"printed; first at #{first + 1}: stored {works[first].id if first < len(stored) else None!r}, "
            f"printed {printed[first].title if first < len(printed) else None!r})")
        return None

    # checking the credits of a migrated release ------------------------------------

    def _lookup_credits(self, names: list[CreditName]) -> list[m.Credit] | None:
        """The credits as printed, from the dictionary only (a check never creates names)."""
        out = []
        for c in names:
            pid = self._find_person(c.name)
            if pid is None:
                return None
            self._saw("person", pid, c.name)
            out.append(m.Credit(person=pid, affiliation=c.affiliation, fullwidth=c.fullwidth))
        return out

    def _saw(self, kind: str, ident: str, printed: str) -> None:
        """A name the page being checked printed for an entity; the first page that prints it as
        stored is kept (``_settle_names``)."""
        if not self.page_url:
            return
        known = self.seen.get((kind, ident))
        if known is None or not _same_spelling(self.ds.table(kind)[ident].names.ja, known[0]) \
                and _same_spelling(self.ds.table(kind)[ident].names.ja, printed):
            self.seen[(kind, ident)] = (printed, self.page_url)

    def _lookup_performers(self, p: Performers | None, group_id: str | None) -> list[m.Performer] | None:
        if p is None:
            return None
        names, guests = split_featured(p.artists or ([p.artist] if p.artist else []))
        featured = [self._find_guest(g) for g in guests]
        for g, f in zip(guests, featured):
            if f:
                self._saw(*f.ref, g)
        sung = self._lookup_sung_by(p, names, group_id)
        return None if sung is None or None in featured else sung + featured  # type: ignore[operator]

    def _lookup_sung_by(self, p: Performers, names: list[str], group_id: str | None) -> list[m.Performer] | None:
        for name, voice in p.members:  # "上原歩夢(CV.大西亜玖璃)", "堀内まり菜（椿 ルリカ役）": both names are printed
            cid, pid = self.character(name) if name else None, self._find_person(voice) if voice else None
            if cid:
                self._saw("character", cid, name)
            if pid:
                self._saw("person", pid, voice)
        if names:
            group_key = match_key(self.spec.group_name)
            named = self._with_joint(names)
            ids = [group_id if match_key(n) == group_key else self._find("artist", n) for n, _ in named]
            for (n, _), a in zip(named, ids):
                if a:
                    self._saw("artist", a, n)
            return [m.Performer(artist=a, joint=j) for a, (_, j) in zip(ids, named)] if all(ids) else None
        if p.cast:
            out = []
            for role, actor in p.members:
                pid, cid = self._find_person(actor), self.character(role) if role else None
                if pid is None or role and cid is None:
                    return None
                out.append(m.Performer(person=pid, role=cid))
            return out or None
        chars = [self.character(name) for name, _ in p.members]
        return [m.Performer(character=c) for c in chars] if chars and all(chars) else None

    def _check_credits(self, tracks: list[tuple[tuple[m.Work, m.Recording], TrackObs]], release_perf: Performers | None,
                       group_id: str | None, src: m.Evidence) -> None:
        """Track by track (the tracklists are the same): credits and singers the page prints that
        equal the stored ones get the page as their evidence; different ones are conflicts. A page
        that prints only the arranger or only the singers of a recording is noted, and ``_settle``
        puts the pages together once every page was read."""
        page = page_id(src.source or "")
        self.page_url = src.source
        for (work, rec), t in tracks:
            key = (work.id, rec.id)
            where = f"{work.id}#{rec.id}"
            ver = split_version(t.title)[1]
            stored_ver = "Off Vocal" if rec.kind == "off_vocal" else rec.version
            # a version the page prints must be the stored one; a stored label the page leaves out
            # ("9 Members Ver." of the first album) is the legacy's own
            off = (ver == "Off Vocal") != (rec.kind == "off_vocal")
            if off or rec.kind != "off_vocal" and ver and match_key(ver) != match_key(stored_ver):
                self._doubt([(rec.evidence, "credits")], f"{where}: version on {page} differs: printed {t.title!r}, stored {stored_ver!r}")
                continue
            if rec.kind == "off_vocal" or rec.instrumental_of:
                self.listed.setdefault(key, src)  # the page lists it; its arranger is its vocal's
                continue
            roles = t.credits
            unknown = [c.name for names in roles.values() for c in names if self._find_person(c.name) is None]
            if unknown:
                self._doubt([(work.evidence, "credits"), (rec.evidence, "credits")],
                            f"{where}: credited names on {page} not in the dictionary: {unknown}")
                continue
            printed = {role: self._lookup_credits(names) for role, names in roles.items()}
            lyr, comp, arr = printed.get("lyricist"), printed.get("composer"), printed.get("arranger")
            if lyr is None and comp is not None and rec.kind == "instrumental" and not work.credits.lyricist:
                lyr = []  # an instrumental piece (an overture) has no lyricist to print
            if lyr is not None and comp is not None:
                if _same_credits(work.credits.lyricist, lyr) and _same_credits(work.credits.composer, comp):
                    _cite(work.evidence, "credits", src)
                    if work.evidence["credits"].source == src.source:
                        _printed_as(work.credits.lyricist, lyr)
                        _printed_as(work.credits.composer, comp)
                else:
                    order = _same_people(work.credits.lyricist, lyr) and _same_people(work.credits.composer, comp)
                    self._doubt(
                        [(work.evidence, "credits")],
                        f"{where}: lyricist/composer on {page} differ{' (order only)' if order else ''}: printed "
                        f"{_credit_ids(lyr)}/{_credit_ids(comp)}, stored "
                        f"{_credit_ids(work.credits.lyricist)}/{_credit_ids(work.credits.composer)}")
            elif not printed and work.kind != "song" and not work.credits.lyricist and not work.credits.composer:
                _cite(work.evidence, "credits", src)  # a drama track: nothing printed, nothing stored (D25)
            arranged = arr is not None and self._arrangement(rec, arr, printed, where, src)
            if not printed and rec.kind == "drama" and not rec.arranger:
                arranged = True
            singers = t.performers or self._named_singers(t.title, ver, rec) or release_perf
            perf = self._lookup_performers(singers, group_id)
            sung = perf is not None and perf == rec.performers
            if not t.performers and rec.kind in ("drama", "instrumental") and not rec.performers:
                sung = True  # a drama track without its cast, an instrumental: nobody to name
            if t.performers and not sung:
                self._doubt([(rec.evidence, "credits")], f"{where}: singers on {page} differ: printed "
                            f"{[p.ref[1] for p in perf] if perf else t.performers}, stored "
                            f"{[p.ref[1] for p in rec.performers]}")
            if arranged and sung:
                self.verified.setdefault(key, src.source or "")
                _cite(rec.evidence, "credits", src)
                if rec.evidence["credits"].source == src.source:
                    _printed_arrangers(rec, printed)
            elif arranged and key not in self.arranged_on:
                self.arranged_on[key] = src
                self.arranged_as[key] = printed
            elif sung and not printed and rec.kind == "vocal":
                self.sung_on.setdefault(key, src)  # "X (Aqours Ver.)", a solo album: the singers only

    def _arrangement(self, rec: m.Recording, arr: list[m.Credit], printed: dict[str, list[m.Credit] | None],
                     where: str, src: m.Evidence) -> bool:
        """Whether the 編曲 the page prints is the stored arranger. The 弦編曲 and 管編曲 it prints are
        stored in their own roles (D42): a migrated arranger list that also held them (the legacy
        files mixed them in, D41) is split, and a recording without them takes them from the page."""
        page = page_id(src.source or "")
        parts = {k: printed.get(k) or [] for k in ARRANGERS[1:]}
        extra = [c for k in ARRANGERS[1:] for c in parts[k] if c.ref not in {a.ref for a in arr}]
        if not _same_credits(rec.arranger, arr):
            mixed = extra and not rec.strings_arranger and not rec.brass_arranger \
                and _same_people(rec.arranger, arr + list({c.ref: c for c in extra}.values()))
            if not mixed:
                order = " (order only)" if _same_people(rec.arranger, arr) else ""
                more = "".join(f" + {k} {_credit_ids(v)}" for k, v in parts.items() if v)
                self._doubt([(rec.evidence, "credits")], f"{where}: arranger on {page} differs{order}: printed "
                            f"{_credit_ids(arr)}{more}, stored {_credit_ids(rec.arranger)}")
                return False
            rec.arranger = arr
            ev = rec.evidence.get("credits")
            if ev is not None and ev.note == LEGACY_WITH_STRINGS:  # the split leaves nothing to note
                rec.evidence["credits"] = ev.model_copy(update={"note": None})
        for k, v in parts.items():
            if not v:
                continue  # an album page may leave out what the single printed
            if not getattr(rec, k):
                setattr(rec, k, v)
                ev = rec.evidence.get("credits")
                if ev is None or ev.source != src.source:
                    rec.evidence[k] = src
            elif not _same_credits(getattr(rec, k), v):
                self._doubt([(rec.evidence, "credits")], f"{where}: {k} on {page} differs: printed "
                            f"{_credit_ids(v)}, stored {_credit_ids(getattr(rec, k))}")
                return False
        return True

    def _named_singers(self, title: str, ver: str | None, rec: m.Recording) -> Performers | None:
        """Singers a track names without a "歌：" line: in its version (``X（高海千歌 Solo Ver.）``,
        ``X (CYaRon! Ver.)``) or, for a drama track, in its title (``高海千歌 (CV.伊波杏樹)``)."""
        if rec.kind == "drama":
            mt = re.fullmatch(r"(.+?)\s*[（(]CV[.．]\s*([^()（）]+)[)）]", title.strip())
            if mt:
                return Performers(None, None, [(mt.group(1).strip(), mt.group(2).strip())])
            # "こんにちは！ ～澁谷かのん～": the one character the title names
            key = match_key(title)
            named = [c for c in self.ds.characters.values()
                     if c.project == self.spec.project and c.names.ja and match_key(c.names.ja) in key]
            return Performers(None, None, [(named[0].names.ja, "")]) if len(named) == 1 else None
        if not ver:
            return None
        name = re.sub(r"\s*(?:Solo\s*)?Ver\.?$", "", ver, flags=re.I).strip()
        if self.character(name):
            return Performers(None, None, [(name, "")])
        if self._find("artist", name):
            return Performers(name, None)
        return None

    def _settle(self) -> None:
        """After every page: a recording whose arranger one page printed and whose singers another
        did is cited to both; one with its singers only takes the arrangement of the same song's
        recording that a page printed (derived); an Off Vocal is cited once its vocal is."""
        for (wid, rid), sung in self.sung_on.items():
            work = self.ds.works[wid]
            rec = next(r for r in work.recordings if r.id == rid)
            ev = rec.evidence.get("credits")
            if ev is not None and ev.source != MIGRATED:
                if ev.status == m.Status.derived:  # cited before: it keeps following the arrangement it borrowed
                    _follow(rec, next((r for r in work.recordings if r is not rec and r.kind == "vocal" and _arranged_as(rec, r)
                                       and r.evidence.get("credits") is not None and r.evidence["credits"].status == m.Status.official
                                       and r.id in (ev.note or "")), None))
                continue
            arranged = self.arranged_on.get((wid, rid))
            if arranged is not None:
                note = "; ".join(n for n in (arranged.note, f"가창자: {sung.source}") if n)
                _cite(rec.evidence, "credits", arranged.model_copy(update={"note": note}))
                if rec.evidence["credits"].source == arranged.source:
                    _printed_arrangers(rec, self.arranged_as[(wid, rid)])
                continue
            same_page = next((r for r in work.recordings if r is not rec and r.kind == "vocal"
                              and self.verified.get((wid, r.id)) == sung.source and _arranged_as(rec, r)), None)
            if same_page is not None:  # "X (Aqours Ver.)" under the credits printed for X
                _follow(rec, same_page)
                _cite(rec.evidence, "credits", sung)
                continue
            other = next((r for r in work.recordings if r is not rec and r.kind == "vocal" and _arranged_as(rec, r)
                          and r.evidence.get("credits") is not None and r.evidence["credits"].status == m.Status.official), None)
            if other is not None and rec.arranger:
                _follow(rec, other)
                _cite(rec.evidence, "credits", m.Evidence(
                    status=m.Status.derived, source=sung.source, checked=self.today,
                    note=f"가창자는 이 페이지. 편곡은 같은 곡 {other.id}의 공식 크레딧"
                         f"({other.evidence['credits'].source})과 같다고 봄"))
        for work in self.ds.works.values():
            if work.project == self.spec.project:
                for rec in work.recordings:
                    vocal = next((r for r in work.recordings if r.id == rec.instrumental_of), None)
                    if vocal is not None and _arranged_as(rec, vocal):  # an Off Vocal is arranged as its vocal
                        _follow(rec, vocal)
        for (wid, rid), listed in self.listed.items():
            work = self.ds.works[wid]
            rec = next(r for r in work.recordings if r.id == rid)
            vocal = next((r for r in work.recordings if r.id == rec.instrumental_of), None)
            ev = vocal.evidence.get("credits") if vocal else None
            if vocal is not None and ev is not None and ev.source != MIGRATED and all(_same_credits(getattr(rec, k), getattr(vocal, k)) for k in ARRANGERS) \
                    and rec.performers in ([], vocal.performers):
                note = ev.note if ev.status == m.Status.official else f"편곡은 {vocal.id}와 같음 (그 근거를 따름)"
                _cite(rec.evidence, "credits", listed.model_copy(update={"status": ev.status, "note": note}))

    def _follow_unprinted(self) -> None:
        """An imported version printed without credits (a solo concert album's cover) is arranged as
        the same song's recording an official page credited, as the check does for migrated ones (D41)."""
        for work in self.ds.works.values():
            if work.project != self.spec.project:
                continue
            for rec in work.recordings:
                ev = rec.evidence.get("credits")
                if rec.kind != "vocal" or rec.id == "original" or rec.all_arrangers() or ev is None \
                        or ev.status != m.Status.official or not (ev.source or "").startswith("http"):
                    continue
                other = next((r for r in sorted(work.recordings, key=lambda r: r.id != "original")
                              if r is not rec and r.kind == "vocal" and r.arranger and r.evidence.get("credits") is not None
                              and r.evidence["credits"].status == m.Status.official), None)
                if other is None:
                    continue
                for k in ARRANGERS:
                    setattr(rec, k, [c.model_copy() for c in getattr(other, k)])
                rec.evidence["credits"] = m.Evidence(
                    status=m.Status.derived, source=ev.source, checked=ev.checked,
                    note=f"가창자는 이 페이지. 편곡은 같은 곡 {other.id}의 공식 크레딧({other.evidence['credits'].source})과 같다고 봄")

    def _settle_names(self) -> None:
        """Names that rest on the migration and a checked page printed: ``names.ja`` is cited to the
        page; the other spellings get their own keys, to be sourced apart (rom from Fandom, ko from
        Namuwiki, D36), except a Latin name, whose rom and ko are the name itself (§5.4)."""
        for (kind, ident), (printed, page) in sorted(self.seen.items()):
            ent = self.ds.table(kind)[ident]
            ev = ent.evidence.get("names")
            if ev is None or ev.source != MIGRATED:
                continue
            if not _same_spelling(ent.names.ja, printed):
                if not any(a.kind == "misprint" and _same_spelling(a.text, printed) for a in getattr(ent, "aliases", [])):
                    self.report.conflicts.append(f"{kind}:{ident}: printed {printed!r} on {page_id(page)}, stored {ent.names.ja!r}")
                continue  # a known misprint of the page: the spelling is sourced elsewhere
            if printed == ent.names.ja:
                note = None
            elif re.sub(r"\s+", "", printed) == re.sub(r"\s+", "", ent.names.ja or ""):
                note = f"공식 표기 {printed!r} (띄어쓰기는 D28)"
            else:  # "CYaRon!" for "CYaRon！": ja keeps the official notation (§5.1, D42)
                self.report.conflicts.append(f"{kind}:{ident}: printed {printed!r} on {page_id(page)}, stored {ent.names.ja!r} "
                                             "(full-/half-width only)")
                continue
            fields = {"names.ja": m.Evidence(status=m.Status.official, source=page, checked=self.today, note=note)}
            latin = is_latin(ent.names.ja or "")
            for f in ("kana", "rom", "ko"):
                value = getattr(ent.names, f)
                if not value:
                    continue
                if latin and f in ("rom", "ko") and value == halfwidth(ent.names.ja):
                    same = "와 같음" if value == ent.names.ja else "의 반각"
                    fields[f"names.{f}"] = m.Evidence(status=m.Status.derived, note=f"라틴 표기: {f}는 ja{same} (§5.4, D42)")
                else:
                    fields[f"names.{f}"] = ev  # still to be sourced
            del ent.evidence["names"]
            ent.evidence = fields | ent.evidence

    def _doubt(self, targets: list[tuple[dict[str, m.Evidence], str]], message: str) -> None:
        """A difference between a page and the stored values. It is reported only if the values are
        still without a source after every page was read: an album page that leaves out what the
        single printed (a string arranger) does not unsettle a value the single's page cited."""
        self.doubts.append((targets, message))

    def _upsert_release(self, obs: ReleaseObs, placed_by: list[tuple[str | None, list[tuple[int, m.Track]]]],
                        perf: list[m.Performer], item: dict[str, Any] | None) -> None:
        tracks = [t for _, placed in placed_by for _, t in placed]
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
        running = any(_runs_on(placed) for _, placed in placed_by)  # the page numbers the discs on (D42)
        albums = [m.LegacyAlbum(title=obs.title, flatten_discs=running)]
        if len(placed_by) == 1:
            discs = _discs(placed_by[0][1])
        else:  # the editions have different track lists: a disc per edition, and a legacy album each
            ids = {match_key(e.label.ja): e.id for e in editions if e.label and e.label.ja}
            discs, albums = [], []
            for label, placed in placed_by:
                eid = ids[match_key(label or "")]
                for d in _discs(placed):
                    discs.append(d.model_copy(update={"editions": [eid]}))
                albums.append(m.LegacyAlbum(title=f"{obs.title} [{label}]", edition=eid, flatten_discs=running))
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
            projects = self.spec.cross.get(obs.page_id) or [self.spec.project]
            rel = m.Release(id=ident, type=rtype, status=status, title=title if item is not None else m.Names(ja=title.ja),
                            projects=projects, artist_credit=perf, label=label, release_date=obs.release_date,
                            editions=editions, discs=discs, links=links,
                            legacy=m.ReleaseLegacy(category="Others" if len(projects) > 1 else self.spec.legacy_group,
                                                   albums=albums),
                            evidence=evidence)
            self.ds.releases[ident] = rel
            if len(projects) > 1:
                self._list_in_legacy_files(rel)
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

    def _list_in_legacy_files(self, rel: m.Release) -> None:
        """A cross-project release in the legacy album file of each of its projects (§10.1)."""
        lay = self.ds.layout
        assert lay is not None
        for p in rel.projects:
            proj = self.ds.projects.get(p)
            group = proj.legacy.file if proj and proj.legacy else None
            if group and group in lay.integrated_order:
                albums = lay.albums.setdefault(group, m.LayoutAlbumsFile(entries=[]))
                if all(e.release != rel.id for e in albums.entries):
                    albums.entries.append(m.LayoutAlbumEntry(release=rel.id))

    def layout(self, members: list[str]) -> None:
        lay = self.ds.layout
        assert lay is not None
        group = self.spec.legacy_file or self.spec.legacy_group
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


def _edition_tracks(obs: ReleaseObs) -> list[tuple[str | None, list[TrackObs], str]]:
    """The tracks to store with the page they are on: the release's, or each edition's when the
    edition pages list different tracks (a single whose editions have their own coupling song)."""
    pages = obs.edition_pages
    if len(pages) > 1 and all(p.label for p in pages) \
            and any([(t.disc, t.no, t.title) for t in p.tracks] != [(t.disc, t.no, t.title) for t in pages[0].tracks] for p in pages):
        return [(p.label, p.tracks, p.url) for p in pages]
    return [(None, obs.tracks, obs.url)]


def _song(title: str) -> tuple[str, str | None, str | None]:
    """(song title, version, version inside an Off Vocal): ``X（104期NEW Ver.）（Off Vocal）`` →
    (X, Off Vocal, 104期NEW Ver.), the instrumental of a version."""
    base, ver = split_version(title)
    inner = None
    if ver == "Off Vocal":
        base, inner = split_version(base)
    return base, ver, inner


def _arranged_as(rec: m.Recording, other: m.Recording) -> bool:
    """The same arrangement as ``other``, or one that can take its 弦編曲 and 管編曲 (D42): ``rec`` has
    none and its arranger list is ``other``'s 編曲, or all of ``other``'s arrangers (the legacy mix)."""
    if all(_same_credits(getattr(rec, k), getattr(other, k)) for k in ARRANGERS):
        return True
    return not rec.strings_arranger and not rec.brass_arranger and bool(rec.arranger) \
        and (_same_credits(rec.arranger, other.arranger) or _same_people(rec.arranger, other.all_arrangers()))


def _printed_as(stored: list[m.Credit], printed: list[m.Credit] | None) -> None:
    """The brackets of the affiliations as the page the credits are cited to prints them (D42)."""
    for s, p in zip(stored, printed or []):
        if s.ref == p.ref:
            s.fullwidth = p.fullwidth and bool(s.affiliation)


def _printed_arrangers(rec: m.Recording, printed: dict[str, list[m.Credit] | None]) -> None:
    for k in ARRANGERS:
        if printed.get(k):
            _printed_as(getattr(rec, k), printed[k])


def _follow(rec: m.Recording, other: m.Recording | None) -> None:
    """``rec`` is arranged as ``other`` (``_arranged_as``): it takes the roles as ``other`` stores them."""
    if other is None or all(getattr(rec, k) == getattr(other, k) for k in ARRANGERS):
        return
    for k in ARRANGERS:
        setattr(rec, k, [c.model_copy() for c in getattr(other, k)])
    ev = rec.evidence.get("credits")
    if ev is not None and ev.note == LEGACY_WITH_STRINGS:
        rec.evidence["credits"] = ev.model_copy(update={"note": None})


def _same_credits(a: list[m.Credit], b: list[m.Credit]) -> bool:
    """The same people in the same order; affiliations compared by match key ("Jazzin'park" = "Jazzin’park")."""
    def key(c: m.Credit) -> tuple[Any, ...]:
        aff = c.affiliation if isinstance(c.affiliation, str) or c.affiliation is None else c.affiliation.ja
        return (c.person, c.character, match_key(aff))

    return [key(c) for c in a] == [key(c) for c in b]


def _refs(credits: list[m.Credit]) -> list[tuple[str, str]]:
    return [c.ref for c in credits]


def _same_spelling(stored: str | None, printed: str) -> bool:
    """The same characters, spaces aside (the spacing of a stored name follows D28)."""
    def squash(x: str) -> str:
        return re.sub(r"\s+", "", unicodedata.normalize("NFKC", x))

    return bool(stored) and squash(stored) == squash(printed)  # type: ignore[arg-type]


def _same_title(work: m.Work, printed: str) -> bool:
    """The work's title as printed; a reading the page adds in parentheses (``夜明珠（イエミンジュ）``)
    is the work's kana."""
    if match_key(work.title.ja) == match_key(printed):
        return True
    if work.kind == "drama":  # "05. 高海千歌 (CV.伊波杏樹)" under "■はじめましてのご挨拶": "はじめましてのご挨拶 ~高海千歌~"
        own = match_key(re.sub(r"\s*[（(]CV[.．][^()（）]*[)）]\s*$", "", printed))
        if own and match_key(work.title.ja).endswith(own):
            return True
    mt = re.fullmatch(r"(.+?)\s*[（(]([^()（）]+)[)）]", printed.strip())
    return bool(mt and work.title.kana and match_key(mt.group(1)) == match_key(work.title.ja)
                and match_key(mt.group(2)) == match_key(work.title.kana))


def _same_people(a: list[m.Credit], b: list[m.Credit]) -> bool:
    return sorted(_credit_ids(a)) == sorted(_credit_ids(b))


def _credit_ids(credits: list[m.Credit]) -> list[str]:
    return [f"{c.ref[1]}({c.affiliation_in('ja')})" if c.affiliation else c.ref[1] for c in credits]


def _cite(evidence: dict[str, m.Evidence], key: str, src: m.Evidence) -> None:
    """Cite the page for a value that has only its migration as evidence; a value already cited
    to a source keeps it (the first page that printed it)."""
    ev = evidence.get(key)
    if ev is None or ev.source == MIGRATED:
        evidence[key] = src


def _discs(placed: list[tuple[int, m.Track]]) -> list[m.Disc]:
    """The tracks by disc, each disc numbered from 1 also where the page numbers them on (D42)."""
    by_disc: dict[int, list[m.Track]] = {}
    for disc, t in placed:
        by_disc.setdefault(disc, []).append(t)
    out = []
    for n, ts in sorted(by_disc.items()):
        first = min((t.no for t in ts if t.no is not None), default=1)
        out.append(m.Disc(disc=n, tracks=[t.model_copy(update={"no": t.no - first + 1}) if t.no is not None else t for t in ts]
                          if _runs_on(placed) else ts))
    return out


def _runs_on(placed: list[tuple[int, m.Track]]) -> bool:
    """Whether the page numbers the tracks on across the discs (Disc.2 starting at 8 after seven tracks)."""
    discs: dict[int, list[int]] = {}
    for disc, t in placed:
        if t.no is not None:
            discs.setdefault(disc, []).append(t.no)
    nos = [discs[d] for d in sorted(discs)]
    return len(nos) > 1 and all(b[0] == a[-1] + 1 for a, b in zip(nos, nos[1:]))


# the tracks evidence of a migrated release whose tracklist the official page confirmed
CHECKED_TRACKS = "공식 페이지의 트랙리스트와 대조함 (같음)"
# the note the first check (D41) left on a migrated arranger list that also held the 弦·管編曲 the page
# prints apart; the check splits such a list into its roles (D42) and drops the note
LEGACY_WITH_STRINGS = "편곡자에 弦·管編曲(현악·관악 편곡) 담당을 포함 (공식 페이지는 따로 표기)"
MIGRATED = m.MIGRATED


def _checked(ev: m.Evidence | None) -> bool:
    return ev is not None and (ev.note or "").startswith(CHECKED_TRACKS)


def _unsourced(rel: m.Release) -> bool:
    """A migrated release whose tracks rest on the migration only, or on an earlier check of them."""
    ev = rel.evidence.get("tracks")
    return ev is None or ev.source == MIGRATED or _checked(ev)


def _migrated(rel: m.Release) -> bool:
    """A release that came from the legacy files: its tracks are compared, never rewritten."""
    ev = rel.evidence.get("tracks")
    return "official" not in rel.links or ev is None or ev.status == m.Status.legacy or _checked(ev)


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
    for obs in site.releases:
        for t in obs.tracks:
            base, ver, _ = _song(t.title)
            if ver is None:
                imp.first_on.setdefault(match_key(base), obs.release_date)
    if spec.check_only or not spec.group_artist:  # a check looks names up and never creates them
        group_id = imp._find("artist", spec.group_name)
    else:
        group_id = imp.artist(spec.group_name, artist_kind="group", used_in="member page", source=site.member_url)
    for obs in site.releases:  # also when names are pending, so that one run lists every new name
        imp.release(obs, group_id)
    if (group_id or not spec.group_artist) and all(members) and not spec.check_only:
        if spec.lineups_from_site:
            imp.lineups(site, group_id, members)  # type: ignore[arg-type]
        imp.layout(members)  # type: ignore[arg-type]
    reviews.save()
    if not spec.check_only:
        imp._follow_unprinted()
    imp._settle()
    imp._settle_names()
    for targets, message in imp.doubts:  # differences that left a value without a source
        if any(key not in ev or ev[key].source == MIGRATED for ev, key in targets) and message not in imp.report.conflicts:
            imp.report.conflicts.append(message)
    created = set(imp.report.created)
    imp.report.updated = [ref for kind, ent in ds.iter_all()
                          if (ref := f"{kind}:{ent.id}") in before and before[ref] != ent.model_dump() and ref not in created]  # type: ignore[attr-defined]
    if ds.layout and ds.layout.model_dump() != layout_before:
        imp.report.updated.append("legacy layout")
    imp.report.skipped += site.skipped + [f"{k} {v}" for k, v in spec.skip.items()]
    return imp.report
