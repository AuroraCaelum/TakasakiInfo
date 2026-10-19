"""スクールアイドルミュージカル official site adapter (DESIGN.md §6.1, §7.2 ③, D41).

Each year's site (``/musical/2022/``, ``/musical/2023/``) has a music page listing the same CDs as
blocks in the layout of the Nijigasaki site; the reader is ``sitepage``. The singers are the cast,
printed as ``堀内まり菜（椿 ルリカ役）`` with the ensemble after them (D29). Releases migrated from the
legacy files are checked against their blocks and completed; the others are imported (Phase 3).
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from .importer import Report, Site, Spec
from .importer import import_site as _import_site
from .official import BASE, Fetcher
from .sitepage import read_block, releases_of, text_lines
from .store import Dataset
from .text import match_key

GROUP = "スクールアイドルミュージカル"
PAGES = ("/musical/2023/music.php", "/musical/2022/music.php")  # the newer site first
MEMBER_PATH = "/musical/2023/member.php"

SPEC = Spec(project="musical", group_name=GROUP, legacy_group="Musical", review_prefix="MSC",
            lineups_from_site=False, group_artist=False)

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
    releases, skipped = releases_of(blocks, SPEC.skip)
    return Site([], releases, BASE + MEMBER_PATH, skipped)


def import_site(ds: Dataset, site: Site, review_dir: Path, today: dt.date) -> Report:
    return _import_site(ds, site, review_dir, today, SPEC)
