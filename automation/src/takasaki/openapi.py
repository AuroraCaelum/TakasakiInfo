"""The API's OpenAPI document (DESIGN.md §10.6).

The endpoints and their parameters come from the routes of the API Lambda (``infra/lambda/api/api.py``),
the entity schemas from the model (the same descriptions as ``schema/*.json`` and the README), and the
two views from ``TRACK_FIELDS``/``RECORDING_FIELDS``. ``takasaki build`` writes it next to the handler,
which serves it at ``/api/v1/openapi.json``; ``takasaki check`` (E8) compares it like any other output.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import Any

from pydantic.json_schema import models_json_schema

from . import model as m
from .build_v1 import RECORDING_FIELDS, TRACK_FIELDS, V1_FORMAT
from .readme import CDN

API_DIR = Path(__file__).resolve().parents[3] / "infra" / "lambda" / "api"
OUTPUT = "infra/lambda/api/openapi.json"
ENTITIES = [m.Work, m.Release, m.Person, m.Character, m.Artist, m.Concert, m.Venue, m.City, m.Project]


@cache
def api_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("takasaki_api", API_DIR / "api.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses look their module up while the file runs
    spec.loader.exec_module(mod)
    return mod


def _ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def _arr(schema: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": schema}


def _obj(props: dict[str, Any], required: list[str] | None = None, description: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        out["required"] = required
    if description:
        out["description"] = description
    return out


REF = _obj({"ref": {"type": "string", "description": "`<type>:<id>` (`person:aki-hata`)."},
            "names": _ref("Names")}, ["ref", "names"], "A reference with its names in every language.")
NULLABLE_REF = {"anyOf": [_ref("Ref"), {"type": "null"}]}


def _view(fields: dict[str, tuple[str, str]], description: str) -> dict[str, Any]:
    kinds = {"string": {"type": ["string", "null"]}, "integer": {"type": ["integer", "null"]},
             "boolean": {"type": "boolean"}, "date": {"type": ["string", "null"], "format": "date"},
             "object": {"type": ["object", "null"]}, "map of string": {"type": ["object", "null"],
                                                                        "additionalProperties": {"type": "string"}},
             "**Names**": _ref("Names"), "**ref**[]": _arr(_ref("Ref"))}
    return _obj({k: {**kinds[t], "description": d} for k, (t, d) in fields.items()}, None, description)


def _extra() -> dict[str, Any]:
    s = lambda d: {"type": "string", "description": d}
    sn = lambda d: {"type": ["string", "null"], "description": d}
    return {
        "Ref": REF,
        "RecordingView": _view(RECORDING_FIELDS, "A recording as a row of `recordings.json`."),
        "TrackView": _view(TRACK_FIELDS, "A track as a row of `tracks.json`."),
        "SearchHit": _obj({**REF["properties"], "type": s("Entity type (`work`)."), "id": s("Entity id."),
                           "matched": s("The name or title that matched.")}, ["ref", "names", "type", "id", "matched"],
                          "Exact matches first, then those that start with the text, then the rest."),
        "Birthday": _obj({**REF["properties"], "type": s("`character` or `person`."), "id": s("Entity id."),
                          "birthday": s("`MM-DD`, or `YYYY-MM-DD` for a person whose year is public."),
                          "project": s("Project of a character.")}, ["ref", "names", "type", "id", "birthday"]),
        "PersonCredit": _obj({"role": s("`lyricist`, `composer`, `arranger`, `strings_arranger`, `brass_arranger`."),
                              "work": _ref("Ref"),
                              "recording": {**NULLABLE_REF, "description": "The recording the credit is on; null "
                                            "for a work-level credit (lyricist, composer)."},
                              "first_release": sn("Earliest release date of the work.")}),
        "Performance": _obj({"date": s("Day of the show."), "label": sn("Show label (`Day.1`)."),
                             "concert": _ref("Ref"), "stop": s("Stop id within the concert."),
                             "venue": NULLABLE_REF, "position": {"type": "integer", "description": "Place in the set list."},
                             "recording": sn("Recording sung, when the set list links one.")}),
        "Show": _obj({"date": s("Day of the show."), "label": sn("Show label."), "stop": s("Stop id."),
                      "venue": NULLABLE_REF,
                      "setlist": _arr(_obj({"position": {"type": "integer"},
                                            "type": s("`song`, or a marker: `mc`, `video`, `encore`, `double_encore`, "
                                                      "`talk`, `other`."),
                                            "work": NULLABLE_REF, "recording": s("Recording id, when linked."),
                                            "version": s("Version sung, when no recording is linked."),
                                            "label": s("Marker text as listed."),
                                            "title_raw": s("Title as listed, when not matched to a work."),
                                            "performers": _arr(_ref("Ref"))}))}),
        "LineupMember": _obj({"character": _ref("Ref"), "from": sn("First day as a member; null: from the start."),
                              "until": sn("Last day as a member; null: still a member."),
                              "cast": _arr(_obj({"person": _ref("Ref"), "from": sn("First day in the role."),
                                                 "until": sn("Last day in the role.")}))}),
        "Health": _obj({"status": s("`ok`."), "dbLastUpdate": s("Time of the live data."),
                        "schemaVersion": s("Schema version of the data."), "sha": s("Commit the data was built from.")}),
        "Meta": _obj({"dbLastUpdate": s("Time of the data that answered."),
                      "count": {"type": "integer", "description": "Number of items; for a page, of all pages."},
                      "limit": {"type": "integer"}, "next": sn("`cursor` of the next page; null on the last.")}),
        "Error": _obj({"error": s("`bad_parameter`, `unknown_parameter`, `missing_parameter`, `not_found`, "
                                  "`method_not_allowed`, `no_data`."), "message": s("What went wrong.")},
                      ["error", "message"]),
    }


def openapi() -> dict[str, Any]:
    api = api_module()
    _, defs = models_json_schema([(cls, "serialization") for cls in ENTITIES], by_alias=True,
                                 ref_template="#/components/schemas/{model}")
    schemas = {**defs["$defs"], **_extra()}
    paths: dict[str, Any] = {}
    error = {"description": "Error", "content": {"application/json": {"schema": _ref("Error")}}}
    for r in api.ROUTES:
        params = [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"},
                   "description": "Id as in the data (`muse/snow-halation`); send a recording id's `#` as `%23`."}] \
            if "{id}" in r.path else []
        params += [{"name": p.name, "in": "query", "required": p.required, "description": p.description,
                    "schema": p.schema()} for p in r.params]
        body = r.data if r.fn is None else _obj({"data": r.data, "meta": _ref("Meta")}, ["data", "meta"])
        op = {"summary": r.summary, "tags": [r.tag], "operationId": "_".join(r.key).replace(".", "_"),
              "responses": {"200": {"description": "OK", "content": {"application/json": {"schema": body}}},
                            **({"400": error, "404": error} if r.fn is not None else {})}}
        if params:
            op["parameters"] = params
        paths[r.path] = {"get": op}
    return {
        "openapi": "3.1.0",
        "info": {"title": "TakasakiInfo API", "version": V1_FORMAT,
                 "description": "Read-only API of the TakasakiInfo database: Love Live! songs, releases, people, "
                                "characters and concerts in Japanese, romaji and Korean. Every response is "
                                "`{\"data\", \"meta\"}`; names and titles come in every language. `?include=evidence` "
                                "adds the source and status of every value."},
        "servers": [{"url": CDN}],
        "paths": paths,
        "components": {"schemas": dict(sorted(schemas.items()))},
    }


def render_openapi() -> bytes:
    return (json.dumps(openapi(), ensure_ascii=False, indent=1) + "\n").encode("utf-8")
