from __future__ import annotations

import argparse
from pathlib import Path
import sys

from migration_toolkit.audit import LegacyMigrationAuditError, legacy_url_from_env, run_audit, target_url_from_env
from migration_toolkit.procedure import render_manifest_template, render_procedure_json, render_procedure_markdown


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render the legacy migration operator guide and manifest template.")
    parser.add_argument(
        "--legacy-url",
        default=None,
        help=(
            "Legacy PostgreSQL URL. Used only with --with-live-audit. Defaults to LEGACY_DATABASE_URL, "
            "or a database named by LEGACY_DATABASE_NAME derived from --target-url, TARGET_DATABASE_URL, "
            "or DATABASE_URL."
        ),
    )
    parser.add_argument(
        "--target-url",
        default=None,
        help=(
            "Target PostgreSQL URL. Used only with --with-live-audit. Defaults to TARGET_DATABASE_URL, "
            "DATABASE_URL, or a compose-style URL from TARGET_DATABASE_NAME/POSTGRES_DB and POSTGRES_* env."
        ),
    )
    parser.add_argument(
        "--with-live-audit",
        action="store_true",
        help="Run the read-only audit and include its summary.",
    )
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown", help="Guide output format.")
    parser.add_argument("--output", type=Path, help="Optional guide output file path. Writes to stdout when omitted.")
    parser.add_argument("--manifest-template", type=Path, help="Optional path for a JSON migration manifest template.")
    parser.add_argument(
        "--fail-on-audit-failure",
        action="store_true",
        help="Exit non-zero when --with-live-audit returns fail status.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    options = parser.parse_args(argv)

    audit_report = None
    if options.with_live_audit:
        target_url = options.target_url or target_url_from_env()
        legacy_url = options.legacy_url or legacy_url_from_env(base_url=target_url)
        try:
            audit_report = run_audit(legacy_url=legacy_url, target_url=target_url)
        except LegacyMigrationAuditError as exc:
            parser.error(str(exc))

    rendered = (
        render_procedure_json(audit_report) if options.format == "json" else render_procedure_markdown(audit_report)
    )
    if options.output:
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(rendered, encoding="utf-8")
        print(f"Wrote legacy migration procedure to {options.output}")
    else:
        print(rendered)

    if options.manifest_template:
        options.manifest_template.parent.mkdir(parents=True, exist_ok=True)
        options.manifest_template.write_text(render_manifest_template(audit_report), encoding="utf-8")
        print(f"Wrote legacy migration manifest template to {options.manifest_template}")

    if audit_report and audit_report.status == "fail" and options.fail_on_audit_failure:
        print("Legacy migration procedure live audit completed with status: fail", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
