# ADR-0008: Litestar 2.x instead of FastAPI for the API layer

- Status: Accepted (2026-10-13)
- Date: 2026-10-13
- Deciders: Alessandro David
- Related: `CLAUDE.md` (Stack obligatorio; rules 4 and 9), `docs/SPEC.md` (Arquitectura), ADR-0002, ADR-0004 §1, EF-04, EF-20

## Context

`CLAUDE.md` fixed FastAPI as the framework of `esfake.api`. The owner now wants to use Litestar in a real project and contribute upstream what turns up along the way. This ADR records the owner's explicit authorisation to depart from the mandated stack.

The change is cheap now and will not stay cheap:

- `esfake.api` holds two small ASGI apps with four routes.
  - The public app serves `/healthz` and `/readyz`.
  - The internal app serves `/internal/embed` and `/internal/verify`.
- Each app runs on its own `uvicorn.Server`, both on one event loop, and they share the loaded model (`CLAUDE.md` rule 9).
- EF-20 will add the public verification endpoint and its rate limits. Switching after that means rewriting much more.

Versions were checked on PyPI and in the official documentation on 2026-10-13:

| Package | Version and date | What matters here |
| --- | --- | --- |
| Litestar | 2.24.0, 2026-06-11 | Latest stable 2.x. No 3.x has been released. Python 3.14 is supported since 2.19.0, and the wheel is pure Python. |
| msgspec | 0.22.0 | CPython 3.14 wheels for Linux x86_64 and aarch64 and for Windows. |
| multidict | 7.1.0 | Same CPython 3.14 wheels. |

Nothing blocks Python 3.14 or the arm64 production VM (ADR-0003 §5).

## Decision

**Scope.** `esfake.api` moves to Litestar `>=2.24,<3`; uvicorn stays. Only `esfake.api`, its tests and the dependency files change: pipeline, corpus, evaluation, shared, workers and cli do not. `serve.py` and `state.py` keep running two `uvicorn.Server` on one loop over the same `ModelState`.

**Contracts are kept:**

- **Validation errors never echo the request** (`CLAUDE.md` rule 4; ADR-0004 §1).
  - Litestar answers a `ValidationException` with 400 and a JSON body that can describe the input. A handler turns it into 422 with an empty body.
  - The handler returns `content=b""`, because `content=None` serialises to `null`.
  - A request body that is not valid JSON also answers 422 with an empty body, as it did under FastAPI.
- **The shared secret.** The internal app's shared secret is checked by a guard with `hmac.compare_digest`, which raises `NotAuthorizedException` (401).
- **Status codes of the internal POST routes.**
  - Both declare `status_code=200`, because Litestar defaults POST to 201 and the CLI and the channel worker expect 200.
  - `/internal/verify` keeps answering 501 until the pipeline is wired in (EF-20).
- **Pydantic stays.** Request and response models stay Pydantic v2 (`shared/internal_contract.py`), served through Litestar's Pydantic plugin.
- **OpenAPI.** It stays enabled on the public app, at Litestar's default path. The internal app has `openapi_config=None`.

**Rate limiting does not use Litestar's `RateLimitMiddleware`.** It keeps its state in the memory of each process and supports a single window. The limits of EF-20 live in the `rate_limit_windows` table in Postgres, with per-minute and per-day windows, as `docs/SPEC.md` specifies.

## Consequences

- **Contract differences that remain.** Status codes do not change; two other things do:
  - Error bodies change shape, from FastAPI's `{"detail": ...}` to Litestar's `{"status_code": ..., "detail": ...}`. The CLI and the worker read only the status code.
  - The public OpenAPI document moves from `/docs` and `/openapi.json` to `/schema` and `/schema/openapi.json`.
- **New runtime dependencies come with Litestar:** msgspec, multidict, polyfactory, rich, rich-click, click, multipart and litestar-htmx. httpx, until now a development dependency of the tests, is now a runtime dependency. The image grows a little.
- **One more thing to learn.** Guards, plugins and Litestar's exception model replace FastAPI's dependencies and exception handlers.
- **Upstream material.** Surprising behaviour or unclear documentation found during the migration is noted for upstream issues, outside this repository.

## Alternatives considered

- **Keep FastAPI.** It is mature, it already works here, and staying costs nothing. Rejected because the owner's goal is hands-on Litestar experience and upstream contributions. With a two-app, four-route API layer and EF-20 not yet started, this is the cheapest moment to switch.
