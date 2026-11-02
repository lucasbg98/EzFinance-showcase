"""Implementação do cofre de chaves em arquivo (``vault.json``)."""

from __future__ import annotations

from pathlib import Path

from appfin.application.ports import InvalidCredentialError, StorageUnavailableError
from appfin.infrastructure.crypto import errors as crypto_errors
from appfin.infrastructure.crypto import vault
from appfin.infrastructure.crypto.kdf import MINIMUM_SECURE_PARAMS, KdfParams
from appfin.infrastructure.crypto.secret import SecretBytes


class FileKeyVault:
    def __init__(
        self,
        path: Path,
        params: KdfParams,
        minimum: KdfParams = MINIMUM_SECURE_PARAMS,
    ) -> None:
        self._path = path
        self._params = params
        self._minimum = minimum

    def exists(self) -> bool:
        return self._path.exists()

    def create(self, password: str) -> tuple[str, SecretBytes]:
        if self.exists():
            raise StorageUnavailableError("O cofre já existe.")
        created = vault.create_vault(password, self._params)
        vault.save_envelope(created.envelope, self._path)
        return created.recovery_key, created.dek

    def unlock_with_password(self, password: str) -> SecretBytes:
        envelope = self._load()
        try:
            return vault.unlock_with_password(envelope, password, self._minimum)
        except crypto_errors.InvalidCredentialError as exc:
            raise InvalidCredentialError("Senha incorreta.") from exc

    def unlock_with_recovery_key(self, recovery_key: str) -> SecretBytes:
        envelope = self._load()
        try:
            return vault.unlock_with_recovery_key(envelope, recovery_key, self._minimum)
        except crypto_errors.InvalidCredentialError as exc:
            raise InvalidCredentialError("Chave de recuperação incorreta.") from exc

    def _load(self) -> vault.VaultEnvelope:
        try:
            return vault.load_envelope(self._path)
        except crypto_errors.VaultFormatError as exc:
            raise StorageUnavailableError("Cofre ausente ou corrompido.") from exc
