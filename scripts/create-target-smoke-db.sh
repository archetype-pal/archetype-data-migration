#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <new_target_database_name>" >&2
  exit 2
fi

db_name="$1"
if [[ ! "$db_name" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]]; then
  echo "Unsafe database name: $db_name" >&2
  exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
backend_repo="${BACKEND_REPO:-../archetype-clean/backend}"
backend_repo="$(cd "$backend_repo" && pwd)"
docker_bin="${DOCKER_BIN:-docker}"
compose=("$docker_bin" compose --project-directory "$backend_repo" -f "$backend_repo/compose.yaml")

exists="$("${compose[@]}" exec -T postgres psql -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$db_name'")"
if [[ "${exists//[[:space:]]/}" == "1" ]]; then
  echo "Database already exists: $db_name" >&2
  exit 2
fi

"${compose[@]}" exec -T postgres createdb -U postgres "$db_name"
echo "Created target smoke database: $db_name"
echo "Next: set TARGET_DATABASE_URL/DATABASE_URL for $db_name and run backend migrations before importing."
