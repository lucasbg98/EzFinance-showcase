"""Repositórios SQLCipher + unit of work.

- SQL 100% parametrizado; nada de concatenação com entrada externa.
- ``update`` exige a ``version`` lida (``WHERE id = ? AND version = ?``): concorrência otimista.
- Toda escrita entra na ``outbox`` na mesma transação (sincronização da fase 2).
- Repositórios não fazem commit: só a ``SqlUnitOfWork``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime
from typing import Any, Self, TypeVar

from appfin.domain.entities import (
    Account,
    Category,
    Company,
    Contact,
    InstallmentGroup,
    Receipt,
    Transaction,
)
from appfin.domain.enums import (
    AccountKind,
    CategoryKind,
    ContactRole,
    DreGroup,
    IntervalUnit,
    LegalType,
    PaymentMethod,
    PersonType,
    TaxRegime,
    TransactionKind,
    TransactionStatus,
)
from appfin.domain.errors import ConcurrencyConflictError, NotFoundError
from appfin.domain.money import Money
from appfin.infrastructure.persistence.database import Connection

Row = tuple[Any, ...]
E = TypeVar("E")


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _required_date(value: str) -> date:
    return date.fromisoformat(value)


class _Base:
    _table: str
    _entity: str

    def __init__(self, connection: Connection, now: Callable[[], datetime]) -> None:
        self._db = connection
        self._now = now

    def _timestamp(self) -> str:
        return self._now().isoformat()

    @staticmethod
    def _require_saved_id(record_id: str) -> None:
        if not record_id:
            raise ValueError("Entidade sem id: o caso de uso deve atribuir um antes de gravar.")

    def _enqueue(self, record_id: str, operation: str = "upsert") -> None:
        self._db.execute(
            "INSERT INTO outbox (entity, record_id, operation, created_at) VALUES (?, ?, ?, ?)",
            (self._entity, record_id, operation, self._timestamp()),
        )

    def _check_updated(self, cursor: Any, record_id: str) -> None:
        if cursor.rowcount == 1:
            return
        # Tabela fixa da própria classe (não vem de entrada externa).
        exists = self._db.execute(
            f"SELECT 1 FROM {self._table} WHERE id = ? AND deleted_at IS NULL",  # noqa: S608  # nosec B608
            (record_id,),
        ).fetchone()
        if exists:
            raise ConcurrencyConflictError("O registro foi alterado em outro lugar. Recarregue.")
        raise NotFoundError("Registro não encontrado.")

    def _soft_delete(self, record_id: str) -> None:
        now = self._timestamp()
        cursor = self._db.execute(
            f"UPDATE {self._table} SET deleted_at = ?, updated_at = ?, version = version + 1 "  # noqa: S608  # nosec B608
            "WHERE id = ? AND deleted_at IS NULL",
            (now, now, record_id),
        )
        if cursor.rowcount != 1:
            raise NotFoundError("Registro não encontrado.")
        self._enqueue(record_id, "delete")


# ---------------------------------------------------------------------- empresa
class SqlCompanyRepository(_Base):
    _table = "company"
    _entity = "company"
    _columns = (
        "legal_type, name, trade_name, document, cro_number, responsible, address, phone, "
        "whatsapp, email, tax_regime"
    )

    def get(self) -> Company | None:
        row = self._db.execute(
            f"SELECT id, {self._columns}, version FROM company WHERE id = 'company'"  # noqa: S608  # nosec B608
        ).fetchone()
        if row is None:
            return None
        return Company(
            id=row[0],
            legal_type=LegalType(row[1]),
            name=row[2],
            trade_name=row[3],
            document=row[4],
            cro_number=row[5],
            responsible=row[6],
            address=row[7],
            phone=row[8],
            whatsapp=row[9],
            email=row[10],
            tax_regime=TaxRegime(row[11]),
            version=row[12],
        )

    def _values(self, c: Company) -> Row:
        return (
            c.legal_type.value,
            c.name,
            c.trade_name,
            c.document,
            c.cro_number,
            c.responsible,
            c.address,
            c.phone,
            c.whatsapp,
            c.email,
            c.tax_regime.value,
        )

    def add(self, company: Company) -> Company:
        now = self._timestamp()
        self._db.execute(
            f"INSERT INTO company (id, {self._columns}, version, created_at, updated_at) "  # noqa: S608  # nosec B608
            "VALUES ('company', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (*self._values(company), now, now),
        )
        self._enqueue(company.id)
        return replace(company, version=1)

    def update(self, company: Company) -> Company:
        cursor = self._db.execute(
            "UPDATE company SET legal_type = ?, name = ?, trade_name = ?, document = ?, "
            "cro_number = ?, responsible = ?, address = ?, phone = ?, whatsapp = ?, email = ?, "
            "tax_regime = ?, version = version + 1, updated_at = ? "
            "WHERE id = 'company' AND version = ?",
            (*self._values(company), self._timestamp(), company.version),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflictError("Os dados da empresa foram alterados. Recarregue.")
        self._enqueue(company.id)
        return replace(company, version=company.version + 1)


# ---------------------------------------------------------------------- conta
class SqlAccountRepository(_Base):
    _table = "account"
    _entity = "account"
    _select = (
        "SELECT id, name, kind, opening_balance_cents, currency, opening_date, archived, version "
        "FROM account WHERE deleted_at IS NULL"
    )

    @staticmethod
    def _map(row: Row) -> Account:
        return Account(
            id=row[0],
            name=row[1],
            kind=AccountKind(row[2]),
            opening_balance=Money(row[3], row[4]),
            opening_date=_date(row[5]),
            archived=bool(row[6]),
            version=row[7],
        )

    def get(self, account_id: str) -> Account | None:
        row = self._db.execute(self._select + " AND id = ?", (account_id,)).fetchone()
        return self._map(row) if row else None

    def list(self, *, include_archived: bool = False) -> list[Account]:
        sql = self._select + ("" if include_archived else " AND archived = 0")
        rows = self._db.execute(sql + " ORDER BY archived, name COLLATE NOCASE").fetchall()
        return [self._map(row) for row in rows]

    def add(self, account: Account) -> Account:
        self._require_saved_id(account.id)
        now = self._timestamp()
        self._db.execute(
            "INSERT INTO account (id, name, kind, opening_balance_cents, currency, opening_date, "
            "archived, version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (
                account.id,
                account.name,
                account.kind.value,
                account.opening_balance.cents,
                account.opening_balance.currency,
                _iso(account.opening_date),
                int(account.archived),
                now,
                now,
            ),
        )
        self._enqueue(account.id)
        return replace(account, version=1)

    def update(self, account: Account) -> Account:
        cursor = self._db.execute(
            "UPDATE account SET name = ?, kind = ?, opening_balance_cents = ?, currency = ?, "
            "opening_date = ?, archived = ?, version = version + 1, updated_at = ? "
            "WHERE id = ? AND version = ? AND deleted_at IS NULL",
            (
                account.name,
                account.kind.value,
                account.opening_balance.cents,
                account.opening_balance.currency,
                _iso(account.opening_date),
                int(account.archived),
                self._timestamp(),
                account.id,
                account.version,
            ),
        )
        self._check_updated(cursor, account.id)
        self._enqueue(account.id)
        return replace(account, version=account.version + 1)


# ---------------------------------------------------------------------- categoria
class SqlCategoryRepository(_Base):
    _table = "category"
    _entity = "category"
    _select = (
        "SELECT id, name, kind, parent_id, dre_group, archived, version "
        "FROM category WHERE deleted_at IS NULL"
    )

    @staticmethod
    def _map(row: Row) -> Category:
        return Category(
            id=row[0],
            name=row[1],
            kind=CategoryKind(row[2]),
            parent_id=row[3],
            dre_group=DreGroup(row[4]) if row[4] else None,
            archived=bool(row[5]),
            version=row[6],
        )

    def get(self, category_id: str) -> Category | None:
        row = self._db.execute(self._select + " AND id = ?", (category_id,)).fetchone()
        return self._map(row) if row else None

    def list(self, *, include_archived: bool = False) -> list[Category]:
        sql = self._select + ("" if include_archived else " AND archived = 0")
        rows = self._db.execute(sql + " ORDER BY name COLLATE NOCASE").fetchall()
        return [self._map(row) for row in rows]

    def count(self) -> int:
        row = self._db.execute("SELECT count(*) FROM category WHERE deleted_at IS NULL").fetchone()
        return int(row[0])

    def add(self, category: Category) -> Category:
        self._require_saved_id(category.id)
        now = self._timestamp()
        self._db.execute(
            "INSERT INTO category (id, parent_id, name, kind, dre_group, archived, version, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (
                category.id,
                category.parent_id,
                category.name,
                category.kind.value,
                category.dre_group.value if category.dre_group else None,
                int(category.archived),
                now,
                now,
            ),
        )
        self._enqueue(category.id)
        return replace(category, version=1)

    def update(self, category: Category) -> Category:
        cursor = self._db.execute(
            "UPDATE category SET parent_id = ?, name = ?, kind = ?, dre_group = ?, archived = ?, "
            "version = version + 1, updated_at = ? WHERE id = ? AND version = ? "
            "AND deleted_at IS NULL",
            (
                category.parent_id,
                category.name,
                category.kind.value,
                category.dre_group.value if category.dre_group else None,
                int(category.archived),
                self._timestamp(),
                category.id,
                category.version,
            ),
        )
        self._check_updated(cursor, category.id)
        self._enqueue(category.id)
        return replace(category, version=category.version + 1)


# ---------------------------------------------------------------------- contato
class SqlContactRepository(_Base):
    _table = "contact"
    _entity = "contact"
    _fields = (
        "name, roles, person_type, document, phone, email, street, number, district, city, "
        "state, zip_code, notes, archived"
    )
    _select = f"SELECT id, {_fields}, version FROM contact WHERE deleted_at IS NULL"  # noqa: S608  # nosec B608

    @staticmethod
    def _map(row: Row) -> Contact:
        return Contact(
            id=row[0],
            name=row[1],
            roles=frozenset(ContactRole(r) for r in row[2].split(",")),
            person_type=PersonType(row[3]),
            document=row[4],
            phone=row[5],
            email=row[6],
            street=row[7],
            number=row[8],
            district=row[9],
            city=row[10],
            state=row[11],
            zip_code=row[12],
            notes=row[13],
            archived=bool(row[14]),
            version=row[15],
        )

    @staticmethod
    def _values(c: Contact) -> Row:
        return (
            c.name,
            ",".join(sorted(role.value for role in c.roles)),
            c.person_type.value,
            c.document,
            c.phone,
            c.email,
            c.street,
            c.number,
            c.district,
            c.city,
            c.state,
            c.zip_code,
            c.notes,
            int(c.archived),
        )

    def get(self, contact_id: str) -> Contact | None:
        row = self._db.execute(self._select + " AND id = ?", (contact_id,)).fetchone()
        return self._map(row) if row else None

    def search(self, text: str = "", *, limit: int = 200, offset: int = 0) -> list[Contact]:
        pattern = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = self._db.execute(
            self._select + " AND archived = 0 AND name LIKE ? ESCAPE '\\' "
            "ORDER BY name COLLATE NOCASE LIMIT ? OFFSET ?",
            (pattern, min(max(limit, 1), 1000), max(offset, 0)),
        ).fetchall()
        return [self._map(row) for row in rows]

    def add(self, contact: Contact) -> Contact:
        self._require_saved_id(contact.id)
        now = self._timestamp()
        self._db.execute(
            f"INSERT INTO contact (id, {self._fields}, version, created_at, updated_at) "  # noqa: S608  # nosec B608
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (contact.id, *self._values(contact), now, now),
        )
        self._enqueue(contact.id)
        return replace(contact, version=1)

    def update(self, contact: Contact) -> Contact:
        cursor = self._db.execute(
            "UPDATE contact SET name = ?, roles = ?, person_type = ?, document = ?, phone = ?, "
            "email = ?, street = ?, number = ?, district = ?, city = ?, state = ?, zip_code = ?, "
            "notes = ?, archived = ?, version = version + 1, updated_at = ? "
            "WHERE id = ? AND version = ? AND deleted_at IS NULL",
            (*self._values(contact), self._timestamp(), contact.id, contact.version),
        )
        self._check_updated(cursor, contact.id)
        self._enqueue(contact.id)
        return replace(contact, version=contact.version + 1)

    def soft_delete(self, contact_id: str) -> None:
        self._soft_delete(contact_id)

    def is_referenced(self, contact_id: str) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM financial_transaction WHERE contact_id = ? AND deleted_at IS NULL "
            "LIMIT 1",
            (contact_id,),
        ).fetchone()
        return row is not None


# ---------------------------------------------------------------------- lançamento
class SqlTransactionRepository(_Base):
    _table = "financial_transaction"
    _entity = "transaction"
    _fields = (
        "kind, description, amount_cents, currency, accrual_date, due_date, paid_date, status, "
        "account_id, category_id, contact_id, payment_method, document_number, "
        "official_receipt_ref, notes, installment_group_id, installment_number, transfer_id, "
        "import_batch_id"
    )
    _select = (
        f"SELECT id, {_fields}, version FROM financial_transaction "  # noqa: S608  # nosec B608
        "WHERE deleted_at IS NULL"
    )

    @staticmethod
    def _map(row: Row) -> Transaction:
        return Transaction(
            id=row[0],
            kind=TransactionKind(row[1]),
            description=row[2],
            amount=Money(row[3], row[4]),
            accrual_date=_required_date(row[5]),
            due_date=_required_date(row[6]),
            paid_date=_date(row[7]),
            status=TransactionStatus(row[8]),
            account_id=row[9],
            category_id=row[10],
            contact_id=row[11],
            payment_method=PaymentMethod(row[12]) if row[12] else None,
            document_number=row[13],
            official_receipt_ref=row[14],
            notes=row[15],
            installment_group_id=row[16],
            installment_number=row[17],
            transfer_id=row[18],
            import_batch_id=row[19],
            version=row[20],
        )

    @staticmethod
    def _values(t: Transaction) -> Row:
        return (
            t.kind.value,
            t.description,
            t.amount.cents,
            t.amount.currency,
            t.accrual_date.isoformat(),
            t.due_date.isoformat(),
            _iso(t.paid_date),
            t.status.value,
            t.account_id,
            t.category_id,
            t.contact_id,
            t.payment_method.value if t.payment_method else None,
            t.document_number,
            t.official_receipt_ref,
            t.notes,
            t.installment_group_id,
            t.installment_number,
            t.transfer_id,
            t.import_batch_id,
        )

    def get(self, transaction_id: str) -> Transaction | None:
        row = self._db.execute(self._select + " AND id = ?", (transaction_id,)).fetchone()
        return self._map(row) if row else None

    def list_by_installment_group(self, group_id: str) -> list[Transaction]:
        rows = self._db.execute(
            self._select + " AND installment_group_id = ? ORDER BY installment_number", (group_id,)
        ).fetchall()
        return [self._map(row) for row in rows]

    def list_by_transfer(self, transfer_id: str) -> list[Transaction]:
        rows = self._db.execute(
            self._select + " AND transfer_id = ? ORDER BY kind", (transfer_id,)
        ).fetchall()
        return [self._map(row) for row in rows]

    def add(self, transaction: Transaction) -> Transaction:
        self._require_saved_id(transaction.id)
        now = self._timestamp()
        placeholders = ", ".join("?" * 20)
        self._db.execute(
            f"INSERT INTO financial_transaction (id, {self._fields}, version, created_at, "  # noqa: S608  # nosec B608
            f"updated_at) VALUES ({placeholders}, 1, ?, ?)",
            (transaction.id, *self._values(transaction), now, now),
        )
        self._enqueue(transaction.id)
        return replace(transaction, version=1)

    def update(self, transaction: Transaction) -> Transaction:
        assignments = ", ".join(f"{name.strip()} = ?" for name in self._fields.split(","))
        cursor = self._db.execute(
            f"UPDATE financial_transaction SET {assignments}, version = version + 1, "  # noqa: S608  # nosec B608
            "updated_at = ? WHERE id = ? AND version = ? AND deleted_at IS NULL",
            (
                *self._values(transaction),
                self._timestamp(),
                transaction.id,
                transaction.version,
            ),
        )
        self._check_updated(cursor, transaction.id)
        self._enqueue(transaction.id)
        return replace(transaction, version=transaction.version + 1)

    def soft_delete(self, transaction_id: str) -> None:
        self._soft_delete(transaction_id)

    def add_installment_group(self, group: InstallmentGroup) -> InstallmentGroup:
        now = self._timestamp()
        self._db.execute(
            "INSERT INTO installment_group (id, count, interval_unit, interval_value, total_cents, "
            "version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
            (
                group.id,
                group.count,
                group.interval_unit.value,
                group.interval_value,
                group.total.cents,
                now,
                now,
            ),
        )
        self._db.execute(
            "INSERT INTO outbox (entity, record_id, operation, created_at) VALUES (?, ?, ?, ?)",
            ("installment_group", group.id, "upsert", now),
        )
        return replace(group, version=1)

    def get_installment_group(self, group_id: str) -> InstallmentGroup | None:
        row = self._db.execute(
            "SELECT id, count, interval_unit, interval_value, total_cents, version "
            "FROM installment_group WHERE id = ? AND deleted_at IS NULL",
            (group_id,),
        ).fetchone()
        if row is None:
            return None
        return InstallmentGroup(
            id=row[0],
            count=row[1],
            interval_unit=IntervalUnit(row[2]),
            interval_value=row[3],
            total=Money(row[4]),
            version=row[5],
        )

    def count_by_category(self, category_id: str) -> int:
        row = self._db.execute(
            "SELECT count(*) FROM financial_transaction WHERE category_id = ? "
            "AND deleted_at IS NULL",
            (category_id,),
        ).fetchone()
        return int(row[0])

    def count_by_account(self, account_id: str) -> int:
        row = self._db.execute(
            "SELECT count(*) FROM financial_transaction WHERE account_id = ? "
            "AND deleted_at IS NULL",
            (account_id,),
        ).fetchone()
        return int(row[0])


# ---------------------------------------------------------------------- recibo
class SqlReceiptRepository(_Base):
    _table = "receipt"
    _entity = "receipt"

    def get_by_transaction(self, transaction_id: str) -> Receipt | None:
        row = self._db.execute(
            "SELECT id, number, transaction_id, issued_on, version FROM receipt "
            "WHERE transaction_id = ?",
            (transaction_id,),
        ).fetchone()
        if row is None:
            return None
        return Receipt(row[0], row[1], row[2], _required_date(row[3]), row[4])

    def next_number(self) -> int:
        # Chamado dentro da unit of work (BEGIN IMMEDIATE): sem corrida entre duas emissões.
        row = self._db.execute("SELECT COALESCE(MAX(number), 0) + 1 FROM receipt").fetchone()
        return int(row[0])

    def add(self, receipt: Receipt) -> Receipt:
        self._require_saved_id(receipt.id)
        now = self._timestamp()
        self._db.execute(
            "INSERT INTO receipt (id, number, transaction_id, issued_on, version, created_at, "
            "updated_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
            (
                receipt.id,
                receipt.number,
                receipt.transaction_id,
                receipt.issued_on.isoformat(),
                now,
                now,
            ),
        )
        self._enqueue(receipt.id)
        return replace(receipt, version=1)


# ---------------------------------------------------------------------- preferências
class SqlSettingsRepository:
    """Tabela ``setting`` (chave/valor). Preferências locais: fora da fila de sincronização."""

    def __init__(self, connection: Connection, now: Callable[[], datetime]) -> None:
        self._db = connection
        self._now = now

    def get(self, key: str) -> str | None:
        row = self._db.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row[0])

    def set(self, key: str, value: str | None) -> None:
        if value is None:
            self._db.execute("DELETE FROM setting WHERE key = ?", (key,))
            return
        self._db.execute(
            "INSERT INTO setting (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (key, value, self._now().isoformat()),
        )


# ---------------------------------------------------------------------- unit of work
class SqlUnitOfWork:
    """Transação explícita: ``with uow: ...; uow.commit()``. Sem commit, tudo é desfeito."""

    def __init__(self, connection: Connection, now: Callable[[], datetime]) -> None:
        self._db = connection
        self._committed = False
        self.company = SqlCompanyRepository(connection, now)
        self.accounts = SqlAccountRepository(connection, now)
        self.categories = SqlCategoryRepository(connection, now)
        self.contacts = SqlContactRepository(connection, now)
        self.transactions = SqlTransactionRepository(connection, now)
        self.receipts = SqlReceiptRepository(connection, now)
        self.settings = SqlSettingsRepository(connection, now)

    def __enter__(self) -> Self:
        if self._db.in_transaction:
            raise RuntimeError("Unit of work aninhada não é permitida.")
        self._committed = False
        self._db.execute("BEGIN IMMEDIATE")
        return self

    def commit(self) -> None:
        self._db.execute("COMMIT")
        self._committed = True

    def __exit__(self, *exc: object) -> None:
        if not self._committed and self._db.in_transaction:
            self._db.execute("ROLLBACK")
