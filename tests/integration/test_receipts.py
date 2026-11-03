"""Recibos: numeração, 2ª via com o mesmo número e regras de emissão (dados fictícios)."""

from __future__ import annotations

import base64
import re
import zlib
from datetime import date

import pytest

from appfin.application.receipts import ReceiptService
from appfin.application.transactions import TransactionDraft
from appfin.domain.entities import Company, Contact
from appfin.domain.enums import ContactRole, PaymentMethod, TransactionKind
from appfin.domain.errors import BusinessRuleError
from appfin.domain.money import Money
from appfin.infrastructure.exporters.receipt_pdf import receipt_number, render_receipt
from appfin.infrastructure.ids import uuid7
from tests.integration.conftest import TODAY, App


@pytest.fixture
def receipts(app: App) -> ReceiptService:
    return ReceiptService(app.uow, uuid7, lambda: TODAY)


def _paid(app: App, *, kind: TransactionKind = TransactionKind.INCOME, pay: bool = True) -> str:
    account = app.catalog.list_accounts()[0]
    category = next(
        c
        for c in app.catalog.list_categories()
        if c.name == ("Tratamentos particulares" if kind is TransactionKind.INCOME else "Aluguel")
    )
    contact = app.catalog.save_contact(
        Contact(
            "",
            name="Paciente Fictício",
            roles=frozenset({ContactRole.PATIENT}),
            document="52998224725",
        )
    )
    created = app.transactions.create(
        TransactionDraft(
            kind=kind,
            description="Limpeza",
            total=Money(25_050),
            first_due=date(2026, 3, 10),
            account_id=account.id,
            category_id=category.id,
            contact_id=contact.id,
            payment_method=PaymentMethod.PIX,
            pay_now=pay,
        )
    )
    return created[0].id


def test_requires_company_data(app: App, receipts: ReceiptService) -> None:
    transaction_id = _paid(app)

    with pytest.raises(BusinessRuleError, match="dados do consultório"):
        receipts.issue(transaction_id)


def test_sequential_numbers_and_reissue(app: App, receipts: ReceiptService) -> None:
    app.catalog.save_company(Company(name="Clínica Fictícia", document="11222333000181"))
    first, second = _paid(app), _paid(app)

    a = receipts.issue(first)
    b = receipts.issue(second)
    again = receipts.issue(first)

    assert (a.receipt.number, b.receipt.number) == (1, 2)
    assert again.receipt.number == 1 and again.reissue and not a.reissue
    assert a.amount_words == "duzentos e cinquenta reais e cinquenta centavos"
    assert a.contact is not None and a.contact.name == "Paciente Fictício"


def test_pending_transaction_has_no_receipt(app: App, receipts: ReceiptService) -> None:
    app.catalog.save_company(Company(name="Clínica Fictícia"))
    pending = _paid(app, pay=False)

    with pytest.raises(BusinessRuleError, match="já recebido ou pago"):
        receipts.issue(pending)


def test_pdf_contains_the_receipt_text(app: App, receipts: ReceiptService) -> None:
    app.catalog.save_company(
        Company(name="Clínica Fictícia Ltda", trade_name="Sorriso Fictício", cro_number="12345")
    )
    data = receipts.issue(_paid(app))

    pdf = render_receipt(data)

    assert pdf.startswith(b"%PDF-") and pdf.rstrip().endswith(b"%%EOF")
    text = _pdf_text(pdf)
    assert "RECIBO" in text and f"N{chr(0xBA)} {receipt_number(1)}" in text
    assert "Recebemos de Paciente Fictício (CPF 529.982.247-25)" in " ".join(text.split())
    assert "Não substitui a nota fiscal" in text
    # Metadados não levam o nome do paciente.
    assert b"Paciente" not in re.sub(rb"stream.*?endstream", b"", pdf, flags=re.S)


def test_expense_receipt_says_we_paid(app: App, receipts: ReceiptService) -> None:
    app.catalog.save_company(Company(name="Clínica Fictícia"))
    data = receipts.issue(_paid(app, kind=TransactionKind.EXPENSE))

    assert "Pagamos a Paciente Fictício" in " ".join(_pdf_text(render_receipt(data)).split())


def _pdf_text(pdf: bytes) -> str:
    """Texto desenhado com Tj, sem depender de leitor de PDF (só zlib)."""
    lines = []
    for content in _streams(pdf):
        lines.extend(literal.decode("cp1252") for literal in _shown_strings(content))
    return NEWLINE.join(lines)


NEWLINE = chr(10)
_BACKSLASH, _OPEN, _CLOSE = 92, 40, 41
_EOL = bytes([13, 10])


def _streams(pdf: bytes) -> list[bytes]:
    found = []
    position = 0
    while (start := pdf.find(b"stream", position)) != -1:
        position = start + len(b"stream")
        if pdf[start - 3 : start] == b"end":
            continue
        end = pdf.find(b"endstream", position)
        raw = pdf[position:end].strip(_EOL)
        if raw.endswith(b"~>"):  # reportlab: /ASCII85Decode + /FlateDecode
            raw = base64.a85decode(raw[:-2])
        try:
            found.append(zlib.decompress(raw))
        except zlib.error:
            found.append(raw)
        position = end + len(b"endstream")
    return found


def _shown_strings(content: bytes) -> list[bytes]:
    """Lê as strings literais ``(...)`` seguidas de ``Tj``, tratando os escapes do PDF."""
    result = []
    index = 0
    while (index := content.find(bytes([_OPEN]), index)) != -1:
        index += 1
        text = bytearray()
        while index < len(content) and content[index] != _CLOSE:
            byte = content[index]
            if byte == _BACKSLASH:
                index += 1
                digits = content[index : index + 3]
                count = len(digits) - len(digits.lstrip(b"01234567"))
                if count:
                    text.append(int(digits[:count], 8))
                    index += count
                    continue
                if index >= len(content):
                    break
                byte = content[index]
            text.append(byte)
            index += 1
        index += 1
        if content[index : index + 3] == b" Tj":
            result.append(bytes(text))
    return result


def test_wrap_keeps_currency_with_number_and_cro_prefix_once() -> None:
    from appfin.infrastructure.exporters.receipt_pdf import cro_text, wrap

    nbsp = chr(0xA0)
    lines = wrap(f"importância de R${nbsp}1.234,56 referente", "Helvetica", 12, 100)
    assert any(f"R${nbsp}1.234,56" in line for line in lines)
    assert all(line.strip() for line in lines)
    assert cro_text("CRO-SP 12345") == "CRO-SP 12345"
    assert cro_text("12345") == "CRO 12345"
