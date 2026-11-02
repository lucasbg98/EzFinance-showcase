"""Dados do consultório: no primeiro uso (onboarding) e em Configurações.

Mesmo padrão visual dos modais (FormBuilder): seções, rótulos acima, vários campos por linha.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from appfin.domain.entities import Company
from appfin.domain.enums import LegalType, TaxRegime
from appfin.domain.errors import DomainError, ValidationError
from appfin.presentation.shared.formatting import format_document, format_phone
from appfin.presentation.shared.ui.feedback import friendly_message
from appfin.presentation.shared.ui.forms import (
    Field,
    FormBuilder,
    combo,
    plain_label,
    select_data,
    set_message,
    text_field,
)
from appfin.presentation.workspace import Workspace

CARD_MAX_WIDTH = 920
REGIMES = [
    ("Simples Nacional", TaxRegime.SIMPLES),
    ("Lucro Presumido", TaxRegime.PRESUMIDO),
    ("Pessoa física (carnê-leão)", TaxRegime.CARNE_LEAO),
    ("Outro", TaxRegime.OTHER),
]


class CompanyForm(FormBuilder, QWidget):
    saved = Signal(object)  # Company

    def __init__(self, workspace: Workspace, *, onboarding: bool = False) -> None:
        super().__init__()
        self._ws = workspace
        self._onboarding = onboarding
        self._current: Company | None = workspace.catalog.get_company()
        self._fields: dict[str, QWidget] = {}

        self.legal_type = combo(
            [("Pessoa jurídica", LegalType.PJ), ("Pessoa física", LegalType.PF)], "Tipo de pessoa"
        )
        self.document = text_field(18, "CNPJ ou CPF")
        self.name = text_field(
            120, "Razão social ou nome", "Ex.: Clínica Odontológica Exemplo Ltda"
        )
        self.trade_name = text_field(120, "Nome fantasia", "Como o consultório é conhecido")
        self.regime = combo(REGIMES, "Regime tributário")
        self.responsible = text_field(120, "Responsável técnico", "Nome do(a) dentista responsável")
        self.cro = text_field(20, "CRO do responsável", "Ex.: CRO-SP 12345")
        self.phone = text_field(16, "Telefone", "(00) 0000-0000")
        self.whatsapp = text_field(16, "WhatsApp", "(00) 00000-0000")
        self.email = text_field(254, "E-mail", "contato@consultorio.com.br")
        self.address = text_field(300, "Endereço", "Rua, número, bairro, cidade/UF, CEP")
        self.message = plain_label("", "error")
        self.submit = QPushButton("Continuar" if onboarding else "Salvar alterações")
        self.submit.setObjectName("primary")

        card = QFrame()
        card.setObjectName("card")
        card.setMaximumWidth(CARD_MAX_WIDTH)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("cardHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(32, 24, 32, 18)
        header_layout.setSpacing(4)
        header_layout.addWidget(plain_label("Dados do consultório", "title"))
        header_layout.addWidget(
            plain_label(
                "Aparecem no cabeçalho dos recibos e relatórios. Ficam só neste computador, "
                "cifrados.",
                "muted",
            )
        )
        card_layout.addWidget(header)

        self.body = QVBoxLayout()
        self.body.setContentsMargins(32, 18, 32, 12)
        self.body.setSpacing(12)
        card_layout.addLayout(self.body)
        if onboarding:
            self.add_banner(
                "Primeiro acesso: preencha os dados básicos para começar. O regime tributário "
                "define as categorias de impostos sugeridas; tudo pode ser alterado depois."
            )
        self.add_section("IDENTIFICAÇÃO")
        self.document_row = self.add_row(
            Field("Tipo de pessoa", self.legal_type, "legal_type", stretch=1),
            Field("CNPJ", self.document, "document", stretch=1),
        )
        self.add_row(Field("Razão social / nome", self.name, "name", required=True))
        self.add_row(
            Field("Nome fantasia", self.trade_name, "trade_name", stretch=1),
            Field("Regime tributário", self.regime, "tax_regime", stretch=1),
        )
        self.add_section("RESPONSÁVEL TÉCNICO")
        self.add_row(
            Field("Nome", self.responsible, "responsible", stretch=2),
            Field("CRO", self.cro, "cro_number", stretch=1),
        )
        self.add_section("CONTATO")
        self.add_row(
            Field("Telefone", self.phone, "phone", stretch=1),
            Field("WhatsApp", self.whatsapp, "whatsapp", stretch=1),
            Field("E-mail", self.email, "email", stretch=2),
        )
        self.add_section("ENDEREÇO")
        self.add_row(Field("Endereço completo", self.address, "address"))

        footer = QFrame()
        footer.setObjectName("cardFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(32, 14, 32, 14)
        footer_layout.addWidget(self.message, 1)
        footer_layout.addWidget(self.submit)
        card_layout.addSpacing(8)
        card_layout.addWidget(footer)

        content = QWidget()
        content.setObjectName("pageContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 24)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(card, 100)
        row.addStretch(1)
        content_layout.addLayout(row)
        content_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self.legal_type.currentIndexChanged.connect(self._update_document_label)
        self.submit.clicked.connect(self._save)
        self._load()
        self._update_document_label()

    def _update_document_label(self) -> None:
        is_pj = self.legal_type.value() is LegalType.PJ
        caption = self.document_row.findChildren(QLabel)[1]
        caption.setText("CNPJ" if is_pj else "CPF")
        self.document.setPlaceholderText("00.000.000/0000-00" if is_pj else "000.000.000-00")

    def _load(self) -> None:
        company = self._current
        if company is None:
            return
        select_data(self.legal_type, company.legal_type)
        self.name.setText(company.name)
        self.trade_name.setText(company.trade_name)
        self.document.setText(format_document(company.document))
        self.cro.setText(company.cro_number)
        self.responsible.setText(company.responsible)
        self.address.setText(company.address)
        self.phone.setText(format_phone(company.phone))
        self.whatsapp.setText(format_phone(company.whatsapp))
        self.email.setText(company.email)
        select_data(self.regime, company.tax_regime)

    def _save(self) -> None:
        self.clear_invalid()
        set_message(self.message, "")
        try:
            company = Company(
                name=self.name.text(),
                legal_type=self.legal_type.value(),
                trade_name=self.trade_name.text(),
                document=self.document.text(),
                cro_number=self.cro.text(),
                responsible=self.responsible.text(),
                address=self.address.text(),
                phone=self.phone.text(),
                whatsapp=self.whatsapp.text(),
                email=self.email.text(),
                tax_regime=self.regime.value(),
            )
            if self._current is not None:
                company = replace(company, version=self._current.version)
            saved = self._ws.catalog.save_company(company)
            if self._onboarding:
                self._ws.catalog.initialize_defaults(saved.tax_regime)
        except DomainError as error:
            set_message(self.message, friendly_message(error, "company.save"))
            if isinstance(error, ValidationError):
                self.mark_invalid(error.field)
            return
        self._current = saved
        set_message(self.message, "" if self._onboarding else "Dados salvos.", ok=True)
        self.saved.emit(saved)
