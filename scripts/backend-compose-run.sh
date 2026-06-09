#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
migration_repo="$(cd "$script_dir/.." && pwd)"
backend_repo="${BACKEND_REPO:-../archetype-clean/backend}"
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
