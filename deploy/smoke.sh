#!/bin/sh
# Smoke checks on a running Compose stack (ADR-0007): in CI after `docker compose up --wait`,
# and on the VM after every deploy. They run from the host, so they also prove that the internal
# listener is not published (CLAUDE.md rule 9).
set -eu

# Host ports as docker-compose.yml publishes them: from the environment, else from .env.
env_value() {
    if [ -f .env ]; then
        sed -n "s/^$1=//p" .env | tail -n 1
    fi
}
api_port="${ESFAKE_API_PORT:-$(env_value ESFAKE_API_PORT)}"
web_port="${ESFAKE_WEB_PORT:-$(env_value ESFAKE_WEB_PORT)}"
api="${ESFAKE_SMOKE_API:-http://127.0.0.1:${api_port:-8000}}"
web="${ESFAKE_SMOKE_WEB:-http://127.0.0.1:${web_port:-3000}}"
internal="${ESFAKE_SMOKE_INTERNAL:-http://127.0.0.1:8001}"

check() {
    if curl --fail --silent --show-error --max-time 10 --output /dev/null "$2"; then
        echo "ok: $1"
    else
        echo "FAILED: $1 ($2)" >&2
        exit 1
    fi
}

check "API liveness" "$api/healthz"
check "API readiness, embedding model loaded" "$api/readyz"
check "web" "$web/"

# Any HTTP answer, even an error status, means the port is published; a refused connection passes.
if curl --silent --max-time 3 --output /dev/null "$internal/"; then
    echo "FAILED: the internal listener answers on $internal" >&2
    exit 1
fi
echo "ok: internal listener not published"

# The runtime services must not hold the owner role (ADR-0002 §6). Only checked where the stack
# runs under Compose from this directory (CI and the VM), not when pointed at a remote URL.
if command -v docker >/dev/null 2>&1 && [ -n "$(docker compose ps --quiet api 2>/dev/null)" ]; then
    for service in api worker-channels worker-maintenance; do
        if docker compose exec -T "$service" printenv MIGRATIONS_DATABASE_URL >/dev/null 2>&1; then
            echo "FAILED: $service holds the owner database URL" >&2
            exit 1
        fi
    done
    echo "ok: runtime services hold no owner credentials"
fi
