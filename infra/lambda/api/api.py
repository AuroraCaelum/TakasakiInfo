"""Queries of the v1 API (DESIGN.md §10.6) over the SQLite release, standard library only.

``handler.py`` downloads the database and hands each request to ``dispatch``. ``ROUTES`` lists every
endpoint with its parameters and the JSON Schema of its ``data``: ``dispatch`` checks requests against
it, and ``takasaki build`` writes ``openapi.json`` from it.

Ids are the ids of the data (``aqours/sakanakanandaka``), slashes and all; a recording id's ``#`` is
sent as ``%23``. Responses are ``{"data": …, "meta": {…}}``; errors are ``{"error", "message"}``.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
import unicodedata
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, unquote

PREFIX = "/api/v1"
DEFAULT_LIMIT, MAX_LIMIT, MAX_RANDOM = 20, 100, 10
JST = dt.timezone(dt.timedelta(hours=9))  # "today" for birthdays and line-ups is the day in Japan

# path segment -> entity kind; search results of equal rank are listed in this order
TYPES = {"works": "work", "releases": "release", "persons": "person", "characters": "character",
         "artists": "artist", "concerts": "concert", "venues": "venue", "recordings": "recording",
         "cities": "city", "projects": "project"}
TITLED = {"work", "recording", "release", "concert"}  # named by `title`; the others by `name`
LANGS = ("ja", "kana", "rom", "ko")
# the model's enums (a test keeps them equal to model.py)
WORK_KINDS = ("song", "bgm", "drama", "other")
RECORDING_KINDS = ("vocal", "off_vocal", "instrumental", "drama", "other")
RELEASE_TYPES = ("single", "album", "mini_album", "digital_single", "bd_bonus", "compilation", "soundtrack",
                 "drama_cd", "radio_cd", "live_album", "box_set", "live_video", "unclassified")
RELEASE_STATUSES = ("announced", "released", "verified")
CONCERT_STATUSES = ("announced", "performed", "settled", "confirmed")
ARTIST_KINDS = ("group", "unit", "solo", "cross_unit", "collab", "special", "unclassified")
CREDIT_ROLES = ("lyricist", "composer", "arranger", "strings_arranger", "brass_arranger")
MOODS = ("upbeat", "slow", "bright", "wistful")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# --- match keys (the same as takasaki.text.match_key, which built the search index) ---------------

_MATCH_DROP = re.compile(r"[\s・·☆★♡♥♪〜～~\-‐–—_!！?？.,，、。:：;；'‘’\"“”()（）\[\]［］【】「」『』/／&＆+＋*＊]+")


def match_key(s: str | None, *, person: bool = False) -> str:
    if not s:
        return ""
    k = _MATCH_DROP.sub("", unicodedata.normalize("NFKC", s).casefold())
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in k) if person else k


# --- parameters -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Param:
    name: str
    kind: str  # string, integer, date (YYYY-MM-DD), month_day (MM-DD), month (1-12), enum
    description: str
    enum: tuple[str, ...] = ()
    minimum: int | None = None
    maximum: int | None = None
    default: Any = None
    required: bool = False

    def parse(self, raw: str) -> Any:
        bad = ApiError(400, "bad_parameter", f"`{self.name}`: {self.description}")
        if self.kind == "integer":
            if not re.fullmatch(r"\d+", raw):
                raise bad
            n = int(raw)
            if (self.minimum is not None and n < self.minimum) or (self.maximum is not None and n > self.maximum):
                raise bad
            return n
        if self.kind == "enum":
            if raw not in self.enum:
                raise ApiError(400, "bad_parameter", f"`{self.name}` is one of {', '.join(self.enum)}")
            return raw
        if self.kind == "date":
            try:
                return dt.date.fromisoformat(raw).isoformat() if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw) else _raise(bad)
            except ValueError:
                raise bad from None
        if self.kind == "month_day":
            try:
                return dt.date(2000, int(raw[:2]), int(raw[3:])).strftime("%m-%d") if re.fullmatch(r"\d{2}-\d{2}", raw) \
                    else _raise(bad)
            except ValueError:
                raise bad from None
        if self.kind == "month":
            if not re.fullmatch(r"\d{1,2}", raw) or not 1 <= int(raw) <= 12:
                raise bad
            return f"{int(raw):02d}"
        if not raw:
            raise bad
        return raw

    def schema(self) -> dict[str, Any]:
        s: dict[str, Any] = {"integer": {"type": "integer"}, "date": {"type": "string", "format": "date"},
                             "month_day": {"type": "string", "pattern": r"^\d{2}-\d{2}$"},
                             "month": {"type": "integer", "minimum": 1, "maximum": 12},
                             "enum": {"type": "string", "enum": list(self.enum)}}.get(self.kind, {"type": "string"})
        if self.minimum is not None:
            s["minimum"] = self.minimum
        if self.maximum is not None:
            s["maximum"] = self.maximum
        if self.default is not None:
            s["default"] = self.default
        return s


def _raise(e: Exception) -> Any:
    raise e


LIMIT = Param("limit", "integer", f"Items per page, 1-{MAX_LIMIT}.", minimum=1, maximum=MAX_LIMIT, default=DEFAULT_LIMIT)
CURSOR = Param("cursor", "string", "`meta.next` of the previous page.")
INCLUDE = Param("include", "enum", "`evidence`: keep the source and status of every value.", enum=("evidence",))
PROJECT = Param("project", "string", "Project id (`liella`).")
PAGED = (LIMIT, CURSOR)


# --- reading ----------------------------------------------------------------------------------------


def _names(con: sqlite3.Connection, entity: str) -> dict[str, str]:
    field = "title" if entity.split(":", 1)[0] in TITLED else "name"
    got = dict(con.execute("SELECT lang, value FROM label WHERE entity = ? AND field = ?", (entity, field)).fetchall())
    return {lang: got[lang] for lang in LANGS if lang in got}


def ref(con: sqlite3.Connection, kind: str, ident: str | None) -> dict[str, Any] | None:
    """A reference as the views write it: `{"ref": "work:<id>", "names": {…}}`."""
    if ident is None:
        return None
    entity = f"{kind}:{ident}"
    return {"ref": entity, "names": _names(con, entity)}


def _strip(o: Any) -> Any:
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if k != "evidence"}
    if isinstance(o, list):
        return [_strip(v) for v in o]
    return o


def document(con: sqlite3.Connection, entity: str, include: str | None = None) -> Any:
    row = con.execute("SELECT body FROM document WHERE entity = ?", (entity,)).fetchone()
    if row is None:
        return None
    doc = json.loads(zlib.decompress(row[0]))
    return doc if include == "evidence" else _strip(doc)


def exists(con: sqlite3.Connection, kind: str, ident: str) -> bool:
    return con.execute("SELECT 1 FROM document WHERE entity = ?", (f"{kind}:{ident}",)).fetchone() is not None


def _page(con: sqlite3.Connection, sql: str, args: list[Any], limit: int, cursor: str | None) -> tuple[list[tuple], dict]:
    if cursor is not None and not re.fullmatch(r"\d+", cursor):
        raise ApiError(400, "bad_parameter", "`cursor`: use `meta.next` of the previous page")
    offset = int(cursor or 0)
    total = con.execute(f"SELECT COUNT(*) FROM ({sql})", args).fetchone()[0]
    rows = con.execute(f"{sql} LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
    nxt = str(offset + limit) if offset + limit < total else None
    return rows, {"count": total, "limit": limit, "next": nxt}


def _in_project(kind: str, column: str) -> str:
    """SQL condition: the entity in `column` belongs to the project given as the next argument."""
    if kind == "character":
        return f"{column} IN (SELECT id FROM character WHERE project = ?)"
    if kind == "recording":  # a work is in its own project and in every project that sings it (D74)
        return (f"{column} IN (SELECT r.id FROM recording r WHERE 'work:' || r.work IN "
                "(SELECT entity FROM entity_project WHERE project = ?))")
    if kind == "project":
        return f"{column} = ?"
    return f"'{kind}:' || {column} IN (SELECT entity FROM entity_project WHERE project = ?)"


def _belongs(con: sqlite3.Connection, kind: str, ident: str, project: str) -> bool:
    """People, venues and cities belong to no project."""
    if kind in ("person", "venue", "city"):
        return False
    return con.execute(f"SELECT {_in_project(kind, '?')}", (ident, project)).fetchone()[0] == 1


def _today() -> dt.date:
    return dt.datetime.now(JST).date()


# --- endpoints --------------------------------------------------------------------------------------


def search(con: sqlite3.Connection, *, q: str, type: str | None = None, project: str | None = None,
           limit: int = DEFAULT_LIMIT, cursor: str | None = None) -> tuple[Any, dict]:
    keys = {k for k in (match_key(q), match_key(q, person=True)) if k}
    if not keys:
        raise ApiError(400, "bad_parameter", "`q` has no letters or digits to search for")
    best: dict[str, tuple[int, int, str]] = {}
    for k in keys:  # every key character that GLOB treats specially (* ? [ ]) is dropped by match_key
        for entity, text, key in con.execute("SELECT entity, text, key FROM search WHERE key GLOB ?", (f"*{k}*",)):
            rank = 0 if key == k else 1 if key.startswith(k) else 2
            cand = (rank, len(key), text)
            if entity not in best or cand < best[entity]:
                best[entity] = cand
    order = {kind: i for i, kind in enumerate(TYPES.values())}
    hits = []
    for entity, (rank, _, text) in best.items():
        kind, ident = entity.split(":", 1)
        if type and kind != TYPES[type]:
            continue
        if project and not _belongs(con, kind, ident, project):
            continue
        hits.append((rank, order[kind], best[entity][1], entity, text))
    hits.sort()
    if cursor is not None and not re.fullmatch(r"\d+", cursor):
        raise ApiError(400, "bad_parameter", "`cursor`: use `meta.next` of the previous page")
    offset = int(cursor or 0)
    page = hits[offset:offset + limit]
    data = [{**ref(con, *e.split(":", 1)), "type": e.split(":", 1)[0], "id": e.split(":", 1)[1], "matched": text}
            for *_, e, text in page]
    return data, {"count": len(hits), "limit": limit,
                  "next": str(offset + limit) if offset + limit < len(hits) else None}


def _lister(kind: str) -> Callable[..., tuple[Any, dict]]:
    def run(con: sqlite3.Connection, *, limit: int = DEFAULT_LIMIT, cursor: str | None = None,
            include: str | None = None, **filters: Any) -> tuple[Any, dict]:
        where, args = [], []
        order = "x.id"
        if filters.get("project"):
            where.append(_in_project(kind, "x.id"))
            args.append(filters["project"])
        for f in ("kind", "type", "status"):
            if filters.get(f):
                where.append(f"x.{f} = ?")
                args.append(filters[f])
        if kind == "release":
            order = "x.release_date IS NULL, x.release_date, x.id"
            if filters.get("from"):
                where.append("x.release_date >= ?")
                args.append(filters["from"])
            if filters.get("to"):
                where.append("x.release_date <= ?")
                args.append(filters["to"])
        if kind == "concert":
            order = "(SELECT MIN(date) FROM performance p WHERE p.concert = x.id), x.id"
            if filters.get("year"):
                where.append("x.id IN (SELECT concert FROM performance WHERE substr(date, 1, 4) = ?)")
                args.append(str(filters["year"]))
        if kind == "venue" and filters.get("city"):
            where.append("x.city = ?")
            args.append(filters["city"])
        sql = f"SELECT x.id FROM {kind} x" + (" WHERE " + " AND ".join(where) if where else "") + f" ORDER BY {order}"
        rows, meta = _page(con, sql, args, limit, cursor)
        return [document(con, f"{kind}:{r[0]}", include) for r in rows], meta
    return run


def detail(kind: str) -> Callable[..., tuple[Any, dict]]:
    def run(con: sqlite3.Connection, ident: str, *, include: str | None = None) -> tuple[Any, dict]:
        return document(con, f"{kind}:{ident}", include), {}
    return run


def work_recordings(con: sqlite3.Connection, ident: str, *, include: str | None = None) -> tuple[Any, dict]:
    rows = con.execute("SELECT id FROM recording WHERE work = ? ORDER BY rowid", (ident,)).fetchall()
    data = [document(con, f"recording:{r[0]}", include) for r in rows]
    return data, {"count": len(data)}


def recording_tracks(con: sqlite3.Connection, ident: str) -> tuple[Any, dict]:
    rows = con.execute(
        "SELECT t.id FROM track t JOIN release r ON r.id = t.release "
        "LEFT JOIN edition e ON e.release = t.release AND e.id = t.edition "
        "WHERE t.recording = ? ORDER BY COALESCE(e.release_date, r.release_date) IS NULL, "
        "COALESCE(e.release_date, r.release_date), t.id", (ident,)).fetchall()
    data = [document(con, f"track:{r[0]}") for r in rows]
    return data, {"count": len(data)}


def person_credits(con: sqlite3.Connection, ident: str, *, role: str | None = None, limit: int = DEFAULT_LIMIT,
                   cursor: str | None = None) -> tuple[Any, dict]:
    sql = ("SELECT c.role, c.work, CASE WHEN c.target = c.work THEN NULL ELSE c.target END, "
           "(SELECT MIN(r.release_date) FROM track t JOIN recording rc ON rc.id = t.recording "
           " JOIN release r ON r.id = t.release WHERE rc.work = c.work AND r.release_date IS NOT NULL) AS first "
           "FROM v_person_credits c WHERE c.person = ?" + (" AND c.role = ?" if role else "")
           + " ORDER BY first IS NULL, first, c.work, c.role, c.target")
    rows, meta = _page(con, sql, [ident, role] if role else [ident], limit, cursor)
    data = [{"role": r, "work": ref(con, "work", w), "recording": ref(con, "recording", rec), "first_release": first}
            for r, w, rec, first in rows]
    return data, meta


def work_performances(con: sqlite3.Connection, ident: str, *, limit: int = DEFAULT_LIMIT,
                      cursor: str | None = None) -> tuple[Any, dict]:
    sql = ("SELECT p.date, p.label, p.concert, p.stop, st.venue, si.seq, si.recording "
           "FROM setlist_item si JOIN performance p ON p.id = si.performance "
           "JOIN stop st ON st.concert = p.concert AND st.id = p.stop "
           "WHERE si.work = ? ORDER BY p.date, p.id, si.seq")
    rows, meta = _page(con, sql, [ident], limit, cursor)
    data = [{"date": d, "label": lab, "concert": ref(con, "concert", c), "stop": s, "venue": ref(con, "venue", v),
             "position": seq, "recording": rec} for d, lab, c, s, v, seq, rec in rows]
    return data, meta


def concert_setlist(con: sqlite3.Connection, ident: str, *, date: str | None = None) -> tuple[Any, dict]:
    doc = document(con, f"concert:{ident}")
    shows = []
    for stop in doc.get("stops", []):
        for p in stop.get("performances", []):
            if date and p["date"] != date:
                continue
            items = []
            for i, it in enumerate(p.get("setlist", []), 1):
                item = {"position": i, "type": it.get("type", "song"), "work": ref(con, "work", it.get("work"))}
                for k in ("recording", "version", "label", "title_raw"):
                    if it.get(k):
                        item[k] = it[k]
                if it.get("performers"):
                    item["performers"] = [_performer_ref(con, x) for x in it["performers"]]
                items.append(item)
            shows.append({"date": p["date"], "label": p.get("label"), "stop": stop["id"],
                          "venue": ref(con, "venue", stop.get("venue")), "setlist": items})
    shows.sort(key=lambda s: s["date"])
    if date and not shows:
        raise ApiError(404, "not_found", f"concert {ident} has no show on {date}")
    return shows, {"count": len(shows)}


def _performer_ref(con: sqlite3.Connection, p: dict[str, Any]) -> dict[str, Any]:
    kind = next(k for k in ("artist", "character", "person") if p.get(k))
    out = ref(con, kind, p[kind])
    if p.get("role"):
        out["role"] = ref(con, "character", p["role"])
    return out


def _active(start: str | None, until: str | None, at: str) -> bool:
    return (start is None or start <= at) and (until is None or at <= until)


def artist_lineup(con: sqlite3.Connection, ident: str, *, at: str | None = None) -> tuple[Any, dict]:
    at = at or _today().isoformat()
    data = []
    seen = set()
    for character, start, until in con.execute(
            'SELECT character, "from", until FROM lineup_member WHERE artist = ? ORDER BY rowid', (ident,)):
        if character in seen or not _active(start, until, at):
            continue
        seen.add(character)
        cast = [{"person": ref(con, "person", p), "from": f, "until": u} for p, f, u in con.execute(
            'SELECT person, "from", until FROM casting WHERE character = ? ORDER BY rowid', (character,))
            if _active(f, u, at)]
        data.append({"character": ref(con, "character", character), "from": start, "until": until, "cast": cast})
    return data, {"count": len(data), "at": at}


def birthdays(con: sqlite3.Connection, *, date: str | None = None, month: str | None = None,
              type: str | None = None) -> tuple[Any, dict]:
    if date and month:
        raise ApiError(400, "bad_parameter", "give `date` or `month`, not both")
    if not date and not month:
        date = _today().strftime("%m-%d")
    pattern = date or f"{month}-__"
    data = []
    for kind, table in (("character", "character"), ("person", "person")):
        if type and TYPES[type] != kind:
            continue
        rows = con.execute(f"SELECT id, birthday FROM {table} WHERE birthday IS NOT NULL "
                           "AND substr(birthday, -5) LIKE ?", (pattern,)).fetchall()
        for ident, bday in rows:
            item = {**ref(con, kind, ident), "type": kind, "id": ident, "birthday": bday}
            if kind == "character":
                item["project"] = con.execute("SELECT project FROM character WHERE id = ?", (ident,)).fetchone()[0]
            data.append(item)
    data.sort(key=lambda x: (x["birthday"][-5:], x["type"], x["id"]))
    return data, {"count": len(data), **({"date": date} if date else {"month": month})}


def random_works(con: sqlite3.Connection, *, project: str | None = None, kind: str = "song", mood: str | None = None,
                 count: int = 1, include: str | None = None) -> tuple[Any, dict]:
    where, args = ["w.kind = ?"], [kind]
    if project:
        where.append(_in_project("work", "w.id"))
        args.append(project)
    if mood:
        where.append("',' || (SELECT mood FROM recording r WHERE r.id = w.representative) || ',' LIKE ?")
        args.append(f"%,{mood},%")
    rows = con.execute(f"SELECT w.id FROM work w WHERE {' AND '.join(where)} ORDER BY random() LIMIT ?",
                       [*args, count]).fetchall()
    data = [document(con, f"work:{r[0]}", include) for r in rows]
    return data, {"count": len(data)}


# --- routes -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Route:
    key: tuple[str, ...]
    path: str  # as in openapi.json
    summary: str
    params: tuple[Param, ...]
    data: dict[str, Any]  # JSON Schema of `data`
    fn: Callable[..., tuple[Any, dict]] | None  # None: served by handler.py
    cache: bool = True  # False: `Cache-Control: no-store`
    tag: str = "data"


def _ref_schema(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def _list(name: str) -> dict[str, Any]:
    return {"type": "array", "items": _ref_schema(name)}


SCHEMA_OF = {"work": "Work", "release": "Release", "person": "Person", "character": "Character", "artist": "Artist",
             "concert": "Concert", "venue": "Venue", "recording": "RecordingView", "city": "City", "project": "Project"}
LIST_FILTERS: dict[str, tuple[Param, ...]] = {
    "works": (PROJECT, Param("kind", "enum", "Kind of work.", enum=WORK_KINDS)),
    "recordings": (PROJECT, Param("kind", "enum", "Kind of recording.", enum=RECORDING_KINDS)),
    "releases": (PROJECT, Param("type", "enum", "Type of release.", enum=RELEASE_TYPES),
                 Param("status", "enum", "Status of the release.", enum=RELEASE_STATUSES),
                 Param("from", "date", "Released on or after this day (YYYY-MM-DD)."),
                 Param("to", "date", "Released on or before this day (YYYY-MM-DD).")),
    "concerts": (PROJECT, Param("status", "enum", "Status of the concert.", enum=CONCERT_STATUSES),
                 Param("year", "integer", "A show was held in this year.", minimum=1000, maximum=9999)),
    "characters": (PROJECT,),
    "artists": (PROJECT, Param("kind", "enum", "Kind of artist.", enum=ARTIST_KINDS)),
    "venues": (Param("city", "string", "City id (`tokyo`)."),),
}


def _routes() -> list[Route]:
    out = [
        Route(("health",), f"{PREFIX}/health", "Status and version of the live data", (),
              _ref_schema("Health"), None, cache=False, tag="meta"),
        Route(("openapi.json",), f"{PREFIX}/openapi.json", "This document", (), {"type": "object"}, None, tag="meta"),
        Route(("search",), f"{PREFIX}/search", "Search names and titles in every language", (
            Param("q", "string", "Text to find: Japanese, romaji, Korean or a credited alias, in part or whole.",
                  required=True),
            Param("type", "enum", "Only this type.", enum=tuple(TYPES)), PROJECT, *PAGED),
            _list("SearchHit"), search),
        Route(("birthdays",), f"{PREFIX}/birthdays", "Characters and people born on a day or in a month", (
            Param("date", "month_day", "Day as MM-DD; default today in Japan."),
            Param("month", "month", "Month, 1-12, instead of a day."),
            Param("type", "enum", "Only characters or only people.", enum=("characters", "persons"))),
            _list("Birthday"), birthdays),
        Route(("random",), f"{PREFIX}/random", "Random works", (
            PROJECT, Param("kind", "enum", "Kind of work.", enum=WORK_KINDS, default="song"),
            Param("mood", "enum", "Mood label of the work's representative recording.", enum=MOODS),
            Param("count", "integer", f"How many, 1-{MAX_RANDOM}.", minimum=1, maximum=MAX_RANDOM, default=1),
            INCLUDE), _list("Work"), random_works, cache=False),
    ]
    for seg, kind in TYPES.items():
        out.append(Route(("list", seg), f"{PREFIX}/{seg}", f"List {seg}",
                         (*LIST_FILTERS.get(seg, ()), *PAGED, INCLUDE), _list(SCHEMA_OF[kind]), _lister(kind)))
        out.append(Route(("detail", seg), f"{PREFIX}/{seg}/{{id}}", f"One {kind}", (INCLUDE,),
                         _ref_schema(SCHEMA_OF[kind]), detail(kind)))
    out += [
        Route(("sub", "works", "recordings"), f"{PREFIX}/works/{{id}}/recordings", "Recordings of a work",
              (INCLUDE,), _list("RecordingView"), work_recordings),
        Route(("sub", "works", "performances"), f"{PREFIX}/works/{{id}}/performances",
              "Shows a work was performed at, oldest first", PAGED, _list("Performance"), work_performances),
        Route(("sub", "recordings", "tracks"), f"{PREFIX}/recordings/{{id}}/tracks",
              "Tracks a recording is on, oldest release first", (), _list("TrackView"), recording_tracks),
        Route(("sub", "persons", "credits"), f"{PREFIX}/persons/{{id}}/credits",
              "Works a person wrote or arranged, oldest first",
              (Param("role", "enum", "Only this role.", enum=CREDIT_ROLES), *PAGED), _list("PersonCredit"),
              person_credits),
        Route(("sub", "concerts", "setlist"), f"{PREFIX}/concerts/{{id}}/setlist", "Set list of every show",
              (Param("date", "date", "Only the shows of this day (YYYY-MM-DD)."),), _list("Show"), concert_setlist),
        Route(("sub", "artists", "lineup"), f"{PREFIX}/artists/{{id}}/lineup", "Members on a day, with their cast",
              (Param("at", "date", "Day (YYYY-MM-DD); default today in Japan."),), _list("LineupMember"),
              artist_lineup),
    ]
    return out


ROUTES = _routes()
BY_KEY = {r.key: r for r in ROUTES}


def _params(route: Route, query: str) -> dict[str, Any]:
    known = {p.name: p for p in route.params}
    out: dict[str, Any] = {}
    for name, raw in parse_qsl(query, keep_blank_values=True):
        if name not in known:
            raise ApiError(400, "unknown_parameter", f"`{name}` is not a parameter of {route.path}"
                           + (f" (use {', '.join(known)})" if known else ""))
        out[name] = known[name].parse(raw)
    for p in route.params:
        if p.required and p.name not in out:
            raise ApiError(400, "missing_parameter", f"`{p.name}` is required: {p.description}")
    return out


def known(path: str) -> bool:
    """Whether the path can name an endpoint, before the database is opened."""
    if not path.startswith(PREFIX + "/"):
        return False
    first = path[len(PREFIX) + 1:].strip("/").split("/")[0]
    return first in TYPES or (first,) in BY_KEY


def resolve(con: sqlite3.Connection, path: str) -> tuple[Route, str | None]:
    """The route of a path and the id in it."""
    if not path.startswith(PREFIX + "/"):
        raise ApiError(404, "not_found", f"no endpoint {path}")
    segs = [unquote(s) for s in path[len(PREFIX) + 1:].strip("/").split("/")]
    if len(segs) == 1 and (segs[0],) in BY_KEY:
        return BY_KEY[(segs[0],)], None
    if segs[0] not in TYPES:
        raise ApiError(404, "not_found", f"no endpoint {path}")
    seg, rest = segs[0], segs[1:]
    if not rest:
        return BY_KEY[("list", seg)], None
    kind = TYPES[seg]
    if len(rest) >= 2 and ("sub", seg, rest[-1]) in BY_KEY and exists(con, kind, "/".join(rest[:-1])):
        return BY_KEY[("sub", seg, rest[-1])], "/".join(rest[:-1])
    ident = "/".join(rest)
    if exists(con, kind, ident):
        return BY_KEY[("detail", seg)], ident
    raise ApiError(404, "not_found", f"no {kind} {ident}" + (" (send a recording id's # as %23)" if kind == "recording" else ""))


def dispatch(con: sqlite3.Connection, path: str, query: str = "") -> tuple[Route, Any, dict]:
    """Answer a request: its route, `data` and `meta` (without the data version)."""
    route, ident = resolve(con, path)
    if route.fn is None:
        raise ApiError(500, "internal", f"{route.path} is served by the handler")
    params = _params(route, query)  # `from` reaches the release lister through **filters
    fn = route.fn
    data, meta = fn(con, ident, **params) if ident is not None else fn(con, **params)
    return route, data, meta
