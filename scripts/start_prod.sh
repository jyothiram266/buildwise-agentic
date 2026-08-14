#!/usr/bin/env bash
# Entry point for a single-container hosted deployment (Render, Railway, Fly, a VM).
#
# Four things a hosted platform needs that docker-compose does not:
#
#   1. Bind $PORT. Platforms assign the port and health-check it. A hardcoded 8000
#      fails the health check and the deploy is marked unhealthy with no useful error.
#   2. No cross-service URL to get wrong. The mock systems of record run on loopback
#      inside this container, so MOCK_CONNECTOR_URL is a constant instead of something
#      assembled from platform service discovery (which yields host:port with no
#      scheme and silently produces a malformed URL).
#   3. Bootstrap without a shell. Free instance types have no shell access, so the
#      database has to populate itself on first boot. Bootstrap is idempotent and
#      skipped entirely once the corpus is indexed.
#   4. Fail loudly. If the database is unreachable the container should exit, not
#      serve an app that 500s on every request.
#
# The loopback hop keeps the architectural boundary real — the connectors still speak
# HTTP and still exercise timeouts, retries and serialisation. The trade-off is that
# API and connectors now scale together; for a demo that is the right call, and
# docker-compose still runs them as separate services for development.
set -euo pipefail

PORT="${PORT:-8000}"
MOCK_PORT="${MOCK_PORT:-8100}"
export MOCK_CONNECTOR_URL="http://127.0.0.1:${MOCK_PORT}"

echo "→ BuildWise starting (api port ${PORT}, connectors on loopback ${MOCK_PORT})"

# --- 1. the mock systems of record, on loopback only -------------------------
uvicorn connectors.mock_server.main:app \
    --host 127.0.0.1 --port "${MOCK_PORT}" --log-level warning &
MOCK_PID=$!

cleanup() {
    kill "${MOCK_PID}" 2>/dev/null || true
}
trap cleanup EXIT

printf "→ waiting for connectors"
for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:${MOCK_PORT}/health" >/dev/null 2>&1; then
        echo " ok"
        break
    fi
    if ! kill -0 "${MOCK_PID}" 2>/dev/null; then
        echo " FAILED — the connector service exited during startup"
        exit 1
    fi
    printf "."
    sleep 2
done

# --- 2. populate the database on first boot ----------------------------------
# `--if-empty` makes this a no-op on every restart after the first, so a redeploy
# costs a single query rather than a full re-ingest.
echo "→ bootstrap (skipped if already populated)"
python scripts/bootstrap.py --if-empty

# --- 3. the API, in the foreground so the platform supervises it -------------
echo "→ serving"
exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT}" --proxy-headers --forwarded-allow-ips '*'
