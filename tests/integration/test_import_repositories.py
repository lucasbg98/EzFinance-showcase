"""Repositórios da importação sobre o SQLCipher real (dados fictícios)."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from appfin.application.receipts import ReceiptService
from appfin.domain.entities import (
    Company,
    ImportBatch,
    ImportCounts,
    ImportProfile,
    ImportReplacement,
    Transaction,
)
from appfin.domain.enums import ImportSource, TransactionKind, TransactionStatus
from appfin.domain.errors import ConcurrencyConflictError, NotFoundError
from appfin.domain.money import Money
from appfin.infrastructure.ids import uuid7
from tests.integration.conftest import TODAY, App

IMPORTED_AT = datetime(2026, 11, 3, 12, tzinfo=UTC)


def _key(cell: str) -> str:
    return hashlib.sha256(cell.encode()).hexdigest()


def _save_batch(app: App, *, profile_name: str = "Fluxo de caixa") -> ImportBatch:
    with app.uow() as uow:
        profile = uow.imports.add_profile(ImportProfile(uuid7(), profile_name))
        batch = uow.imports.add(
            ImportBatch(uuid7(), profile.id, ImportSource.XLSX, _key("arquivo"), 2026, IMPORTED_AT)
        )
        uow.commit()
    return batch


def _refs(app: App) -> tuple[str, str]:
    """Conta e categoria lidas antes de abrir a unit of work do teste."""
    account = app.catalog.list_accounts()[0]
    rent = next(c for c in app.catalog.list_categories() if c.name == "Aluguel")
    return account.id, rent.id


def _imported(refs: tuple[str, str], batch_id: str, cell: str, cents: int = 10_000) -> Transaction:
    account_id, category_id = refs
    return Transaction(
        id=uuid7(),
        kind=TransactionKind.EXPENSE,
        description="Aluguel",
        amount=Money(cents),
        accrual_date=date(2026, 1, 31),
        due_date=date(2026, 1, 31),
        account_id=account_id,
        category_id=category_id,
        import_batch_id=batch_id,
        import_row_key=_key(cell),
    )


def _outbox(app: App, entity: str) -> int:
    row = app.db.execute("SELECT count(*) FROM outbox WHERE entity = ?", (entity,)).fetchone()
    return int(row[0])


# ---------------------------------------------------------------------- perfis
def test_profile_round_trip_and_case_insensitive_lookup(app: App) -> None:
    line_map = {"despesas|aluguel": "cat-1", "receitas|pix": "cat-2"}
    with app.uow() as uow:
        saved = uow.imports.add_profile(ImportProfile(uuid7(), "Fluxo de caixa", line_map=line_map))
        uow.commit()

    with app.uow() as uow:
        found = uow.imports.find_profile("FLUXO DE CAIXA")
        assert uow.imports.get_profile(saved.id) == found

    assert found is not None
    assert found.version == 1
    assert dict(found.line_map) == line_map
    assert _outbox(app, "import_profile") == 1


def test_profile_update_uses_optimistic_concurrency(app: App) -> None:
    with app.uow() as uow:
        saved = uow.imports.add_profile(ImportProfile(uuid7(), "Fluxo"))
        updated = uow.imports.update_profile(replace(saved, line_map={"linha": "cat"}))
        uow.commit()

    assert updated.version == 2
    with app.uow() as uow, pytest.raises(ConcurrencyConflictError):
        uow.imports.update_profile(replace(saved, name="Versão antiga"))
    with app.uow() as uow, pytest.raises(NotFoundError):
        uow.imports.update_profile(ImportProfile("inexistente", "Fluxo", version=1))


# ---------------------------------------------------------------------- lotes
def test_batch_round_trip_list_and_undo(app: App) -> None:
    first = _save_batch(app)
    with app.uow() as uow:
        later = uow.imports.add(
            replace(first, id=uuid7(), imported_at=datetime(2026, 11, 4, tzinfo=UTC), version=0)
        )
        counted = uow.imports.update(
            replace(later, counts=ImportCounts(created=5, replaced=1, removed=1, skipped=2, kept=1))
        )
        uow.commit()

    with app.uow() as uow:
        assert [b.id for b in uow.imports.list_recent()] == [later.id, first.id]
        assert uow.imports.get(later.id) == counted
        undone = uow.imports.update(counted.mark_undone(datetime(2026, 11, 5, tzinfo=UTC)))
        uow.commit()

    with app.uow() as uow:
        stored = uow.imports.get(later.id)
    assert stored == undone
    assert stored is not None and stored.is_undone
    with app.uow() as uow, pytest.raises(ConcurrencyConflictError):
        uow.imports.update(counted)


def test_replacements_round_trip_including_removals(app: App) -> None:
    batch = _save_batch(app)
    refs = _refs(app)
    with app.uow() as uow:
        old_a, old_b, new_a = uow.transactions.add_many(
            [
                _imported(refs, batch.id, "a"),
                _imported(refs, batch.id, "b"),
                _imported(refs, batch.id, "c"),
            ]
        )
        replacements = [
            ImportReplacement(batch.id, old_a.id, new_a.id),
            ImportReplacement(batch.id, old_b.id),
        ]
        uow.imports.add_replacements(replacements)
        uow.commit()

    with app.uow() as uow:
        listed = uow.imports.list_replacements(batch.id)
    assert sorted(listed, key=lambda r: r.old_transaction_id) == sorted(
        replacements, key=lambda r: r.old_transaction_id
    )


def test_unit_of_work_without_commit_saves_nothing(app: App) -> None:
    with app.uow() as uow:
        profile = uow.imports.add_profile(ImportProfile(uuid7(), "Fluxo"))
        uow.imports.add(
            ImportBatch(uuid7(), profile.id, ImportSource.CSV, _key("x"), 2026, IMPORTED_AT)
        )

    with app.uow() as uow:
        assert uow.imports.find_profile("Fluxo") is None
        assert uow.imports.list_recent() == []


# ---------------------------------------------------------------------- lançamentos importados
def test_add_many_and_find_by_cell_keys_across_chunks(app: App) -> None:
    batch = _save_batch(app)
    refs = _refs(app)
    cells = [f"despesas|linha {n}|2026-01" for n in range(1_200)]  # mais de 2 lotes do IN (...)
    with app.uow() as uow:
        saved = uow.transactions.add_many([_imported(refs, batch.id, cell) for cell in cells])
        uow.commit()

    with app.uow() as uow:
        found = uow.transactions.find_by_import_row_keys([_key(c) for c in cells] + [_key("nova")])
        in_batch = uow.transactions.list_by_import_batch(batch.id)

    assert len(found) == len(cells) == len(in_batch)
    assert found[_key(cells[700])] == saved[700]
    assert {t.version for t in saved} == {1}
    assert _outbox(app, "transaction") == len(cells)


def test_soft_deleted_cell_is_not_found_and_can_be_restored(app: App) -> None:
    batch = _save_batch(app)
    refs = _refs(app)
    with app.uow() as uow:
        saved = uow.transactions.add(_imported(refs, batch.id, "a"))
        uow.transactions.soft_delete(saved.id)
        replacement = uow.transactions.add(_imported(refs, batch.id, "a", cents=20_000))
        uow.commit()

    with app.uow() as uow:
        assert uow.transactions.find_by_import_row_keys([_key("a")]) == {_key("a"): replacement}
        uow.transactions.soft_delete(replacement.id)  # desfazer: tira o novo, volta o antigo
        uow.transactions.restore(saved.id)
        uow.commit()

    with app.uow() as uow:
        restored = uow.transactions.get(saved.id)
        with pytest.raises(NotFoundError):
            uow.transactions.restore(saved.id)  # já não está excluído
    assert restored is not None
    assert restored.amount == Money(10_000)
    assert restored.version == 3  # incluído, excluído e restaurado


def test_restoring_over_a_live_cell_is_refused(app: App) -> None:
    batch = _save_batch(app)
    refs = _refs(app)
    with app.uow() as uow:
        old = uow.transactions.add(_imported(refs, batch.id, "a"))
        uow.transactions.soft_delete(old.id)
        uow.transactions.add(_imported(refs, batch.id, "a", cents=20_000))
        uow.commit()

    with app.uow() as uow, pytest.raises(Exception, match="UNIQUE"):
        uow.transactions.restore(old.id)


def test_editing_never_changes_import_origin(app: App) -> None:
    batch = _save_batch(app)
    refs = _refs(app)
    with app.uow() as uow:
        saved = uow.transactions.add(_imported(refs, batch.id, "a"))
        uow.commit()

    edited = app.transactions.update(
        replace(saved, description="Aluguel da sala", import_batch_id=None, import_row_key=None)
    )

    stored = app.transactions.get(saved.id)
    assert stored == edited
    assert (stored.import_batch_id, stored.import_row_key) == (batch.id, _key("a"))
    assert stored.description == "Aluguel da sala"
    assert stored.version == 2


def test_transactions_with_receipt(app: App) -> None:
    batch = _save_batch(app)
    refs = _refs(app)
    app.catalog.save_company(Company(name="Clínica Fictícia"))
    with app.uow() as uow:
        paid, pending = uow.transactions.add_many(
            [
                replace(
                    _imported(refs, batch.id, "a"),
                    kind=TransactionKind.INCOME,
                    category_id=None,
                    status=TransactionStatus.PAID,
                    paid_date=date(2026, 1, 31),
                ),
                _imported(refs, batch.id, "b"),
            ]
        )
        uow.commit()
    ReceiptService(app.uow, uuid7, lambda: TODAY).issue(paid.id)

    with app.uow() as uow:
        with_receipt = uow.transactions.find_by_import_row_keys([_key("a"), _key("b")])
        ids = uow.receipts.transactions_with_receipt([t.id for t in with_receipt.values()])

    assert ids == {paid.id}
    assert pending.id not in ids
