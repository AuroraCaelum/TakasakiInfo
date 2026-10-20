"""Concerts (DESIGN.md §4.6, §7.7, D47): schedules, and set lists read from Fandom.

A concert's schedule (stops, venues, dates) comes from its official live page; the set lists from
its Fandom page (``fandom.py``). The concert names its Fandom page (``external_ids.fandom``) and
each performance the set-list tab it is read from (``external_ids.fandom``: ``<section>|<tab>``),
so a later run reads the same tab again whatever the page's layout.

A set list read from Fandom is a draft (§7.7 ``performed``): it is replaced on each run until the
concert is ``settled``; after that a difference is reported, never written. Songs that match no work
keep their printed title (``title_raw``, E9) and are listed in a review file.
"""

from __future__ import annotations

import datetime as dt
import io
import re
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from . import fandom
from . import model as m
from .importer import Report
from .official import NameReviews
from .store import Dataset
from .text import halfwidth, is_latin, match_key, slugify, split_version

REVIEW_PREFIX = "LIV"
# the rights holders' sites and the official sites of events they organize
OFFICIAL = ("lovelive-anime.jp", "yohane.net", "lantis.jp", "bandainamco", "tutoliella-live.jp", "ijigen-fes.jp",
            "lovelive-overseas.bitfan.id")

# Fandom's names for artists the dataset writes otherwise
ALIASES = {"YYY": "waiwaiwai", "Mi&Nori=Tea": "mi-nori-tea"}

# what Fandom's set lists write wrong, by the item's title there: the corrected title and Japanese title
TITLE_FIXES: dict[str, dict[str, str | None]] = {
    "Ima Shiknai Shunkan o": {"title": "Ima Shika Nai Shunkan o"},  # 今しかない
    "Dancing Tamahaire La-Pa-Pa-Pa!": {"title": "Dancing Tamaire La-Pa-Pa-Pa!"},  # 玉入れ is たまいれ
    "Niko no Kako": {"title": "Nico no Kako"},  # the characters' rom (Nico, Eli)
    "Eri no Yaritai Koto": {"title": "Eli no Yaritai Koto"},
    # the soundtrack's own spelling (otonokizaka release.php#cd48)
    "Love Live! Kesshou": {"ja": "ラブライブ！決勝"},
    "Koremade no Love Live! ~Musical Ver.~": {"ja": "これまでのラブライブ！ ～ミュージカルver.～"},
    "Zetsubou": {"ja": "絶望"},
    # songs of other series, as their own releases write them
    "Dye the Sky": {"title": "Dye the sky."},
    "Shine In the Sky☆": {"title": "Shine In The Sky☆"},
    "Hoshi Meguri no Uta": {"ja": "星めぐりの歌"},
}


def _fixed(it: fandom.Item) -> fandom.Item:
    fix = TITLE_FIXES.get(it.title)
    return replace(it, **fix) if fix else it  # type: ignore[arg-type]

_GENERIC = {"mc": {"mc"}, "video": {"intermission", "video", "vtr", "movie", "animation"}}


def _loose(s: str) -> str:
    """A match key that forgives the romanization of long vowels (Yuuki / Yuki, Waai / Wai) and ー."""
    k = match_key(s).replace("ー", "")
    return re.sub(r"([aiueo])\1+", r"\1", k.replace("ou", "o"))


class Resolver:
    """Works and singers by the names Fandom writes them with."""

    def __init__(self, ds: Dataset) -> None:
        self.ds = ds
        self.strict: dict[str, set[str]] = defaultdict(set)
        self.loose: dict[str, set[str]] = defaultdict(set)
        for w in ds.works.values():
            if w.kind not in ("song", "bgm"):  # a soundtrack cue is played live too (D50)
                continue
            names = [w.title.ja, w.title.rom, w.external_ids.get("fandom")]
            names += [n for r in w.recordings if r.title for n in (r.title.ja, r.title.rom)]
            for s in filter(None, names):
                for x in {s, split_version(s)[0]}:
                    self.strict[match_key(x)].add(w.id)
                self.loose[_loose(s)].add(w.id)
        self.singers: dict[str, set[tuple[str, str]]] = defaultdict(set)
        for c in ds.characters.values():
            rom = c.names.rom or ""
            self.singers[match_key(rom, person=True)].add(("character", c.id))
            if " " in rom:
                given, family = rom.rsplit(" ", 1)
                self.singers[match_key(f"{family} {given}", person=True)].add(("character", c.id))
        for a in ds.artists.values():
            for s in filter(None, (a.names.rom, a.names.ja)):
                self.singers[match_key(_feat(s), person=True)].add(("artist", a.id))
        for p in ds.persons.values():
            for s in filter(None, (p.names.rom, p.names.ja)):
                self.singers[match_key(s, person=True)].add(("person", p.id))
        for alias, aid in ALIASES.items():
            self.singers[match_key(alias, person=True)] = {("artist", aid)}

    def work(self, it: fandom.Item, projects: list[str]) -> tuple[m.Work | None, str | None]:
        """The work an item names, or why none: ``None`` (no work by that name) or ``"ambiguous"``."""
        title = re.sub(r"\s*\((?:song|[^)]*\bver\.?|[^)]*version)\)$", "", it.title, flags=re.I)
        names = ([it.ja, split_version(it.ja)[0]] if it.ja else []) + [it.title, title, split_version(title)[0]]
        found = next((self.strict[k] for n in names if (k := match_key(n)) and k in self.strict), None)
        if not found:
            found = next((self.loose[k] for n in names if (k := _loose(n)) and len(self.loose.get(k, ())) == 1), None)
        if not found:
            return None, None
        ids = sorted(found)
        if len(ids) > 1:
            ids = [i for i in ids if self.ds.works[i].project in projects] or ids
        return (self.ds.works[ids[0]], None) if len(ids) == 1 else (None, "ambiguous")

    def _one(self, name: str, projects: list[str]) -> tuple[str, str] | None:
        found = self.singers.get(match_key(_feat(name), person=True), set())
        if len(found) > 1:  # an artist before a character before a person; this concert's projects first
            rank = {"artist": 0, "character": 1, "person": 2}
            found = {min(found, key=lambda r: (rank[r[0]], self._project(r) not in projects, r[1]))}
        return next(iter(found), None)

    def _project(self, ref: tuple[str, str]) -> str | None:
        kind, ident = ref
        if kind == "character":
            return self.ds.characters[ident].project
        if kind == "artist":
            return next(iter(self.ds.artists[ident].projects), None)
        return None

    def performers(self, it: fandom.Item, projects: list[str]) -> tuple[list[m.Performer], list[str]]:
        """The singers of an item, and the names that match no artist, character or person."""
        whole = self._one(it.by, projects) if it.by else None
        if whole:
            return [m.Performer(**{whole[0]: whole[1]})], []
        out: list[m.Performer] = []
        missing: list[str] = []
        for s in it.singers:
            parts = re.split(r"\s+(feat\.|featuring|with)\s+", _feat(s))
            featured = False
            for sep, part in zip([None, *parts[1::2]], parts[::2]):
                featured = featured or sep in ("feat.", "featuring")  # the guests after "feat." (D48)
                ref = self._one(part, projects)
                if ref is None:
                    missing.append(part)
                elif all(p.ref != ref for p in out):
                    out.append(m.Performer(**{ref[0]: ref[1]}, featured=featured))
        return out, missing

    @staticmethod
    def recording(work: m.Work, version: str | None) -> str | None:
        """The recording of the version sung, when the work has one by that version name."""
        if not version:
            return None
        key = match_key(version)
        rec = next((r for r in work.recordings if r.kind == "vocal" and r.version and match_key(r.version) == key), None)
        return f"{work.id}#{rec.id}" if rec else None


def _feat(s: str) -> str:
    return re.sub(r"\s+ft\.?\s+", " feat. ", s)


def _marker(it: fandom.Item) -> m.SetlistItem:
    text = it.title.strip()
    if it.kind == "encore":
        label: str | None = "Encore" if re.fullmatch(r"encore", text, re.I) else text
    elif it.kind == "double_encore":
        label = "Double Encore" if re.fullmatch(r"(?:double|w)[\s-]*encore", text, re.I) else text
    elif it.kind in _GENERIC and match_key(text) in _GENERIC[it.kind]:
        label = None  # numbered by the legacy builder (::MC1, ::VID1)
    else:
        label = text
    return m.SetlistItem(type=it.kind, label=label)  # type: ignore[arg-type]


def _version(it: fandom.Item) -> str | None:
    return it.version or (split_version(it.ja)[1] if it.ja else None) or split_version(it.title)[1]


def setlist(items: list[fandom.Item], res: Resolver, projects: list[str]) -> tuple[list[m.SetlistItem], list[dict[str, Any]]]:
    """The set list of one tab, and its songs that match no work."""
    out: list[m.SetlistItem] = []
    unresolved: list[dict[str, Any]] = []
    for n, it in enumerate(items, 1):
        if it.kind != "song":
            out.append(_marker(it))
            continue
        it = _fixed(it)
        work, why = res.work(it, projects)
        perf, _ = res.performers(it, projects)
        version = _version(it)
        if work is None:
            raw = it.ja or it.title
            out.append(m.SetlistItem(title_raw=raw, version=version, performers=perf))
            unresolved.append({"position": n, "title_raw": raw, "fandom_title": it.title, "singers": it.by,
                               "linked": it.linked, "why": why or "no work by this title"})
            continue
        rec = res.recording(work, version)
        out.append(m.SetlistItem(work=work.id, recording=rec, version=None if rec else version, performers=perf))
    return out, unresolved


def _songs(items: list[m.SetlistItem]) -> list[str]:
    return [x.work or x.recording or x.title_raw or "?" for x in items if x.type == "song"]


def _diff(old: list[str], new: list[str]) -> str:
    """The positions where two song lists differ: ``#9 liella/anniversary → liella/primary``."""
    import difflib

    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=old, b=new).get_opcodes():
        if op != "equal":
            out.append(f"#{i1 + 1} {', '.join(old[i1:i2]) or '-'} → {', '.join(new[j1:j2]) or '-'}")
    return "; ".join(out)


def tab_key(t: fandom.Tab) -> str:
    return f"{t.section or ''}|{t.name}"


SETLIST_NOTE = "Fandom 세트리스트 초안 (performed: 나무위키 대조·승인 전, 공식 미게재)"


def import_setlists(ds: Dataset, pages: dict[str, str], review_dir: Path, today: dt.date) -> Report:
    """Read the set list of every performance whose concert names a Fandom page."""
    report = Report()
    res = Resolver(ds)
    open_items: list[dict[str, Any]] = []
    for c in sorted(ds.concerts.values(), key=lambda c: c.id):
        page = c.external_ids.get("fandom")
        if not page:
            continue
        if page not in pages:
            report.skipped.append(f"{c.id}: Fandom page {page!r} was not read")
            continue
        tabs = {tab_key(t): t for t in fandom.parse_setlists(pages[page])}
        for s in c.stops:
            for p in s.performances:
                keys = [k for k in p.external_ids.get("fandom", "").split("; ") if k]
                if not keys:
                    continue
                if missing := [k for k in keys if k not in tabs]:
                    report.conflicts.append(f"{c.id} {p.date}: Fandom has no tab {missing}")
                    continue
                items = [it for k in keys for it in tabs[k].items]
                new, unresolved = setlist(items, res, c.projects)
                where = f"{c.id} {p.date}{' ' + p.label if p.label else ''}"
                if c.status in ("settled", "confirmed"):  # the songs are compared; markers are written differently
                    if _songs(new) != _songs(p.setlist):
                        report.conflicts.append(f"{where}: Fandom's songs differ from the {c.status} list (not written): "
                                                + _diff(_songs(p.setlist), _songs(new)))
                    continue
                for u in unresolved:
                    open_items.append({"ref": f"concert:{c.id}", "date": p.date.isoformat(), "label": p.label, **u,
                                       "source": fandom.page_url(page)})
                key = f"setlist.{p.date}"
                if new != p.setlist or key not in c.evidence:
                    p.setlist = new
                    c.evidence[key] = m.Evidence(status=m.Status.draft, source=fandom.page_url(page), checked=today,
                                                 note=SETLIST_NOTE)
                    report.updated.append(f"{where}: {sum(x.type == 'song' for x in new)} songs"
                                          + (f", {len(unresolved)} unresolved" if unresolved else ""))
    _write_unresolved(review_dir, open_items)
    return report


UNRESOLVED_HOW = (
    "Fandom 세트리스트에서 데이터의 곡(Work)과 맞지 않은 항목. 레거시 출력 전(performed)이라 title_raw로 둔다(E9 경고). "
    "데이터에 있어야 할 곡이면 Work를 만들거나(공연 선공개 곡은 recordings: []) 표기 차이면 Work의 external_ids.fandom에 "
    "Fandom 제목을 적은 뒤 takasaki fandom concerts --apply를 다시 실행한다. 외부 곡(커버, BGM, 게임 코너)은 그대로 둔다. "
    "끝나면 decision: done."
)


def _write_unresolved(review_dir: Path, items: list[dict[str, Any]]) -> None:
    from .store import _to_node, _yaml

    path = review_dir / f"{REVIEW_PREFIX}-setlist-songs.yaml"
    old = YAML(typ="safe").load(path.read_text(encoding="utf-8")) if path.exists() else None
    doc = {"type": "setlist-songs", "decision": (old or {}).get("decision", ""), "how": UNRESOLVED_HOW, "items": items}
    if not items:
        if path.exists():
            path.unlink()
        return
    buf = io.StringIO()
    _yaml().dump(_to_node(doc), buf)
    review_dir.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text(encoding="utf-8") != buf.getvalue():
        path.write_text(buf.getvalue(), encoding="utf-8", newline="\n")


# --- schedules ----------------------------------------------------------------------

SERIES = [  # the series prefix of an official title: (ja, rom, ko)
    ("ラブライブ！サンシャイン!!", "Love Live! Sunshine!!", "러브 라이브! 선샤인!!"),
    ("ラブライブ！スーパースター!!", "Love Live! Superstar!!", "러브 라이브! 슈퍼스타!!"),
    ("ラブライブ！虹ヶ咲学園スクールアイドル同好会", "Love Live! Nijigasaki High School Idol Club", "러브 라이브! 니지가사키 학원 스쿨 아이돌 동호회"),
    ("ラブライブ！蓮ノ空女学院スクールアイドルクラブ", "Love Live! Hasunosora Girls' High School Idol Club",
     "러브 라이브! 하스노소라 여학원 스쿨 아이돌 클럽"),
    ("ラブライブ！シリーズ", "Love Live! Series", "러브 라이브! 시리즈"),
    ("ラブライブ！", "Love Live!", "러브 라이브!"),
]


def title_drafts(ja: str, fandom_en: str | None) -> tuple[str | None, str | None, str]:
    """rom and ko drafts of an official concert title: the series prefix in its fixed forms, the rest
    as printed when it is Latin (half-width, as the stored titles write it). A rest in Japanese has
    no ko yet; its rom is Fandom's."""
    rest, rom_p, ko_p = ja, "", ""
    for p_ja, p_rom, p_ko in SERIES:
        if ja.startswith(p_ja):
            rest, rom_p, ko_p = ja[len(p_ja):].strip(), p_rom + " ", p_ko + " "
            break
    if is_latin(halfwidth(rest).replace("～", "~")):
        tail = halfwidth(rest).replace("～", "~")
        return rom_p + tail, ko_p + tail, "rom·ko: 시리즈명 고정 표기 + 공식 라틴 표기"
    rom = halfwidth(fandom_en).replace("～", "~") if fandom_en else None
    return rom, None, "rom: Fandom 표기(확인 필요), ko: 일본어 부분 번역·음역 필요"


def _official(url: str | None) -> bool:
    return bool(url) and any(h in url for h in OFFICIAL)  # type: ignore[operator]


def import_schedule(ds: Dataset, entries: list[dict[str, Any]], review_dir: Path, today: dt.date) -> Report:
    """Create the concerts of a schedule file (status ``performed``), their venues and cities. New names
    go to the ``LIV-*`` review files with drafts filled in. Existing concerts only get their Fandom keys."""
    report = Report()
    reviews = NameReviews(review_dir, "concerts")
    venue_by_ja = {match_key(v.names.ja): v.id for v in ds.venues.values() if v.names.ja}
    for e in entries:
        if e.get("exclude"):
            report.skipped.append(f"{e['fandom']}: {e['exclude']}")
            continue
        if e.get("existing"):
            _link_existing(ds, ds.concerts[e["existing"]], e, report)
            continue
        cid = e["id"]
        if cid in ds.concerts:
            report.skipped.append(f"{cid}: already in the dataset")
            continue
        stops = []
        sources = {s.get("source") for s in e["stops"]}
        for n, s in enumerate(e["stops"], 1):
            city = _city(ds, s.get("city"), reviews, cid)
            venue = _venue(ds, s.get("venue"), city, reviews, venue_by_ja, s.get("source"), cid)
            perfs = []
            dates = [p["date"] for p in s["performances"]]
            for p in s["performances"]:
                key = "; ".join(f"{f.get('section') or ''}|{f.get('tab') or ''}" for f in p.get("fandom") or [])
                label = p.get("label") if dates.count(p["date"]) > 1 else None  # the date names a single show
                perfs.append(m.Performance(date=p["date"], label=label, external_ids={"fandom": key} if key else {}))
            stops.append(m.Stop(id=s.get("id") or f"{n}-{city or 'online'}", city=city, label=s.get("label"), venue=venue,
                                performances=perfs))
        rom, ko, how = title_drafts(e["title_ja"], e.get("title_en"))
        if e.get("title_rom") or e.get("title_ko"):  # drafts researched for the schedule
            rom, ko, how = e.get("title_rom") or rom, e.get("title_ko") or ko, e.get("title_note") or how
        title = m.Names(ja=e["title_ja"], rom=rom, ko=ko)
        c = m.Concert(id=cid, projects=e["projects"], status="performed", title=title, stops=stops,
                      external_ids={"fandom": e["fandom"]})
        file = f"{REVIEW_PREFIX}-concerts.yaml"
        it = reviews.item(file, "concert", e["title_ja"], {"title": title.model_dump(exclude_none=True),
                                                            "source": e.get("title_source") or ""}, cid)
        memo = " / ".join(x for x in [e.get("note")] + [f"{s.get('id')}: {s['note']}" for s in e["stops"] if s.get("note")] if x)
        it["note"] = it.get("note") or (f"{how}. 일정 조사 메모: {memo}" if memo else how)
        it["ref"] = f"concert:{cid}"
        c.evidence["title"] = m.Evidence(status=m.Status.draft, source=f"automation/review/{file}", note="승인 대기 (new-names 리뷰)")
        if len(sources) == 1:
            c.evidence["schedule"] = _schedule_ev(next(iter(sources)), e["stops"][0].get("note_ko"), today)
        else:
            for st, s in zip(stops, e["stops"]):
                c.evidence[f"schedule.{st.id}"] = _schedule_ev(s.get("source"), s.get("note_ko"), today)
        ds.concerts[cid] = c
        report.created.append(f"concert {cid}: {len(stops)} stops, {sum(len(s.performances) for s in stops)} shows")
    reviews.save()
    return report


def _schedule_ev(source: str | None, note: str | None, today: dt.date) -> m.Evidence:
    """The schedule's source; what the researchers noted goes to the concert's review item."""
    official = _official(source)
    return m.Evidence(status=m.Status.official if official else m.Status.established, source=source, checked=today,
                      note=note if official else f"공식 미게재{': ' + note if note else ''}")


def _city(ds: Dataset, city: dict[str, Any] | None, reviews: NameReviews, cid: str) -> str | None:
    if not city or not city.get("id"):
        return None
    ident = city["id"]
    if ident not in ds.cities:
        names = m.Names(ja=city.get("ja"), rom=city.get("rom"), ko=city.get("ko"))
        ds.cities[ident] = m.City(id=ident, names=names, evidence={
            "names": m.Evidence(status=m.Status.draft, source=f"automation/review/{REVIEW_PREFIX}-venues.yaml",
                                note="승인 대기 (new-names 리뷰)")})
        it = reviews.item(f"{REVIEW_PREFIX}-venues.yaml", "city", city.get("rom") or ident,
                          {"names": names.model_dump(exclude_none=True)}, cid)
        it["ref"] = f"city:{ident}"
    else:
        reviews.note_use(f"{REVIEW_PREFIX}-venues.yaml", "city", ds.cities[ident].names.rom or ident, cid)
    return ident


def _venue(ds: Dataset, v: dict[str, Any] | None, city: str | None, reviews: NameReviews, by_ja: dict[str, str],
           source: str | None, cid: str) -> str | None:
    if not v or v.get("online") or not v.get("ja"):
        return None
    file = f"{REVIEW_PREFIX}-venues.yaml"
    if (vid := by_ja.get(match_key(v["ja"]))) is not None:
        reviews.note_use(file, "venue", v["ja"], cid)
        return vid
    vid = slugify(v.get("rom") or v["ja"])
    while vid in ds.venues:
        vid += "-2"
    names = m.Names(ja=v["ja"], rom=v.get("rom"), ko=v.get("ko"))
    ds.venues[vid] = m.Venue(id=vid, city=city, names=names,
                             external_ids={"fandom": v["en_fandom"]} if v.get("en_fandom") else {},
                             evidence={"names": m.Evidence(status=m.Status.draft, source=f"automation/review/{file}",
                                                           note="승인 대기 (new-names 리뷰)")})
    by_ja[match_key(v["ja"])] = vid
    it = reviews.item(file, "venue", v["ja"], {"names": names.model_dump(exclude_none=True), "source": source or ""}, cid)
    it["note"] = it.get("note") or "ja: 공식 표기(공연 당시), rom·ko: 초안" + (f". {v['note']}" if v.get("note") else "")
    it["ref"] = f"venue:{vid}"
    return vid


def _link_existing(ds: Dataset, c: m.Concert, e: dict[str, Any], report: Report) -> None:
    """An existing concert's tabs, in page order, are its shows in date order (checked by count)."""
    c.external_ids["fandom"] = e["fandom"]
    tabs = [f"{s['section'] or ''}|{t['tab']}" for s in e.get("sections", []) for t in s["tabs"]]
    perfs = [p for s in c.stops for p in s.performances]
    if len(tabs) != len(perfs):
        report.conflicts.append(f"{c.id}: {len(tabs)} Fandom tabs for {len(perfs)} shows; map them by hand")
        return
    for p, k in zip(perfs, tabs):
        p.external_ids["fandom"] = k
    report.updated.append(f"{c.id}: Fandom tabs linked")
