#!/usr/bin/env bash
# Build plan P0-T4 asks for this script. It brings the stack up, waits for health
# properly rather than sleeping, then bootstraps and self-checks — so a fresh clone
# reaches a working demo with one command.
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "→ creating .env from .env.example"
  cp .env.example .env
fi

echo "→ starting containers"
docker compose up -d --build

wait_for() {
  local name=$1 url=$2 tries=${3:-40}
  printf "→ waiting for %s" "$name"
  for _ in $(seq 1 "$tries"); do
    if curl -fsS "$url" >/dev/null 2>&1; then echo " ok"; return 0; fi
    printf "."
    sleep 3
  done
  echo " FAILED"
  echo "   logs: docker compose logs $name"
  return 1
}

# Postgres reports through pg_isready rather than HTTP.
printf "→ waiting for postgres"
for _ in $(seq 1 40); do
  if docker compose exec -T postgres pg_isready -U buildwise -d buildwise >/dev/null 2>&1; then
    echo " ok"; break
  fi
  printf "."; sleep 2
done

wait_for mock-connectors http://localhost:8100/health
wait_for api http://localhost:8000/health

echo "→ bootstrapping data"
docker compose exec -T api python scripts/bootstrap.py

echo "→ selfcheck"
docker compose exec -T api python scripts/selfcheck.py

cat <<'EOF'

Ready.
  console   http://localhost:3000
  api docs  http://localhost:8000/docs
  health    http://localhost:8000/health

Switch identity with the "Acting as" selector — that is the demo.
EOF
