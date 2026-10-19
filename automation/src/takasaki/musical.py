"""スクールアイドルミュージカル official site adapter (DESIGN.md §6.1, §7.2 ③, D41).

Each year's site (``/musical/2022/``, ``/musical/2023/``) has a music page listing the same CDs as
blocks in the layout of the Nijigasaki site; the reader is ``sitepage``. The singers are the cast,
printed as ``堀内まり菜（椿 ルリカ役）`` with the ensemble after them (D29). Only the releases already in
``data/`` are checked (``check_only``).
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
from .text import match_key

GROUP = "スクールアイドルミュージカル"
PAGES = ("/musical/2023/music.php", "/musical/2022/music.php")  # the newer site first
MEMBER_PATH = "/musical/2023/member.php"

SPEC = Spec(project="musical", group_name=GROUP, legacy_group="Musical", review_prefix="MSC",
            lineups_from_site=False, check_only=True)

_BOX = re.compile(r'<div class="box" id="([^"]+)">')


def parse_page(html: str, url: str) -> list:
    starts = [(mt.start(), mt.group(1)) for mt in _BOX.finditer(html)]
    blocks = []
    for i, (pos, anchor) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(html)
        part = html[pos:end]
        b = read_block(text_lines(part), f"{url}#{anchor}", part, cast=True)
        if b.release_date and b.tracks:
            blocks.append(b)
    return blocks


def collect(fetcher: Fetcher, *, fresh: bool = False) -> Site:
    blocks, seen = [], set()
    for path in PAGES:  # the years' sites list the same CDs: each is read once
        for b in parse_page(fetcher.get(path, fresh=fresh).html, BASE + path):
            key = (b.release_date, match_key(b.title), b.edition)
            if key not in seen:
                seen.add(key)
                blocks.append(b)
    releases = [to_release(g, performers_of(g[0])) for g in group_blocks(blocks)]
    releases.sort(key=lambda r: (r.release_date, r.url))
    return Site([], releases, BASE + MEMBER_PATH, [f"{b.url} {p}" for b in blocks for p in b.problems])


def import_site(ds: Dataset, site: Site, review_dir: Path, today: dt.date) -> Report:
    return _import_site(ds, site, review_dir, today, SPEC)
