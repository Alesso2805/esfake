# Reglas de arquitectura

Reglas de dependencia y de estructura del código de `esfake`. Complementan las reglas no negociables de `CLAUDE.md` (que fijan el comportamiento del producto) con las que mantienen el código mantenible. Cada regla dice cómo se verifica; las que aún no tienen test están marcadas como **por aplicar**.

Origen: auditoría `docs/AUDIT.md` (2026-10-12), sección 7.

## 1. Las dependencias van hacia abajo

Los paquetes de `backend/src/esfake/` se ordenan en capas, de la más baja a la más alta:

| Nivel | Paquetes | Qué contiene |
| --- | --- | --- |
| 0 | `shared` | Reloj, configuración, base de datos, HMAC, logging, catálogos de configuración |
| 1 | `pipeline` | Normalización, redacción, reglas, URLs, similitud, juez, política |
| 2 | `corpus` | Corpus, clústeres y splits |
| 3 | `evaluation` | Métricas, gate, líneas base, publicación de versiones |
| 4 | `api`, `workers` | Procesos de servicio |
| 5 | `cli` | Comandos |

- Un paquete solo importa paquetes de un nivel inferior o de su propio paquete.
- Dos paquetes del mismo nivel (`api` y `workers`) no se importan entre sí.
- Cuentan todos los imports: los de nivel de módulo, los de dentro de funciones y los de `TYPE_CHECKING`. Los imports locales de la CLI para no cargar modelos pesados están permitidos, pero siguen sujetos a esta regla.
- **Verificación:** `backend/tests/unit/test_architecture.py` (escaneo AST). Falla ante una dependencia nueva hacia arriba o lateral.

### Excepciones conocidas

Las violaciones que existían al crear la regla están listadas en `KNOWN_VIOLATIONS` de ese test, con su motivo. El test también falla cuando una excepción ya no se necesita, de modo que la lista solo puede encogerse. Cada excepción tiene una corrección prevista:

| Importador | Importa | Corrección |
| --- | --- | --- |
| `shared.brands` | `corpus` | Mover el catálogo de modalidades a `shared` |
| `pipeline.rules.catalog` | `corpus` | Igual: usar el catálogo de `shared` |
| `pipeline.similarity.internal_client` | `api` | Mover el contrato de `/internal/embed` a un módulo neutral |

No se agregan excepciones nuevas. Si un cambio las necesita, se rediseña la dependencia o se discute el orden de capas y se actualiza este documento.

## 2. Los contratos compartidos viven en la capa más baja que los usa

Un contrato (esquema de una petición, constante de cabecera, catálogo leído de un YAML) no se define en el proceso que lo sirve, sino en un módulo que cliente y servidor puedan importar. Un cliente nunca importa del servidor. **Verificación:** la regla 1 (el servidor está en una capa más alta que el cliente).

## 3. Una sola implementación por función de dominio — por aplicar

Una función de dominio (por ejemplo, plegar texto a minúsculas sin acentos) existe una sola vez y se importa. Dos copias divergen y las reglas y la redacción terminan tratando el mismo texto de forma distinta. Hoy `fold()` está duplicada en `pipeline/redaction/names.py` y `pipeline/rules/fold.py`; se unifica en una PR aparte. **Verificación prevista:** test que falle ante dos definiciones con el mismo nombre en `pipeline/`.

## 4. La CLI orquesta, no decide — por aplicar

`cli/` traduce opciones y códigos de salida; la lógica de negocio (qué se evalúa, qué se publica, qué se asigna) vive en `evaluation/` y `corpus/`. `cli/main.py` supera las 700 líneas y se divide por área antes de agregar `label`, `report` y `redteam`. **Verificación prevista:** límite de tamaño por archivo del paquete `cli`.

## 5. El texto crudo no cruza la frontera de la redacción

Reglamentado por ADR-0004 §1 y verificado por `backend/tests/unit/test_text_boundary.py`: solo `normalize` y `redaction` leen `RawText`, y solo `redaction` construye `RedactedText`.

## Cómo cambiar estas reglas

Un cambio en las capas o en las excepciones se hace en una PR que actualice este documento y el test juntos. Una decisión que cambie una regla de fondo se registra como ADR en `docs/adr/`.
