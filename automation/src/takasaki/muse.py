"""μ's (ラブライブ！) official site adapter (DESIGN.md §6.1, §7.2 ③, D44).

Every CD is a block on one page (``/otonokizaka/release.php``, ``<div class="box" id="cd01">``), in the
labelled layout the other older sites use, but written over ten years in several ways: ``【発売日】``
or ``発売日：…`` or ``2013.11.27 on sale``, ``アーティスト名：…``, ``歌：…`` above the tracks, ``・収録曲``
or no label at all, ``[ドラマパート]``, the artist with its reading (``μ's（ミューズ）``) or with its
members in brackets. The blocks are normalized to the common layout and read by ``sitepage``.

The two newest blocks are loaded by script (``release_detail.php``): a V.A. tribute album and a Blu-ray
(checked 2026-10-20), so they are not read. μ's has no migrated releases: everything is imported.
"""

from __future__ import annotations

import datetime as dt
import html as htmllib
import re
from pathlib import Path

from .importer import EditionObs, Performers, ReleaseObs, Report, Site, Spec, TrackObs
from .importer import import_site as _import_site
from .official import BASE, Fetcher
from .sitepage import Block, editions_of, parse_date, read_block, releases_of, split_edition, text_lines, unquote
from .store import Dataset
from .text import is_latin

GROUP = "μ’s"
PAGE = "/otonokizaka/release.php"
# the Blu-ray pages: each volume came with a CD of one new song (μ's オリジナルソングCD)
BD_PAGES = {"/otonokizaka/bd/tv1st/": "TVA1", "/otonokizaka/bd/tv2nd/": "TVA2", "/otonokizaka/bd/movie/": "Movie"}
# the Blu-ray BOX page lists every one of those songs with its singers, in order: TV 1 Vol.1～7, TV 2 Vol.1～7,
# the film, then the four all-volume purchase bonuses of the stores. The TV 1 page prints only Vol.1's CD.
BD_BOX = "/otonokizaka/bd/"  # the BD BOX (Forever Edition) page
# the box page's notation where the release itself prints another (its jacket, the label, Complete BEST BOX)
BOX_TITLES = {"silent tonight": "Silent tonight"}
STORES = {"アニブロゲーマーズ": "Gamers", "ゲーマーズ": "Gamers", "アニメイト": "animate", "ソフマップ": "Sofmap", "とらのあな": "Toranoana"}
MEMBER_PATH = "/otonokizaka/member/"

SPEC = Spec(project="muse", group_name=GROUP, legacy_group="Muse", review_prefix="MUS",
            skip={"release.php#cd91": "「Bring the LOVE！」: cross-project, imported with the Nijigasaki page (D45)",
                  "release.php#cd83": "Memorial CD-BOX「Complete BEST BOX」: a box of the earlier releases that prints no "
                                      "singers (its two START:DASH!! cannot be told apart)",
                  "release.php#cd40": "Solo Live! collection Memorial BOX Ⅱ: a box of the nine Solo Live! III albums "
                                      "(cd31～cd39), which are read on their own"},
            lineups_from_site=False)

# release dates the page leaves out or prints without the year, with what settles them
DATE_FIXES = {
    # Solo Live! III prints "4月2日発売": on the page between cd30 (2014-01-29) and cd41 (2014-04-23)
    **{f"cd{n}": dt.date(2014, 4, 2) for n in range(31, 41)},
    "cd52": dt.date(2015, 4, 22),  # 「ミはμ’sicのミ」 (LACM-14341): no date on the page; label metadata, Lantis catalog
    "cd16": dt.date(2012, 10, 17),  # にこりんぱな テーマソングDJCD (LACA-15244): no date on the page; Lantis catalog, Fandom
}
# drama and monologue tracks the page does not mark: (block, track number)
DRAMA = {("cd07", 10), ("cd08", 10), ("cd28", 5), ("cd28", 6), ("cd28", 7)}
# track titles as printed, corrected: (block, track number) -> title
TRACK_FIXES = {
    ("cd24", 4): "START:DASH!!(Off Vocal)",  # printed "(-1)", the minus-one (karaoke) track of the μ's version
    ("cd51", 3): "冬がくれた予感(Off Vocal)",  # printed "冬がくれた予感く(Off Vocal)", a stray く
    ("cd52", 3): "ミはμ'sicのミ(Off Vocal)",  # printed "ミはμ'sicのミく(Off Vocal)"
}
# credits the page misprints, left unread (the song's credits from its other pages stand): (block, title)
CREDIT_MISPRINTS = {
    ("cd37", "Wonder zone（NOZOMI Mix）"),  # prints the credits of これからのSomeday (yozuca*, lotta); every other page: 佐々倉有吾
}
# the solo albums: their series line names neither アルバム nor the catalog
ALBUM = re.compile(r"Solo Live!|ソロCD")

_BOX = re.compile(r'<div class="box" id="(cd\d+)">')
_LABELS = {"アーティスト名": "アーティスト", "アーティスト": "アーティスト", "発売日": "発売日", "価格": "価格", "税抜価格": "価格",
           "品番": "価格"}
_READING = re.compile(r"[（(][ァ-ヶー・]+[)）]")  # "μ's（ミューズ）", "BiBi（ビビ）"
_ANNOTATED = re.compile(r"^(.+?)\s*(?:[（(](新曲|ミニドラマ|モノローグ)[)）]|(\[DJトラック\]))$")
_MEMBERS_IN_BRACKETS = re.compile(r"^([^（(]+?)\s*[（(](.*[（(].*)[)）]$")  # "Printemps（高坂穂乃果(新田恵海)、…）"


def _clean_track(title: str) -> str:
    """A track title without what the page prints around it: the artist after it ("Shangri-La Shower　μ's"),
    the reading in a note ("小夜啼鳥恋詩（ルビ：ナイチンゲールラブソング）"), a stray closing bracket
    ("baby maybe 恋のボタン(Off Vocal)）", cd02)."""
    title = re.sub(r"\s+μ[’']s$", "", title)
    title = re.sub(r"\s*[（(]ルビ[：:][^()（）]*[)）]", "", title)
    if title[-1:] in ")）" and len(re.findall(r"[(（]", title)) < len(re.findall(r"[)）]", title)):
        title = title[:-1]
    return title.strip()


def _artist_line(ln: str) -> list[str]:
    """An artist line as ``sitepage.performers_of`` reads it: without the reading, its members' names
    joined by commas, several artists on lines of their own joined by ``＆``."""
    ln = _READING.sub("", ln).strip()
    mt = _MEMBERS_IN_BRACKETS.match(ln)
    if mt and "CV." not in mt.group(2):
        ln = mt.group(1).strip()  # the members are in the unit already
    ln = re.sub(r"[)）]\s*[＆&・,，]\s*", ")、", ln)  # "高坂穂乃果(CV.新田恵海)＆星空 凛(CV.飯田里穂)"
    ln = re.sub(r"\s*[＆&]\s*$", "", ln)
    if "／" in ln:  # "μ's／星空 凛(CV.飯田里穂)・西木野真姫(CV.Pile)": the group, then the trio
        return [x for p in ln.split("／") for x in (p.strip(), "＆")][:-1]
    return [ln]


def _normalize(lines: list[str]) -> list[str]:
    """The block's lines in the common layout: ``発売日：…`` → ``【発売日】…``, ``・収録曲`` → ``【収録内容】``
    (also before a track list printed without a label), a ``歌：`` line above the tracks → the artist,
    ``BD付通常盤：LACM-…`` → ``【BD付通常盤】LACM-…``."""
    out: list[str] = []
    tracks = artist = False
    for ln in lines:
        mt = re.match(r"^(アーティスト名?|発売日|税抜価格|価格|品番)\s*[：:]\s*(.*)$", ln)
        if mt and not tracks:
            artist = mt.group(1).startswith("アーティスト")
            out.append(f"【{_LABELS[mt.group(1)]}】")
            if mt.group(2):
                out += _artist_line(mt.group(2)) if artist else [mt.group(2)]
            continue
        if re.fullmatch(r"[・■＜【]?\s*(?:CD\s*)?(?:収録曲|収録内容|INDEX)\s*[＞】]?", ln):
            out.append("【収録内容】")
            tracks = True
            continue
        if not tracks and re.match(r"^\d{1,2}\s*[.．]", ln):
            out.append("【収録内容】")  # a track list without a label (cd21, cd22, cd24)
            tracks = True
        if not tracks and (sm := re.match(r"^歌\s*[：:]\s*(.+)$", ln)):
            out.append("【アーティスト】")
            out += _artist_line(sm.group(1))
            artist = True
            continue
        if not tracks and (em := re.match(r"^([^：:【】]*盤)\s*[：:]\s*(.+)$", ln)):
            out.append(f"【{em.group(1)}】{em.group(2)}")
            continue
        if dm := re.fullmatch(r"[▼＜<]?\s*[Dd][Ii][Ss][Cc]\s*[-.．]?\s*(\d+)\s*[＞>]?", ln):
            out.append(f"Disc.{dm.group(1)}")  # "▼disc - 2", "＜Disc2＞"
            continue
        if ln.startswith("【"):
            artist = ln.startswith("【アーティスト】")
            out.append(ln)
            continue
        if tracks and (sm := re.match(r"^歌\s*[：:]\s*(.+)$", ln)):
            ln = "歌：" + " ＆ ".join(p for p in _artist_line(sm.group(1)) if p != "＆")  # "歌：lily white（園田海未(三森すずこ)、…）"
        out += _artist_line(ln) if artist and not tracks else [ln]
    return out


def _title(part: str, read: str) -> tuple[str, str | None] | None:
    """(title, edition) from the block's title box (``<div class="titlebase">``): its last line, after the
    series line for a Solo Live! album (``ラブライブ！ Solo Live! from μ's 高坂穂乃果 orange cheers!``)."""
    mt = re.search(r'<div class="titlebase">(.*?)</div>', part, re.S)
    if not mt:
        return None
    ps = [" ".join(htmllib.unescape(re.sub(r"<[^>]+>", "", p)).split())
          for p in re.findall(r"<p[^>]*>(.*?)</p>", mt.group(1), re.S)]
    ps = [p for p in ps if p]
    if not ps:
        return None
    title = re.sub(r"\s*\[\s*CD\s*\+\s*DVD\s*\]\s*$", "", ps[-1])
    edition = None
    if em := re.match(r"^(.*?)\s*【([^【】]*(?:盤|仕様))】$", title):
        title, edition = em.group(1), em.group(2)
    title, ed2 = split_edition(title)
    title = re.sub(r"\s*[／/]\s*μ[’']s$", "", title)  # "僕らは今のなかで / μ’s"
    title = " / ".join(unquote(p.strip().strip("「」")) for p in re.split(r"」\s*[／/]\s*「", title))  # "「A」/「B」"
    if len(ps) > 1 and ps[0].startswith("ラブライブ！ Solo Live!"):
        title = f"{ps[0]} {title}"
    elif read.startswith("ラブライブ！ Solo Live!") or len(read) > len(title) and read.endswith(title):
        title = read  # the full title in 【タイトル】: the first Solo Live! albums, ラブライ部 ラジオ課外活動 にこりんぱな …
    return title, edition or ed2


def _head_date(lines: list[str]) -> dt.date | None:
    """A full date above the track list where no 発売日 label is printed ("2013.11.27 on sale")."""
    for ln in lines:
        if ln == "【収録内容】":
            break
        d = parse_date(ln)
        if d:
            return d
    return None


def parse_page(html: str, url: str) -> tuple[list[Block], list[str], dict[str, str]]:
    """The blocks to import, the ones left out with the reason, and the release type of the solo albums."""
    starts = [(mt.start(), mt.group(1)) for mt in _BOX.finditer(html)]
    blocks, skipped, types = [], [], {}
    for pos, anchor in starts:
        end = html.find("<!-- ! END", pos)
        part = html[pos:end if end > pos else None]
        lines = _normalize(text_lines(part))
        b = read_block(lines, f"{url}#{anchor}", part)
        named = _title(part, b.title)
        if named:
            b.alt_titles = [t for t in (b.title,) if t and t != named[0]]
            b.title, b.edition = named[0], named[1] or b.edition
        b.release_date = b.release_date or DATE_FIXES.get(anchor) or _head_date(lines)
        for t in b.tracks:
            t.title = TRACK_FIXES.get((anchor, t.no), _clean_track(t.title))
            if am := _ANNOTATED.match(t.title):
                t.title = am.group(1)
                t.drama = t.drama or am.group(2) != "新曲"
            t.drama = t.drama or (anchor, t.no) in DRAMA
            if (anchor, t.title) in CREDIT_MISPRINTS:
                t.credits = {}
        why = _video(b) or ("no tracklist on the page (song names only)" if not b.tracks else None) \
            or ("no release date on the page" if b.release_date is None else None)
        if why:
            skipped.append(f"release.php#{anchor} {b.title}: {why}")
            continue
        if ALBUM.search(" ".join(b.header + [b.title])):
            types[b.url] = "album"
        blocks.append(b)
    return blocks, skipped, types


def _video(b: Block) -> str | None:
    catalogs = [e.catalog for e in editions_of(b) if e.catalog]
    video = catalogs and all(c.startswith(("LABX", "LABM")) for c in catalogs)
    if video or re.search(r"Blu-ray|DVD", b.title) and "CD" not in b.title:
        return "a video release (Blu-ray / DVD), not a music release"
    return None


_BD_BOX = re.compile(r'id="(bd\d+)"')
# '1.「夢なき夢は夢じゃない」（歌：高坂穂乃果）', '01もしもからきっと（歌：東條 希）', '02.そして最後のページには（Off Vocal）'
_BD_TRACK = re.compile(r"^0?(\d)\s*[.．]?\s*「?(.+?)」?\s*[（(](?:歌[：:]\s*(.+?)|(Off Vocal))[)）]$")


def _bd_singers(text: str) -> Performers:
    """``南ことり・小泉花陽`` (characters, with or without their CV), or an artist: ``μ's``, ``Printemps``."""
    text = re.sub(r"\s*[（(]CV[.．][^()（）]*[)）]", "", text)
    names = [n.strip() for n in re.split(r"[・、]", text) if n.strip()]
    if len(names) == 1 and is_latin(names[0]):
        return Performers(GROUP if re.fullmatch(r"μ[’']s", names[0]) else names[0], None)
    return Performers(None, None, [(n, "") for n in names])


def parse_bd_box(html: str) -> list[tuple[str, Performers]]:
    """(song, singers) of the box page's list of the Blu-ray CD songs, in its order."""
    lines = text_lines(html)
    k = next(n for n, ln in enumerate(lines) if ln == "＜収録曲＞")
    out = []
    for song, singers in zip(lines[k + 1::1], lines[k + 2::1]):
        if song.startswith("＋") or not singers.startswith("／"):
            continue
        out.append((BOX_TITLES.get(song, song), _bd_singers(singers[1:].strip())))
    return out


def _bd_tracks(song: str, perf: Performers) -> list[TrackObs]:
    return [TrackObs(1, song, perf), TrackObs(2, f"{song} (Off Vocal)")]


def parse_bd_page(html: str, url: str, season: str, box: list[tuple[str, Performers]]) -> list[ReleaseObs]:
    """The CD of each Blu-ray volume, the volume's release date, and the stores' all-volume purchase CDs
    (dated with the last volume). A volume whose block does not print its CD takes its song and singers
    from the box page (``box``); the Off Vocal is the second track as on the volumes that print theirs."""
    starts = [(mt.start(), mt.group(1)) for mt in _BD_BOX.finditer(html)]
    offset = {"TVA1": 0, "TVA2": 7, "Movie": 14}[season]
    out: list[ReleaseObs] = []
    last: dt.date | None = None
    stores: list[tuple[str, str]] = []
    for i, (pos, anchor) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(html)
        lines = text_lines(html[pos:end])
        if "法人特典" in " ".join(lines[:3]):
            for n, ln in enumerate(lines):
                if ln == "○全巻購入特典" and n > 0 and lines[n - 1] in STORES and "新曲" in lines[n + 1]:
                    stores.append((STORES[lines[n - 1]], lines[n + 1]))
            continue
        date = next((d for ln in lines if "発売日" in ln and (d := parse_date(ln))), None)
        vol = re.search(r"第\s*(\d+)\s*巻", " ".join(lines[:3]))
        if date is None or (season != "Movie" and vol is None):
            continue
        name = f"{season} BD Vol.{vol.group(1)}" if season != "Movie" else "Movie BD"
        k = next((n for n, ln in enumerate(lines) if "オリジナルソングCD" in ln), None)
        tracks = []
        for ln in lines[k + 1:k + 4] if k is not None else []:
            if mt := _BD_TRACK.match(ln.strip()):
                song = mt.group(2).strip()
                tracks.append(TrackObs(int(mt.group(1)), f"{song} (Off Vocal)" if mt.group(4) else song,
                                       None if mt.group(4) else _bd_singers(mt.group(3))))
        if not tracks:
            n = offset + (int(vol.group(1)) - 1 if vol else 0)
            if n >= len(box):
                continue
            tracks = _bd_tracks(*box[n])
        perf = next(t.performers for t in tracks if t.performers)
        out.append(ReleaseObs(f"{url}#{anchor}", "", name, date, perf, [EditionObs("特装限定版", None, "CD")], tracks, {},
                              type="bd_bonus"))
        last = max(last or date, date)
    full = box[15:]  # TV 1's Printemps song, then TV 2's three
    for store, bonus in stores:
        unit = next((u for u in ("Printemps", "BiBi", "lily white") if u in bonus), None)
        named = re.search(r"「(.+?)」", bonus)
        pick = [(sg, p) for sg, p in (full[:1] if season == "TVA1" else full[1:]) if p.artist == unit]
        if named:
            pick = [(sg, p) for sg, p in full if sg == named.group(1)]
        if pick and last:
            song, perf = pick[0]
            out.append(ReleaseObs(f"{url}#bd00-{store.lower()}", "", f"{season} BD Full ({store})", last, perf,
                                  [EditionObs(None, None, "CD")], _bd_tracks(song, perf), {}, type="bd_bonus"))
    return out


def collect(fetcher: Fetcher, *, fresh: bool = False) -> Site:
    blocks, skipped, types = parse_page(fetcher.get(PAGE, fresh=fresh).html, BASE + PAGE)
    releases, more = releases_of(blocks, SPEC.skip)
    box = parse_bd_box(fetcher.get(BD_BOX, fresh=fresh).html)
    for path, season in BD_PAGES.items():
        releases += parse_bd_page(fetcher.get(path, fresh=fresh).html, BASE + path, season, box)
    releases.sort(key=lambda r: (r.release_date, r.url))
    for r in releases:
        if not r.performers.artist and not r.performers.artists and not r.performers.members:
            r.performers = Performers(GROUP, None)  # a block that names no artist: μ's (the title says "／μ's")
        r.type = r.type or types.get(r.url)
    return Site([], releases, BASE + MEMBER_PATH, skipped + more)


def import_site(ds: Dataset, site: Site, review_dir: Path, today: dt.date) -> Report:
    return _import_site(ds, site, review_dir, today, SPEC)
