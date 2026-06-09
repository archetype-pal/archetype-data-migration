from __future__ import annotations

import argparse
from pathlib import Path
import sys

from migration_toolkit.audit import (
    LegacyMigrationAuditError,
    legacy_url_from_env,
    render_json,
    render_markdown,
    run_audit,
    target_url_from_env,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only audit of a legacy source database against the current Archetype schema."
    )
    parser.add_argument(
        "--legacy-url",
        default=None,
        help=(
            "Legacy PostgreSQL URL. Defaults to LEGACY_DATABASE_URL, or a database named by "
            "LEGACY_DATABASE_NAME derived from --target-url, TARGET_DATABASE_URL, or DATABASE_URL."
        ),
    )
    parser.add_argument(
        "--target-url",
        default=None,
        help=(
            "Target PostgreSQL URL. Defaults to TARGET_DATABASE_URL, DATABASE_URL, or a compose-style "
            "URL from TARGET_DATABASE_NAME/POSTGRES_DB and POSTGRES_* env."
        ),
    )
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown", help="Output format.")
    parser.add_argument("--output", type=Path, help="Optional output file path. Writes to stdout when omitted.")
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="Exit non-zero when the audit has warnings as well as hard failures.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    options = parser.parse_args(argv)
    target_url = options.target_url or target_url_from_env()
    legacy_url = options.legacy_url or legacy_url_from_env(base_url=target_url)

    try:
        report = run_audit(legacy_url=legacy_url, target_url=target_url)
    except LegacyMigrationAuditError as exc:
        parser.error(str(exc))

    rendered = render_json(report) if options.format == "json" else render_markdown(report)
    if options.output:
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(rendered, encoding="utf-8")
        print(f"Wrote legacy migration audit to {options.output}")
    else:
        print(rendered)

    if report.status == "fail" or (report.status == "warn" and options.fail_on_warning):
        print(f"Legacy migration audit completed with status: {report.status}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
