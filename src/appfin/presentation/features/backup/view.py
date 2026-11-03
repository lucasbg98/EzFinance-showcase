"""Backup e segurança: backup cifrado, restauração e nova chave de recuperação.

- Backups são sempre cifrados (diferente das exportações em CSV/Excel/PDF).
- Restaurar em duas etapas: "Verificar backup" (decifra e confere numa área separada, sem mexer
  em nada) e só então "Restaurar" (troca os dados; antes, faz backup do estado atual).
- Nova chave de recuperação: pede a senha mestra de novo; a chave nova só passa a valer depois de
  confirmada (a antiga continua valendo até lá).
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from appfin.application.backup import BackupStatus
from appfin.application.ports import (
    BackupFileError,
    BackupManifest,
    InvalidCredentialError,
)
from appfin.br_format import format_date
from appfin.infrastructure.app_logging import log_exception
from appfin.infrastructure.backup.retention import EXTENSION
from appfin.presentation.features.lock.views import RecoveryKeyView
from appfin.presentation.shared.ui.feedback import show_error, show_info
from appfin.presentation.shared.ui.forms import Field, FormDialog, combo, plain_label
from appfin.presentation.shared.worker import run_in_background
from appfin.presentation.workspace import Workspace

Runner = Callable[[Callable[[], Any], Callable[[Any], None], Callable[[Exception], None]], None]
Prepare = Callable[[Path, str | None, str | None], BackupManifest]

COUNT_LABELS = {
    "financial_transaction": "lançamento(s)",
    "contact": "contato(s)",
    "account": "conta(s)",
    "category": "categoria(s)",
    "receipt": "recibo(s)",
}

# Ganchos substituíveis nos testes (evitam abrir diálogos do sistema).
ask_backup_file: Callable[[QWidget], str] = lambda parent: QFileDialog.getOpenFileName(  # noqa: E731
    parent, "Escolher backup", "", f"Backup do AppFinanceiro (*{EXTENSION})"
)[0]
ask_folder: Callable[[QWidget], str] = lambda parent: QFileDialog.getExistingDirectory(  # noqa: E731
    parent, "Pasta extra para os backups"
)
open_folder: Callable[[Path], object] = lambda path: QDesktopServices.openUrl(  # noqa: E731
    QUrl.fromLocalFile(str(path))
)


def _qt_runner(parent: QWidget) -> Runner:
    def run(
        work: Callable[[], Any], ok: Callable[[Any], None], fail: Callable[[Exception], None]
    ) -> None:
        run_in_background(work, ok, fail, parent=parent)

    return run


def format_moment(moment: Any) -> str:
    local = moment.astimezone() if moment.tzinfo else moment
    return f"{format_date(local.date())} às {local:%H:%M}"


def manifest_summary(manifest: BackupManifest) -> str:
    parts = [
        f"{manifest.counts[name]} {label}"
        for name, label in COUNT_LABELS.items()
        if name in manifest.counts
    ]
    return (
        f"Backup de {format_moment(manifest.created_at)} (versão {manifest.app_version}). "
        f"Contém: {', '.join(parts)}."
    )


# ---------------------------------------------------------------------- restaurar
class OpenWith(StrEnum):
    MASTER = "master"  # senha mestra da época do backup
    RECOVERY_KEY = "recovery_key"


class RestoreDialog(FormDialog):
    """Escolher o arquivo, informar a senha/chave da época, verificar e confirmar."""

    def __init__(
        self,
        prepare: Prepare,
        discard: Callable[[], None],
        parent: QWidget | None,
        *,
        replaces_data: bool,
        runner: Runner | None = None,
    ) -> None:
        super().__init__(
            "Restaurar backup",
            parent,
            subtitle="Recupera os dados a partir de um arquivo de backup do AppFinanceiro.",
            save_text="Verificar backup",
            width=600,
        )
        self._prepare = prepare
        self._discard = discard
        self._runner = runner or _qt_runner(self)
        self._prepared = False
        self._busy = False
        self.file = QLineEdit()
        self.file.setReadOnly(True)
        self.file.setPlaceholderText(f"Nenhum arquivo escolhido (*{EXTENSION})")
        self.file.setAccessibleName("Arquivo de backup")
        self.choose = QPushButton("Escolher arquivo…")
        file_row = QWidget()
        row = QHBoxLayout(file_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.file, 1)
        row.addWidget(self.choose)
        self.mode = combo(
            [
                ("Senha mestra da época do backup", OpenWith.MASTER),
                ("Chave de recuperação", OpenWith.RECOVERY_KEY),
            ],
            "Como abrir o backup",
        )
        self.secret = QLineEdit()
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret.setAccessibleName("Senha mestra ou chave de recuperação")
        self.add_row(Field("Arquivo de backup", file_row, "file", required=True))
        self.add_row(
            Field("Abrir com", self.mode, "mode", stretch=2),
            Field("Senha / chave", self.secret, "secret", required=True, stretch=3),
        )
        self.preview = plain_label("", "")
        self.preview.setVisible(False)
        self.add_widget(self.preview)
        warning = (
            "Os dados atuais deste computador serão SUBSTITUÍDOS pelos do backup. Antes disso, "
            "o app faz um backup do estado atual. Depois, o app abre com a senha mestra da época "
            "do backup."
            if replaces_data
            else "Depois de restaurar, o app abre com a senha mestra da época do backup (ou com a "
            "chave de recuperação daquela época)."
        )
        self.warning = self.add_banner(warning)
        self.warning.setVisible(False)

        self.choose.clicked.connect(self._choose)
        self.mode.currentIndexChanged.connect(lambda _i: self._mode_changed())
        self.secret.textChanged.connect(lambda _t: self._reset_preview())
        self.secret.returnPressed.connect(self._on_save)

    # ------------------------------------------------------------------ ações
    def set_file(self, path: str) -> None:
        self.file.setText(path)
        self._reset_preview()

    def _choose(self) -> None:
        chosen = ask_backup_file(self)
        if chosen:
            self.set_file(chosen)

    def _mode_changed(self) -> None:
        recovery = self.mode.value() is OpenWith.RECOVERY_KEY
        self.secret.clear()
        self.secret.setEchoMode(
            QLineEdit.EchoMode.Normal if recovery else QLineEdit.EchoMode.Password
        )
        self.secret.setPlaceholderText("XXXX-XXXX-…" if recovery else "")

    def _on_save(self) -> None:
        if self._busy:
            return
        if self._prepared:
            self.accept()
            return
        self.error.setText("")
        self.clear_invalid()
        if not self.file.text():
            self.error.setText("Escolha o arquivo de backup.")
            self.mark_invalid("file")
            return
        if not self.secret.text().strip():
            self.error.setText("Digite a senha mestra ou a chave de recuperação.")
            self.mark_invalid("secret")
            return
        path = Path(self.file.text())
        secret = self.secret.text()
        recovery = self.mode.value() is OpenWith.RECOVERY_KEY
        self._set_busy(True)
        self._runner(
            lambda: self._prepare(path, None if recovery else secret, secret if recovery else None),
            self._on_prepared,
            self._on_failed,
        )

    def _on_prepared(self, manifest: Any) -> None:
        self._set_busy(False)
        self._prepared = True
        self.preview.setText(manifest_summary(manifest))
        self.preview.setVisible(True)
        self.warning.setVisible(True)
        self.save_button.setText("Restaurar agora")
        self.fit_to_content()

    def _on_failed(self, error: Exception) -> None:
        self._set_busy(False)
        if isinstance(error, InvalidCredentialError):
            recovery = self.mode.value() is OpenWith.RECOVERY_KEY
            self.error.setText(
                "Chave de recuperação incorreta para este backup."
                if recovery
                else "Senha incorreta para este backup (use a senha da época em que ele foi feito)."
            )
            self.mark_invalid("secret")
        elif isinstance(error, BackupFileError):
            self.error.setText(str(error))
        else:
            log_exception("backup.restore_prepare", error, error_code="E-RESTORE")
            self.error.setText("Não foi possível verificar o backup. (código E-RESTORE)")

    def _reset_preview(self) -> None:
        if self._prepared:
            self._discard()
            self._prepared = False
        self.preview.setVisible(False)
        self.warning.setVisible(False)
        self.save_button.setText("Verificar backup")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.save_button.setEnabled(not busy)
        self.choose.setEnabled(not busy)
        if busy:
            self.save_button.setText("Verificando… aguarde")

    def reject(self) -> None:
        if self._busy:
            return
        if self._prepared:
            self._discard()
            self._prepared = False
        super().reject()


# ---------------------------------------------------------------------- nova chave
class NewRecoveryKeyDialog(QDialog):
    """Senha mestra → nova chave exibida uma vez → confirmação → só então passa a valer."""

    def __init__(self, ws: Workspace, parent: QWidget | None, runner: Runner | None = None):
        super().__init__(parent)
        self.setObjectName("formDialog")
        self.setWindowTitle("Nova chave de recuperação")
        self.setModal(True)
        self.setMinimumWidth(620)
        self._ws = ws
        self._runner = runner or _qt_runner(self)
        self._busy = False
        self._confirmed = False

        self.ask = QWidget()
        ask_layout = QVBoxLayout(self.ask)
        ask_layout.setContentsMargins(24, 20, 24, 20)
        ask_layout.setSpacing(10)
        ask_layout.addWidget(plain_label("Gerar nova chave de recuperação", "dialogTitle"))
        ask_layout.addWidget(
            plain_label(
                "Use se a chave atual foi perdida ou pode ter sido vista por outra pessoa. "
                "A chave antiga deixa de abrir este computador assim que você confirmar a nova. "
                "Backups feitos antes continuam abrindo com a chave antiga (ou com a senha da "
                "época).",
                "muted",
            )
        )
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Senha mestra atual")
        self.password.setAccessibleName("Senha mestra atual")
        self.message = plain_label("", "error")
        self.generate = QPushButton("Gerar nova chave")
        self.generate.setObjectName("primary")
        cancel = QPushButton("Cancelar")
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.generate)
        ask_layout.addWidget(self.password)
        ask_layout.addWidget(self.message)
        ask_layout.addLayout(buttons)

        self.key_view = RecoveryKeyView()
        self.key_view.setVisible(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.ask)
        layout.addWidget(self.key_view)

        cancel.clicked.connect(self.reject)
        self.generate.clicked.connect(self._generate)
        self.password.returnPressed.connect(self._generate)
        self.key_view.confirmed.connect(self._confirm)
        ws.app.set_auto_lock_paused(True)

    def _generate(self) -> None:
        if self._busy:
            return
        if not self.password.text():
            self.message.setText("Digite a senha mestra.")
            return
        self.message.setText("")
        password = self.password.text()
        self._busy = True
        self.generate.setEnabled(False)
        self.generate.setText("Conferindo… aguarde")
        self._runner(
            lambda: self._ws.app.prepare_recovery_key(password), self._on_key, self._on_error
        )

    def _on_key(self, recovery_key: Any) -> None:
        self._busy = False
        self.password.clear()
        self.ask.setVisible(False)
        self.key_view.show_key(str(recovery_key))
        self.key_view.setVisible(True)
        self.adjustSize()

    def _on_error(self, error: Exception) -> None:
        self._busy = False
        self.generate.setEnabled(True)
        self.generate.setText("Gerar nova chave")
        if isinstance(error, InvalidCredentialError):
            self.message.setText("Senha incorreta.")
            return
        log_exception("vault.recovery_key", error, error_code="E-RECOVERY-KEY")
        self.message.setText("Não foi possível gerar a chave. (código E-RECOVERY-KEY)")

    def _confirm(self) -> None:
        try:
            self._ws.app.confirm_recovery_key()
        except Exception as error:  # noqa: BLE001 - mensagem amigável + log sem dados
            show_error(self, error, "vault.recovery_key")
            self.reject()
            return
        self._confirmed = True
        self.accept()

    def done(self, result: int) -> None:
        if self._busy:
            return
        self.key_view.clear()
        if not self._confirmed:
            self._ws.app.cancel_recovery_key()
        self._ws.app.set_auto_lock_paused(False)
        super().done(result)


# ---------------------------------------------------------------------- página
def _panel(title: str, text: str, *widgets: QWidget) -> QFrame:
    frame = QFrame()
    frame.setObjectName("panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 16)
    layout.setSpacing(8)
    layout.addWidget(plain_label(title, "panelTitle"))
    layout.addWidget(plain_label(text, "muted"))
    for widget in widgets:
        layout.addWidget(widget)
    return frame


def _buttons(*buttons: QPushButton) -> QWidget:
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 4, 0, 0)
    for button in buttons:
        row.addWidget(button)
    row.addStretch(1)
    return holder


class BackupPage(QWidget):
    def __init__(self, ws: Workspace) -> None:
        super().__init__()
        self._ws = ws
        self.status_text = plain_label("", "")
        self.status_text.setTextFormat(Qt.TextFormat.PlainText)
        self.folder_text = plain_label("", "muted")
        self.alert = plain_label("", "error")
        self.backup_button = QPushButton("Fazer backup agora")
        self.backup_button.setObjectName("primary")
        self.folder_button = QPushButton("Escolher pasta extra…")
        self.remove_folder_button = QPushButton("Remover pasta extra")
        self.open_button = QPushButton("Abrir pasta dos backups")
        self.restore_button = QPushButton("Restaurar de um backup…")
        self.recovery_button = QPushButton("Gerar nova chave de recuperação…")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(plain_label("Backup e segurança", "title"))
        layout.addWidget(
            plain_label(
                "Backups cifrados dos dados do consultório e a chave de recuperação.", "muted"
            )
        )
        layout.addWidget(
            _panel(
                "Backups",
                "Feitos automaticamente a cada 24 horas de uso e ao fechar o app, sempre "
                "cifrados. Ficam os 10 mais recentes e um de cada dia (7 dias), "
                "semana (4) e mês (12).",
                self.status_text,
                self.folder_text,
                self.alert,
                _buttons(
                    self.backup_button,
                    self.folder_button,
                    self.remove_folder_button,
                    self.open_button,
                ),
            )
        )
        layout.addWidget(
            _panel(
                "Restaurar",
                "Para voltar os dados de um backup, inclusive em outro computador. Você vai "
                "precisar da senha mestra (ou da chave de recuperação) da época do backup.",
                _buttons(self.restore_button),
            )
        )
        layout.addWidget(
            _panel(
                "Chave de recuperação",
                "Se a chave foi perdida ou outra pessoa pode ter visto, gere uma nova. "
                "Guarde-a em papel, fora do computador.",
                _buttons(self.recovery_button),
            )
        )
        layout.addStretch(1)

        self.backup_button.clicked.connect(self.backup_now)
        self.folder_button.clicked.connect(self.choose_folder)
        self.remove_folder_button.clicked.connect(lambda: self._set_folder(None))
        self.open_button.clicked.connect(lambda: open_folder(self._status.local_dir))
        self.restore_button.clicked.connect(self.restore)
        self.recovery_button.clicked.connect(self.new_recovery_key)
        self.refresh()

    def refresh(self) -> None:
        self._status: BackupStatus = self._ws.backups.status()
        status = self._status
        if status.last_success_at is None:
            self.status_text.setText("Nenhum backup feito ainda.")
        else:
            self.status_text.setText(f"Último backup: {format_moment(status.last_success_at)}.")
        if status.folder is None:
            self.folder_text.setText(
                "Pasta extra: nenhuma. Escolha uma pasta num pen drive ou no OneDrive: a cópia "
                "que fica só neste computador não protege se ele estragar ou for roubado."
            )
        else:
            self.folder_text.setText(f"Pasta extra: {status.folder}")
        self.remove_folder_button.setVisible(status.folder is not None)
        self.alert.setText(
            "O último backup não foi gravado em todas as pastas. Confira se o pen drive está "
            "conectado e faça um backup agora."
            if status.last_attempt_failed
            else ""
        )
        self.alert.setVisible(status.last_attempt_failed)

    def backup_now(self) -> None:
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            report = self._ws.backups.backup_now("manual")
        except Exception as error:  # noqa: BLE001 - mensagem amigável + log sem dados
            QGuiApplication.restoreOverrideCursor()
            self.refresh()
            show_error(self, error, "backup.create")
            return
        QGuiApplication.restoreOverrideCursor()
        self.refresh()
        if report.failed:
            show_info(
                self,
                "O backup foi feito neste computador, mas NÃO foi possível gravar na pasta extra "
                "(o pen drive está conectado?).",
            )
        else:
            show_info(self, f"Backup feito e conferido ({len(report.saved_to)} cópia(s)).")

    def choose_folder(self) -> None:
        chosen = ask_folder(self)
        if chosen:
            self._set_folder(Path(chosen))

    def _set_folder(self, folder: Path | None) -> None:
        try:
            self._ws.backups.set_folder(folder)
        except Exception as error:  # noqa: BLE001 - mensagem amigável + log sem dados
            show_error(self, error, "backup.folder")
        self.refresh()

    def restore(self) -> None:
        backups = self._ws.backups

        def prepare(path: Path, password: str | None, recovery_key: str | None) -> BackupManifest:
            return backups.prepare_restore(path, password=password, recovery_key=recovery_key)

        dialog = RestoreDialog(prepare, self._discard_restore, self, replaces_data=True)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._ws.app.apply_restore()

    def _discard_restore(self) -> None:
        self._ws.app.discard_restore()

    def new_recovery_key(self) -> None:
        dialog = NewRecoveryKeyDialog(self._ws, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            show_info(
                self,
                "Nova chave de recuperação ativada. A anterior não abre mais este computador.",
            )
