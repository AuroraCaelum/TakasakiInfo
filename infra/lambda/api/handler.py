"""API Lambda behind CloudFront (Function URL, payload format 2.0). DESIGN.md §10.4, §10.6.

The queries are in ``api.py``. This module keeps the SQLite release in ``/tmp``: it reads
``data/version.json`` at most every ``VERSION_TTL`` seconds and downloads the database again when the
release changed. ``GET /api/v1/health`` reads the version every time (the deploy smoke test uses it) and
``GET /api/v1/openapi.json`` serves the document ``takasaki build`` writes next to this file.
"""

import base64
import gzip
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

import api
import boto3
from botocore.exceptions import ClientError

BUCKET = os.environ["DATA_BUCKET"]
PREFIX = os.environ.get("DATA_PREFIX", "data/")
DB_KEY = f"{PREFIX}takasakiinfo.sqlite"
VERSION_TTL = 300
DB_DIR = "/tmp"
CACHE = "public, max-age=300"
OPENAPI = Path(__file__).with_name("openapi.json")
_s3 = boto3.client("s3")
_state: dict = {"con": None, "version": None, "checked": 0.0}


def _response(status: int, body: dict, cache: str, headers: dict | None = None) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json; charset=utf-8", "Cache-Control": cache, **(headers or {})},
        "body": json.dumps(body, ensure_ascii=False),
    }


def _error(status: int, code: str, message: str) -> dict:
    return _response(status, {"error": code, "message": message}, "no-store" if status >= 500 else "public, max-age=60")


def data_version() -> dict | None:
    try:
        obj = _s3.get_object(Bucket=BUCKET, Key=f"{PREFIX}version.json")
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            return None
        raise
    return json.loads(obj["Body"].read())


def database(now: float | None = None) -> tuple[sqlite3.Connection, dict] | None:
    """The open database of the live release; None while there is no release."""
    now = time.time() if now is None else now
    if _state["con"] is not None and now - _state["checked"] < VERSION_TTL:
        return _state["con"], _state["version"]
    version = data_version()
    _state["checked"] = now
    if version is None:
        return None
    if _state["con"] is None or version.get("sha") != (_state["version"] or {}).get("sha"):
        path = f"{DB_DIR}/takasakiinfo-{version.get('sha', 'live')}.sqlite"
        if not os.path.exists(path):
            _s3.download_file(BUCKET, DB_KEY, path + ".part")
            os.replace(path + ".part", path)
        if _state["con"] is not None:
            _state["con"].close()
            old = f"{DB_DIR}/takasakiinfo-{_state['version'].get('sha', 'live')}.sqlite"
            if old != path and os.path.exists(old):
                os.remove(old)
        _state["con"] = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True, check_same_thread=False)
    _state["version"] = version
    return _state["con"], version


def _finish(res: dict, event: dict) -> dict:
    """ETag from the body (304 when the client has it), and gzip when the client takes it."""
    body = res["body"]
    tag = '"' + hashlib.sha1(body.encode("utf-8")).hexdigest()[:20] + '"'
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if res["headers"]["Cache-Control"] != "no-store":
        res["headers"]["ETag"] = tag
        if headers.get("if-none-match") == tag:
            return {"statusCode": 304, "headers": {"ETag": tag, "Cache-Control": res["headers"]["Cache-Control"]}}
    if "gzip" in headers.get("accept-encoding", "") and len(body) > 1024:
        res["body"] = base64.b64encode(gzip.compress(body.encode("utf-8"))).decode("ascii")
        res["isBase64Encoded"] = True
        res["headers"]["Content-Encoding"] = "gzip"
        res["headers"]["Vary"] = "Accept-Encoding"
    return res


def handler(event: dict, context: object) -> dict:
    http = event.get("requestContext", {}).get("http", {})
    method = http.get("method", "GET")
    path = event.get("rawPath", "/")
    if method not in ("GET", "HEAD"):
        return _error(405, "method_not_allowed", "the API is read-only: use GET")
    if path == f"{api.PREFIX}/health":
        version = data_version()  # read every time: this route exists to report the live release
        if version is None:
            return _response(503, {"status": "no-data"}, "no-store")
        return _response(200, {"status": "ok", **version}, "no-store")
    if path == f"{api.PREFIX}/openapi.json":
        return _finish({"statusCode": 200, "body": OPENAPI.read_text(encoding="utf-8"),
                        "headers": {"Content-Type": "application/json; charset=utf-8", "Cache-Control": CACHE}}, event)
    if not api.known(path):
        return _error(404, "not_found", f"no endpoint {path}")
    try:
        db = database()
        if db is None:
            return _error(503, "no_data", "no data release is live yet")
        con, version = db
        route, data, meta = api.dispatch(con, path, event.get("rawQueryString", ""))
    except api.ApiError as e:
        return _error(e.status, e.code, e.message)
    except sqlite3.OperationalError as e:  # a release built before the tables this code reads
        return _error(503, "no_data", f"the live data release does not have what the API reads ({e})")
    meta = {"dbLastUpdate": version.get("dbLastUpdate"), **meta}
    return _finish(_response(200, {"data": data, "meta": meta}, CACHE if route.cache else "no-store"), event)
