"""Official project sites (DESIGN.md §6.1, §7.2 ②): a polite fetcher with snapshots.

The site answers 403 to clients that identify as bots, so requests carry a browser user agent
(approved for this project on 2026-10-18). To stay polite: one request every ``interval`` seconds or
more, ``/common/`` (disallowed by robots.txt) is never fetched, and every page is cached under
``automation/.cache/official/`` so a page is downloaded once per ``max_age``. A page saved by hand
into ``automation/inbox/<project>/`` takes precedence (the manual path of §7.2 ②). Raw HTML is never
committed (D9); only the facts parsed from it are.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from . import model as m
from .text import join_ja_name, join_kana_name, match_key

BASE = "https://www.lovelive-anime.jp"
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/130.0.0.0 Safari/537.36")
DISALLOWED = ("/common/",)


@dataclass
class Page:
    url: str
    html: str
    fetched_at: float
    sha256: str
    from_inbox: bool = False


class Fetcher:
    def __init__(self, cache_dir: Path, inbox_dir: Path | None = None, interval: float = 3.0,
                 max_age: float = 7 * 24 * 3600, offline: bool = False) -> None:
        self.cache_dir, self.inbox_dir = cache_dir, inbox_dir
        self.interval, self.max_age, self.offline = interval, max_age, offline
        self._last = 0.0

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / (hashlib.sha1(url.encode()).hexdigest() + ".html")

    def _inbox_path(self, url: str) -> Path | None:
        if not self.inbox_dir:
            return None
        q = urllib.parse.urlparse(url)
        name = (q.path.strip("/").replace("/", "_") or "index") + (("_" + q.query.replace("=", "-").replace("&", "_")) if q.query else "")
        path = self.inbox_dir / f"{name}.html"
        return path if path.exists() else None

    def get(self, url: str, *, fresh: bool = False) -> Page:
        url = urllib.parse.urljoin(BASE, url)
        path = urllib.parse.urlparse(url).path
        if any(path.startswith(d) for d in DISALLOWED):
            raise PermissionError(f"{url}: disallowed by robots.txt")
        inbox = self._inbox_path(url)
        if inbox:
            html = inbox.read_text(encoding="utf-8")
            return Page(url, html, inbox.stat().st_mtime, hashlib.sha256(html.encode()).hexdigest(), from_inbox=True)
        cached = self._cache_path(url)
        if cached.exists() and not fresh and time.time() - cached.stat().st_mtime < self.max_age:
            html = cached.read_text(encoding="utf-8")
            return Page(url, html, cached.stat().st_mtime, hashlib.sha256(html.encode()).hexdigest())
        if self.offline:
            if cached.exists():
                html = cached.read_text(encoding="utf-8")
                return Page(url, html, cached.stat().st_mtime, hashlib.sha256(html.encode()).hexdigest())
            raise FileNotFoundError(f"{url}: not cached (offline)")
        wait = self._last + self.interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ja"})
        with urllib.request.urlopen(req, timeout=30) as res:
            html = res.read().decode(res.headers.get_content_charset() or "utf-8")
        self._last = time.monotonic()
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(html, encoding="utf-8")
        return Page(url, html, time.time(), hashlib.sha256(html.encode()).hexdigest())


# --- new-names review files (§7.3) ---------------------------------------------------
#
# A name read from an official page that is not in the dictionary yet becomes one item in a
# ``new-names`` review file. Its readings are filled in there (the importer stops at items
# without them), the next import creates the entity with a draft status, and the decision
# ``approve`` writes the values again (edits made in the file win) with the item's status.

HOWTO = (
    "공식 사이트에서 처음 나온 이름. 빈 칸을 채우고 다시 가져오면(takasaki official ikizulive) 초안으로 들어간다. "
    "인명은 family_name/given_name(성·이름)을 채우면 names가 D28 규칙으로 만들어진다(rom은 이름-성, ko는 성-이름). "
    "한 단어 이름(필명 등)은 family_name/given_name을 지우고 names만 채운다. names에 값을 적으면 그 값이 우선한다. "
    "근거는 공식 페이지가 먼저이고, 공식에 없는 값(ko, 읽기)만 나무위키 등에서 가져온다(D36). "
    "status는 승인 후 근거 등급(official|established|derived). 확인이 끝나면 decision: approve 후 takasaki review apply."
)


def _blank_names(seed: dict[str, Any] | None) -> dict[str, str]:
    return {"ja": "", "rom": "", "ko": ""} | {k: v for k, v in (seed or {}).items() if v is not None}


def _seeded(kind: str, printed: str, seed: dict[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = {"kind": kind, "printed": printed}
    if kind in ("work", "release"):
        item["title"] = _blank_names(seed.get("title")) | {"ja": (seed.get("title") or {}).get("ja") or printed}
    elif "names" in seed and not seed.get("family_name"):
        item["names"] = _blank_names(seed["names"])
    else:
        item["family_name"] = _blank_names(seed.get("family_name"))
        item["given_name"] = _blank_names(seed.get("given_name"))
        item["names"] = _blank_names({})
    for key in ("native_script", "artist_kind"):
        if seed.get(key):
            item[key] = seed[key]
    item["status"] = seed.get("status", "derived")
    item["source"] = seed.get("source", "")
    item["note"] = ""
    return item


class NameReviews:
    """The ``new-names`` review files of one project, keyed by file name under ``review_dir``."""

    def __init__(self, review_dir: Path, project: str) -> None:
        self.dir, self.project = review_dir, project
        self.docs: dict[str, dict[str, Any]] = {}
        self.dirty: set[str] = set()

    def doc(self, file: str) -> dict[str, Any]:
        if file not in self.docs:
            path = self.dir / file
            doc = YAML(typ="safe").load(path.read_text(encoding="utf-8")) if path.exists() else None
            self.docs[file] = doc or {"type": "new-names", "project": self.project, "decision": "", "how": HOWTO, "items": []}
        return self.docs[file]

    def item(self, file: str, kind: str, printed: str, seed: dict[str, Any], used_in: str | None) -> dict[str, Any]:
        doc = self.doc(file)
        key = match_key(printed, person=kind == "person")
        for it in doc["items"]:
            if it.get("kind") == kind and match_key(str(it.get("printed")), person=kind == "person") == key:
                break
        else:
            it = _seeded(kind, printed, seed)
            doc["items"].append(it)
            self.dirty.add(file)
        if used_in and used_in not in it.setdefault("used_in", []):
            it["used_in"].append(used_in)
            self.dirty.add(file)
        return it

    def save(self) -> list[Path]:
        from .store import _to_node, _yaml

        out = []
        for file in sorted(self.dirty | {f for f, d in self.docs.items() if any(i.get("ref") for i in d["items"])}):
            buf = io.StringIO()
            _yaml().dump(_to_node(self.docs[file]), buf)
            path = self.dir / file
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists() or path.read_text(encoding="utf-8") != buf.getvalue():
                path.write_text(buf.getvalue(), encoding="utf-8")
                out.append(path)
        return out


def _names(d: dict[str, Any] | None) -> m.Names | None:
    vals = {k: str(v).strip() for k, v in (d or {}).items() if v not in (None, "")}
    return m.Names(**vals) if vals else None


def item_values(item: dict[str, Any]) -> dict[str, Any]:
    """Entity fields from a review item; raises ValueError naming what is still missing."""
    kind = item["kind"]
    if kind in ("work", "release"):
        title = _names(item.get("title"))
        missing = [k for k in ("ja", "rom", "ko") if not (title and getattr(title, k))]
        if missing:
            raise ValueError(f"fill title.{'/'.join(missing)}")
        return {"title": title}
    fam, giv = _names(item.get("family_name")), _names(item.get("given_name"))
    composed: dict[str, str] = {}
    if fam and giv:
        if fam.ja and giv.ja:
            composed["ja"] = join_ja_name(fam.ja, giv.ja)
        if fam.kana and giv.kana:
            composed["kana"] = join_kana_name(fam.kana, giv.kana)
        if fam.rom and giv.rom:
            composed["rom"] = f"{giv.rom} {fam.rom}"  # given-family (D4)
        if fam.ko and giv.ko:
            composed["ko"] = f"{fam.ko} {giv.ko}"
    explicit = _names(item.get("names"))
    names = m.Names(**(composed | (explicit.model_dump(exclude_none=True) if explicit else {})))
    missing = [k for k in ("ja", "rom", "ko") if not getattr(names, k)]
    if missing:
        raise ValueError(f"fill {'/'.join(missing)} (family_name/given_name or names)")
    out: dict[str, Any] = {"names": names}
    if kind in ("person", "character"):
        out |= {"family_name": fam, "given_name": giv}
    if kind == "person" and item.get("native_script"):
        out["native_script"] = item["native_script"]
    return out


def approve_names(ds: Any, doc: dict[str, Any], today: dt.date) -> str:
    """Decision ``approve`` on a new-names file: write each item's values and status."""
    done = []
    for it in doc.get("items", []):
        ref = it.get("ref")
        if not ref:
            raise ValueError(f"{it.get('printed')!r} has not been imported yet; run the importer first")
        kind, _, ident = str(ref).partition(":")
        ent = ds.table(kind)[ident]
        values = item_values(it)
        if kind == "release":
            values["title"] = m.Names(ja=values["title"].ja, rom=values["title"].rom, ko=values["title"].ko)
        for k, v in values.items():
            setattr(ent, k, v)
        key = "title" if kind in ("work", "release") else "names"
        ent.evidence[key] = m.Evidence(status=m.Status(it.get("status") or "derived"), source=it.get("source") or None,
                                       checked=today, note=it.get("note") or None)
        if values.get("family_name"):
            ent.evidence["name_parts"] = m.Evidence(status=m.Status.derived, note="성·이름 분리: 리뷰에서 확인 (D28)")
        done.append(str(ref))
    return f"approved {len(done)} names"
