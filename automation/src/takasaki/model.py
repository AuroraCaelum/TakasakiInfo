"""Canonical data model (DESIGN.md §4).

Every entity is stored as one YAML file under ``data/``. Models forbid unknown
keys so that typos in hand-edited files fail validation (E1) instead of being
silently ignored.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Status(StrEnum):
    """Trust level of a value (DESIGN.md §4.4)."""

    official = "official"
    established = "established"
    derived = "derived"
    legacy = "legacy"
    draft = "draft"


class Names(Strict):
    ja: str | None = None
    kana: str | None = None
    rom: str | None = None
    ko: str | None = None


class Evidence(Strict):
    status: Status
    source: str | None = None
    checked: dt.date | None = None
    note: str | None = None


# --- projects -----------------------------------------------------------------


class Copyright(Strict):
    text: str
    lang: str
    source: str | None = None
    checked: dt.date | None = None


class ProjectLegacy(Strict):
    category: str
    file: str


class Project(Strict):
    id: str
    names: Names
    legacy: ProjectLegacy | None = None
    copyright: list[Copyright] = []
    official: dict[str, str] = {}
    evidence: dict[str, Evidence] = {}


# --- people -------------------------------------------------------------------


class Alias(Strict):
    text: str
    kind: Literal["variant", "misprint", "former"] = "variant"
    note: str | None = None


class Person(Strict):
    id: str
    names: Names
    native_script: Literal["ja", "latin"] = "ja"
    aliases: list[Alias] = []
    distinct_from: list[str] = []
    evidence: dict[str, Evidence] = {}


class Casting(Strict):
    person: str
    from_: dt.date | None = Field(default=None, alias="from")
    until: dt.date | None = None


class Character(Strict):
    id: str
    project: str
    names: Names
    casting: list[Casting] = []
    distinct_from: list[str] = []
    evidence: dict[str, Evidence] = {}


class Lineup(Strict):
    from_: dt.date | None = Field(default=None, alias="from")
    until: dt.date | None = None
    members: list[str]


ArtistKind = Literal["group", "unit", "solo", "cross_unit", "collab", "special", "unclassified"]


class ArtistLegacy(Strict):
    category: str | None = None


class Artist(Strict):
    id: str
    kind: ArtistKind
    projects: list[str] = []
    names: Names
    lineups: list[Lineup] = []
    distinct_from: list[str] = []
    evidence: dict[str, Evidence] = {}


# --- works and recordings -----------------------------------------------------


class Credit(Strict):
    """One credited person. ``role`` holds the character a cast member is credited as
    (e.g. musical cast credited as lyricists: ``堀内まり菜（椿 ルリカ役）``)."""

    person: str
    affiliation: str | None = None
    role: Names | None = None


class Performer(Strict):
    artist: str | None = None
    character: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Performer:
        if (self.artist is None) == (self.character is None):
            raise ValueError("performer needs exactly one of artist / character")
        return self

    @property
    def ref(self) -> tuple[str, str]:
        return ("artist", self.artist) if self.artist else ("character", self.character)  # type: ignore[return-value]


class WorkCredits(Strict):
    lyricist: list[Credit] = []
    composer: list[Credit] = []


RecordingKind = Literal["vocal", "off_vocal", "instrumental", "drama", "other"]


class Recording(Strict):
    id: str
    kind: RecordingKind = "vocal"
    title: Names | None = None  # display title when it differs from the work title
    version: str | None = None
    performers: list[Performer] = []
    arranger: list[Credit] = []
    credits_override: WorkCredits | None = None
    instrumental_of: str | None = None
    external_ids: dict[str, str] = {}
    evidence: dict[str, Evidence] = {}


WorkKind = Literal["song", "drama", "other"]


class Work(Strict):
    id: str
    kind: WorkKind = "song"
    project: str
    title: Names
    credits: WorkCredits = WorkCredits()
    recordings: list[Recording]
    external_ids: dict[str, str] = {}
    evidence: dict[str, Evidence] = {}


# --- releases -----------------------------------------------------------------


class Edition(Strict):
    id: str
    label: Names | None = None
    catalog: str | None = None
    media: list[str] = []
    release_date: dt.date | None = None


class Track(Strict):
    no: int | None = None
    recording: str  # "<work id>#<recording id>"
    title_as_printed: Names | None = None
    note: str | None = None
    category: str | None = None  # legacy category override


class Disc(Strict):
    disc: int = 1
    editions: Literal["all"] | list[str] = "all"
    tracks: list[Track]


class Streaming(Strict):
    platform: Literal["youtube_music"] = "youtube_music"
    editions: list[str] = []  # empty = every edition
    browse_id: str | None = None
    tracks: dict[str, str] = {}  # "<disc>-<position>" -> video id


class LegacyAlbum(Strict):
    title: str
    edition: str | None = None
    disc: int | None = None


class ReleaseLegacy(Strict):
    category: str | None = None
    albums: list[LegacyAlbum] = []


ReleaseType = Literal[
    "single", "album", "mini_album", "digital_single", "bd_bonus", "compilation",
    "soundtrack", "drama_cd", "live_video", "unclassified",
]


class Release(Strict):
    id: str
    type: ReleaseType = "unclassified"
    status: Literal["announced", "released", "verified"] = "released"
    title: Names
    projects: list[str]
    artist_credit: list[Performer] = []
    label: str | None = None
    release_date: dt.date | None = None
    editions: list[Edition] = []
    discs: list[Disc]
    streaming: list[Streaming] = []
    links: dict[str, str] = {}
    legacy: ReleaseLegacy = ReleaseLegacy()
    evidence: dict[str, Evidence] = {}


# --- concerts -----------------------------------------------------------------


class City(Strict):
    id: str
    names: Names


class Venue(Strict):
    id: str
    city: str | None = None
    names: Names
    external_ids: dict[str, str] = {}


SetlistType = Literal["song", "mc", "video", "encore", "double_encore", "talk", "other"]


class SetlistItem(Strict):
    type: SetlistType = "song"
    work: str | None = None
    recording: str | None = None
    performers: list[Performer] = []
    label: str | None = None  # literal marker text for unnumbered markers
    title_raw: str | None = None  # unresolved song title (E9)


class Performance(Strict):
    date: dt.date
    label: str | None = None
    setlist: list[SetlistItem] = []


class Stop(Strict):
    id: str
    city: str
    label: str | None = None
    venue: str
    performances: list[Performance]


class ConcertLegacy(Strict):
    event_code: str | None = None


class Concert(Strict):
    id: str
    projects: list[str]
    status: Literal["announced", "performed", "settled", "confirmed"] = "settled"
    title: Names
    stops: list[Stop]
    legacy: ConcertLegacy = ConcertLegacy()
    external_ids: dict[str, str] = {}
    evidence: dict[str, Evidence] = {}


# --- metadata and legacy layout ---------------------------------------------------


class Meta(Strict):
    schema_version: str
    db_last_update: str  # dbLastUpdate in TakasakiInfo.json; bumped when data changes


class LayoutAlbumEntry(Strict):
    release: str
    album: int = 0  # index into release.legacy.albums
    category: str | None = None  # per-file category when a release is listed in several group files


class LayoutAlbumsFile(Strict):
    bom: bool = True
    entries: list[LayoutAlbumEntry]


class LayoutMemberRow(Strict):
    character: str
    unit: str | None = None


class LayoutMembersFile(Strict):
    bom: bool = True
    rows: list[LayoutMemberRow]


class LegacyLayout(Strict):
    """Placement of entities in the legacy files, which are ordered by hand (DESIGN.md §10.1)."""

    integrated_order: list[str]
    albums: dict[str, LayoutAlbumsFile]
    members: dict[str, LayoutMembersFile]
    concerts: dict[str, list[str]]
