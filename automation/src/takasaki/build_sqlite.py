"""SQLite database (DESIGN.md §10.5): the entities of §4 as tables, names and aliases as rows, every
evidence entry, external ids, views for common joins, and a trigram search index.

The database is a build product: rebuilt from ``data/`` every time, never edited. Polymorphic tables
(``label``, ``alias``, ``evidence``, ``external_id``, ``entity_project``) key entities as ``kind:id``.
Trigram search needs three characters; shorter queries use ``LIKE`` on ``label`` (the API does this).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import model as m
from .build_legacy import edition_ids, edition_tracks, main_videos, own_video, release_title
from .build_v1 import V1_FORMAT
from .store import Dataset
from .text import match_key

DERIVED_TITLE = m.Evidence(status=m.Status.derived, note="수록곡 제목 또는 라틴 원문에서 생성 (D39)")

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE project (id TEXT PRIMARY KEY);
CREATE TABLE person (id TEXT PRIMARY KEY, native_script TEXT NOT NULL);
CREATE TABLE character (id TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES project(id));
CREATE TABLE artist (id TEXT PRIMARY KEY, kind TEXT NOT NULL);
CREATE TABLE work (id TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES project(id), kind TEXT NOT NULL);
CREATE TABLE recording (
  id TEXT PRIMARY KEY, work TEXT NOT NULL REFERENCES work(id), kind TEXT NOT NULL, version TEXT,
  instrumental_of TEXT REFERENCES recording(id) DEFERRABLE INITIALLY DEFERRED);
CREATE TABLE release (id TEXT PRIMARY KEY, type TEXT NOT NULL, status TEXT NOT NULL, release_date TEXT, label TEXT);
CREATE TABLE edition (release TEXT NOT NULL REFERENCES release(id), id TEXT NOT NULL, catalog TEXT, release_date TEXT,
  PRIMARY KEY (release, id));
CREATE TABLE track (
  id TEXT PRIMARY KEY, release TEXT NOT NULL REFERENCES release(id), edition TEXT, disc INTEGER NOT NULL,
  position INTEGER NOT NULL, no INTEGER, recording TEXT NOT NULL REFERENCES recording(id), note TEXT,
  UNIQUE (release, edition, disc, position));
CREATE TABLE stream_link (
  track TEXT NOT NULL REFERENCES track(id), platform TEXT NOT NULL, url TEXT NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('own', 'main')), PRIMARY KEY (track, platform));
CREATE TABLE credit (
  target TEXT NOT NULL, role TEXT NOT NULL, seq INTEGER NOT NULL,
  person TEXT REFERENCES person(id), character TEXT REFERENCES character(id), affiliation TEXT, credited_as TEXT,
  CHECK ((person IS NULL) <> (character IS NULL)), PRIMARY KEY (target, role, seq));
CREATE TABLE performer (
  recording TEXT NOT NULL REFERENCES recording(id), seq INTEGER NOT NULL,
  artist TEXT REFERENCES artist(id), character TEXT REFERENCES character(id), person TEXT REFERENCES person(id),
  role TEXT REFERENCES character(id), PRIMARY KEY (recording, seq));
CREATE TABLE lineup_member (
  artist TEXT NOT NULL REFERENCES artist(id), character TEXT NOT NULL REFERENCES character(id),
  "from" TEXT, until TEXT, CHECK ("from" IS NULL OR until IS NULL OR "from" <= until));
CREATE TABLE casting (
  character TEXT NOT NULL REFERENCES character(id), person TEXT NOT NULL REFERENCES person(id),
  "from" TEXT, until TEXT, CHECK ("from" IS NULL OR until IS NULL OR "from" <= until));
CREATE TABLE entity_project (entity TEXT NOT NULL, project TEXT NOT NULL REFERENCES project(id), PRIMARY KEY (entity, project));
CREATE TABLE city (id TEXT PRIMARY KEY);
CREATE TABLE venue (id TEXT PRIMARY KEY, city TEXT REFERENCES city(id));
CREATE TABLE concert (id TEXT PRIMARY KEY, status TEXT NOT NULL);
CREATE TABLE stop (concert TEXT NOT NULL REFERENCES concert(id), id TEXT NOT NULL, city TEXT REFERENCES city(id),
  venue TEXT REFERENCES venue(id), label TEXT, PRIMARY KEY (concert, id));
CREATE TABLE performance (id INTEGER PRIMARY KEY, concert TEXT NOT NULL, stop TEXT NOT NULL, date TEXT NOT NULL, label TEXT,
  FOREIGN KEY (concert, stop) REFERENCES stop(concert, id));
CREATE TABLE setlist_item (
  performance INTEGER NOT NULL REFERENCES performance(id), seq INTEGER NOT NULL, type TEXT NOT NULL,
  work TEXT REFERENCES work(id), recording TEXT REFERENCES recording(id), label TEXT, title_raw TEXT,
  PRIMARY KEY (performance, seq));
CREATE TABLE label (
  entity TEXT NOT NULL, field TEXT NOT NULL, lang TEXT NOT NULL, value TEXT NOT NULL, status TEXT,
  PRIMARY KEY (entity, field, lang));
CREATE TABLE alias (entity TEXT NOT NULL, text TEXT NOT NULL, kind TEXT NOT NULL);
CREATE TABLE evidence (entity TEXT NOT NULL, field TEXT NOT NULL, status TEXT NOT NULL, source TEXT, checked TEXT, note TEXT,
  PRIMARY KEY (entity, field));
CREATE TABLE external_id (entity TEXT NOT NULL, system TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (entity, system));
CREATE VIRTUAL TABLE search USING fts5(entity UNINDEXED, text, key, tokenize = 'trigram');

CREATE INDEX track_recording ON track(recording);
CREATE INDEX credit_person ON credit(person);
CREATE INDEX performer_artist ON performer(artist);
CREATE INDEX performer_character ON performer(character);
CREATE INDEX setlist_work ON setlist_item(work);

-- the legacy row shape with ids, titles in every language and the link (§10.5)
CREATE VIEW v_track_flat AS
SELECT t.id, t.release, t.edition, t.disc, t.position, t.no, r.release_date, r.status, t.recording, rec.work,
       COALESCE(rt_ja.value, wt_ja.value) AS title_ja, COALESCE(rt_rom.value, wt_rom.value) AS title_rom,
       COALESCE(rt_ko.value, wt_ko.value) AS title_ko, s.url AS youtube_music, s.source AS link_source, t.note
FROM track t
JOIN release r ON r.id = t.release
JOIN recording rec ON rec.id = t.recording
LEFT JOIN label rt_ja ON rt_ja.entity = 'recording:' || t.recording AND rt_ja.field = 'title' AND rt_ja.lang = 'ja'
LEFT JOIN label rt_rom ON rt_rom.entity = 'recording:' || t.recording AND rt_rom.field = 'title' AND rt_rom.lang = 'rom'
LEFT JOIN label rt_ko ON rt_ko.entity = 'recording:' || t.recording AND rt_ko.field = 'title' AND rt_ko.lang = 'ko'
LEFT JOIN label wt_ja ON wt_ja.entity = 'work:' || rec.work AND wt_ja.field = 'title' AND wt_ja.lang = 'ja'
LEFT JOIN label wt_rom ON wt_rom.entity = 'work:' || rec.work AND wt_rom.field = 'title' AND wt_rom.lang = 'rom'
LEFT JOIN label wt_ko ON wt_ko.entity = 'work:' || rec.work AND wt_ko.field = 'title' AND wt_ko.lang = 'ko'
LEFT JOIN stream_link s ON s.track = t.id AND s.platform = 'youtube_music';

-- who wrote what: work-level lyricist/composer (or a recording's override) and recording-level arranger
CREATE VIEW v_person_credits AS
SELECT c.person, c.role, c.target,
       CASE WHEN c.target IN (SELECT id FROM work) THEN c.target ELSE (SELECT work FROM recording WHERE id = c.target) END AS work
FROM credit c WHERE c.person IS NOT NULL;

-- every time a work was performed live
CREATE VIEW v_work_performances AS
SELECT si.work, p.date, p.concert, p.stop, st.venue, p.label AS day_label, si.seq
FROM setlist_item si JOIN performance p ON p.id = si.performance
JOIN stop st ON st.concert = p.concert AND st.id = p.stop
WHERE si.work IS NOT NULL;
"""


def _iso(d: object) -> str | None:
    return d.isoformat() if d else None  # type: ignore[attr-defined]


def build_sqlite(ds: Dataset, path: Path) -> None:
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        con.executescript(SCHEMA)
        _fill(con, ds)
        con.commit()
        bad = con.execute("PRAGMA foreign_key_check").fetchall()
        if bad:
            raise ValueError(f"foreign key violations: {bad[:5]}")
        con.execute("VACUUM")
    finally:
        con.close()


def _fill(con: sqlite3.Connection, ds: Dataset) -> None:
    assert ds.meta is not None
    ins = lambda table, *rows: con.executemany(  # noqa: E731
        f"INSERT INTO {table} VALUES ({', '.join('?' * len(rows[0]))})", rows) if rows else None
    ins("meta", ("schema_version", V1_FORMAT), ("data_schema_version", ds.meta.schema_version),
        ("db_last_update", ds.meta.db_last_update))

    def names(entity: str, field: str, n: m.Names | None, evidence: dict[str, m.Evidence]) -> None:
        if n is None:
            return
        base = evidence.get(field if field != "name" else "names") or evidence.get("title" if field == "title" else "names")
        for lang, value in n.model_dump().items():
            if value:
                ev = evidence.get(f"{'names' if field == 'name' else field}.{lang}") or base
                ins("label", (entity, field, lang, value, ev.status.value if ev else None))
                con.execute("INSERT INTO search VALUES (?, ?, ?)", (entity, value, match_key(value, person=field == "name")))

    def common(entity: str, ent: object) -> None:
        for f, ev in getattr(ent, "evidence", {}).items():
            ins("evidence", (entity, f, ev.status.value, ev.source, _iso(ev.checked), ev.note))
        for system, value in (getattr(ent, "external_ids", None) or {}).items():
            ins("external_id", (entity, system, value))

    ins("project", *[(p,) for p in sorted(ds.projects)])
    for p in ds.projects.values():
        names(f"project:{p.id}", "name", p.names, p.evidence)
        common(f"project:{p.id}", p)
    for p in ds.persons.values():
        ins("person", (p.id, p.native_script))
        e = f"person:{p.id}"
        names(e, "name", p.names, p.evidence)
        names(e, "family_name", p.family_name, {})
        names(e, "given_name", p.given_name, {})
        ins("alias", *[(e, a.text, a.kind) for a in p.aliases])
        for a in p.aliases:
            con.execute("INSERT INTO search VALUES (?, ?, ?)", (e, a.text, match_key(a.text, person=True)))
        common(e, p)
    for c in ds.characters.values():
        ins("character", (c.id, c.project))
        e = f"character:{c.id}"
        names(e, "name", c.names, c.evidence)
        names(e, "family_name", c.family_name, {})
        names(e, "given_name", c.given_name, {})
        common(e, c)
    for a in ds.artists.values():
        ins("artist", (a.id, a.kind))
        e = f"artist:{a.id}"
        names(e, "name", a.names, a.evidence)
        ins("entity_project", *[(e, p) for p in a.projects])
        common(e, a)
    for c in ds.characters.values():
        ins("casting", *[(c.id, x.person, _iso(x.from_), _iso(x.until)) for x in c.casting])
    for a in ds.artists.values():
        for lu in a.lineups:
            ins("lineup_member", *[(a.id, mem, _iso(lu.from_), _iso(lu.until)) for mem in lu.members])

    def credits(target: str, role: str, cs: list[m.Credit]) -> None:
        for i, c in enumerate(cs, 1):
            aff = c.affiliation if isinstance(c.affiliation, str) or c.affiliation is None else c.affiliation.ja
            ins("credit", (target, role, i, c.person, c.character, aff, c.role.ja if c.role else None))

    for w in ds.works.values():
        ins("work", (w.id, w.project, w.kind))
        names(f"work:{w.id}", "title", w.title, w.evidence)
        common(f"work:{w.id}", w)
        credits(w.id, "lyricist", w.credits.lyricist)
        credits(w.id, "composer", w.credits.composer)
        for r in w.recordings:
            rid = f"{w.id}#{r.id}"
            ins("recording", (rid, w.id, r.kind, r.version, f"{w.id}#{r.instrumental_of}" if r.instrumental_of else None))
            names(f"recording:{rid}", "title", r.title, r.evidence)
            common(f"recording:{rid}", r)
            credits(rid, "arranger", r.arranger)
            if r.credits_override:
                credits(rid, "lyricist", r.credits_override.lyricist)
                credits(rid, "composer", r.credits_override.composer)
            ins("performer", *[(rid, i, p.artist, p.character, p.person, p.role) for i, p in enumerate(r.performers, 1)])

    mains = main_videos(ds)
    for rel in ds.releases.values():
        ins("release", (rel.id, rel.type, rel.status, _iso(rel.release_date), rel.label))
        e = f"release:{rel.id}"
        title, filled = release_title(ds, rel)
        names(e, "title", title, rel.evidence | {f"title.{lang}": DERIVED_TITLE for lang in filled})
        ins("entity_project", *[(e, p) for p in rel.projects])
        common(e, rel)
        ins("edition", *[(rel.id, ed.id, ed.catalog, _iso(ed.release_date)) for ed in rel.editions])
        for ed in edition_ids(rel):
            for disc, pos, t in edition_tracks(rel, ed):
                tid = f"{rel.id}@{ed or '-'}/{disc}-{pos}"
                ins("track", (tid, rel.id, ed, disc, pos, t.no, t.recording, t.note))
                own = own_video(rel, ed, disc, pos)
                vid = own or mains.get(t.recording)
                if vid:
                    ins("stream_link", (tid, "youtube_music", "https://youtu.be/" + vid, "own" if own else "main"))

    ins("city", *[(c,) for c in ds.cities])
    for c in ds.cities.values():
        names(f"city:{c.id}", "name", c.names, {})
    for v in ds.venues.values():
        ins("venue", (v.id, v.city))
        names(f"venue:{v.id}", "name", v.names, {})
        common(f"venue:{v.id}", v)
    perf_id = 0
    for c in ds.concerts.values():
        ins("concert", (c.id, c.status))
        e = f"concert:{c.id}"
        names(e, "title", c.title, c.evidence)
        ins("entity_project", *[(e, p) for p in c.projects])
        common(e, c)
        for s in c.stops:
            ins("stop", (c.id, s.id, s.city, s.venue, s.label))
            for p in s.performances:
                perf_id += 1
                ins("performance", (perf_id, c.id, s.id, p.date.isoformat(), p.label))
                ins("setlist_item", *[(perf_id, i, it.type, it.work, it.recording, it.label, it.title_raw)
                                      for i, it in enumerate(p.setlist, 1)])
