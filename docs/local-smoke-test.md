# Local Disposable Smoke Test

This procedure verifies the migration toolkit against a throwaway target database.
It is for local operator confidence before staging or production work.

The disposable database itself is not committed to this repository. Keep only the
procedure and, if useful, selected reviewed reports. The generated `reports/*.json`
files are ignored by default.

## Requirements

- Docker Desktop is running.
- The backend repo is available beside this repo, or `BACKEND_REPO` points to it.
- The backend Compose `postgres` service can see the restored legacy database.
- `LEGACY_DATABASE_NAME` or `LEGACY_DATABASE_URL` identifies the legacy source.

## Example Variables

```bash
export BACKEND_REPO=../backend
export DOCKER_BIN=/Applications/Docker.app/Contents/Resources/bin/docker
export LEGACY_DATABASE_NAME=<legacy_source_database>
export SMOKE_DB=legacy_import_toolkit_smoke_$(date +%Y%m%d_%H%M)
```

If you prefer explicit URLs, set `LEGACY_DATABASE_URL` and `TARGET_DATABASE_URL`
instead of deriving by database name.

## Create A Disposable Target

```bash
./scripts/create-target-smoke-db.sh "$SMOKE_DB"
```

Build a target URL using the same Postgres credentials as the backend Compose
stack, then run the current backend migrations into the disposable database:

```bash
export POSTGRES_PASSWORD="$(awk -F= '/POSTGRES_PASSWORD=/{print $2; exit}' "$BACKEND_REPO/compose.yaml)"
export TARGET_DATABASE_URL="postgresql://postgres:${POSTGRES_PASSWORD}@postgres:5432/${SMOKE_DB}"

"$DOCKER_BIN" compose \
  --project-directory "$BACKEND_REPO" \
  -f "$BACKEND_REPO/compose.yaml" \
  run --rm \
  -e DATABASE_URL="$TARGET_DATABASE_URL" \
  api python manage.py migrate --noinput
```

Create a fallback publication author in the disposable target:

```bash
"$DOCKER_BIN" compose \
  --project-directory "$BACKEND_REPO" \
  -f "$BACKEND_REPO/compose.yaml" \
  run --rm \
  -e DATABASE_URL="$TARGET_DATABASE_URL" \
  api python manage.py shell -c "from django.contrib.auth import get_user_model; User = get_user_model(); User.objects.get_or_create(username='legacy-import-author', defaults={'email': 'legacy-import-author@example.invalid', 'is_staff': True})"
```

## Dry Run

```bash
TARGET_DATABASE_URL="$TARGET_DATABASE_URL" \
LEGACY_DATABASE_NAME="$LEGACY_DATABASE_NAME" \
DOCKER_BIN="$DOCKER_BIN" \
./scripts/backend-compose-run.sh python -m commands.migrate_legacy_data \
  --manifest reports/local-smoke-dry-run.json
```

Expected result: status `warn`, not `fail`. The warning should come from known
target-only or accepted audit warnings, not from missing tables or failed phases.

## Execute

```bash
TARGET_DATABASE_URL="$TARGET_DATABASE_URL" \
LEGACY_DATABASE_NAME="$LEGACY_DATABASE_NAME" \
DOCKER_BIN="$DOCKER_BIN" \
./scripts/backend-compose-run.sh python -m commands.migrate_legacy_data \
  --execute \
  --publication-author-username legacy-import-author \
  --allow-warnings \
  --manifest reports/local-smoke-import-run.json
```

Expected result:

- `core_vocabularies`: `ok`
- `symbols`: `ok`
- `manuscripts`: `ok`
- `scribes_hands`: `ok`
- `image_text`: `ok`
- `annotations`: `ok`
- `publications`: `ok`
- `target_only`: `warn` by design

## Post-Import Audit

```bash
TARGET_DATABASE_URL="$TARGET_DATABASE_URL" \
LEGACY_DATABASE_NAME="$LEGACY_DATABASE_NAME" \
DOCKER_BIN="$DOCKER_BIN" \
./scripts/backend-compose-run.sh python -m commands.audit_legacy_migration \
  --format json \
  --output reports/local-smoke-post-audit.json
```

Check the final status:

```bash
jq -r '.status' reports/local-smoke-post-audit.json
```

Expected result: `warn`, not `fail`, until all accepted migration warnings have
been resolved or explicitly signed off.
