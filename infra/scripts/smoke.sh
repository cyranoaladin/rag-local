#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

# Activate the core services when profiles are not already provided (fits CI defaults).
profiles_csv="${COMPOSE_PROFILES:-db,llm,api}"
export COMPOSE_PROFILES="${profiles_csv}"

# Normalise profiles into an array so we can forward them explicitly to the CLI.
IFS=',' read -ra profile_tokens <<< "${profiles_csv}"
compose_profiles=()
for token in "${profile_tokens[@]}"; do
  stripped=${token//[[:space:]]/}
  if [ -n "${stripped}" ]; then
    compose_profiles+=("${stripped}")
  fi
done
unset IFS

# Ensure baseline env files exist for both local and CI usage.
if [ ! -f infra/.env ]; then
  if [ -f infra/.env.ci ]; then
    cp infra/.env.ci infra/.env
  else
    touch infra/.env
  fi
fi

# Select compose overrides depending on environment so we match the stack that is already up in CI.
compose_files=(infra/docker-compose.yml)
if [ "${CI:-}" = "true" ] && [ -f infra/docker-compose.smoke.override.yml ]; then
  compose_files+=(infra/docker-compose.smoke.override.yml)
else
  compose_files+=(infra/docker-compose.dev.yml)
fi

env_file="infra/.env"
if [ "${CI:-}" = "true" ] && [ -f infra/.env.ci ]; then
  env_file="infra/.env.ci"
fi

[ -f "${env_file}" ] || touch "${env_file}"

# Compose helper (order-sensitive flags), reused throughout the script.
# Compose CLI already reads COMPOSE_PROFILES from env; keeping flags minimal avoids "no service selected" edge cases in CI.
compose_cmd=(docker compose)
for file in "${compose_files[@]}"; do
  compose_cmd+=(-f "${file}")
done
compose_cmd+=(--env-file "${env_file}")
for profile in "${compose_profiles[@]}"; do
  compose_cmd+=(--profile "${profile}")
done

# Restrict compose actions to the services we actually need for the smoke.
target_services=(chroma ollama ingestor)

# Validate that the requested services are available after profile filtering to avoid
# cryptic "no service selected" errors on CI runners.
mapfile -t compose_services < <("${compose_cmd[@]}" config --services)
if [ "${#compose_services[@]}" -eq 0 ]; then
  echo "docker compose config --services returned no services (profiles: ${profiles_csv})" >&2
  exit 1
fi

smoke_services=()
missing_services=()
for svc in "${target_services[@]}"; do
  if printf '%s\n' "${compose_services[@]}" | grep -qx "${svc}"; then
    smoke_services+=("${svc}")
  else
    missing_services+=("${svc}")
  fi
done

if [ "${#missing_services[@]}" -ne 0 ]; then
  echo "Expected smoke services absent with profiles ${profiles_csv}: ${missing_services[*]}" >&2
  echo "Available services: ${compose_services[*]}" >&2
  exit 1
fi

echo "== stack up command: ${compose_cmd[*]} up -d --remove-orphans (profiles: ${profiles_csv}) =="

# ENV minimaux (ensure target env file has the essentials)
grep -q '^INGESTOR_API_TOKEN=' "${env_file}" || printf '\nINGESTOR_API_TOKEN=devtoken\n' >> "${env_file}"
grep -q '^INGESTOR_IP_ALLOWLIST=' "${env_file}" || printf '\nINGESTOR_IP_ALLOWLIST=\n' >> "${env_file}"

# Démarrage stack (base + dev)
# Avoid passing explicit service names; Compose will honour the active profiles and
# this sidesteps flaky "no service selected" parsing on some runner builds.
"${compose_cmd[@]}" up -d --remove-orphans

# Attente santé (simple boucle)
echo "== wait: health =="
for attempt in $(seq 1 30); do
  ok=1
  ps_output=$("${compose_cmd[@]}" ps "${smoke_services[@]}") || ps_output=""
  printf '%s' "${ps_output}" | grep -q "chroma.*(healthy)"   || ok=0
  printf '%s' "${ps_output}" | grep -q "ollama.*(healthy)"   || ok=0
  printf '%s' "${ps_output}" | grep -q "ingestor.*(healthy)" || ok=0 || true
  "${compose_cmd[@]}" ps | grep -q "ui.*(healthy)"            || ok=0 || true
  if [ "$ok" = "1" ]; then
    break
  fi
  echo "waiting for healthy services (attempt ${attempt}/30)..."
  sleep 2
done

if [ "$ok" != "1" ]; then
  echo "Services failed to reach healthy state" >&2
  exit 1
fi

# Checks côté hôte
curl -fsS http://127.0.0.1:18001/health -H "X-API-Token: ${INGESTOR_API_TOKEN:-devtoken}" -o /dev/null && echo "ingestor: OK"

# Ingestion smoke
curl -fsS -X POST "http://127.0.0.1:18001/ingest" \
  -H "X-API-Token: ${INGESTOR_API_TOKEN:-devtoken}" \
  -H "Content-Type: application/json" \
  -d '{"source_type":"url","source":"https://example.com","hints":{"env":"smoke"}}' \
  | jq -c .

echo "== done =="
