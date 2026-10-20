"""Canonical data model (DESIGN.md §4).

Every entity is stored as one YAML file under ``data/``. Models forbid unknown
keys so that typos in hand-edited files fail validation (E1) instead of being
silently ignored.

The docstring under each field is its description: it goes into the JSON Schema of the v1 files
and into the README's v1 schema tables, and the README build fails on a field without one (§10.3).
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, use_attribute_docstrings=True)


class Status(StrEnum):
    """Trust level of a value (DESIGN.md §4.4)."""

    official = "official"
    established = "established"
    derived = "derived"
    legacy = "legacy"
    draft = "draft"


class Names(Strict):
    """A name or title in each language."""

    ja: str | None = None
    """Japanese, as officially printed."""
    kana: str | None = None
    """Reading in kana: song titles (the legacy `pronunciation`) and Japanese names, spaced between family and
    given name."""
    rom: str | None = None
    """Romanization, or the official Latin-script form. People's names are given name first (`Aki Hata`)."""
    ko: str | None = None
    """Korean. A name whose official form is in Latin script keeps that form."""


# the source of a value as migrated from the legacy files (§12) before a source was found for it (D41)
MIGRATED = "migration:legacy"


class Evidence(Strict):
    """Where a value comes from."""

    status: Status
    """How far the value can be trusted. `official`: the rights holder's own; `established`: no official value,
    a widely used one whose source a person checked; `derived`: made by a rule and approved; `legacy`: from the
    hand-made lists, source not found yet; `draft`: not approved yet (kept out of the legacy files)."""
    source: str | None = None
    """URL the value was checked against."""
    checked: dt.date | None = None
    """When the source was last checked."""
    note: str | None = None
    """Why this source, or what differs from other sources (often in Korean)."""


# --- projects -----------------------------------------------------------------


class Copyright(Strict):
    text: str
    """Copyright notice as printed."""
    lang: str
    """Language of the notice (`ja`, `en`)."""
    source: str | None = None
    """Page the notice is printed on."""
    checked: dt.date | None = None
    """When the page was last checked."""


class ProjectLegacy(Strict):
    category: str
    """`Category` value of the project in the legacy files."""
    file: str
    """Name of the project's legacy files (`albums/<file>/<file>.csv`, `members/<file>.csv`, …)."""


class Project(Strict):
    id: str
    """Project id (`aqours`, `ikizulive`); `external` holds songs and characters from outside the series."""
    names: Names
    """Project name."""
    legacy: ProjectLegacy | None = None
    """How the project appears in the legacy files; absent for a project without files of its own."""
    copyright: list[Copyright] = []
    """Copyright notices of the project, as in the README's Disclaimer."""
    official: dict[str, str] = {}
    """Official accounts by kind: `site`, `youtube`, `x`."""
    evidence: dict[str, Evidence] = {}
    """Sources, keyed by the field they cover."""


# --- people -------------------------------------------------------------------


class Alias(Strict):
    text: str
    """The spelling as seen in a credit."""
    kind: Literal["variant", "misprint", "former"] = "variant"
    """`variant`: another spelling in use; `misprint`: a printing error; `former`: a former name."""
    note: str | None = None
    """Where the spelling was seen."""


class Person(Strict):
    """Japanese names keep the family/given split; ``names.ja`` and ``names.kana`` are written
    from it by the spacing rule (D28)."""

    id: str
    """Slug of the romanized name (`aki-hata`)."""
    names: Names
    """Name. `ja` and `kana` are spaced from `family_name` and `given_name`."""
    family_name: Names | None = None
    """Family name in each language."""
    given_name: Names | None = None
    """Given name in each language."""
    native_script: Literal["ja", "latin"] = "ja"
    """`latin` for a name whose original form is in Latin script; its `ko` is then the original."""
    aliases: list[Alias] = []
    """Other spellings seen in credits. Used to match credits, never printed."""
    distinct_from: list[str] = []
    """Ids of people with a similar name who are known to be someone else."""
    evidence: dict[str, Evidence] = {}
    """Sources, keyed by the field they cover (`names.ja`, `names.ko`, `name_parts`, …)."""


class Casting(Strict):
    person: str
    """Person id of the voice actor."""
    from_: dt.date | None = Field(default=None, alias="from")
    """First day of the casting; absent: from the start."""
    until: dt.date | None = None
    """Last day of the casting; absent: to date."""


class Character(Strict):
    """The family/given split lives in ``family_name`` / ``given_name`` (D26); ``names.ja`` is
    written from it by the spacing rule (D28)."""

    id: str
    """`<project>/<slug>` (`nijigasaki/setsuna-yuki`)."""
    project: str
    """Project id; `external` for a character from outside the series."""
    names: Names
    """Name. `ja` is spaced from `family_name` and `given_name`."""
    family_name: Names | None = None
    """Family name in each language."""
    given_name: Names | None = None
    """Given name in each language."""
    casting: list[Casting] = []
    """Voice actors over time."""
    distinct_from: list[str] = []
    """Ids of characters with a similar name who are known to be someone else."""
    evidence: dict[str, Evidence] = {}
    """Sources, keyed by the field they cover."""


class Lineup(Strict):
    from_: dt.date | None = Field(default=None, alias="from")
    """First day of this lineup; absent: from the start."""
    until: dt.date | None = None
    """Last day of this lineup; absent: to date."""
    members: list[str]
    """Character ids of the members."""


ArtistKind = Literal["group", "unit", "solo", "cross_unit", "collab", "special", "unclassified"]


class ArtistLegacy(Strict):
    category: str | None = None


class Artist(Strict):
    id: str
    """Slug of the romanized name (`ikizuraibu`, `cerise-bouquet`)."""
    kind: ArtistKind
    """What the artist is. `cross_unit`: a unit of members from several projects (AiScReam); `collab`: two artists
    singing as one (Saint Aqours Snow); `special`: a one-off ensemble (浦の星交響楽団)."""
    projects: list[str] = []
    """Project ids the artist belongs to."""
    names: Names
    """Name."""
    lineups: list[Lineup] = []
    """Members over time."""
    distinct_from: list[str] = []
    """Ids of artists with a similar name that are known to be another."""
    evidence: dict[str, Evidence] = {}
    """Sources, keyed by the field they cover."""


# --- works and recordings -----------------------------------------------------


class Credit(Strict):
    """One credited person, or a character credited in-story (高咲侑 on Hurray Hurray, D27).
    ``role`` holds the character a cast member is credited as (e.g. musical cast credited as
    lyricists: ``堀内まり菜（椿 ルリカ役）``)."""

    person: str | None = None
    """Person id. Exactly one of `person` and `character` is set."""
    character: str | None = None
    """Character id, for a character credited in-story (高咲 侑 on Hurray Hurray)."""
    affiliation: str | Names | None = None  # D31
    """Affiliation printed after the name, `名前(所属)`; a names object when the spelling differs by language."""
    fullwidth: bool = False  # D42
    """The cited official page prints the affiliation in full-width brackets, `名前（所属）`; `ja` keeps them,
    `rom` and `ko` are half-width."""
    role: Names | None = None
    """The role a cast member is credited as (`椿 ルリカ役`)."""

    def affiliation_in(self, lang: str) -> str | None:
        if isinstance(self.affiliation, Names):
            return getattr(self.affiliation, lang)
        return self.affiliation

    @model_validator(mode="after")
    def _exactly_one(self) -> Credit:
        if (self.person is None) == (self.character is None):
            raise ValueError("credit needs exactly one of person / character")
        if self.fullwidth and not self.affiliation:
            raise ValueError("fullwidth is about the brackets of an affiliation")
        return self

    @property
    def ref(self) -> tuple[str, str]:
        return ("person", self.person) if self.person else ("character", self.character)  # type: ignore[return-value]


class Performer(Strict):
    """An artist, a character, or a person. A person singing in a role (musical cast,
    ``堀内まり菜（椿ルリカ役）``) names the character in ``role`` (D29). A credit that names several
    performers as one is not an artist of its own (D48): a guest after ``feat.`` is ``featured``
    (``Aqours feat. 初音ミク``), and the performers of a joint name are each ``joint``
    (``Aqours・虹ヶ咲学園スクールアイドル同好会・Liella!``). The builders print the credit from them."""

    artist: str | None = None
    """Artist id. Exactly one of `artist`, `character` and `person` is set."""
    character: str | None = None
    """Character id, for a credit that lists characters rather than a group name."""
    person: str | None = None
    """Person id: a cast member singing in a role (see `role`) or as themselves."""
    role: str | None = None
    """Character id of the role sung; only with `person`."""
    featured: bool = False
    """A guest, printed after `feat.` (`Aqours feat. 初音ミク`)."""
    joint: bool = False
    """One of the performers of a joint name, printed joined with `・`
    (`Aqours・虹ヶ咲学園スクールアイドル同好会・Liella!`)."""

    @model_validator(mode="after")
    def _exactly_one(self) -> Performer:
        if sum(x is not None for x in (self.artist, self.character, self.person)) != 1:
            raise ValueError("performer needs exactly one of artist / character / person")
        if self.role is not None and self.person is None:
            raise ValueError("role is only for a person")
        if self.featured and self.joint:
            raise ValueError("a performer is featured or part of a joint name, not both")
        return self

    @property
    def ref(self) -> tuple[str, str]:
        if self.artist:
            return ("artist", self.artist)
        if self.character:
            return ("character", self.character)
        return ("person", self.person)  # type: ignore[return-value]


def _credit_shape(performers: list[Performer]) -> list[Performer]:
    if performers and all(p.featured for p in performers):
        raise ValueError("featured performers need a performer to feature them (D48)")
    joint = [i for i, p in enumerate(performers) if p.joint]
    if joint and (len(joint) < 2 or joint != list(range(joint[0], joint[-1] + 1))):
        raise ValueError("a joint name credits two or more performers next to each other (D48)")
    return performers


PerformerList = Annotated[list[Performer], AfterValidator(_credit_shape)]


class WorkCredits(Strict):
    lyricist: list[Credit] = []
    """作詞."""
    composer: list[Credit] = []
    """作曲."""


RecordingKind = Literal["vocal", "off_vocal", "instrumental", "drama", "other"]


class Recording(Strict):
    id: str
    """Id within the work (`original`, `off-vocal`, `kanon-ver`). The full recording id is `<work id>#<id>`."""
    kind: RecordingKind = "vocal"
    """What the recording is. Credits that do not apply (no singer on an off vocal) are empty lists."""
    title: Names | None = None
    """Title as printed, when it differs from the work title."""
    version: str | None = None
    """Version label as printed (`Off Vocal`, `104期 Ver.`, `高海千歌 Solo Ver.`)."""
    performers: PerformerList = []
    """Singers."""
    arranger: list[Credit] = []
    """編曲."""
    # 弦編曲 and 管編曲, printed apart from 編曲 (D42); 弦管編曲 credits the person in both
    strings_arranger: list[Credit] = []
    """弦編曲 (strings arrangement)."""
    brass_arranger: list[Credit] = []
    """管編曲 (brass arrangement)."""
    credits_override: WorkCredits | None = None
    """Lyricist and composer of this recording when they differ from the work's (rare; the evidence says why)."""
    instrumental_of: str | None = None
    """For an off vocal or instrumental: id of the vocal recording in the same work."""
    external_ids: dict[str, str] = {}
    """Ids elsewhere: `isrc`."""
    evidence: dict[str, Evidence] = {}
    """Sources, keyed by the field they cover."""

    def all_arrangers(self) -> list[Credit]:
        """編曲, then 弦編曲 and 管編曲, each person once: the legacy Arranger column (D42)."""
        out: list[Credit] = []
        for c in self.arranger + self.strings_arranger + self.brass_arranger:
            if all(c.ref != x.ref for x in out):
                out.append(c)
        return out


WorkKind = Literal["song", "bgm", "drama", "other"]  # bgm: a soundtrack cue played at a concert (D50)


class Work(Strict):
    id: str
    """`<project>/<slug>` (`ikizulive/dou-da-doing`)."""
    kind: WorkKind = "song"
    """What the work is. `bgm`: a soundtrack cue played at a concert."""
    project: str
    """Project id; `external` for a song from outside the series (a cover, a song of another franchise)."""
    title: Names
    """Title."""
    credits: WorkCredits = WorkCredits()
    """Lyricist and composer. Arrangers and singers are on each recording."""
    recordings: list[Recording]
    """Recordings of the work. Empty for a song with no recording in the data (performed live only so far, or
    released only on a release not in the data, such as a soundtrack or a fan club CD)."""
    external_ids: dict[str, str] = {}
    """Ids elsewhere: `fandom` (title of the Love Live! Fandom article, for matching set lists)."""
    evidence: dict[str, Evidence] = {}
    """Sources, keyed by the field they cover (`title`, `title.ko`, `credits`, …)."""


# --- releases -----------------------------------------------------------------


class Edition(Strict):
    id: str
    """Id within the release (`e1`, `e2`, …)."""
    label: Names | None = None
    """Edition name as printed (`初回生産限定盤`, `通常盤`, `【上原歩夢盤】`)."""
    catalog: str | None = None
    """Catalog number (品番), as printed (`LACM-24755`)."""
    media: list[str] = []
    """Discs in the package in order, one entry per disc: `CD`, `BD`, `DVD`; `digital` for a digital-only edition
    (`[CD, BD, BD]`)."""
    release_date: dt.date | None = None
    """Release date of this edition, when it differs from the release's."""


class Track(Strict):
    no: int | None = None
    """Track number as printed; absent for an unnumbered track."""
    recording: str
    """Recording id, `<work id>#<recording id>`."""
    title_as_printed: Names | None = None
    """Title as printed on this release, when it differs from the recording's."""
    note: str | None = None  # see LegacyAlbum
    """What is true of this track only (tie-in, act, version label); goes into the legacy `Note`."""
    category: str | None = None
    """Legacy `Category` of this track, when it differs from the release's."""


class Disc(Strict):
    disc: int = 1
    """Disc number."""
    editions: Literal["all"] | list[str] = "all"
    """`all`, or the ids of the editions with this disc, when the editions' track lists differ."""
    tracks: list[Track]
    """Tracks in order. A track's streaming key is `<disc>-<position in this list>`."""


class Streaming(Strict):
    platform: Literal["youtube_music"] = "youtube_music"
    """Streaming service."""
    editions: list[str] = []
    """Ids of the editions this album stands for; empty: every edition."""
    browse_id: str | None = None
    """YouTube Music album id (`MPREb_…`): `https://music.youtube.com/browse/<browse_id>`."""
    tracks: dict[str, str] = {}
    """Video id of each track on this album, keyed `<disc>-<position>` (`1-1`): `https://youtu.be/<video id>`.
    Only the album's own videos: a track missing here falls back to the same recording on another release
    (`tracks.json` gives which)."""


class LegacyAlbum(Strict):
    """One album in the legacy files. Its Note column is built from parts (M3): ``Disc.N`` when
    ``flatten_discs``, ``Drama Part`` from the recording kind, ``note`` (the whole album), the
    track's own note, then ``Link is from the [...]`` when the URL is a main-URL fallback."""

    title: str
    """Album name in the legacy files."""
    edition: str | None = None
    """Edition id whose tracks the album lists; absent: the discs every edition shares."""
    disc: int | None = None
    """Only this disc."""
    note: str | None = None
    """Legacy `Note` for every track of the album."""
    flatten_discs: bool = False
    """Several discs listed as one album, with running track numbers and `Disc.N` in the Note."""


class ReleaseLegacy(Strict):
    category: str | None = None
    """Legacy `Category` of the release's tracks."""
    albums: list[LegacyAlbum] = []
    """The albums the release is listed as in the legacy files; empty: not in them."""


ReleaseType = Literal[
    "single", "album", "mini_album", "digital_single", "bd_bonus", "compilation",
    "soundtrack", "drama_cd", "live_video", "unclassified",
]


class Release(Strict):
    id: str
    """`<project>/<year>-<slug>` (`ikizulive/2025-homerun-queen`)."""
    type: ReleaseType = "unclassified"
    """Kind of release. `digital_single`: released only for download and streaming; `bd_bonus`: a CD that comes
    with a Blu-ray."""
    status: Literal["announced", "released", "verified"] = "released"
    """`announced`: not out yet (left out of the legacy files); `released`: out; `verified`: checked again after
    release, with no change."""
    title: Names
    """Title. In v1, `rom` and `ko` not stored are filled in from the song titles (`A / B`) or from a Latin-script
    title."""
    projects: list[str]
    """Project ids; more than one for a cross-project release."""
    artist_credit: PerformerList = []
    """Artist of the release as a whole, as credited."""
    label: str | None = None
    """Record label (`Lantis`)."""
    release_date: dt.date | None = None
    """Release date. An edition released on another day has its own."""
    editions: list[Edition] = []
    """Editions (初回限定盤, 通常盤, …) with their catalog numbers and media."""
    discs: list[Disc]
    """Track list, disc by disc."""
    streaming: list[Streaming] = []
    """YouTube Music albums of the release, one entry per album."""
    links: dict[str, str] = {}
    """Pages about the release. `official`: its page on the official site; `smartlink`: the label's link page to
    every download and streaming service (`https://lnk.to/…`, the 楽曲配信 link of the official page);
    `musicbrainz`: its MusicBrainz release."""
    legacy: ReleaseLegacy = ReleaseLegacy()
    """How the release appears in the legacy files."""
    evidence: dict[str, Evidence] = {}
    """Sources, keyed by the field they cover (`tracks`, `editions`, `release_date`, `streaming`, `title`, …)."""


# --- concerts -----------------------------------------------------------------


class City(Strict):
    id: str
    """Slug of the romanized name (`tokyo`, `seoul`)."""
    names: Names
    """Name."""
    evidence: dict[str, Evidence] = {}
    """Sources, keyed by the field they cover."""


class Venue(Strict):
    id: str
    """Slug of the romanized name (`makuhari-event-hall`)."""
    city: str | None = None
    """City id."""
    names: Names
    """Name at the time of the shows."""
    external_ids: dict[str, str] = {}
    """Ids elsewhere: `fandom` (title of the venue's Love Live! Fandom article)."""
    evidence: dict[str, Evidence] = {}
    """Sources, keyed by the field they cover."""


SetlistType = Literal["song", "mc", "video", "encore", "double_encore", "talk", "other"]


class SetlistItem(Strict):
    type: SetlistType = "song"
    """A song, or a marker: `mc`, `video`, `encore` (start of the encore), `double_encore`, `talk` (a character
    talk), `other` (a game, a sports-day event)."""
    work: str | None = None
    """Work id of the song."""
    recording: str | None = None
    """Recording id, when the version sung is a released recording."""
    version: str | None = None  # §4.6
    """Version sung, when no recording of it is linked (`104th Class Ver.`)."""
    performers: PerformerList = []
    """Who sang it."""
    label: str | None = None
    """Marker text as listed (`Encore`, `Opening`, `Talk Portion`)."""
    title_raw: str | None = None  # E9
    """Song title as listed, when it is not matched to a work yet."""


class Performance(Strict):
    date: dt.date
    """Day of the show."""
    label: str | None = None
    """Show label (`Day.1`, `Day.2 Noon`)."""
    cast: PerformerList = []
    """Cast of this show when it differs from the concert's: the whole list, which replaces the concert's."""
    setlist: list[SetlistItem] = []
    """Set list in order."""
    external_ids: dict[str, str] = {}  # D47
    """Ids elsewhere: `fandom` (the set-list tab the list is read from, `<section>|<tab>`)."""


class Stop(Strict):
    id: str
    """Id within the concert, `<n>-<city>` (`1-osaka`)."""
    city: str | None = None
    """City id; absent for an online-only show."""
    label: str | None = None
    """Stop label (`Trip to Asia`, `with DOLLCHESTRA`)."""
    venue: str | None = None
    """Venue id."""
    performances: list[Performance]
    """Shows at this stop, day by day."""


class ConcertLegacy(Strict):
    event_code: str | None = None
    """`eventCode` in the legacy concert files (`Liella_1st`)."""


class Concert(Strict):
    id: str
    """`<project>/<slug>`."""
    projects: list[str]
    """Project ids."""
    status: Literal["announced", "performed", "settled", "confirmed"] = "settled"
    """`announced`: schedule only; `performed`: set lists drafted from Fandom; `settled`: set lists cross-checked
    and approved; `confirmed`: set lists as on the official Blu-ray or stream. The legacy files list `settled` and
    `confirmed` concerts only."""
    title: Names
    """Concert title."""
    cast: PerformerList = []
    """Cast of every show as the official live page announces it: a voice actor as the character they play, a
    stage actor as a person in a role. `featured`: a guest or support appearance (ゲスト出演, 応援出演). A show
    with another cast lists its own."""
    stops: list[Stop]
    """Stops of the tour (city, venue, shows)."""
    legacy: ConcertLegacy = ConcertLegacy()
    """How the concert appears in the legacy files."""
    external_ids: dict[str, str] = {}
    """Ids elsewhere: `fandom` (title of the concert's Love Live! Fandom article)."""
    evidence: dict[str, Evidence] = {}
    """Sources, keyed by the field they cover (`title`, `schedule`, `cast`, `setlist.<date>`, …)."""


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
