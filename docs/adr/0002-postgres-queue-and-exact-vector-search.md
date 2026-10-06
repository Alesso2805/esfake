# ADR-0002: PostgreSQL as job queue and exact vector store

- Status: Proposed
- Date: 2026-10-06
- Deciders: Alessandro David
- Related: `docs/SPEC.md` (Arquitectura, Esquema), `CLAUDE.md` rules 7 and 9, EF-03, EF-04, EF-13, EF-18, EF-23

## Context

The system needs:

- Synchronous verification on the web.
- Asynchronous processing for channel webhooks, which must answer 200 at once and reply later.
- Periodic maintenance jobs.
- Nearest-neighbour search over a labelled corpus of 384-dimensional embeddings. The corpus starts at about 600 messages and should stay in the low thousands during the MVP.

Production runs for free on one always-on VM, with Postgres in a container on that VM (ADR-0003). The pilot has about 20 people and a few hundred messages. `CLAUDE.md` rules out Redis and message brokers.

## Decision

### 1. One stateful service

PostgreSQL 16 with pgvector holds everything: domain data, corpus, queue, rate-limit windows and spend ledger. There is no Redis, broker or separate vector database.

### 2. The queue is the `verification_queue` table

- **Enqueue.** Insert the queue row in the same transaction that creates the verification. Notify listeners with `NOTIFY` in that transaction. `NOTIFY` is delivered only on commit.
- **Claim.** A short, committed transaction does the following:
  1. `SELECT … WHERE available_at <= :now AND sent_at IS NULL AND failed_at IS NULL ORDER BY available_at LIMIT :n FOR UPDATE SKIP LOCKED`.
  2. Set `attempts = attempts + 1` and `available_at = :now + 60 s`.
  3. Commit.

  The 60-second move works as a lease. If a worker dies, its row becomes visible again after 60 s with no heartbeat.
- **Process.** In a separate transaction, call `/internal/verify`, send the reply through the channel API, then set `sent_at`.
- **Fail.** At 5 attempts, set `failed_at` and send the fallback message ("no pudimos verificar este mensaje; no envíes dinero hasta confirmarlo por otro medio").
- **Wake-up.** Workers `LISTEN` and also poll every 5 s. Postgres does not store notifications: they are lost if the listening connection is down, and polling covers that gap.
- **Cleanup.** The maintenance worker deletes sent or failed rows, and their encrypted reply addresses, after 24 h.
- **Delivery guarantee.** At least once. A crash between sending and setting `sent_at` can duplicate a reply; a crash before sending delays it by up to 60 s. Both are documented and accepted.
- **Index.** A partial index on `available_at` where `sent_at IS NULL AND failed_at IS NULL`.
- **Time source.** `:now` comes from the injected `Clock` and is passed as a parameter, not taken from SQL `now()`. Tests can then move time with a fake clock (rule 13). The only role of the database is to serialise claims.

### 3. Two connection strings

- `DATABASE_URL` serves normal work and may point to a pooler.
- `DATABASE_DIRECT_URL` must reach Postgres directly and is the only one used for `LISTEN`.

A transaction-mode pooler does not keep a session, so `LISTEN` behind it silently stops receiving. Locally, both strings point to the same server.

### 4. Postgres must never auto-suspend

Scale-to-zero drops the `LISTEN` connection, and a cold start eats into the 4 s p95 budget of the web. Production runs Postgres in a container on an always-on VM (ADR-0003), so nothing suspends it. A move to a managed provider (plan B in ADR-0003) must let us disable suspension. EF-18 runs a `LISTEN` test over the direct connection in production.

### 5. Exact similarity search

The query is `ORDER BY embedding <=> :q LIMIT :k`, over rows with `split = 'index'` and no ANN index. At this corpus size a sequential scan fits the 200 ms stage budget and returns the true neighbours. Evaluation then never depends on the recall or tuning of an approximate index.

Access goes through a `SimilarityIndex` interface. HNSW can be added when measurements justify it. That change alters the manifest and needs its own ADR.

### 6. Roles and extension bootstrap

Two roles:

- `esfake_owner` owns the schema and runs the migrations.
- `esfake_app` is the runtime role. It gets DML rights through `ALTER DEFAULT PRIVILEGES`, and `audit_log` grants it `INSERT` and `SELECT` only.

Two operations need more than `esfake_owner` has:

- `CREATE EXTENSION vector` needs a superuser or the provider's admin role. pgvector 0.8.7's `vector.control` does not declare `trusted = true`.
- Creating roles needs `CREATEROLE`.

A migration run by `esfake_owner` can do neither. So a bootstrap SQL script, run once as superuser, creates both roles and the extension:

- In Docker Compose, through the Postgres image's init directory.
- In integration tests (testcontainers), with the same script.
- In production, through the same init directory of the Postgres container on the VM. On a managed provider (plan B), it becomes a documented one-time step.

The first Alembic migration keeps `CREATE EXTENSION IF NOT EXISTS vector`. It does nothing where the bootstrap already ran, and it still works on providers that allow the database owner to create the extension.

## Alternatives considered

- **Redis with RQ or Celery, or a cloud queue (SQS, Pub/Sub).** Another service to run, pay for and back up, with a second failure mode. Our throughput is far below what one Postgres handles, and a separate service loses the transactional enqueue.
- **A dedicated vector database (Qdrant, Pinecone, …).** Another service, plus a copy of the data that must stay in sync with splits, retention and deletion by donation code. With a small corpus it adds nothing.
- **An ANN index (HNSW or IVFFlat) from the start.** It adds an approximation variable to every evaluation and is unnecessary at this scale. Deferred behind `SimilarityIndex`.
- **Polling only.** Simpler, but we would trade latency (up to the poll interval) against load. `LISTEN` plus a 5 s poll fallback gives low latency and survives lost notifications.

## Consequences

- There is one system to back up and restore, and a verification is created and enqueued atomically.
- Similarity results are exact and reproducible from the index snapshot in the manifest.
- Postgres bounds queue throughput. This is fine for the pilot; usage reports (EF-27) will show if that changes.
- At-least-once delivery means a user can, rarely, get a duplicate reply.
- The hosting choice is constrained. It needs pgvector, direct connections and no auto-suspension.
- Self-hosting Postgres makes upgrades, monitoring and backups our job (ADR-0003). On a managed provider, one manual bootstrap step would sit outside Alembic.

## Verification

Integration tests use real Postgres (testcontainers):

- Two concurrent workers never claim the same row.
- An expired lease is claimed again after 60 s of fake time.
- A row with 5 attempts gets `failed_at`.
- `NOTIFY` wakes a worker well before the 5 s poll, and polling alone still delivers when no notification arrives.
- `esfake_app` cannot create, alter or drop objects.
- `audit_log` rejects `UPDATE`, `DELETE` and `TRUNCATE`.

EF-18 checks that `LISTEN` works over the direct production connection.
