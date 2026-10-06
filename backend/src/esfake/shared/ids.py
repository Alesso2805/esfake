"""Primary keys are UUID v7 generated in the application (docs/SPEC.md, Esquema)."""

import uuid


def new_id() -> uuid.UUID:
    return uuid.uuid7()
