"""Aqours (ラブライブ！サンシャイン!!) official site adapter (DESIGN.md §6.1, §7.2 ③, D41).

Every CD since the first single (2015) is a block on ``/uranohoshi/cd.php``, each after an anchor
(``<a id="cd51">``); the reader is ``sitepage``. Releases migrated from the legacy files are checked
against their blocks and completed (type, label, editions, artist); the others are imported (Phase 3).
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from .importer import Report, Site, Spec, TrackObs, page_id, parse_credit_line
from .importer import import_site as _import_site
from .official import BASE, Fetcher
from .sitepage import Block, expand_in_elements, read_block, releases_of, text_lines
from .store import Dataset

GROUP = "Aqours"
PAGE = "/uranohoshi/cd.php"
MEMBER_PATH = "/uranohoshi/member/"

SPEC = Spec(project="aqours", group_name=GROUP, legacy_group="Aqours", review_prefix="AQR",
            skip={"cd.php#cd68": "LIVE with a smile!: stored with the Nijigasaki page, which lists the three groups",
                  "cd.php#cd100": "「Bring the LOVE！」: cross-project, imported with the Nijigasaki page (D45)",
                  "cd.php#cd101": "AiScReam「愛♡スクリ～ム！」: cross-project, imported with the Nijigasaki page (D45)"},
            lineups_from_site=False)

# misprinted credit lines, corrected with the source that settles them: (page id, line as printed) -> line
LINE_FIXES = {
    # the Guilty Kiss album prints 「Love Pulsar」 as 作曲：編曲：渡辺未来; its single (cd35) prints 作曲・編曲
    ("cd.php#cd56", "作詞：畑 亜貴 作曲：編曲：渡辺未来"): "作詞：畑 亜貴 作曲・編曲：渡辺未来",
    # the 2nd season's soundtrack repeats the 1st one's 「輝きを目指して」 (cd12 #1-28) as #1-25; the label's
    # catalog (67648) and its distribution name the cue 「輝きのその先へ」 (D53)
    ("cd.php#cd24", "25.輝きを目指して"): "25.輝きのその先へ",
}

# blocks that print no track list, with the list from the source that has it: page id -> (source, tracks)
BLOCK_TRACKS = {
    # CLUB CD SET 2023 (cd84) describes its CD only; the label's catalog lists it (the CLEAR EDITION splits
    # the same eleven tracks over two CDs). Credits as the CHRONICLE (2021～2024) block prints them (cd01_4906)
    "cd.php#cd84": ("https://catalog.bandainamcomusiclive.co.jp/release/70792/", [
        "SORA, FUJI, SUNSHINE!", "SORA, FUJI, SUNSHINE!（Off Vocal）",
        *(f"SORA, FUJI, SUNSHINE!（{m} Solo Ver.）" for m in (
            "高海千歌", "桜内梨子", "松浦果南", "黒澤ダイヤ", "渡辺 曜", "津島善子", "国木田花丸", "小原鞠莉", "黒澤ルビィ"))]),
}
_PRODUCT = re.compile(r"^■(.+?(?:EDITION|SET\s*\d{4})\s*(?:【[^【】]+】)?)$")  # "■…CLUB CD SET 2021 HOLOGRAM EDITION【初回限定生産】"


def _products(lines: list[str]) -> list[str]:
    """A CLUB CD SET block names each set (``■…【初回限定生産】``) with its catalog number on the next line,
    the second one deep in the contents: both are put under 【価格】 as ``【name】catalog`` (the editions)."""
    out = []
    for i, ln in enumerate(lines[:-1]):
        if (pm := _PRODUCT.match(ln)) and re.match(r"^LAC[A-Z]-\s*\d", lines[i + 1]):
            out.append(f"【{pm.group(1)}】{lines[i + 1].replace('LACM- ', 'LACM-')}")
    if not out:
        return lines
    rest = [ln for i, ln in enumerate(lines) if not (_PRODUCT.match(ln) or i and _PRODUCT.match(lines[i - 1]))]
    k = next((i for i, ln in enumerate(rest) if ln.startswith("【商品名】")), None)
    return rest if k is None else rest[:k] + ["【価格】", *out] + rest[k + 1:]


_ANCHOR = re.compile(r'<a id="(cd[\d_]+)"></a>')  # cd51, and cd01_5621 for a block the script loads


def parse_page(html: str, url: str) -> list[Block]:
    starts = [(mt.start(), mt.group(1)) for mt in _ANCHOR.finditer(html)]
    blocks = []
    for i, (pos, anchor) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(html)
        part = html[pos:end]
        pid = page_id(f"{url}#{anchor}")
        b = read_block(_products([LINE_FIXES.get((pid, ln), ln) for ln in text_lines(part)]), f"{url}#{anchor}", part)
        if not b.tracks and pid in BLOCK_TRACKS:
            b.tracks = [TrackObs(n, t, printed=t) for n, t in enumerate(BLOCK_TRACKS[pid][1], 1)]
            b.tracks[0].credits = parse_credit_line("作詞：畑 亜貴 作曲：前迫潤哉・RUSH EYE・春川仁志 編曲：RUSH EYE")
        if b.release_date and b.tracks:
            blocks.append(b)
    return blocks


def collect(fetcher: Fetcher, *, fresh: bool = False) -> Site:
    html = expand_in_elements(fetcher.get(PAGE, fresh=fresh).html, BASE + PAGE, fetcher, '<a id="{}"></a><div>')
    blocks = parse_page(html, BASE + PAGE)
    releases, skipped = releases_of(blocks, SPEC.skip)
    return Site([], releases, BASE + MEMBER_PATH, skipped)


def import_site(ds: Dataset, site: Site, review_dir: Path, today: dt.date) -> Report:
    return _import_site(ds, site, review_dir, today, SPEC)
