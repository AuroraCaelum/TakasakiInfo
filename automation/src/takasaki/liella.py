"""Liella! (ラブライブ！スーパースター!!) official site adapter (DESIGN.md §6.1, §7.2 ③, D41).

Each CD edition has its own page, listed on ``/yuigaoka/music/``: ``cdNN.php`` (2021–2024) and
``detail.php?p=01_NNNN`` (later). A page is one block in the layout of the Nijigasaki site; the
reader is ``sitepage``. Only the releases already in ``data/`` are checked (``check_only``).
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from .importer import Report, Site, Spec
from .importer import import_site as _import_site
from .official import BASE, Fetcher
from .sitepage import group_blocks, performers_of, read_block, text_lines, to_release
from .store import Dataset

GROUP = "Liella!"
LIST_PATH = "/yuigaoka/music/"
MEMBER_PATH = "/yuigaoka/member/"

SPEC = Spec(project="liella", group_name=GROUP, legacy_group="Liella", review_prefix="LLA",
            lineups_from_site=False, check_only=True)

_PAGE = re.compile(r'href="((?:cd\d+\.php)|(?:detail\.php\?p=01_\d+))"')
_BOX = re.compile(r'<div class="box" id="([^"]+)">')


def parse_page(html: str, url: str):
    mt = _BOX.search(html)
    if not mt:
        return None
    end = html.find("</article>", mt.start())
    part = html[mt.start():end if end > 0 else None]
    b = read_block(text_lines(part), url, part)
    return b if b.release_date and b.tracks else None


def collect(fetcher: Fetcher, *, fresh: bool = False) -> Site:
    listing = fetcher.get(LIST_PATH, fresh=fresh).html
    blocks = []
    for path in dict.fromkeys(_PAGE.findall(listing)):
        url = BASE + LIST_PATH + path
        b = parse_page(fetcher.get(url, fresh=fresh).html, url)
        if b is not None:
            blocks.append(b)
    releases = [to_release(g, performers_of(g[0])) for g in group_blocks(blocks)]
    releases.sort(key=lambda r: (r.release_date, r.url))
    return Site([], releases, BASE + MEMBER_PATH, [f"{b.url} {p}" for b in blocks for p in b.problems])


def import_site(ds: Dataset, site: Site, review_dir: Path, today: dt.date) -> Report:
    return _import_site(ds, site, review_dir, today, SPEC)
