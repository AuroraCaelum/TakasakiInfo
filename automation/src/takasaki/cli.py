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
    root, data, _ = _paths()
    files = build_legacy(load_dataset(data))
    out = Path(args.out).resolve() if args.out else root
    changed = write_outputs(files, out)
    print(f"{len(files)} legacy files, {len(changed)} written to {out}")
    for rel in changed:
        print(f"  {rel}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """E8: committed legacy files must equal a fresh build (nobody edits generated files)."""
    root, data, _ = _paths()
    files = build_legacy(load_dataset(data))
    stale = [rel for rel, blob in sorted(files.items()) if not (root / rel).exists() or (root / rel).read_bytes() != blob]
    if stale:
        print("[E8] generated files differ from a fresh build (run `takasaki build`):")
        for rel in stale:
            print(f"  {rel}")
        return 1
    print(f"[E8] ok: {len(files)} legacy files match the build")
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
    (data / "meta.yaml").write_text(dump_model(ds.meta), encoding="utf-8")
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
    files = release_files(load_dataset(data), args.sha)
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
    b = sub.add_parser("build", help="generate legacy files from data/")
    b.add_argument("--out", help="output directory (default: repository root)")
    b.set_defaults(func=cmd_build)
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
    mg = sub.add_parser("migrate", help="one-time import of the legacy files into data/ (§12)")
    mg.add_argument("--force", action="store_true")
    mg.set_defaults(func=cmd_migrate)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
