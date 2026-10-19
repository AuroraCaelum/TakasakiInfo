"""``takasaki`` command line (DESIGN.md §11)."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from .build_legacy import build_legacy, write_outputs
from .store import dump_model, load_dataset, repo_root, save_dataset


def _paths() -> tuple[Path, Path, Path]:
    root = repo_root()
    return root, root / "data", root / "automation" / "review"


def cmd_build(args: argparse.Namespace) -> int:
    from .readme import build_outputs

    root, data, _ = _paths()
    files = build_outputs(load_dataset(data))
    out = Path(args.out).resolve() if args.out else root
    changed = write_outputs(files, out)
    print(f"{len(files)} generated files (legacy files and README), {len(changed)} written to {out}")
    for rel in changed:
        print(f"  {rel}")
    return 0


def cmd_dist(args: argparse.Namespace) -> int:
    """v1 files, JSON Schema, quality metrics and the SQLite database (§10.2, §10.5) under dist/."""
    from .build_sqlite import build_sqlite
    from .build_v1 import build_v1

    root, data, review = _paths()
    ds = load_dataset(data)
    out = Path(args.out).resolve() if args.out else root / "dist"
    files = build_v1(ds, review)
    changed = write_outputs(files, out)
    build_sqlite(ds, out / "takasakiinfo.sqlite")
    print(f"{len(files)} v1 files ({len(changed)} written) and takasakiinfo.sqlite in {out}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """E8: committed legacy files and README must equal a fresh build (nobody edits generated files)."""
    from .readme import build_outputs

    root, data, _ = _paths()
    files = build_outputs(load_dataset(data))
    stale = [rel for rel, blob in sorted(files.items()) if not (root / rel).exists() or (root / rel).read_bytes() != blob]
    if stale:
        print("[E8] generated files differ from a fresh build (run `takasaki build`):")
        for rel in stale:
            print(f"  {rel}")
        return 1
    print(f"[E8] ok: {len(files)} generated files match the build")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from .validate import validate

    _, data, review = _paths()
    findings = validate(load_dataset(data), review)
    errors = [f for f in findings if f.level == "error"]
    warns = [f for f in findings if f.level == "warn"]
    for f in errors:
        print(f"ERROR {f}")
    shown = warns if args.verbose else warns[:20]
    for f in shown:
        print(f"warn  {f}")
    if len(warns) > len(shown):
        print(f"warn  … {len(warns) - len(shown)} more (use -v)")
    print(f"{len(errors)} errors, {len(warns)} warnings")
    return 1 if errors else 0


def cmd_stamp(args: argparse.Namespace) -> int:
    """Bump dbLastUpdate after a data change (§10.4: the build itself never reads the clock)."""
    _, data, _ = _paths()
    ds = load_dataset(data)
    assert ds.meta is not None
    ds.meta.db_last_update = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    (data / "meta.yaml").write_text(dump_model(ds.meta), encoding="utf-8", newline="\n")
    print(f"dbLastUpdate = {ds.meta.db_last_update}")
    return 0


def cmd_review_apply(args: argparse.Namespace) -> int:
    from .review import ReviewError, apply_reviews

    _, data, review = _paths()
    ds = load_dataset(data)
    try:
        applied = apply_reviews(ds, review)
    except ReviewError as e:
        print(f"error: {e}")
        return 1
    if not applied:
        print("no review item has a decision")
        return 0
    assert ds.meta is not None
    ds.meta.db_last_update = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    save_dataset(ds, data)
    for a in applied:
        print(f"{a.path.name}: {a.message}")
        a.path.unlink()
    print(f"{len(applied)} items applied; run `takasaki build` to regenerate the legacy files")
    return 0


def cmd_deploy(args: argparse.Namespace) -> int:
    """Upload a release; with --promote also make it live (DESIGN.md §10.4)."""
    import boto3  # deploy-only dependency (uv sync --group deploy)

    from .deploy import Deployer, DeployError, release_files

    _, data, _ = _paths()
    files = release_files(load_dataset(data), args.sha, _paths()[2])
    deployer = Deployer(
        boto3.client("s3"), boto3.client("cloudfront"),
        bucket=args.bucket, distribution_id=args.distribution, base_url=args.base_url,
    )
    try:
        deployer.run(args.sha, files, promote=args.promote)
    except DeployError as e:
        print(f"deploy failed: {e}")
        return 1
    return 0


def _ytm_client(root: Path):  # noqa: ANN202 - ytmusicapi is an optional dependency (uv sync --group sync)
    from .ytmusic import Client, default_auth

    return Client(default_auth(root / "automation"), root / "automation" / ".cache" / "ytm")


def _write_review(path: Path, doc: dict) -> None:
    import io

    from .store import _to_node, _yaml

    buf = io.StringIO()
    _yaml().dump(_to_node(doc), buf)
    path.parent.mkdir(parents=True, exist_ok=True)  # git drops the folder once every item is closed
    path.write_text(buf.getvalue(), encoding="utf-8", newline="\n")


def cmd_ytm_match(args: argparse.Namespace) -> int:
    """Find each release's YouTube Music album and fill its tracks' own video ids (§7.2, L0)."""
    from .ytmusic import SKIP_TYPES, apply_matches, plan_release, review_doc

    root, data, review = _paths()
    ds = load_dataset(data)
    client = _ytm_client(root)
    rels = [r for r in ds.releases.values()
            if (not args.release or r.id in args.release) and (not args.project or args.project in r.projects)
            and r.type not in SKIP_TYPES and r.status != "announced"]  # not out yet: nothing to find
    today = dt.date.today().isoformat()
    applied = added = replaced = absent = 0
    reviews: list[str] = []
    for rel in rels:
        matches, ok = plan_release(client, ds, rel)
        slug = rel.id.replace("/", "-")
        if not ok:
            reviews.append(rel.id)
            print(f"review  {rel.id}: " + "; ".join(f"{mt.edition or '-'}: {mt.reason}" for mt in matches if not mt.chosen))
            if args.apply:
                _write_review(review / f"YTM-{slug}.yaml", review_doc(rel, matches))
            continue
        if all(mt.reason == "absent" for mt in matches):
            absent += 1
            print(f"absent  {rel.id}: not on YouTube Music, nothing stored")
            continue
        if not args.apply:
            print(f"match   {rel.id}: " + "; ".join(f"{mt.edition or '-'} → {mt.chosen.title}" if mt.chosen else f"{mt.edition}: no own album"
                                                for mt in matches))
            continue
        out = apply_matches(client, rel, matches, today)
        applied += 1
        added += out.added
        replaced += out.replaced
        print(f"applied {rel.id}: +{out.added} new, {out.replaced} dead replaced" + (f", {len(out.kept_live)} live kept" if out.kept_live else ""))
        if out.kept_live:
            _write_review(review / f"YTM-change-{slug}.yaml", review_doc(rel, matches, out.kept_live))
    # bonus CDs are not distributed: a stored id there was copied from another album; drop it once it is dead
    dropped = 0
    if args.apply:
        for rel in ds.releases.values():
            if rel.type not in SKIP_TYPES or not rel.streaming or (args.release and rel.id not in args.release) \
                    or (args.project and args.project not in rel.projects):
                continue
            for s in rel.streaming:
                dead = [k for k, v in s.tracks.items() if client.status(v) != "OK"]
                for k in dead:
                    del s.tracks[k]
                dropped += len(dead)
                if dead:
                    print(f"dropped {rel.id}: {len(dead)} dead id(s) copied from another album")
            rel.streaming = [s for s in rel.streaming if s.tracks]
        applied += bool(dropped)
    if args.apply and applied:
        assert ds.meta is not None
        ds.meta.db_last_update = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        save_dataset(ds, data)
    verb = "applied" if args.apply else "would apply"
    print(f"{len(rels)} releases: {verb} {applied if args.apply else len(rels) - len(reviews) - absent}, review {len(reviews)}, absent {absent}"
          + (f"; {added} ids added, {replaced} dead ids replaced, {dropped} dead copies dropped" if args.apply else ""))
    return 0


def cmd_ytm_links(args: argparse.Namespace) -> int:
    """W7: check that every stored own video id still plays (needs the logged-in session)."""
    import collections
    import json

    root, data, _ = _paths()
    ds = load_dataset(data)
    client = _ytm_client(root)
    seen: dict[str, tuple[str, str]] = {}
    for rel in ds.releases.values():
        for s in rel.streaming:
            for key, vid in s.tracks.items():
                seen.setdefault(vid, (rel.id, key))
    report = [{"video_id": vid, "release": r, "key": k, "status": client.status(vid)} for vid, (r, k) in seen.items()]
    by_project = collections.Counter((r["release"].split("/")[0], r["status"] == "OK") for r in report)
    for proj in sorted({p for p, _ in by_project}):
        print(f"{proj:12s} playable {by_project[(proj, True)]:4d} / {by_project[(proj, True)] + by_project[(proj, False)]}")
    dead = [r for r in report if r["status"] != "OK"]
    print(f"[W7] {len(dead)} of {len(report)} video ids do not play")
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def cmd_official(args: argparse.Namespace) -> int:
    """Read the project's official site and upsert what it lists (§7.2 ③). New names go to review first."""
    import importlib

    from .official import Fetcher

    adapter = importlib.import_module(f".{args.project}", __package__)
    collect, import_site = adapter.collect, adapter.import_site
    root, data, review = _paths()
    ds = load_dataset(data)
    cache = root / "automation" / ".cache" / "official"
    fetcher = Fetcher(cache, root / "automation" / "inbox" / args.project, offline=args.offline)
    site = collect(fetcher, fresh=args.fresh)
    print(f"read {len(site.releases)} releases and {len(site.members)} members from the official site")
    report = import_site(ds, site, review if args.apply else root / "automation" / ".cache" / "review-dry-run", dt.date.today())
    for label, rows in (("created", report.created), ("updated", report.updated), ("pending", report.pending),
                        ("conflict", report.conflicts), ("skipped", report.skipped)):
        for row in rows:
            print(f"{label:8} {row}")
    if report.pending:
        print(f"{len(report.pending)} names need readings: fill automation/review/{adapter.SPEC.review_prefix}-*.yaml and run again")
    if args.apply and (report.created or report.updated):
        assert ds.meta is not None
        ds.meta.db_last_update = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        save_dataset(ds, data)
    elif not args.apply:
        print("dry run: nothing written (--apply writes data/ and the review files)")
    return 1 if report.conflicts else 0


def _report(report) -> None:  # type: ignore[no-untyped-def]
    for label, rows in (("created", report.created), ("updated", report.updated), ("pending", report.pending),
                        ("conflict", report.conflicts), ("skipped", report.skipped)):
        for row in rows:
            print(f"{label:8} {row}")


def cmd_fandom_concerts(args: argparse.Namespace) -> int:
    """Read the set lists of the concerts that name a Fandom page (§7.7 ②, D47)."""
    from . import fandom
    from .concerts import import_setlists
    from .official import Fetcher

    root, data, review = _paths()
    ds = load_dataset(data)
    fetcher = Fetcher(root / "automation" / ".cache" / "fandom", interval=3.0, offline=args.offline)
    wanted = sorted({c.external_ids["fandom"] for c in ds.concerts.values() if "fandom" in c.external_ids})
    pages = {t: fandom.parse_response(fetcher.get(fandom.wikitext_url(t), fresh=args.fresh).html) for t in wanted}
    print(f"read {len(pages)} Fandom concert pages")
    report = import_setlists(ds, pages, review if args.apply else root / "automation" / ".cache" / "review-dry-run",
                             dt.date.today())
    _report(report)
    if args.apply and report.updated:
        assert ds.meta is not None
        ds.meta.db_last_update = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        save_dataset(ds, data)
    elif not args.apply:
        print("dry run: nothing written (--apply writes data/ and the review file)")
    return 1 if report.conflicts else 0


def cmd_concerts_schedule(args: argparse.Namespace) -> int:
    """Create the concerts of a schedule file with their venues and cities (D47)."""
    from ruamel.yaml import YAML

    from .concerts import import_schedule

    root, data, review = _paths()
    ds = load_dataset(data)
    entries = YAML(typ="safe").load(Path(args.file).read_text(encoding="utf-8"))
    report = import_schedule(ds, entries, review if args.apply else root / "automation" / ".cache" / "review-dry-run",
                             dt.date.today())
    _report(report)
    if args.apply and (report.created or report.updated):
        assert ds.meta is not None
        ds.meta.db_last_update = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        save_dataset(ds, data)
    elif not args.apply:
        print("dry run: nothing written (--apply writes data/ and the review files)")
    return 1 if report.conflicts else 0


def cmd_migrate(args: argparse.Namespace) -> int:
    from .migrate_legacy import migrate
    from .report import write_migration_report

    root, data, review = _paths()
    if data.exists() and any(data.iterdir()) and not args.force:
        print(f"{data} already exists; pass --force to overwrite it from the legacy files")
        return 1
    res = migrate(root)
    n = save_dataset(res.ds, data)
    report = write_migration_report(root, res, review)
    print(f"wrote {n} files under {data}")
    print(f"report: {report}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="takasaki", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="generate the legacy files and README.md from data/")
    b.add_argument("--out", help="output directory (default: repository root)")
    b.set_defaults(func=cmd_build)
    ds_ = sub.add_parser("dist", help="build the v1 files and the SQLite database (not committed; deploy uploads them)")
    ds_.add_argument("--out", help="output directory (default: <repo>/dist)")
    ds_.set_defaults(func=cmd_dist)
    sub.add_parser("check", help="E8: verify committed legacy files equal a fresh build").set_defaults(func=cmd_check)
    v = sub.add_parser("validate", help="run validation rules (DESIGN.md §8)")
    v.add_argument("-v", "--verbose", action="store_true")
    v.set_defaults(func=cmd_validate)
    sub.add_parser("stamp", help="bump dbLastUpdate in data/meta.yaml").set_defaults(func=cmd_stamp)
    rv = sub.add_parser("review", help="review items under automation/review/ (§7.3)")
    rv_sub = rv.add_subparsers(dest="review_cmd", required=True)
    rv_sub.add_parser("apply", help="apply every item that has a decision").set_defaults(func=cmd_review_apply)
    dp = sub.add_parser("deploy", help="upload a data release to S3; --promote makes it live (§10.4)")
    dp.add_argument("--bucket", required=True)
    dp.add_argument("--distribution", required=True, help="CloudFront distribution id")
    dp.add_argument("--base-url", required=True, help="https://<id>.cloudfront.net")
    dp.add_argument("--sha", required=True, help="git commit of the release")
    dp.add_argument("--promote", action="store_true", help="copy into data/ + site/, invalidate, smoke test")
    dp.set_defaults(func=cmd_deploy)
    yt = sub.add_parser("ytm", help="YouTube Music adapter (§7.2); needs `uv sync --group sync` and automation/browser.json")
    yt_sub = yt.add_subparsers(dest="ytm_cmd", required=True)
    ym = yt_sub.add_parser("match", help="find release albums and fill own video ids (dry run unless --apply)")
    ym.add_argument("--release", action="append", help="release id (repeatable)")
    ym.add_argument("--project")
    ym.add_argument("--apply", action="store_true", help="write data/ and review items")
    ym.set_defaults(func=cmd_ytm_match)
    yl = yt_sub.add_parser("links", help="W7: report stored video ids that no longer play")
    yl.add_argument("--json", help="write the full report here")
    yl.set_defaults(func=cmd_ytm_links)
    of = sub.add_parser("official", help="official-site adapter (§7.2 ③): read releases and members, upsert them")
    of.add_argument("project", choices=["ikizulive", "hasunosora", "nijigasaki", "liella", "aqours", "musical", "muse", "yohane"])
    of.add_argument("--apply", action="store_true", help="write data/ and the new-names review files")
    of.add_argument("--fresh", action="store_true", help="download pages again even when cached")
    of.add_argument("--offline", action="store_true", help="use cached pages only")
    of.set_defaults(func=cmd_official)
    fd = sub.add_parser("fandom", help="Love Live! Fandom adapter (§7.7 ②)")
    fd_sub = fd.add_subparsers(dest="fandom_cmd", required=True)
    fc = fd_sub.add_parser("concerts", help="read the set lists of the concerts that name a Fandom page")
    fc.add_argument("--apply", action="store_true", help="write data/ and the unresolved-songs review file")
    fc.add_argument("--fresh", action="store_true", help="download pages again even when cached")
    fc.add_argument("--offline", action="store_true", help="use cached pages only")
    fc.set_defaults(func=cmd_fandom_concerts)
    co = sub.add_parser("concerts", help="concert schedules (§7.7)")
    co_sub = co.add_subparsers(dest="concerts_cmd", required=True)
    cs = co_sub.add_parser("schedule", help="create the concerts of a schedule file (status performed)")
    cs.add_argument("file")
    cs.add_argument("--apply", action="store_true", help="write data/ and the LIV-* review files")
    cs.set_defaults(func=cmd_concerts_schedule)
    mg = sub.add_parser("migrate", help="one-time import of the legacy files into data/ (§12)")
    mg.add_argument("--force", action="store_true")
    mg.set_defaults(func=cmd_migrate)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
