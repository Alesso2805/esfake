# Auditoría de arquitectura de ¿EsFake?

Fecha: 2026-10-12 · Rama auditada: `feat/EF-11-rules-injection` (incluye EF-11 y `esfake rules check`; PR #14, aún sin fusionar a `main`).

## Alcance y método

- Se compara el repositorio con `docs/SPEC.md`, `docs/BACKLOG.md`, `CLAUDE.md` y `docs/adr/` (ADR-0001 a ADR-0007).
- **`docs/ARCHITECTURE_RULES.md` no existe** en el repositorio ni en el historial reciente, y tampoco hay tests de arquitectura. Las reglas de arquitectura se auditaron contra las 13 reglas no negociables de `CLAUDE.md` y la tabla de requisitos no funcionales de la SPEC. La ausencia del documento se cuenta como hallazgo (§2, fila 14).
- Cuatro auditores trabajaron en paralelo, de solo lectura salvo el clon de la sección 8. Los hallazgos que más pesan se volvieron a comprobar con `grep` antes de incluirlos (marcados con ✔).
- "Pendiente por plan" significa que la historia que lo cubre aún no se ha implementado según `docs/BACKLOG.md`. No se cuenta como incumplimiento.
- Convención de estados: **Cumple**, **Parcial**, **No cumple**, **Pendiente** (por plan), **No verificado**.

### Ejecución real de herramientas (desde `backend/`)

| Comando | Resultado |
| --- | --- |
| `uv run pytest -q` | 430 passed, 0 fallos, 0 omitidos, exit 0 (≈4 min, testcontainers con Docker) |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 116 archivos ya formateados |
| `uv run mypy` | Success: no issues found in 111 source files |
| CI de la rama (GitHub Actions) | Backend, Web y Compose arm64 en verde en la última corrida revisada |
| Clon limpio + `docker compose up --wait` + `deploy/smoke.sh` | Correcto, sin pasos manuales (ver §8) |

Aviso: con el CI actual el gate de `esfake eval` **pasa en vacío**: el corpus no tiene casos `eval` asignados ni existe la versión 0 publicada. Que el CI esté verde no demuestra calidad de detección todavía.

---

## 1. Estructura del repositorio

| Elemento (SPEC) | Estado real | Clasificación |
| --- | --- | --- |
| `backend/src/esfake/{shared,corpus,evaluation,cli,api,workers}` | Existen | Cumple |
| `pipeline/{normalize,redaction,rules,similarity,decision,llm}` | Existen (`similarity` solo con embedder y cliente interno; `llm` solo con `cache.py` y `payload.py`) | Cumple parcialmente: el resto llega con EF-10, 12, 13, 14 |
| `pipeline/urls/`, `pipeline/templates/`, `pipeline/llm/prompts/` | No existen | Pendiente (EF-12, EF-16, EF-14) |
| `channels/` | No existe | Pendiente (EF-20, EF-23) |
| `backend/migrations/` | Existe (`versions/0001..0004` y `bootstrap/`) | Cumple |
| `backend/tests/{unit,integration}` | Existen | Cumple |
| `backend/tests/canaries/` | No existe; los canarios están en `tests/integration/test_canaries.py` | Está en otro lugar (menor) |
| `web/` | Existe; la portada es "En construcción" | Cumple como esqueleto |
| `config/{rules,official_domains,modalities,thresholds}.yaml` | Existen los cuatro | Cumple |
| `evals/datasets/` | Existe (`corpus.jsonl`, 144 filas) | Cumple |
| `evals/llm_cache/` | No existe, aunque `cli/main.py:38` apunta a `../evals/llm_cache` | Falta; hoy no hay ruta de juez que la use (menor) |
| `evals/redteam/{dev,heldout}` | No existen | Pendiente (EF-17) |
| `docs/{SPEC,BACKLOG}.md`, `docs/adr/` | Existen | Cumple |
| `docs/evals/` | No existe; la versión 0 no está publicada | Pendiente por plan, bloqueada por tareas del dueño (importante) |
| `docs/sprints/` | No existe | Falta (menor, sin historia asignada) |
| `docs/ARCHITECTURE_RULES.md` | No existe | Falta (importante, ver §7) |
| `README.md`, `CHANGELOG.md` | No existen | Faltan (menor; la SPEC pide actualizar el README al cierre de cada sprint) |
| `docker-compose.yml`, `Makefile`, `CLAUDE.md` | Existen | Cumple |

**Lo que sobra (existe y la SPEC no lista):** `deploy/{deploy.sh,smoke.sh}`, `config/models.yaml`, `config/subcategories.yaml`, `.github/workflows/{ci,cd}.yml`, `.env.example`, `evals/redaction/` (con un `generate_names.py` mezclado con datos), `backend/tests/{fakes,paths}.py`, `web/AGENTS.md` (artefacto de `create-next-app`) y los módulos `pipeline/{intake,manifest,text,verdict,verifier}.py` y `shared/{brands,ids,hmac_keys,models_config,thresholds}.py`. Todo es coherente con los ADR; el árbol de la SPEC está desactualizado.

**Orden de sprint:** EF-11 se hizo antes que EF-10 por decisión del dueño (EF-10 necesita la cuenta de AWS Bedrock). No hay ADR que lo registre.

---

## 2. Reglas de arquitectura

### 2.1 Reglas no negociables de `CLAUDE.md`

| # | Regla | Estado | Evidencia |
| --- | --- | --- | --- |
| 1 | Entrada no confiable; modelo solo devuelve valores cerrados | Parcial | `Level`, `Route`, `Layer` como `Literal` y `extra="forbid"` en `pipeline/verdict.py:8-10`. `JudgeResponse.output` es `dict[str, Any]` en `pipeline/llm/cache.py`; no existe `LLMJudge` (EF-14). |
| 2 | Texto de plantillas es/en; nunca "es seguro" | Pendiente | `pipeline/templates/` no existe; sin test de frases prohibidas (EF-16). |
| 3 | Pisos de política | Parcial | `pipeline/decision/policy_v0.py:20-24`: señal `injection` o con `weight >= suspicious_at` fija mínimo `suspicious`. Tests: `test_policy_v0.py::test_injection_or_a_strong_signal_keeps_at_least_suspicious`, `test_rules.py::test_an_injection_is_a_suspicious_floor_and_a_signal_in_its_own_layer`. Faltan modo degradado y "similitud nunca decide `no_signals`" (EF-13, EF-15). |
| 4 | Privacidad estructural | Cumple en lo implementado | `RawText` no es `str` (`pipeline/text.py`); `tests/unit/test_text_boundary.py` (AST); `hide_input_in_errors` en `test_api_models.py`; 422 sin cuerpo en `api/errors.py` (`test_api.py::test_validation_errors_never_echo_the_request`); canarios en BD, logs y payload del juez simulado (`tests/integration/test_canaries.py`). Pendiente: canarios sobre logs por capa (EF-19); el payload real del juez (EF-14). |
| 5 | Consentimiento previo | Pendiente | Solo el esquema: `privacy_notice_version` NOT NULL y trigger `esfake_require_privacy_notice`. Sin flujo de aviso (EF-21, EF-23). |
| 6 | Corpus: `case_id`, clústeres, splits | Parcial | Código y tests completos (`test_corpus_assign.py`, `test_corpus_validate.py`, `test_constraints.py`). Datos: las 144 filas de `evals/datasets/corpus.jsonl` tienen `case_id`, `cluster_id` y `split` en `null`; `cluster_threshold_reviewed: false` en `config/thresholds.yaml`. |
| 7 | Cola en Postgres | Parcial | Existe `LISTEN/NOTIFY` por conexión directa con polling cada 5 s (`workers/channels.py`, `test_channel_worker.py`) y el esquema con índice parcial. No hay `SELECT … FOR UPDATE SKIP LOCKED`, `attempts`, `sent_at`/`failed_at` ni borrado a las 24 h (EF-23). |
| 8 | Webhooks | Pendiente | No hay webhook; `KeyRing` y `hmac_keys.py` son la base (EF-23). |
| 9 | Listener interno aparte | Parcial | Dos `uvicorn.Server` en el mismo loop con modelo compartido (`api/serve.py`; `test_serve.py`), secreto con `hmac.compare_digest` (`api/internal.py`), lista explícita de proxies. ✔ `/internal/verify` responde 501 (`api/internal.py:68`) aunque el detector de reglas ya existe. |
| 10 | URLs | Pendiente | `pipeline/urls/` no existe; no hay peticiones de red a URLs de mensajes (EF-12, EF-21). |
| 11 | Evaluación y caché del modelo | Parcial | Clave `sha256(prompt_version \| model@params \| entrada)` en `pipeline/llm/cache.py:30-47`; modos `cached_strict`/`record`/`live`; gate con McNemar exacto (`evaluation/gate.py`, `stats.py`). Sin `docs/evals/` ni `evals/llm_cache/`; no hay modo release (EF-08 v0, EF-30). |
| 12 | Manifiesto | Parcial | `pipeline/manifest.py` (hash SHA-256 del JSON canónico). `llm_model` y `prompt_version` van en `None` hasta EF-14. El hash no incluye `rules.yaml`; solo lo fija `git_sha`. |
| 13 | `Clock` inyectado; sin secretos en el repo | Parcial | `datetime.now` solo en `SystemClock` (`shared/clock.py:13`). `time.perf_counter()` en `evaluation/{harness,redaction,embedding_comparison}.py` (mide duración; no es inyectable). Secretos: no se ejecutó un escáner. |
| 14 | Documento `ARCHITECTURE_RULES.md` y tests de arquitectura | No cumple | El documento no existe. Sin import-linter ni test de capas. Lo único estructural es `test_text_boundary.py` (frontera de texto crudo). |

### 2.2 Requisitos no funcionales de la SPEC

| Categoría | Estado | Evidencia |
| --- | --- | --- |
| Calidad (recall, FP, gate) | Parcial | Métricas con Wilson y gate probados (`test_eval_metrics.py`, `test_eval_gate.py`, `test_eval_stats.py`); no hay medición real ni versión publicada. |
| Comparación con LLM solo | Pendiente | EF-10, EF-22, EF-30. |
| Robustez (redteam) | Pendiente | `esfake redteam` es stub (`test_cli_stubs.py`); hay 6 reglas de inyección con test (EF-17). |
| Salida del modelo | Pendiente | EF-14, EF-16. |
| Modo degradado | Pendiente | EF-15. |
| Latencia p95 | No verificado | Sin API de verificación ni trazas por capa (EF-19, EF-20). |
| Costo (≤ 40 % con modelo) | Pendiente | `ResponseCache` registra `cost_usd`; sin topes (EF-14, EF-20). |
| Privacidad | Parcial | Ver regla 4. Pendiente: AES-GCM de la dirección de respuesta, vaciado a 30 días, borrado a 24 h (el `MaintenanceWorker` corre con `jobs=()`). |
| Consentimiento y borrado | Pendiente | EF-21, 23, 24. |
| Marco legal | Parcial | ADR-0004 documenta Ley 29733; falta la lista de EF-25. |
| Abuso (topes, IP, firma) | Parcial | Listener interno y proxies listos; topes y firma pendientes (EF-20, EF-23). |
| Seguridad web | Pendiente | EF-12, EF-21. |
| Reproducibilidad | Parcial | Manifiesto y `assign` determinista e idempotente; no hay versión publicada que re-ejecutar. |
| Fuga de datos | Parcial | Test de fuga y CHECKs listos; corpus real sin splits. |
| Accesibilidad | Pendiente | Sin Playwright ni axe en CI (EF-21). |
| Observabilidad | Parcial | structlog JSON y canario de intake; falta tiempo y costo por capa (EF-19). |

---

## 3. Historias y criterios de aceptación

Rutas de tests relativas a `backend/tests/`. Detalle por criterio de las historias trabajadas:

### EF-01 (ADR): Parcial
- ADR-0001 a 0006 existen (Accepted). Sin test por naturaleza documental.
- **Hueco:** el criterio pide la franquicia de WhatsApp "confirmada en la documentación de Meta". ADR-0003 §4 admite que no se citó textualmente (la página mostraba el texto antiguo) y lo difiere a EF-23.

### EF-02 (monorepo y CI): Cumple
- Makefile, CI (Ruff, Mypy strict, Pytest, build de Next.js), caché de modelos y `.gitattributes` con LF. Sin test propio del Makefile ni de `.gitattributes`.
- La caché de spaCy no es explícita: ADR-0007 la delega en la caché de `uv`.

### EF-03 (migración inicial): Parcial
- Probado: 16 tablas (`integration/test_migrations.py::test_schema_has_the_sixteen_tables`), coincidencia modelos-migraciones, downgrade/upgrade, vector(384), roles, privilegios por defecto, `audit_log` append-only.
- **Hueco:** 13 CHECKs sin caso negativo en `integration/test_constraints.py::test_schema_rejects`: `ck_verifications_channel_valid`, `ck_verifications_external_message_hmac_format`, `ck_eval_results_{case_source_valid,expected_label_valid,route_valid,usage_non_negative}`, `ck_eval_runs_{dataset_version_format,live_calls_non_negative}`, `ck_labeling_tasks_label_valid`, `ck_rate_limit_windows_request_count_non_negative`, `ck_spend_ledger_{period_kind_valid,units_non_negative}`. Tampoco hay test del índice parcial `ix_verification_queue_ready` ni de `uq_labeling_tasks_verification_id`.

### EF-04 (Docker Compose): Cumple
- Probado: dos listeners con modelo compartido, readiness solo con el modelo cargado (`unit/test_api.py`), `docker compose up` en CI (job `compose` arm64) y en clon limpio (§8).
- Los dos workers arrancan pero no hacen trabajo útil hasta EF-23/24 (coherente con el plan).

### EF-05: No verificado
- Tarea del dueño. Sin evidencia en el repo del trámite con Meta. Fecha límite de decisión en la SPEC: 4 de enero.

### EF-06 (redacción): Parcial
- Probado: frontera de texto crudo, canarios, redacción determinista de 5 tipos, nombres PER, marcas exentas, `hide_input_in_errors`, 422 sin cuerpo, piso de nombres aplicado en CI.
- **Huecos:** los sets de nombres (`evals/redaction/names*.jsonl`) son sintéticos y ADR-0004 enmienda 1 exige re-medir con mensajes reales; los tipos deterministas no tienen recall sobre un set etiquetado; `esfake redaction-report` no tiene test; el canario del payload del juez usa un stub.

### EF-07 (corpus sin fugas): Parcial (código completo, datos pendientes)
- Probado (unit e integración): import idempotente, clúster, split 70/15/15 determinista y congelado, herencia, `excluded`, sintético descartado, test de fuga con la misma función y umbral.
- **Huecos:** `cluster_threshold_reviewed: false` y sin pares etiquetados commiteados; las 144 filas sin `case_id`, `cluster_id` ni `split`; la decisión del checkpoint de embeddings (ADR-0003 enmienda 1) sin resultado commiteado; el exceso de `excluded` sobre 5 % solo avisa.

### EF-08 (`make eval`): Parcial (código completo, v0 sin publicar)
- Probado: matriz 3×2, recall y Wilson, conteos, costo y rutas, política v0, `cached_strict` con "run make eval-record", predicciones por versión, McNemar y bootstrap pareado, exclusión de respuestas grabadas en vivo, pisos absolutos apagados por defecto, aviso antes de v0, manifiesto.
- **Hueco:** `docs/evals/v0.json` no existe, así que ningún test ni comando puede demostrar "publica la versión 0".

### EF-09: Parcial
- Tarea del dueño. 144 mensajes (84 estafas, 60 legítimos; 130 sintéticos y 14 alertas públicas) contra ≥ 400 antes del sprint 2 y ≥ 600 al cierre del sprint 3.

### EF-10 (LLMClient y líneas base): Pendiente
- Solo existe `ResponseCache` (`unit/test_llm_cache.py`). Sin cliente de Bedrock ni líneas base. Bloqueada por la cuenta de AWS del dueño.

### EF-11 (reglas e inyección): Parcial
- Probado (`unit/test_rules.py`): 27 reglas (18 de modalidad, 3 genéricas, 6 de inyección), un test parametrizado por cada ejemplo, offsets sobre el texto original, un `Signal` por regla, piso de inyección, la inyección no baja un veredicto, cableado en `build_pipeline`, validación del catálogo, `esfake rules check`.
- **Hueco:** el criterio "medida con la política v0" no es medible (sin casos `eval` ni v0). La única medición es informativa sobre el corpus semilla (0/60 legítimos marcados; 22/84 estafas con nivel ≠ `no_signals`), no la exige ningún test. El PR no lleva tabla de `make eval`.

### EF-12 a EF-14: Pendiente
- Sin `pipeline/urls`, `SimilarityIndex`, `LLMJudge`. `thresholds.yaml` no tiene k ni δ.

### EF-15: Parcial
- Pisos de inyección y de señal fuerte ya probados en la política v0. Faltan umbrales calibrados, modo degradado, plantilla de verificación limitada, tabla de verdad.

### EF-16, EF-17: Pendiente
- Sin plantillas ni `evals/redteam/`; `make redteam` es stub.

### EF-18 (despliegue): Parcial
- Existen `deploy/{deploy.sh,smoke.sh}`, `.github/workflows/cd.yml` apagado con `DEPLOY_ENABLED` y ADR-0007. Sin evidencia de VM, dominio, backup con restauración probada ni rollback ejecutado (tareas del dueño). **Bloqueante antes de encender el CD:** ver §4 (credenciales del owner).

### EF-19 (trazas): Parcial
- structlog JSON y canario de `message_redacted`. Faltan tiempo y costo por capa y canarios sobre logs de capas.

### EF-20 (API segura): Parcial
- Hecho: `/internal/*` en listener aparte con secreto y lista de proxies (`unit/test_api.py::test_internal_endpoints_require_the_shared_secret`, `unit/test_config.py::test_trusted_proxies_are_an_explicit_list`). Falta `POST /v1/verify`, topes, 429 y header falsificado.

### EF-21 a EF-30: Pendiente
- Web (EF-21), resultados (EF-22), WhatsApp (EF-23), feedback y borrado (EF-24), Ley 29733 (EF-25), `esfake label` (EF-26), `esfake report` (EF-27), piloto, README, v1.0. Existen solo esquemas y piezas de apoyo (`/internal/embed`, `KeyRing`, tablas).
- **Observación de orden:** la SPEC pone EF-25 al inicio del sprint 4, antes de EF-19 y de desplegar producción.

### Criterios sin test (resumen)
1. 13 CHECKs, el índice parcial de la cola y un UNIQUE (EF-03).
2. `esfake redaction-report` y recall por tipo determinista (EF-06).
3. Medición de recall y falsos positivos de las reglas con la política v0 (EF-11).
4. Publicación de la versión 0 (EF-08).
5. Confirmación textual de la franquicia de WhatsApp (EF-01).
6. `.gitattributes` y Makefile (EF-02).

---

## 4. Datos

Fuente: migraciones `0001..0004`, modelos en `shared/db/models/`, y 75 tests de integración ejecutados en la auditoría (`test_migrations`, `test_roles`, `test_constraints`, `test_modalities_seed`).

| Tabla | Frente a la SPEC | Estado |
| --- | --- | --- |
| `channel_identities` | Igual; CHECK extra de formato HMAC | Cumple |
| `verifications` | Igual; `external_message_hmac` nullable solo en web (CHECK); trigger extra `esfake_require_privacy_notice`; CHECKs extra de donación y de `text_purged_at` | Cumple |
| `verification_queue` | Índice parcial `ix_verification_queue_ready`, `attempts` 0..5, `UNIQUE(verification_id)`; sin test del índice | Cumple |
| `urls` | `lookalike_score` en [0,1] y ligado a `lookalike_of` (extra) | Cumple |
| `signals` | `neighbor_ids` solo con `layer = 'similarity'` (extra) | Cumple |
| `verdicts` | CHECKs de `likely_scam` con modalidad y de campos del modelo nulos iff `llm_used` falso | Cumple |
| `feedback` | Único por `verification_id`; no puede ir vacío (extra) | Cumple |
| `modalities` | Sembrada desde `config/modalities.yaml` (9 filas en el stack real) | Cumple |
| `corpus_messages` | CHECKs `legit` con subcategoría y `synthetic` fuera de `test`; `donation_provenance` y `vector(384)` NOT NULL; formato `^\d+\.\d+$` de `dataset_version` no definido en la SPEC | Cumple |
| `labeling_tasks` | Trigger `esfake_require_donation`; coherencia de `labeled` | Cumple |
| `pipeline_manifests` | Hash hexadecimal de 64 caracteres como PK | Cumple |
| `eval_runs`, `eval_results` | Igual; CHECK extra `correct` ligado al nivel | Cumple |
| `spend_ledger` | Subtope diario solo para `llm`; `billable_units <= units` | Cumple |
| `rate_limit_windows` | Igual | Cumple |
| `audit_log` | `REVOKE UPDATE, DELETE, TRUNCATE` a `esfake_app` más triggers que frenan también al owner (`test_roles.py`) | Cumple |
| Roles y bootstrap (ADR-0002) | `esfake_owner`, `esfake_app`, extensión `vector`, privilegios por defecto (`bootstrap/00-roles-and-extensions.sh`, `test_roles.py`) | Cumple |
| Credenciales del owner en runtime (ADR-0002 §6) | ✔ `docker-compose.yml:17` define `MIGRATIONS_DATABASE_URL` con el usuario `esfake_owner` dentro del ancla `x-backend`, usada por 4 servicios (líneas 42, 50, 68, 75). El comentario dice que solo `migrate` lo tiene; es falso. | **No cumple** |

Otros puntos: 16 tablas más `alembic_version` en el stack real, head en 0004. No hay índices para los jobs de retención (`verifications.received_at`, `text_purged_at`); aún no existen esos jobs. No hay índice vectorial, deliberado según ADR-0002 §5.

---

## 5. Decisiones (ADR)

Los siete ADR existen en inglés y ninguna referencia de SPEC o CLAUDE.md apunta a un ADR inexistente.

| ADR | Decisión | ¿Coincide lo implementado? | Estado |
| --- | --- | --- | --- |
| 0001 | Seis etapas, modelo solo con códigos, pisos, riesgo residual | Normalización, redacción, reglas y pisos v0 sí; URLs, similitud, juez, plantillas y modo degradado no | Parcial |
| 0002 | Cola en Postgres, `SKIP LOCKED`, lease 60 s, `LISTEN` directo, roles | Tabla, índice, roles, bootstrap y `LISTEN` sí; el worker no toma filas, no hay lease ni `SimilarityIndex`; los tests de concurrencia que enumera el ADR no existen | Parcial |
| 0003 | MiniLM-L12 (fastembed), Haiku 4.5 en Bedrock, topes, Oracle; enmienda 1 con e5-small | `config/models.yaml` usa MiniLM; falta el resultado del checkpoint y la enmienda 2; sin `LLMClient` | Parcial |
| 0004 | Texto crudo solo hasta el redactor; pisos del redactor por enmienda | Implementado y probado (`test_canaries.py`, `test_name_redaction.py`) | Cumple |
| 0005 | URLs sin red (PSL vendida, UTS #39, punycode) | Sin módulo `pipeline/urls` | Pendiente |
| 0006 | Margen −10 puntos fijado antes de medir; gate con McNemar o bootstrap | Gate implementado; la v0 que habilita la comparación no está publicada | Parcial |
| 0007 | CI en cada push, smoke arm64 en PR, CD por SSH apagado | Workflows y scripts presentes; smoke reproducido en local; CD real no verificado | Cumple |

---

## 6. Desviaciones

| # | Desviación | ¿ADR o plan que la justifica? |
| --- | --- | --- |
| 1 | Embeddings: el código usa MiniLM-L12 y e5-small queda como contendiente sin resultado | Sí: ADR-0003 enmienda 1 |
| 2 | `cluster_threshold: 0.90` provisional, `reviewed: false` | Sí: regla 12 de `CLAUDE.md` (se fija en EF-07 con ~100 pares) |
| 3 | Corpus de 144 mensajes sin asignar, mayoría sintéticos | Sí: EF-09 es tarea del dueño |
| 4 | Versión 0 sin publicar; el gate pasa en vacío | Sí: regla 11 (aviso antes de v0), pero depende de las tareas del dueño |
| 5 | ✔ Falta `time-machine` en las dependencias de desarrollo (`backend/pyproject.toml`); `CLAUDE.md` lo exige en el stack. Los tests usan un `FakeClock` propio | No |
| 6 | ✔ Credenciales de `esfake_owner` en todos los servicios del Compose (ver §4) | No: contradice ADR-0002 §6 |
| 7 | EF-11 antes que EF-10 por falta de cuenta de Bedrock | No hay ADR; decisión del dueño |
| 8 | Árbol de la SPEC desactualizado (`deploy/`, `models.yaml`, `subcategories.yaml`, `evals/redaction/`, módulos nuevos) | No |
| 9 | Canarios en `tests/integration/` en vez de `tests/canaries/` | No |
| 10 | La SPEC habla de `docs/evals/<versión>.json`; `published.py` busca `v*.json` | No (ambigüedad de nombre) |

Resumen: 4 justificadas, 6 sin justificar. Idioma de documentos: SPEC y BACKLOG en español, ADR en inglés, como manda `CLAUDE.md` (sin desviación). Stack: Python 3.14, FastAPI (reemplazado por Litestar 2.x en ADR-0008, posterior a esta auditoría), SQLAlchemy 2, Next.js 16 y Node 24 verificados; Playwright y axe aún no están en `web/package.json` (llegan con EF-21).

---

## 7. Riesgos de escalabilidad

| # | Riesgo | Evidencia | Severidad |
| --- | --- | --- | --- |
| 1 | ✔ `shared` importa `corpus`: la capa más baja depende de una alta | `shared/brands.py:8` importa `esfake.corpus.modalities.load_catalog` | Importante |
| 2 | ✔ Dependencia bidireccional `pipeline` ↔ `corpus` (hoy sin ciclo de módulos) | `pipeline/rules/catalog.py:15` importa `corpus.modalities`; `corpus/add.py:18-20` importa `pipeline.normalize`, `redaction`, `text` | Importante |
| 3 | ✔ `pipeline` importa `api`: el contrato del endpoint interno vive en el servidor | `pipeline/similarity/internal_client.py:14` importa `MAX_TEXTS`, `SECRET_HEADER`, `EmbedResponse` de `api.internal` | Importante |
| 4 | ✔ `fold()` duplicada con dos implementaciones; si divergen, reglas y redacción pliegan distinto | `pipeline/redaction/names.py:65` y `pipeline/rules/fold.py:11`; `evaluation/redaction.py:18` importa la primera | Importante |
| 5 | `cli/main.py` de 768 líneas con orquestación de negocio, y vienen `label`, `report`, `redteam` | `_evaluate` (líneas 58-139), `corpus_assign` (468-557); rutas por defecto relativas a `backend/` (líneas 36-38, 258) | Importante |
| 6 | Sin tests de capas ni documento de reglas, pese a tres inversiones ya presentes | ver §2, fila 14 | Importante |
| 7 | Cargadores YAML repetidos en seis módulos | `corpus/modalities.py:40`, `corpus/subcategories.py:36`, `shared/brands.py:27`, `shared/thresholds.py:63`, `shared/models_config.py:49`, `pipeline/rules/catalog.py:93` | Menor |
| 8 | Imports locales en casi todos los comandos de la CLI ocultan el mapa real de dependencias | `cli/main.py` (≈ 12 puntos) | Menor |
| 9 | Sin contrato de capa (`Protocol`): cada capa nueva se cablea a mano en `verifier.py` y en el harness; la política v0 se llama desde dos puntos | `pipeline/verifier.py`, `pipeline/rules/check.py` | Menor |
| 10 | `shared.models_config` importa un modelo ORM solo por una constante | `shared/models_config.py:9` | Menor |

Archivos grandes además de `cli/main.py`: `corpus/assign.py` (245), `shared/db/models/verification.py` (222), `shared/db/models/corpus.py` (206), `evaluation/embedding_comparison.py` (196). Ninguno es problemático todavía.

---

## 8. Reproducibilidad

Procedimiento: clon limpio con `git clone --branch feat/EF-11-rules-injection` en un directorio nuevo del scratchpad; proyecto de Compose aparte (`esfake-audit`); sin tocar contenedores ni volúmenes ajenos.

| Paso | Resultado |
| --- | --- |
| `docker compose -p esfake-audit up --detach --build --wait` | Correcto tras ≈ 12 min de build en frío; db, migrate (exit 0), api con `/readyz` y modelo cargado, web y los dos workers sanos |
| `sh deploy/smoke.sh` | Correcto: liveness, readiness con modelo, web y listener interno no publicado |
| Estado de la base | 16 tablas, head 0004, extensión `vector`, 9 modalidades sembradas |
| Pasos manuales no documentados | Ninguno; los secretos tienen valores `dev-insecure-*` por defecto y el aviso de reemplazarlos en producción está en `docker-compose.yml` y `.env.example` |
| `uv sync` y `uv run pytest tests/unit -q` | 330 passed |
| `npm ci && npm run build` en `web/` | Correcto |
| Suite completa en el repo de trabajo | 430 passed |
| Build y smoke en arm64 | No verificado localmente; el CI de GitHub lo corre en `ubuntu-24.04-arm` y estaba en verde |
| CD real contra la VM de Oracle | No verificado (requiere la VM, tarea del dueño) |
| Sin internet | No verificado si algún test descarga modelos de red |

Efecto secundario de la auditoría: quedan en Docker las imágenes `esfake-backend:local` y `esfake-web:local`. El resto se limpió con `down -v` y se borró el clon.

---

## Resumen por sección

Conteo de ítems evaluados en las tablas de cada sección. En §6 "Cumple" significa desviación justificada y "No cumple" sin justificar. En §7 la severidad importante cuenta como "No cumple" y la menor como "Parcial".

| Sección | Cumple | Parcial | Pendiente por plan | No cumple | No verificado |
| --- | --- | --- | --- | --- | --- |
| 1. Estructura | 8 | 3 | 4 | 3 | 0 |
| 2. Reglas de arquitectura | 1 | 15 | 12 | 1 | 1 |
| 3. Historias (EF-01 a EF-30) | 2 | 11 | 16 | 0 | 1 |
| 4. Datos | 16 | 0 | 0 | 1 | 0 |
| 5. ADR | 2 | 4 | 1 | 0 | 0 |
| 6. Desviaciones | 4 | 0 | 0 | 6 | 0 |
| 7. Escalabilidad | 0 | 4 | 0 | 6 | 0 |
| 8. Reproducibilidad | 7 | 0 | 0 | 0 | 2 |

Notas de conteo: §1 cuenta 18 filas de la tabla (8 Cumple; 3 Parcial = `pipeline/` incompleto, canarios en otro lugar, `evals/llm_cache`; 4 Pendiente = `urls/templates/prompts`, `channels/`, `evals/redteam`, `docs/evals/`; 3 No cumple = `docs/sprints/`, `ARCHITECTURE_RULES.md`, `README.md` y `CHANGELOG.md`). El árbol de la SPEC desactualizado se cuenta en §6. §2 cuenta 14 reglas y 16 requisitos. §4 cuenta 16 tablas más roles/bootstrap como Cumple y las credenciales del owner como No cumple.

---

## Correcciones priorizadas

### Bloqueantes
1. **Credenciales de `esfake_owner` expuestas a api y workers** (`docker-compose.yml:17`, ancla `x-backend`). Quitar `MIGRATIONS_DATABASE_URL` de `x-backend` y dejarla solo en `migrate`; añadir un test o chequeo en `deploy/smoke.sh` que verifique que `api` no ve la variable. Bloquea habilitar el CD (EF-18) y contradice ADR-0002 §6.
2. **Cerrar EF-07, EF-08 y EF-11 requiere datos del dueño.** Etiquetar ~100 pares, fijar `cluster_threshold_reviewed: true`, correr `esfake corpus assign` con `ESFAKE_CORPUS_HMAC_KEYS`, commitear el corpus y `dataset.json`, y publicar `esfake eval --publish v0`. Mientras tanto el gate de CI no protege nada.

### Importantes
3. Crear `docs/ARCHITECTURE_RULES.md` y un test de capas (por ejemplo import-linter) que impidan las inversiones de §7; fijar la convención de imports locales de la CLI.
4. Mover el catálogo de modalidades (`corpus/modalities.py`, parte de carga) a una capa baja (`shared/` o un paquete de catálogo) para corregir `shared/brands.py:8` y `pipeline/rules/catalog.py:15`.
5. Mover el contrato de `/internal/embed` (`MAX_TEXTS`, `SECRET_HEADER`, `EmbedResponse`) a un módulo neutral y que `pipeline/similarity/internal_client.py` deje de importar `api`.
6. Unificar `fold()` en un único módulo (por ejemplo `pipeline/text.py`) y que reglas, redacción y evaluación lo compartan.
7. Dividir `cli/main.py` (768 líneas) en subapps por área y mover la orquestación de `_evaluate` y `corpus_assign` a `evaluation/` y `corpus/`.
8. Añadir `time-machine` a las dependencias de desarrollo (stack obligatorio de `CLAUDE.md`) o registrar un ADR de excepción por el `FakeClock`.
9. Añadir casos negativos para los 13 CHECKs sin test y un test del índice parcial de la cola.
10. Conectar `/internal/verify` a `build_pipeline` (hoy responde 501) cuando corresponda, y adjuntar a EF-11 la tabla de `make eval` apenas exista la v0.
11. Resolver el checkpoint de embeddings (`esfake corpus compare-models`) y registrar la enmienda 2 de ADR-0003; confirmar la franquicia de WhatsApp en la documentación oficial de Meta (EF-23).
12. Re-medir la redacción de nombres con mensajes reales (ADR-0004 enmienda 1) y añadir un set etiquetado para los tipos deterministas.

### Menores
13. Crear `README.md`, `CHANGELOG.md` y `docs/sprints/`; actualizar el árbol de la SPEC (`deploy/`, `models.yaml`, `subcategories.yaml`, `evals/redaction/`, módulos nuevos).
14. Mover los canarios a `tests/canaries/` o actualizar la SPEC.
15. Aclarar el nombre de archivo de versiones (`<versión>.json` frente a `v*.json`).
16. Un helper común `load_yaml_model` para los seis cargadores; rutas por defecto de la CLI independientes del directorio de trabajo (relevante para EF-26 en producción).
17. Añadir test a `esfake redaction-report`; revisar si se conserva `web/AGENTS.md`; separar `generate_names.py` de los datos en `evals/redaction/`.
18. Evaluar un `Protocol` de capa para que URLs, similitud y juez se conecten sin tocar `verifier.py` y el harness; incluir un hash de `rules.yaml` en el manifiesto si se quiere trazabilidad independiente del commit.
19. Valorar abstraer `time.perf_counter()` en `evaluation/` para poder sustituirlo en pruebas.
20. Ejecutar un escáner de secretos sobre el historial (no verificado en esta auditoría).
