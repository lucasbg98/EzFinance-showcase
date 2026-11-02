import argon2.low_level
import pytest

from appfin.infrastructure.crypto.errors import VaultFormatError
from appfin.infrastructure.crypto.kdf import (
    MINIMUM_SECURE_PARAMS,
    PRODUCTION_PARAMS,
    KdfParams,
    derive_master_key,
    derive_subkey,
    normalize_password,
)
from appfin.infrastructure.crypto.secret import SecretBytes

SALT = bytes(range(16))


def test_argon2id_matches_independent_implementation() -> None:
    """libsodium (PyNaCl) e a implementação de referência (argon2-cffi) devem concordar."""
    params = KdfParams(opslimit=2, memlimit=64 * 1024 * 1024)

    ours = derive_master_key("frase secreta de teste", SALT, params).reveal()
    reference = argon2.low_level.hash_secret_raw(
        secret=b"frase secreta de teste",
        salt=SALT,
        time_cost=2,
        memory_cost=64 * 1024,  # KiB
        parallelism=1,  # libsodium usa paralelismo 1
        hash_len=32,
        type=argon2.low_level.Type.ID,
        version=19,
    )

    assert ours == reference


def test_derivation_is_deterministic_and_salt_dependent() -> None:
    params = KdfParams(opslimit=1, memlimit=8 * 1024)
    first = derive_master_key("senha", SALT, params).reveal()
    again = derive_master_key("senha", SALT, params).reveal()
    other_salt = derive_master_key("senha", bytes(16), params).reveal()

    assert first == again
    assert first != other_salt


def test_password_is_unicode_normalized() -> None:
    composed = "ação"
    decomposed = "ação"

    assert normalize_password(composed) == normalize_password(decomposed)


def test_rejects_wrong_salt_size() -> None:
    with pytest.raises(VaultFormatError):
        derive_master_key("senha", b"curto", KdfParams(1, 8 * 1024))


def test_production_params_are_above_minimum() -> None:
    assert PRODUCTION_PARAMS.is_at_least(MINIMUM_SECURE_PARAMS)
    assert MINIMUM_SECURE_PARAMS.memlimit >= 64 * 1024 * 1024
    assert MINIMUM_SECURE_PARAMS.opslimit >= 3


def test_hkdf_matches_rfc5869_test_case_3() -> None:
    """RFC 5869, caso 3 (salt e info vazios) — confere o uso correto do HKDF-SHA256."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    okm = HKDF(algorithm=hashes.SHA256(), length=42, salt=None, info=b"").derive(b"\x0b" * 22)

    assert okm.hex() == (
        "8da4e775a563c18f715f802a063c5a31b8a11f5c5ee1879ec3454e5f3c738d2d9d201395faa4b61a96c8"
    )


def test_subkeys_are_independent_per_purpose() -> None:
    key = SecretBytes(bytes(32))

    kek = derive_subkey(key, "kek").reveal()
    db = derive_subkey(key, "sqlcipher").reveal()

    assert kek != db
    assert len(kek) == len(db) == 32
