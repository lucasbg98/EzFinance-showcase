"""Contatos: pacientes, fornecedores e convênios. Minimização de dados (LGPD)."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from appfin.domain.entities import NEW_ID, Contact
from appfin.domain.enums import ContactRole, PersonType
from appfin.domain.errors import ValidationError
from appfin.presentation.shared.formatting import format_document, format_phone
from appfin.presentation.shared.ui.feedback import confirm, show_error
from appfin.presentation.shared.ui.forms import (
    Field,
    FormDialog,
    chip,
    combo,
    notes_field,
    plain_label,
    search_field,
    select_data,
    text_field,
)
from appfin.presentation.shared.ui.table import (
    Column,
    RowsTableModel,
    TablePanel,
    make_table,
    selected_rows,
)
from appfin.presentation.workspace import Workspace

ROLE_LABELS = {
    ContactRole.PATIENT: "Paciente",
    ContactRole.SUPPLIER: "Fornecedor",
    ContactRole.INSURER: "Convênio",
    ContactRole.OTHER: "Outro",
}
EMPTY_CONTACTS = "Nenhum contato cadastrado ainda. Clique em “+ Novo contato” para começar."
LGPD_HINT = (
    "Cadastre só o necessário: de paciente, apenas o nome é obrigatório. "
    "Não registre informações clínicas (procedimentos, diagnósticos) aqui."
)


class ContactDialog(FormDialog):
    def __init__(self, ws: Workspace, contact: Contact | None, parent: QWidget) -> None:
        super().__init__(
            "Editar contato" if contact else "Novo contato",
            parent,
            subtitle="Paciente, fornecedor ou convênio.",
            save_text="Salvar contato",
            width=620,
        )
        self._ws = ws
        self._contact = contact
        self.name = text_field(120, "Nome", "Nome completo ou razão social")
        self.roles = {role: chip(label) for role, label in ROLE_LABELS.items()}
        roles_row = QWidget()
        roles_layout = QHBoxLayout(roles_row)
        roles_layout.setContentsMargins(0, 0, 0, 0)
        roles_layout.setSpacing(8)
        for button in self.roles.values():
            roles_layout.addWidget(button)
        roles_layout.addStretch(1)
        self.person_type = combo(
            [("Pessoa física", PersonType.PF), ("Pessoa jurídica", PersonType.PJ)], "Tipo de pessoa"
        )
        self.document = text_field(18, "CPF ou CNPJ")
        self.phone = text_field(16, "Telefone", "(00) 00000-0000")
        self.email = text_field(254, "E-mail", "nome@exemplo.com")
        self.street = text_field(120, "Rua")
        self.number = text_field(20, "Número")
        self.district = text_field(60, "Bairro")
        self.city = text_field(60, "Cidade")
        self.state = text_field(2, "UF", "SP")
        self.zip_code = text_field(9, "CEP", "00000-000")
        self.notes = notes_field(1000, "Observações")
        self.notes.setPlaceholderText("Informações administrativas (nunca clínicas).")

        self.add_banner(LGPD_HINT)
        self.add_section("IDENTIFICAÇÃO")
        self.add_row(Field("Nome", self.name, "name", required=True))
        self.add_row(Field("Tipo de contato", roles_row, "roles", required=True))
        self.document_row = self.add_row(
            Field("Pessoa", self.person_type, "person_type", stretch=1),
            Field("CPF", self.document, "document", stretch=1),
        )
        self.add_section("CONTATO")
        self.add_row(
            Field("Telefone", self.phone, "phone", stretch=2),
            Field("E-mail", self.email, "email", stretch=3),
        )
        self.add_section("ENDEREÇO")
        self.address_toggle = QPushButton("+ Adicionar endereço (opcional)")
        self.address_toggle.setObjectName("ghost")
        self.add_widget(self.address_toggle)
        self.address_rows = [
            self.add_row(
                Field("Rua", self.street, "street", stretch=4),
                Field("Número", self.number, "number", stretch=1),
            ),
            self.add_row(
                Field("Bairro", self.district, "district", stretch=3),
                Field("Cidade", self.city, "city", stretch=3),
                Field("UF", self.state, "state", stretch=1),
                Field("CEP", self.zip_code, "zip_code", stretch=2),
            ),
        ]
        self.add_section("OBSERVAÇÕES")
        self.add_row(Field("Observações", self.notes, "notes"))

        self.person_type.currentIndexChanged.connect(self._update_document_label)
        self.address_toggle.clicked.connect(lambda: self._show_address(True))
        if contact:
            self._load(contact)
        else:
            self.roles[ContactRole.PATIENT].setChecked(True)
        self._show_address(bool(contact and (contact.street or contact.city or contact.zip_code)))
        self._update_document_label()
        self.on_save(self._save)

    def _show_address(self, visible: bool) -> None:
        self.address_toggle.setVisible(not visible)
        for row in self.address_rows:
            row.setVisible(visible)
        self.adjustSize()

    def _update_document_label(self) -> None:
        is_pf = self.person_type.value() is PersonType.PF
        caption = self.document_row.findChildren(QLabel)[1]
        caption.setText("CPF" if is_pf else "CNPJ")
        self.document.setPlaceholderText("000.000.000-00" if is_pf else "00.000.000/0000-00")

    def _load(self, c: Contact) -> None:
        self.name.setText(c.name)
        for role, button in self.roles.items():
            button.setChecked(role in c.roles)
        select_data(self.person_type, c.person_type)
        self.document.setText(format_document(c.document))
        self.phone.setText(format_phone(c.phone))
        self.email.setText(c.email)
        self.street.setText(c.street)
        self.number.setText(c.number)
        self.district.setText(c.district)
        self.city.setText(c.city)
        self.state.setText(c.state)
        self.zip_code.setText(c.zip_code)
        self.notes.setPlainText(c.notes)

    def _save(self) -> Contact:
        roles = frozenset(role for role, button in self.roles.items() if button.isChecked())
        if not roles:
            raise ValidationError("roles", "Escolha ao menos um tipo de contato.")
        base = self._contact or Contact(NEW_ID, self.name.text() or "?")
        contact = replace(
            base,
            name=self.name.text(),
            roles=roles,
            person_type=self.person_type.value(),
            document=self.document.text(),
            phone=self.phone.text(),
            email=self.email.text(),
            street=self.street.text(),
            number=self.number.text(),
            district=self.district.text(),
            city=self.city.text(),
            state=self.state.text(),
            zip_code=self.zip_code.text(),
            notes=self.notes.toPlainText(),
        )
        return self._ws.catalog.save_contact(contact)


class ContactsPage(QWidget):
    def __init__(self, ws: Workspace) -> None:
        super().__init__()
        self._ws = ws
        columns = [
            Column("Nome", lambda c: c.name, stretch=True),
            Column("Tipo", lambda c: ", ".join(ROLE_LABELS[r] for r in sorted(c.roles))),
            Column("CPF / CNPJ", lambda c: format_document(c.document)),
            Column("Telefone", lambda c: format_phone(c.phone)),
            Column("Cidade/UF", lambda c: "/".join(p for p in (c.city, c.state) if p)),
        ]
        self.model = RowsTableModel(columns, self)
        self.table = make_table(self.model, columns)
        self.search = search_field("Buscar contato pelo nome", "Buscar contato")
        self.new_button = QPushButton("+ Novo contato")
        self.new_button.setObjectName("primary")
        self.edit_button = QPushButton("Editar")
        self.delete_button = QPushButton("Excluir")
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        bar = QHBoxLayout()
        for widget in (self.new_button, self.edit_button, self.delete_button):
            bar.addWidget(widget)
        bar.addStretch(1)
        bar.addWidget(self.search)
        layout = QVBoxLayout(self)
        layout.addWidget(plain_label("Contatos", "title"))
        layout.addWidget(plain_label(LGPD_HINT, "muted"))
        layout.addLayout(bar)
        self.panel = TablePanel(self.table, self.model, EMPTY_CONTACTS)
        layout.addWidget(self.panel)
        self.new_button.clicked.connect(lambda: self._open(None))
        self.edit_button.clicked.connect(self._edit_selected)
        self.table.doubleClicked.connect(self._edit_selected)
        self.delete_button.clicked.connect(self._delete_selected)
        self.search.textChanged.connect(lambda _: self._debounce.start())
        self._debounce.timeout.connect(self.reload)
        self.reload()

    def reload(self) -> None:
        text = self.search.text().strip()
        self.panel.set_empty_text(
            f"Nenhum contato encontrado para “{text}”." if text else EMPTY_CONTACTS
        )
        self.model.set_rows(self._ws.catalog.search_contacts(text))

    def _selected(self) -> Contact | None:
        rows = selected_rows(self.table)
        return self.model.row_at(rows[0]) if rows else None

    def _open(self, contact: Contact | None) -> None:
        if ContactDialog(self._ws, contact, self).exec():
            self.reload()

    def _edit_selected(self) -> None:
        contact = self._selected()
        if contact:
            self._open(self._ws.catalog.get_contact(contact.id))

    def _delete_selected(self) -> None:
        contact = self._selected()
        if contact is None:
            return
        if not confirm(self, f'Excluir o contato "{contact.name}"?', accept="Excluir"):
            return
        try:
            self._ws.catalog.delete_contact(contact.id)
        except Exception as error:  # noqa: BLE001 - mensagem amigável + log sem dados
            show_error(self, error, "contact.delete")
        self.reload()
