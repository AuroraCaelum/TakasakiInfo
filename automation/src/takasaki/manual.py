"""Releases entered by hand (D53): the ones no official music page lists, read from a curated file.

Fan club CD sets, Blu-ray bonus CDs, advance-ticket and store CDs, digital-only releases: their facts
come from the label's catalog, the project's news and Blu-ray pages, the label's distribution
metadata, or (where nothing official prints them) MusicBrainz and Fandom. The file
(``automation/manual/releases.yaml``) writes each release as the official pages would, so the
importer reads it like a page: titles as printed (``X（Off Vocal）``, ``X（高海千歌 Solo Ver.）``),
singers as a ``歌：`` line, credits as a credit line. Names not in the dictionary go to the project's
``new-names`` review files, as for an official page.

An entry::

    - project: liella                # the project whose importer settings (review files, legacy file) apply
      source: https://…              # the page the release is cited to (its official link)
      status: established            # the grade of that source; established: 공식 미게재 (default official)
      note: "…"                      # what the evidence note says (which source gives what)
      title: アイコトバ！
      title_rom: …                   # drafts for a title that is not made of song titles (optional; else review)
      title_ko: …
      date: 2024-07-26
      type: single
      artist: Liella!                # the release's artist as printed (optional)
      cross: [aqours, liella]        # the projects whose characters may sing on it (a cross-series release)
      editions: [{label: 【プレミアコース盤】, catalog: LAPE-1003, media: CD+3BD, date: 2024-07-26}]   # date: its own day
      smartlink: https://lnk.to/…    # optional
      legacy: false                  # a link source only, without rows in the legacy files (optional)
      # no tracks/discs: a CD whose track list was never published (D54); it has no legacy rows either
      tracks:                        # one disc; or discs: [{tracks: […]}, …]
        - {title: アイコトバ！, singers: Liella!, credits: 作詞：宮嶋淳子 作曲・編曲：大畑拓也}
        - アイコトバ！（Off Vocal）
        - {title: …, recording: nijigasaki/tokimeki-runners#off-vocal}   # a recording in data, named directly
        - {title: 青空Jumping Heart, singers: Aqours, live: {concert: aqours/aqours-finale, date: 2025-06-21},
           version: ラブライブ！サンシャイン!! Aqours Finale LoveLive! ～永久stage～ Ver.}   # a live take as printed (D54)
        - {title: 明けましておめでとう!, drama: true, rom: Akemashite Omedetou!, ko: 새해 복 많이 받으세요!}   # a new title's drafts
        - {title: Dye the sky., work: external/dye-the-sky}   # a work named directly
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import importlib
from pathlib import Path
from typing import Any

from . import model as m
from .importer import EditionObs, Performers, ReleaseObs, Report, Site, TrackObs, page_id, parse_credit_line
from .store import Dataset

ADAPTERS = {"muse": "muse", "aqours": "aqours", "nijigasaki": "nijigasaki", "liella": "liella",
            "hasunosora": "hasunosora", "musical": "musical", "yohane": "yohane", "ikizulive": "ikizulive"}


def _singers(text: str | None) -> Performers | None:
    from .sitepage import _singers as read

    return read(text) if text else None


def _track(t: Any, no: int, disc: int) -> TrackObs:
    if isinstance(t, str):
        t = {"title": t}
    obs = TrackObs(int(t.get("no", no)), t["title"], disc=disc, drama=bool(t.get("drama")), printed=t["title"])
    obs.performers = _singers(t.get("singers"))
    obs.recording = t.get("recording")
    if t.get("live"):
        obs.live = m.LiveOf(**t["live"])
        obs.version = t.get("version")
    obs.work = t.get("work")
    if t.get("credits"):
        obs.credits = parse_credit_line(t["credits"])
    return obs


def observation(e: dict[str, Any]) -> ReleaseObs:
    discs = e.get("discs") or ([{"tracks": e["tracks"]}] if e.get("tracks") else [])  # none: no track list published
    tracks = [_track(t, n, d.get("disc", i)) for i, d in enumerate(discs, 1) for n, t in enumerate(d["tracks"], 1)]
    editions = [EditionObs(x.get("label"), x.get("catalog"), x.get("media")) for x in e.get("editions") or []]
    links = {"smartlink": e["smartlink"]} if e.get("smartlink") else {}
    perf = _singers(e.get("artist")) or Performers(None, None)
    date = e["date"] if isinstance(e["date"], dt.date) else dt.date.fromisoformat(str(e["date"]))
    return ReleaseObs(e["source"], "", e["title"], date, perf, editions, tracks, links, type=e.get("type"),
                      urls=[e["source"], *e.get("sources", [])])


def import_manual(ds: Dataset, entries: list[dict[str, Any]], review_dir: Path, today: dt.date) -> Report:
    from .importer import import_site

    report = Report()
    by_project: dict[str, list[dict[str, Any]]] = {}
    for e in entries:
        by_project.setdefault(e["project"], []).append(e)
    for project, es in by_project.items():
        mod = importlib.import_module(f".{ADAPTERS[project]}", __package__)
        site = Site([], sorted((observation(e) for e in es), key=lambda r: (r.release_date, r.url)), "")
        cross = {**mod.SPEC.cross, **{page_id(e["source"]): e["cross"] for e in es if e.get("cross")}}  # other series' singers
        spec = dataclasses.replace(mod.SPEC, lineups_from_site=False, skip={}, cross=cross)  # no member page: the lineups stay
        _title_drafts(review_dir, spec, es)
        r = import_site(ds, site, review_dir, today, spec, partial=True)
        for e in es:
            _settle(ds, e, today)
        for k in ("created", "updated", "pending", "conflicts", "skipped"):
            getattr(report, k).extend(x for x in getattr(r, k) if x not in getattr(report, k))
    return report


def _title_drafts(review_dir: Path, spec: Any, entries: list[dict[str, Any]]) -> None:
    """An entry's ``title_rom``/``title_ko`` (researched drafts) seed the review item of its title, which the
    importer asks for when the title is not made of song titles; an item filled in already is kept."""
    from .official import NameReviews

    reviews = NameReviews(review_dir, spec.project, partial=True)
    for e in entries:
        if e.get("title_rom") or e.get("title_ko"):
            seed = {"title": {"ja": e["title"], "rom": e.get("title_rom") or "", "ko": e.get("title_ko") or ""},
                    "source": e["source"]}
            it = reviews.item(spec.review_file("release"), "release", e["title"], seed, None)
            if e.get("title_note") and not it.get("note"):
                it["note"] = e["title_note"]
        for t in [t for d in e.get("discs") or [{"tracks": e.get("tracks") or []}] for t in d["tracks"]]:
            if isinstance(t, dict) and (t.get("rom") or t.get("ko")):  # a new title's drafts (a drama track)
                seed = {"title": {"ja": t["title"], "rom": t.get("rom") or "", "ko": t.get("ko") or ""}, "source": e["source"]}
                it = reviews.item(spec.review_file("work"), "work", t["title"], seed, None)
                if not it.get("note"):
                    it["note"] = t.get("title_note") or "rom: 헵번식, ko: 번역안"
    reviews.save()


def _settle(ds: Dataset, e: dict[str, Any], today: dt.date) -> None:
    """What the importer cannot know of a hand entry: the grade of its source and the evidence note,
    for the release and for the credits it was the first to give; a link-source release leaves the
    legacy files."""
    rel = next((r for r in ds.releases.values() if r.links.get("official") == e["source"]), None)
    if rel is None:
        return
    status = m.Status(e.get("status", "official"))
    note = e.get("note")
    if status != m.Status.official and not (note or "").startswith("공식 미게재"):
        note = "공식 미게재" + (f": {note}" if note else "")  # what W16 asks of a value no official page gives
    for key in ("tracks", "editions"):
        ev = rel.evidence.get(key)
        if ev is not None and ev.source == e["source"]:
            rel.evidence[key] = ev.model_copy(update={"status": status, "note": note or ev.note})
    for x, ed in zip(e.get("editions") or [], rel.editions):  # an edition released on another day (a reissue)
        if x.get("date"):
            ed.release_date = x["date"] if isinstance(x["date"], dt.date) else dt.date.fromisoformat(str(x["date"]))
    if (e.get("legacy") is False or not (e.get("tracks") or e.get("discs"))) and rel.legacy.albums:  # no rows to list
        rel.legacy.albums = []
        if ds.layout:
            for f in ds.layout.albums.values():
                f.entries = [x for x in f.entries if x.release != rel.id]
    if status == m.Status.official and not e.get("credits_note"):
        return
    cnote = e.get("credits_note") or note
    if status != m.Status.official and cnote and not cnote.startswith("공식 미게재"):
        cnote = f"공식 미게재: {cnote}"
    for d in rel.discs:
        for t in d.tracks:
            work, rec = ds.recording(t.recording)
            for ent in (work, rec):
                ev = ent.evidence.get("credits")
                if ev is not None and ev.source == e["source"] and ev.status == m.Status.official:
                    ent.evidence["credits"] = ev.model_copy(update={"status": status if status != m.Status.official else ev.status,
                                                                    "note": cnote or ev.note})
