"""v1 files and the SQLite database built from the real data/ tree (§10.2, §10.5)."""

import json
import sqlite3

import pytest

from takasaki.build_sqlite import build_sqlite
from takasaki.build_v1 import build_v1
from takasaki.store import load_dataset, repo_root

DATA = repo_root() / "data"
pytestmark = pytest.mark.skipif(not (DATA / "meta.yaml").exists(), reason="data/ not migrated yet")


@pytest.fixture(scope="module")
def ds():
    return load_dataset(DATA)


def test_v1_files_agree_with_the_database(ds, tmp_path):
    files = build_v1(ds)
    tracks = json.loads(files["v1/tracks.json"])
    assert tracks["schemaVersion"] == "1.0.0" and tracks["count"] == len(tracks["data"])
    assert {t["link"]["source"] for t in tracks["data"]} <= {"own", "main", "none"}
    schema = json.loads(files["v1/schema/works.json"])
    assert "recordings" in schema["properties"]

    db = tmp_path / "t.sqlite"
    build_sqlite(ds, db)  # raises on any foreign key violation
    con = sqlite3.connect(db)
    assert con.execute("select count(*) from track").fetchone()[0] == tracks["count"]
    linked = sum(1 for t in tracks["data"] if t["link"]["youtube_music"])
    assert con.execute("select count(*) from stream_link").fetchone()[0] == linked
    for view in ("v_track_flat", "v_person_credits", "v_work_performances"):
        assert con.execute(f"select count(*) from {view}").fetchone()[0] > 0
    # trigram search over names in every language and over match keys (spaces dropped)
    assert con.execute("select count(*) from search where search match 'atanabe'").fetchone()[0] > 0
    assert ("character:aqours/you-watanabe",) in con.execute("select entity from search where search match '\"渡辺 曜\"'").fetchall()
    # dated lineups answer "who was in the unit on this day"
    on_day = con.execute("select character from lineup_member where artist = 'cerise-bouquet' "
                         "and \"from\" <= '2024-05-01' and until >= '2024-05-01' order by character").fetchall()
    assert [c for (c,) in on_day] == ["hasunosora/ginko-momose", "hasunosora/kaho-hinoshita", "hasunosora/kozue-otomune"]
