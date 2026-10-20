"""幻日のヨハネ -SUNSHINE in the MIRROR- official site adapter (DESIGN.md §6.1, §7.2 ③, D46).

The site is https://www.yohane.net/ (not under lovelive-anime.jp). Its music list links a page per
release edition (``/music/detail/?id=N``): the four insert-song singles each have an A and a B edition
with the same tracks. Each Blu-ray volume (``/bd/detail/?id=N``) and the theatrical compilation
(``/bd/movie/``) came with a CD of a drama and a new song (録り下ろしオリジナルソングCD). The pages
print their labels on lines of their own (発売日, アーティスト, 価格, 収録内容); they are turned into the
common layout and read by ``sitepage``.

The songs are sung by the characters of this work (ヨハネ, ライラプス, the parallel-world Aqours), not
by Aqours's characters. Aqours's own singles for the series (the opening, the ending, 「Deep Blue」) are
on the Aqours page and imported from there.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from .importer import EditionObs, Performers, ReleaseObs, Report, Site, Spec, TrackObs, parse_credit_line
from .importer import import_site as _import_site
from .official import Fetcher
from .sitepage import parse_date, read_block, skip_reason, text_lines
from .store import Dataset

SITE = "https://www.yohane.net"
MUSIC = SITE + "/music/"
BD_PAGES = [SITE + f"/bd/detail/?id={n}" for n in range(1, 8)] + [SITE + "/bd/movie/"]

SPEC = Spec(project="yohane", group_name="幻日のヨハネ", legacy_group="Yohane", review_prefix="YHN",
            skip={"1": "「幻日ミステリウム」: Aqours's single, imported with the Aqours page",
                  "2": "「キミノタメボクノタメ」: Aqours's single, imported with the Aqours page",
                  "12": "「Deep Blue」: Aqours's single, imported with the Aqours page",
                  "13": "「幻日のヨハネ -The Story of the Sound of Heart-」 Blu-ray Memorial BOX: a video release"},
            lineups_from_site=False, group_artist=False)

_LABELS = ("発売日", "アーティスト", "価格", "収録内容", "初回生産特典", "店舗別特典はこちら", "封入特典", "映像特典", "仕様")
_EDITION = re.compile(r"^＜(.+?)＞$")


def _content(html: str) -> list[str]:
    """The page's lines from its heading on (after the site menu's MUSIC / Blu-ray)."""
    lines = text_lines(html)
    start = next((n + 1 for n, ln in enumerate(lines) if ln in ("MUSIC", "Blu-ray") and n > 10), 0)
    end = next((n for n, ln in enumerate(lines) if ln in ("BACK TO LIST", "SHARE") and n > start), len(lines))
    return lines[start:end]


def _singers(text: str) -> Performers:
    """``ヨハネ(CV.小林愛香) , ライラプス(CV.日笠陽子)``: the characters (the voice actresses are known)."""
    return Performers(None, None, [(n.strip(), cv.strip()) for n, cv in re.findall(r"([^,，、()（）]+?)\s*[（(]\s*CV[.．]\s*([^)）]+)[)）]", text)])


def parse_music_page(html: str, url: str) -> tuple[ReleaseObs | None, str | None]:
    """A single's edition page: the release (both editions' catalog numbers are printed on each), or
    why it is left out. The page prints the singers of the two songs in its artist field, one per
    song, separated by ``/``."""
    lines = _content(html)
    first = next((n for n, ln in enumerate(lines) if ln in _LABELS), len(lines))
    head = lines[:first]  # the series line, the title, the edition; then notes and links to the songs' videos
    edition = next((m.group(1) for ln in head if (m := _EDITION.match(ln))), None)
    norm: list[str] = [ln for ln in head[:3] if not _EDITION.match(ln)][:2]
    for ln in lines[first:]:
        norm.append(f"【{ln}】" if ln in _LABELS else ln)
    b = read_block(norm, url)
    b.edition = edition
    why = skip_reason(b) or (None if b.tracks and b.release_date else "no tracklist (a video release)")
    if why:
        return None, why
    i = norm.index("【アーティスト】") if "【アーティスト】" in norm else len(norm)
    end = next((n for n in range(i + 1, len(norm)) if norm[n].startswith("【")), len(norm))
    artist = " ".join(norm[i + 1:end])
    groups = [g for g in artist.split("/") if "CV" in g]
    songs = [t for t in b.tracks if "Off Vocal" not in t.title and "Off vocal" not in t.title]
    if len(groups) == len(songs):  # each song's singers
        for t, g in zip(songs, groups):
            t.performers = _singers(g)
    eds: list[EditionObs] = []
    label = None
    for ln in norm[norm.index("【価格】") + 1:]:
        if ln.startswith("【"):
            break
        if m := _EDITION.match(ln):
            label = m.group(1)
        elif cm := re.search(r"[A-Z]{4}-\d{4,6}", ln):
            eds.append(EditionObs(label, cm.group(0), "CD"))
            label = None
    perf = _singers(artist)
    return ReleaseObs(url, " ".join(b.header[:-1]), b.title, b.release_date, perf, eds, b.tracks, {},  # type: ignore[arg-type]
                      type="single"), None


def parse_bd_page(html: str, url: str) -> ReleaseObs | None:
    """A Blu-ray's original song CD: a drama, the new song and its Off vocal (the film adds a version)."""
    lines = _content(html)
    k = next((n for n, ln in enumerate(lines) if "オリジナルソングCD" in ln), None)
    date = next((d for n, ln in enumerate(lines[:-1]) if ln == "発売日" and (d := parse_date(lines[n + 1]))), None)
    if k is None or date is None:
        return None
    vol = re.search(r"第\s*(\d+)\s*巻", " ".join(lines[:4]))
    name = f"TVA1 BD Vol.{vol.group(1)}" if vol else "Movie BD"
    tracks: list[TrackObs] = []
    for ln in lines[k + 1:]:
        ln = re.sub(r"^(作|編|歌)\s+(詞|曲|唱)", r"\1\2", ln).replace("歌唱", "歌")  # "作 詞：", "歌 唱："
        if ln.startswith("・") or ln in _LABELS:
            break
        if m := re.match(r"^(\d{1,2})\s*[.．]\s*(.+)$", ln):
            title = m.group(2).strip()
            drama = re.fullmatch(r"ドラマ\s*『(.+)』", title)
            tracks.append(TrackObs(int(m.group(1)), drama.group(1) if drama else title, drama=bool(drama)))
        elif tracks and (sm := re.match(r"^歌\s*[：:]\s*(.+)$", ln)):
            tracks[-1].performers = _singers(sm.group(1))
        elif tracks and re.match(r"^(作詞|作曲|編曲|作詞・作曲・編曲|作曲・編曲|作編曲)\s*[：:]", ln):
            tracks[-1].credits.update(parse_credit_line(ln))
    catalog = next((m.group(0) for ln in lines if (m := re.search(r"BCXA-\d{4}", ln))), None)
    if not tracks:
        return None
    return ReleaseObs(url, "", name, date, Performers(None, None), [EditionObs("特装限定版", catalog, "CD")], tracks, {},
                      type="bd_bonus")


def collect(fetcher: Fetcher, *, fresh: bool = False) -> Site:
    listing = fetcher.get(MUSIC, fresh=fresh).html
    ids = list(dict.fromkeys(re.findall(r'href="\./detail/\?id=(\d+)"', listing)))
    releases: dict[tuple[dt.date, str], ReleaseObs] = {}
    skipped = []
    for i in ids:
        url = f"{MUSIC}detail/?id={i}"
        if i in SPEC.skip:
            continue
        obs, why = parse_music_page(fetcher.get(url, fresh=fresh).html, url)
        if obs is None:
            skipped.append(f"music ?id={i}: {why}")
            continue
        key = (obs.release_date, obs.title)
        if key in releases:  # the other edition's page: the same tracks
            releases[key].urls.append(url)
            continue
        obs.urls = [url]
        releases[key] = obs
    out = list(releases.values())
    for url in BD_PAGES:
        bd = parse_bd_page(fetcher.get(url, fresh=fresh).html, url)
        if bd is not None:
            out.append(bd)
    out.sort(key=lambda r: (r.release_date, r.url))
    return Site([], out, SITE + "/character/", skipped)


def import_site(ds: Dataset, site: Site, review_dir: Path, today: dt.date) -> Report:
    return _import_site(ds, site, review_dir, today, SPEC)
