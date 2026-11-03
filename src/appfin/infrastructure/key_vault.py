"""Implementação do cofre de chaves em arquivo (``vault.json``)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from appfin.application.ports import DataKey, InvalidCredentialError, StorageUnavailableError
from appfin.infrastructure.crypto import errors as crypto_errors
from appfin.infrastructure.crypto import vault
from appfin.infrastructure.crypto.kdf import MINIMUM_SECURE_PARAMS, KdfParams
from appfin.infrastructure.crypto.secret import SecretBytes


@dataclass(frozen=True, slots=True)
class _PendingRecovery:
    based_on: vault.VaultEnvelope
    envelope: vault.VaultEnvelope


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

    def verify_password(self, password: str) -> None:
        """Confere a senha mestra (reautenticação antes de operações sensíveis)."""
        self.unlock_with_password(password).wipe()

    def prepare_recovery_key(self, key: DataKey) -> tuple[str, object]:
        if not isinstance(key, SecretBytes):
            raise TypeError("Chave de dados de tipo inesperado.")
        current = self._load()
        envelope, text = vault.replace_recovery_key(current, key)
        return text, _PendingRecovery(current, envelope)

    def commit_recovery_key(self, pending: object) -> None:
        if not isinstance(pending, _PendingRecovery):
            raise TypeError("Pendência de tipo inesperado.")
        if self._load() != pending.based_on:
            # O cofre mudou depois da geração (ex.: restauração): não sobrescrever.
            raise StorageUnavailableError("O cofre mudou; gere a chave novamente.")
        vault.save_envelope(pending.envelope, self._path)

    def envelope(self) -> vault.VaultEnvelope:
        return self._load()

    def _load(self) -> vault.VaultEnvelope:
        try:
            return vault.load_envelope(self._path)
        except crypto_errors.VaultFormatError as exc:
            raise StorageUnavailableError("Cofre ausente ou corrompido.") from exc
