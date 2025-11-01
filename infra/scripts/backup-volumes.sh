#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

backup_root=${BACKUP_DIR:-./backups}
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$backup_root"

volumes=(rag_chroma_data rag_ollama_data rag_n8n_data)
for vol in "${volumes[@]}"; do
  archive="${backup_root}/${vol}-${timestamp}.tgz"
  echo "Creating archive ${archive}"
  docker run --rm \
    -v "${vol}:/data:ro" \
    -v "${backup_root}:/backup" \
    busybox \
    sh -c "cd /data && tar czf \"/backup/$(basename "$archive")\" ."
  echo "Archive ready: ${archive}"
done

echo "Backup completed in ${backup_root}"
