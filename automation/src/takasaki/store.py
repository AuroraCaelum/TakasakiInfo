"""Load and save the canonical ``data/`` tree.

YAML is written deterministically (fixed key order from the models, flow style
for flat list items) so that re-saving unchanged data produces no diff.
"""

from __future__ import annotations

import datetime as dt
import io
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, TypeVar

from pydantic import BaseModel
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from . import model as m

T = TypeVar("T", bound=BaseModel)


def repo_root() -> Path:
    env = os.environ.get("TAKASAKI_ROOT")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "automation").is_dir() and (parent / "README.md").exists():
            return parent
    raise RuntimeError("cannot locate repository root; set TAKASAKI_ROOT")


def _yaml() -> YAML:
    y = YAML(typ="rt")
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    y.allow_unicode = True
    y.preserve_quotes = False
    y.representer.ignore_aliases = lambda *_: True  # a value shared by two fields is written twice, not as &id/*id
    return y


def _plain(v: Any) -> Any:
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    return v


def _to_node(v: Any, in_list: bool = False) -> Any:
    if isinstance(v, dict):
        cm = CommentedMap()
        for k, x in v.items():
            cm[k] = _to_node(x)
        flat = all(not isinstance(x, (dict, list)) for x in v.values())
        if in_list and flat and len(v) <= 8:
            cm.fa.set_flow_style()
        return cm
    if isinstance(v, list):
        seq = CommentedSeq()
        for x in v:
            seq.append(_to_node(x, in_list=True))
        if v and all(isinstance(x, str) for x in v) and len(v) <= 12 and sum(len(x) for x in v) < 120:
            seq.fa.set_flow_style()
        return seq
    return v


def dump_model(obj: BaseModel) -> str:
    data = _plain(obj.model_dump(mode="python", by_alias=True, exclude_none=True, exclude_defaults=True))
    if "id" in data:  # always lead with the id
        data = {"id": data.pop("id"), **data}
    buf = io.StringIO()
    _yaml().dump(_to_node(data), buf)
    return buf.getvalue()


def load_model(path: Path, cls: type[T]) -> T:
    with path.open(encoding="utf-8") as f:
        raw = _yaml().load(f)
    return cls.model_validate(_from_node(raw))


def _from_node(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): _from_node(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_from_node(x) for x in v]
    if isinstance(v, dt.datetime):
        return v.date() if v.time() == dt.time() else v
    return v


# --- dataset ------------------------------------------------------------------

# entity type -> (directory under data/, model, nested by project?)
LAYOUT: dict[str, tuple[str, type[BaseModel], bool]] = {
    "project": ("projects", m.Project, False),
    "person": ("persons", m.Person, False),
    "character": ("characters", m.Character, True),
    "artist": ("artists", m.Artist, False),
    "work": ("works", m.Work, True),
    "release": ("releases", m.Release, True),
    "city": ("cities", m.City, False),
    "venue": ("venues", m.Venue, False),
    "concert": ("concerts", m.Concert, True),
}


def entity_path(data_dir: Path, kind: str, ent: BaseModel) -> Path:
    sub, _, _ = LAYOUT[kind]
    ident: str = ent.id  # type: ignore[attr-defined]
    # ids of project-scoped entities already carry the project ("liella/start-true-dreams")
    return data_dir / sub / f"{ident}.yaml"


@dataclass
class Dataset:
    projects: dict[str, m.Project] = field(default_factory=dict)
    persons: dict[str, m.Person] = field(default_factory=dict)
    characters: dict[str, m.Character] = field(default_factory=dict)
    artists: dict[str, m.Artist] = field(default_factory=dict)
    works: dict[str, m.Work] = field(default_factory=dict)
    releases: dict[str, m.Release] = field(default_factory=dict)
    cities: dict[str, m.City] = field(default_factory=dict)
    venues: dict[str, m.Venue] = field(default_factory=dict)
    concerts: dict[str, m.Concert] = field(default_factory=dict)
    meta: m.Meta | None = None
    layout: m.LegacyLayout | None = None

    def table(self, kind: str) -> dict[str, Any]:
        return getattr(self, LAYOUT[kind][0])

    def recording(self, ref: str) -> tuple[m.Work, m.Recording]:
        work_id, _, rec_id = ref.partition("#")
        work = self.works[work_id]
        for rec in work.recordings:
            if rec.id == rec_id:
                return work, rec
        raise KeyError(ref)

    def iter_all(self) -> Iterator[tuple[str, BaseModel]]:
        for kind in LAYOUT:
            for ent in self.table(kind).values():
                yield kind, ent


def load_dataset(data_dir: Path) -> Dataset:
    ds = Dataset()
    for kind, (sub, cls, _) in LAYOUT.items():
        base = data_dir / sub
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.yaml")):
            ent = load_model(path, cls)
            expected = base / f"{ent.id}.yaml"  # type: ignore[attr-defined]
            if path != expected:
                raise ValueError(f"{path}: id {ent.id!r} does not match file location")  # type: ignore[attr-defined]
            ds.table(kind)[ent.id] = ent  # type: ignore[attr-defined]
    if (data_dir / "meta.yaml").exists():
        ds.meta = load_model(data_dir / "meta.yaml", m.Meta)
    if (data_dir / "legacy" / "layout.yaml").exists():
        ds.layout = load_model(data_dir / "legacy" / "layout.yaml", m.LegacyLayout)
    return ds


def save_dataset(ds: Dataset, data_dir: Path) -> int:
    """Write every entity; returns the number of files written. Stale files are removed."""
    written: set[Path] = set()
    for kind, ent in ds.iter_all():
        path = entity_path(data_dir, kind, ent)
        _write(path, dump_model(ent))
        written.add(path)
    if ds.meta:
        _write(data_dir / "meta.yaml", dump_model(ds.meta))
        written.add(data_dir / "meta.yaml")
    if ds.layout:
        _write(data_dir / "legacy" / "layout.yaml", dump_model(ds.layout))
        written.add(data_dir / "legacy" / "layout.yaml")
    for path in data_dir.rglob("*.yaml"):
        if path not in written:
            path.unlink()
    return len(written)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    path.write_text(text, encoding="utf-8", newline="\n")
