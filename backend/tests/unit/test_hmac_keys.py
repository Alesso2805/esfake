import re

import pytest

from esfake.shared.db.base import HMAC_PATTERN
from esfake.shared.hmac_keys import KeyRing

SECRET = "first-test-secret-0001"  # noqa: S105
OLD_SECRET = "older-test-secret-0000"  # noqa: S105


def test_digests_carry_their_key_id_and_match_the_stored_format() -> None:
    digest = KeyRing.parse(f"k1:{SECRET}").digest("hola")

    assert digest.startswith("k1:")
    assert re.fullmatch(HMAC_PATTERN, digest)


def test_rotation_signs_with_the_new_key_and_still_finds_old_digests() -> None:
    old = KeyRing.parse(f"k1:{OLD_SECRET}")
    rotated = KeyRing.parse(f"k2:{SECRET},k1:{OLD_SECRET}")

    assert rotated.digest("hola").startswith("k2:")
    assert old.digest("hola") in rotated.candidates("hola")


@pytest.mark.parametrize(
    ("spec", "error"),
    [
        ("no-separator", "<key_id>:<secret>"),
        ("k1:abc123", "shorter than"),
        ("bad id!:long-enough-secret-123", "key ids"),
    ],
)
def test_invalid_key_specs_fail_without_echoing_the_secret(spec: str, error: str) -> None:
    with pytest.raises(ValueError, match=error) as raised:
        KeyRing.parse(spec)

    secret = spec.partition(":")[2]
    assert not secret or secret not in str(raised.value)
