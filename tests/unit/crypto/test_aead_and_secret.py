import pytest

from appfin.infrastructure.crypto import aead
from appfin.infrastructure.crypto.errors import DecryptionError, SecretWipedError
from appfin.infrastructure.crypto.secret import SecretBytes

KEY = SecretBytes(bytes(range(32)))


def test_roundtrip() -> None:
    blob = aead.encrypt(KEY, b"dado sintetico", b"contexto")

    assert aead.decrypt(KEY, blob, b"contexto") == b"dado sintetico"
    assert b"dado sintetico" not in blob


def test_same_plaintext_gives_different_ciphertexts() -> None:
    assert aead.encrypt(KEY, b"x", b"a") != aead.encrypt(KEY, b"x", b"a")


def test_wrong_aad_fails() -> None:
    blob = aead.encrypt(KEY, b"x", b"registro-1")

    with pytest.raises(DecryptionError):
        aead.decrypt(KEY, blob, b"registro-2")


def test_wrong_key_fails() -> None:
    blob = aead.encrypt(KEY, b"x", b"a")

    with pytest.raises(DecryptionError):
        aead.decrypt(SecretBytes(bytes(32)), blob, b"a")


@pytest.mark.parametrize("position", [0, 30, -1])
def test_any_flipped_bit_is_detected(position: int) -> None:
    blob = bytearray(aead.encrypt(KEY, b"conteudo", b"a"))
    blob[position] ^= 0x01

    with pytest.raises(DecryptionError):
        aead.decrypt(KEY, bytes(blob), b"a")


def test_truncated_blob_fails() -> None:
    with pytest.raises(DecryptionError):
        aead.decrypt(KEY, b"\x00" * 10, b"a")


def test_secret_is_hidden_from_repr_and_wiped() -> None:
    source = bytearray(b"\x07" * 32)
    secret = SecretBytes(source)

    assert source == bytearray(32), "a origem mutável deve ser zerada"
    assert "07" not in repr(secret) and "\\x07" not in str(secret)

    secret.wipe()

    assert secret.is_wiped
    with pytest.raises(SecretWipedError):
        secret.reveal()


def test_context_manager_wipes() -> None:
    with SecretBytes(b"\x01" * 32) as secret:
        assert secret.reveal() == b"\x01" * 32

    assert secret.is_wiped
