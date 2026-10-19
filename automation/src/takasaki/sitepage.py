"""Music pages of the older project sites (DESIGN.md §6.1, §7.2 ③, D41): Nijigasaki, Liella!,
Aqours and the musical. They list a release as a block of labelled sections (``【アーティスト】``,
``【発売日】``, ``【価格】``, ``【収録内容】``), several blocks on one page (each with an anchor) or one
block per edition page. The reader turns a block into lines of text and reads them by section,
keeping the strings as printed; a line inside a track that is neither a credit nor a singer is left
out, and a credit line that cannot be read is listed as a problem.

A release migrated from the legacy files is checked: the tracks, the credits and the singers the
page prints get it as their evidence (D41), and the page fills in its type, label, editions and
artist. The releases the sites list beyond them are imported (Phase 3), except soundtracks, tribute
albums and releases without a tracklist yet (``skip_reason``), and the cross-project releases each
adapter names in ``Spec.skip``.
"""

from __future__ import annotations

import datetime as dt
import html as htmllib
import re
import unicodedata
from dataclasses import dataclass, field

from .hasunosora import parse_artists, parse_singers
from .importer import (EditionObs, EditionPage, ParseError, Performers, ReleaseObs, TrackObs, is_credit_line, page_id,
                       parse_credit_line)
from .text import match_key, split_version

# a credit span starts a line ("<span class="uta">作詞：…"); the same span also holds a title's tail ("(Off Vocal)")
_BREAKS = re.compile(r"<br\s*/?>|</p>|</div>|</h\d>|</li>|</dt>|</dd>|</tr>|<dl[^>]*>"
                     r"|<span class=\"uta\">(?=\s*(?:作|編|歌|弦|管|菅|ストリングス))")
_LABEL = re.compile(r"^【\s*([^【】]+?)\s*】\s*(.*)$")
_TRACK = re.compile(r"^(\d{1,2})\s*[.．]\s*(.+)$")
_DISC = re.compile(r"^[\[［【]?\s*(?:Disc|DISC|CD)\s*[.．]?\s*(\d+)\s*[\]］】]?(?:\s*[：:].*)?$")  # "Disc.2 ：スペシャルメモリアルCD"
_ROLE_WORD = r"(?:弦管編曲|弦編曲|管編曲|菅編曲|ストリングスアレンジ|作編曲|作詞|作曲|編曲)"
_ROLE_ONLY = re.compile(rf"^({_ROLE_WORD}(?:\s*[／/・]\s*{_ROLE_WORD})*)\s*[：:]$")
_SINGERS = re.compile(r"^(?:歌|掛け声)\s*[：:]\s*(.*)$")  # 掛け声: the voice calling the radio exercises (cd58, cd59)
# credits in English (the Aqours rock re-arrangement album): "Lyric：Aki Hata", "Arranged by EFFY(FirstCall)"
_EN_CREDIT = re.compile(r"^(Lyrics?|Music|Arranged by|Arrange(?:ment)?)\s*[：:]?\s*(.+)$")
_EN_ROLE = {"Lyric": "作詞", "Lyrics": "作詞", "Music": "作曲", "Arranged by": "編曲", "Arrange": "編曲", "Arrangement": "編曲"}
_OWN_VERSION = re.compile(r"^[A-Za-z][A-Za-z0-9 '&.-]{0,40}\sVer\.?$")  # "Hard Rock Ver." on a line of its own
# a video disc or the bonus items after the tracks: the end of the track list
# ("＜Blu-ray＞ ※初回限定盤のみ収録", "・BD" on the Aqours page)
_VIDEO = re.compile(r"^(?:[\[［【■＜<・]\s*)?(?:同梱)?(?:DVD|BD|Blu-ray|ＢＤ|ＤＶＤ)(?:\s*/\s*(?:DVD|BD))?(?:収録内容)?\s*[\]］】＞>]?"
                    r"(?:\s*※.*)?$")
_AFTER = ("特典", "封入", "店舗別", "試聴", "リリースイベント", "応募期間", "収録内容・商品仕様", "ご注文")
# an annotation after a title in a compilation's track list: "（Aqours 1st Single）"
_ANNOTATION_WORDS = r"Single|シングル|挿入歌|主題歌|テーマ|Blu-ray|特典|アルバム|Album|楽曲|コラボ|×|の歌"
_ANNOTATION = re.compile(rf"^(.+?)\s*[（(]([^()（）]*(?:{_ANNOTATION_WORDS})[^()（）]*)[)）]\s*$")
_DATE = re.compile(r"(\d{4})\s*[年/.]\s*(\d{1,2})\s*[月/.]\s*(\d{1,2})")
_CATALOG = re.compile(r"[A-Z]{2,5}[-\s]?\d{4,6}(?:[～~]\d+)?")


def text_lines(fragment: str) -> list[str]:
    text = re.sub(r"<ruby[^>]*>(.*?)</ruby>", _ruby, fragment, flags=re.S)
    text = _BREAKS.sub("\n", text)
    text = re.sub(r"<script.*?</script>|<style.*?</style>|<!--.*?-->", "", text, flags=re.S)
    text = htmllib.unescape(re.sub(r"<[^>]+>", "", text))
    return [" ".join(ln.split()) for ln in text.split("\n") if ln.strip()]


def _ruby(mt: re.Match[str]) -> str:
    """The base text, with the reading in brackets where the page gives brackets for it (<rp>), as a
    browser without ruby shows it: 祝祭<rt>カーニバル</rt> → 祝祭,
    羅針盤<rp>（</rp><rt>コンパス</rt><rp>）</rp> → 羅針盤（コンパス）."""
    inner = mt.group(1)
    return inner if "<rp>" in inner else re.sub(r"<rt>.*?</rt>", "", inner, flags=re.S)


def strip_annotation(title: str) -> str:
    """A version label is not an annotation: ``TOKIMEKI Runners（スクスタストーリー17章挿入歌Ver.）`` stays."""
    mt = _ANNOTATION.match(title)
    return mt.group(1) if mt and not split_version(title)[1] else title


def parse_date(s: str) -> dt.date | None:
    mt = _DATE.search(s)
    return dt.date(int(mt.group(1)), int(mt.group(2)), int(mt.group(3))) if mt else None


@dataclass
class Block:
    url: str  # the page, with the block's anchor
    header: list[str]  # the lines before the first label: the series line(s) and the title
    title: str
    edition: str | None
    release_date: dt.date | None
    artist: list[str] = field(default_factory=list)
    prices: list[str] = field(default_factory=list)
    tracks: list[TrackObs] = field(default_factory=list)
    alt_titles: list[str] = field(default_factory=list)  # other ways the block names the release
    problems: list[str] = field(default_factory=list)  # lines that could not be read (the track keeps no credits)


_EDITION = re.compile(r"^(.*?)\s*(?:【([^【】]*盤)】|［([^［］]*盤)］|\[([^\[\]]*盤)\]|（([^（）]*盤)）|\(([^()]*盤)\))$")


def split_edition(title: str) -> tuple[str, str | None]:
    """``X【上原歩夢盤】`` / ``X［第1話盤］`` / ``X（通常盤）`` → (X, edition)."""
    mt = _EDITION.match(title.strip())
    if not mt:
        return title.strip(), None
    return mt.group(1).strip(), next(g for g in mt.groups()[1:] if g)


def unquote(s: str) -> str:
    while (mt := re.fullmatch(r"[「『](.*)[」』]", s.strip())) and "」「" not in mt.group(1):
        s = mt.group(1)
    return s.strip()


_TITLE_BOX = re.compile(r'<div class="(?:title|llbox)">\s*<p>(.*?)</p>', re.S)


def title_parts(block_html: str) -> tuple[str, str, str | None] | None:
    """(series line, title, edition) from a block's title box: ``<span>series</span>title <span>[edition]</span>``."""
    mt = _TITLE_BOX.search(block_html)
    if not mt:
        return None
    inner = re.sub(r"<rt>.*?</rt>|<rp>.*?</rp>|<br\s*/?>", " ", mt.group(1), flags=re.S).strip()
    lead = edition = ""
    if inner.startswith("<span"):  # the series line, which may hold spans of its own
        end = _span_end(inner)
        lead, inner = inner[:end], inner[end:]
    em = re.search(r"<span[^>]*>([^<]*)</span>\s*$", inner)
    if em and re.fullmatch(r"\s*[\[［【（(][^\]］】）)]*盤[\]］】）)]\s*", htmllib.unescape(em.group(1))):
        edition, inner = em.group(1), inner[:em.start()]
    title, ed = split_edition(_clean(inner))
    if edition:
        _, ed = split_edition("x" + _clean(edition))
    return _clean(lead), unquote(title), ed


def _span_end(html: str) -> int:
    """The end of the span that opens ``html``, counting the spans inside it."""
    depth = 0
    for mt in re.finditer(r"<span[^>]*>|</span>", html):
        depth += 1 if mt.group(0) != "</span>" else -1
        if depth == 0:
            return mt.end()
    return len(html)


def _clean(fragment: str) -> str:
    return " ".join(htmllib.unescape(re.sub(r"<[^>]+>", "", fragment)).split())


def read_block(lines: list[str], url: str, block_html: str | None = None, *, cast: bool = False) -> Block:
    """One release block, read section by section. ``cast``: the singers are a stage cast (D29)."""
    header: list[str] = []
    section: str | None = None
    titles, artist, dates, prices = [], [], [], []
    tracks: list[TrackObs] = []
    disc, role, singing, done, drama, bonus = 1, None, False, False, False, False
    problems: list[str] = []
    # "森 悠也 歌：Liella!": the names of a role and the singers on one line
    lines = [part for ln in lines for part in re.split(r"\s+(?=歌\s*[：:])", ln)]
    for ln in lines:
        lm = _LABEL.match(ln)
        if lm and not _DISC.match(ln):
            label = lm.group(1).replace("　", "").replace(" ", "")
            rest = lm.group(2).strip()
            if label in ("一般発売日", "劇場先行発売日"):  # a film's theme sold in cinemas first: the general date
                section = "発売日" if label == "一般発売日" else "other"
                if rest and label == "一般発売日":
                    dates.append(rest)
                continue
            if label in ("タイトル", "アーティスト", "発売日", "価格", "収録内容", "収録曲", "CD収録曲", "収録楽曲"):
                section = {"収録曲": "収録内容", "CD収録曲": "収録内容", "収録楽曲": "収録内容"}.get(label, label)
                if tracks and section != "収録内容":
                    done = True
                if rest and section in ("価格", "発売日"):
                    (prices if section == "価格" else dates).append(rest)
                continue
            if section == "価格":  # "【初回限定盤】LACA-…" is an edition inside the prices
                prices.append(ln)
                continue
            if tracks:
                done = True  # another label after the tracks ("【初回生産特典】")
            section = "other"
            continue
        if ln == "収録内容":
            section = "収録内容"
            continue
        if section is None:
            header.append(ln)
        elif section == "タイトル":
            titles.append(ln)
        elif section == "アーティスト":
            artist.append(ln)
        elif section == "発売日":
            dates.append(ln)
        elif section == "価格" and not _TRACK.match(ln):
            prices.append(ln)
        elif section in ("収録内容", "価格") and not done:  # some blocks start the tracks without the label
            section = "収録内容"
            if _VIDEO.match(ln):
                done = True
                continue
            if dm := _DISC.match(ln):
                disc, role, singing, drama = int(dm.group(1)), None, False, False
                continue
            if ln in ("[CD]", "［CD］", "【CD】", "＜CD＞", "・CD") or ln.startswith("■") or re.fullmatch(r"第[一二三四五六七八九十]+幕", ln):
                role, singing = None, False
                drama = ln.startswith("■") and re.search(r"ドラマ|ラジオ", ln) is not None  # "■ドラマパート", "■録り下ろしラジオ"
                bonus = ln.startswith("■") and "ボーナストラック" in ln
                continue
            if role:  # the names under a role label
                if _ROLE_ONLY.match(ln) or _SINGERS.match(ln):
                    role = None  # the role was printed without names
                else:
                    _credit(tracks[-1], f"{role}：{ln}", problems)
                    role = None
                    continue
            if singing:  # the singers under "歌："
                singing = False
                if not (_ROLE_ONLY.match(ln) or is_credit_line(ln) or _TRACK.match(ln)):
                    tracks[-1].performers = _singers(ln, cast)
                    continue
            tm = _TRACK.match(ln)
            if tm:
                tracks.append(TrackObs(int(tm.group(1)), strip_annotation(tm.group(2).strip()), disc=disc, drama=drama))
                continue
            if not tracks:
                continue
            if rm := _ROLE_ONLY.match(ln):
                role = rm.group(1)
            elif sm := _SINGERS.match(ln):
                if sm.group(1):
                    tracks[-1].performers = _singers(sm.group(1), cast)
                else:
                    singing = True
            elif is_credit_line(ln):
                _credit(tracks[-1], ln, problems)
            elif em := _EN_CREDIT.match(ln):
                _credit(tracks[-1], f"{_EN_ROLE[em.group(1)]}：{em.group(2)}", problems)
            elif _OWN_VERSION.match(ln) and not split_version(tracks[-1].title)[1]:
                tracks[-1].title = f"{tracks[-1].title} ({ln})"
            elif bonus and tracks[-1].performers is None and not tracks[-1].credits and not ln.startswith(("・", "※", "★", "●")) \
                    and not any(w in ln for w in _AFTER):
                tracks[-1].performers = Performers(ln, None)  # the bonus track's performer ("浦の星交響楽団")
            elif any(w in ln for w in _AFTER):
                done = True
            elif "(CV." in ln.replace("（", "(") and tracks[-1].performers and not tracks[-1].performers.artists:
                more = _singers(ln)  # singers continued on the next line
                tracks[-1].performers.members += more.members
            elif tracks[-1].performers and tracks[-1].performers.cast and not _LABEL.match(ln):
                tracks[-1].performers.members += _cast(ln).members  # the cast continued (the ensemble)
            elif cast and tracks[-1].performers is None and not _LABEL.match(ln):
                # the cast printed under the title without "歌：" (the 2024 album), or the school idol club
                # that sings it, with its cast in brackets on the next line
                tracks[-1].performers = _cast(ln) if re.search(r"役[)）]|[、,，]", ln) else Performers(ln.strip(), None, cast=True)
    title_line = " ".join(titles) if titles else (header[-1] if header else "")
    title, edition = split_edition(title_line)
    if not titles and len(header) >= 2 and (edition is None or not title):
        # the edition on a line of its own under the title: "［みんなで叶える物語盤］", "（R3BIRTH盤）"
        _, own = split_edition("x" + header[-1])
        if own is not None:
            title, edition = split_edition(header[-2])[0], own
    date = next((d for d in map(parse_date, dates) if d), None)
    alt = []
    parts = title_parts(block_html) if block_html else None
    if titles:  # "【タイトル】" lines: the title on the first, or a series line and the title
        alt = [split_edition(t)[0] for t in (titles[0], titles[-1])]
    if parts and parts[1]:
        alt.append(title)
        _, title, edition = parts
        alt.append(re.sub(r"\s*[／/]\s*[^／/]+$", "", title))  # "君のこころは輝いてるかい？／Aqours"
    alt = [unquote(a) for a in dict.fromkeys(alt) if a and match_key(a) != match_key(title)]
    for t in tracks:
        if t.credits.pop("unreadable", None) is not None:
            t.credits.clear()  # a misprinted credit line leaves the whole track unchecked
    return Block(url, header, unquote(title), edition, date, artist, prices, tracks, alt, problems)


def _credit(track: TrackObs, line: str, problems: list[str]) -> None:
    try:
        track.credits.update(parse_credit_line(line))
    except ParseError as e:
        problems.append(f"track {track.no} {track.title!r}: {e}")
        track.credits["unreadable"] = []


_ROLE_OF = re.compile(r"^(.+?)\s*[（(]([^()（）]+?)役[)）]$")


def _cast(text: str) -> Performers:
    """``堀内まり菜（椿 ルリカ役）、金子 楓`` → members (role, actor); an ensemble member has no role."""
    members = []
    text = text.strip()
    if re.fullmatch(r"[（(].*[)）]", text):  # the cast of a group in brackets: "(堀内まり菜（椿 ルリカ役）、…)"
        text = text[1:-1]
    depth = len(re.findall(r"[（(]", text)) - len(re.findall(r"[)）]", text))
    if depth > 0 and text[:1] in "(（":  # ... over two lines: the bracket opens on the first
        text = text[1:]
    elif depth < 0 and text[-1:] in ")）":  # and closes on the last
        text = text[:-1]
    for part in re.split(r"\s*[、,，]\s*", text):
        if not part:
            continue
        mt = _ROLE_OF.match(part)
        members.append((mt.group(2).strip(), mt.group(1).strip()) if mt else ("", part.strip()))
    return Performers(None, None, members, cast=True)


def _singers(text: str, cast: bool = False) -> Performers:
    if cast or re.search(r"役[)）]", text):
        return _cast(text)
    text = text.replace("（", "(").replace("）", ")")
    if "(CV." in text and not re.search(r"[［\[]", text):
        # "高海千歌(CV.伊波杏樹) , 桜内梨子(CV.逢田梨香子)" or the names only ("国木田花丸 , 黒澤ルビィ")
        return parse_singers(text)
    if "(CV." not in text and re.search(r"\s[,，、]\s|、", text) and not re.search(r"[［\[]", text):
        return Performers(None, None, [(n.strip(), "") for n in re.split(r"\s*[,，、]\s*", text) if n.strip()])
    return parse_artists([text])


def editions_of(block: Block) -> list[EditionObs]:
    """Editions as the prices print them: ``【初回限定盤】LACA-…`` / ``みんなで叶える物語盤【BD付】`` followed
    by ``LACM-24100 / ￥4,950``, or one catalog number for a release with one edition."""
    out: list[EditionObs] = []
    label = None
    for ln in block.prices:
        lm = re.match(r"^【([^【】]*盤)】\s*(.*)$", ln)
        if lm:
            label, ln = lm.group(1), lm.group(2)
        elif not _CATALOG.search(ln) and re.search(r"盤", ln):
            label = re.sub(r"【[^【】]*付】", "", ln).strip()
            continue
        cm = _CATALOG.search(ln)
        if cm:
            out.append(EditionObs(label, unicodedata.normalize("NFKC", cm.group(0)).replace(" ", "-")))
            label = None
    return out


def release_type(block: Block) -> str | None:
    """The release type the block's series line says (``Aqours ベストアルバム``, ``主題歌ミニアルバム``);
    None leaves it to the catalog number."""
    lead = " ".join(block.header + [block.title])
    if "ドラマCD" in lead:
        return "drama_cd"
    if "ミニアルバム" in lead:
        return "mini_album"
    if "ベストアルバム" in lead:
        return "compilation"
    if re.search(r"アルバム|Album", lead):
        return "album"
    return None


def to_release(blocks: list[Block], performers: Performers, *, series: str = "") -> ReleaseObs:
    """The blocks of one release (one per edition, or one): the first one's tracks."""
    first = blocks[0]
    assert first.release_date is not None
    # an edition page that prints one catalog number without a label is the edition its title names
    editions = [EditionObs(e.label or (b.edition if len(eds) == 1 else None), e.catalog, e.media)
                for b in blocks for eds in [editions_of(b)] for e in eds] \
        or [EditionObs(b.edition, None) for b in blocks if b.edition]
    return ReleaseObs(first.url, series, first.title, first.release_date, performers, editions, first.tracks, {},
                      type=release_type(first), urls=[b.url for b in blocks],
                      edition_pages=[EditionPage(b.edition, b.url, b.tracks) for b in blocks], alt_titles=first.alt_titles)


def skip_reason(block: Block) -> str | None:
    """Why a release is not imported, as on the Hasunosora site (D40): a soundtrack (score), a
    tribute album of other franchises' artists, or a release announced before its tracklist."""
    artist = " ".join(block.artist).strip()
    if artist == "V.A.":
        return "V.A.: other franchises' artists (tribute album)"
    if artist.startswith("音楽："):
        return "soundtrack (score), not in the legacy files"
    if block.title == "タイトル未定" or any(re.fullmatch(r"[?？]+", split_version(t.title)[0].strip()) for t in block.tracks):
        return "announced without its tracklist yet"
    return None


def releases_of(blocks: list[Block], skip: dict[str, str]) -> tuple[list[ReleaseObs], list[str]]:
    """The releases of the blocks, oldest first, and the ones left out with the reason. A page id in
    ``skip`` (a cross-project release, left to a later phase) is reported by the importer."""
    releases, skipped = [], []
    for g in group_blocks(blocks):
        pid = page_id(g[0].url)
        if pid in skip:
            continue
        why = skip_reason(g[0])
        if why:
            skipped.append(f"{pid} {g[0].title}: {why}")
            continue
        releases.append(to_release(g, performers_of(g[0])))
    releases.sort(key=lambda r: (r.release_date, r.url))
    return releases, skipped + [f"{b.url} {p}" for b in blocks for p in b.problems]


def performers_of(block: Block) -> Performers:
    lines = [ln.replace("（", "(").replace("）", ")") for ln in block.artist if ln.strip()]
    if not lines:
        return Performers(None, None)
    try:
        return parse_artists(lines)
    except ParseError:
        return Performers(None, None)


def group_blocks(blocks: list[Block]) -> list[list[Block]]:
    """Blocks with the same date and title are the editions of one release."""
    groups: dict[tuple[dt.date | None, str], list[Block]] = {}
    for b in blocks:
        groups.setdefault((b.release_date, match_key(b.title)), []).append(b)
    return list(groups.values())


def check_title(stored: str, printed: str) -> bool:
    return match_key(stored) == match_key(printed) or match_key(stored) == match_key(strip_annotation(printed))
