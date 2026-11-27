import base64
import gzip
import importlib
import io
import json
import sqlite3
import sys
import zlib
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambda" / "api"))


class FakeS3:
    def __init__(self, objects):
        self.objects = objects
        self.downloads = 0

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[Key])}

    def download_file(self, Bucket, Key, Filename):
        self.downloads += 1
        Path(Filename).write_bytes(self.objects[Key])


def _db(tmp_path, name="Liella!"):
    """A database with one project, enough for a detail request."""
    path = tmp_path / f"{name}.sqlite"
    con = sqlite3.connect(path)
    con.executescript("CREATE TABLE document (entity TEXT PRIMARY KEY, body BLOB NOT NULL);"
                      "CREATE TABLE label (entity TEXT, field TEXT, lang TEXT, value TEXT, status TEXT);")
    doc = {"id": "liella", "names": {"ja": name, "rom": name, "ko": name}, "note": "x" * 2000,
           "evidence": {"names": {"status": "official"}}}
    con.execute("INSERT INTO document VALUES (?, ?)", ("project:liella", zlib.compress(json.dumps(doc).encode())))
    con.commit()
    con.close()
    return path.read_bytes()


@pytest.fixture
def handler(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_BUCKET", "bucket")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-northeast-2")
    mod = importlib.import_module("handler")
    monkeypatch.setattr(mod, "_state", {"con": None, "version": None, "checked": 0.0})
    monkeypatch.setattr(mod, "DB_DIR", str(tmp_path / "db"))
    (tmp_path / "db").mkdir()
    return mod


def _event(path, method="GET", query="", headers=None):
    return {"rawPath": path, "rawQueryString": query, "headers": headers or {},
            "requestContext": {"http": {"method": method}}}


def _live(handler, monkeypatch, tmp_path, sha="abc", name="Liella!"):
    version = {"dbLastUpdate": "2026-11-27T00:00:00Z", "sha": sha}
    s3 = FakeS3({"data/version.json": json.dumps(version).encode(), "data/takasakiinfo.sqlite": _db(tmp_path, name)})
    monkeypatch.setattr(handler, "_s3", s3)
    return s3


def test_health_reports_live_version(handler, monkeypatch):
    version = {"dbLastUpdate": "2026-10-17T00:00:00Z", "sha": "abc"}
    monkeypatch.setattr(handler, "_s3", FakeS3({"data/version.json": json.dumps(version).encode()}))
    res = handler.handler(_event("/api/v1/health"), None)
    assert res["statusCode"] == 200
    assert res["headers"]["Cache-Control"] == "no-store"
    assert json.loads(res["body"]) == {"status": "ok", **version}


def test_health_without_data(handler, monkeypatch):
    monkeypatch.setattr(handler, "_s3", FakeS3({}))
    assert handler.handler(_event("/api/v1/health"), None)["statusCode"] == 503


def test_unknown_path_and_method(handler, monkeypatch):
    monkeypatch.setattr(handler, "_s3", FakeS3({}))
    assert handler.handler(_event("/api/v1/nope"), None)["statusCode"] == 404
    assert handler.handler(_event("/api/v1/health", "POST"), None)["statusCode"] == 405


def test_a_request_is_answered_from_the_live_release(handler, monkeypatch, tmp_path):
    s3 = _live(handler, monkeypatch, tmp_path)
    res = handler.handler(_event("/api/v1/projects/liella"), None)
    assert res["statusCode"] == 200 and res["headers"]["Cache-Control"] == "public, max-age=300"
    body = json.loads(res["body"])
    assert body["data"]["names"]["ja"] == "Liella!" and "evidence" not in body["data"]
    assert body["meta"] == {"dbLastUpdate": "2026-11-27T00:00:00Z"}
    full = json.loads(handler.handler(_event("/api/v1/projects/liella", query="include=evidence"), None)["body"])
    assert "evidence" in full["data"]
    assert s3.downloads == 1  # the second request uses the open database


def test_etag_and_gzip(handler, monkeypatch, tmp_path):
    _live(handler, monkeypatch, tmp_path)
    res = handler.handler(_event("/api/v1/projects/liella"), None)
    tag = res["headers"]["ETag"]
    again = handler.handler(_event("/api/v1/projects/liella", headers={"If-None-Match": tag}), None)
    assert again["statusCode"] == 304 and "body" not in again
    zipped = handler.handler(_event("/api/v1/projects/liella", headers={"Accept-Encoding": "gzip, br"}), None)
    assert zipped["isBase64Encoded"] and zipped["headers"]["Content-Encoding"] == "gzip"
    assert json.loads(gzip.decompress(base64.b64decode(zipped["body"])))["data"]["id"] == "liella"


def test_a_new_release_is_picked_up_after_the_ttl(handler, monkeypatch, tmp_path):
    _live(handler, monkeypatch, tmp_path, sha="abc", name="Liella!")
    handler.handler(_event("/api/v1/projects/liella"), None)
    s3 = _live(handler, monkeypatch, tmp_path, sha="def", name="Liella!!")
    body = json.loads(handler.handler(_event("/api/v1/projects/liella"), None)["body"])
    assert body["data"]["names"]["ja"] == "Liella!" and s3.downloads == 0  # within the TTL
    handler._state["checked"] -= handler.VERSION_TTL
    body = json.loads(handler.handler(_event("/api/v1/projects/liella"), None)["body"])
    assert body["data"]["names"]["ja"] == "Liella!!" and s3.downloads == 1


def test_errors_are_json(handler, monkeypatch, tmp_path):
    _live(handler, monkeypatch, tmp_path)
    res = handler.handler(_event("/api/v1/projects/nope"), None)
    assert res["statusCode"] == 404 and json.loads(res["body"])["error"] == "not_found"
    res = handler.handler(_event("/api/v1/projects", query="colour=red"), None)
    assert res["statusCode"] == 400 and json.loads(res["body"])["error"] == "unknown_parameter"


def test_no_release_yet(handler, monkeypatch):
    monkeypatch.setattr(handler, "_s3", FakeS3({}))
    res = handler.handler(_event("/api/v1/works"), None)
    assert res["statusCode"] == 503 and json.loads(res["body"])["error"] == "no_data"


def test_openapi_is_served(handler, monkeypatch):
    monkeypatch.setattr(handler, "_s3", FakeS3({}))
    res = handler.handler(_event("/api/v1/openapi.json"), None)
    assert res["statusCode"] == 200 and json.loads(res["body"])["openapi"].startswith("3.")


def test_a_release_older_than_the_api(handler, monkeypatch, tmp_path):
    path = tmp_path / "old.sqlite"
    sqlite3.connect(path).close()
    version = {"dbLastUpdate": "2026-10-17T00:00:00Z", "sha": "old"}
    monkeypatch.setattr(handler, "_s3", FakeS3({"data/version.json": json.dumps(version).encode(),
                                                "data/takasakiinfo.sqlite": path.read_bytes()}))
    res = handler.handler(_event("/api/v1/works/muse/snow-halation"), None)
    assert res["statusCode"] == 503 and json.loads(res["body"])["error"] == "no_data"
