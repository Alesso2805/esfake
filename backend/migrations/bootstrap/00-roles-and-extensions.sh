#!/usr/bin/env bash
# Runs once, as the Postgres superuser, when the data directory is first initialised: the
# official image executes it from /docker-entrypoint-initdb.d (Docker Compose, testcontainers
# and the production VM all mount this directory there). It creates what a migration run by
# esfake_owner cannot: the two roles and the pgvector extension (ADR-0002 §6).
#
# The entrypoint may source this file instead of executing it, so it avoids `set -u` and `exit`.

: "${ESFAKE_OWNER_PASSWORD:?ESFAKE_OWNER_PASSWORD must be set}"
: "${ESFAKE_APP_PASSWORD:?ESFAKE_APP_PASSWORD must be set}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v owner_password="$ESFAKE_OWNER_PASSWORD" \
    -v app_password="$ESFAKE_APP_PASSWORD" <<'SQL'
-- Owns the database and therefore the public schema; runs every migration.
CREATE ROLE esfake_owner LOGIN PASSWORD :'owner_password';
-- Runtime role: data access only, granted through default privileges in the first migration.
CREATE ROLE esfake_app LOGIN PASSWORD :'app_password';

ALTER DATABASE :"DBNAME" OWNER TO esfake_owner;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- pgvector is not a trusted extension, so only a superuser can create it.
CREATE EXTENSION IF NOT EXISTS vector;
SQL
