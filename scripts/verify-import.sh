#!/usr/bin/env bash
set -euo pipefail

# Read-only verification wrapper. Review warnings in the migration manifest
# before treating the target as ready.
./scripts/backend-compose-run.sh python -m commands.audit_legacy_migration \
  --format markdown \
  --output reports/legacy-migration-post-import-audit.md
