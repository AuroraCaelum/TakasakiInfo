"""Deploy logic against in-memory S3 / CloudFront fakes (no AWS calls)."""

import io
import json
import types

import pytest

from takasaki.deploy import VERSION_KEY, Deployer, DeployError, File, content_type


class NoSuchKey(Exception):
    pass


class FakeS3:
    exceptions = types.SimpleNamespace(NoSuchKey=NoSuchKey)

    def __init__(self):
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.writes: list[str] = []

    def put_object(self, Bucket, Key, Body, ContentType, CacheControl):
        self.objects[Key] = (Body, ContentType)
        self.writes.append(Key)

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise NoSuchKey(Key)
        return {"Body": io.BytesIO(self.objects[Key][0])}

    def copy_object(self, Bucket, Key, CopySource, MetadataDirective):
        self.objects[Key] = self.objects[CopySource["Key"]]
        self.writes.append(Key)

    def delete_objects(self, Bucket, Delete):
        for o in Delete["Objects"]:
            del self.objects[o["Key"]]

    def get_paginator(self, name):
        store = self

        class P:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": k} for k in sorted(store.objects) if k.startswith(Prefix)]}

        return P()


class FakeCloudFront:
    def __init__(self):
        self.invalidations = 0

    def create_invalidation(self, DistributionId, InvalidationBatch):
        self.invalidations += 1
        return {"Invalidation": {"Id": f"I{self.invalidations}"}}

    def get_invalidation(self, DistributionId, Id):
        return {"Invalidation": {"Status": "Completed"}}


def cdn(s3: FakeS3, broken_api: bool = False):
    """Serve the live prefixes the way the distribution does."""
    def fetch(url: str):
        path = url.removeprefix("https://cdn.example")
        if path == "/api/v1/health":
            if broken_api:
                raise OSError("502 from origin")
            return {"status": "ok", **json.loads(s3.objects[VERSION_KEY][0])}
        return json.loads(s3.objects[path.lstrip("/")][0])
    return fetch


def release(sha: str, db: str, extra: dict | None = None) -> dict[str, File]:
    version = {"dbLastUpdate": db, "schemaVersion": "0.1.0", "sha": sha}
    files = {
        "data/legacy/TakasakiInfo.json": File(json.dumps({"dbLastUpdate": db, "data": []}).encode(), content_type(".json"), "c"),
        "site/index.html": File(b"<html></html>", content_type(".html"), "c"),
        VERSION_KEY: File(json.dumps(version).encode(), content_type(".json"), "c"),
    }
    files.update(extra or {})
    return files


def deployer(s3, cf, fetch):
    return Deployer(s3, cf, bucket="b", distribution_id="D", base_url="https://cdn.example", fetch=fetch,
                    sleep=lambda s: None, log=lambda m: None)


def test_stage_only_leaves_live_prefixes_alone():
    s3, cf = FakeS3(), FakeCloudFront()
    deployer(s3, cf, cdn(s3)).run("a1", release("a1", "T1"), promote=False)
    assert all(k.startswith("releases/a1/") for k in s3.objects)
    assert cf.invalidations == 0


def test_promote_mirrors_release_and_writes_version_last():
    s3, cf = FakeS3(), FakeCloudFront()
    s3.objects["data/legacy/old-file.json"] = (b"{}", "x")  # stale object from an earlier release
    deployer(s3, cf, cdn(s3)).run("a1", release("a1", "T1"), promote=True)
    live = sorted(k for k in s3.objects if not k.startswith("releases/"))
    assert live == ["data/legacy/TakasakiInfo.json", VERSION_KEY, "site/index.html"]
    live_writes = [k for k in s3.writes if not k.startswith("releases/")]
    assert live_writes[-1] == VERSION_KEY
    assert cf.invalidations == 1


def test_failed_smoke_rolls_back_to_previous_release():
    s3, cf = FakeS3(), FakeCloudFront()
    deployer(s3, cf, cdn(s3)).run("a1", release("a1", "T1"), promote=True)
    with pytest.raises(DeployError):
        deployer(s3, cf, cdn(s3, broken_api=True)).run("b2", release("b2", "T2"), promote=True)
    assert json.loads(s3.objects[VERSION_KEY][0])["sha"] == "a1"
    assert json.loads(s3.objects["data/legacy/TakasakiInfo.json"][0])["dbLastUpdate"] == "T1"
    assert cf.invalidations == 3  # a1, b2, rollback to a1


def test_incomplete_release_is_refused():
    s3, cf = FakeS3(), FakeCloudFront()
    s3.objects["releases/x/data/legacy/TakasakiInfo.json"] = (b"{}", "x")
    with pytest.raises(DeployError, match="incomplete"):
        deployer(s3, cf, cdn(s3)).promote("x")


def test_release_files_from_dataset():
    from takasaki.deploy import release_files
    from takasaki.store import load_dataset, repo_root

    data = repo_root() / "data"
    if not (data / "meta.yaml").exists():
        pytest.skip("data/ not migrated yet")
    files = release_files(load_dataset(data), "abc123")
    assert "data/legacy/TakasakiInfo.json" in files and "data/legacy/albums/Aqours/Aqours.csv" in files
    assert files["data/legacy/albums/Aqours/Aqours.csv"].content_type == "text/csv; charset=utf-8"
    version = json.loads(files[VERSION_KEY].body)
    assert version["sha"] == "abc123"
    assert json.loads(files["data/legacy/TakasakiInfo.json"].body)["dbLastUpdate"] == version["dbLastUpdate"]
    # the v1 files and the database ship with the same data version (§10.2)
    assert json.loads(files["data/v1/quality.json"].body)["dbLastUpdate"] == version["dbLastUpdate"]
    assert json.loads(files["data/v1/tracks.json"].body)["count"] > 1000
    assert files["data/takasakiinfo.sqlite"].body[:16] == b"SQLite format 3\x00"
