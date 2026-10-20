"""虹ヶ咲学園スクールアイドル同好会 official site adapter (DESIGN.md §6.1, §7.2 ③, D41).

Every CD is a block on one page (``/nijigasaki/cd.php``), each with an anchor (``#cd02``, ``#01_5258``);
the reader is ``sitepage``. Releases migrated from the legacy files are checked against their blocks
and completed (type, label, editions, artist); the others are imported (Phase 3).
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from .importer import Report, Site, Spec
from .importer import import_site as _import_site
from .official import BASE, Fetcher
from .sitepage import expand_in_elements, read_block, releases_of, text_lines
from .store import Dataset

GROUP = "虹ヶ咲学園スクールアイドル同好会"
PAGES = ("/nijigasaki/cd.php",)
MEMBER_PATH = "/nijigasaki/member/"

SPEC = Spec(project="nijigasaki", group_name=GROUP, legacy_group="Nijigasaki", legacy_file="Nijigaku",
            review_prefix="NJG",
            skip={"cd.php#cd68": "「珊瑚礁の記憶」: the film's soundtrack and vocal collection, a soundtrack (score)",
                  "cd.php#cd01_5904": "AiScReam「NEXT CARD」: cross-project, imported with the Liella! page (D45)"},
            cross={"cd.php#cd61": ["nijigasaki", "aqours", "liella", "hasunosora", "muse"],  # Bring the LOVE！ (D45)
                   "cd.php#cd81": ["nijigasaki", "aqours", "liella"]},  # AiScReam「愛♡スクリ～ム！」 (its first lineup)
            lineups_from_site=False)
# drama tracks the page does not mark: (page id, track number)
DRAMA = {("cd.php#cd81", 2)}  # あまくてたのしい♡AiScReamラジオ！ ("※録り下ろしドラマはCD限定収録")
# misprints on the page, corrected with the source that settles them: (page id, track number) -> track
TRACK_FIXES = {
    # 「モノクロラビリンス」 prints track 4 as Jungle Hunter♡; the label's YouTube Music album and the layout
    # (3 is モノクロラビリンス(Off Vocal)) make it the Off Vocal
    ("cd.php#cd01_6286", 4): "Jungle Hunter♡(Off Vocal)",
}

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
        html = expand_in_elements(fetcher.get(path, fresh=fresh).html, BASE + path, fetcher, '<div class="box" id="{}">')
        blocks += parse_page(html, BASE + path)
    releases, skipped = releases_of(blocks, SPEC.skip)
    for r in releases:
        for t in r.tracks:
            t.drama = t.drama or (r.page_id, t.no) in DRAMA
            t.title = TRACK_FIXES.get((r.page_id, t.no), t.title)
    return Site([], releases, BASE + MEMBER_PATH, skipped)


def import_site(ds: Dataset, site: Site, review_dir: Path, today: dt.date) -> Report:
    return _import_site(ds, site, review_dir, today, SPEC)
