"""Cifra autenticada: XChaCha20-Poly1305 (libsodium), nonce aleatório de 192 bits.

Formato do blob: ``nonce (24 bytes) || ciphertext+tag``.
O AAD (dados associados) amarra o texto cifrado ao seu contexto: um blob copiado para outro
contexto (outro registro, outro usuário, outra finalidade) não decifra.
"""

from __future__ import annotations

import nacl.bindings
import nacl.exceptions
import nacl.utils

from appfin.infrastructure.crypto.errors import DecryptionError
from appfin.infrastructure.crypto.secret import SecretBytes

NONCE_SIZE = nacl.bindings.crypto_aead_xchacha20poly1305_ietf_NPUBBYTES  # 24
TAG_SIZE = nacl.bindings.crypto_aead_xchacha20poly1305_ietf_ABYTES  # 16
KEY_SIZE = nacl.bindings.crypto_aead_xchacha20poly1305_ietf_KEYBYTES  # 32


def encrypt(key: SecretBytes, plaintext: bytes, aad: bytes) -> bytes:
    _check_key(key)
    nonce = nacl.utils.random(NONCE_SIZE)
    ciphertext = nacl.bindings.crypto_aead_xchacha20poly1305_ietf_encrypt(
        plaintext, aad, nonce, key.reveal()
    )
    return nonce + ciphertext


def decrypt(key: SecretBytes, blob: bytes, aad: bytes) -> bytes:
    _check_key(key)
    if len(blob) < NONCE_SIZE + TAG_SIZE:
        raise DecryptionError("Dado cifrado inválido.")
    nonce, ciphertext = blob[:NONCE_SIZE], blob[NONCE_SIZE:]
    try:
        return nacl.bindings.crypto_aead_xchacha20poly1305_ietf_decrypt(
            ciphertext, aad, nonce, key.reveal()
        )
    except nacl.exceptions.CryptoError as exc:
        raise DecryptionError(
            "Não foi possível decifrar: chave incorreta ou dado adulterado."
        ) from exc


def _check_key(key: SecretBytes) -> None:
    if len(key) != KEY_SIZE:
        raise ValueError("Chave com tamanho inválido.")
