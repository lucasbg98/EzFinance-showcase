"""Erros de domínio: tipos explícitos, nunca strings soltas."""


class DomainError(Exception):
    """Base de todos os erros de regra de negócio."""


class InvalidAmountError(DomainError):
    """Valor monetário inválido (tipo, casas decimais ou limite)."""


class CurrencyMismatchError(DomainError):
    """Operação entre valores de moedas diferentes."""


class ValidationError(DomainError):
    """Campo inválido. ``field`` permite à interface destacar o campo; a mensagem é amigável."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


class NotFoundError(DomainError):
    """Registro inexistente (ou excluído)."""


class ConcurrencyConflictError(DomainError):
    """O registro foi alterado depois de lido (concorrência otimista)."""


class BusinessRuleError(DomainError):
    """Operação que viola uma regra de negócio (mensagem amigável para a usuária)."""
