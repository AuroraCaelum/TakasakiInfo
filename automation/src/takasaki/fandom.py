"""Love Live! Fandom concert pages (DESIGN.md §6.1, §7.7 ②, D47): the set lists.

The wiki has no set lists of its own structure, but its concert pages write them one way:

    ==Set Lists==
    ===PIA ARENA MM===
    {{Liella Tab|<tabber>
    Day 1=
    #'''Opening'''
    #[[GOING UP]] by [[Liella!]]
    #[[Mizuiro no Sunday]] (水色のSunday) by [[Keke Tang]]
    |-|
    Day 2=
    ...

A section is a stop (its venue or city), a tab a performance (``Day 1``, ``Day 2 (Night)``), an item
a song — the linked article, the Japanese title in brackets when it is not Latin, the singers after
``by`` — or a bold marker (``'''MC'''``, ``'''ENCORE'''``). Pages are read through the MediaWiki API
(``action=parse&prop=wikitext``) and cached; the dates and venues are not here (the pages write them in
prose) but in the schedule table (``automation/concerts/schedule.yaml``).
"""

from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass, field, replace

API = "https://love-live.fandom.com/api.php"
CATEGORY = "Category:Live_Concerts"


@dataclass
class Item:
    kind: str  # "song" or a marker type: mc, video, encore, double_encore, talk, other
    title: str = ""  # the linked article (the song's Fandom title) or the marker's text
    ja: str | None = None  # the Japanese title in brackets
    version: str | None = None  # text between the link and the brackets ("～What a Wonderful Dream!! Ver.～")
    singers: list[str] = field(default_factory=list)
    by: str = ""  # the text after "by", unsplit: "Ruri&To" is one unit, not two singers
    linked: bool = False  # the title links an article: a song the wiki knows
    raw: str = ""


@dataclass
class Tab:
    section: str | None  # the stop's heading ("PIA ARENA MM", "Nagoya"), None for a page without sections
    name: str  # "Day 1", "Day 2 (Night)", "" for a single list
    items: list[Item]


def page_url(title: str) -> str:
    return "https://love-live.fandom.com/wiki/" + urllib.parse.quote(title.replace(" ", "_"), safe="!~()'*:/,&")


def wikitext_url(title: str) -> str:
    return API + "?" + urllib.parse.urlencode({"action": "parse", "page": title, "prop": "wikitext", "format": "json",
                                               "redirects": 1})


def category_url() -> str:
    return API + "?" + urllib.parse.urlencode({"action": "query", "list": "categorymembers", "cmtitle": CATEGORY,
                                               "cmlimit": 500, "format": "json"}, safe=":")


def parse_response(text: str) -> str:
    """The wikitext of an ``action=parse`` answer."""
    return json.loads(text)["parse"]["wikitext"]["*"]


# markers: the bold items of a set list, by what they say (D47)
MARKERS = [
    (re.compile(r"double\s*encore|w\s*encore|wアンコール", re.I), "double_encore"),
    (re.compile(r"encore|アンコール", re.I), "encore"),
    (re.compile(r"\bMC\b|talk corner|トーク", re.I), "mc"),
    (re.compile(r"talk|drama|ドラマ|corner|コーナー|skit|reading|朗読", re.I), "talk"),
    (re.compile(r"opening|intermission|video|movie|animation|animated|vtr|interlude|幕間|映像|overture", re.I), "video"),
]


def marker_type(text: str) -> str:
    return next((t for pat, t in MARKERS if pat.search(text)), "other")


_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def _unlink(text: str) -> str:
    return _LINK.sub(lambda m: m.group(2) or m.group(1), text).replace("'''", "").replace("''", "").strip()


_NOTE = re.compile(r"\s*[(（]([^()（）]*\b(?:version|ver\.?|medley|cover|arrange|remix|edit|acoustic|a cappella)\b[^()（）]*)[)）]\s*$", re.I)


def _singers(text: str) -> tuple[list[str], str | None]:
    """The singers after ``by``, and a note after them (``(short version)``). ``Liella! (Kanon Shibuya,
    …)`` names the group with its members of the time: the group is the singer."""
    text = re.sub(r"<[^>]+>", "", text).strip()
    note = None
    if nm := _NOTE.search(text):
        text, note = text[:nm.start()], nm.group(1).strip()
    text = re.sub(r"\s*[(（][^()（）]*[)）]\s*$", "", _unlink(text))  # the group's members in brackets
    parts = re.split(r",\s*(?:and\s+)?|\s+and\s+|\s*&\s*(?=[A-Z])|\s*×\s*", text)
    return [p.strip().strip(".") for p in parts if p.strip()], note


def _template(text: str) -> tuple[list[str], str]:
    """The arguments of the template that starts ``text`` (``{{Nihongo|EN|JA|…}}``) and what follows it."""
    depth, i, args, cur = 0, 0, [], ""
    while i < len(text):
        two = text[i:i + 2]
        if two in ("{{", "[["):
            depth += 1
            if depth > 1:
                cur += two
            i += 2
            continue
        if two in ("}}", "]]"):
            depth -= 1
            if depth == 0:
                args.append(cur)
                return [a.strip() for a in args[1:]], text[i + 2:]
            cur += two
            i += 2
            continue
        if text[i] == "|" and depth == 1:
            args.append(cur)
            cur = ""
        else:
            cur += text[i]
        i += 1
    return [], text


_WIKIPEDIA = re.compile(r"\{\{\s*w\s*\|([^{}|]*)(?:\|([^{}|]*))?\}\}")  # {{w|article|label}}, a link to Wikipedia
# "Shine!! Short Ver.", "Rat A Tat!!! TV Size"
_SIZE_VERSION = re.compile(r"(.+?)\s+((?:Short|TV|Game|Movie|Full)\s*(?:size|Ver\.?)(?:\s*Ver\.?)?)", re.I)


def _closed(title: str) -> str:
    """A title whose closing bracket the wiki left out: ``Hajimari no Asa (Main Theme``."""
    return title + ")" * (title.count("(") - title.count(")")) if title.count("(") > title.count(")") else title


def parse_item(line: str) -> Item | None:
    text = re.sub(r"^[#*:]+\s*", "", line).strip()  # "#*" is a song of a medley
    text = re.sub(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>|<br\s*/?>", "", text).strip()
    text = _WIKIPEDIA.sub(lambda mt: mt.group(2) or mt.group(1), text)
    text = re.sub(r"^\d+(?=\[\[)", "", text)  # "#3[[Guilty Eyes Fever]]": a stray digit before the link
    if not text:
        return None
    if re.match(r"\{\{\s*[Nn]ihongo\s*\|", text):
        args, rest = _template(text)
        if not args:
            return Item("other", _unlink(text), raw=line)
        lm = _LINK.search(args[0])
        linked = lm is not None
        title = _closed(lm.group(1).strip() if lm else _unlink(args[0]))
        ja = _unlink(args[1]) if len(args) > 1 and args[1] else None
        if ja and " / " in ja and _unlink(args[0]).count(" / ") == ja.count(" / "):  # two songs in one item (split_medley)
            title = _unlink(args[0])
        if args[0].startswith("'''") and not re.search(r"\s+by\s+", rest):  # a marker: {{Nihongo|'''Drama'''|ドラマ}}
            return Item(marker_type(title), title, ja, raw=line)
    elif m := _LINK.match(text):
        title, rest, ja, linked = m.group(1).strip(), text[m.end():], None, True
    elif text.startswith("'''") or not re.search(r"\s+by\s+", text):
        bold = re.fullmatch(r"'''(.+?)'''\s*(.*)", text)
        label = _unlink(bold.group(1) if bold else text).rstrip(":")
        return Item(marker_type(label), label, raw=line)
    else:  # a song without an article: "#Song (歌) by X"
        title, rest, ja, linked = "", text, None, False
    by = ""
    size = None
    if re.search(r"\s+by\s+", rest):
        rest, by = re.split(r"\s+by\s+", rest, maxsplit=1)
    if not title:  # the title is the text before "by"
        jm = re.search(r"[(（]([^()（）]*[^\x00-\x7f][^()（）]*)[)）]\s*$", rest)
        title, ja, rest = _unlink(rest[:jm.start()] if jm else rest), (jm.group(1).strip() if jm else None), ""
        if sm := _SIZE_VERSION.fullmatch(title):
            title, size = sm.group(1), sm.group(2)
    elif ja is None and (jm := re.search(r"[(（]([^()（）]*[^\x00-\x7f][^()（）]*)[)）]", rest)):  # "[[X]] (日本語)"
        ja, rest = jm.group(1).strip(), rest[:jm.start()] + rest[jm.end():]
    version = _unlink(rest).strip(" -–") or size
    if version and (vm := re.fullmatch(r"[(（](.+)[)）]", version)):
        version = vm.group(1).strip()
    singers, note = _singers(by)
    if note:
        version = f"{version}, {note}" if version else note
    return Item("song", title, ja, version, singers, _unlink(re.sub(r"<[^>]+>", "", by)), linked, line)


_SHOW = re.compile(r"(?:noon|evening|day|night|matinee|soir[ée]e|afternoon|morning|(?:\d+(?:st|nd|rd|th)|first|second|third) "
                   r"(?:show|performance|part|session)|[12]部|昼|夜)\b", re.I)


def parse_setlists(wikitext: str) -> list[Tab]:
    """The tabs of the page's set list sections, in order. A set list section is a heading ``Set Lists``
    (``Set List``, ``Set Lists: Japan``); its subsections are the stops. Under another heading
    (``==μ's Fan Meeting In Taipei==`` / ``===Set Lists===``) that heading is the stop."""
    tabs: list[Tab] = []
    section: str | None = None
    tab: Tab | None = None
    region: int | None = None  # the level of the set list heading we are in
    parents: dict[int, str] = {}
    base = ""  # the name of the tab whose shows a bold "Noon:" line splits
    for raw in wikitext.split("\n"):
        line = raw.strip()
        if hm := re.fullmatch(r"(={2,6})\s*(.+?)\s*=+", line):
            level, text = len(hm.group(1)), _unlink(hm.group(2))
            parents = {k: v for k, v in parents.items() if k < level}
            parents[level] = text
            if region is not None and level <= region:
                region = None
            if region is None and re.match(r"Set[ -]?[Ll]ists?\b", text):
                region, section, tab = level, (parents.get(level - 1) if level > 2 else None), None
            elif region is not None:
                section, tab = text, None
            base = ""
            continue
        if region is None:
            continue
        line = re.sub(r"^\{\{[^|{}]*\|\s*<tabber>\s*", "", line)  # "{{Liella Tab|<tabber>"
        line = line.replace("<tabber>", "").replace("</tabber>", "").strip()
        if line in ("}}", "|-|", ""):
            if line == "|-|":
                tab = None
            continue
        if line.startswith("|-|"):
            line = line[3:].strip()
            tab = None
        if tm := re.fullmatch(r"([^#=|{}<]{1,60}?)\s*=\s*", line):
            tab = Tab(section, tm.group(1).strip(), [])
            base = tab.name
            tabs.append(tab)
            continue
        if (sm := re.fullmatch(r"'''([^']{1,30}?):?'''", line)) and _SHOW.match(sm.group(1)):
            # one tab, two shows: "Day 2=" / "'''Noon:'''" … / "'''Evening:'''" … are "Day 2 (Noon)" and "Day 2 (Evening)"
            name = f"{base} ({sm.group(1).strip()})" if base else sm.group(1).strip()
            if tab is None or tab.items:
                tab = Tab(section, name, [])
                tabs.append(tab)
            else:
                tab.name = name
            continue
        if line.startswith("#"):
            item = parse_item(line)
            if item is None:
                continue
            if tab is None:
                tab = Tab(section, "", [])
                tabs.append(tab)
            tab.items += split_medley(item)
    return [t for t in tabs if t.items]


def split_medley(it: Item) -> list[Item]:
    """``{{Nihongo|[[Private Wars]] / Zetsubou|Private Wars / 絶望}}``: two songs played as one item, each
    with the item's singers. A title with one ``/`` and no Japanese one to match stays a song."""
    titles, jas = it.title.split(" / "), (it.ja or "").split(" / ")
    if it.kind != "song" or len(titles) < 2 or len(titles) != len(jas):
        return [it]
    return [replace(it, title=t.strip(), ja=j.strip()) for t, j in zip(titles, jas)]


def nihongo_title(wikitext: str) -> tuple[str | None, str | None]:
    """(English, Japanese) of the page's first {{Nihongo|'''English'''|日本語|…}}."""
    m = re.search(r"\{\{[Nn]ihongo\|\s*'''(.+?)'''\s*\|([^|}]+)", wikitext)
    return (m.group(1).strip(), m.group(2).strip()) if m else (None, None)
