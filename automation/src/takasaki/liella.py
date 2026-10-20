"""Liella! (ラブライブ！スーパースター!!) official site adapter (DESIGN.md §6.1, §7.2 ③, D41).

Each CD edition has its own page, listed on ``/yuigaoka/music/``: ``cdNN.php`` (2021–2024) and
``detail.php?p=01_NNNN`` (later). A page is one block in the layout of the Nijigasaki site; the
reader is ``sitepage``. Releases migrated from the legacy files are checked against their pages and
completed (type, label, editions, artist); the others are imported (Phase 3).
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

GROUP = "Liella!"
LIST_PATH = "/yuigaoka/music/"
MEMBER_PATH = "/yuigaoka/member/"

SPEC = Spec(project="liella", group_name=GROUP, legacy_group="Liella", review_prefix="LLA",
            skip={"cd13.php": "LIVE with a smile!: stored with the Nijigasaki page, which lists the three groups",
                  "cd37.php": "「Bring the LOVE！」: cross-project, imported with the Nijigasaki page (D45)",
                  "cd47.php": "AiScReam「愛♡スクリ～ム！」: cross-project, imported with the Nijigasaki page (D45)"},
            cross={"01_5904": ["liella", "nijigasaki", "hasunosora", "ikizulive"]},  # AiScReam「NEXT CARD」 (D45)
            lineups_from_site=False)

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
    releases, skipped = releases_of(blocks, SPEC.skip)
    return Site([], releases, BASE + MEMBER_PATH, skipped)


def import_site(ds: Dataset, site: Site, review_dir: Path, today: dt.date) -> Report:
    return _import_site(ds, site, review_dir, today, SPEC)
