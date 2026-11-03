"""Telas: configuração inicial, chave de recuperação e desbloqueio.

Todo texto dinâmico é exibido como texto simples (``PlainText``) — nunca HTML.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from appfin.presentation.features.lock.view_model import LockViewModel


def _label(text: str = "", object_name: str = "") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    if object_name:
        label.setObjectName(object_name)
    return label


def _caption(text: str, buddy: QWidget) -> QLabel:
    """Rótulo acima do campo, no mesmo padrão dos formulários do app."""
    caption = _label(text, "fieldLabel")
    caption.setBuddy(buddy)
    return caption


def _password_field(placeholder: str) -> QLineEdit:
    field = QLineEdit()
    field.setEchoMode(QLineEdit.EchoMode.Password)
    field.setPlaceholderText(placeholder)
    field.setMaxLength(256)
    return field


def _card(*widgets: QWidget) -> QWidget:
    """Cartão centralizado na página."""
    page = QWidget()
    outer = QVBoxLayout(page)
    outer.addStretch(1)
    row = QHBoxLayout()
    row.addStretch(1)
    card = QFrame()
    card.setObjectName("card")
    card.setFixedWidth(520)
    inner = QVBoxLayout(card)
    inner.setContentsMargins(32, 28, 32, 28)
    inner.setSpacing(12)
    for widget in widgets:
        inner.addWidget(widget)
    row.addWidget(card)
    row.addStretch(1)
    outer.addLayout(row)
    outer.addStretch(1)
    return page


class SetupView(QWidget):
    """Criação da senha mestra (primeiro uso) ou restauração de um backup (outro computador)."""

    restore_requested = Signal()

    def __init__(self, view_model: LockViewModel) -> None:
        super().__init__()
        self._vm = view_model
        self.password = _password_field("Senha mestra")
        self.password.setAccessibleName("Senha mestra")
        self.confirmation = _password_field("Repita a senha mestra")
        self.confirmation.setAccessibleName("Confirmação da senha mestra")
        self.strength = _label("", "muted")
        self.message = _label("", "error")
        self.submit = QPushButton("Criar cofre")
        self.submit.setObjectName("primary")
        self.restore = QPushButton("Já uso o app em outro computador: restaurar um backup")

        explanation = _label(
            "Esta senha protege todos os dados do consultório. Ela não é enviada para lugar nenhum "
            "e não pode ser recuperada por ninguém. Use uma frase com 4 ou mais palavras sem "
            "relação entre si (mínimo de 12 caracteres).",
            "muted",
        )
        self.strength.setVisible(False)
        layout = QVBoxLayout(self)
        layout.addWidget(
            _card(
                _label("Bem-vinda! Crie a senha mestra", "title"),
                explanation,
                _caption("Senha mestra", self.password),
                self.password,
                self.strength,
                _caption("Repita a senha mestra", self.confirmation),
                self.confirmation,
                self.message,
                self.submit,
                self.restore,
            )
        )

        self.restore.clicked.connect(self.restore_requested)
        self.password.textChanged.connect(self._update_strength)
        self.submit.clicked.connect(self._on_submit)
        self.confirmation.returnPressed.connect(self._on_submit)
        self._vm.error.connect(self.message.setText)
        self._vm.busy_changed.connect(self._on_busy)

    def _update_strength(self, text: str) -> None:
        self.strength.setVisible(bool(text))
        if not text:
            self.strength.setText("")
            return
        assessment = self._vm.assess(text)
        detail = "" if assessment.is_acceptable else " — " + " ".join(assessment.problems)
        self.strength.setText(f"Força: {assessment.label}{detail}")

    def _on_submit(self) -> None:
        self.message.setText("")
        self._vm.create(self.password.text(), self.confirmation.text())

    def _on_busy(self, busy: bool) -> None:
        self.submit.setEnabled(not busy)
        self.submit.setText("Protegendo… aguarde" if busy else "Criar cofre")

    def clear(self) -> None:
        for field in (self.password, self.confirmation):
            field.clear()
        self.message.setText("")


class RecoveryKeyView(QWidget):
    """Mostra a chave de recuperação UMA vez e exige confirmação de que foi anotada."""

    confirmed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._last_group = ""
        self.key_label = _label("", "recoveryKey")
        self.key_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.saved = QCheckBox(
            "Anotei a chave em papel e guardei em local seguro, fora do computador."
        )
        self.last_group = QLineEdit()
        self.last_group.setPlaceholderText("Digite o último grupo da chave para confirmar")
        self.last_group.setAccessibleName("Último grupo da chave de recuperação")
        self.message = _label("", "error")
        self.submit = QPushButton("Continuar")
        self.submit.setObjectName("primary")
        self.submit.setEnabled(False)

        warning = _label(
            "Esta é a única forma de recuperar os dados se a senha mestra for esquecida. "
            "Ela aparece só agora: anote em papel (não tire foto nem salve no computador). "
            "Sem a senha e sem esta chave, os dados não podem ser recuperados por ninguém.",
            "muted",
        )
        layout = QVBoxLayout(self)
        layout.addWidget(
            _card(
                _label("Chave de recuperação", "title"),
                warning,
                self.key_label,
                self.saved,
                self.last_group,
                self.message,
                self.submit,
            )
        )
        self.saved.toggled.connect(self.submit.setEnabled)
        self.submit.clicked.connect(self._on_submit)
        self.last_group.returnPressed.connect(self._on_submit)

    def show_key(self, recovery_key: str) -> None:
        self.key_label.setText(recovery_key.replace("-", " "))
        self._last_group = recovery_key.split("-")[-1]

    def _on_submit(self) -> None:
        if not self.saved.isChecked():
            return
        if self.last_group.text().strip().upper() != self._last_group:
            self.message.setText("O grupo digitado não confere com o final da chave.")
            return
        self.clear()
        self.confirmed.emit()

    def clear(self) -> None:
        """Apaga a chave da tela assim que ela foi confirmada."""
        self.key_label.setText("")
        self._last_group = ""
        self.last_group.clear()
        self.saved.setChecked(False)
        self.message.setText("")


class UnlockView(QWidget):
    """Desbloqueio com senha mestra ou chave de recuperação."""

    def __init__(self, view_model: LockViewModel) -> None:
        super().__init__()
        self._vm = view_model
        self._using_recovery = False
        self._delay_left = 0
        self._busy = False
        self.title = _label("Desbloquear", "title")
        self.hint = _label("Digite a senha mestra para abrir os dados do consultório.", "muted")
        self.secret = _password_field("Senha mestra")
        self.secret.setAccessibleName("Senha mestra")
        self.message = _label("", "error")
        self.submit = QPushButton("Desbloquear")
        self.submit.setObjectName("primary")
        self.toggle_mode = QPushButton("Esqueci a senha — usar a chave de recuperação")
        self.toggle_mode.setObjectName("link")
        self._countdown = QTimer(self)
        self._countdown.setInterval(1000)

        layout = QVBoxLayout(self)
        layout.addWidget(
            _card(self.title, self.hint, self.secret, self.message, self.submit, self.toggle_mode)
        )
        self.submit.clicked.connect(self._on_submit)
        self.secret.returnPressed.connect(self._on_submit)
        self.toggle_mode.clicked.connect(self._toggle_mode)
        self._countdown.timeout.connect(self._tick)
        self._vm.error.connect(self.message.setText)
        self._vm.busy_changed.connect(self._on_busy)
        self._vm.delay_started.connect(self._start_delay)

    def reset(self) -> None:
        self.secret.clear()
        self.message.setText("")
        if self._using_recovery:
            self._toggle_mode()
        self.secret.setFocus()

    def _on_submit(self) -> None:
        if self._delay_left or self._busy:
            return
        self.message.setText("")
        value = self.secret.text()
        self.secret.clear()
        if self._using_recovery:
            self._vm.unlock_with_recovery_key(value)
        else:
            self._vm.unlock(value)

    def _toggle_mode(self) -> None:
        self._using_recovery = not self._using_recovery
        self.secret.clear()
        self.message.setText("")
        if self._using_recovery:
            self.hint.setText("Digite a chave de recuperação (os grupos de 4 caracteres).")
            self.secret.setPlaceholderText("Chave de recuperação")
            self.secret.setAccessibleName("Chave de recuperação")
            self.toggle_mode.setText("Voltar para a senha mestra")
        else:
            self.hint.setText("Digite a senha mestra para abrir os dados do consultório.")
            self.secret.setPlaceholderText("Senha mestra")
            self.secret.setAccessibleName("Senha mestra")
            self.toggle_mode.setText("Esqueci a senha — usar a chave de recuperação")

    def _on_busy(self, busy: bool) -> None:
        self._busy = busy
        self._refresh_button()

    def _start_delay(self, seconds: int) -> None:
        self._delay_left = seconds
        self._countdown.start()
        self._refresh_button()

    def _tick(self) -> None:
        self._delay_left = max(0, self._delay_left - 1)
        if not self._delay_left:
            self._countdown.stop()
        self._refresh_button()

    def _refresh_button(self) -> None:
        if self._busy:
            self.submit.setEnabled(False)
            self.submit.setText("Verificando… aguarde")
        elif self._delay_left:
            self.submit.setEnabled(False)
            self.submit.setText(f"Aguarde {self._delay_left} s")
        else:
            self.submit.setEnabled(True)
            self.submit.setText("Desbloquear")
