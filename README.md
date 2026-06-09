# Archetype Data Migration

This repository is the dedicated operational home for the Archetype legacy-to-current database migration.
It keeps the migration process outside the backend application while still running real database work through the backend Docker Compose runtime.

`tei_exporter/` is intentionally preserved as the existing TEI export utility and export collection. The rest of the active repository focuses on migration audit, planning, guarded import, manifests, and operator evidence.

## Repository Layout

| Path | Purpose |
| --- | --- |
| `migration_toolkit/` | Standalone Python package for audit, import, and procedure generation. |
| `commands/` | CLI entry points runnable with `python -m commands.<name>`. |
| `docs/` | Current migration guide, plan, audit notes, and target database map. |
| `manifests/` | Manifest template and operator-run metadata shape. |
| `reports/` | Generated audits/import reports. Committed only as selected evidence. |
| `scripts/` | Helpers for running the toolkit inside the backend Compose API container. |
| `tests/` | Unit tests for the toolkit and CLI wrappers. |
| `tei_exporter/` | Existing TEI exporter directory, left intact. |

## Runtime Model

For real database work, run the toolkit inside the backend API container:

```bash
BACKEND_REPO=../backend ./scripts/backend-compose-run.sh python -m commands.audit_legacy_migration --help
```

The backend checkout supplies the current Django environment, Postgres network, and dependency set. This repo supplies the migration code and reports.

Direct local Python is fine for unit tests and offline rendering, but trial/staging/production database operations should use the Compose helper.

## Configuration

Copy `.env.example` to `.env` and fill the values for your environment:

```bash
cp .env.example .env
```

Use explicit URLs for serious runs:

```text
LEGACY_DATABASE_URL=postgresql://<user>:<password>@<host>:<port>/<legacy_database>
TARGET_DATABASE_URL=postgresql://<user>:<password>@<host>:<port>/<target_database>
```

The toolkit can also derive a legacy URL from the target URL when both databases live on the same Postgres server. In that case set `LEGACY_DATABASE_NAME` and either `TARGET_DATABASE_URL` or `DATABASE_URL`.

## Common Commands

```bash
just test
just procedure
just audit
just dry-run-import
just execute-import <target-author-username>
```

Equivalent direct Compose commands:

```bash
./scripts/backend-compose-run.sh python -m commands.legacy_migration_procedure \
  --output docs/operator-guide.md \
  --manifest-template manifests/legacy-migration-manifest-template.json

./scripts/backend-compose-run.sh python -m commands.audit_legacy_migration \
  --format markdown \
  --output reports/legacy-migration-audit.md

./scripts/backend-compose-run.sh python -m commands.migrate_legacy_data \
  --manifest reports/legacy-migration-import-dry-run.json
```

Write imports require `--execute` and should only run after backups, audit review, and manifest sign-off.

For a disposable local execute test, follow [local-smoke-test.md](docs/local-smoke-test.md). Do not commit local database dumps or generated run reports unless the team explicitly wants them preserved as reviewed evidence.

## Backend Version Contract

Every trial or production run should record:

- backend git SHA
- migration repo git SHA
- Django migration state
- source database fingerprint
- target database fingerprint
- command arguments
- dry-run versus execute mode
- pre/post row counts
- accepted warnings
- backup file names, checksums, and restore location

The manifest template in `manifests/legacy-migration-manifest-template.json` is the starting point for that record.
