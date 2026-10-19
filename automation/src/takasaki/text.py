"""String handling shared by the importer, builder and validator.

Display strings are stored exactly as published (NFC only). Match keys are a
lossy normalisation used only to compare strings (DESIGN.md §5.1).
"""

from __future__ import annotations

import re
import unicodedata

_MATCH_DROP = re.compile(r"[\s・·☆★♡♥♪〜～~\-‐–—_!！?？.,，、。:：;；'’\"“”()（）\[\]［］【】「」『』/／&＆+＋*＊]+")  # ~: NFKC turns ～ into ~


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def kata_to_hira(s: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


def match_key(s: str | None, *, person: bool = False) -> str:
    """NFKC → casefold → drop whitespace/punctuation/decoration; for person names also
    fold katakana to hiragana. Never stored or output."""
    if not s:
        return ""
    k = unicodedata.normalize("NFKC", s).casefold()
    k = _MATCH_DROP.sub("", k)
    if person:
        k = kata_to_hira(k)
    return k


def slugify(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def is_latin(s: str) -> bool:
    """True when the string has no kana/kanji/hangul (Latin-native names, DESIGN.md §5.4)."""
    return not re.search(r"[぀-ヿ㐀-鿿가-힯ｦ-ﾟ]", s)


# kana blocks without the katakana middle dot U+30FB, which is punctuation in any script
_KANA = "぀-ヺー-ヿｦ-ﾟ"


def has_kana(s: str | None) -> bool:
    return bool(s) and bool(re.search(f"[{_KANA}]", s))  # type: ignore[arg-type]


def has_kana_or_kanji(s: str | None) -> bool:
    return bool(s) and bool(re.search(f"[{_KANA}㐀-鿿]", s))  # type: ignore[arg-type]


# kanji, including compatibility ideographs (中﨑) and the marks written as part of a kanji name
_KANJI = "㐀-鿿豈-﫿々〆ヶ"


def has_kanji(s: str | None) -> bool:
    return bool(s) and re.search(f"[{_KANJI}]", s) is not None  # type: ignore[arg-type]


def is_all_kanji(s: str | None) -> bool:
    return bool(s) and re.fullmatch(f"[{_KANJI}]+", s) is not None  # type: ignore[arg-type]


def join_ja_name(family: str, given: str) -> str:
    """Japanese name spacing (DESIGN.md §5.2, D28): a space only when both parts are all kanji
    (畑 亜貴, 渡辺 曜); none when one part has kana (光増ハジメ, 中須かすみ). All-kana names follow
    their official notation instead, so this is only the default for them."""
    return f"{family} {given}" if is_all_kanji(family) and is_all_kanji(given) else family + given


def join_kana_name(family: str, given: str) -> str:
    """Name readings always take a space (わたなべ よう)."""
    return f"{family} {given}"


# --- credits ------------------------------------------------------------------

LANGS = ("ja", "rom", "ko")

# cast credited in character: 堀内まり菜（椿 ルリカ役） / Marina Horiuchi(as Rurika Tsubaki) / 호리우치 마리나(츠바키 루리카 역)
_ROLE = {
    "ja": re.compile(r"^(?P<name>.+?)（(?P<role>.+?)役）$"),
    "rom": re.compile(r"^(?P<name>.+?)\(as (?P<role>.+?)\)$"),
    "ko": re.compile(r"^(?P<name>.+?)\((?P<role>.+?) 역\)$"),
}
_AFFILIATION = re.compile(r"^(?P<name>.+?)(?P<space>\s*)\((?P<aff>[^()（）]+)\)$")


def render_credit_name(name: str, lang: str, affiliation: str | None = None, role: str | None = None) -> str:
    if role is not None:
        if lang == "ja":
            return f"{name}（{role}役）"
        if lang == "rom":
            return f"{name}(as {role})"
        return f"{name}({role} 역)"
    if affiliation:
        return f"{name}({affiliation})"  # DESIGN.md D10: no space before the parenthesis
    return name


def parse_credit(parts: dict[str, str]) -> tuple[dict[str, str], str | None, dict[str, str] | None, bool]:
    """Split one credited name (given in ja/rom/ko) into (names, affiliation, role, normalised).

    Parsing is accepted only when every language parses the same way and rendering
    reproduces the input. The one tolerated difference is the space before an
    affiliation parenthesis, which D10 removes; ``normalised`` reports that case.
    """
    role_m = {lang: _ROLE[lang].match(parts[lang]) for lang in LANGS}
    if all(role_m.values()):
        names = {lang: role_m[lang]["name"] for lang in LANGS}  # type: ignore[index]
        role = {lang: role_m[lang]["role"] for lang in LANGS}  # type: ignore[index]
        if all(render_credit_name(names[l], l, role=role[l]) == parts[l] for l in LANGS):
            return names, None, role, False
    aff_m = {lang: _AFFILIATION.match(parts[lang]) for lang in LANGS}
    if all(aff_m.values()):
        affs = {aff_m[l]["aff"] for l in LANGS}  # type: ignore[index]
        if len(affs) == 1:
            aff = affs.pop()
            names = {lang: aff_m[lang]["name"] for lang in LANGS}  # type: ignore[index]
            normalised = any(aff_m[l]["space"] for l in LANGS)  # type: ignore[index]
            return names, aff, None, normalised
    return dict(parts), None, None, False


# --- titles -------------------------------------------------------------------

# trailing "(… Ver.)", "(Off Vocal)", "(instrumental)", "(Album Version)"; DESIGN.md §4.2
_VERSION_SUFFIX = re.compile(
    r"^(?P<base>.+?)\s*[(（](?P<ver>[^()（）]*(?:[Vv]er\.?|[Vv]ersion|Off Vocal|[Ii]nstrumental))[)）]\s*$"
)


def split_version(title: str) -> tuple[str, str | None]:
    m = _VERSION_SUFFIX.match(title)
    if not m:
        return title, None
    return m["base"], m["ver"]


def recording_kind(title_ja: str, note: str) -> str:
    if "Drama Part" in note:
        return "drama"
    if "Off Vocal" in title_ja:
        return "off_vocal"
    if re.search(r"[(（]instrumental[)）]", title_ja, re.I):
        return "instrumental"
    return "vocal"


_NOTE_VERSION = re.compile(r"(?:^|,\s*)([^,]*?\bVer\.?)\s*(?=,|$)")


def note_version(note: str) -> str | None:
    """Version label carried only in the legacy note column (e.g. ``Kanon Ver.``)."""
    m = _NOTE_VERSION.search(note)
    return m.group(1).strip() if m else None
