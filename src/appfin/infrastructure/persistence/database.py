"""Abertura do banco local cifrado (SQLCipher 4).

- A chave é **bruta** (32 bytes derivados da DEK via HKDF ``"sqlcipher"``), passada em hexadecimal:
  o SQLCipher não roda seu próprio PBKDF2 (a derivação forte já foi feita com Argon2id).
- ``cipher_memory_security`` ligado: o SQLCipher zera a memória que ele aloca.
- Conexão em modo *autocommit* (``isolation_level=None``): transações são abertas explicitamente
  pela unit of work (``BEGIN IMMEDIATE`` … ``COMMIT``).
- Uma conexão por thread (skill ``concurrency``). Exceção controlada: a conexão pode ser **aberta**
  numa thread de trabalho (junto com o Argon2id do desbloqueio) e **entregue** à thread da UI, que
  passa a ser a única a usá-la. Por isso ``check_same_thread=False``; o SQLite embutido é compilado
  com ``THREADSAFE=1`` (serializado), verificado em teste.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import sqlcipher3

from appfin.infrastructure.crypto.kdf import derive_subkey
from appfin.infrastructure.crypto.secret import SecretBytes

DATABASE_KEY_PURPOSE = "sqlcipher"
BUSY_TIMEOUT_MS = 5000

Connection = Any  # sqlcipher3.Connection não tem stubs de tipo


class DatabaseError(Exception):
    """Base dos erros de persistência (mensagens sem dados)."""


class WrongDatabaseKeyError(DatabaseError):
    """O banco não abriu com a chave fornecida (chave errada ou arquivo corrompido)."""


def open_encrypted(path: Path, dek: SecretBytes) -> Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlcipher3.connect(str(path), isolation_level=None, check_same_thread=False)
    try:
        _silence_cipher_log(connection)
        with derive_subkey(dek, DATABASE_KEY_PURPOSE) as db_key:
            # PRAGMA não aceita parâmetro (?). A chave é hex gerado por nós, nunca entrada externa.
            connection.execute(f"PRAGMA key = \"x'{db_key.reveal().hex()}'\"")
        connection.execute("PRAGMA cipher_memory_security = ON")
        _verify_key(connection)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA secure_delete = ON")
        connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS:d}")
        connection.execute("PRAGMA journal_mode = WAL")
    except BaseException:
        connection.close()
        raise
    return connection


def _verify_key(connection: Connection) -> None:
    try:
        connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlcipher3.DatabaseError as exc:
        raise WrongDatabaseKeyError("Não foi possível abrir o banco de dados.") from exc


def _silence_cipher_log(connection: Connection) -> None:
    """O SQLCipher escreve erros de decifragem no stderr: evita ruído e pistas no console."""
    try:
        connection.execute("PRAGMA cipher_log_level = NONE")
    except sqlcipher3.DatabaseError:
        return
