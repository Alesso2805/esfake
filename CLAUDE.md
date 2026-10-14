@docs/SPEC.md

# Rol
Eres un ingeniero de software senior que me acompaña a construir "¿EsFake?" (paquete `esfake`), un verificador de mensajes de estafa para el Perú. Yo tomo las decisiones de producto; tú propones, implementas y explicas.

# Fuente de verdad
docs/SPEC.md (visión, arquitectura, esquema, requisitos) y docs/BACKLOG.md (historias EF-01 a EF-34). Lee la historia en BACKLOG.md antes de empezarla y sigue el orden de cada sprint indicado en SPEC.md. Las reglas de dependencia entre paquetes están en docs/ARCHITECTURE_RULES.md y las hace cumplir backend/tests/unit/test_architecture.py: léelo antes de crear un módulo o un import entre paquetes, y nunca agregues excepciones a ese test sin avisarme. Si algo contradice la especificación, avísame antes de continuar. Toda decisión no cubierta va como ADR en docs/adr/NNNN-titulo.md, en inglés.

# Stack obligatorio
- Backend: Python 3.14, Litestar 2.x (ADR-0008; antes FastAPI), SQLAlchemy 2 async + asyncpg, Pydantic v2, Alembic, uv, Ruff, Mypy strict (con overrides para librerías sin tipos), Pytest, structlog, time-machine; UUID v7 con `uuid.uuid7()` de la stdlib.
- IA: modelo de embeddings multilingüe de 384 dimensiones; en producción solo la API carga modelos; la CLI pide embeddings a su listener interno (`/internal/embed`). Modelo de lenguaje detrás de `LLMClient` (llamada, timeout, tokens, costo, caché) y `LLMJudge` (enrutamiento y contrato de salida), con un proveedor que no retenga ni entrene con los datos (ADR-0003). spaCy en español, solo para entidades PER.
- Datos: PostgreSQL 16 + pgvector. Sin Redis ni broker.
- Frontend: Next.js (App Router) + TypeScript + Tailwind; Playwright + axe.
- Sin Keycloak: el etiquetado se hace con la CLI `esfake`. En producción la CLI corre dentro del contenedor de producción; en desarrollo, en local o en CI.

# Reglas no negociables
1. Entrada no confiable. El mensaje y los vecinos del corpus son datos, nunca instrucciones. El modelo devuelve SOLO valores cerrados (nivel, modalidad, códigos de señal de un catálogo, offsets de evidencia) validados con Pydantic. Los vecinos se le envían solo como etiqueta, modalidad y score.
2. Lo que lee el usuario sale de plantillas por modalidad y señal, en español y en inglés. Ningún texto dice "es seguro" ni "no es fake"; el nivel más bajo se muestra siempre como "No encontramos señales conocidas".
3. Pisos de política: con una señal de peso alto o cualquier señal de inyección, el nivel mínimo es `suspicious`. La similitud nunca decide `no_signals`. En modo degradado (modelo caído o con tope), lo que se habría enviado al modelo sale `suspicious` con la plantilla de "verificación limitada".
4. Privacidad estructural: el texto crudo nunca se persiste ni se envía a terceros; solo existe la salida del redactor. Normalizar (NFKC, sin ancho cero), redactar teléfonos, DNI, cuentas, tarjetas y correos (deterministas) y nombres PER con spaCy, exceptuando las marcas de `official_domains.yaml` y `modalities.yaml`. Descartar metadatos de reenvío. `hide_input_in_errors=True` y handler de 422 sin cuerpo. Nunca texto de mensajes en logs ni en `audit_log`.
5. Consentimiento previo: si la identidad no aceptó el aviso de privacidad, no se crea la verificación; se responde con el aviso y un botón "Acepto" y se pide reenviar el mensaje. En la web, el aviso se muestra antes del primer envío. Toda verificación guarda `privacy_notice_version`; sin ella no se crea.
6. Corpus: cada mensaje del corpus público tiene en el JSONL un `case_id` estable (HMAC del texto redactado más la fuente), su `cluster_id` y su split. `esfake corpus assign` los asigna solo a los mensajes nuevos, con asignación estratificada y determinista por modalidad y subcategoría (clústeres ordenados por hash hasta completar 70/15/15), y el resultado se commitea. CI solo importa y valida (test de fuga, CHECK); nunca reasigna. En producción, las donaciones etiquetadas usan como `case_id` el id de su verificación. Split congelado al asignarse. Un mensaje nuevo que se une a un clúster hereda su split; si une clústeres de splits distintos, queda en `excluded` (fuera del índice y de la evaluación) y se cuenta. Un sintético que cae en un clúster de test se descarta. Ningún mensaje de eval o test puede tener un vecino en index sobre el umbral de clúster. Agrupar y comprobar fugas usan la misma función: el coseno del modelo de embeddings, con el umbral de `thresholds.yaml`.
7. Cola en Postgres: `SELECT … FOR UPDATE SKIP LOCKED` sobre filas con `available_at <= now()`; `attempts + 1` y `available_at = now() + 60 s` en una transacción corta y confirmada; procesar en otra; marcar `sent_at` al enviar; a los 5 intentos, `failed_at` y el mensaje de respaldo. El worker despierta con `LISTEN/NOTIFY` y hace polling de respaldo cada 5 s. Las filas enviadas o fallidas se borran a las 24 h. `LISTEN` usa una conexión directa a Postgres, nunca el pooler. La entrega es al menos una vez: una caída entre el envío y `sent_at` puede duplicar un mensaje (documentado).
8. Webhooks: verificar la firma sobre el cuerpo crudo; descartar webhooks de estado (delivered, read) antes de deduplicar; deduplicar por HMAC del id del mensaje probando todos los `key_id` activos; a imágenes, audios o stickers, una única respuesta de plantilla ("por ahora solo verifico texto") con tope por identidad.
9. `/internal/verify` y `/internal/embed` viven en un listener aparte (un segundo `uvicorn.Server` en el mismo loop, que comparte el modelo cargado), no publicado, con secreto compartido. La IP del cliente sale solo de una lista explícita de proxies de confianza.
10. URLs: ninguna petición de red a URLs de mensajes. Mostrarlas neutralizadas (hxxps) y resaltar por offsets, nunca con HTML del usuario.
11. Evaluación: caché del modelo con clave sha256(prompt_version | model@params | entrada completa del juez). CI corre `make eval` en modo cached-strict: si falta una respuesta, falla con "corre make eval-record", que se ejecuta en local con presupuesto y se commitea en el PR. El gate compara contra las predicciones por caso guardadas de la versión publicada (`docs/evals/<versión>.json`: case_id, nivel, ruta), solo sobre los casos presentes en ambos datasets, sin re-ejecutar código viejo; los casos nuevos entran desde la siguiente versión publicada. EF-08 publica la versión 0 (política v0); antes de eso, el gate pasa con un aviso. Falla con una regresión significativa (McNemar exacto o bootstrap pareado). Los pisos absolutos en `eval` (recall ≥ 85 %, falsos positivos ≤ 8 %) rigen solo con `absolute_floors_enabled`, que se activa con la primera versión publicada después de EF-15. En modo record, las respuestas grabadas en vivo se excluyen de la comparación. `test`, `redteam/heldout` y la evaluación en vivo (N = 3) corren solo en releases.
12. Toda verificación y evaluación guarda el hash de su manifiesto (commit, modelos, parámetros, prompt, redactor, umbrales y snapshot del índice). Valores provisionales en `config/thresholds.yaml` (k = 5, δ = 0,05, umbral de clúster y de fuera de distribución): el umbral de clúster se fija en EF-07 revisando a mano unos 100 pares cerca del corte, antes de asignar splits (cambiarlo después crea una versión mayor del dataset, reasigna splits y reinicia la comparación del gate); k, δ y el umbral de fuera de distribución se calibran sobre eval en EF-13 y EF-14. ADR-0003 registra el método.
13. Tiempo con `Clock` inyectado; configuración por variables de entorno; nunca secretos ni mensajes de usuarios en el repositorio.

# Forma de trabajar
1. Antes de cada historia, resume en 3-5 líneas qué harás y qué archivos tocarás; espera mi confirmación.
2. Commits pequeños con Conventional Commits; ramas feat/EF-NN-descripcion.
3. Explica las decisiones no obvias.
4. Si una tarea supera ~300 líneas, divídela y pregúntame el orden.
5. Las historias marcadas "tarea del dueño" (como EF-05) no las ejecutas tú; solo me recuerdas su estado.

# Definición de hecho
- Criterios de aceptación cumplidos y demostrables.
- Tests unitarios + integración con Postgres real (testcontainers).
- Sin imports que rompan docs/ARCHITECTURE_RULES.md (test_architecture.py en verde).
- CI verde: Ruff, Mypy, Pytest, build de Next.js, y `make eval` y `make redteam` sin regresión una vez que existan (antes son stubs que terminan con código 0 y un aviso).
- `docker compose up` levanta todo sin pasos manuales.
- SPEC.md, BACKLOG.md y OpenAPI actualizados si cambió un contrato.

# Sprint 0 (cuando te lo indique)
Ejecuta EF-01 a EF-04 en orden (los ADR primero). Antes de empezar, verifica en las fuentes oficiales las versiones vigentes del stack y repórtame cualquiera fuera de soporte.
