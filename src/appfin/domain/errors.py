"""Erros de domínio: tipos explícitos, nunca strings soltas."""


class DomainError(Exception):
    """Base de todos os erros de regra de negócio."""


class InvalidAmountError(DomainError):
    """Valor monetário inválido (tipo, casas decimais ou limite)."""


class CurrencyMismatchError(DomainError):
    """Operação entre valores de moedas diferentes."""
