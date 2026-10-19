"""Aqours (ラブライブ！サンシャイン!!) official site adapter (DESIGN.md §6.1, §7.2 ③, D41).

Every CD since the first single (2015) is a block on ``/uranohoshi/cd.php``, each after an anchor
(``<a id="cd51">``); the reader is ``sitepage``. Releases migrated from the legacy files are checked
against their blocks and completed (type, label, editions, artist); the others are imported (Phase 3).
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from .importer import Report, Site, Spec
from .importer import import_site as _import_site
from .official import BASE, Fetcher
from .sitepage import Block, read_block, releases_of, text_lines
from .store import Dataset

GROUP = "Aqours"
PAGE = "/uranohoshi/cd.php"
MEMBER_PATH = "/uranohoshi/member/"

SPEC = Spec(project="aqours", group_name=GROUP, legacy_group="Aqours", review_prefix="AQR",
            skip={"cd.php#cd68": "LIVE with a smile!: Aqours, Nijigasaki and Liella!, cross-project (Phase 3)",
                  "cd.php#cd69": "not ALONE not HITORI / ミラクル STAY TUNE！ / Shooting Voice!!: split single of three groups, "
                                 "cross-project (Phase 3)",
                  "cd.php#cd100": "「Bring the LOVE！」: LoveLive! Series Asia Tour theme song, cross-project (Phase 3)",
                  "cd.php#cd101": "AiScReam「愛♡スクリ～ム！」: cross-project unit (Phase 3)"},
            lineups_from_site=False)

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
    releases, skipped = releases_of(blocks, SPEC.skip)
    return Site([], releases, BASE + MEMBER_PATH, skipped)


def import_site(ds: Dataset, site: Site, review_dir: Path, today: dt.date) -> Report:
    return _import_site(ds, site, review_dir, today, SPEC)
