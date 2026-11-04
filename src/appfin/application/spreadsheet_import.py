"""Casos de uso da importação da planilha "Fluxo de caixa" (plano de importação §3 a §6, §7.1).

Fluxo: ``preview`` (nada é gravado) → a usuária revisa e decide → ``confirm`` com a impressão
digital (``fingerprint``) da prévia (backup automático, depois tudo numa única transação) →
``undo`` se precisar.

Regras que valem sempre:
- "sem erros" (P12): qualquer problema bloqueante ou total que não confere impede a confirmação;
  nunca há importação parcial;
- reimportar não duplica (cada célula tem uma chave única) e o app **nunca apaga trabalho feito
  nele**: lançamento alterado no app (``version`` acima da de importação ou com recibo) é mantido;
- nada da planilha vai para log: só eventos e contagens.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from enum import StrEnum

from appfin.application.ports import EventLog
from appfin.domain.default_categories import default_categories
from appfin.domain.entities import (
    Category,
    ImportBatch,
    ImportCounts,
    ImportProfile,
    ImportReplacement,
    Transaction,
)
from appfin.domain.enums import (
    CategoryKind,
    DreGroup,
    ImportSource,
    PaymentMethod,
    TaxRegime,
    TransactionKind,
    TransactionStatus,
)
from appfin.domain.errors import (
    BusinessRuleError,
    ConcurrencyConflictError,
    NotFoundError,
    ValidationError,
)
from appfin.domain.money import Money
from appfin.domain.repositories import UnitOfWork
from appfin.domain.spreadsheet_import.cash_flow_layout import CASH_FLOW_LAYOUT
from appfin.domain.spreadsheet_import.cash_flow_profile import (
    FROM_LABEL,
    PROFILE_NAME,
    RuleSource,
    Suggestion,
    line_kind,
    suggest,
)
from appfin.domain.spreadsheet_import.grid import SpreadsheetFile
from appfin.domain.spreadsheet_import.monthly_matrix import (
    MONTH_COUNT,
    Issue,
    IssueLevel,
    MatrixLine,
    MatrixReading,
    MonthStatus,
    TotalCheck,
    read_monthly_matrix,
)
from appfin.domain.spreadsheet_import.parse import cell_key, normalize_label
from appfin.domain.spreadsheet_import.reconcile import (
    CellCandidate,
    ImportedState,
    ReconcileAction,
    ReconcileDecision,
    reconcile,
)
from appfin.domain.validation import clean_text

MAX_DESCRIPTION = 200
MAX_CATEGORY_NAME = 60
MAX_HISTORY = 1000
PENDING_PROFILE_ID = "perfil-ainda-nao-salvo"  # 1ª importação: ainda não há células importadas
_IMPORT_MARK = "Importado da planilha (linha {row})"
_IMPORT_MARK_LINE = re.compile(r"(?:\n|\A)Importado da planilha \(linha \d+\)\Z")
_YEAR_4 = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
_YEAR_2 = re.compile(r"(?<!\d)(\d{2})(?!\d)")
_TAX_TOTAL = "TOTAL DE IMPOSTOS"
_INVESTMENT_TOTAL = "INVESTIMENTOS"
_FINAL_RESULT = "LUCRO TOTAL FINAL"
_DRE_LINES = (
    _TAX_TOTAL,
    _INVESTMENT_TOTAL,
    _FINAL_RESULT,
)  # "(-) Impostos", "(-) Invest.", resultado
_CHANGES = (ReconcileAction.CREATE, ReconcileAction.REPLACE, ReconcileAction.REMOVE)
_ADJUSTABLE = (ReconcileAction.REPLACE, ReconcileAction.REMOVE)


# ---------------------------------------------------------------------- pedido da usuária
@dataclass(frozen=True, slots=True)
class NewCategory:
    """Categoria a criar na confirmação (nome sugerido pelo perfil ou digitado na prévia)."""

    name: str
    kind: CategoryKind
    dre_group: DreGroup

    def __post_init__(self) -> None:
        name = clean_text(self.name, "name", max_length=MAX_CATEGORY_NAME, required=True)
        object.__setattr__(self, "name", name)

    @property
    def identity(self) -> tuple[str, CategoryKind, DreGroup]:
        return normalize_label(self.name), self.kind, self.dre_group


@dataclass(frozen=True, slots=True)
class LineChoice:
    """Categoria escolhida para uma linha: uma existente **ou** uma nova."""

    category_id: str | None = None
    new_category: NewCategory | None = None

    def __post_init__(self) -> None:
        if (self.category_id is None) == (self.new_category is None):
            raise ValidationError("category_id", "Escolha uma categoria ou crie uma nova.")


@dataclass(frozen=True, slots=True)
class ImportRequest:
    """O que a usuária escolheu no assistente. As chaves de linha vêm da prévia."""

    year: int
    account_id: str
    sheet_index: int = 0
    month_statuses: Mapping[int, MonthStatus] = field(default_factory=dict)  # EMPTY = mês fora
    choices: Mapping[str, LineChoice] = field(default_factory=dict)
    descriptions: Mapping[str, str] = field(default_factory=dict)
    move_category_ids: frozenset[str] = frozenset()
    keep_row_keys: frozenset[str] = frozenset()  # substituições/remoções desmarcadas na prévia


# ---------------------------------------------------------------------- prévia
class LineSource(StrEnum):
    PROFILE = "profile"  # escolha salva numa importação anterior
    CHOICE = "choice"  # escolhida agora, na prévia
    RULE = "rule"  # regra do perfil padrão
    BLOCK = "block"  # sugerida pelo bloco da planilha (aviso: confira)
    MISSING = "missing"  # sem categoria: a usuária precisa escolher


@dataclass(frozen=True, slots=True)
class PreviewLine:
    key: str
    row: int
    label: str
    block: str
    kind: TransactionKind
    description: str
    source: LineSource
    category_id: str | None = None
    new_category: NewCategory | None = None
    payment_method: PaymentMethod | None = None
    is_empty: bool = False

    @property
    def is_resolved(self) -> bool:
        return self.category_id is not None or self.new_category is not None


@dataclass(frozen=True, slots=True)
class PreviewItem:
    """Uma célula: o lançamento que entra, sai ou fica (com o estado atual, se já importada)."""

    row_key: str
    line_key: str
    row: int
    month: int
    description: str
    action: ReconcileAction
    amount_cents: int | None  # None = célula zerada (remoção)
    is_paid: bool
    notes: str
    selected: bool = True  # False: substituição/remoção desmarcada (vira "manter")
    current_transaction_id: str | None = None
    current_amount_cents: int | None = None
    current_is_paid: bool | None = None
    current_notes: str | None = None

    @property
    def effective_action(self) -> ReconcileAction:
        return self.action if self.selected else ReconcileAction.KEEP


@dataclass(frozen=True, slots=True)
class CategoryMove:
    """Categoria padrão que está noutro grupo do DRE (banco anterior à 1.7.1): oferecer mover."""

    category_id: str
    name: str
    from_group: DreGroup | None
    to_group: DreGroup
    to_parent_id: str | None


@dataclass(frozen=True, slots=True)
class DreCheck:
    """DRE do app (com o mapeamento escolhido) versus a linha da planilha, num mês."""

    label: str
    month: int
    sheet_cents: int | None
    app_cents: int
    blocking: bool

    @property
    def ok(self) -> bool:
        return self.sheet_cents == self.app_cents


@dataclass(frozen=True, slots=True)
class ImportPreview:
    source: ImportSource
    file_sha256: str
    has_macros: bool
    sheet_names: tuple[str, ...]
    sheet_index: int
    year: int
    detected_months: tuple[MonthStatus, ...]
    months: tuple[MonthStatus, ...]
    lines: tuple[PreviewLine, ...]
    items: tuple[PreviewItem, ...]
    checks: tuple[TotalCheck, ...]
    dre_checks: tuple[DreCheck, ...]
    issues: tuple[Issue, ...]
    new_categories: tuple[NewCategory, ...]
    category_moves: tuple[CategoryMove, ...]
    move_category_ids: frozenset[str]
    fingerprint: str

    @property
    def errors(self) -> tuple[Issue, ...]:
        return tuple(issue for issue in self.issues if issue.level is IssueLevel.ERROR)

    @property
    def counts(self) -> ImportCounts:
        actions = Counter(item.effective_action for item in self.items)
        return ImportCounts(
            created=actions[ReconcileAction.CREATE],
            replaced=actions[ReconcileAction.REPLACE],
            removed=actions[ReconcileAction.REMOVE],
            skipped=actions[ReconcileAction.SKIP],
            kept=actions[ReconcileAction.KEEP],
        )

    @property
    def can_confirm(self) -> bool:
        return (
            bool(self.lines)
            and not self.errors
            and all(check.ok for check in self.checks)
            and all(check.ok for check in self.dre_checks if check.blocking)
        )

    @property
    def has_transaction_changes(self) -> bool:
        return any(item.effective_action in _CHANGES for item in self.items)


@dataclass(frozen=True, slots=True)
class ImportResult:
    batch: ImportBatch | None  # None: nada mudou nos lançamentos (nenhum lote registrado)
    counts: ImportCounts
    categories_created: int = 0
    categories_moved: int = 0


@dataclass(frozen=True, slots=True)
class UndoCheck:
    """Por que um lote não pode ser desfeito (a tela lista os lançamentos)."""

    changed_in_app: tuple[Transaction, ...] = ()
    deleted_in_app: int = 0
    newer_batch: bool = False
    already_undone: bool = False

    @property
    def ok(self) -> bool:
        return not (
            self.changed_in_app or self.deleted_in_app or self.newer_batch or self.already_undone
        )


# ---------------------------------------------------------------------- serviço
class SpreadsheetImportService:
    def __init__(
        self,
        uow: Callable[[], UnitOfWork],
        new_id: Callable[[], str],
        now: Callable[[], datetime],
        backup: Callable[[], object],
        events: EventLog | None = None,
        audit: Callable[[str, str], None] | None = None,
    ) -> None:
        self._uow = uow
        self._new_id = new_id
        self._now = now
        self._backup = backup
        self._events = events
        self._audit = audit

    # ------------------------------------------------------------------ consultas
    @staticmethod
    def suggest_year(
        file: SpreadsheetFile, sheet_index: int = 0, file_name: str = ""
    ) -> int | None:
        """Ano sugerido pelo nome da aba (ex.: ``JAN26`` → 2026) ou, se não der, do arquivo.

        ``file_name`` só serve para esta sugestão: nunca é guardado nem vai para log.
        """
        names = [file.sheets[sheet_index].name] if 0 <= sheet_index < len(file.sheets) else []
        names.append(file_name)
        for pattern in (_YEAR_4, _YEAR_2):
            for name in names:
                if found := pattern.search(name):
                    year = int(found.group(1))
                    return year if year >= 2000 else 2000 + year
        return None

    def preview(self, file: SpreadsheetFile, request: ImportRequest) -> ImportPreview:
        with self._uow() as uow:
            return _Planner(uow, file, request).preview()

    def history(self, *, limit: int = 100) -> list[ImportBatch]:
        with self._uow() as uow:
            return uow.imports.list_recent(limit=limit)

    # ------------------------------------------------------------------ confirmar
    def confirm(
        self, file: SpreadsheetFile, request: ImportRequest, fingerprint: str
    ) -> ImportResult:
        """Grava o que a prévia mostrou. ``fingerprint`` garante que nada mudou desde a prévia."""
        preview = self.preview(file, request)
        _require_same(preview, fingerprint)
        if not preview.can_confirm:
            raise BusinessRuleError("A prévia tem erros: corrija a planilha ou o mapeamento.")
        if not (
            preview.has_transaction_changes or preview.new_categories or preview.move_category_ids
        ):
            return ImportResult(None, preview.counts)
        self._backup()  # backup automático antes de gravar (falhou = nada é importado)
        profile_id = self._new_id()
        with self._uow() as uow:
            planner = _Planner(uow, file, request, new_profile_id=profile_id)
            preview = planner.preview()
            _require_same(preview, fingerprint)
            result = _Writer(uow, self._new_id, self._now(), planner, preview).write()
            uow.commit()
        self._record("import.confirm", result.counts)
        return result

    # ------------------------------------------------------------------ desfazer
    def undo_check(self, batch_id: str) -> UndoCheck:
        with self._uow() as uow:
            return _undo_check(uow, _required_batch(uow, batch_id))

    def undo(self, batch_id: str) -> ImportBatch:
        """Exclui os lançamentos do lote e restaura os que ele substituiu, numa transação."""
        with self._uow() as uow:
            batch = _required_batch(uow, batch_id)
            check = _undo_check(uow, batch)
            if not check.ok:
                raise BusinessRuleError(_undo_message(check))
            for transaction in uow.transactions.list_by_import_batch(batch.id):
                uow.transactions.soft_delete(transaction.id)
            for replacement in uow.imports.list_replacements(batch.id):
                uow.transactions.restore(replacement.old_transaction_id)
            saved = uow.imports.update(batch.mark_undone(self._now()))
            uow.commit()
        self._record("import.undo", batch.counts)
        return saved

    # ------------------------------------------------------------------ interno
    def _record(self, event: str, counts: ImportCounts) -> None:
        if self._audit is not None:
            self._audit(event, "ok")
        if self._events is not None:
            self._events.record(
                event,
                outcome="ok",
                created=counts.created,
                replaced=counts.replaced,
                removed=counts.removed,
                skipped=counts.skipped,
                kept=counts.kept,
            )


def _require_same(preview: ImportPreview, fingerprint: str) -> None:
    if preview.fingerprint != fingerprint:
        raise ConcurrencyConflictError("Os dados mudaram desde a prévia. Gere a prévia de novo.")


def _required_batch(uow: UnitOfWork, batch_id: str) -> ImportBatch:
    batch = uow.imports.get(batch_id)
    if batch is None:
        raise NotFoundError("Importação não encontrada.")
    return batch


# ---------------------------------------------------------------------- cálculo da prévia
class _Planner:
    """Calcula a prévia dentro de uma unit of work (sem gravar). A confirmação recalcula."""

    def __init__(
        self,
        uow: UnitOfWork,
        file: SpreadsheetFile,
        request: ImportRequest,
        new_profile_id: str = PENDING_PROFILE_ID,
    ) -> None:
        _validate_request(file, request)
        self.uow = uow
        self.file = file
        self.request = request
        self.reading: MatrixReading = read_monthly_matrix(
            file.sheets[request.sheet_index], CASH_FLOW_LAYOUT
        )
        self.profile = uow.imports.find_profile(PROFILE_NAME)
        self.profile_id = self.profile.id if self.profile else new_profile_id
        self.categories = uow.categories.list(include_archived=True)
        self.by_id = {category.id: category for category in self.categories}
        self.issues: list[Issue] = list(self.reading.issues)
        self.lines: list[PreviewLine] = []

    # ------------------------------------------------------------------ montagem
    def preview(self) -> ImportPreview:
        self._check_file_and_account()
        months = self._months()
        moves = self._category_moves()
        selected_moves = frozenset(
            move.category_id for move in moves if move.category_id in self.request.move_category_ids
        )
        self.lines = [self._line(line) for line in self.reading.lines]
        items = self._items(months)
        new_categories = tuple(
            {
                line.new_category.identity: line.new_category
                for line in self.lines
                if line.new_category is not None and not line.is_empty
            }.values()
        )
        dre_checks = self._dre_checks(items, months, moves, selected_moves)
        preview = ImportPreview(
            source=self.file.source,
            file_sha256=self.file.sha256,
            has_macros=self.file.has_macros,
            sheet_names=tuple(sheet.name for sheet in self.file.sheets),
            sheet_index=self.request.sheet_index,
            year=self.request.year,
            detected_months=self.reading.months,
            months=months,
            lines=tuple(self.lines),
            items=tuple(items),
            checks=self.reading.checks,
            dre_checks=tuple(dre_checks),
            issues=tuple(self.issues),
            new_categories=new_categories,
            category_moves=moves,
            move_category_ids=selected_moves,
            fingerprint="",
        )
        return replace(preview, fingerprint=_fingerprint(preview))

    def _check_file_and_account(self) -> None:
        if self.file.has_macros:
            self.issues.append(
                Issue(IssueLevel.WARNING, "Arquivo com macros: só os valores foram lidos.")
            )
        account = self.uow.accounts.get(self.request.account_id)
        if account is None or account.archived:
            self.issues.append(Issue(IssueLevel.ERROR, "Escolha uma conta ativa de destino."))

    def _months(self) -> tuple[MonthStatus, ...]:
        detected = self.reading.months or (MonthStatus.EMPTY,) * MONTH_COUNT
        return tuple(
            self.request.month_statuses.get(month, status)
            for month, status in enumerate(detected, start=1)
        )

    # ------------------------------------------------------------------ linhas → categorias
    def _line(self, line: MatrixLine) -> PreviewLine:
        kind = line_kind(line)
        suggestion = suggest(line)
        method = suggestion.target.payment_method if suggestion else None
        base = PreviewLine(
            key=line.key,
            row=line.row,
            label=line.label,
            block=line.block,
            kind=kind,
            description=self._description(line),
            source=LineSource.MISSING,
            payment_method=method,
            is_empty=line.is_empty,
        )
        resolved = (
            self._chosen(base) or self._saved(base) or self._suggested(base, line, suggestion)
        )
        if resolved is None:
            if not line.is_empty:
                self.issues.append(
                    Issue(IssueLevel.ERROR, "Escolha a categoria desta linha.", line.row)
                )
            return base
        return resolved

    def _chosen(self, line: PreviewLine) -> PreviewLine | None:
        choice = self.request.choices.get(line.key)
        if choice is None:
            return None
        if choice.new_category is not None:
            if not _new_accepts(choice.new_category, line.kind):
                self.issues.append(
                    Issue(IssueLevel.ERROR, "A categoria nova não aceita este tipo.", line.row)
                )
                return replace(line, source=LineSource.CHOICE)
            return replace(line, source=LineSource.CHOICE, new_category=choice.new_category)
        if not self._usable(choice.category_id, line.kind):
            self.issues.append(
                Issue(IssueLevel.ERROR, "Categoria escolhida inválida para esta linha.", line.row)
            )
            return replace(line, source=LineSource.CHOICE)
        return replace(line, source=LineSource.CHOICE, category_id=choice.category_id)

    def _saved(self, line: PreviewLine) -> PreviewLine | None:
        if self.profile is None:
            return None
        category_id = self.profile.line_map.get(line.key)
        if category_id is None or not self._usable(category_id, line.kind):
            return None  # categoria arquivada/excluída: volta para a sugestão
        return replace(line, source=LineSource.PROFILE, category_id=category_id)

    def _suggested(
        self, line: PreviewLine, matrix_line: MatrixLine, suggestion: Suggestion | None
    ) -> PreviewLine | None:
        if suggestion is None:
            return None
        target = suggestion.target
        name = target.name if target.name != FROM_LABEL else matrix_line.label
        source = LineSource.RULE if suggestion.source is RuleSource.RULE else LineSource.BLOCK
        existing = self._find_category(name, line.kind, target.dre_group)
        if existing is not None:
            return replace(line, source=source, category_id=existing.id)
        new = NewCategory(name[:MAX_CATEGORY_NAME], _category_kind(line.kind), target.dre_group)
        return replace(line, source=source, new_category=new)

    def _usable(self, category_id: str | None, kind: TransactionKind) -> bool:
        category = self.by_id.get(category_id or "")
        return category is not None and not category.archived and category.accepts(kind)

    def _find_category(self, name: str, kind: TransactionKind, group: DreGroup) -> Category | None:
        wanted = normalize_label(name)
        matches = [
            c
            for c in self.categories
            if not c.archived and c.accepts(kind) and normalize_label(c.name) == wanted
        ]
        matches.sort(key=lambda c: (self.dre_group_of(c) != group, c.is_group))
        return matches[0] if matches else None

    def dre_group_of(self, category: Category) -> DreGroup | None:
        if category.dre_group is not None or category.parent_id is None:
            return category.dre_group
        parent = self.by_id.get(category.parent_id)
        return parent.dre_group if parent else None

    def _description(self, line: MatrixLine) -> str:
        override = self.request.descriptions.get(line.key)
        if override is not None:
            try:
                return clean_text(
                    override, "description", max_length=MAX_DESCRIPTION, required=True
                )
            except ValidationError as exc:
                self.issues.append(Issue(IssueLevel.ERROR, exc.message, line.row))
                return line.label[:MAX_DESCRIPTION] or "Lançamento importado"
        text = f"{line.label} — {line.owner_label}" if line.owner_label else line.label
        return text[:MAX_DESCRIPTION].strip() or "Lançamento importado"

    # ------------------------------------------------------------------ células → ações
    def _items(self, months: Sequence[MonthStatus]) -> list[PreviewItem]:
        included = {
            month for month, status in enumerate(months, start=1) if status is not MonthStatus.EMPTY
        }
        by_key = {line.key: line for line in self.lines}
        candidates: list[CellCandidate] = []
        where: dict[str, tuple[MatrixLine, int]] = {}
        for line in self.reading.lines:
            for month in sorted(included):
                cents = line.amounts[month - 1]
                if not cents:
                    continue
                row_key = cell_key(self.profile_id, self.request.year, month, line.key)
                is_paid = months[month - 1] is MonthStatus.REALIZED
                candidates.append(CellCandidate(row_key, cents, is_paid, line.comments[month - 1]))
                where[row_key] = (line, month)
        imported = self._imported()
        empty_keys = [
            key
            for key, transaction in imported.items()
            if transaction.due_date.month in included and key not in where
        ]
        states = self._states(imported)
        decisions = reconcile(candidates, states, empty_keys)
        return [self._item(decision, where, by_key, imported) for decision in decisions]

    def _item(
        self,
        decision: ReconcileDecision,
        where: Mapping[str, tuple[MatrixLine, int]],
        by_key: Mapping[str, PreviewLine],
        imported: Mapping[str, Transaction],
    ) -> PreviewItem:
        current = decision.current
        old = imported.get(decision.row_key)
        if decision.row_key in where:
            matrix_line, month = where[decision.row_key]
            line_key, row, description = (
                matrix_line.key,
                matrix_line.row,
                by_key[matrix_line.key].description,
            )
        elif old is not None:  # importada antes e agora vazia: os dados vêm do lançamento atual
            line_key, row, description, month = "", 0, old.description, old.due_date.month
        else:  # pragma: no cover - ``reconcile`` só devolve células da planilha ou já importadas
            raise RuntimeError("Célula sem origem na reconciliação.")
        candidate = decision.candidate
        return PreviewItem(
            row_key=decision.row_key,
            line_key=line_key,
            row=row,
            month=month,
            description=description,
            action=decision.action,
            amount_cents=candidate.amount_cents if candidate else None,
            is_paid=candidate.is_paid if candidate else False,
            notes=candidate.notes if candidate else "",
            selected=not (
                decision.action in _ADJUSTABLE and decision.row_key in self.request.keep_row_keys
            ),
            current_transaction_id=current.transaction_id if current else None,
            current_amount_cents=current.amount_cents if current else None,
            current_is_paid=current.is_paid if current else None,
            current_notes=current.notes if current else None,
        )

    def _imported(self) -> dict[str, Transaction]:
        """Lançamentos vivos das importações (não desfeitas) deste perfil e ano, por célula."""
        found: dict[str, Transaction] = {}
        for batch in self._batches(undone=False):
            for transaction in self.uow.transactions.list_by_import_batch(batch.id):
                if transaction.import_row_key:
                    found[transaction.import_row_key] = transaction
        return found

    def _batches(self, *, undone: bool) -> list[ImportBatch]:
        if self.profile is None:
            return []
        return [
            batch
            for batch in self.uow.imports.list_recent(limit=MAX_HISTORY)
            if batch.profile_id == self.profile.id
            and batch.period_year == self.request.year
            and batch.is_undone == undone
        ]

    def _states(self, imported: Mapping[str, Transaction]) -> dict[str, ImportedState]:
        transactions = list(imported.values())
        with_receipt = self.uow.receipts.transactions_with_receipt([t.id for t in transactions])
        restored = _restore_counts(self.uow, self._batches(undone=True))
        return {
            key: ImportedState(
                transaction_id=t.id,
                amount_cents=t.amount.cents,
                is_paid=t.status is TransactionStatus.PAID,
                notes=imported_comment(t.notes),
                changed_in_app=t.id in with_receipt
                or t.version > untouched_version(restored[t.id]),
            )
            for key, t in imported.items()
        }

    # ------------------------------------------------------------------ categorias padrão a mover
    def _category_moves(self) -> tuple[CategoryMove, ...]:
        company = self.uow.company.get()
        regime = company.tax_regime if company else TaxRegime.SIMPLES
        moves: list[CategoryMove] = []
        for group_name, _kind, dre_group, children in default_categories(regime):
            parent = self.group_for(dre_group, group_name)
            wanted = {normalize_label(name) for name in children}
            for category in self.categories:
                if category.archived or category.is_group:
                    continue
                if normalize_label(category.name) not in wanted:
                    continue
                current = self.dre_group_of(category)
                if current is dre_group:
                    continue
                moves.append(
                    CategoryMove(
                        category.id,
                        category.name,
                        current,
                        dre_group,
                        parent.id if parent else category.parent_id,
                    )
                )
        return tuple(moves)

    def group_for(self, dre_group: DreGroup, preferred_name: str = "") -> Category | None:
        """Grupo de categorias (ativo) do grupo do DRE; prefere o de nome ``preferred_name``."""
        groups = [
            c
            for c in self.categories
            if c.is_group and not c.archived and self.dre_group_of(c) is dre_group
        ]
        groups.sort(key=lambda c: normalize_label(c.name) != normalize_label(preferred_name))
        return groups[0] if groups else None

    # ------------------------------------------------------------------ DRE do app versus planilha
    def _dre_checks(
        self,
        items: Sequence[PreviewItem],
        months: Sequence[MonthStatus],
        moves: Sequence[CategoryMove],
        selected_moves: frozenset[str],
    ) -> list[DreCheck]:
        moved = {
            move.category_id: move.to_group for move in moves if move.category_id in selected_moves
        }
        lines = {line.key: line for line in self.lines}
        totals: dict[tuple[str, int], int] = defaultdict(int)
        for item in items:
            line = lines.get(item.line_key)
            if line is None or item.amount_cents is None:
                continue
            signed = (
                item.amount_cents if line.kind is TransactionKind.INCOME else -item.amount_cents
            )
            totals[(_FINAL_RESULT, item.month)] += signed
            group = self._line_group(line, moved)
            if group is DreGroup.TAXES:
                totals[(_TAX_TOTAL, item.month)] += item.amount_cents
            elif group is DreGroup.INVESTMENTS:
                totals[(_INVESTMENT_TOTAL, item.month)] += item.amount_cents
        sheet = self._sheet_totals()
        checks: list[DreCheck] = []
        for month, status in enumerate(months, start=1):
            if status is MonthStatus.EMPTY:
                continue
            for label in _DRE_LINES:
                if (label, month) not in sheet:
                    continue
                checks.append(
                    DreCheck(
                        label,
                        month,
                        sheet[(label, month)],
                        totals[(label, month)],
                        blocking=label == _FINAL_RESULT,
                    )
                )
        if any(not check.ok and not check.blocking for check in checks):
            self.issues.append(
                Issue(
                    IssueLevel.WARNING,
                    "Com as categorias escolhidas, Impostos ou Investimentos do DRE "
                    "não batem com a planilha.",
                )
            )
        return checks

    def _line_group(self, line: PreviewLine, moved: Mapping[str, DreGroup]) -> DreGroup | None:
        if line.new_category is not None:
            return line.new_category.dre_group
        category = self.by_id.get(line.category_id or "")
        if category is None:
            return None
        return moved.get(category.id) or self.dre_group_of(category)

    def _sheet_totals(self) -> dict[tuple[str, int], int | None]:
        """Valores da planilha nas linhas comparadas (vêm da conferência dos totais)."""
        return {
            (check.label, check.month): check.sheet_cents
            for check in self.reading.checks
            if check.label in _DRE_LINES
        }


def _validate_request(file: SpreadsheetFile, request: ImportRequest) -> None:
    if not 0 <= request.sheet_index < len(file.sheets):
        raise ValidationError("sheet_index", "Escolha uma aba da planilha.")
    if not 2000 <= request.year <= 2100:
        raise ValidationError("year", "Informe o ano da planilha (2000 a 2100).")
    if any(not 1 <= month <= MONTH_COUNT for month in request.month_statuses):
        raise ValidationError("month_statuses", "Mês inválido.")


def _new_accepts(category: NewCategory, kind: TransactionKind) -> bool:
    return category.kind is CategoryKind.BOTH or category.kind is _category_kind(kind)


def _category_kind(kind: TransactionKind) -> CategoryKind:
    return CategoryKind.INCOME if kind is TransactionKind.INCOME else CategoryKind.EXPENSE


def _fingerprint(preview: ImportPreview) -> str:
    """Impressão digital do que a confirmação vai gravar (sem as chaves das células)."""
    material = {
        "file": preview.file_sha256,
        "sheet": preview.sheet_index,
        "year": preview.year,
        "months": [m.value for m in preview.months],
        "lines": [
            [
                line.key,
                line.category_id,
                line.new_category and list(map(str, line.new_category.identity)),
                line.description,
                line.payment_method,
            ]
            for line in preview.lines
        ],
        "items": [
            [
                item.line_key,
                item.month,
                item.effective_action.value,
                item.amount_cents,
                item.is_paid,
                item.notes,
                item.current_transaction_id,
            ]
            for item in preview.items
        ],
        "moves": sorted(preview.move_category_ids),
    }
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------- "alterado no app"
def untouched_version(times_restored: int) -> int:
    """Versão de um lançamento importado que o app não alterou.

    Nasce com 1; cada substituição desfeita (exclusão lógica + restauração) soma 2 sem que a
    usuária tenha mexido nele.
    """
    return 1 + 2 * times_restored


def _restore_counts(uow: UnitOfWork, undone_batches: Iterable[ImportBatch]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for batch in undone_batches:
        for replacement in uow.imports.list_replacements(batch.id):
            counts[replacement.old_transaction_id] += 1
    return counts


def transaction_notes(comment: str, row: int) -> str:
    mark = _IMPORT_MARK.format(row=row)
    return f"{comment}\n{mark}" if comment else mark


def imported_comment(notes: str) -> str:
    """Só o comentário da planilha: a marca "Importado da planilha (linha N)" não é comparada
    (ela muda quando uma linha é inserida na planilha)."""
    return _IMPORT_MARK_LINE.sub("", notes)


# ---------------------------------------------------------------------- gravação
class _Writer:
    def __init__(
        self,
        uow: UnitOfWork,
        new_id: Callable[[], str],
        now: datetime,
        planner: _Planner,
        preview: ImportPreview,
    ) -> None:
        self.uow = uow
        self.new_id = new_id
        self.now = now
        self.planner = planner
        self.preview = preview

    def write(self) -> ImportResult:
        moved = self._move_categories()
        created_ids = self._create_categories()
        profile = self._save_profile(created_ids)
        counts = self.preview.counts
        if not self.preview.has_transaction_changes:
            return ImportResult(None, counts, len(created_ids), moved)
        batch = self.uow.imports.add(
            ImportBatch(
                id=self.new_id(),
                profile_id=profile.id,
                source=self.preview.source,
                file_sha256=self.preview.file_sha256,
                period_year=self.preview.year,
                imported_at=self.now,
                counts=counts,
            )
        )
        self._write_transactions(batch, profile.line_map)
        return ImportResult(batch, counts, len(created_ids), moved)

    def _move_categories(self) -> int:
        moves = [
            m
            for m in self.preview.category_moves
            if m.category_id in self.preview.move_category_ids
        ]
        for move in moves:
            category = self.planner.by_id[move.category_id]
            self.uow.categories.update(
                replace(category, dre_group=move.to_group, parent_id=move.to_parent_id)
            )
        return len(moves)

    def _create_categories(self) -> dict[tuple[str, CategoryKind, DreGroup], str]:
        created: dict[tuple[str, CategoryKind, DreGroup], str] = {}
        for new in self.preview.new_categories:
            parent = self.planner.group_for(new.dre_group)
            if parent is not None and not _parent_accepts(parent, new.kind):
                parent = None
            category = self.uow.categories.add(
                Category(
                    self.new_id(),
                    new.name,
                    new.kind,
                    parent_id=parent.id if parent else None,
                    dre_group=new.dre_group,
                )
            )
            created[new.identity] = category.id
        return created

    def _save_profile(
        self, created: Mapping[tuple[str, CategoryKind, DreGroup], str]
    ) -> ImportProfile:
        line_map = dict(self.planner.profile.line_map) if self.planner.profile else {}
        for line in self.preview.lines:
            category_id = line.category_id
            if line.new_category is not None:
                category_id = created.get(line.new_category.identity)
            if category_id is not None:
                line_map[line.key] = category_id
        current = self.planner.profile
        if current is None:
            return self.uow.imports.add_profile(
                ImportProfile(self.planner.profile_id, PROFILE_NAME, line_map=line_map)
            )
        if dict(current.line_map) == line_map:
            return current
        return self.uow.imports.update_profile(replace(current, line_map=line_map))

    def _write_transactions(self, batch: ImportBatch, line_map: Mapping[str, str]) -> None:
        lines = {line.key: line for line in self.preview.lines}
        new_transactions: list[Transaction] = []
        replacements: list[ImportReplacement] = []
        for item in self.preview.items:
            action = item.effective_action
            if action not in _CHANGES:
                continue
            if action in _ADJUSTABLE and item.current_transaction_id:
                self.uow.transactions.soft_delete(item.current_transaction_id)
            new_id: str | None = None
            if action is not ReconcileAction.REMOVE:
                line = lines[item.line_key]
                transaction = self._transaction(batch, item, line, line_map[line.key])
                new_transactions.append(transaction)
                new_id = transaction.id
            if action in _ADJUSTABLE and item.current_transaction_id:
                replacements.append(
                    ImportReplacement(batch.id, item.current_transaction_id, new_id)
                )
        self.uow.transactions.add_many(new_transactions)
        self.uow.imports.add_replacements(replacements)

    def _transaction(
        self, batch: ImportBatch, item: PreviewItem, line: PreviewLine, category_id: str
    ) -> Transaction:
        last_day = date(self.preview.year, item.month, 1).replace(
            day=calendar.monthrange(self.preview.year, item.month)[1]
        )
        return Transaction(
            id=self.new_id(),
            kind=line.kind,
            description=line.description,
            amount=Money(item.amount_cents or 0),
            accrual_date=last_day,
            due_date=last_day,
            account_id=self.planner.request.account_id,
            status=TransactionStatus.PAID if item.is_paid else TransactionStatus.PENDING,
            paid_date=last_day if item.is_paid else None,
            category_id=category_id,
            payment_method=line.payment_method,
            notes=transaction_notes(item.notes, item.row),
            import_batch_id=batch.id,
            import_row_key=item.row_key,
        )


def _parent_accepts(parent: Category, kind: CategoryKind) -> bool:
    return parent.kind is CategoryKind.BOTH or parent.kind is kind


# ---------------------------------------------------------------------- desfazer
def _undo_check(uow: UnitOfWork, batch: ImportBatch) -> UndoCheck:
    if batch.is_undone:
        return UndoCheck(already_undone=True)
    siblings = [
        other
        for other in uow.imports.list_recent(limit=MAX_HISTORY)
        if other.id != batch.id
        and other.profile_id == batch.profile_id
        and other.period_year == batch.period_year
    ]
    newer = any(
        not other.is_undone and (other.imported_at, other.id) > (batch.imported_at, batch.id)
        for other in siblings
    )
    transactions = uow.transactions.list_by_import_batch(batch.id)
    with_receipt = uow.receipts.transactions_with_receipt([t.id for t in transactions])
    restored = _restore_counts(uow, [other for other in siblings if other.is_undone])
    changed = tuple(
        t
        for t in transactions
        if t.id in with_receipt or t.version > untouched_version(restored[t.id])
    )
    expected = batch.counts.created + batch.counts.replaced
    return UndoCheck(
        changed_in_app=changed,
        deleted_in_app=max(expected - len(transactions), 0),
        newer_batch=newer,
    )


def _undo_message(check: UndoCheck) -> str:
    if check.already_undone:
        return "Esta importação já foi desfeita."
    if check.newer_batch:
        return "Desfaça antes a importação mais recente desta planilha."
    return (
        "Alguns lançamentos desta importação foram alterados ou excluídos no app; "
        "por segurança, ela não pode ser desfeita."
    )
