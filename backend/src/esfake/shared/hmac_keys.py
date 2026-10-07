"""HMAC-SHA256 with key ids (docs/SPEC.md, Esquema; ADR-0004 §1).

Digests are stored as "<key_id>:<hex>". New digests use the first key; lookups try every active
key, so a rotation adds a key in front and keeps the old one until its rows have expired.
"""

import hashlib
import hmac
import re
from collections.abc import Sequence

_KEY_ID = re.compile(r"[A-Za-z0-9_-]{1,32}")
MIN_SECRET_LENGTH = 16


class KeyRing:
    def __init__(self, keys: Sequence[tuple[str, str]]) -> None:
        if not keys:
            raise ValueError("at least one HMAC key is required")
        for key_id, secret in keys:
            if not _KEY_ID.fullmatch(key_id):
                raise ValueError("HMAC key ids use letters, digits, '_' or '-' (1 to 32)")
            if len(secret) < MIN_SECRET_LENGTH:
                raise ValueError(f"HMAC key {key_id} is shorter than {MIN_SECRET_LENGTH} chars")
        self._keys = [(key_id, secret.encode()) for key_id, secret in keys]

    @classmethod
    def parse(cls, spec: str) -> KeyRing:
        """Parse "k2:secret2,k1:secret1": the first key signs, every key verifies."""
        keys = []
        for item in spec.split(","):
            key_id, separator, secret = item.strip().partition(":")
            if not separator:
                raise ValueError("each HMAC key is written as <key_id>:<secret>")
            keys.append((key_id, secret))
        return cls(keys)

    def digest(self, value: str) -> str:
        key_id, secret = self._keys[0]
        return self._digest(key_id, secret, value)

    def candidates(self, value: str) -> list[str]:
        return [self._digest(key_id, secret, value) for key_id, secret in self._keys]

    @staticmethod
    def _digest(key_id: str, secret: bytes, value: str) -> str:
        return f"{key_id}:{hmac.new(secret, value.encode(), hashlib.sha256).hexdigest()}"
