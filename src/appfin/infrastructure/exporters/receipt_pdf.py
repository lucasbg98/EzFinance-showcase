"""Recibo em PDF (A4) com reportlab.

Segurança: só ``drawString`` com texto simples — nada de ``Paragraph`` (que interpreta marcação),
então nome/descrição digitados não viram formatação. Os metadados do PDF não levam o nome do
paciente. O texto deixa claro que é comprovante interno e não substitui a NFS-e.
"""

from __future__ import annotations

import io

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm as _reportlab_mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from appfin.application.receipts import ReceiptData
from appfin.br_format import format_cents, format_date, format_document, format_phone, long_date
from appfin.domain.enums import PaymentMethod, TransactionKind

PAYMENT_LABELS = {
    PaymentMethod.PIX: "Pix",
    PaymentMethod.CASH: "Dinheiro",
    PaymentMethod.CREDIT: "Cartão de crédito",
    PaymentMethod.DEBIT: "Cartão de débito",
    PaymentMethod.BOLETO: "Boleto",
    PaymentMethod.TRANSFER: "Transferência",
    PaymentMethod.CHECK: "Cheque",
    PaymentMethod.OTHER: "Outra",
}
MM: float = float(_reportlab_mm)  # 1 milímetro em pontos (tipado)
_MARGIN = 20 * MM
_FONT = "Helvetica"
_BOLD = "Helvetica-Bold"
_NBSP = chr(0xA0)  # espaço que não quebra linha ("R$" junto do número)
_PRIMARY = (0.06, 0.46, 0.43)
_MUTED = (0.32, 0.38, 0.43)


def receipt_number(number: int) -> str:
    return f"{number:06d}"


def cro_text(value: str) -> str:
    """Evita "CRO CRO-SP 123" quando o cadastro já traz o prefixo."""
    return value if value.upper().startswith("CRO") else f"CRO {value}"


def wrap(text: str, font: str, size: float, width: float) -> list[str]:
    """Quebra só em espaços comuns (o espaço inseparável mantém "R$ 1.234,56" junto)."""
    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        candidate = f"{current} {word}" if current else word
        if current and stringWidth(candidate, font, size) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def render_receipt(data: ReceiptData) -> bytes:
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=A4, invariant=True)
    canvas.setTitle(f"Recibo {receipt_number(data.receipt.number)}")
    canvas.setAuthor("AppFinanceiro")
    canvas.setCreator("AppFinanceiro")
    width, height = A4
    right = width - _MARGIN
    y = height - _MARGIN

    y = _company_header(canvas, data, y, right)
    canvas.setStrokeColorRGB(*_PRIMARY)
    canvas.setLineWidth(1.2)
    canvas.line(_MARGIN, y, right, y)
    y -= 14 * MM

    canvas.setFont(_BOLD, 18)
    canvas.setFillColorRGB(0, 0, 0)
    canvas.drawString(_MARGIN, y, "RECIBO")
    canvas.setFont(_FONT, 11)
    canvas.drawString(_MARGIN, y - 7 * MM, f"Nº {receipt_number(data.receipt.number)}")
    _amount_box(canvas, format_cents(data.transaction.amount.cents), right, y)
    y -= 22 * MM

    canvas.setFont(_FONT, 12)
    for line in wrap(_body_text(data), _FONT, 12, right - _MARGIN):
        canvas.drawString(_MARGIN, y, line)
        y -= 7 * MM
    y -= 4 * MM

    canvas.setFont(_FONT, 10.5)
    for label, value in _details(data):
        canvas.setFillColorRGB(*_MUTED)
        canvas.drawString(_MARGIN, y, label)
        canvas.setFillColorRGB(0, 0, 0)
        canvas.drawString(_MARGIN + 45 * MM, y, value)
        y -= 6 * MM

    y -= 18 * MM
    canvas.setFont(_FONT, 11)
    canvas.drawString(_MARGIN, y, f"Emitido em {long_date(data.receipt.issued_on)}.")
    y -= 30 * MM
    middle = width / 2
    canvas.setStrokeColorRGB(0, 0, 0)
    canvas.setLineWidth(0.6)
    canvas.line(middle - 45 * MM, y, middle + 45 * MM, y)
    signer = data.company.responsible or data.company.trade_name or data.company.name
    canvas.setFont(_FONT, 10)
    canvas.drawCentredString(middle, y - 5 * MM, signer)
    if data.company.cro_number:
        canvas.drawCentredString(middle, y - 10 * MM, cro_text(data.company.cro_number))

    canvas.setFont(_FONT, 8)
    canvas.setFillColorRGB(*_MUTED)
    footer = "Comprovante interno emitido pelo AppFinanceiro. Não substitui a nota fiscal (NFS-e)."
    if data.reissue:
        footer += "  •  2ª via"
    canvas.drawString(_MARGIN, _MARGIN, footer)
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def _company_header(canvas: Canvas, data: ReceiptData, y: float, right: float) -> float:
    company = data.company
    canvas.setFillColorRGB(*_PRIMARY)
    canvas.setFont(_BOLD, 15)
    canvas.drawString(_MARGIN, y, company.trade_name or company.name)
    y -= 6 * MM
    canvas.setFillColorRGB(*_MUTED)
    canvas.setFont(_FONT, 9.5)
    lines = []
    if company.trade_name:
        lines.append(company.name)
    identity = []
    if company.document:
        identity.append(
            ("CNPJ " if len(company.document) == 14 else "CPF ") + format_document(company.document)
        )
    if company.cro_number:
        identity.append(cro_text(company.cro_number))
    if identity:
        lines.append("  •  ".join(identity))
    if company.address:
        lines.append(company.address)
    contact = [format_phone(p) for p in (company.phone, company.whatsapp) if p]
    if company.email:
        contact.append(company.email)
    if contact:
        lines.append("  •  ".join(contact))
    for line in lines:
        for piece in wrap(line, _FONT, 9.5, right - _MARGIN):
            canvas.drawString(_MARGIN, y, piece)
            y -= 4.6 * MM
    return y - 3 * MM


def _amount_box(canvas: Canvas, amount: str, right: float, y: float) -> None:
    box_width, box_height = 60 * MM, 14 * MM
    canvas.setStrokeColorRGB(*_PRIMARY)
    canvas.setLineWidth(1)
    canvas.roundRect(right - box_width, y - 8 * MM, box_width, box_height, 3 * MM)
    canvas.setFont(_BOLD, 15)
    canvas.setFillColorRGB(0, 0, 0)
    canvas.drawCentredString(right - box_width / 2, y - 2.5 * MM, amount)


def _body_text(data: ReceiptData) -> str:
    t = data.transaction
    party = data.contact.name if data.contact else "—"
    if data.contact and data.contact.document:
        kind = "CPF" if len(data.contact.document) == 11 else "CNPJ"
        party += f" ({kind} {format_document(data.contact.document)})"
    value = f"{format_cents(t.amount.cents).replace(' ', _NBSP)} ({data.amount_words})"
    if t.kind is TransactionKind.INCOME:
        return f"Recebemos de {party} a importância de {value}, referente a: {t.description}."
    return f"Pagamos a {party} a importância de {value}, referente a: {t.description}."


def _details(data: ReceiptData) -> list[tuple[str, str]]:
    t = data.transaction
    rows = [("Data do pagamento:", format_date(t.paid_date))]
    if t.payment_method:
        rows.append(("Forma de pagamento:", PAYMENT_LABELS[t.payment_method]))
    if t.document_number:
        rows.append(("Documento:", t.document_number))
    if t.official_receipt_ref:
        rows.append(("NFS-e:", t.official_receipt_ref))
    return rows
