"""The API's queries (infra/lambda/api/api.py) over a database built from the real data/ tree (§10.6)."""

import json
import re
import sqlite3
import typing
from pathlib import Path

import pytest

from takasaki import model as m
from takasaki.build_sqlite import build_sqlite
from takasaki.openapi import OUTPUT, api_module, openapi
from takasaki.store import load_dataset
from takasaki.text import match_key

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def api():
    return api_module()


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "takasakiinfo.sqlite"
    build_sqlite(load_dataset(ROOT / "data"), path)
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    yield c
    c.close()


def call(api, con, path, query=""):
    _, data, meta = api.dispatch(con, "/api/v1/" + path, query)
    return data, meta


def error(api, con, path, query=""):
    with pytest.raises(api.ApiError) as e:
        api.dispatch(con, "/api/v1/" + path, query)
    return e.value


def test_match_key_is_the_one_that_built_the_index(api, con):
    for (text,) in con.execute("SELECT text FROM search"):
        assert api.match_key(text) == match_key(text)
        assert api.match_key(text, person=True) == match_key(text, person=True)


def test_enums_follow_the_model(api):
    lit = lambda t: tuple(typing.get_args(t))
    assert api.WORK_KINDS == lit(m.WorkKind)
    assert api.RECORDING_KINDS == lit(m.RecordingKind)
    assert api.RELEASE_TYPES == lit(m.ReleaseType)
    assert api.ARTIST_KINDS == lit(m.ArtistKind)
    assert api.RELEASE_STATUSES == lit(m.Release.model_fields["status"].annotation)
    assert api.CONCERT_STATUSES == lit(m.Concert.model_fields["status"].annotation)
    from takasaki.audio import MOODS
    assert api.MOODS == tuple(MOODS)


def test_search_in_every_language(api, con):
    for q in ("snow hal", "Snow halation", "スノーハレーション"):
        data, _ = call(api, con, "search", f"q={q}&type=works")
        assert data[0]["id"] == "muse/snow-halation", q
    data, _ = call(api, con, "search", "q=하타 아키")
    assert data[0]["ref"] == "person:aki-hata" and data[0]["names"]["ja"] == "畑 亜貴"
    data, meta = call(api, con, "search", "q=かのん&project=liella")
    assert data[0]["ref"] == "character:liella/kanon-shibuya"
    assert all(h["type"] in ("work", "release", "character", "artist", "concert", "recording") for h in data)
    assert meta["count"] >= len(data)
    assert error(api, con, "search", "q=!!").code == "bad_parameter"
    assert error(api, con, "search").code == "missing_parameter"


def test_detail_and_evidence(api, con):
    work, _ = call(api, con, "works/muse/snow-halation")
    assert work["id"] == "muse/snow-halation" and "evidence" not in work
    assert all("evidence" not in r for r in work["recordings"])
    full, _ = call(api, con, "works/muse/snow-halation", "include=evidence")
    assert "evidence" in full
    rec, _ = call(api, con, "recordings/muse/snow-halation%23original")
    assert rec["work"] == "muse/snow-halation" and rec["title"]["ja"] == "Snow halation"
    assert error(api, con, "works/muse/no-such-song").status == 404
    assert "%23" in error(api, con, "recordings/muse/snow-halation").message


def test_lists_page_and_filter(api, con):
    data, meta = call(api, con, "works", "project=liella&kind=song&limit=5")
    assert len(data) == 5 and meta["next"] == "5" and all(w["project"] == "liella" for w in data)
    more, meta2 = call(api, con, "works", f"project=liella&kind=song&limit=5&cursor={meta['next']}")
    assert {w["id"] for w in data}.isdisjoint(w["id"] for w in more) and meta2["count"] == meta["count"]
    rels, _ = call(api, con, "releases", "project=liella&from=2024-01-01&to=2024-12-31&limit=100")
    assert rels and all("2024-01-01" <= r["release_date"] <= "2024-12-31" for r in rels)
    assert [r["release_date"] for r in rels] == sorted(r["release_date"] for r in rels)
    shows, _ = call(api, con, "concerts", "project=liella&year=2024&limit=100")
    assert shows and all(any(p["date"].startswith("2024") for s in c["stops"] for p in s["performances"]) for c in shows)
    assert error(api, con, "works", "limit=0").code == "bad_parameter"
    assert error(api, con, "works", "colour=red").code == "unknown_parameter"
    assert error(api, con, "releases", "from=2024-13-01").code == "bad_parameter"


def test_relations(api, con):
    recs, _ = call(api, con, "works/muse/snow-halation/recordings")
    assert "muse/snow-halation#original" in [r["id"] for r in recs]
    tracks, _ = call(api, con, "recordings/muse/snow-halation%23original/tracks")
    assert tracks[0]["release"] == "muse/2010-snow-halation"
    shows, meta = call(api, con, "works/muse/snow-halation/performances", "limit=3")
    assert len(shows) == 3 and meta["count"] > 3 and [s["date"] for s in shows] == sorted(s["date"] for s in shows)
    credits, _ = call(api, con, "persons/aki-hata/credits", "role=lyricist&limit=100")
    assert credits and {c["role"] for c in credits} == {"lyricist"}
    assert credits[0]["work"]["ref"].startswith("work:") and credits[0]["first_release"]
    setlist, _ = call(api, con, "concerts/hasunosora/kagayaki-fes-2026/setlist")
    assert [i["work"]["ref"] for i in setlist[0]["setlist"]][:2] == ["work:hasunosora/zenhoui-kyun",
                                                                     "work:hasunosora/non-fiction-hero-show"]
    assert error(api, con, "concerts/hasunosora/kagayaki-fes-2026/setlist", "date=2026-10-04").status == 404


def test_lineup_on_a_day(api, con):
    first, meta = call(api, con, "artists/liella/lineup", "at=2021-08-01")
    assert meta["at"] == "2021-08-01" and len(first) == 5
    assert first[0]["character"]["ref"] == "character:liella/kanon-shibuya"
    assert first[0]["cast"][0]["person"]["ref"] == "person:sayuri-date"
    later, _ = call(api, con, "artists/liella/lineup", "at=2024-08-01")
    assert len(later) > 5


def test_birthdays_and_random(api, con):
    day, meta = call(api, con, "birthdays", "date=01-01")
    assert meta["date"] == "01-01" and "character:aqours/dia-kurosawa" in [b["ref"] for b in day]
    month, _ = call(api, con, "birthdays", "month=1&type=characters")
    assert month and all(b["type"] == "character" and b["birthday"].startswith("01-") for b in month)
    assert error(api, con, "birthdays", "date=02-30").code == "bad_parameter"
    assert error(api, con, "birthdays", "date=01-01&month=1").code == "bad_parameter"
    picks, _ = call(api, con, "random", "project=aqours&mood=upbeat&count=3")
    assert len(picks) == 3 and all(w["project"] == "aqours" and w["kind"] == "song" for w in picks)
    assert error(api, con, "random", "count=11").code == "bad_parameter"


def test_every_route_answers(api, con):
    samples = {"works": "muse/snow-halation", "recordings": "muse/snow-halation#original",
               "releases": "muse/2010-snow-halation", "persons": "aki-hata", "characters": "liella/kanon-shibuya",
               "artists": "liella", "concerts": "liella/liella-1st", "venues": "nhk-hall", "cities": "tokyo",
               "projects": "liella"}
    for r in api.ROUTES:
        if r.fn is None:
            continue
        path = r.path[len("/api/v1/"):]
        if "{id}" in path:
            path = path.replace("{id}", samples[path.split("/")[0]].replace("#", "%23"))
        query = "q=snow" if r.key == ("search",) else ""
        data, _ = call(api, con, path, query)
        assert data is not None, r.path


def test_openapi_covers_every_route_and_resolves(api):
    doc = openapi()
    assert set(doc["paths"]) == {r.path for r in api.ROUTES}
    text = json.dumps(doc)
    assert set(re.findall(r"#/components/schemas/([A-Za-z0-9_]+)", text)) <= set(doc["components"]["schemas"])
    assert (ROOT / OUTPUT).read_text(encoding="utf-8") == json.dumps(doc, ensure_ascii=False, indent=1) + "\n"
