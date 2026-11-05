"""Original soundtracks (DESIGN.md §4.2, D53): the anime's score and the songs as the episodes used them.

An OST block on the official site prints the score's cues by their titles (μ's adds the cue number:
``始まりの朝（メインテーマ）[LM01]``) and the songs as heard in an episode (``青空Jumping Heart
【オープニング主題歌(TVサイズ)】``, ``未来は風のように 〜第2話Ver.〜``). The importer hands such a
release here. The label's catalog page of the album (``catalog.bandainamcomusiclive.co.jp``, also
official) prints the same track list with more: the singers of every song, the size of a cut the
project page leaves out, and each title in Latin script on its EN tab. The album is stored as:

- a cue: a ``bgm`` work of the project, composed by the album's 音楽 credit, with one instrumental
  recording; a cue printed again with a version (``スノードームメモリー（String Quartet Ver.）``) is
  another recording of it. A new cue title is named in review like any title (``<prefix>-titles.yaml``),
  its rom seeded from the catalog's EN title (else the album's Fandom article); the cue number and the
  episode go into the track note;
- a song: a recording of its work. The version is the one printed (``TV size``, ``MOVIEサイズ``,
  ``第2話Ver.``, a member's ``Ver.``); the singers are the ones the page prints (μ's), else the ones the
  catalog prints, else the ones the Fandom article names (``By: …``), else those of the recording the
  version is cut from. A cut (a size, an episode's version) is arranged as that recording; another
  arrangement (``Piano Mix``) keeps only what is printed. Tracks the rules cannot read are set in
  ``OVERRIDES``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from . import model as m
from .text import halfwidth, is_latin, match_key, slugify

# the Love Live! Fandom article of each soundtrack: its track list romanizes the cues and names the singers
FANDOM = {
    "https://www.lovelive-anime.jp/otonokizaka/release.php#cd23": "Notes of School idol days",
    "https://www.lovelive-anime.jp/otonokizaka/release.php#cd48": "Notes of School idol days ~Glory~",
    "https://www.lovelive-anime.jp/otonokizaka/release.php#cd57": "Notes of School idol days ~Curtain Call~",
    "https://www.lovelive-anime.jp/uranohoshi/cd.php#cd12": "Sailing to the Sunshine",
    "https://www.lovelive-anime.jp/uranohoshi/cd.php#cd24": "Journey to the Sunshine",
    "https://www.lovelive-anime.jp/uranohoshi/cd.php#cd30": "Sailing to the Rainbow",
    "https://www.lovelive-anime.jp/nijigasaki/cd.php#cd28": "Sound of TOKIMEKI",
    "https://www.lovelive-anime.jp/nijigasaki/cd.php#cd46": "Bound for TOKIMEKI",
    "https://www.lovelive-anime.jp/nijigasaki/cd.php#cd68": "Sangoshou no Kioku",
    "https://www.lovelive-anime.jp/nijigasaki/cd.php#cd01_5601": "Sazameki no Machikado",
    "https://www.lovelive-anime.jp/yuigaoka/music/cd11.php": "Dreams of the Superstar",
    "https://www.lovelive-anime.jp/yuigaoka/music/cd26.php": "Twinkle of the Superstar",
    "https://www.lovelive-anime.jp/yuigaoka/music/cd49.php": "The beginning of the Superstar",
    "https://www.lovelive-anime.jp/hasunosora/music/cd/?p=01_6148": "Petals of History",
    "https://www.yohane.net/music/detail/?id=5": "Minna no Oto",
}

# the label's catalog page of each soundtrack (catalog.bandainamcomusiclive.co.jp/release/<id>/)
CATALOG = {
    "https://www.lovelive-anime.jp/otonokizaka/release.php#cd23": 62812,
    "https://www.lovelive-anime.jp/otonokizaka/release.php#cd48": 65010,
    "https://www.lovelive-anime.jp/otonokizaka/release.php#cd57": 65870,
    "https://www.lovelive-anime.jp/uranohoshi/cd.php#cd12": 67052,
    "https://www.lovelive-anime.jp/uranohoshi/cd.php#cd24": 67648,
    "https://www.lovelive-anime.jp/uranohoshi/cd.php#cd30": 68256,
    "https://www.lovelive-anime.jp/nijigasaki/cd.php#cd28": 69362,
    "https://www.lovelive-anime.jp/nijigasaki/cd.php#cd46": 70237,
    "https://www.lovelive-anime.jp/nijigasaki/cd.php#cd68": 72132,
    "https://www.lovelive-anime.jp/nijigasaki/cd.php#cd01_5601": 84933,
    "https://www.lovelive-anime.jp/yuigaoka/music/cd11.php": 69839,
    "https://www.lovelive-anime.jp/yuigaoka/music/cd26.php": 70388,
    "https://www.lovelive-anime.jp/yuigaoka/music/cd49.php": 72246,
    "https://www.lovelive-anime.jp/hasunosora/music/cd/?p=01_6148": 93682,
    "https://www.yohane.net/music/detail/?id=5": 71177,
}
CATALOG_URL = "https://catalog.bandainamcomusiclive.co.jp/release/{}/"

# tracks the rules below cannot read, by (album page, disc, track number): fields of the track as stored.
# "work": the song (its id); "version": (ja, rom, ko) of the version, "id" its recording id; "performers":
# [(kind, id)]; "kind": the recording kind; "cut": whether it is arranged as the recording it is cut from;
# "printed": (ja, rom, ko) of the track's title as printed, when it names more than the recording
OVERRIDES: dict[tuple[str, int, int], dict[str, Any]] = {
    # 2期 #14 prints 「想いよひとつになれ」: 梨子's piano piece on the song (Fandom: "Riko's Piano Sonata"), no singing
    ("https://www.lovelive-anime.jp/uranohoshi/cd.php#cd24", 2, 14): {
        "work": "aqours/omoi-yo-hitotsu-ni-nare", "id": "riko-s-piano-sonata", "kind": "instrumental", "cut": False,
        "version": ("Riko's Piano Sonata", "Riko's Piano Sonata", "Riko's Piano Sonata"), "performers": [],
        "performers_note": "공식 페이지는 곡명만 인쇄. Fandom OST 문서의 'Riko's Piano Sonata'(피아노 연주곡, 가창 없음)",
        "as_printed": True},
    # the film's 「As Time Goes By」 (Herman Hupfeld), a cover sung by a singer of the film: a work of external (D50)
    ("https://www.lovelive-anime.jp/otonokizaka/release.php#cd57", 1, 12): {"project": "external"},
    # the film's two songs run together as one track: stored as PHOENIX's MOVIE size, printed as the album prints it
    ("https://www.lovelive-anime.jp/nijigasaki/cd.php#cd68", 1, 19): {
        "work": "nijigasaki/phoenix", "printed": ("PHOENIX (MOVIE size)～Stellar Stream (MOVIE size)",
                                                  "PHOENIX (MOVIE size)~Stellar Stream (MOVIE size)",
                                                  "PHOENIX (MOVIE size)~Stellar Stream (MOVIE size)")},
}

# the album as the page names it: "オリジナルサウンドトラック 「Twinkle of the Superstar」" → the album's own title
_TITLE = re.compile(r"(?:オリジナルサウンドトラック|サウンドトラック)\s*[「『](.+?)[」』]\s*$|"
                    r"(?:オリジナルサウンドトラック|サウンドトラック)\s+(.+)$")

# the cue numbers of the score: "[LM01]", "（LM15H）", "（LM01 TypeB）", "（LM73 EDアレンジ）", "[ED Arrange]", "（M11A）"
_CUE = re.compile(r"\s*[\[［(（]\s*((?:[LTP]?M\d+[A-Z]?|LMOP)(?:\s+(?:Type\s*[A-Z]|EDアレンジ))?|BGM|(?:OP|ED)\s*Arrange)"
                  r"\s*[\]］)）]")
# a note in brackets: "[第1話挿入歌]", "【オープニング主題歌(TVサイズ)】", "［オープニング主題歌］"
_NOTE = re.compile(r"\s*(?:\[([^\[\]]*)\]|［([^［］]*)］|【([^【】]*)】)")
_SIZE_IN = re.compile(r"[(（]([^()（）]*(?:サイズ|[Ss]ize)[^()（）]*)[)）]")
_VERSION_WORDS = r"サイズ|[Ss]ize|[Vv]er\.?|[Vv]ersion|[Mm][Ii][Xx]|[Ee]dit|Demo|リフレイン|[Oo]ff [Vv]ocal|アレンジ|Arrange"
_ROUND = re.compile(rf"^(?P<base>.+?)\s*[(（](?P<ver>[^()（）]*(?:{_VERSION_WORDS})[^()（）]*)[)）]\s*$")
_WAVE = re.compile(rf"^(?P<base>.+?)\s*[～〜~](?P<ver>[^～〜~]*(?:{_VERSION_WORDS})[^～〜~]*)[～〜~]\s*$")
_TAIL = re.compile(r"^(?P<base>.+?)\s+(?P<ver>[A-Za-z][A-Za-z ]*\s(?:ver|Ver|version|Version)\.?)$")  # "色とりどりの虹 EDM ver."

# the album's own notes on a track
_UNUSED = re.compile(r"\s*※(.+)$")  # "※未使用音源"

# versions in Japanese, in rom and ko (a Latin label is the same in every language)
VERSION_NAMES = {
    "TVサイズ": ("TV Size", "TV 사이즈"),
    "Shortサイズ": ("Short Size", "Short 사이즈"),
    "MOVIEサイズ": ("MOVIE Size", "MOVIE 사이즈"),
    "TVアニメ挿入歌Ver.": ("TV Anime Insert Song Ver.", "TV 애니메이션 삽입곡 Ver."),
    "ピアノアレンジVer.": ("Piano Arrange Ver.", "피아노 어레인지 Ver."),
    "歌謡Ver.": ("Kayou Ver.", "가요 Ver."),
    "上海 Ver.": ("Shanghai Ver.", "상하이 Ver."),
    "ミュージカルver.": ("Musical ver.", "뮤지컬 ver."),
    "リフレイン": ("Refrain", "리프레인"),
    # μ's endings: the members singing that episode's version (their fans' shorthand, as printed)
    "TVサイズ・ことほのうみ": ("TV Size・KotoHonoUmi", "TV 사이즈・코토호노우미"),
    "TVサイズ・まきりんぱな": ("TV Size・MakiRinPana", "TV 사이즈・마키린파나"),
    "TVサイズ・にこソロ": ("TV Size・Nico Solo", "TV 사이즈・니코 솔로"),
    "TVサイズ・にこりんぱなまきことほのうみ": ("TV Size・NicoRinPanaMakiKotoHonoUmi", "TV 사이즈・니코린파나마키코토호노우미"),
    "TVサイズ・えりのぞ": ("TV Size・EliNozo", "TV 사이즈・에리노조"),
    "TVサイズ・ことりソロ": ("TV Size・Kotori Solo", "TV 사이즈・코토리 솔로"),
    "TVサイズ・穂乃果ソロ": ("TV Size・Honoka Solo", "TV 사이즈・호노카 솔로"),
    "TVサイズ・のぞえりにこ": ("TV Size・NozoEliNico", "TV 사이즈・노조에리니코"),
    "TVサイズ・凛ソロ": ("TV Size・Rin Solo", "TV 사이즈・린 솔로"),
    "TVサイズ・のぞまきえり": ("TV Size・NozoMakiEli", "TV 사이즈・노조마키에리"),
    "TVサイズ・全員合唱": ("TV Size・All Together", "TV 사이즈・전원 합창"),
}
_EPISODE = re.compile(r"^第\s*([0-9０-９]+)\s*話\s*Ver\.?$")
# an episode's opening or ending printed without a size: that episode's version of the song
_THEME = re.compile(r"^第\s*([0-9０-９]+)\s*話\s*(エンディング|オープニング)(?:主題歌|テーマ)$")
# a cut of a recording: arranged as the recording it is cut from
_CUT = re.compile(r"サイズ|[Ss]ize|第\s*[0-9０-９]+\s*話|[Ee]dit$|挿入歌Ver|主題歌$")


@dataclass
class FandomTrack:
    rom: str
    ja: str | None = None
    link: str | None = None  # the song article the line links
    by: list[str] = field(default_factory=list)  # the singers after "By:"
    by_text: str = ""


@dataclass
class CatalogTrack:
    ja: str
    singers: str | None = None  # "澁谷かのん (CV.伊達さゆり)/唐 可可 (CV.Liyuu)", "Liella!"
    en: str | None = None


@dataclass
class CatalogAlbum:
    url: str
    catalog: str | None
    title_en: str | None
    discs: list[list[CatalogTrack]]

    def track(self, disc: int, pos: int) -> CatalogTrack | None:
        return self.discs[disc - 1][pos] if disc - 1 < len(self.discs) and pos < len(self.discs[disc - 1]) else None


def read_catalog(html: str, url: str) -> CatalogAlbum:
    """A catalog page: the JP tab (titles, then the singers of a song on the next line) and the EN tab
    (the same tracks in Latin script), each as discs of ``N.`` lines."""
    from .sitepage import text_lines

    lines = text_lines(html)
    cat = next((ln for ln in lines if re.fullmatch(r"[A-Z]{4}-\d{4,6}.*", ln)), None)
    tabs: list[list[list[tuple[str, list[str]]]]] = []
    discs: list[list[tuple[str, list[str]]]] = []
    for i, ln in enumerate(lines):
        if mt := re.fullmatch(r"DISC\s*(\d+)", ln):
            if int(mt.group(1)) == 1 and discs:
                tabs.append(discs)
                discs = []
            discs.append([])
        elif discs and re.fullmatch(r"\d{1,2}\.", ln) and i + 1 < len(lines):
            discs[-1].append((lines[i + 1], []))
        elif discs and discs[-1] and lines[i - 1] != discs[-1][-1][0] and not re.fullmatch(r"\d{1,2}\.", lines[i - 1]):
            pass
        elif discs and discs[-1] and lines[i - 1] == discs[-1][-1][0] and not re.fullmatch(r"\d{1,2}\.|DISC\s*\d+", ln) \
                and not re.search(r"[¥￥]|BUY|PLAY|BACK|購入", ln):
            discs[-1][-1][1].append(ln)  # the singers under the title
    if discs:
        tabs.append(discs)
    title_en = None
    if (k := next((i for i, ln in enumerate(lines) if cat and ln == cat), None)) is not None:
        title_en = lines[k + 5] if k + 5 < len(lines) else None  # catalog, date, ALBUM, Lantis, JP title, EN title
    ja = tabs[0] if tabs else []
    en = tabs[1] if len(tabs) > 1 else []
    out = [[CatalogTrack(t, s[0] if s else None, en[d][n][0] if d < len(en) and n < len(en[d]) else None)
            for n, (t, s) in enumerate(disc)] for d, disc in enumerate(ja)]
    return CatalogAlbum(url, cat, title_en, out)


def catalog_album(cid: int) -> CatalogAlbum:
    from .official import Fetcher
    from .store import repo_root

    url = CATALOG_URL.format(cid)
    fetcher = Fetcher(repo_root() / "automation" / ".cache" / "catalog", interval=3.0)
    return read_catalog(fetcher.get(url).html, url)


def catalog_singers(text: str) -> Any:
    """``澁谷かのん (CV.伊達さゆり)/唐 可可 (CV.Liyuu)`` (characters), ``Liella!`` / ``Aqours`` (artists),
    ``A-RISE (綺羅ツバサ (CV.桜川めぐ), …)`` (an artist with its members)."""
    from .importer import Performers

    parts = [p.strip() for p in re.split(r"\s*/\s*(?![^()（）]*[)）])", text) if p.strip()]
    members, artists = [], []
    for p in parts:
        if mt := re.fullmatch(r"(.+?)\s*[(（]\s*CV[.．:：]\s*([^()（）]+?)\s*[)）](?:\s*from\s+.+)?", p):
            members.append((mt.group(1).strip(), mt.group(2).strip()))
        else:
            artists.append(re.sub(r"\s*[(（].*[)）]\s*$", "", p).strip())
    if artists and not members:
        return Performers(artists[0], None) if len(artists) == 1 else Performers(None, None, [], artists)
    if members and not artists:
        return Performers(None, None, members)
    return None


@dataclass
class Printed:
    """A track title as the page prints it, taken apart."""

    base: str  # the work's title as printed
    version: str | None = None  # the version label as printed ("TVサイズ", "第2話Ver.")
    wave: bool = False  # printed between wave dashes ("～TV Size～")
    off_vocal: bool = False
    notes: list[str] = field(default_factory=list)  # cue number, episode, "未使用音源"
    tail: str = ""  # the version as printed after the base ("（リフレイン）", " ～TV Size～")


def album_title(title: str) -> str:
    mt = _TITLE.search(title)
    return (mt.group(1) or mt.group(2)).strip() if mt else title


def read_title(printed: str) -> Printed:
    text = unicodedata.normalize("NFC", printed).strip()
    notes: list[str] = []
    version: str | None = None
    if um := _UNUSED.search(text):
        notes.append(um.group(1).strip())
        text = text[:um.start()].strip()
    for cm in list(_CUE.finditer(text)):
        notes.insert(0, re.sub(r"\s+", " ", cm.group(1)))
    text = _CUE.sub("", text).strip()
    for nm in list(_NOTE.finditer(text)):
        inner = next(g for g in nm.groups() if g is not None).strip()
        size = _SIZE_IN.search(inner)
        if size:
            version = size.group(1).strip()
            inner = _SIZE_IN.sub("", inner).strip()
        if inner:
            notes.append(inner)
    text = _NOTE.sub("", text).strip()
    off = False
    if om := re.match(r"^(.+?)\s*[(（]\s*[Oo]ff [Vv]ocal\s*[)）]\s*$", text):
        text, off = om.group(1).strip(), True
    wave, tail = False, ""
    if version and re.fullmatch(r"フルサイズ|[Ff]ull\s*[Ss]ize", version):  # 【第8話挿入歌(フルサイズ)】: the recording itself
        notes.append(version)
        version = None
        return Printed(text, None, False, off, notes, "")
    if version is None:
        if rm := _ROUND.match(text):
            tail = text[len(rm["base"]):]
            text, version = rm["base"].strip(), rm["ver"].strip()
        elif wm := _WAVE.match(text):
            tail = text[len(wm["base"]):]
            text, version, wave = wm["base"].strip(), wm["ver"].strip(), True
        elif tm := _TAIL.match(text):
            tail = text[len(tm["base"]):]
            text, version = tm["base"].strip(), tm["ver"].strip()
    return Printed(text, version, wave, off, notes, tail)


# --- Fandom ------------------------------------------------------------------------------


def _unlink(text: str) -> str:
    text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    return text.replace("'''", "").replace("''", "").strip()


def _template_args(text: str) -> tuple[list[str], str]:
    from .fandom import _template

    return _template(text)


def fandom_tracks(wikitext: str) -> list[list[FandomTrack]]:
    """The album's track list, disc by disc (a heading naming a disc or a CD starts one)."""
    start = wikitext.find("==Track Listing==")
    body = wikitext[start:] if start >= 0 else wikitext
    end = re.search(r"^==[^=]", body[len("==Track Listing=="):], re.M)
    body = body[:end.start() + len("==Track Listing==")] if end else body
    discs: list[list[FandomTrack]] = []
    for line in body.splitlines():
        if re.match(r"^=+.*(?:Disc|CD)\s*\d", line):
            discs.append([])
            continue
        if not line.startswith("#"):
            continue
        if not discs:
            discs.append([])
        discs[-1].append(_fandom_line(line))
    return discs


def _fandom_line(line: str) -> FandomTrack:
    text = re.sub(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>|<br\s*/?>", "", line.lstrip("#").strip())
    by_text = ""
    if bm := re.search(r"\s+[Bb]y\s*[:：]?\s*(.+)$", text):
        text, by_text = text[:bm.start()].strip(), bm.group(1).strip()
    link = None
    if text.startswith("{{"):
        args, _ = _template_args(text)
        lm = re.search(r"\[\[([^\]|]+)", args[0]) if args else None
        link = lm.group(1).strip() if lm else None
        rom = _unlink(args[0]) if args else _unlink(text)
        ja = _unlink(args[1]) if len(args) > 1 else None
    else:
        lm = re.match(r"\s*\[\[([^\]|]+)", text)
        link = lm.group(1).strip() if lm else None
        jm = re.search(r"\s*\(([^()]*[^\x00-\x7f][^()]*?)(?:\s*''[^']*'')?\)", text)
        ja = re.sub(r"\s*''.*$", "", jm.group(1)).strip() if jm else None
        rom = _unlink(text[:jm.start()] if jm else text)
    rom = re.sub(r"\s*\[[^\]]*\]\s*$", "", rom).strip()  # "Dance! Dance! Dance! [LM46]"
    from .fandom import _singers

    singers = _singers(by_text)[0] if by_text else []
    return FandomTrack(rom, ja, link, singers, by_text)


def fandom_wikitext(title: str) -> str:
    """The article's wikitext, from the Fandom cache (``automation/.cache/fandom``, fetched when missing)."""
    from . import fandom
    from .official import Fetcher
    from .store import repo_root

    fetcher = Fetcher(repo_root() / "automation" / ".cache" / "fandom", interval=3.0)
    return fandom.parse_response(fetcher.get(fandom.wikitext_url(title)).html)


_PARTICLES = {"no", "wa", "ga", "o", "wo", "ni", "de", "to", "e", "he", "mo", "ka", "ya", "yo", "ne", "na", "kara", "made",
              "yori", "dake", "shika", "tte", "sa", "zo", "ze"}


def title_case(rom: str) -> str:
    """``Sakurairo no kaze`` → ``Sakurairo no Kaze``: words capitalized, particles after the first word in
    lower case, a word with capitals of its own (``LET'S``) as written."""
    out = []
    for i, w in enumerate(rom.split(" ")):
        if w != w.lower() or not w[:1].isalpha():
            out.append(w)
        elif i and w in _PARTICLES:
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


# --- versions ---------------------------------------------------------------------------


def version_names(imp: Any, ver: str, project: str) -> tuple[str, str, str, str] | None:
    """(recording id, ja, rom, ko) of a version as printed."""
    label = ver.strip()
    if label in VERSION_NAMES:
        rom, ko = VERSION_NAMES[label]
        return slugify(rom), label, rom, ko
    if em := _EPISODE.match(label):
        n = int(unicodedata.normalize("NFKC", em.group(1)))
        return f"episode-{n}-ver", label, f"Episode {n} Ver.", f"제{n}화 Ver."
    if tm := _THEME.match(label):
        n = int(unicodedata.normalize("NFKC", tm.group(1)))
        rom, ko = ("Ending Theme", "엔딩 주제가") if tm.group(2) == "エンディング" else ("Opening Theme", "오프닝 주제가")
        return f"episode-{n}-{slugify(rom)}", label, f"Episode {n} {rom}", f"제{n}화 {ko}"
    mt = re.fullmatch(r"(.+?)\s*Ver\.?", label)
    if mt:  # a member's version: "三船栞子 Ver.", "澁谷かのんVer."
        key = match_key(mt.group(1))
        chars = [c for c in imp.ds.characters.values() if c.names.ja and match_key(c.names.ja) == key]
        chars = [c for c in chars if c.project == project] or chars
        if len(chars) == 1 and chars[0].names.rom and chars[0].names.ko:
            c = chars[0]
            return f"{slugify(c.names.rom)}-ver", label, f"{c.names.rom} Ver.", f"{c.names.ko} Ver."  # type: ignore[union-attr]
    if is_latin(label):
        latin = halfwidth(unicodedata.normalize("NFKC", label))
        return slugify(latin), label, latin, latin
    return None


def member_of_version(imp: Any, ver: str | None, project: str) -> list[m.Performer] | None:
    """The member a version names (``三船栞子 Ver.``)."""
    mt = re.fullmatch(r"(.+?)\s*Ver\.?", (ver or "").strip())
    if not mt:
        return None
    key = match_key(mt.group(1))
    chars = [c for c in imp.ds.characters.values() if c.names.ja and match_key(c.names.ja) == key]
    chars = [c for c in chars if c.project == project] or chars
    return [m.Performer(character=chars[0].id)] if len(chars) == 1 else None


# --- import -----------------------------------------------------------------------------


def _fandom_for(tracks: list[list[FandomTrack]], disc: int, pos: int, pr: Printed) -> FandomTrack | None:
    """The Fandom line of a track: the one at the same place when its title is the printed one, else the
    line with that title anywhere on the album (the wiki leaves out or adds a track now and then)."""
    def same(ft: FandomTrack) -> bool:
        keys = {match_key(pr.base), match_key(pr.base + pr.tail)}
        return bool(ft.ja and (match_key(read_title(ft.ja).base) in keys or match_key(ft.ja) in keys)) \
            or match_key(read_title(ft.rom).base) in keys or match_key(ft.rom) in keys
    if disc - 1 < len(tracks) and pos < len(tracks[disc - 1]) and same(tracks[disc - 1][pos]):
        return tracks[disc - 1][pos]
    return next((ft for d in tracks for ft in d if same(ft)), None)


def _song_work(imp: Any, title: str, ft: FandomTrack | None, sung: bool = False) -> m.Work | None:
    """The song a track is: one of the project by its title, or one the Fandom line links (a song of
    another project heard in the episode: μ's 「ユメノトビラ」 in the Aqours anime). A cue that only
    shares its title with a song of elsewhere (「今しかない瞬間を」) is no song; ``sung``: the album prints the
    track as sung (a size, its singers), so a song of another project of the series by that title is it
    (the Aqours theme 「幻日ミステリウム」 on the 幻日のヨハネ soundtrack)."""
    key = match_key(title)
    songs = [w for w in imp.ds.works.values() if w.kind == "song" and match_key(w.title.ja) == key]
    own = [w for w in songs if w.project == imp.spec.project]
    if len(own) == 1:
        return own[0]
    series = [w for w in songs if w.project != "external"]
    if sung and len(series) == 1:  # a song of another project the album prints as sung (its size, its singers)
        return series[0]
    if not ft or not ft.link or not (songs or sung):  # a cue on the song's melody (「未来ハーモニー with YOU」) is a cue
        return None
    link = match_key(re.sub(r"\s*\(song\)$", "", ft.link))
    linked = [w for w in imp.ds.works.values() if w.kind == "song"
              and link in {match_key(w.external_ids.get("fandom") or ""), match_key(w.title.rom or "")}]
    linked = [w for w in linked if w in songs] or linked
    return linked[0] if len(linked) == 1 else None


def _resolver(imp: Any) -> Any:
    from .concerts import Resolver

    if getattr(imp, "_ost_resolver", None) is None:
        imp._ost_resolver = Resolver(imp.ds)
    return imp._ost_resolver


def _singers_printed(imp: Any, p: Any, group_id: str | None, used: str, url: str) -> list[m.Performer] | None:
    """The singers a μ's page prints under a track: an artist (with its members), or characters with
    their voices. A character not in data yet (``女性シンガー(CV.高山みなみ)``) is named in review."""
    if p.artist or p.artists:
        return imp.performers(p, group_id, used)
    out: list[m.Performer] = []
    for name, cv in p.members:
        cid = next((c.id for c in imp.ds.characters.values() if c.names.ja and match_key(c.names.ja) == match_key(name)
                    and c.project == imp.spec.project), None)
        if cid is None:
            cid = imp.resolve("character", name, file=imp.spec.review_file("member"), used_in=used,
                              seed={"names": {"ja": name, "rom": "", "ko": ""}, "source": url})
            if cid is None:
                return None
        if cv:
            pid = imp.resolve("person", cv, file=imp.spec.review_file("person"), used_in=f"CV of {name}", seed={"source": url})
            if pid is None:
                return None
            char = imp.ds.characters[cid]
            if not any(c.person == pid for c in char.casting):
                char.casting.append(m.Casting(person=pid))
                char.evidence.setdefault("casting", m.Evidence(status=m.Status.official, source=url, checked=imp.today))
        out.append(m.Performer(character=cid))
    return out


def _distinct(rec_id: str, perf: list[m.Performer]) -> str:
    """A recording id for the same version sung by others (``START:DASH!!``'s TV size by three, then by
    μ's); a song sung by one member alone is her solo (``ユメノトビラ`` by 桜内梨子: ``riko-sakurauchi-solo``)."""
    names = [slugify(p.ref[1].rsplit("/", 1)[-1]) for p in perf]
    if rec_id == "original" and len(perf) == 1 and perf[0].character:
        return f"{names[0]}-solo"
    return rec_id + "-" + "-".join(names)


def _cue_title(work: m.Work, labels: tuple[str, str, str, str], pr: Printed) -> m.Names:
    _, ja, rom, ko = labels
    if pr.wave:
        dash = re.search(r"[～〜~]", pr.tail)
        d = dash.group(0) if dash else "～"
        return m.Names(ja=f"{work.title.ja} {d}{ja}{d}", rom=f"{work.title.rom} ~{rom}~" if work.title.rom else None,
                       ko=f"{work.title.ko} ~{ko}~" if work.title.ko else None)
    return m.Names(ja=f"{work.title.ja} ({ja})", rom=f"{work.title.rom} ({rom})" if work.title.rom else None,
                   ko=f"{work.title.ko} ({ko})" if work.title.ko else None)


def _song(imp: Any, work: m.Work, pr: Printed, t: Any, ft: FandomTrack | None, ov: dict[str, Any], url: str,
          used: str, group_id: str | None, ct: CatalogTrack | None = None, album: CatalogAlbum | None = None) -> str | None:
    """The recording of a song track (``<work>#<recording>``), or None while names wait for review."""
    project = imp.spec.project
    ver = ov.get("version", (pr.version,))[0] if "version" in ov else pr.version
    labels = None
    if ver:
        labels = (ov["id"], *ov["version"]) if "version" in ov else version_names(imp, ver, project)
        if labels is None:
            imp.report.conflicts.append(f"{work.id}: unhandled soundtrack version {ver!r} on {used}")
            return None
    vocal = [r for r in work.recordings if r.kind == "vocal"]
    base_rec = next((r for r in vocal if r.id == "original"), vocal[0] if vocal else None)
    if pr.off_vocal:  # the instrumental of the version (or of the recording) the album has
        return _off_vocal(imp, work, labels[0] if labels else "original", url, used)
    # singers: an override, the page, the version's member, Fandom, else the recording the version is cut from
    how = None
    perf: list[m.Performer] | None = None
    if "performers" in ov:
        perf, how = [m.Performer(**{k: v}) for k, v in ov["performers"]], ov.get("performers_note", "가창자: 아래 근거")
    elif t.performers and (t.performers.artist or t.performers.artists or t.performers.members) \
            and not (t.performers.members and not t.performers.artist and _artist_named(ct)):
        perf = _singers_printed(imp, t.performers, group_id, used, url)
        if perf is None:
            return None
    elif ct is not None and ct.singers and (cp := catalog_singers(ct.singers)) is not None:
        perf = _singers_printed(imp, cp, group_id, used, album.url if album else url)
        if perf is None:
            return None
        how = f"가창자: 레이블 카탈로그({album.url if album else ''})"
    elif member := member_of_version(imp, ver, project):
        perf, how = member, "가창자: 버전명의 멤버"
    elif ft and ft.by:
        from .fandom import Item

        found, missing = _resolver(imp).performers(Item("song", ft.rom, ft.ja, None, ft.by, ft.by_text), [project])
        if found and not missing:
            perf, how = found, f"가창자: Fandom OST 문서(공식 미게재, 'By: {ft.by_text}')"
        else:
            imp.report.conflicts.append(f"{used}: Fandom singers {ft.by_text!r} not read ({missing}); set OVERRIDES")
    kind = ov.get("kind", "vocal")
    if perf is None and ct is not None and album is not None and any(x.singers for d in album.discs for x in d):
        # the catalog names the singers of every song on the album but this one: an instrumental arrangement
        perf, kind, how = [], "instrumental", "가창 없음: 레이블 카탈로그가 이 앨범의 다른 노래와 달리 가창자를 싣지 않음(연주곡)"
    if perf is None and base_rec is not None and ver is not None:
        perf, how = list(base_rec.performers), f"가창자: 공식 미게재. 이 버전이 줄인 음원({base_rec.id})의 가창자를 따름"
    # credits the page prints (μ's), else a cut is arranged as the recording it is cut from
    printed = {role: imp.credits(names, f"{work.title.ja}: {role}", url) for role, names in t.credits.items()}
    if any(v is None for v in printed.values()):
        return None
    src = m.Evidence(status=m.Status.official, source=url, checked=imp.today)
    lyr, comp = printed.get("lyricist"), printed.get("composer")
    if (lyr or comp) and not work.credits.lyricist and not work.credits.composer:
        work.credits = m.WorkCredits(lyricist=lyr or [], composer=comp or [])
        work.evidence["credits"] = src
    from .importer import ARRANGERS

    arranged = {k: printed.get(k) or [] for k in ARRANGERS}
    cut = ov.get("cut", ver is not None and (bool(_CUT.search(ver)) or member_of_version(imp, ver, project) is not None))
    notes = [n for n in (how,) if n]
    if not any(arranged.values()) and cut and base_rec is not None:
        arranged = {k: [c.model_copy() for c in getattr(base_rec, k)] for k in ARRANGERS}
        notes.append(f"편곡: 공식 미게재. 원곡 음원({base_rec.id})을 줄인 것이라 그 편곡을 따름")
    official = bool(t.credits) and bool(t.performers) and not how
    ev = src if official else m.Evidence(status=m.Status.derived, source=url, checked=imp.today, note="; ".join(notes) or None)
    if labels is None:  # the recording itself (a full song on the album)
        rid = "original"
        rec = next((r for r in work.recordings if r.id == rid), None)
        if rec is not None and perf and rec.performers and perf != rec.performers:
            rid = _distinct(rid, perf)
            rec = next((r for r in work.recordings if r.id == rid), None)
        if rec is None:
            rec = imp._upsert_recording(work, rid, {"performers": perf or [], **arranged, "kind": kind}, ev)
    else:
        rid = labels[0]
        rec = next((r for r in work.recordings if r.id == rid), None)
        if rec is not None and perf and rec.performers != perf:
            rid = _distinct(rid, perf)
            rec = next((r for r in work.recordings if r.id == rid), None)
        if rec is None:
            fields = {"title": _cue_title(work, labels, pr), "version": labels[1], "performers": perf or [], **arranged,
                      "kind": kind}
            rec = imp._upsert_recording(work, rid, fields, ev)
    return f"{work.id}#{rec.id}"


def _artist_named(ct: CatalogTrack | None) -> bool:
    """Whether the catalog credits a track to an artist (``A-RISE (綺羅ツバサ(CV.桜川めぐ)、…)``) where
    the page prints the artist's members only: the artist is the credit."""
    from .importer import Performers

    cp = catalog_singers(ct.singers) if ct is not None and ct.singers else None
    return isinstance(cp, Performers) and bool(cp.artist or cp.artists) and not cp.members


def _off_vocal(imp: Any, work: m.Work, rid: str, url: str, used: str) -> str | None:
    from .importer import ARRANGERS

    rec = next((r for r in work.recordings if r.id == rid), None)
    if rec is None:
        imp.report.conflicts.append(f"{work.id}: Off Vocal of {rid!r} without that recording on {used}")
        return None
    oid = "off-vocal" if rid == "original" else f"{rid}-off-vocal"
    title = rec.title or work.title
    off = {"kind": "off_vocal", "title": m.Names(ja=f"{title.ja} (Off Vocal)", rom=f"{title.rom} (Off Vocal)" if title.rom else None,
                                                  ko=f"{title.ko} (Off Vocal)" if title.ko else None),
           "version": "Off Vocal", "instrumental_of": rid, **{k: [c.model_copy() for c in getattr(rec, k)] for k in ARRANGERS}}
    ev = m.Evidence(status=m.Status.official, source=url, checked=imp.today, note="편곡은 보컬 음원과 같음")
    found = next((r for r in work.recordings if r.id == oid), None) or imp._upsert_recording(work, oid, off, ev)
    return f"{work.id}#{found.id}"


def _find_cue(imp: Any, title: str) -> m.Work | None:
    key = match_key(title)
    return next((w for w in imp.ds.works.values() if w.project == imp.spec.project and w.kind == "bgm"
                 and match_key(w.title.ja) == key), None)


def _cue(imp: Any, pr: Printed, ft: FandomTrack | None, score: list[m.Credit], url: str, used: str,
         ct: CatalogTrack | None = None, album: CatalogAlbum | None = None) -> str | None:
    """The recording of a cue: a bgm work (named in review when new) and its instrumental recording."""
    from .importer import _rom_title

    labels = version_names(imp, pr.version, imp.spec.project) if pr.version else None
    base = _find_cue(imp, pr.base) if labels else None
    title = pr.base if base is not None else pr.base + pr.tail  # a version only of a cue known already
    if base is None:
        base = _find_cue(imp, title)
        labels = None if base is None or match_key(base.title.ja) == match_key(title) else labels
    if base is None:
        rom, whence = "", ""
        if ct is not None and ct.en:  # the catalog's EN title, as the cue's title is taken from the JP one
            en = read_title(ct.en)
            rom, whence = (en.base + en.tail) if title != pr.base or not en.tail else en.base, f"레이블 카탈로그 EN 표기({album.url if album else ''})"
            rom = re.sub(r"\s*\[[^\]]*\]\s*$", "", rom)
            squash = lambda x: re.sub(r"[\s'’-]+", "", x).lower()  # noqa: E731
            if ft and ft.rom and squash(ft.rom) == squash(rom) and ft.rom != rom:
                # the same spelling, run together on the catalog ("Sakurairono Kaze"): the wiki's word breaks,
                # in the case of the series' titles (particles in lower case)
                rom, whence = title_case(ft.rom), f"{whence}의 철자, 띄어쓰기는 Fandom OST 문서"
        elif ft:
            rom, whence = ft.rom, "Fandom OST 문서"
        rom = halfwidth(unicodedata.normalize("NFKC", rom)) if rom else _rom_title(title)
        file = imp.spec.review_file("work")
        seed = {"title": {"ja": title, "rom": rom, "ko": _rom_title(title)}, "source": url}
        item = imp.reviews.item(file, "work", title, seed, used)
        if not item.get("note") and whence and not item.get("ref"):
            item["note"] = f"ja: 공식 페이지. rom: {whence}. ko: 번역안"
        wid = imp.resolve("work", title, file=file, used_in=used, seed=seed)
        if wid is None:
            return None
        base = imp.ds.works[wid]
        if f"work:{wid}" in imp.report.created and not base.recordings:
            base.kind = "bgm"  # type: ignore[assignment]
    else:  # a cue made on an earlier run: its review item still lists this use
        imp.reviews.note_use(imp.spec.review_file("work"), "work", base.title.ja or title, used)
    if base.kind != "bgm":
        imp.report.conflicts.append(f"{used}: cue {title!r} is the song {base.id}")
        return None
    src = m.Evidence(status=m.Status.official, source=url, checked=imp.today)
    if score and not base.credits.composer:
        base.credits = m.WorkCredits(composer=[c.model_copy() for c in score])
        base.evidence["credits"] = src.model_copy(update={"note": "OST의 音楽 크레딧"})
    if labels is None:
        rec = imp._upsert_recording(base, "original", {"kind": "instrumental"}, src)
    else:
        fields = {"kind": "instrumental", "title": _cue_title(base, labels, pr), "version": labels[1]}
        rec = imp._upsert_recording(base, labels[0], fields, src)
    return f"{base.id}#{rec.id}"


def release(imp: Any, obs: Any, group_id: str | None) -> None:
    """Import a soundtrack (``Importer.release`` hands over a release of type ``soundtrack``)."""
    from .importer import CreditName, _rom_title, item_values

    url = obs.url
    obs.title = album_title(obs.title)
    complete = True
    latin_title = halfwidth(unicodedata.normalize("NFKC", obs.title))  # "Notes of School idol days ～Glory～"
    latin = is_latin(obs.title)
    if latin:  # its own rom and ko (D39), not stored
        title_item: dict[str, Any] | None = {"kind": "release", "title": {"ja": obs.title, "rom": obs.title, "ko": obs.title}}
    else:
        seed = latin_title if is_latin(latin_title) else ""
        title_item = imp.reviews.item(imp.spec.review_file("release"), "release", obs.title,
                                      {"title": {"ja": obs.title, "rom": seed, "ko": seed}, "source": url}, obs.page_id)
        try:
            item_values(title_item)
        except (KeyError, ValueError) as e:
            imp.report.pending.append(f"release {obs.title}: {e}")
            complete = False
    score = imp.credits([CreditName(n) for n in obs.score], f"{obs.title}: 音楽", url) if obs.score else []
    if score is None:
        complete = False
    p = obs.performers
    sung = imp.performers(p, group_id, obs.page_id) if (p.artist or p.artists or p.members) else []
    if sung is None:
        complete = False
    album = catalog_album(CATALOG[url]) if url in CATALOG else None
    if album is not None and album.catalog and not any(e.catalog for e in obs.editions):
        from .importer import EditionObs  # the page prints no catalog number; the label's catalog does

        n = max((t.disc for t in obs.tracks), default=1)
        obs.editions = [EditionObs(None, album.catalog, f"{n}CD" if n > 1 else "CD")]
    ftracks = fandom_tracks(fandom_wikitext(FANDOM[url])) if url in FANDOM else []
    placed: list[tuple[int, m.Track]] = []
    pos: dict[int, int] = {}
    for t in obs.tracks:
        i = pos.get(t.disc, 0)
        pos[t.disc] = i + 1
        pr = read_title(t.printed or t.title)
        ct = album.track(t.disc, i) if album else None
        if ct is not None and match_key(read_title(ct.ja).base) != match_key(pr.base):
            ct = next((x for d in album.discs for x in d if match_key(read_title(x.ja).base) == match_key(pr.base)), None)  # type: ignore[union-attr]
        if ct is not None and pr.version is None and (cv := read_title(ct.ja)).version:
            pr.version, pr.wave = cv.version, cv.wave  # "【第1話エンディング主題歌】": the catalog prints its size
        ft = _fandom_for(ftracks, t.disc, i, pr)
        ov = OVERRIDES.get((url, t.disc, t.no), {})
        used = f"{obs.page_id} #{t.disc}-{t.no}"
        heard = pr.version is not None and bool(_CUT.search(pr.version)) or ct is not None and bool(ct.singers)
        work = imp.ds.works[ov["work"]] if "work" in ov else _song_work(imp, pr.base, ft, heard)
        if work is not None and pr.version is None and "BGM" in pr.notes:  # "友情ノーチェンジ（BGM）": the song as a cue
            pr.version = "BGM"
            pr.notes.remove("BGM")
            ov = {"id": "bgm", "version": ("BGM", "BGM", "BGM"), "kind": "instrumental", "cut": False, "performers": [],
                  "performers_note": "공식 페이지의 （BGM）: 곡의 BGM 편곡(가창 없음)", **ov}
        if work is not None and pr.version is None:  # "【第1話エンディング主題歌】": that episode's version
            theme = next((n for n in pr.notes if _THEME.match(n)), None)
            if theme:
                pr.version = theme
                pr.notes.remove(theme)
        if work is None and (t.credits or t.performers or ct is not None and ct.singers):  # sung: a song only here
            rom = read_title(ct.en).base if ct is not None and ct.en else ft.rom if ft else ""
            seed = {"title": {"ja": pr.base, "rom": halfwidth(unicodedata.normalize("NFKC", rom)), "ko": _rom_title(pr.base)},
                    "source": url}
            if "project" in ov:  # a cover of a song from outside the series (D50): a work of external
                item = imp.reviews.item(imp.spec.review_file("work"), "work", pr.base, seed, used)
                if rom and not item.get("ref"):
                    item.setdefault("id", f"{ov['project']}/{slugify(halfwidth(unicodedata.normalize('NFKC', rom)))}")
            wid = imp.resolve("work", pr.base, file=imp.spec.review_file("work"), used_in=used, seed=seed)
            work = imp.ds.works[wid] if wid else None
            if work is not None and "project" in ov:
                work.project = ov["project"]
            if work is None:
                complete = False
                continue
        ref = _song(imp, work, pr, t, ft, ov, url, used, group_id, ct, album) if work is not None \
            else _cue(imp, pr, ft, score or [], url, used, ct, album)
        if ref is None:
            complete = False
            continue
        track = m.Track(no=t.no, recording=ref, note=", ".join(pr.notes) or None)
        if ov.get("as_printed"):  # the album prints the work's title only
            track.title_as_printed = m.Names(ja=pr.base, rom=work.title.rom, ko=work.title.ko)  # type: ignore[union-attr]
        if "printed" in ov:
            track.title_as_printed = m.Names(ja=ov["printed"][0], rom=ov["printed"][1], ko=ov["printed"][2])
        placed.append((t.disc, track))
    if not complete:
        imp.report.skipped.append(f"{obs.page_id} {obs.title}: waiting for names")
        return
    credit = [m.Performer(person=c.person) for c in score or []] + (sung or [])
    imp._upsert_release(obs, [(None, placed)], credit, title_item)
    rel = next(r for r in imp.ds.releases.values() if r.links.get("official") == url)
    if latin and rel.evidence.get("title") is not None and rel.evidence["title"].status == m.Status.draft:
        rel.title = m.Names(ja=obs.title)
        del rel.evidence["title"]
