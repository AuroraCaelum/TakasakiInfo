"""Publish a data release to S3 and promote it behind CloudFront (DESIGN.md §10.4).

    releases/<sha>/data/…   immutable copy of every release (rollback source)
    releases/<sha>/site/…
    data/…, site/…          live prefixes served by CloudFront; data/version.json is written last

Stage-only runs (non-main branches) upload the release and stop: nothing public changes.
"""

from __future__ import annotations

import html
import json
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .build_legacy import build_legacy
from .store import Dataset

LIVE_PREFIXES = ("data/", "site/")
VERSION_KEY = "data/version.json"
# browsers revalidate quickly; CloudFront keeps objects until the next deploy invalidates them
DATA_CACHE = "public, max-age=300, s-maxage=31536000"
VERSION_CACHE = "public, max-age=0, s-maxage=31536000"


class DeployError(RuntimeError):
    pass


def content_type(key: str) -> str:
    if key.endswith(".json"):
        return "application/json; charset=utf-8"
    if key.endswith(".csv"):
        return "text/csv; charset=utf-8"
    if key.endswith(".html"):
        return "text/html; charset=utf-8"
    if key.endswith(".sqlite"):
        return "application/vnd.sqlite3"
    return "application/octet-stream"


@dataclass(frozen=True)
class File:
    body: bytes
    content_type: str
    cache_control: str


def version_doc(ds: Dataset, sha: str) -> dict[str, str]:
    assert ds.meta is not None
    return {"dbLastUpdate": ds.meta.db_last_update, "schemaVersion": ds.meta.schema_version, "sha": sha}


def landing_page(version: dict[str, str]) -> str:
    """Placeholder for the connection-map site (§10.7, Phase 7)."""
    rows = "".join(
        f'<li><a href="{html.escape(href)}">{html.escape(href)}</a></li>'
        for href in ("/data/legacy/TakasakiInfo.json", "/data/version.json", "/api/v1/health")
    )
    return (
        "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>TakasakiInfo</title></head><body>"
        f"<h1>TakasakiInfo</h1><p>dbLastUpdate: {html.escape(version['dbLastUpdate'])}</p>"
        f"<ul>{rows}</ul>"
        "<p><a href=\"https://github.com/AuroraCaelum/TakasakiInfo\">GitHub</a></p></body></html>"
    )


def release_files(ds: Dataset, sha: str) -> dict[str, File]:
    """Every object of one release, keyed by its live path (``data/…`` or ``site/…``)."""
    files = {f"data/legacy/{rel}": File(blob, content_type(rel), DATA_CACHE) for rel, blob in build_legacy(ds).items()}
    version = version_doc(ds, sha)
    files["site/index.html"] = File(landing_page(version).encode("utf-8"), content_type("index.html"), DATA_CACHE)
    files[VERSION_KEY] = File(json.dumps(version, ensure_ascii=False).encode("utf-8"),
                              content_type(VERSION_KEY), VERSION_CACHE)
    return files


def http_get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "takasaki-deploy/0.1"})
    with urllib.request.urlopen(req, timeout=20) as res:
        return json.loads(res.read())


class Deployer:
    def __init__(self, s3: Any, cloudfront: Any, *, bucket: str, distribution_id: str, base_url: str,
                 fetch: Callable[[str], Any] = http_get_json, sleep: Callable[[float], None] = time.sleep,
                 log: Callable[[str], None] = print, smoke_attempts: int = 6, smoke_delay: float = 10) -> None:
        self.s3, self.cf = s3, cloudfront
        self.bucket, self.distribution_id = bucket, distribution_id
        self.base_url = base_url.rstrip("/")
        self.fetch, self.sleep, self.log = fetch, sleep, log
        self.smoke_attempts, self.smoke_delay = smoke_attempts, smoke_delay

    # --- S3 helpers -----------------------------------------------------------

    def _keys(self, prefix: str) -> list[str]:
        out: list[str] = []
        for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix):
            out.extend(obj["Key"] for obj in page.get("Contents", []))
        return out

    def _get_json(self, key: str) -> Any | None:
        try:
            obj = self.s3.get_object(Bucket=self.bucket, Key=key)
        except self.s3.exceptions.NoSuchKey:
            return None
        return json.loads(obj["Body"].read())

    # --- steps ----------------------------------------------------------------

    def stage(self, sha: str, files: dict[str, File]) -> None:
        root = f"releases/{sha}/"
        for key, f in sorted(files.items()):
            self.s3.put_object(Bucket=self.bucket, Key=root + key, Body=f.body,
                               ContentType=f.content_type, CacheControl=f.cache_control)
        self.log(f"staged {len(files)} objects under s3://{self.bucket}/{root}")

    def live_sha(self) -> str | None:
        doc = self._get_json(VERSION_KEY)
        return doc.get("sha") if doc else None

    def promote(self, sha: str) -> None:
        root = f"releases/{sha}/"
        keys = [k[len(root):] for k in self._keys(root)]
        if VERSION_KEY not in keys:
            raise DeployError(f"release {sha} is incomplete: {root}{VERSION_KEY} is missing")
        for key in sorted(k for k in keys if k != VERSION_KEY):
            self.s3.copy_object(Bucket=self.bucket, Key=key, CopySource={"Bucket": self.bucket, "Key": root + key},
                                MetadataDirective="COPY")
        wanted = set(keys)
        stale = [k for p in LIVE_PREFIXES for k in self._keys(p) if k not in wanted]
        for i in range(0, len(stale), 1000):
            self.s3.delete_objects(Bucket=self.bucket,
                                   Delete={"Objects": [{"Key": k} for k in stale[i:i + 1000]], "Quiet": True})
        # last: Lambda and clients treat a new version.json as "the release is complete"
        self.s3.copy_object(Bucket=self.bucket, Key=VERSION_KEY,
                            CopySource={"Bucket": self.bucket, "Key": root + VERSION_KEY}, MetadataDirective="COPY")
        self.log(f"promoted {sha}: {len(keys)} objects live, {len(stale)} stale removed")

    def invalidate(self, sha: str, timeout: float = 900) -> None:
        res = self.cf.create_invalidation(
            DistributionId=self.distribution_id,
            InvalidationBatch={"Paths": {"Quantity": 1, "Items": ["/*"]}, "CallerReference": f"{sha}-{time.time_ns()}"},
        )
        inv_id = res["Invalidation"]["Id"]
        waited = 0.0
        while self.cf.get_invalidation(DistributionId=self.distribution_id, Id=inv_id)["Invalidation"]["Status"] != "Completed":
            if waited >= timeout:
                raise DeployError(f"invalidation {inv_id} did not complete in {timeout}s")
            self.sleep(10)
            waited += 10
        self.log(f"invalidated /* ({inv_id})")

    def smoke(self, version: dict[str, str]) -> None:
        checks = [
            ("/data/version.json", lambda d: d.get("sha") == version["sha"]),
            ("/data/legacy/TakasakiInfo.json", lambda d: d.get("dbLastUpdate") == version["dbLastUpdate"]),
            ("/api/v1/health", lambda d: d.get("status") == "ok" and d.get("sha") == version["sha"]),
        ]
        for path, ok in checks:
            last: Any = None
            for attempt in range(self.smoke_attempts):
                try:
                    last = self.fetch(self.base_url + path)
                    if ok(last):
                        break
                except Exception as e:  # network errors and HTTP errors count as a failed attempt
                    last = repr(e)
                if attempt + 1 < self.smoke_attempts:
                    self.sleep(self.smoke_delay)
            else:
                raise DeployError(f"smoke test failed for {path}: {str(last)[:300]}")
            self.log(f"smoke ok: {path}")

    def run(self, sha: str, files: dict[str, File], *, promote: bool) -> None:
        self.stage(sha, files)
        if not promote:
            self.log("stage-only run: live prefixes untouched")
            return
        previous = self.live_sha()
        version = json.loads(files[VERSION_KEY].body)
        self.promote(sha)
        self.invalidate(sha)
        try:
            self.smoke(version)
        except DeployError:
            if previous and previous != sha:
                self.log(f"rolling back to {previous}")
                self.promote(previous)
                self.invalidate(previous)
            raise
