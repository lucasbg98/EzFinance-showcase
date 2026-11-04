"""Importação da planilha de ponta a ponta, num banco SQLCipher real (dados fictícios).

Cobre a §11 "Aplicação" do plano: primeira importação, reimportação idêntica, valor/observação
alterados, alterado no app, projeção → realizado, célula zerada, desfazer com restauração, mover
categorias padrão, backup antes, falha no meio e o DRE do app versus a planilha.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from appfin.application.reports import month_range
from appfin.application.spreadsheet_import import (
    ImportPreview,
    ImportRequest,
    ImportResult,
    LineChoice,
    LineSource,
    NewCategory,
    PreviewItem,
    SpreadsheetImportService,
    imported_comment,
    transaction_notes,
)
from appfin.domain.entities import Receipt, Transaction
from appfin.domain.enums import (
    CategoryKind,
    DreGroup,
    ImportSource,
    PaymentMethod,
    ReportBasis,
    TransactionKind,
    TransactionStatus,
)
from appfin.domain.errors import BusinessRuleError, ConcurrencyConflictError
from appfin.domain.income_statement import LineType
from appfin.domain.spreadsheet_import.grid import CellValue, Sheet, SpreadsheetFile
from appfin.domain.spreadsheet_import.monthly_matrix import MonthStatus
from appfin.domain.spreadsheet_import.reconcile import ReconcileAction
from appfin.infrastructure.ids import uuid7
from appfin.infrastructure.importers.safe_reader import read_spreadsheet
from appfin.infrastructure.system import LoggingEventLog
from tests.integration.conftest import App
from tests.spreadsheet_fixtures import CashFlowFixture, cash_flow_fixture, write_csv, write_xlsx

YEAR = 2026
NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)


class Backups:
    def __init__(self) -> None:
        self.calls = 0
        self.fail = False

    def __call__(self) -> None:
        if self.fail:
            raise OSError("pasta de backup indisponível")
        self.calls += 1


@pytest.fixture
def backups() -> Backups:
    return Backups()


@pytest.fixture
def service(app: App, backups: Backups) -> SpreadsheetImportService:
    return SpreadsheetImportService(app.uow, uuid7, lambda: NOW, backups, LoggingEventLog())


def _file(fixture: CashFlowFixture, name: str = "JAN26") -> SpreadsheetFile:
    sheet = fixture.sheet(name)
    digest = hashlib.sha256(repr((sheet.rows, sorted(sheet.comments.items()))).encode()).hexdigest()
    return SpreadsheetFile(ImportSource.XLSX, digest, (sheet,))


def _account(app: App) -> str:
    return app.catalog.list_accounts()[0].id


def _request(app: App, **changes: object) -> ImportRequest:
    return replace(ImportRequest(YEAR, _account(app)), **changes)  # type: ignore[arg-type]  # campos variados


def _import(
    service: SpreadsheetImportService, file: SpreadsheetFile, request: ImportRequest
) -> tuple[ImportPreview, ImportResult]:
    preview = service.preview(file, request)
    return preview, service.confirm(file, request, preview.fingerprint)


def _live(app: App) -> list[Transaction]:
    with app.uow() as uow:
        return [
            t
            for batch in uow.imports.list_recent()
            for t in uow.transactions.list_by_import_batch(batch.id)
        ]


def _cells(fixture: CashFlowFixture) -> int:
    return sum(1 for detail in fixture.details for cents in detail.cents if cents)


def _batch_id(result: ImportResult) -> str:
    assert result.batch is not None
    return result.batch.id


def _item(preview: ImportPreview, label: str, month: int) -> PreviewItem:
    line = next(line for line in preview.lines if line.label == label)
    return next(i for i in preview.items if i.line_key == line.key and i.month == month)


# ---------------------------------------------------------------------- primeira importação
def test_first_import_creates_one_transaction_per_cell(
    app: App, service: SpreadsheetImportService, backups: Backups
) -> None:
    fixture = cash_flow_fixture()

    preview, result = _import(service, _file(fixture), _request(app))

    assert preview.can_confirm, preview.errors
    assert preview.counts.created == _cells(fixture)
    assert result.counts.created == _cells(fixture)
    assert backups.calls == 1
    transactions = _live(app)
    assert len(transactions) == _cells(fixture)
    assert {t.import_batch_id for t in transactions} == {_batch_id(result)}
    assert len({t.import_row_key for t in transactions}) == len(transactions)


def test_transactions_follow_the_plan_rules(app: App, service: SpreadsheetImportService) -> None:
    fixture = cash_flow_fixture()
    _import(service, _file(fixture), _request(app))
    by_key = {(t.description, t.due_date.month): t for t in _live(app)}

    credit = by_key[("CARTÃO CRÉDITO", 2)]
    assert credit.kind is TransactionKind.INCOME
    assert credit.payment_method is PaymentMethod.CREDIT
    assert credit.amount.cents == fixture.detail("revenue", "CARTÃO CRÉDITO").cents[1]
    assert credit.status is TransactionStatus.PAID
    assert credit.due_date == credit.accrual_date == credit.paid_date == date(2026, 2, 28)
    assert credit.notes == "Duas maquininhas no mês.\nImportado da planilha (linha 5)"

    refund = by_key[("DEVOLUÇÃO DE CRÉDITO", 3)]
    assert refund.kind is TransactionKind.EXPENSE and refund.amount.cents == 12_345

    rent = by_key[("ALUGUEL", 10)]  # outubro: projeção
    assert rent.status is TransactionStatus.PENDING and rent.paid_date is None
    assert rent.due_date == date(2026, 10, 31)

    thirteenth = [t for (description, _m), t in by_key.items() if description.startswith("13º")]
    assert {t.description for t in thirteenth} <= {
        "13º SALÁRIO — SALÁRIO AUXILIAR FICTÍCIA 1",
        "13º SALÁRIO — SALÁRIO AUXILIAR FICTÍCIA 2",
    }


def test_new_categories_and_profile_are_created(
    app: App, service: SpreadsheetImportService
) -> None:
    fixture = cash_flow_fixture()
    preview, result = _import(service, _file(fixture), _request(app))

    names = {category.name for category in preview.new_categories}
    assert {
        "Correios e entregas",
        "IR pessoa física",
        "RECEBIDOS SÓCIA FICTÍCIA",
        "SÓCIA FICTÍCIA - GERAL",
    } <= names
    assert result.categories_created == len(preview.new_categories)
    categories = {c.name: c for c in app.catalog.list_categories()}
    assert categories["RECEBIDOS SÓCIA FICTÍCIA"].dre_group is DreGroup.OTHER_RESULTS
    assert categories["RECEBIDOS SÓCIA FICTÍCIA"].kind is CategoryKind.INCOME
    assert categories["SÓCIA FICTÍCIA - GERAL"].dre_group is DreGroup.DIRECT_COSTS
    with app.uow() as uow:
        profile = uow.imports.find_profile("Fluxo de caixa")
    assert profile is not None and len(profile.line_map) == len(preview.lines)


def test_app_income_statement_matches_the_sheet_every_month(
    app: App, service: SpreadsheetImportService
) -> None:
    """Pronto quando: Impostos, Investimentos e Resultado do período = linhas 70, 96 e 104."""
    fixture = cash_flow_fixture()
    preview, _result = _import(service, _file(fixture), _request(app))
    assert preview.dre_checks and all(check.ok for check in preview.dre_checks)

    for month in range(1, 13):
        statement = app.reports.income_statement(*month_range(YEAR, month), ReportBasis.ACCRUAL)
        by_group = {line.group: line.amount.cents for line in statement if line.group}
        result = next(line for line in statement if line.line_type is LineType.RESULT)

        assert by_group[DreGroup.TAXES] == -_sum(fixture, "taxes", month)
        assert by_group[DreGroup.INVESTMENTS] == -_sum(fixture, "investments", month)
        assert result.amount.cents == _final_result(fixture, month)


def _sum(fixture: CashFlowFixture, block: str, month: int) -> int:
    return sum(detail.cents[month - 1] for detail in fixture.block(block))


def _final_result(fixture: CashFlowFixture, month: int) -> int:
    income = (
        _sum(fixture, "revenue", month)
        - 2 * fixture.detail("revenue", "DEVOLUÇÃO DE CRÉDITO").cents[month - 1]
    )
    entries, exits = (d.cents[month - 1] for d in fixture.block("non_operating"))
    expenses = sum(
        _sum(fixture, block, month)
        for block in (
            "dentists",
            "prosthetics",
            "misc",
            "supplies",
            "fixed",
            "salaries",
            "taxes",
            "investments",
        )
    )
    return income - expenses + entries - exits


@pytest.mark.parametrize("kind", ["xlsx", "csv"])
def test_real_files_import_the_same_way(
    app: App, service: SpreadsheetImportService, tmp_path: Path, kind: str
) -> None:
    fixture = cash_flow_fixture()
    path = (write_xlsx if kind == "xlsx" else write_csv)(tmp_path / f"planilha.{kind}", fixture)
    file = read_spreadsheet(path)

    preview, _result = _import(service, file, _request(app))

    assert preview.can_confirm
    assert preview.counts.created == _cells(fixture)
    commented = sum(1 for t in _live(app) if imported_comment(t.notes))
    assert commented == (3 if kind == "xlsx" else 0)  # o CSV não tem comentários


def test_year_is_suggested_by_the_sheet_name(service: SpreadsheetImportService) -> None:
    fixture = cash_flow_fixture()

    assert service.suggest_year(_file(fixture, "JAN26")) == 2026
    assert service.suggest_year(_file(fixture, "Fluxo 2027")) == 2027
    assert service.suggest_year(_file(fixture, "Planilha")) is None
    assert service.suggest_year(_file(fixture, "Planilha"), file_name="FLUXO (JAN26).csv") == 2026
    assert service.suggest_year(_file(fixture, "MAR25"), file_name="fluxo 2026.csv") == 2026


# ---------------------------------------------------------------------- importar de novo
def test_identical_reimport_changes_nothing(
    app: App, service: SpreadsheetImportService, backups: Backups
) -> None:
    fixture = cash_flow_fixture()
    _import(service, _file(fixture), _request(app))

    preview, result = _import(service, _file(fixture), _request(app))

    assert preview.counts.skipped == _cells(fixture)
    assert not preview.has_transaction_changes
    assert result.batch is None
    assert backups.calls == 1  # só o da primeira importação
    assert all(line.source is LineSource.PROFILE for line in preview.lines)


def test_changed_value_or_comment_replaces_the_old_transaction(
    app: App, service: SpreadsheetImportService
) -> None:
    fixture = cash_flow_fixture()
    _import(service, _file(fixture), _request(app))
    old = {(t.description, t.due_date.month): t for t in _live(app)}
    fixture.detail("fixed", "INTERNET").cents[8] += 1_000
    key = next(k for k in fixture.comments if k[0] == "taxes")
    fixture.comments[key] = "Anuidade com desconto (corrigida)."

    preview, result = _import(service, _file(fixture), _request(app))

    assert preview.counts.replaced == 2 and preview.counts.created == 0
    with app.uow() as uow:
        replacements = uow.imports.list_replacements(_batch_id(result))
        assert uow.transactions.get(old[("INTERNET", 9)].id) is None  # excluído (lógico)
    assert {r.old_transaction_id for r in replacements} == {
        old[("INTERNET", 9)].id,
        old[("CRO", 3)].id,
    }
    now = {(t.description, t.due_date.month): t for t in _live(app)}
    assert now[("INTERNET", 9)].amount.cents == old[("INTERNET", 9)].amount.cents + 1_000
    assert now[("CRO", 3)].notes.startswith("Anuidade com desconto (corrigida).")
    assert len(_live(app)) == _cells(fixture)


def test_transaction_changed_in_app_is_kept(app: App, service: SpreadsheetImportService) -> None:
    fixture = cash_flow_fixture()
    _import(service, _file(fixture), _request(app))
    rent = next(t for t in _live(app) if t.description == "ALUGUEL" and t.due_date.month == 9)
    app.transactions.mark_paid([rent.id], date(2026, 9, 30))  # pago no app (versão 2)
    fixture.detail("fixed", "ALUGUEL ").cents[8] += 500

    preview, result = _import(service, _file(fixture), _request(app))

    item = _item(preview, "ALUGUEL", 9)
    assert item.action is ReconcileAction.KEEP
    assert preview.counts.kept == 1 and result.batch is None
    with app.uow() as uow:
        kept = uow.transactions.get(rent.id)
    assert kept is not None and kept.status is TransactionStatus.PAID


def test_transaction_with_receipt_is_kept(app: App, service: SpreadsheetImportService) -> None:
    fixture = cash_flow_fixture()
    _import(service, _file(fixture), _request(app))
    cash = next(t for t in _live(app) if t.description == "DINHEIRO")
    with app.uow() as uow:
        uow.receipts.add(Receipt(uuid7(), 1, cash.id, date(2026, 9, 1)))
        uow.commit()
    fixture.detail("revenue", "DINHEIRO").cents[cash.due_date.month - 1] += 100

    preview = service.preview(_file(fixture), _request(app))

    assert _item(preview, "DINHEIRO", cash.due_date.month).action is ReconcileAction.KEEP


def test_projection_becoming_realized_replaces_with_a_paid_transaction(
    app: App, service: SpreadsheetImportService
) -> None:
    fixture = cash_flow_fixture()
    _import(service, _file(fixture), _request(app))
    fixture.detail("revenue", "DINHEIRO").cents[8] = 70_000  # setembro passa a ter receita

    preview, _result = _import(service, _file(fixture), _request(app))

    assert preview.months[8] is MonthStatus.REALIZED
    rent = _item(preview, "ALUGUEL", 9)
    assert rent.action is ReconcileAction.REPLACE and rent.is_paid
    september = [t for t in _live(app) if t.due_date.month == 9]
    assert september and all(t.status is TransactionStatus.PAID for t in september)


def test_emptied_cell_is_removed_or_kept_when_unchecked(
    app: App, service: SpreadsheetImportService
) -> None:
    fixture = cash_flow_fixture()
    _import(service, _file(fixture), _request(app))
    software = fixture.detail("fixed", "SOFTWARE")
    software.cents[11] = 0

    preview = service.preview(_file(fixture), _request(app))
    [removal] = [i for i in preview.items if i.action is ReconcileAction.REMOVE]
    assert removal.amount_cents is None and removal.current_amount_cents

    keep = service.preview(
        _file(fixture), _request(app, keep_row_keys=frozenset({removal.row_key}))
    )
    assert keep.counts.removed == 0 and keep.counts.kept == 1

    service.confirm(_file(fixture), _request(app), preview.fingerprint)
    assert not [t for t in _live(app) if t.description == "SOFTWARE" and t.due_date.month == 12]


def test_excluded_month_is_neither_imported_nor_removed(
    app: App, service: SpreadsheetImportService
) -> None:
    fixture = cash_flow_fixture()
    request = _request(app, month_statuses={12: MonthStatus.EMPTY})
    preview, _result = _import(service, _file(fixture), request)

    assert not [i for i in preview.items if i.month == 12]
    assert not [t for t in _live(app) if t.due_date.month == 12]
    assert service.preview(_file(fixture), request).counts.removed == 0


# ---------------------------------------------------------------------- linha desconhecida
def _with_unknown_line(fixture: CashFlowFixture) -> SpreadsheetFile:
    """Linha nova (sem regra) no bloco "Diversos" com R$ 25,00 em abril, e os totais ajustados."""
    sheet = _file(fixture).sheets[0]
    rows = [list(row) for row in sheet.rows]
    april = 2 + 3

    def bump(label: str, delta: int) -> None:
        row = next(row for row in rows if row[1] == label)
        row[april] = (row[april] or Decimal(0)) + delta  # type: ignore[operator]

    bump("TOTAL DIVERSOS ", 25)
    bump("CUSTOS VARIÁVEIS ", 25)
    bump("LUCRO TOTAL FINAL ", -25)
    position = next(i for i, row in enumerate(rows) if row[1] == "TOTAL DIVERSOS ")
    new_row: list[CellValue] = [None, "ITEM NOVO DESCONHECIDO", *[None] * 12]
    new_row[april] = Decimal(25)
    rows.insert(position + 1, new_row)
    return replace(_file(fixture), sheets=(Sheet(sheet.name, tuple(tuple(r) for r in rows)),))


def test_unknown_line_blocks_until_a_category_is_chosen(
    app: App, service: SpreadsheetImportService
) -> None:
    file = _with_unknown_line(cash_flow_fixture())

    blocked = service.preview(file, _request(app))
    unknown = next(line for line in blocked.lines if line.label == "ITEM NOVO DESCONHECIDO")
    assert unknown.source is LineSource.MISSING
    assert not blocked.can_confirm
    with pytest.raises(BusinessRuleError):
        service.confirm(file, _request(app), blocked.fingerprint)

    choice = LineChoice(
        new_category=NewCategory(
            "Despesas fictícias", CategoryKind.EXPENSE, DreGroup.OPERATING_EXPENSES
        )
    )
    request = _request(app, choices={unknown.key: choice})
    preview, _result = _import(service, file, request)
    assert preview.can_confirm, preview.errors

    again = service.preview(file, _request(app))
    assert next(line for line in again.lines if line.key == unknown.key).source is (
        LineSource.PROFILE
    )


def test_choosing_an_existing_category_of_the_wrong_kind_is_an_error(
    app: App, service: SpreadsheetImportService
) -> None:
    file = _with_unknown_line(cash_flow_fixture())
    blocked = service.preview(file, _request(app))
    unknown = next(line for line in blocked.lines if line.label == "ITEM NOVO DESCONHECIDO")
    income = next(c for c in app.catalog.list_categories() if c.name == "Tratamentos particulares")

    preview = service.preview(
        file, _request(app, choices={unknown.key: LineChoice(category_id=income.id)})
    )

    assert not preview.can_confirm


# ---------------------------------------------------------------------- desfazer
def test_undo_restores_the_replaced_transactions(
    app: App, service: SpreadsheetImportService
) -> None:
    fixture = cash_flow_fixture()
    _import(service, _file(fixture), _request(app))
    first = {t.id for t in _live(app)}
    fixture.detail("fixed", "INTERNET").cents[8] += 1_000
    _preview, result = _import(service, _file(fixture), _request(app))
    second = _batch_id(result)

    assert service.undo_check(second).ok
    undone = service.undo(second)

    assert undone.is_undone
    assert {t.id for t in _live(app)} == first
    with pytest.raises(BusinessRuleError):
        service.undo(second)


def test_reimport_after_undo_replaces_again(app: App, service: SpreadsheetImportService) -> None:
    """Restaurar não conta como "alterado no app"."""
    fixture = cash_flow_fixture()
    _import(service, _file(fixture), _request(app))
    fixture.detail("fixed", "INTERNET").cents[8] += 1_000
    _preview, result = _import(service, _file(fixture), _request(app))
    service.undo(_batch_id(result))

    preview = service.preview(_file(fixture), _request(app))

    assert _item(preview, "INTERNET", 9).action is ReconcileAction.REPLACE


def test_undo_everything_leaves_no_imported_transaction(
    app: App, service: SpreadsheetImportService
) -> None:
    _preview, result = _import(service, _file(cash_flow_fixture()), _request(app))

    service.undo(_batch_id(result))

    assert _live(app) == []
    assert service.history()[0].is_undone


def test_undo_is_blocked_when_a_transaction_was_changed_in_app(
    app: App, service: SpreadsheetImportService
) -> None:
    _preview, result = _import(service, _file(cash_flow_fixture()), _request(app))
    rent = next(t for t in _live(app) if t.description == "ALUGUEL" and t.due_date.month == 9)
    app.transactions.mark_paid([rent.id], date(2026, 9, 30))

    check = service.undo_check(_batch_id(result))

    assert [t.id for t in check.changed_in_app] == [rent.id]
    with pytest.raises(BusinessRuleError):
        service.undo(_batch_id(result))
    assert len(_live(app)) == _cells(cash_flow_fixture())


def test_undo_is_blocked_when_a_transaction_was_deleted_in_app(
    app: App, service: SpreadsheetImportService
) -> None:
    _preview, result = _import(service, _file(cash_flow_fixture()), _request(app))
    app.transactions.delete([_live(app)[0].id])

    assert service.undo_check(_batch_id(result)).deleted_in_app == 1


def test_older_batch_can_only_be_undone_after_the_newer_one(
    app: App, service: SpreadsheetImportService
) -> None:
    fixture = cash_flow_fixture()
    _preview, first = _import(service, _file(fixture), _request(app))
    fixture.detail("fixed", "INTERNET").cents[8] += 1_000
    _preview, second = _import(service, _file(fixture), _request(app))

    assert service.undo_check(_batch_id(first)).newer_batch
    service.undo(_batch_id(second))
    assert service.undo_check(_batch_id(first)).ok


# ---------------------------------------------------------------------- categorias padrão a mover
def test_default_category_in_an_old_group_can_be_moved(
    app: App, service: SpreadsheetImportService
) -> None:
    categories = {c.name: c for c in app.catalog.list_categories()}
    operating = categories["Despesas operacionais"]
    app.catalog.save_category(
        replace(
            categories["Contador"], dre_group=DreGroup.OPERATING_EXPENSES, parent_id=operating.id
        )
    )  # como num banco anterior à 1.7.1
    file = _file(cash_flow_fixture())

    preview = service.preview(file, _request(app))
    [move] = [m for m in preview.category_moves if m.name == "Contador"]
    assert move.to_group is DreGroup.TAXES
    assert any(not c.ok for c in preview.dre_checks if c.label == "TOTAL DE IMPOSTOS")
    assert preview.can_confirm  # só aviso: o grupo pode ser escolha do contador

    request = _request(app, move_category_ids=frozenset({move.category_id}))
    moved_preview, result = _import(service, file, request)

    assert result.categories_moved == 1
    assert all(c.ok for c in moved_preview.dre_checks)
    contador = next(c for c in app.catalog.list_categories() if c.name == "Contador")
    assert contador.dre_group is DreGroup.TAXES
    assert contador.parent_id == categories["Impostos"].id


# ---------------------------------------------------------------------- segurança e atomicidade
def test_failed_backup_imports_nothing(
    app: App, service: SpreadsheetImportService, backups: Backups
) -> None:
    backups.fail = True
    file = _file(cash_flow_fixture())
    preview = service.preview(file, _request(app))

    with pytest.raises(OSError, match="backup"):
        service.confirm(file, _request(app), preview.fingerprint)

    assert _live(app) == [] and service.history() == []


def test_failure_in_the_middle_writes_nothing(
    app: App, backups: Backups, monkeypatch: pytest.MonkeyPatch
) -> None:
    from appfin.infrastructure.persistence import repositories

    def boom(self: object, transactions: object) -> None:
        raise RuntimeError("falha simulada")

    monkeypatch.setattr(repositories.SqlTransactionRepository, "add_many", boom)
    service = SpreadsheetImportService(app.uow, uuid7, lambda: NOW, backups)
    file = _file(cash_flow_fixture())
    preview = service.preview(file, _request(app))
    categories_before = len(app.catalog.list_categories(include_archived=True))

    with pytest.raises(RuntimeError):
        service.confirm(file, _request(app), preview.fingerprint)

    assert service.history() == []
    assert len(app.catalog.list_categories(include_archived=True)) == categories_before
    with app.uow() as uow:
        assert uow.imports.find_profile("Fluxo de caixa") is None


def test_stale_preview_is_refused(app: App, service: SpreadsheetImportService) -> None:
    fixture = cash_flow_fixture()
    preview = service.preview(_file(fixture), _request(app))
    fixture.detail("fixed", "INTERNET").cents[0] += 1

    with pytest.raises(ConcurrencyConflictError):
        service.confirm(_file(fixture), _request(app), preview.fingerprint)


def test_inactive_account_blocks_the_import(app: App, service: SpreadsheetImportService) -> None:
    preview = service.preview(_file(cash_flow_fixture()), _request(app, account_id="inexistente"))

    assert not preview.can_confirm


def test_confirm_logs_only_counts(
    app: App, service: SpreadsheetImportService, caplog: pytest.LogCaptureFixture
) -> None:
    fixture = cash_flow_fixture()
    secrets = [d.label.strip() for d in fixture.details] + list(fixture.comments.values())

    with caplog.at_level(logging.DEBUG):
        _import(service, _file(fixture), _request(app))

    assert "import.confirm" in caplog.text
    assert not [secret for secret in secrets if secret in caplog.text]
    assert not [
        str(cents)
        for d in fixture.details
        for cents in d.cents
        if cents > 10_000 and str(cents) in caplog.text
    ]


def test_notes_helpers_round_trip() -> None:
    assert imported_comment(transaction_notes("Nota fictícia.", 12)) == "Nota fictícia."
    assert imported_comment(transaction_notes("", 12)) == ""
    assert imported_comment("Editado no app") == "Editado no app"
