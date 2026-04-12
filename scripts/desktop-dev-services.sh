#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIDS=()

cleanup() {
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
    fi
  done
}

trap cleanup EXIT INT TERM

if lsof -ti tcp:8420 >/dev/null 2>&1; then
  echo "Backend already listening on 8420; reusing it."
else
  echo "Starting backend on 8420..."
  (
    cd "$ROOT/backend"
    python3 -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8420
  ) &
  PIDS+=("$!")
fi

echo "Starting desktop frontend on 1420..."
(
  cd "$ROOT/frontend"
  VITE_PORT=1420 npm run dev
) &
PIDS+=("$!")

wait
