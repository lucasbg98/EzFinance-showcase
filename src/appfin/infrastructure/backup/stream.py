"""Formato do arquivo de backup cifrado (``.afbkp``), versão 1.

Layout::

    MAGIC (8 bytes)
    tamanho do cabeçalho (uint32, big-endian) + cabeçalho JSON (UTF-8)
    cabeçalho do secretstream (24 bytes)
    mensagens: tamanho (uint32, big-endian) + texto cifrado
        1ª mensagem: manifesto JSON (data, versão, contagens); AD = MAGIC + cabeçalho
        demais: o arquivo do banco em blocos; a última com TAG_FINAL

- Cifra: ``crypto_secretstream_xchacha20poly1305`` (libsodium) com a chave ``HKDF(DEK, "backup")``
  (docs/PROJETO.md §7.6). O secretstream detecta blocos adulterados, reordenados, removidos ou
  repetidos; exigir a TAG_FINAL no fim detecta arquivo **truncado**.
- O cabeçalho é público, mas **autenticado** (entra como AD da 1ª mensagem): traz o envelope do
  cofre da época do backup (só cópias **cifradas** da DEK), para restaurar em outro computador com
  a senha mestra ou a chave de recuperação daquela época.
- O banco gravado no backup já é o arquivo SQLCipher (cifrado com a subchave ``sqlcipher``):
  nenhum dado em claro passa pelo disco nem na criação nem na restauração.
- Entrada não confiável na leitura: limites de tamanho em tudo antes de alocar.
"""

from __future__ import annotations

import json
import struct
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

import nacl.bindings as sodium
import nacl.exceptions

from appfin.infrastructure.crypto.kdf import derive_subkey
from appfin.infrastructure.crypto.secret import SecretBytes

MAGIC = b"AFBACKUP"
FORMAT_NAME = "appfin-backup"
FORMAT_VERSION = 1
KEY_PURPOSE = "backup"
CHUNK_SIZE = 1024 * 1024
MAX_HEADER_BYTES = 64 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
MAX_DATABASE_BYTES = 4 * 1024 * 1024 * 1024
_LENGTH = struct.Struct(">I")
_ABYTES = sodium.crypto_secretstream_xchacha20poly1305_ABYTES
_STREAM_HEADER = sodium.crypto_secretstream_xchacha20poly1305_HEADERBYTES
_TAG_MESSAGE = sodium.crypto_secretstream_xchacha20poly1305_TAG_MESSAGE
_TAG_FINAL = sodium.crypto_secretstream_xchacha20poly1305_TAG_FINAL


class BackupFormatError(Exception):
    """Arquivo que não é um backup do app, corrompido, adulterado ou incompleto."""


@dataclass(frozen=True, slots=True)
class BackupHeader:
    raw: bytes  # bytes exatos lidos do arquivo (autenticados como AD)
    vault: dict[str, Any]


def encode_header(vault_document: dict[str, Any]) -> bytes:
    document = {"format": FORMAT_NAME, "version": FORMAT_VERSION, "vault": vault_document}
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def write_backup(
    target: BinaryIO,
    header: bytes,
    manifest: dict[str, Any],
    database: Path,
    dek: SecretBytes,
) -> None:
    if len(header) > MAX_HEADER_BYTES:
        raise BackupFormatError("Cabeçalho grande demais.")
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode("utf-8")
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise BackupFormatError("Manifesto grande demais.")
    state = sodium.crypto_secretstream_xchacha20poly1305_state()
    with derive_subkey(dek, KEY_PURPOSE) as key:
        stream_header = sodium.crypto_secretstream_xchacha20poly1305_init_push(state, key.reveal())
    target.write(MAGIC + _LENGTH.pack(len(header)) + header + stream_header)
    _write_message(target, state, manifest_bytes, MAGIC + header, _TAG_MESSAGE)
    with database.open("rb") as source:
        chunk = source.read(CHUNK_SIZE)
        while True:
            following = source.read(CHUNK_SIZE)
            tag = _TAG_FINAL if not following else _TAG_MESSAGE
            _write_message(target, state, chunk, None, tag)
            if not following:
                break
            chunk = following


def read_header(source: BinaryIO) -> BackupHeader:
    if source.read(len(MAGIC)) != MAGIC:
        raise BackupFormatError("O arquivo não é um backup do AppFinanceiro.")
    length = _read_length(source, MAX_HEADER_BYTES)
    raw = _read_exact(source, length)
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupFormatError("Cabeçalho do backup corrompido.") from exc
    if (
        not isinstance(document, dict)
        or document.get("format") != FORMAT_NAME
        or not isinstance(document.get("vault"), dict)
    ):
        raise BackupFormatError("Cabeçalho do backup corrompido.")
    if document.get("version") != FORMAT_VERSION:
        raise BackupFormatError("Backup de uma versão de formato desconhecida.")
    return BackupHeader(raw=raw, vault=document["vault"])


def read_backup(
    source: BinaryIO, header: BackupHeader, dek: SecretBytes, database_out: BinaryIO
) -> dict[str, Any]:
    """Decifra o resto do arquivo (depois de ``read_header``) e grava o banco em ``database_out``.

    Retorna o manifesto. Qualquer adulteração, troca de chave ou truncamento levanta
    ``BackupFormatError`` (o chamador deve descartar o que foi gravado).
    """
    stream_header = _read_exact(source, _STREAM_HEADER)
    state = sodium.crypto_secretstream_xchacha20poly1305_state()
    with derive_subkey(dek, KEY_PURPOSE) as key:
        try:
            sodium.crypto_secretstream_xchacha20poly1305_init_pull(
                state, stream_header, key.reveal()
            )
        except nacl.exceptions.CryptoError as exc:
            raise BackupFormatError("Backup corrompido.") from exc
    messages = _messages(source, state, MAGIC + header.raw)
    manifest_bytes, tag = next(messages, (b"", -1))
    if tag != _TAG_MESSAGE:
        raise BackupFormatError("Backup incompleto.")
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupFormatError("Manifesto do backup corrompido.") from exc
    if not isinstance(manifest, dict):
        raise BackupFormatError("Manifesto do backup corrompido.")
    written = 0
    finished = False
    for chunk, tag in messages:
        written += len(chunk)
        if written > MAX_DATABASE_BYTES:
            raise BackupFormatError("Backup grande demais.")
        database_out.write(chunk)
        if tag == _TAG_FINAL:
            finished = True
            break
    if not finished:
        raise BackupFormatError("Backup incompleto (arquivo truncado).")
    if source.read(1):
        raise BackupFormatError("Backup com dados extras depois do fim.")
    return manifest


# ---------------------------------------------------------------------- auxiliares
def _write_message(
    target: BinaryIO, state: Any, message: bytes, ad: bytes | None, tag: int
) -> None:
    ciphertext = sodium.crypto_secretstream_xchacha20poly1305_push(state, message, ad, tag)
    target.write(_LENGTH.pack(len(ciphertext)) + ciphertext)


def _messages(source: BinaryIO, state: Any, first_ad: bytes) -> Iterator[tuple[bytes, int]]:
    ad: bytes | None = first_ad
    limit = max(CHUNK_SIZE, MAX_MANIFEST_BYTES) + _ABYTES
    while True:
        prefix = source.read(_LENGTH.size)
        if not prefix:
            return
        if len(prefix) != _LENGTH.size:
            raise BackupFormatError("Backup incompleto (arquivo truncado).")
        (length,) = _LENGTH.unpack(prefix)
        if length < _ABYTES or length > limit:
            raise BackupFormatError("Backup corrompido.")
        ciphertext = _read_exact(source, length)
        try:
            message, tag = sodium.crypto_secretstream_xchacha20poly1305_pull(state, ciphertext, ad)
        except nacl.exceptions.CryptoError as exc:
            raise BackupFormatError(
                "Não foi possível decifrar o backup: arquivo adulterado ou corrompido."
            ) from exc
        ad = None
        yield message, tag


def _read_length(source: BinaryIO, maximum: int) -> int:
    (length,) = _LENGTH.unpack(_read_exact(source, _LENGTH.size))
    if length > maximum:
        raise BackupFormatError("Backup corrompido.")
    return int(length)


def _read_exact(source: BinaryIO, size: int) -> bytes:
    data = source.read(size)
    if len(data) != size:
        raise BackupFormatError("Backup incompleto (arquivo truncado).")
    return data
