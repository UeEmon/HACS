#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
docker compose up --build -d
printf '%s\n' 'HACS: http://localhost:8787'
printf '%s\n' 'HACS receiver simulator: http://localhost:8788'
