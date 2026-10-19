"""Aqours (ラブライブ！サンシャイン!!) official site adapter (DESIGN.md §6.1, §7.2 ③, D41).

Every CD since the first single (2015) is a block on ``/uranohoshi/cd.php``, each after an anchor
(``<a id="cd51">``); the reader is ``sitepage``. Only the releases already in ``data/`` are checked
(``check_only``).
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from .importer import Report, Site, Spec
from .importer import import_site as _import_site
from .official import BASE, Fetcher
from .sitepage import Block, group_blocks, performers_of, read_block, text_lines, to_release
from .store import Dataset

GROUP = "Aqours"
PAGE = "/uranohoshi/cd.php"
MEMBER_PATH = "/uranohoshi/member/"

SPEC = Spec(project="aqours", group_name=GROUP, legacy_group="Aqours", review_prefix="AQR",
            lineups_from_site=False, check_only=True)

_ANCHOR = re.compile(r'<a id="(cd\d+)"></a>')


def parse_page(html: str, url: str) -> list[Block]:
    starts = [(mt.start(), mt.group(1)) for mt in _ANCHOR.finditer(html)]
    blocks = []
    for i, (pos, anchor) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(html)
        part = html[pos:end]
        b = read_block(text_lines(part), f"{url}#{anchor}", part)
        if b.release_date and b.tracks:
            blocks.append(b)
    return blocks


def collect(fetcher: Fetcher, *, fresh: bool = False) -> Site:
    blocks = parse_page(fetcher.get(PAGE, fresh=fresh).html, BASE + PAGE)
    releases = [to_release(g, performers_of(g[0])) for g in group_blocks(blocks)]
    releases.sort(key=lambda r: (r.release_date, r.url))
    return Site([], releases, BASE + MEMBER_PATH, [f"{b.url} {p}" for b in blocks for p in b.problems])


def import_site(ds: Dataset, site: Site, review_dir: Path, today: dt.date) -> Report:
    return _import_site(ds, site, review_dir, today, SPEC)
