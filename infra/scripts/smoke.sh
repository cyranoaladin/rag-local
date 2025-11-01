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
mandatory_services=(chroma ollama ingestor)
optional_services=(ui)

# Validate that the requested services are available after profile filtering to avoid
# cryptic "no service selected" errors on CI runners.
mapfile -t compose_services < <("${compose_cmd[@]}" config --services)
if [ "${#compose_services[@]}" -eq 0 ]; then
  echo "docker compose config --services returned no services (profiles: ${profiles_csv})" >&2
  exit 1
fi

missing_services=()
for svc in "${mandatory_services[@]}"; do
  if printf '%s\n' "${compose_services[@]}" | grep -qx "${svc}"; then
    :
  else
    missing_services+=("${svc}")
  fi
done

if [ "${#missing_services[@]}" -ne 0 ]; then
  echo "Expected smoke services absent with profiles ${profiles_csv}: ${missing_services[*]}" >&2
  echo "Available services: ${compose_services[*]}" >&2
  exit 1
fi

present_optional_services=()
for svc in "${optional_services[@]}"; do
  if printf '%s\n' "${compose_services[@]}" | grep -qx "${svc}"; then
    present_optional_services+=("${svc}")
  fi
done

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
  ps_json=$("${compose_cmd[@]}" ps --format json 2>/dev/null || true)
  status_snapshot=""
  if [ -n "${ps_json}" ]; then
    declare -A service_health=()
    status_lines=$(printf '%s\n' "${ps_json}" | jq -r '.[] | select(.Service != null) | "\(.Service)=\(.Health // .State // \"\")"')
    while IFS='=' read -r svc status; do
      [ -z "${svc}" ] && continue
      service_health["${svc}"]="${status}"
    done <<< "${status_lines}"
    for svc in "${mandatory_services[@]}"; do
      health="${service_health[$svc]:-}"
      [ "${health}" = "healthy" ] || ok=0
    done
    for svc in "${present_optional_services[@]}"; do
      health="${service_health[$svc]:-}"
      [ "${health}" = "healthy" ] || ok=0
    done
    status_snapshot=$(printf '%s\n' "${ps_json}" | jq -r '.[] | select(.Service != null) | "\(.Service)\t\(.Health // .State // \"\")"')
  else
    ps_output=$("${compose_cmd[@]}" ps) || ps_output=""
    for svc in "${mandatory_services[@]}"; do
      printf '%s' "${ps_output}" | grep -q "${svc}.*(healthy)" || ok=0
    done
    for svc in "${present_optional_services[@]}"; do
      printf '%s' "${ps_output}" | grep -q "${svc}.*(healthy)" || ok=0
    done
    status_snapshot="${ps_output}"
  fi
  if [ "$ok" = "1" ]; then
    break
  fi
  printf 'compose services snapshot (attempt %s):\n%s\n' "${attempt}" "${status_snapshot}"
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
