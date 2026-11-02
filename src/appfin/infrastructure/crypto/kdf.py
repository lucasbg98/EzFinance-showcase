"""Derivação de chaves.

- Senha mestra → chave mestra (MK): **Argon2id** (libsodium, ``crypto_pwhash`` alg. argon2id13).
- MK/DEK → subchaves independentes: **HKDF-SHA256** com ``info`` por finalidade.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

import nacl.pwhash
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from appfin.infrastructure.crypto.errors import VaultFormatError
from appfin.infrastructure.crypto.secret import SecretBytes

KEY_SIZE = 32
SALT_SIZE = nacl.pwhash.argon2id.SALTBYTES  # 16
ALGORITHM = "argon2id13"
_HKDF_INFO_PREFIX = b"appfin/v1/"
_MIB = 1024 * 1024


@dataclass(frozen=True, slots=True)
class KdfParams:
    """Custo do Argon2id. Guardado junto com o envelope para permitir subir no futuro."""

    opslimit: int
    memlimit: int

    def is_at_least(self, minimum: KdfParams) -> bool:
        return self.opslimit >= minimum.opslimit and self.memlimit >= minimum.memlimit


# Produção (docs/PROJETO.md §7.4): ~256 MiB, 3 iterações (~1 s na máquina alvo; calibrar na fase 0).
PRODUCTION_PARAMS = KdfParams(opslimit=3, memlimit=256 * _MIB)
# Piso aceito ao abrir um cofre: impede downgrade dos parâmetros por adulteração do arquivo.
MINIMUM_SECURE_PARAMS = KdfParams(opslimit=3, memlimit=64 * _MIB)


def normalize_password(password: str) -> bytes:
    """NFC + UTF-8: a mesma senha digitada em teclados/sistemas diferentes gera os mesmos bytes."""
    return unicodedata.normalize("NFC", password).encode("utf-8")


def derive_master_key(password: str, salt: bytes, params: KdfParams) -> SecretBytes:
    if len(salt) != SALT_SIZE:
        raise VaultFormatError("Salt com tamanho inválido.")
    if not password:
        raise ValueError("Senha vazia.")
    raw = nacl.pwhash.argon2id.kdf(
        KEY_SIZE,
        normalize_password(password),
        salt,
        opslimit=params.opslimit,
        memlimit=params.memlimit,
    )
    return SecretBytes(bytearray(raw))


def derive_subkey(key: SecretBytes, purpose: str, length: int = KEY_SIZE) -> SecretBytes:
    """Subchave independente por finalidade (``kek``, ``auth``, ``sqlcipher``, ``backup``…)."""
    if not purpose or not purpose.isascii():
        raise ValueError("Finalidade da subchave inválida.")
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=length,
        salt=None,
        info=_HKDF_INFO_PREFIX + purpose.encode("ascii"),
    )
    return SecretBytes(bytearray(hkdf.derive(key.reveal())))
