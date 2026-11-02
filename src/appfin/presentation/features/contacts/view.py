"""Contatos: pacientes, fornecedores e convênios. Minimização de dados (LGPD)."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
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
    FormDialog,
    combo,
    notes_field,
    plain_label,
    select_data,
    text_field,
)
from appfin.presentation.shared.ui.table import Column, RowsTableModel, make_table, selected_rows
from appfin.presentation.workspace import Workspace

ROLE_LABELS = {
    ContactRole.PATIENT: "Paciente",
    ContactRole.SUPPLIER: "Fornecedor",
    ContactRole.INSURER: "Convênio",
    ContactRole.OTHER: "Outro",
}
LGPD_HINT = (
    "Cadastre só o necessário: de paciente, apenas o nome é obrigatório. "
    "Não registre informações clínicas (procedimentos, diagnósticos) aqui."
)


class ContactDialog(FormDialog):
    def __init__(self, ws: Workspace, contact: Contact | None, parent: QWidget) -> None:
        super().__init__("Editar contato" if contact else "Novo contato", parent)
        self._ws = ws
        self._contact = contact
        self.name = text_field(120, "Nome")
        self.roles = {role: QCheckBox(label) for role, label in ROLE_LABELS.items()}
        roles_row = QWidget()
        roles_layout = QHBoxLayout(roles_row)
        roles_layout.setContentsMargins(0, 0, 0, 0)
        for box in self.roles.values():
            roles_layout.addWidget(box)
        self.person_type = combo(
            [("Pessoa física", PersonType.PF), ("Pessoa jurídica", PersonType.PJ)], "Tipo de pessoa"
        )
        self.document = text_field(18, "CPF ou CNPJ")
        self.phone = text_field(16, "Telefone")
        self.email = text_field(254, "E-mail")
        self.street = text_field(120, "Rua")
        self.number = text_field(20, "Número")
        self.district = text_field(60, "Bairro")
        self.city = text_field(60, "Cidade")
        self.state = text_field(2, "UF")
        self.zip_code = text_field(9, "CEP")
        self.notes = notes_field(1000, "Observações")
        self.form.addRow(plain_label(LGPD_HINT, "muted"))
        self.form.addRow("Nome:*", self.name)
        self.form.addRow("Tipo de contato:*", roles_row)
        self.form.addRow("Pessoa:", self.person_type)
        self.form.addRow("CPF / CNPJ:", self.document)
        self.form.addRow("Telefone:", self.phone)
        self.form.addRow("E-mail:", self.email)
        self.form.addRow("Rua:", self.street)
        self.form.addRow("Número:", self.number)
        self.form.addRow("Bairro:", self.district)
        self.form.addRow("Cidade:", self.city)
        self.form.addRow("UF:", self.state)
        self.form.addRow("CEP:", self.zip_code)
        self.form.addRow("Observações:", self.notes)
        if contact:
            self._load(contact)
        else:
            self.roles[ContactRole.PATIENT].setChecked(True)
        self.on_save(self._save)

    def _load(self, c: Contact) -> None:
        self.name.setText(c.name)
        for role, box in self.roles.items():
            box.setChecked(role in c.roles)
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
        roles = frozenset(role for role, box in self.roles.items() if box.isChecked())
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
        self.search = text_field(100, "Buscar contato", "Buscar por nome…")
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
        layout.addWidget(self.table)
        self.new_button.clicked.connect(lambda: self._open(None))
        self.edit_button.clicked.connect(self._edit_selected)
        self.table.doubleClicked.connect(self._edit_selected)
        self.delete_button.clicked.connect(self._delete_selected)
        self.search.textChanged.connect(lambda _: self._debounce.start())
        self._debounce.timeout.connect(self.reload)
        self.reload()

    def reload(self) -> None:
        self.model.set_rows(self._ws.catalog.search_contacts(self.search.text()))

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
