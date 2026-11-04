"""Casos de uso dos lançamentos: criar (com parcelamento), editar, excluir, baixar, transferir."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import date

from appfin.domain.entities import InstallmentGroup, Transaction
from appfin.domain.enums import (
    IntervalUnit,
    PaymentMethod,
    TransactionKind,
    TransactionStatus,
)
from appfin.domain.errors import BusinessRuleError, NotFoundError, ValidationError
from appfin.domain.installments import plan_installments
from appfin.domain.money import Money
from appfin.domain.repositories import UnitOfWork

MAX_BATCH = 1000


@dataclass(frozen=True, slots=True)
class TransactionDraft:
    """Dados do formulário "novo lançamento" (contas a receber ou a pagar)."""

    kind: TransactionKind
    description: str
    total: Money
    first_due: date
    account_id: str
    accrual_date: date | None = None  # padrão: data do 1º vencimento
    category_id: str | None = None
    contact_id: str | None = None
    payment_method: PaymentMethod | None = None
    document_number: str = ""
    notes: str = ""
    installments: int = 1
    interval_unit: IntervalUnit = IntervalUnit.MONTH
    interval_value: int = 1
    pay_now: bool = False  # "Receber/Pagar agora": quita a 1ª parcela na data abaixo
    paid_date: date | None = None


class TransactionService:
    def __init__(
        self,
        uow: Callable[[], UnitOfWork],
        new_id: Callable[[], str],
        today: Callable[[], date],
    ) -> None:
        self._uow = uow
        self._new_id = new_id
        self._today = today

    # ------------------------------------------------------------------ criar
    def create(self, draft: TransactionDraft) -> list[Transaction]:
        if draft.kind not in (TransactionKind.INCOME, TransactionKind.EXPENSE):
            raise ValidationError("kind", "Use a transferência para mover dinheiro entre contas.")
        plan = plan_installments(
            draft.total,
            draft.installments,
            draft.first_due,
            draft.interval_unit,
            draft.interval_value,
        )
        accrual = draft.accrual_date or draft.first_due
        paid_date = draft.paid_date or self._today()
        with self._uow() as uow:
            self._check_references(
                uow, draft.kind, draft.account_id, draft.category_id, draft.contact_id
            )
            group_id = None
            if len(plan) > 1:
                group = uow.transactions.add_installment_group(
                    InstallmentGroup(
                        self._new_id(),
                        len(plan),
                        draft.interval_unit,
                        draft.interval_value,
                        draft.total,
                    )
                )
                group_id = group.id
            created = []
            for item in plan:
                suffix = f" — parcela {item.number}/{len(plan)}" if len(plan) > 1 else ""
                paid = draft.pay_now and item.number == 1
                transaction = Transaction(
                    id=self._new_id(),
                    kind=draft.kind,
                    description=(draft.description.strip() + suffix),
                    amount=item.amount,
                    accrual_date=accrual,
                    due_date=item.due_date,
                    account_id=draft.account_id,
                    status=TransactionStatus.PAID if paid else TransactionStatus.PENDING,
                    paid_date=paid_date if paid else None,
                    category_id=draft.category_id,
                    contact_id=draft.contact_id,
                    payment_method=draft.payment_method,
                    document_number=draft.document_number,
                    notes=draft.notes,
                    installment_group_id=group_id,
                    installment_number=item.number if group_id else None,
                )
                created.append(uow.transactions.add(transaction))
            uow.commit()
        return created

    # ------------------------------------------------------------------ editar
    def get(self, transaction_id: str) -> Transaction:
        with self._uow() as uow:
            return _required(uow.transactions.get(transaction_id))

    def update(self, transaction: Transaction) -> Transaction:
        if transaction.kind.is_transfer:
            raise BusinessRuleError("Edite a transferência pela tela de transferências.")
        with self._uow() as uow:
            current = _required(uow.transactions.get(transaction.id))
            if current.kind != transaction.kind:
                raise ValidationError("kind", "Não é possível trocar receita por despesa.")
            self._check_references(
                uow,
                transaction.kind,
                transaction.account_id,
                transaction.category_id,
                transaction.contact_id,
                allow_archived_ids={current.account_id, current.category_id or ""},
            )
            # A origem da importação (lote e célula) não muda ao editar no app.
            saved = uow.transactions.update(
                replace(
                    transaction,
                    import_batch_id=current.import_batch_id,
                    import_row_key=current.import_row_key,
                )
            )
            uow.commit()
        return saved

    # ------------------------------------------------------------------ ações em lote
    def delete(self, transaction_ids: Iterable[str]) -> int:
        ids = _unique(transaction_ids)
        with self._uow() as uow:
            deleted: set[str] = set()
            for transaction_id in ids:
                if transaction_id in deleted:
                    continue
                transaction = _required(uow.transactions.get(transaction_id))
                legs = (
                    uow.transactions.list_by_transfer(transaction.transfer_id)
                    if transaction.transfer_id
                    else [transaction]
                )
                for leg in legs:  # transferência: as duas pernas juntas
                    uow.transactions.soft_delete(leg.id)
                    deleted.add(leg.id)
            uow.commit()
        return len(deleted)

    def mark_paid(
        self, transaction_ids: Iterable[str], paid_date: date, account_id: str | None = None
    ) -> int:
        ids = _unique(transaction_ids)
        with self._uow() as uow:
            if account_id is not None:
                account = _required(uow.accounts.get(account_id))
                if account.archived:
                    raise ValidationError("account_id", "Conta arquivada.")
            changed = 0
            for transaction_id in ids:
                transaction = _required(uow.transactions.get(transaction_id))
                if transaction.status is TransactionStatus.PAID:
                    continue
                uow.transactions.update(transaction.mark_paid(paid_date, account_id))
                changed += 1
            uow.commit()
        return changed

    def mark_pending(self, transaction_ids: Iterable[str]) -> int:
        ids = _unique(transaction_ids)
        with self._uow() as uow:
            changed = 0
            for transaction_id in ids:
                transaction = _required(uow.transactions.get(transaction_id))
                if transaction.status is not TransactionStatus.PAID or transaction.kind.is_transfer:
                    continue
                uow.transactions.update(transaction.mark_pending())
                changed += 1
            uow.commit()
        return changed

    # ------------------------------------------------------------------ transferência
    def transfer(
        self,
        from_account_id: str,
        to_account_id: str,
        amount: Money,
        on: date,
        description: str = "Transferência entre contas",
    ) -> tuple[Transaction, Transaction]:
        """Duas pernas ligadas pelo mesmo ``transfer_id``, gravadas na mesma transação (D5)."""
        if from_account_id == to_account_id:
            raise ValidationError("to_account_id", "Escolha contas diferentes.")
        transfer_id = self._new_id()
        with self._uow() as uow:
            for account_id in (from_account_id, to_account_id):
                account = _required(uow.accounts.get(account_id))
                if account.archived:
                    raise ValidationError("account_id", "Conta arquivada.")
            legs = []
            for kind, account_id in (
                (TransactionKind.TRANSFER_OUT, from_account_id),
                (TransactionKind.TRANSFER_IN, to_account_id),
            ):
                legs.append(
                    uow.transactions.add(
                        Transaction(
                            id=self._new_id(),
                            kind=kind,
                            description=description,
                            amount=amount,
                            accrual_date=on,
                            due_date=on,
                            account_id=account_id,
                            status=TransactionStatus.PAID,
                            paid_date=on,
                            payment_method=PaymentMethod.TRANSFER,
                            transfer_id=transfer_id,
                        )
                    )
                )
            uow.commit()
        return legs[0], legs[1]

    # ------------------------------------------------------------------ regras
    @staticmethod
    def _check_references(
        uow: UnitOfWork,
        kind: TransactionKind,
        account_id: str,
        category_id: str | None,
        contact_id: str | None,
        allow_archived_ids: set[str] | None = None,
    ) -> None:
        keep = allow_archived_ids or set()
        account = uow.accounts.get(account_id)
        if account is None or (account.archived and account.id not in keep):
            raise ValidationError("account_id", "Escolha uma conta ativa.")
        if category_id is not None:
            category = uow.categories.get(category_id)
            if category is None or (category.archived and category.id not in keep):
                raise ValidationError("category_id", "Escolha uma categoria ativa.")
            if not category.accepts(kind):
                raise ValidationError(
                    "category_id",
                    "Categoria de despesa em receita (ou o contrário). Escolha outra categoria.",
                )
        if contact_id is not None and uow.contacts.get(contact_id) is None:
            raise ValidationError("contact_id", "Contato não encontrado.")


def _unique(ids: Iterable[str]) -> list[str]:
    unique = list(dict.fromkeys(ids))
    if len(unique) > MAX_BATCH:
        raise ValidationError("ids", f"Selecione no máximo {MAX_BATCH} lançamentos por vez.")
    return unique


def _required[T](value: T | None) -> T:
    if value is None:
        raise NotFoundError("Lançamento não encontrado.")
    return value
