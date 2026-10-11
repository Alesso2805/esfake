#!/bin/sh
# Production deploy, run on the VM as the forced command of the CD key (ADR-0007).
#
# The CD job connects with `ssh <user>@<vm> deploy <commit sha>`. In ~/.ssh/authorized_keys the
# key may run nothing but this script:
#   command="/opt/esfake/app/deploy/deploy.sh",restrict ssh-ed25519 AAAA... esfake-cd
# By hand on the VM: deploy/deploy.sh <commit sha>.
#
# It builds the images on the VM (native arm64, no registry), starts them, runs the smoke checks
# and, when anything fails, returns to the commit that was running. Production secrets live only
# in the .env next to docker-compose.yml, never in GitHub. Migrations run in the `migrate` service
# and are not reverted on rollback, so they must stay compatible with the previous code.
#
# Everything happens inside main(), called on the script's last line: `git checkout` rewrites
# this file while it runs, and sh reads a whole line, and a whole function, before running it.
set -eu

log() {
    printf '%s deploy: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2
}

fail() {
    log "ERROR: $*"
    exit 1
}

main() {
    request="${SSH_ORIGINAL_COMMAND:-deploy ${1:-}}"
    sha="${request#deploy }"
    case "$sha" in
        "" | *[!0-9a-f]*) fail "expected 'deploy <40-character commit sha>'" ;;
    esac
    [ "${#sha}" -eq 40 ] || fail "expected 'deploy <40-character commit sha>'"

    cd "${ESFAKE_APP_DIR:-/opt/esfake/app}"
    previous="$(git rev-parse HEAD)"
    git fetch --quiet origin main
    git merge-base --is-ancestor "$sha" origin/main || fail "$sha is not on main"

    log "building $sha; production runs $previous"
    git checkout --quiet --detach "$sha"
    if ! docker compose build; then
        git checkout --quiet --detach "$previous"
        fail "build failed; production still runs $previous"
    fi
    if docker compose up --detach --wait --wait-timeout 900 && sh deploy/smoke.sh; then
        docker image prune --force >/dev/null
        log "deployed $sha"
        return 0
    fi

    log "deploy of $sha failed; rolling back to $previous"
    git checkout --quiet --detach "$previous"
    docker compose up --detach --build --wait --wait-timeout 900
    sh deploy/smoke.sh
    fail "rolled back to $previous"
}

main "$@"; exit $?
