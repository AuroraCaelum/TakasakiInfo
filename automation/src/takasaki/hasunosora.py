"""蓮ノ空女学院スクールアイドルクラブ official site adapter (DESIGN.md §6.1, §7.2 ③).

The music pages come in two generations with one layout: ``/hasunosora/music/NN/`` (2023–2025, no
longer listed but still served) and ``/hasunosora/music/<cd|str>/?p=01_NNNN`` (listed). Each edition
of a CD has its own page (``【…盤】``); pages with the same date and title are one release. The
page text is read line by line, since the markup of the track lists differs from page to page; an
unknown line inside a track raises instead of being guessed (§7.2 ③).

Characters and their casting are already in ``data/`` and the unit lineups are dated by school year
(D33), so the member pages are not read and the lineups are left alone.
"""

from __future__ import annotations

import datetime as dt
import html as htmllib
import re
import unicodedata
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path

from .importer import (EditionObs, ParseError, Performers, ReleaseObs, Report, Site, Spec, TrackObs, is_credit_line,
                       page_id, parse_credit_line)
from .importer import import_site as _import_site
from .official import BASE, Fetcher
from .store import Dataset
from .text import match_key

GROUP = "蓮ノ空女学院スクールアイドルクラブ"
OLD_PAGE = "/hasunosora/music/{:02d}/"
LISTS = ("/hasunosora/music/cd/", "/hasunosora/music/str/")
MEMBER_PATH = "/hasunosora/member/"

SPEC = Spec(project="hasunosora", group_name=GROUP, legacy_group="Hasunosora", review_prefix="HSN",
            skip={"01_5904": "AiScReam「NEXT CARD」: cross-project unit (Phase 3)",
                  "22": "「Bring the LOVE！」: LoveLive! Series Asia Tour theme song, cross-project (Phase 3)"},
            lineups_from_site=False)

# misprints on the official pages, corrected with the source that settles them: (page id, track as printed) -> track
TRACK_FIXES = {
    # NDL deposit record R100000002-I033990581 lists track 4 as Retrofuture(Off Vocal)
    ("36", "Retrofutur（Off Vocal）"): "Retrofuture（Off Vocal）",
}

_LABELS ={"アーティスト", "発売日", "品番", "価格", "仕様", "CD", "収録楽曲", "収録内容", "Blu-ray", "DVD"}
_TRACK = re.compile(r"^(\d{1,2})[.．]\s*(.+)$")
_DISC = re.compile(r"^\[Disc\.?\s*(\d+)\]$")
_CATALOG = re.compile(r"[A-Z]{2,5}-\d{3,6}(?:[～~]\d+)?")
_MEMBER = re.compile(r"([^、,，()（）［］\[\]]+?)\s*\(CV\.\s*([^)]+)\)")
_EDITION = re.compile(r"^(.*?)\s*【([^【】]*盤)】$")


def _text(fragment: str) -> str:
    return " ".join(htmllib.unescape(re.sub(r"<[^>]+>", "", fragment)).split())


def _lines(fragment: str) -> list[str]:
    text = re.sub(r"<br\s*/?>|</p>|</div>|</h\d>", "\n", fragment)
    text = htmllib.unescape(re.sub(r"<[^>]+>", "", text))
    return [" ".join(line.split()) for line in text.split("\n") if line.strip()]


def _unquote(s: str) -> str:
    while (mt := re.fullmatch(r"[「『](.*)[」』]", s)) and "」「" not in mt.group(1):
        s = mt.group(1)
    return s


def _date(s: str) -> dt.date:
    mt = re.search(r"(\d{4})[年.](\d{1,2})[月.](\d{1,2})", s)
    if not mt:
        raise ParseError(f"no date in {s!r}")
    return dt.date(int(mt.group(1)), int(mt.group(2)), int(mt.group(3)))


def parse_artists(lines: list[str]) -> Performers:
    """Blocks joined by ``＆``: an artist name with its members (``［…］`` on the same or the next
    line, or a plain list), or characters only (``乙宗 梢(CV.花宮初奈)``)."""
    blocks: list[list[str]] = [[]]
    for ln in map(_cv, lines):
        if ln in ("＆", "&"):
            blocks.append([])
        else:
            blocks[-1].append(ln)
    names, members = [], []
    for block in (b for b in blocks if b):
        head = block[0]
        bracket = re.match(r"^([^［\[(（]+?)\s*[［\[]", head)
        if bracket:  # "スリーズブーケ［日野下花帆(CV.楡井希実)、…］"
            names.append(bracket.group(1).strip())
            rest = " ".join(block)
        elif "(CV." in head:  # characters only
            rest = " ".join(block)
        else:
            names.append(head.strip())
            rest = " ".join(block[1:])
        members += [(a.strip(), b.strip()) for a, b in _MEMBER.findall(rest)]
    if not names and not members:
        raise ParseError(f"no performers in {lines!r}")
    if len(names) > 1:
        return Performers(None, None, members, names)
    return Performers(names[0] if names else None, None, members)


def parse_singers(text: str) -> Performers:
    """``歌：`` of a track: characters (``乙宗 梢(CV.花宮初奈)``) or artists joined by a full-width
    ``＆`` (a half-width ``&`` belongs to a name: ``Ruri&To``)."""
    text = _cv(text)
    if "(CV." in text:
        members = [(a.strip(), b.strip()) for a, b in _MEMBER.findall(text)]
        if not members:
            raise ParseError(f"no singers in {text!r}")
        return Performers(None, None, members)
    names = [n.strip() for n in re.split(r"\s*＆\s*", text) if n.strip()]
    return Performers(names[0], None) if len(names) == 1 else Performers(None, None, [], names)


def _cv(text: str) -> str:
    """``村野さやか（CV. 野中ここな）`` → ``村野さやか(CV.野中ここな)``."""
    return re.sub(r"[（(]\s*CV[.．]\s*([^)）]+?)\s*[)）]", r"(CV.\1)", text)


@dataclass
class PageObs:
    """One page as read, before the editions of a release are put together."""

    url: str
    lead: str  # "スリーズブーケ 6thシングル"
    title: str  # without the edition and the quotes
    edition: str | None  # "初回限定盤"
    category: str  # "CD", "配信", "Blu-ray"
    release_date: dt.date
    performers: Performers | None = None
    catalog: str | None = None
    media: str | None = None
    tracks: list[TrackObs] = field(default_factory=list)
    smartlink: str | None = None
    note: str | None = None
    skip: str | None = None  # why the page is left out


def _skip_reason(lead: str, title: str, category: str, artist: list[str]) -> str | None:
    joined = " ".join(artist)
    if category not in ("CD", "配信") or "Blu-ray" in lead + title:
        return f"{category}: a video release, not a music release"
    if joined.strip() == "V.A.":
        return "V.A.: other franchises' artists (tribute album)"
    if joined.startswith("音楽："):
        return "soundtrack (score), not in the legacy files"
    if title == "タイトル未定":
        return "announced without a title or tracklist yet"
    return None


def parse_page(html: str, url: str) -> PageObs:
    head = re.search(r'<span class="head--title__lead">(.*?)</span>\s*<span class="head--title__main">(.*?)</span>', html, re.S)
    cat = re.search(r'<p class="head--category">(.*?)</p>', html, re.S)
    start = html.find('class="detail__content"')
    if not head or not cat or start < 0:
        raise ParseError(f"{url}: unexpected page structure")
    lead, main, category = _text(head.group(1)), _text(head.group(2)), _text(cat.group(1))
    em = _EDITION.match(main)
    edition, main = (em.group(2), em.group(1)) if em else (None, main)
    series = re.fullmatch(r"(『[^』]+』)\s*(「.+」)", main)  # "『映画 …』「A / B」" on a streaming page
    if series:
        lead, main = (lead + " " + series.group(1)).strip(), series.group(2)
    title = _unquote(main.strip())
    lines = _lines(html[html.find(">", start) + 1:])
    if "BACK" in lines:
        lines = lines[:lines.index("BACK")]
    section, artist, dates, catalogs = None, [], [], []
    tracks: list[TrackObs] = []
    errors: list[str] = []  # raised only for a page that is read (a skipped page may differ)
    disc, bd, disc_opened = 1, False, False
    for ln in lines:
        if ln in _LABELS:
            section = ln
            bd = bd or ln in ("Blu-ray", "DVD")
            continue
        if ln.startswith("●"):
            section = "other"
            continue
        after_disc, disc_opened = disc_opened, False
        if section == "アーティスト":
            artist.append(ln)
        elif section == "発売日":
            dates.append(ln)
        elif section in ("Blu-ray", "DVD", "other") or section is None:
            continue
        elif dm := _DISC.match(ln):
            disc, disc_opened = int(dm.group(1)), True
        elif tm := _TRACK.match(ln):
            printed = tm.group(2).strip()
            tracks.append(TrackObs(int(tm.group(1)), TRACK_FIXES.get((page_id(url), printed), printed), disc=disc))
        elif after_disc and not ln.startswith("歌：") and not is_credit_line(ln):
            tracks.append(TrackObs(1, ln, disc=disc))  # the first track of a disc printed without its number (01_6068)
        elif section in ("品番", "価格") and not tracks:
            catalogs.append(ln)
        elif not tracks or ln.startswith(("※", "・", "NOW PRINTING")) or (section == "仕様" and not tracks):
            continue
        else:
            try:
                if ln.startswith("歌："):
                    tracks[-1].performers = parse_singers(ln.removeprefix("歌：").strip())
                elif re.match(r"^[［\[].*\(CV\.", ln) and tracks[-1].performers:  # the members of the artist above
                    tracks[-1].performers.members += [(a.strip(), b.strip()) for a, b in _MEMBER.findall(ln)]
                elif is_credit_line(ln):
                    tracks[-1].credits.update(parse_credit_line(ln))
                else:
                    raise ParseError(f"unexpected line {ln!r}")
            except ParseError as e:
                errors.append(f"{url}: track {tracks[-1].no} {tracks[-1].title!r}: {e}")
    if not dates:
        raise ParseError(f"{url}: no release date")
    page = PageObs(url, lead, title, edition, category, _date(dates[0]))
    page.note = next((d.removeprefix("※").strip() for d in dates[1:] if d.startswith("※")), None)
    page.skip = _skip_reason(lead, title, category, artist) or (None if tracks else "no tracklist yet")
    if page.skip:
        return page
    if errors:
        raise ParseError("; ".join(errors))
    page.performers = parse_artists(artist)
    page.tracks = tracks
    cm = next((_CATALOG.search(c) for c in catalogs if _CATALOG.search(c)), None)
    page.catalog = unicodedata.normalize("NFKC", cm.group(0)) if cm else None
    n_discs = max(t.disc for t in tracks)
    page.media = "配信" if category == "配信" else ((f"{n_discs}CD" if n_discs > 1 else "CD") + ("+BD" if bd else ""))
    sm = re.search(r'href="(https://lnk\.to/[^"]+)"', html)
    page.smartlink = sm.group(1) if sm else None
    return page


def _type(lead: str, title: str, category: str) -> str:
    s = f"{lead} {title}"
    if category == "配信":
        return "album" if re.search(r"Collection|アルバム|Album", s) else "digital_single"
    if "ミニアルバム" in s:
        return "mini_album"
    if re.search(r"アルバム|Album", s):
        return "album"
    return "single" if "シングル" in s else "unclassified"


def _key(t: TrackObs) -> tuple[int, int, str]:
    return (t.disc, t.no, t.title)


def group_pages(pages: list[PageObs]) -> tuple[list[ReleaseObs], list[str]]:
    """Pages with the same date, lead and title are the editions of one release."""
    groups: dict[tuple[dt.date, str], list[PageObs]] = {}
    for p in pages:
        groups.setdefault((p.release_date, match_key(p.title)), []).append(p)
    out, notes = [], []
    for (date, _), ps in groups.items():
        ps.sort(key=lambda p: (p.edition != "初回限定盤", p.url))
        first = ps[0]
        lead, title = first.lead, first.title
        for p in ps[1:]:
            if [_key(t) for t in p.tracks] != [_key(t) for t in first.tracks]:
                notes.append(f"{page_id(p.url)} {title}【{p.edition}】: its tracks differ from {page_id(first.url)}; only the first edition is read")
        assert first.performers is not None
        smart = next((p.smartlink for p in ps if p.smartlink), None)
        out.append(ReleaseObs(first.url, lead, title, date, first.performers,
                              [EditionObs(p.edition, p.catalog, p.media) for p in ps], first.tracks,
                              {"smartlink": smart} if smart else {}, first.note, _type(lead, title, first.category),
                              [p.url for p in ps]))
    out.sort(key=lambda r: (r.release_date, r.url))
    return out, notes


def _list_urls(html: str, path: str) -> list[str]:
    return [BASE + path + "?p=" + p for p in dict.fromkeys(re.findall(r'href="\./\?p=(01_\d+)"', html))]


def collect(fetcher: Fetcher, *, fresh: bool = False) -> Site:
    urls: list[str] = []
    for path in LISTS:
        urls += _list_urls(fetcher.get(path, fresh=fresh).html, path)
    n, misses = 1, 0
    # the old numbered pages are no longer listed; read them until three are missing. A missing
    # number answers 200 with the site's top page, so a page without a release heading is missing
    while misses < 3:
        try:
            if "head--title__main" in fetcher.get(OLD_PAGE.format(n), fresh=fresh).html:
                urls.append(BASE + OLD_PAGE.format(n))
                misses = 0
            else:
                misses += 1
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            misses += 1
        except FileNotFoundError:  # offline: not cached
            misses += 1
        n += 1
    pages, seen, skipped = [], set(), []
    for url in urls:
        if page_id(url) in SPEC.skip:
            continue
        p = parse_page(fetcher.get(url, fresh=fresh).html, url)
        key = (p.release_date, match_key(p.title), p.edition)
        if key in seen:  # an old page that is also listed under its new address
            continue
        seen.add(key)
        if p.skip:
            skipped.append(f"{page_id(url)} {p.lead} {p.title}: {p.skip}")
        else:
            pages.append(p)
    releases, notes = group_pages(pages)
    return Site([], releases, BASE + MEMBER_PATH, skipped + notes)


def import_site(ds: Dataset, site: Site, review_dir: Path, today: dt.date) -> Report:
    return _import_site(ds, site, review_dir, today, SPEC)
