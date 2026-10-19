"""虹ヶ咲学園スクールアイドル同好会 official site adapter (DESIGN.md §6.1, §7.2 ③, D41).

Every CD is a block on one page (``/nijigasaki/cd.php``), each with an anchor (``#cd02``, ``#01_5258``);
the reader is ``sitepage``. Only the releases already in ``data/`` are checked (``check_only``).
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

GROUP = "虹ヶ咲学園スクールアイドル同好会"
PAGES = ("/nijigasaki/cd.php",)
MEMBER_PATH = "/nijigasaki/member/"

SPEC = Spec(project="nijigasaki", group_name=GROUP, legacy_group="Nijigasaki", review_prefix="NJG",
            lineups_from_site=False, check_only=True)

_BOX = re.compile(r'<div class="box" id="([^"]+)">')


def parse_page(html: str, url: str) -> list:
    starts = [(mt.start(), mt.group(1)) for mt in _BOX.finditer(html)]
    blocks = []
    for i, (pos, anchor) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else html.find("<!-- ! END", pos)
        part = html[pos:end if end > pos else None]
        lines = [ln for ln in text_lines(part) if ln != "▲"]
        b = read_block(lines, f"{url}#{anchor}", part)
        if b.release_date and b.tracks:
            blocks.append(b)
    return blocks


def collect(fetcher: Fetcher, *, fresh: bool = False) -> Site:
    blocks = []
    for path in PAGES:
        blocks += parse_page(fetcher.get(path, fresh=fresh).html, BASE + path)
    releases = [to_release(g, performers_of(g[0])) for g in group_blocks(blocks)]
    releases.sort(key=lambda r: (r.release_date, r.url))
    return Site([], releases, BASE + MEMBER_PATH, [f"{b.url} {p}" for b in blocks for p in b.problems])


def import_site(ds: Dataset, site: Site, review_dir: Path, today: dt.date) -> Report:
    return _import_site(ds, site, review_dir, today, SPEC)
