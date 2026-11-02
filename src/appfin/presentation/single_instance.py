"""Instância única: só um processo abre o banco; o segundo apenas traz o primeiro para frente."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_SERVER_NAME = "appfin-single-instance-v1"
_ACTIVATE = b"activate"
_TIMEOUT_MS = 1000


class SingleInstance(QObject):
    activation_requested = Signal()

    def __init__(self, lock_path: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = QLockFile(str(lock_path))
        self._lock.setStaleLockTime(0)
        self._server: QLocalServer | None = None

    def acquire(self) -> bool:
        """True se esta é a instância principal. Caso contrário, avisa a principal."""
        if not self._lock.tryLock(100):
            _notify_running_instance()
            return False
        QLocalServer.removeServer(_SERVER_NAME)
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._on_connection)
        self._server.listen(_SERVER_NAME)
        return True

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
        self._lock.unlock()

    def _on_connection(self) -> None:
        if self._server is None:
            return
        socket = self._server.nextPendingConnection()
        if socket.waitForReadyRead(_TIMEOUT_MS) and socket.readAll().data() == _ACTIVATE:
            self.activation_requested.emit()
        socket.disconnectFromServer()


def _notify_running_instance() -> None:
    socket = QLocalSocket()
    socket.connectToServer(_SERVER_NAME)
    if socket.waitForConnected(_TIMEOUT_MS):
        socket.write(_ACTIVATE)
        socket.waitForBytesWritten(_TIMEOUT_MS)
        socket.disconnectFromServer()
