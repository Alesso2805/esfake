#!/bin/sh
# Smoke checks on a running Compose stack (ADR-0007): in CI after `docker compose up --wait`,
# and on the VM after every deploy. They run from the host, so they also prove that the internal
# listener is not published (CLAUDE.md rule 9).
set -eu

api="${ESFAKE_SMOKE_API:-http://127.0.0.1:8000}"
web="${ESFAKE_SMOKE_WEB:-http://127.0.0.1:3000}"
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
