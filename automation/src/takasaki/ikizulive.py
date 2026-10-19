"""イキヅライブ！ official site adapter (DESIGN.md §6.1, §7.2 ③, §13).

The parser turns pages into lines of text and reads them by section. It keeps the strings exactly as
printed and raises when a page does not have the expected structure instead of returning nothing
(§7.2 ③). The importer (``importer.py``) resolves what was read against ``data/``.
"""

from __future__ import annotations

import datetime as dt
import html as htmllib
import re
from pathlib import Path

from .importer import (CreditName, EditionObs, MemberObs, ParseError, Performers, ReleaseObs, Report, Site, Spec,
                       TrackObs, _media, is_credit_line, parse_credit_line)
from .importer import import_site as _import_site
from .official import BASE, Fetcher
from .store import Dataset

__all__ = ["CreditName", "EditionObs", "MemberObs", "ParseError", "Performers", "ReleaseObs", "Report", "SPEC", "Site",
           "TrackObs", "_media", "collect", "import_site", "parse_credit_line", "parse_detail", "parse_members",
           "parse_performers"]

LIST_PATH = "/lovehigh/music/"
MEMBER_PATH = "/lovehigh/member/"
_DETAIL = re.compile(r'href="(https://www\.lovelive-anime\.jp/lovehigh/music/detail\.php\?p=[^"]+)"')


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


# --- performers ---------------------------------------------------------------------

_MEMBER = re.compile(r"\s*([^,，()（）]+?)\s*\(CV\.\s*([^)]+)\)")
_FROM = re.compile(r"\s+from\s+(\S+)\s*$")


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

# releases left to a later phase; the reason is printed on every run
SPEC = Spec(project="ikizulive", group_name="いきづらい部！", legacy_group="Ikizulive",  # D3
            review_prefix="IKZ", skip={"01_5904": "AiScReam「NEXT CARD」: cross-project, imported with the Liella! page (D45)"})


def collect(fetcher: Fetcher, *, fresh: bool = False) -> Site:
    first = fetcher.get(LIST_PATH, fresh=fresh)
    urls = list_detail_urls(first.html)
    for page in range(2, list_page_count(first.html) + 1):
        urls += list_detail_urls(fetcher.get(f"{LIST_PATH}?page={page}", fresh=fresh).html)
    rels = [parse_detail(fetcher.get(u, fresh=fresh).html, u) for u in dict.fromkeys(urls)
            if u.rsplit("=", 1)[-1] not in SPEC.skip]
    rels.reverse()  # the list is newest first
    rels.sort(key=lambda r: r.release_date)
    members = parse_members(fetcher.get(MEMBER_PATH, fresh=fresh).html)
    return Site(members, rels, BASE + MEMBER_PATH)


def import_site(ds: Dataset, site: Site, review_dir: Path, today: dt.date) -> Report:
    return _import_site(ds, site, review_dir, today, SPEC)
