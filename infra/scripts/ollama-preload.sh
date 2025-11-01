#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

profiles=${COMPOSE_PROFILES:-db,llm,api}
models=${OLLAMA_PRELOAD_MODELS:-"nomic-embed-text llama3.2:latest"}
compose_files=(docker-compose.yml)
if [ -f docker-compose.dev.yml ] && [ "${USE_DEV_OVERRIDE:-0}" = "1" ]; then
  compose_files+=(docker-compose.dev.yml)
fi

compose_cmd=(docker compose)
for file in "${compose_files[@]}"; do
  compose_cmd+=(-f "$file")
done
compose_cmd+=(--env-file .env)
IFS=',' read -ra profile_list <<< "${profiles}"
for profile in "${profile_list[@]}"; do
  trimmed=${profile//[[:space:]]/}
  [ -n "$trimmed" ] && compose_cmd+=(--profile "$trimmed")
done

if [ ! -f .env ]; then
  echo "infra/.env is required (copy infra/.env.example and adjust)." >&2
  exit 1
fi

# Ensure the Ollama container is up before pulling models.
"${compose_cmd[@]}" up -d ollama

for model in ${models}; do
  echo "Preloading Ollama model: ${model}"
  if ! "${compose_cmd[@]}" exec -T ollama ollama pull "${model}"; then
    echo "Failed to pull model ${model}" >&2
    exit 1
  fi
done

echo "All requested models pulled successfully."
