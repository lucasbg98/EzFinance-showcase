"""Erros da camada de criptografia. Mensagens nunca contêm material sensível."""


class CryptoError(Exception):
    """Base dos erros de criptografia."""


class DecryptionError(CryptoError):
    """Falha de autenticação/decifragem (chave errada, dado adulterado ou AAD diferente)."""


class InvalidCredentialError(CryptoError):
    """Senha mestra ou chave de recuperação incorreta."""


class VaultFormatError(CryptoError):
    """Arquivo do cofre ausente, corrompido, de versão desconhecida ou com parâmetros inseguros."""


class SecretWipedError(CryptoError):
    """Tentativa de usar um segredo já apagado (app bloqueado)."""
