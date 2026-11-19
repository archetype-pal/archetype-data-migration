#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
migration_repo="$(cd "$script_dir/.." && pwd)"
backend_repo="${BACKEND_REPO:-../backend}"
backend_repo="$(cd "$backend_repo" && pwd)"
docker_bin="${DOCKER_BIN:-docker}"

if [[ ! -f "$backend_repo/compose.yaml" ]]; then
  echo "Backend compose file not found at $backend_repo/compose.yaml" >&2
  exit 2
fi

env_args=()
for name in \
  LEGACY_DATABASE_URL \
  TARGET_DATABASE_URL \
  LEGACY_DATABASE_NAME \
  TARGET_DATABASE_NAME \
  DATABASE_URL \
  POSTGRES_USER \
  POSTGRES_PASSWORD \
  POSTGRES_HOST \
  POSTGRES_PORT \
  POSTGRES_DB; do
  if [[ -n "${!name+x}" ]]; then
    env_args+=("-e" "$name=${!name}")
  fi
done

compose_cmd=(
  "$docker_bin"
  compose
  --project-directory "$backend_repo"
  -f "$backend_repo/compose.yaml"
  run
  --rm
)
# A source mapping file outside this repo is mounted read-only; inside the repo it is
# already visible under /migration.
if [[ -n "${SOURCE_MAPPING_PATH:-}" ]]; then
  mapping_abs="$(cd "$(dirname "$SOURCE_MAPPING_PATH")" && pwd)/$(basename "$SOURCE_MAPPING_PATH")"
  if [[ ! -f "$mapping_abs" ]]; then
    echo "SOURCE_MAPPING_PATH not found: $SOURCE_MAPPING_PATH" >&2
    exit 2
  fi
  if [[ "$mapping_abs" == "$migration_repo"/* ]]; then
    env_args+=("-e" "SOURCE_MAPPING_PATH=/migration/${mapping_abs#"$migration_repo"/}")
  else
    compose_cmd+=(-v "$mapping_abs:/source-mapping.json:ro")
    env_args+=("-e" "SOURCE_MAPPING_PATH=/source-mapping.json")
  fi
fi
if (( ${#env_args[@]} > 0 )); then
  compose_cmd+=("${env_args[@]}")
fi
compose_cmd+=(
  -v "$migration_repo:/migration"
  -w /migration
  api
  "$@"
)

exec "${compose_cmd[@]}"
