"""Cofre de chaves (envelope da DEK).

Hierarquia (docs/PROJETO.md §7.4):

    senha mestra --Argon2id--> MK --HKDF("kek")----------> KEK --cifra--> DEK
    chave de recuperação (256 bits) --HKDF("recovery-kek")--> RKEK --cifra--> DEK (2ª cópia)

- A **DEK** (chave de dados) é aleatória; o banco e os backups usam subchaves dela.
- Trocar a senha só recifra o envelope; os dados não mudam.
- O cabeçalho (formato, versão, parâmetros do KDF, salt) entra no **AAD** da cópia da senha:
  adulterar o arquivo (ex.: baixar os parâmetros do Argon2id) faz a abertura falhar. Além disso,
  parâmetros abaixo do mínimo seguro são recusados antes de qualquer derivação.
- O envelope não contém segredo em claro; ele fica fora do banco (que depende dele para abrir).
"""

from __future__ import annotations

import base64
import binascii
import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from appfin.infrastructure.crypto import aead
from appfin.infrastructure.crypto.errors import (
    DecryptionError,
    InvalidCredentialError,
    VaultFormatError,
)
from appfin.infrastructure.crypto.kdf import (
    ALGORITHM,
    KEY_SIZE,
    MINIMUM_SECURE_PARAMS,
    SALT_SIZE,
    KdfParams,
    derive_master_key,
    derive_subkey,
)
from appfin.infrastructure.crypto.secret import SecretBytes

FORMAT_NAME = "appfin-vault"
FORMAT_VERSION = 1
_RECOVERY_GROUP = 4
_RECOVERY_CHARS = 52  # 32 bytes em base32, sem padding
_MAX_ENVELOPE_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class VaultEnvelope:
    params: KdfParams
    salt: bytes
    wrapped_dek: bytes
    wrapped_dek_recovery: bytes


@dataclass(frozen=True, slots=True)
class CreatedVault:
    envelope: VaultEnvelope
    recovery_key: str  # exibida UMA vez para a usuária guardar; nunca persistida pelo app
    dek: SecretBytes


# ---------------------------------------------------------------------- operações
def create_vault(password: str, params: KdfParams) -> CreatedVault:
    salt = secrets.token_bytes(SALT_SIZE)
    dek = SecretBytes(bytearray(secrets.token_bytes(KEY_SIZE)))
    recovery_raw = SecretBytes(bytearray(secrets.token_bytes(KEY_SIZE)))
    try:
        wrapped = _wrap_with_password(dek, password, salt, params)
        with derive_subkey(recovery_raw, "recovery-kek") as rkek:
            wrapped_recovery = aead.encrypt(rkek, dek.reveal(), _recovery_aad())
        recovery_text = format_recovery_key(recovery_raw.reveal())
    finally:
        recovery_raw.wipe()
    envelope = VaultEnvelope(params, salt, wrapped, wrapped_recovery)
    return CreatedVault(envelope=envelope, recovery_key=recovery_text, dek=dek)


def unlock_with_password(
    envelope: VaultEnvelope,
    password: str,
    minimum: KdfParams = MINIMUM_SECURE_PARAMS,
) -> SecretBytes:
    _require_secure_params(envelope.params, minimum)
    with (
        derive_master_key(password, envelope.salt, envelope.params) as master,
        derive_subkey(master, "kek") as kek,
    ):
        try:
            raw = aead.decrypt(
                kek, envelope.wrapped_dek, _password_aad(envelope.params, envelope.salt)
            )
        except DecryptionError as exc:
            raise InvalidCredentialError("Senha incorreta.") from exc
    return SecretBytes(bytearray(raw))


def unlock_with_recovery_key(
    envelope: VaultEnvelope,
    recovery_key: str,
    minimum: KdfParams = MINIMUM_SECURE_PARAMS,
) -> SecretBytes:
    _require_secure_params(envelope.params, minimum)
    with (
        SecretBytes(bytearray(parse_recovery_key(recovery_key))) as recovery_raw,
        derive_subkey(recovery_raw, "recovery-kek") as rkek,
    ):
        try:
            raw = aead.decrypt(rkek, envelope.wrapped_dek_recovery, _recovery_aad())
        except DecryptionError as exc:
            raise InvalidCredentialError("Chave de recuperação incorreta.") from exc
    return SecretBytes(bytearray(raw))


def change_password(
    envelope: VaultEnvelope, dek: SecretBytes, new_password: str, params: KdfParams
) -> VaultEnvelope:
    """Recifra só a cópia da DEK protegida pela senha, com salt novo (e parâmetros possivelmente
    mais fortes). A cópia protegida pela chave de recuperação não muda: os dados não são recifrados.
    """
    salt = secrets.token_bytes(SALT_SIZE)
    wrapped = _wrap_with_password(dek, new_password, salt, params)
    return VaultEnvelope(params, salt, wrapped, envelope.wrapped_dek_recovery)


# ---------------------------------------------------------------------- chave de recuperação
def format_recovery_key(raw: bytes) -> str:
    text = base64.b32encode(raw).decode("ascii").rstrip("=")
    groups = [text[i : i + _RECOVERY_GROUP] for i in range(0, len(text), _RECOVERY_GROUP)]
    return "-".join(groups)


def parse_recovery_key(text: str) -> bytes:
    compact = "".join(text.split()).replace("-", "").upper()
    if len(compact) != _RECOVERY_CHARS:
        raise InvalidCredentialError("Chave de recuperação em formato inválido.")
    try:
        raw = base64.b32decode(compact + "====", casefold=False)
    except (binascii.Error, ValueError) as exc:
        raise InvalidCredentialError("Chave de recuperação em formato inválido.") from exc
    if len(raw) != KEY_SIZE:
        raise InvalidCredentialError("Chave de recuperação em formato inválido.")
    return raw


# ---------------------------------------------------------------------- persistência
def save_envelope(envelope: VaultEnvelope, path: Path) -> None:
    """Grava de forma atômica (arquivo temporário + ``os.replace``)."""
    document = {
        **_header(envelope.params, envelope.salt),
        "wrapped_dek": _b64(envelope.wrapped_dek),
        "wrapped_dek_recovery": _b64(envelope.wrapped_dek_recovery),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def load_envelope(path: Path) -> VaultEnvelope:
    try:
        if path.stat().st_size > _MAX_ENVELOPE_BYTES:
            raise VaultFormatError("Arquivo do cofre grande demais.")
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise VaultFormatError("Cofre não encontrado.") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VaultFormatError("Arquivo do cofre corrompido.") from exc
    return _parse_document(document)


def _parse_document(document: Any) -> VaultEnvelope:
    try:
        if document["format"] != FORMAT_NAME or document["version"] != FORMAT_VERSION:
            raise VaultFormatError("Formato do cofre desconhecido.")
        kdf = document["kdf"]
        if kdf["algorithm"] != ALGORITHM:
            raise VaultFormatError("Algoritmo de derivação desconhecido.")
        params = KdfParams(opslimit=_int(kdf["opslimit"]), memlimit=_int(kdf["memlimit"]))
        salt = _unb64(kdf["salt"])
        if len(salt) != SALT_SIZE:
            raise VaultFormatError("Salt inválido.")
        return VaultEnvelope(
            params=params,
            salt=salt,
            wrapped_dek=_unb64(document["wrapped_dek"]),
            wrapped_dek_recovery=_unb64(document["wrapped_dek_recovery"]),
        )
    except (KeyError, TypeError) as exc:
        raise VaultFormatError("Arquivo do cofre corrompido.") from exc


# ---------------------------------------------------------------------- auxiliares
def _wrap_with_password(dek: SecretBytes, password: str, salt: bytes, params: KdfParams) -> bytes:
    with derive_master_key(password, salt, params) as master, derive_subkey(master, "kek") as kek:
        return aead.encrypt(kek, dek.reveal(), _password_aad(params, salt))


def _header(params: KdfParams, salt: bytes) -> dict[str, Any]:
    return {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "kdf": {
            "algorithm": ALGORITHM,
            "opslimit": params.opslimit,
            "memlimit": params.memlimit,
            "salt": _b64(salt),
        },
    }


def _password_aad(params: KdfParams, salt: bytes) -> bytes:
    """AAD da cópia protegida pela senha: amarra formato, versão, parâmetros e salt."""
    canonical = json.dumps(_header(params, salt), sort_keys=True, separators=(",", ":"))
    return canonical.encode("ascii") + b"|password"


def _recovery_aad() -> bytes:
    """AAD da cópia de recuperação: não usa Argon2, então não depende de salt/parâmetros."""
    return f"{FORMAT_NAME}|{FORMAT_VERSION}|recovery".encode("ascii")


def _require_secure_params(params: KdfParams, minimum: KdfParams) -> None:
    if not params.is_at_least(minimum):
        raise VaultFormatError("Parâmetros de derivação abaixo do mínimo seguro.")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: Any) -> bytes:
    if not isinstance(text, str):
        raise VaultFormatError("Arquivo do cofre corrompido.")
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise VaultFormatError("Arquivo do cofre corrompido.") from exc


def _int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise VaultFormatError("Arquivo do cofre corrompido.")
    return int(value)
