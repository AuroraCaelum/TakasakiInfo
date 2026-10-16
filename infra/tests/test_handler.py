import importlib
import io
import json
import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambda" / "api"))


class FakeS3:
    def __init__(self, objects):
        self.objects = objects

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[Key])}


@pytest.fixture
def handler(monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "bucket")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-northeast-2")
    mod = importlib.import_module("handler")
    return mod


def _event(path, method="GET"):
    return {"rawPath": path, "requestContext": {"http": {"method": method}}}


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
