"""イキヅライブ！ official site adapter (DESIGN.md §6.1, §7.2 ③, §13).

Two halves:

- the parser turns pages into lines of text and reads them by section. It keeps the strings exactly
  as printed and raises when a page does not have the expected structure instead of returning
  nothing (§7.2 ③);
- the importer resolves what was read against ``data/`` and upserts the project's characters,
  artists, works and releases. A name that is not in the dictionary yet (new staff, members, units,
  song titles) goes to a ``new-names`` review file first: its readings are filled in there, the
  next run creates the entity as a draft, and ``takasaki review apply`` approves it (E3 keeps
  drafts out of the legacy files until then).
"""

from __future__ import annotations

import datetime as dt
import html as htmllib
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import model as m
from .official import BASE, Fetcher, NameReviews, item_values
from .store import Dataset
from .text import is_latin, match_key, split_version

LIST_PATH = "/lovehigh/music/"
MEMBER_PATH = "/lovehigh/member/"
_DETAIL = re.compile(r'href="(https://www\.lovelive-anime\.jp/lovehigh/music/detail\.php\?p=[^"]+)"')


class ParseError(ValueError):
    pass


def page_lines(html: str, start: str = "<!--Music", end: str = "<!--Footer") -> list[str]:
    body = html[html.find(start):html.find(end)] if start in html and end in html else html
    text = re.sub(r"<br\s*/?>", "\n", body)
    text = re.sub(r"<[^>]+>", "", text)
    text = htmllib.unescape(text)
    return [" ".join(line.split()) for line in text.split("\n") if line.strip()]


# --- music list -------------------------------------------------------------------


def list_detail_urls(html: str) -> list[str]:
    return list(dict.fromkeys(_DETAIL.findall(html)))


def list_page_count(html: str) -> int:
    return max([1] + [int(n) for n in re.findall(r'href="\?page=(\d+)"', html)])


# --- credits ----------------------------------------------------------------------

ROLE = {"作詞": "lyricist", "作曲": "composer", "編曲": "arranger"}
_ROLES = r"(?:作詞|作曲|編曲)(?:\s*[／/]\s*(?:作詞|作曲|編曲))*"
_AFFILIATION = re.compile(r"^(.*?)\s*[（(]([^()（）]+)[)）]$")


@dataclass
class CreditName:
    name: str
    affiliation: str | None = None


def parse_credit_line(line: str) -> dict[str, list[CreditName]]:
    """``作詞：畑 亜貴　作曲/編曲：光増ハジメ (FirstCall)`` → {lyricist: [畑 亜貴], composer/arranger: [光増ハジメ (FirstCall)]}."""
    out: dict[str, list[CreditName]] = {}
    # a name may contain spaces, so segments are split only before "<roles>："
    for seg in re.split(rf"\s+(?={_ROLES}\s*[：:])", line.strip()):
        mt = re.match(rf"^({_ROLES})\s*[：:]\s*(.+)$", seg)
        if not mt:
            raise ParseError(f"not a credit segment: {seg!r} in {line!r}")
        roles = [ROLE[r.strip()] for r in re.split(r"[／/]", mt.group(1))]
        if re.search(r"[：:]", mt.group(2)):  # a label this parser does not know ("歌：…")
            raise ParseError(f"unknown credit label in {seg!r}")
        names = []
        for part in re.split(r"\s*[・、&＆]\s*", mt.group(2)):
            am = _AFFILIATION.match(part.strip())
            names.append(CreditName(am.group(1).strip(), am.group(2).strip()) if am else CreditName(part.strip()))
        for r in roles:
            out[r] = names
    return out


def is_credit_line(line: str) -> bool:
    return re.match(rf"^{_ROLES}\s*[：:]", line) is not None


# --- performers ---------------------------------------------------------------------

_MEMBER = re.compile(r"\s*([^,，()（）]+?)\s*\(CV\.\s*([^)]+)\)")
_FROM = re.compile(r"\s+from\s+(\S+)\s*$")


@dataclass
class Performers:
    artist: str | None  # "いきづらい部！", "CHAKI！"; None for a list of members only
    group: str | None  # "いきづらい部！" when the line says "… from いきづらい部！"
    members: list[tuple[str, str]] = field(default_factory=list)  # (character, voice actress) as printed


def parse_performers(lines: list[str]) -> Performers:
    """An optional artist line (``CHAKI！ from いきづらい部！``), then members ``名前(CV.声優) , …``,
    where the last line may end with ``from いきづらい部！``."""
    rest = [re.sub(r"^アーティスト[：:]\s*", "", ln).strip() for ln in lines if ln.strip()]
    artist = group = None
    if rest and "(CV." not in rest[0]:
        head = rest.pop(0)
        fm = _FROM.search(head)
        if fm:
            group, head = fm.group(1), head[:fm.start()]
        artist = head.strip() or None
    text = " ".join(rest)
    fm = _FROM.search(text)
    if fm:
        group, text = group or fm.group(1), text[:fm.start()]
    members = [(a.strip(), b.strip()) for a, b in _MEMBER.findall(text)]
    if not artist and not members:
        raise ParseError(f"no performers in {lines!r}")
    return Performers(artist, group, members)


# --- release detail -----------------------------------------------------------------


@dataclass
class TrackObs:
    no: int
    title: str
    performers: Performers | None = None
    credits: dict[str, list[CreditName]] = field(default_factory=dict)


@dataclass
class EditionObs:
    label: str | None
    catalog: str
    media: str | None = None  # as printed: "CD+BD+グッズ", "CDのみ"


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

    @property
    def page_id(self) -> str:
        return self.url.rsplit("=", 1)[-1]


def _date(s: str) -> dt.date:
    mt = re.search(r"(\d{4})[年.](\d{1,2})[月.](\d{1,2})", s)
    if not mt:
        raise ParseError(f"no date in {s!r}")
    return dt.date(int(mt.group(1)), int(mt.group(2)), int(mt.group(3)))


def parse_detail(html: str, url: str) -> ReleaseObs:
    lines = page_lines(html)
    if "BACK" in lines:
        lines = lines[:lines.index("BACK")]
    try:
        series, title_line, release_line = lines[0], lines[1], lines[2]
        i_artist, i_date = lines.index("アーティスト"), lines.index("発売日")
        i_catalog = lines.index("品番")
        i_content = next(i for i, ln in enumerate(lines) if ln.startswith("収録内容"))
    except (ValueError, IndexError, StopIteration) as e:
        raise ParseError(f"{url}: unexpected page structure ({e!r})") from e
    title = re.sub(r"^[「『](.*)[」』]$", r"\1", title_line.strip())
    performers = parse_performers(lines[i_artist + 1:i_date])
    date_line = lines[i_date + 1]
    note = date_line.split("※", 1)[1].strip() if "※" in date_line else None
    i_price = lines.index("価格") if "価格" in lines else i_content
    editions, label = [], None
    for line in lines[i_catalog + 1:min(i_price, i_content)]:
        if line.startswith("※") or line.startswith("（※"):
            continue
        lm = re.match(r"^【(.+?)】$", line)
        if lm:
            label = lm.group(1)
            continue
        cm = re.match(r"^(?:【(.+?)】\s*)?([A-Z]{2,5}-\d{4,6})\s*(?:[\[［](.+?)[\]］])?", line)
        if cm:
            editions.append(EditionObs(cm.group(1) or label, cm.group(2), cm.group(3)))
            label = None
    if not editions:
        raise ParseError(f"{url}: no catalog number")
    # tracks: from 収録内容 to the first video section or link line
    content = [lines[i_content].removeprefix("収録内容").strip()] + lines[i_content + 1:]
    tracks: list[TrackObs] = []
    pending: list[str] = []
    for line in content:
        if line.startswith(("■", "▼")) or "http" in line or re.match(r"^【(?:Blu-ray|BD)", line):
            break
        if not line or re.match(r"^【.*】$", line):
            continue
        tm = re.match(r"^(\d{1,2})\.\s*(.+)$", line)
        if tm:
            tracks.append(TrackObs(int(tm.group(1)), tm.group(2).strip()))
            pending = []
            continue
        if not tracks:
            continue  # headings such as "1stソロシングル表題曲"
        if is_credit_line(line):
            tracks[-1].credits.update(parse_credit_line(line))
        else:
            pending.append(line)
            tracks[-1].performers = parse_performers(pending)
    if not tracks:
        raise ParseError(f"{url}: no tracks")
    links = {}
    for line in lines:
        lm = re.match(r"^■(.+?)[：:]\s*(https?://\S+)", line)
        if lm:
            links[lm.group(1).strip()] = lm.group(2)
    return ReleaseObs(url, series, title, _date(release_line), performers, editions, tracks, links, note)


# --- members ----------------------------------------------------------------------


@dataclass
class MemberObs:
    name: str  # as printed (official notation)
    rom_family_first: str  # "Takahashi Polka"
    grade: str | None
    cv: str
    cv_rom_family_first: str


def parse_members(html: str) -> list[MemberObs]:
    lines = page_lines(html, "<main", "<!--Footer") if "<main" in html else page_lines(html)
    out: list[MemberObs] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # a profile starts with the Latin name, then the Japanese name followed by a "-->" leftover
        if re.fullmatch(r"[A-Z][a-z]+ [A-Z][a-z]+", line) and i + 1 < len(lines) and lines[i + 1].endswith("-->"):
            rom, name = line, lines[i + 1].removesuffix("-->").strip()
            j = i + 2
            while j < len(lines) and not lines[j].startswith("CV."):
                j += 1
            if j >= len(lines):
                break
            grade = next((lines[k + 1] for k in range(i, j) if lines[k] == "学年"), None)
            cv = lines[j].removeprefix("CV.").strip()
            cv_rom = lines[j + 1] if j + 1 < len(lines) else ""
            if not out or out[-1].name != name:
                out.append(MemberObs(name, rom, grade, cv, cv_rom))
            i = j + 2
            continue
        i += 1
    if not out:
        raise ParseError("member page: no profiles found")
    return out


# --- collect ----------------------------------------------------------------------

PROJECT = "ikizulive"
LEGACY_GROUP = "Ikizulive"  # D3
# releases left to a later phase; the reason is printed on every run
SKIP = {"01_5904": "AiScReam「NEXT CARD」: cross-project unit (Phase 3)"}


@dataclass
class Site:
    members: list[MemberObs]
    releases: list[ReleaseObs]  # oldest first
    member_url: str


def collect(fetcher: Fetcher, *, fresh: bool = False) -> Site:
    first = fetcher.get(LIST_PATH, fresh=fresh)
    urls = list_detail_urls(first.html)
    for page in range(2, list_page_count(first.html) + 1):
        urls += list_detail_urls(fetcher.get(f"{LIST_PATH}?page={page}", fresh=fresh).html)
    rels = [parse_detail(fetcher.get(u, fresh=fresh).html, u) for u in dict.fromkeys(urls)
            if u.rsplit("=", 1)[-1] not in SKIP]
    rels.reverse()  # the list is newest first
    rels.sort(key=lambda r: r.release_date)
    members = parse_members(fetcher.get(MEMBER_PATH, fresh=fresh).html)
    return Site(members, rels, BASE + MEMBER_PATH)


# --- import -----------------------------------------------------------------------

REVIEW_FILES = {  # new-names review file per kind of name
    "member": "IKZ-members.yaml",  # characters and their voice actresses
    "artist": "IKZ-artists.yaml",
    "person": "IKZ-persons.yaml",  # staff in the credits
    "work": "IKZ-titles.yaml",
    "release": "IKZ-titles.yaml",
}


@dataclass
class Report:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)  # names whose readings are not filled in yet
    conflicts: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _media(printed: str | None) -> list[str]:
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


class Importer:
    def __init__(self, ds: Dataset, reviews: NameReviews, today: dt.date, member_names: set[str] = frozenset()) -> None:  # type: ignore[assignment]
        self.ds, self.reviews, self.today = ds, reviews, today
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
        key = match_key(printed)
        if kind == "character":
            hits = [c.id for c in self.ds.characters.values() if c.project == PROJECT and match_key(c.names.ja) == key]
        elif kind == "artist":
            hits = [a.id for a in self.ds.artists.values() if PROJECT in a.projects and match_key(a.names.ja) == key]
        elif kind == "work":
            hits = [w.id for w in self.ds.works.values() if w.project == PROJECT and match_key(w.title.ja) == key]
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
        ident = item.get("id") or _slug_id(kind, rom)
        if ident in self.ds.table(kind):
            raise ValueError(f"{kind} id {ident!r} already exists; set `id:` on the review item for {item['printed']!r}")
        if kind == "person":
            ent: Any = m.Person(id=ident, **values, evidence={"names": m.Evidence(**draft)})
            if item.get("name_parts") and not values.get("family_name"):
                ent.evidence["name_parts"] = m.Evidence(status=m.Status.derived, note=str(item["name_parts"]))
        elif kind == "character":
            ent = m.Character(id=ident, project=PROJECT, **values, evidence={"names": m.Evidence(**draft)})
        elif kind == "artist":
            ent = m.Artist(id=ident, kind=item.get("artist_kind", "unit"), projects=[PROJECT], **values,
                           evidence={"names": m.Evidence(**draft)})
        elif kind == "work":
            ent = m.Work(id=ident, project=PROJECT, title=values["title"], recordings=[],
                         evidence={"title": m.Evidence(**draft)})
        else:
            raise ValueError(kind)
        self.ds.table(kind)[ident] = ent
        item["ref"] = f"{kind}:{ident}"
        self.report.created.append(f"{kind}:{ident}")
        return ident

    # members ----------------------------------------------------------------------

    def members(self, site: Site) -> list[str | None]:
        out = []
        for mem in site.members:
            fam_rom, giv_rom = mem.cv_rom_family_first.split(" ", 1)
            split = _split_ja(mem.cv, fam_rom)
            cv = self.resolve("person", mem.cv, file=REVIEW_FILES["member"], used_in=f"CV of {mem.name}", seed={
                "family_name": {"ja": split[0] if split else "", "rom": fam_rom},
                "given_name": {"ja": split[1] if split else "", "rom": giv_rom},
                "source": site.member_url,
            })
            fam_rom, giv_rom = mem.rom_family_first.split(" ", 1)
            split = _split_ja(mem.name, fam_rom)
            ch = self.resolve("character", mem.name, file=REVIEW_FILES["member"], used_in=f"member page ({mem.grade})", seed={
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
        return self.resolve("artist", printed, file=REVIEW_FILES["artist"], seed=seed, used_in=used_in)

    # credits ----------------------------------------------------------------------

    def credits(self, names: list[CreditName], used_in: str, source: str) -> list[m.Credit] | None:
        out: list[m.Credit | None] = []
        for c in names:
            seed: dict[str, Any] = {"source": source}
            if is_latin(c.name):
                seed |= {"names": {"ja": c.name, "rom": c.name, "ko": c.name}, "native_script": "latin"}
            pid = self.resolve("person", c.name, file=REVIEW_FILES["person"], seed=seed, used_in=used_in)
            out.append(m.Credit(person=pid, affiliation=c.affiliation) if pid else None)
        return None if None in out else out  # every name is looked up, so one run lists them all

    # works and releases -----------------------------------------------------------

    def performers(self, p: Performers, group_id: str | None, used_in: str | None = None) -> list[m.Performer] | None:
        if p.artist:
            aid = group_id if p.artist == GROUP_NAME else self.artist(p.artist, used_in=used_in, source=self.page)
            return [m.Performer(artist=aid)] if aid else None
        chars = [self.character(name) for name, _ in p.members]
        if not all(chars):
            strangers = [name for name, _ in p.members if match_key(name) not in self.member_keys]
            if strangers:  # otherwise the member is only waiting for review
                self.report.conflicts.append(f"not on the member page: {strangers}")
            return None
        return [m.Performer(character=c) for c in chars]

    def release(self, obs: ReleaseObs, group_id: str | None) -> None:
        tracks: list[m.Track] = []
        self.page = obs.url
        release_perf = self.performers(obs.performers, group_id, obs.page_id)
        complete = release_perf is not None
        title_item = None
        known = any(r.links.get("official") == obs.url for r in self.ds.releases.values())
        if not known and not all(p in {split_version(t.title)[0] for t in obs.tracks} for p in obs.title.split(" / ")):
            # a title that is not made of song titles is named in review (its rom gives the id)
            title_item = self.reviews.item(REVIEW_FILES["release"], "release", obs.title,
                                           {"title": {"ja": obs.title, "rom": "", "ko": ""}, "source": obs.url}, obs.page_id)
            try:
                item_values(title_item)
            except (KeyError, ValueError) as e:
                self.report.pending.append(f"release {obs.title}: {e}")
                complete = False
        vocal_of: dict[str, m.Recording] = {}
        for t in obs.tracks:
            base, ver = split_version(t.title)
            used = f"{obs.page_id} #{t.no}"
            wid = self.resolve("work", base, file=REVIEW_FILES["work"], used_in=used,
                               seed={"title": {"ja": base, "rom": _rom_title(base), "ko": base if is_latin(base) else ""},
                                     "source": obs.url})
            perf = self.performers(t.performers, group_id, used) if t.performers else release_perf
            credits = {role: self.credits(names, f"{base}: {role}", obs.url) for role, names in t.credits.items()}
            if wid is None or perf is None or any(v is None for v in credits.values()):
                complete = False
                continue
            if not complete and ver == "Off Vocal":
                continue  # its vocal track is waiting for names too
            work = self.ds.works[wid]
            rec = self.recording(work, ver, perf, credits, obs, vocal_of)
            if rec is None:
                complete = False
                continue
            tracks.append(m.Track(no=t.no, recording=f"{wid}#{rec.id}"))
        if not complete:
            self.report.skipped.append(f"{obs.page_id} {obs.title}: waiting for names")
            return
        self._upsert_release(obs, tracks, release_perf or [], title_item)

    def recording(self, work: m.Work, ver: str | None, perf: list[m.Performer], credits: dict[str, list[m.Credit] | None],
                  obs: ReleaseObs, vocal_of: dict[str, m.Recording]) -> m.Recording | None:
        lyr, comp, arr = credits.get("lyricist"), credits.get("composer"), credits.get("arranger")
        src = m.Evidence(status=m.Status.official, source=obs.url, checked=self.today)
        if lyr is not None or comp is not None:
            new = m.WorkCredits(lyricist=lyr or [], composer=comp or [])
            if not work.credits.lyricist and not work.credits.composer:
                work.credits = new
                work.evidence["credits"] = src
            elif work.credits != new:
                self.report.conflicts.append(f"{work.id}: credits on {obs.page_id} differ from the stored ones")
        if ver == "Off Vocal":
            vocal = vocal_of.get(work.id) or next((r for r in work.recordings if r.id == "original"), None)
            if vocal is None:
                self.report.conflicts.append(f"{work.id}: Off Vocal without a vocal recording on {obs.page_id}")
                return None
            rid, title = ("off-vocal" if vocal.id == "original" else f"{vocal.id}-off-vocal"), _suffixed(work.title, " (Off Vocal)")
            fields: dict[str, Any] = {"kind": "off_vocal", "title": title, "version": "Off Vocal", "instrumental_of": vocal.id,
                                      "arranger": arr if arr is not None else vocal.arranger}
        elif ver is None:
            rid = "original"
            fields = {"performers": perf, "arranger": arr or []}
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
            raise ParseError(f"{obs.url}: unhandled version {ver!r} of {work.title.ja}")
        rec = next((r for r in work.recordings if r.id == rid), None)
        if rec is None:
            rec = m.Recording(id=rid, **fields, evidence={"credits": src})
            work.recordings.append(rec)
        else:
            for k, v in fields.items():
                if k == "arranger" and not v:
                    continue  # a page without credits (the unit album's repeats) keeps what was read before
                setattr(rec, k, v)
        if ver is None:
            vocal_of[work.id] = rec
        return rec

    def _upsert_release(self, obs: ReleaseObs, tracks: list[m.Track], perf: list[m.Performer],
                        item: dict[str, Any] | None) -> None:
        rel = next((r for r in self.ds.releases.values() if r.links.get("official") == obs.url), None)
        catalog = obs.editions[0].catalog
        rtype = "digital_single" if catalog.startswith("LZC") else "album" if catalog.startswith("LACA") else "single"
        if len(obs.editions) == 1:
            e = obs.editions[0]
            editions = [m.Edition(id="e1", label=m.Names(ja=e.label) if e.label else None, catalog=e.catalog,
                                  media=_media(e.media) or (["digital"] if rtype == "digital_single" else []))]
        else:
            editions = [m.Edition(id=f"e{i}", label=m.Names(ja=e.label) if e.label else None, catalog=e.catalog, media=_media(e.media))
                        for i, e in enumerate(obs.editions, 1)]
        links = {"official": obs.url} | ({"smartlink": obs.links["楽曲配信"]} if "楽曲配信" in obs.links else {})
        status = "announced" if obs.release_date > self.today else "released"
        src = m.Evidence(status=m.Status.official, source=obs.url, checked=self.today)
        evidence = {"tracks": src, "editions": src}
        if obs.note:
            evidence["release_date"] = src.model_copy(update={"note": obs.note})
        if rel is None:  # an existing release keeps its title
            if item is not None:
                title = item_values(item)["title"]
            else:  # song titles: their rom gives the id
                works = {w.title.ja: w for w in (self.ds.recording(t.recording)[0] for t in tracks)}
                title = m.Names(ja=obs.title, rom=" / ".join(works[p].title.rom or "" for p in obs.title.split(" / ")))
            ident = f"{PROJECT}/{obs.release_date.year}-{_slug(title.rom or '')}"
            if ident in self.ds.releases:
                raise ValueError(f"release id {ident!r} already exists ({obs.url})")
            if item is not None:  # a title that is not made of song titles was named in review
                item["ref"] = f"release:{ident}"
                evidence["title"] = m.Evidence(status=m.Status.draft, source=f"automation/review/{REVIEW_FILES['release']}",
                                               note="승인 대기 (new-names 리뷰)")
            rel = m.Release(id=ident, type=rtype, status=status, title=title if item is not None else m.Names(ja=title.ja),
                            projects=[PROJECT], artist_credit=perf,
                            label="Lantis" if catalog.startswith("LA") else None, release_date=obs.release_date,
                            editions=editions, discs=[m.Disc(tracks=tracks)], links=links,
                            legacy=m.ReleaseLegacy(category=LEGACY_GROUP, albums=[m.LegacyAlbum(title=obs.title)]),
                            evidence=evidence)
            self.ds.releases[ident] = rel
            self.report.created.append(f"release:{ident}")
            return
        before = rel.model_dump()
        rel.type, rel.artist_credit, rel.release_date, rel.editions = rtype, perf, obs.release_date, editions
        rel.discs = [m.Disc(tracks=tracks)]
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
        for obs in site.releases:
            p = obs.performers
            if not p.artist or p.artist == GROUP_NAME or not p.members:
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
        if LEGACY_GROUP not in lay.integrated_order:
            lay.integrated_order.append(LEGACY_GROUP)
        albums = lay.albums.setdefault(LEGACY_GROUP, m.LayoutAlbumsFile(entries=[]))
        have = {e.release for e in albums.entries}
        rels = sorted((r for r in self.ds.releases.values() if PROJECT in r.projects and r.legacy.albums),
                      key=lambda r: (r.release_date or dt.date.max, r.id))
        for rel in rels:
            if rel.id not in have:
                albums.entries.append(m.LayoutAlbumEntry(release=rel.id))
        rows = lay.members.setdefault(LEGACY_GROUP, m.LayoutMembersFile(rows=[]))
        known = {r.character for r in rows.rows}
        rows.rows += [m.LayoutMemberRow(character=c) for c in members if c not in known]


GROUP_NAME = "いきづらい部！"


def _slug(s: str) -> str:
    from .text import slugify

    return slugify(s)


def _slug_id(kind: str, rom: str | None) -> str:
    if not rom:
        raise ValueError("rom is needed for the id")
    return f"{PROJECT}/{_slug(rom)}" if kind in ("character", "work") else _slug(rom)


def _suffixed(n: m.Names, suffix: str) -> m.Names:
    return m.Names(ja=n.ja + suffix if n.ja else None, rom=n.rom + suffix if n.rom else None, ko=n.ko + suffix if n.ko else None)


def import_site(ds: Dataset, site: Site, review_dir: Path, today: dt.date) -> Report:
    """Upsert everything read from the site. Names still waiting in a review file leave the
    releases that use them out; the review files are written back with what was found."""
    reviews = NameReviews(review_dir, PROJECT)
    imp = Importer(ds, reviews, today, {mem.name for mem in site.members})
    before = {f"{kind}:{ent.id}": ent.model_dump() for kind, ent in ds.iter_all()}  # type: ignore[attr-defined]
    layout_before = ds.layout.model_dump() if ds.layout else None
    members = imp.members(site)
    group_id = imp.artist(GROUP_NAME, artist_kind="group", used_in="member page", source=site.member_url)
    for obs in site.releases:  # also when names are pending, so that one run lists every new name
        imp.release(obs, group_id)
    if group_id and all(members):
        imp.lineups(site, group_id, members)  # type: ignore[arg-type]
        imp.layout(members)  # type: ignore[arg-type]
    reviews.save()
    created = set(imp.report.created)
    imp.report.updated = [ref for kind, ent in ds.iter_all()
                          if (ref := f"{kind}:{ent.id}") in before and before[ref] != ent.model_dump() and ref not in created]  # type: ignore[attr-defined]
    if ds.layout and ds.layout.model_dump() != layout_before:
        imp.report.updated.append("legacy layout")
    imp.report.skipped += [f"{k} {v}" for k, v in SKIP.items()]
    return imp.report
