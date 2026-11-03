"""Emissão de recibo interno (comprovante complementar; o documento fiscal é a NFS-e)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from appfin.domain.amount_in_words import amount_in_words
from appfin.domain.entities import Company, Contact, Receipt, Transaction
from appfin.domain.enums import TransactionStatus
from appfin.domain.errors import BusinessRuleError, NotFoundError
from appfin.domain.repositories import UnitOfWork


@dataclass(frozen=True, slots=True)
class ReceiptData:
    """Tudo o que o PDF precisa — montado aqui para o gerador não acessar o banco."""

    receipt: Receipt
    company: Company
    transaction: Transaction
    contact: Contact | None
    amount_words: str
    reissue: bool


class ReceiptService:
    def __init__(
        self,
        uow: Callable[[], UnitOfWork],
        new_id: Callable[[], str],
        today: Callable[[], date],
    ) -> None:
        self._uow = uow
        self._new_id = new_id
        self._today = today

    def issue(self, transaction_id: str) -> ReceiptData:
        """Emite (ou reemite, com o mesmo número) o recibo de um lançamento pago."""
        with self._uow() as uow:
            transaction = uow.transactions.get(transaction_id)
            if transaction is None:
                raise NotFoundError("Lançamento não encontrado.")
            if transaction.kind.is_transfer:
                raise BusinessRuleError("Transferências entre contas não têm recibo.")
            if transaction.status is not TransactionStatus.PAID:
                raise BusinessRuleError(
                    "Só é possível emitir recibo de lançamento já recebido ou pago."
                )
            company = uow.company.get()
            if company is None:
                raise BusinessRuleError("Preencha os dados do consultório antes de emitir recibos.")
            existing = uow.receipts.get_by_transaction(transaction_id)
            if existing is None:
                receipt = uow.receipts.add(
                    Receipt(
                        self._new_id(),
                        uow.receipts.next_number(),
                        transaction_id,
                        self._today(),
                    )
                )
                uow.commit()
            else:
                receipt = existing
            contact = uow.contacts.get(transaction.contact_id) if transaction.contact_id else None
        return ReceiptData(
            receipt=receipt,
            company=company,
            transaction=transaction,
            contact=contact,
            amount_words=amount_in_words(transaction.amount.cents),
            reissue=existing is not None,
        )
