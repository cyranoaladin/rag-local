#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ $# -lt 2 ]; then
  echo "Usage: $0 <archive.tgz> <volume_name>" >&2
  exit 1
fi

archive_path=$1
volume_name=$2

if [ ! -f "$archive_path" ]; then
  echo "Archive $archive_path not found" >&2
  exit 1
fi

# Restore by extracting into the named volume.
docker run --rm \
  -v "${volume_name}:/data" \
  -v "$(dirname "$archive_path"):/backup:ro" \
  busybox \
  sh -c "cd /data && rm -rf ./* && tar xzf \"/backup/$(basename "$archive_path")\""

echo "Volume ${volume_name} restored from ${archive_path}"
