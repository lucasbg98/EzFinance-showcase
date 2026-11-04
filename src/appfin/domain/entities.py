"""Entidades do domínio. Imutáveis; as invariantes são garantidas no construtor.

Metadados técnicos (``created_at``/``updated_at``/``deleted_at``) ficam na persistência;
``version`` fica na entidade porque participa da concorrência otimista.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from types import MappingProxyType

from appfin.domain.enums import (
    AccountKind,
    CategoryKind,
    ContactRole,
    DreGroup,
    ImportLayout,
    ImportSource,
    IntervalUnit,
    LegalType,
    PaymentMethod,
    PersonType,
    TaxRegime,
    TransactionKind,
    TransactionStatus,
)
from appfin.domain.errors import BusinessRuleError, ValidationError
from appfin.domain.money import Money
from appfin.domain.validation import (
    clean_document,
    clean_email,
    clean_multiline,
    clean_text,
    only_digits,
)

COMPANY_ID = "company"
MAX_INSTALLMENTS = 360
MAX_PROFILE_LINES = 2000
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_UF = frozenset(
    [
        "AC",
        "AL",
        "AP",
        "AM",
        "BA",
        "CE",
        "DF",
        "ES",
        "GO",
        "MA",
        "MT",
        "MS",
        "MG",
        "PA",
        "PB",
        "PR",
        "PE",
        "PI",
        "RJ",
        "RN",
        "RS",
        "RO",
        "RR",
        "SC",
        "SP",
        "SE",
        "TO",
    ]
)


def _set(entity: object, name: str, value: object) -> None:
    object.__setattr__(entity, name, value)


NEW_ID = ""  # entidade ainda não salva: o caso de uso atribui o UUIDv7 ao gravar


def _require_id(value: str, field_name: str = "id", *, allow_new: bool = False) -> None:
    if allow_new and value == NEW_ID:
        return
    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        raise ValidationError(field_name, "Identificador inválido.")


def _require_sha256(value: str | None, field_name: str) -> None:
    if not isinstance(value, str) or not _SHA256_HEX.fullmatch(value):
        raise ValidationError(field_name, "Identificador de importação inválido.")


def _clean_phone(value: str, field_name: str) -> str:
    digits = only_digits(value)
    if digits and not 10 <= len(digits) <= 13:
        raise ValidationError(field_name, "Telefone inválido (use DDD + número).")
    return digits


# ---------------------------------------------------------------------- empresa
@dataclass(frozen=True, slots=True)
class Company:
    name: str
    legal_type: LegalType = LegalType.PJ
    trade_name: str = ""
    document: str = ""
    cro_number: str = ""
    responsible: str = ""
    address: str = ""
    phone: str = ""
    whatsapp: str = ""
    email: str = ""
    tax_regime: TaxRegime = TaxRegime.SIMPLES
    id: str = COMPANY_ID
    version: int = 0

    def __post_init__(self) -> None:
        if self.id != COMPANY_ID:
            raise ValidationError("id", "Só existe um cadastro de empresa.")
        _set(self, "name", clean_text(self.name, "name", max_length=120, required=True))
        _set(self, "trade_name", clean_text(self.trade_name, "trade_name", max_length=120))
        document = clean_document(self.document, "document")
        expected = 14 if self.legal_type is LegalType.PJ else 11
        if document and len(document) != expected:
            raise ValidationError("document", "Documento não corresponde ao tipo (CPF/CNPJ).")
        _set(self, "document", document)
        _set(self, "cro_number", clean_text(self.cro_number, "cro_number", max_length=20))
        _set(self, "responsible", clean_text(self.responsible, "responsible", max_length=120))
        _set(self, "address", clean_text(self.address, "address", max_length=300))
        _set(self, "phone", _clean_phone(self.phone, "phone"))
        _set(self, "whatsapp", _clean_phone(self.whatsapp, "whatsapp"))
        _set(self, "email", clean_email(self.email))


# ---------------------------------------------------------------------- conta
@dataclass(frozen=True, slots=True)
class Account:
    id: str
    name: str
    kind: AccountKind = AccountKind.CHECKING
    opening_balance: Money = field(default_factory=Money.zero)
    opening_date: date | None = None
    archived: bool = False
    version: int = 0

    def __post_init__(self) -> None:
        _require_id(self.id, allow_new=True)
        _set(self, "name", clean_text(self.name, "name", max_length=60, required=True))


# ---------------------------------------------------------------------- categoria
@dataclass(frozen=True, slots=True)
class Category:
    id: str
    name: str
    kind: CategoryKind
    parent_id: str | None = None
    dre_group: DreGroup | None = None
    archived: bool = False
    version: int = 0

    def __post_init__(self) -> None:
        _require_id(self.id, allow_new=True)
        _set(self, "name", clean_text(self.name, "name", max_length=60, required=True))
        if self.parent_id is not None:
            _require_id(self.parent_id, "parent_id")
            if self.parent_id == self.id:
                raise ValidationError("parent_id", "Uma categoria não pode ser grupo de si mesma.")

    @property
    def is_group(self) -> bool:
        return self.parent_id is None

    def accepts(self, kind: TransactionKind) -> bool:
        if kind is TransactionKind.INCOME:
            return self.kind in (CategoryKind.INCOME, CategoryKind.BOTH)
        if kind is TransactionKind.EXPENSE:
            return self.kind in (CategoryKind.EXPENSE, CategoryKind.BOTH)
        return False


# ---------------------------------------------------------------------- contato
@dataclass(frozen=True, slots=True)
class Contact:
    """Paciente, fornecedor ou convênio. De paciente, só o nome é obrigatório (LGPD)."""

    id: str
    name: str
    roles: frozenset[ContactRole] = frozenset({ContactRole.PATIENT})
    person_type: PersonType = PersonType.PF
    document: str = ""
    phone: str = ""
    email: str = ""
    street: str = ""
    number: str = ""
    district: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    notes: str = ""
    archived: bool = False
    version: int = 0

    def __post_init__(self) -> None:
        _require_id(self.id, allow_new=True)
        _set(self, "name", clean_text(self.name, "name", max_length=120, required=True))
        roles = frozenset(self.roles)
        if not roles:
            raise ValidationError("roles", "Escolha ao menos um tipo de contato.")
        _set(self, "roles", roles)
        document = clean_document(self.document, "document")
        expected = 11 if self.person_type is PersonType.PF else 14
        if document and len(document) != expected:
            raise ValidationError("document", "Documento não corresponde ao tipo (CPF/CNPJ).")
        _set(self, "document", document)
        _set(self, "phone", _clean_phone(self.phone, "phone"))
        _set(self, "email", clean_email(self.email))
        for name, size in (("street", 120), ("number", 20), ("district", 60), ("city", 60)):
            _set(self, name, clean_text(getattr(self, name), name, max_length=size))
        state = clean_text(self.state, "state", max_length=2).upper()
        if state and state not in _UF:
            raise ValidationError("state", "UF inválida.")
        _set(self, "state", state)
        zip_code = only_digits(self.zip_code)
        if zip_code and len(zip_code) != 8:
            raise ValidationError("zip_code", "CEP inválido.")
        _set(self, "zip_code", zip_code)
        _set(self, "notes", clean_multiline(self.notes, "notes", max_length=1000))


# ---------------------------------------------------------------------- parcelamento
@dataclass(frozen=True, slots=True)
class InstallmentGroup:
    id: str
    count: int
    interval_unit: IntervalUnit
    interval_value: int
    total: Money
    version: int = 0

    def __post_init__(self) -> None:
        _require_id(self.id, allow_new=True)
        if not 1 <= self.count <= MAX_INSTALLMENTS:
            raise ValidationError("count", f"Parcelas: de 1 a {MAX_INSTALLMENTS}.")
        if not 1 <= self.interval_value <= 366:
            raise ValidationError("interval_value", "Intervalo inválido.")
        if not self.total.is_positive:
            raise ValidationError("total", "Informe um valor maior que zero.")


# ---------------------------------------------------------------------- lançamento
@dataclass(frozen=True, slots=True)
class Transaction:
    id: str
    kind: TransactionKind
    description: str
    amount: Money
    accrual_date: date
    due_date: date
    account_id: str
    status: TransactionStatus = TransactionStatus.PENDING
    paid_date: date | None = None
    category_id: str | None = None
    contact_id: str | None = None
    payment_method: PaymentMethod | None = None
    document_number: str = ""
    official_receipt_ref: str = ""
    notes: str = ""
    installment_group_id: str | None = None
    installment_number: int | None = None
    transfer_id: str | None = None
    import_batch_id: str | None = None
    # Identidade da célula da planilha (SHA-256 em hex): a mesma célula nunca entra duas vezes.
    import_row_key: str | None = None
    version: int = 0

    def __post_init__(self) -> None:
        _require_id(self.id, allow_new=True)
        _require_id(self.account_id, "account_id")
        _set(
            self,
            "description",
            clean_text(self.description, "description", max_length=200, required=True),
        )
        if not self.amount.is_positive:
            raise ValidationError("amount", "Informe um valor maior que zero.")
        if self.status is TransactionStatus.PAID and self.paid_date is None:
            raise ValidationError("paid_date", "Informe a data de pagamento.")
        if self.status is not TransactionStatus.PAID and self.paid_date is not None:
            raise ValidationError("paid_date", "Só lançamentos pagos têm data de pagamento.")
        if self.kind.is_transfer:
            if self.transfer_id is None:
                raise ValidationError("transfer_id", "Transferência sem vínculo.")
            if self.category_id is not None:
                raise ValidationError("category_id", "Transferência não tem categoria.")
        elif self.transfer_id is not None:
            raise ValidationError("transfer_id", "Só transferências têm vínculo de transferência.")
        has_group = self.installment_group_id is not None
        if has_group != (self.installment_number is not None):
            raise ValidationError("installment_number", "Parcela sem parcelamento (ou vice-versa).")
        if self.installment_number is not None and not (
            1 <= self.installment_number <= MAX_INSTALLMENTS
        ):
            raise ValidationError("installment_number", "Número de parcela inválido.")
        if self.import_batch_id is not None:
            _require_id(self.import_batch_id, "import_batch_id")
        if self.import_row_key is not None:
            _require_sha256(self.import_row_key, "import_row_key")
            if self.import_batch_id is None:
                raise ValidationError("import_row_key", "Célula importada sem lote.")
        _set(
            self,
            "document_number",
            clean_text(self.document_number, "document_number", max_length=40),
        )
        _set(
            self,
            "official_receipt_ref",
            clean_text(self.official_receipt_ref, "official_receipt_ref", max_length=60),
        )
        _set(self, "notes", clean_multiline(self.notes, "notes", max_length=1000))

    # ------------------------------------------------------------------ consultas
    def is_overdue(self, today: date) -> bool:
        """Vencida é **calculado**: pendente e com vencimento anterior a hoje."""
        return self.status is TransactionStatus.PENDING and self.due_date < today

    # ------------------------------------------------------------------ transições
    def mark_paid(self, paid_date: date, account_id: str | None = None) -> Transaction:
        if self.status is TransactionStatus.CANCELLED:
            raise ValidationError("status", "Lançamento cancelado não pode ser pago.")
        return replace(
            self,
            status=TransactionStatus.PAID,
            paid_date=paid_date,
            account_id=account_id or self.account_id,
        )

    def mark_pending(self) -> Transaction:
        return replace(self, status=TransactionStatus.PENDING, paid_date=None)


# ---------------------------------------------------------------------- recibo
@dataclass(frozen=True, slots=True)
class Receipt:
    """Recibo interno numerado (comprovante complementar; não substitui a NFS-e)."""

    id: str
    number: int
    transaction_id: str
    issued_on: date
    version: int = 0

    def __post_init__(self) -> None:
        _require_id(self.id, allow_new=True)
        _require_id(self.transaction_id, "transaction_id")
        if self.number < 1:
            raise ValidationError("number", "Número de recibo inválido.")


# ---------------------------------------------------------------------- importação de planilha
@dataclass(frozen=True, slots=True)
class ImportProfile:
    """Mapeamento salvo de uma planilha: chave normalizada da linha → id da categoria.

    Fica só no banco cifrado: as chaves vêm dos rótulos da planilha e podem conter nomes de
    pessoas (plano de importação §5.3), por isso nunca vão para código, testes ou logs.
    """

    id: str
    name: str
    layout: ImportLayout = ImportLayout.MONTHLY_MATRIX
    line_map: Mapping[str, str] = field(default_factory=dict)
    version: int = 0

    def __post_init__(self) -> None:
        _require_id(self.id, allow_new=True)
        _set(self, "name", clean_text(self.name, "name", max_length=60, required=True))
        if len(self.line_map) > MAX_PROFILE_LINES:
            raise ValidationError("line_map", f"No máximo {MAX_PROFILE_LINES} linhas por perfil.")
        cleaned: dict[str, str] = {}
        for key, category_id in self.line_map.items():
            line_key = clean_text(key, "line_map", max_length=200, required=True)
            _require_id(category_id, "line_map")
            cleaned[line_key] = category_id
        _set(self, "line_map", MappingProxyType(cleaned))


@dataclass(frozen=True, slots=True)
class ImportCounts:
    """O que uma confirmação fez (plano de importação §6.2)."""

    created: int = 0
    replaced: int = 0
    removed: int = 0
    skipped: int = 0
    kept: int = 0  # diferença informada, mas o lançamento alterado no app foi mantido

    def __post_init__(self) -> None:
        for name in ("created", "replaced", "removed", "skipped", "kept"):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0:
                raise ValidationError(name, "Contagem inválida.")


@dataclass(frozen=True, slots=True)
class ImportBatch:
    """Lote de uma importação confirmada. Sem nome de arquivo (pode ter nome de pessoa)."""

    id: str
    profile_id: str
    source: ImportSource
    file_sha256: str
    period_year: int
    imported_at: datetime
    counts: ImportCounts = field(default_factory=ImportCounts)
    undone_at: datetime | None = None
    version: int = 0

    def __post_init__(self) -> None:
        _require_id(self.id, allow_new=True)
        _require_id(self.profile_id, "profile_id")
        _require_sha256(self.file_sha256, "file_sha256")
        if not 2000 <= self.period_year <= 2100:
            raise ValidationError("period_year", "Ano inválido.")
        for name in ("imported_at", "undone_at"):
            moment = getattr(self, name)
            if moment is not None and moment.tzinfo is None:
                raise ValidationError(name, "Data e hora sem fuso.")

    @property
    def is_undone(self) -> bool:
        return self.undone_at is not None

    def mark_undone(self, at: datetime) -> ImportBatch:
        if self.is_undone:
            raise BusinessRuleError("Esta importação já foi desfeita.")
        return replace(self, undone_at=at)


@dataclass(frozen=True, slots=True)
class ImportReplacement:
    """Lançamento antigo que o lote excluiu; ``new_transaction_id=None`` = só removeu."""

    batch_id: str
    old_transaction_id: str
    new_transaction_id: str | None = None

    def __post_init__(self) -> None:
        _require_id(self.batch_id, "batch_id")
        _require_id(self.old_transaction_id, "old_transaction_id")
        if self.new_transaction_id is not None:
            _require_id(self.new_transaction_id, "new_transaction_id")
            if self.new_transaction_id == self.old_transaction_id:
                raise ValidationError("new_transaction_id", "Substituição para o mesmo lançamento.")
