"""Autoteste do executável empacotado (``AppFinanceiro.exe --self-test``).

Rodado pelo script de release logo após o build: garante que o PyInstaller incluiu tudo o que o
app precisa em produção (cripto, banco cifrado, migrações, interface, cliente de atualização, o
``root.json`` confiável, os geradores de PDF/Excel, o formato de backup e a leitura segura de
planilhas com ``defusedxml``).
Retorna 0 se tudo estiver OK. Não toca em dados reais.
"""

from __future__ import annotations

import tempfile
from pathlib import Path


def run_self_test() -> int:
    try:
        _check_crypto_and_database()
        _check_update_client()
        _check_ui_modules()
        _check_exporters()
        _check_backup_format()
        _check_spreadsheet_import()
    except Exception:  # noqa: BLE001 - qualquer falha = build inválido
        return 1
    return 0


def _check_crypto_and_database() -> None:
    from appfin.infrastructure.crypto.kdf import KdfParams
    from appfin.infrastructure.crypto.vault import create_vault, unlock_with_password
    from appfin.infrastructure.persistence.database import open_encrypted
    from appfin.infrastructure.persistence.migrator import migrate

    fast = KdfParams(opslimit=1, memlimit=8 * 1024)
    created = create_vault("autoteste do executavel", fast)
    dek = unlock_with_password(created.envelope, "autoteste do executavel", minimum=fast)
    with tempfile.TemporaryDirectory() as directory:
        connection = open_encrypted(Path(directory) / "selftest.db", dek)
        try:
            if migrate(connection) < 1:
                raise RuntimeError("migrações não encontradas no pacote")
        finally:
            connection.close()


def _check_update_client() -> None:
    import tufup.client  # noqa: F401 - só verifica que o import funciona no executável

    from appfin.infrastructure.updater import bundled_root_metadata

    if not bundled_root_metadata():
        raise RuntimeError("root.json confiável ausente do pacote")


def _check_ui_modules() -> None:
    import PySide6.QtNetwork
    import PySide6.QtWidgets  # noqa: F401
    import zxcvbn  # noqa: F401


def _check_exporters() -> None:
    from datetime import date

    from appfin.application.export_table import ColumnKind, ExportColumn, ExportTable
    from appfin.application.receipts import ReceiptData
    from appfin.domain.entities import Company, Receipt, Transaction
    from appfin.domain.enums import TransactionKind, TransactionStatus
    from appfin.domain.money import Money
    from appfin.infrastructure.exporters.receipt_pdf import render_receipt
    from appfin.infrastructure.exporters.tabular import to_csv, to_xlsx

    fake_id = "00000000-0000-7000-8000-000000000001"
    day = date(2026, 1, 1)
    transaction = Transaction(
        id=fake_id,
        kind=TransactionKind.INCOME,
        description="Autoteste",
        amount=Money(100),
        due_date=day,
        accrual_date=day,
        account_id=fake_id,
        status=TransactionStatus.PAID,
        paid_date=day,
    )
    data = ReceiptData(
        Receipt(fake_id, 1, fake_id, day),
        Company(name="Autoteste"),
        transaction,
        None,
        "um real",
        False,
    )
    if not render_receipt(data).startswith(b"%PDF-"):
        raise RuntimeError("gerador de PDF inválido")
    table = ExportTable("Autoteste", [ExportColumn("Valor", ColumnKind.MONEY)], [[100]])
    if not to_xlsx(table).startswith(b"PK") or not to_csv(table):
        raise RuntimeError("gerador de planilha inválido")


def _check_backup_format() -> None:
    import io

    from appfin.infrastructure.backup import stream
    from appfin.infrastructure.crypto.secret import SecretBytes

    key = SecretBytes(bytes(32))
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "db.bin"
        database.write_bytes(b"autoteste")
        out = io.BytesIO()
        stream.write_backup(out, stream.encode_header({}), {"ok": True}, database, key)
        source = io.BytesIO(out.getvalue())
        restored = io.BytesIO()
        manifest = stream.read_backup(source, stream.read_header(source), key, restored)
    if manifest != {"ok": True} or restored.getvalue() != b"autoteste":
        raise RuntimeError("formato de backup inválido")


def _check_spreadsheet_import() -> None:
    """Planilha mínima no layout "Fluxo de caixa", gerada em memória (dados fictícios), lida pelo
    leitor seguro (``defusedxml`` obrigatório) e conferida pela matriz mensal."""
    import io

    from openpyxl import Workbook
    from openpyxl.comments import Comment

    from appfin.domain.spreadsheet_import.cash_flow_layout import CASH_FLOW_LAYOUT
    from appfin.domain.spreadsheet_import.monthly_matrix import read_monthly_matrix
    from appfin.domain.spreadsheet_import.parse import MONTHS
    from appfin.infrastructure.importers.safe_reader import read_xlsx_bytes

    workbook = Workbook()
    sheet = workbook.active
    sheet.append([None, None, *MONTHS])
    sheet.append([None, "DINHEIRO", 1.5])
    sheet.cell(2, 3).comment = Comment("Autoteste:\nnota", "Autoteste")
    for anchor in CASH_FLOW_LAYOUT.anchors:
        value = 1.5 if anchor.label in ("RECEITA TOTAL", "LUCRO TOTAL FINAL") else None
        sheet.append([None, anchor.label, value])
    buffer = io.BytesIO()
    workbook.save(buffer)
    reading = read_monthly_matrix(read_xlsx_bytes(buffer.getvalue()).sheets[0], CASH_FLOW_LAYOUT)
    [line] = reading.lines
    if not reading.is_valid or line.amounts[0] != 150 or line.comments[0] != "nota":
        raise RuntimeError("leitura de planilha inválida")
