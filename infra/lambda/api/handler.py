"""API Lambda behind CloudFront (Function URL, payload format 2.0). DESIGN.md §10.4, §10.6.

For now it serves ``GET /api/v1/health``, which the deploy smoke test uses to check
the CloudFront → Lambda route and the data version. Query endpoints (§10.6) are
added on top of the SQLite release in Phase 6.
"""

import json
import os

import boto3
from botocore.exceptions import ClientError

BUCKET = os.environ["DATA_BUCKET"]
PREFIX = os.environ.get("DATA_PREFIX", "data/")
_s3 = boto3.client("s3")


def _response(status: int, body: dict, cache: str) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json; charset=utf-8", "Cache-Control": cache},
        "body": json.dumps(body, ensure_ascii=False),
    }


def data_version() -> dict | None:
    try:
        obj = _s3.get_object(Bucket=BUCKET, Key=f"{PREFIX}version.json")
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            return None
        raise
    return json.loads(obj["Body"].read())


def handler(event: dict, context: object) -> dict:
    http = event.get("requestContext", {}).get("http", {})
    method = http.get("method", "GET")
    path = event.get("rawPath", "/")
    if method not in ("GET", "HEAD"):
        return _response(405, {"error": "method not allowed"}, "no-store")
    if path == "/api/v1/health":
        version = data_version()  # read every time: this route exists to report the live release
        if version is None:
            return _response(503, {"status": "no-data"}, "no-store")
        return _response(200, {"status": "ok", **version}, "no-store")
    return _response(404, {"error": "not found", "path": path}, "public, max-age=60")
