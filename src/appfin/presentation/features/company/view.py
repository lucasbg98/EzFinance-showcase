"""Dados do consultório: no primeiro uso (onboarding) e em Configurações."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFormLayout, QFrame, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from appfin.domain.entities import Company
from appfin.domain.enums import LegalType, TaxRegime
from appfin.domain.errors import DomainError
from appfin.presentation.shared.formatting import format_document, format_phone
from appfin.presentation.shared.ui.feedback import friendly_message
from appfin.presentation.shared.ui.forms import (
    combo,
    plain_label,
    select_data,
    set_message,
    text_field,
)
from appfin.presentation.workspace import Workspace

REGIMES = [
    ("Simples Nacional", TaxRegime.SIMPLES),
    ("Lucro Presumido", TaxRegime.PRESUMIDO),
    ("Pessoa física (carnê-leão)", TaxRegime.CARNE_LEAO),
    ("Outro", TaxRegime.OTHER),
]


class CompanyForm(QWidget):
    saved = Signal(object)  # Company

    def __init__(self, workspace: Workspace, *, onboarding: bool = False) -> None:
        super().__init__()
        self._ws = workspace
        self._onboarding = onboarding
        self._current: Company | None = workspace.catalog.get_company()

        self.legal_type = combo(
            [("Pessoa jurídica (CNPJ)", LegalType.PJ), ("Pessoa física (CPF)", LegalType.PF)],
            "Tipo de pessoa",
        )
        self.name = text_field(120, "Razão social ou nome", "Ex.: Clínica Odontológica Exemplo")
        self.trade_name = text_field(120, "Nome fantasia")
        self.document = text_field(18, "CNPJ ou CPF", "00.000.000/0000-00")
        self.cro = text_field(20, "CRO do responsável")
        self.responsible = text_field(120, "Responsável técnico")
        self.address = text_field(300, "Endereço")
        self.phone = text_field(16, "Telefone", "(00) 0000-0000")
        self.whatsapp = text_field(16, "WhatsApp", "(00) 00000-0000")
        self.email = text_field(254, "E-mail")
        self.regime = combo(REGIMES, "Regime tributário")
        self.message = plain_label("", "error")
        self.submit = QPushButton("Continuar" if onboarding else "Salvar")
        self.submit.setObjectName("primary")

        form = QFormLayout()
        for label, widget in (
            ("Tipo:", self.legal_type),
            ("Razão social / nome:*", self.name),
            ("Nome fantasia:", self.trade_name),
            ("CNPJ / CPF:", self.document),
            ("CRO:", self.cro),
            ("Responsável:", self.responsible),
            ("Endereço:", self.address),
            ("Telefone:", self.phone),
            ("WhatsApp:", self.whatsapp),
            ("E-mail:", self.email),
            ("Regime tributário:", self.regime),
        ):
            form.addRow(label, widget)

        card = QFrame()
        card.setObjectName("card")
        card.setMaximumWidth(640)
        inner = QVBoxLayout(card)
        inner.setContentsMargins(28, 24, 28, 24)
        inner.addWidget(plain_label("Dados do consultório", "title"))
        inner.addWidget(
            plain_label(
                "Usados no cabeçalho dos recibos e relatórios. Ficam só neste computador, "
                "cifrados. O regime tributário define as categorias de impostos sugeridas."
                if onboarding
                else "Usados no cabeçalho dos recibos e relatórios.",
                "muted",
            )
        )
        inner.addLayout(form)
        inner.addWidget(self.message)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.submit)
        inner.addLayout(buttons)
        outer = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(card)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)

        self.submit.clicked.connect(self._save)
        self._load()

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
        self.message.setText("")
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
            return
        self._current = saved
        set_message(self.message, "" if self._onboarding else "Dados salvos.", ok=True)
        self.saved.emit(saved)
