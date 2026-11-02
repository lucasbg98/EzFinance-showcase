"""Bloqueio automático (docs/PROJETO.md §7.4, decisão D2).

- Inatividade: qualquer tecla, clique, rolagem ou movimento do mouse reinicia o contador
  (padrão 3 min).
- Windows: bloqueio da sessão (Win+L) e suspensão/hibernação bloqueiam o app imediatamente.
"""

from __future__ import annotations

import ctypes
import sys
from typing import Final

from PySide6.QtCore import (
    QAbstractNativeEventFilter,
    QByteArray,
    QCoreApplication,
    QEvent,
    QObject,
    QTimer,
    Signal,
)

DEFAULT_AUTO_LOCK_MINUTES: Final = 3
_ACTIVITY_EVENTS: Final = frozenset(
    {
        QEvent.Type.KeyPress,
        QEvent.Type.MouseButtonPress,
        QEvent.Type.MouseMove,
        QEvent.Type.Wheel,
        QEvent.Type.TouchBegin,
    }
)
# Mensagens do Windows (winuser.h / wtsapi32.h)
_WM_WTSSESSION_CHANGE: Final = 0x02B1
_WTS_SESSION_LOCK: Final = 0x7
_WM_POWERBROADCAST: Final = 0x0218
_PBT_APMSUSPEND: Final = 0x4
_NOTIFY_FOR_THIS_SESSION: Final = 0


class InactivityLock(QObject):
    """Emite ``lock_requested`` após ``minutes`` sem atividade da usuária."""

    lock_requested = Signal(str)

    def __init__(self, minutes: float = DEFAULT_AUTO_LOCK_MINUTES, parent: QObject | None = None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(int(minutes * 60_000))
        self._timer.timeout.connect(lambda: self.lock_requested.emit("inactivity"))

    def start(self) -> None:
        app = QCoreApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self._timer.start()

    def stop(self) -> None:
        app = QCoreApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._timer.stop()

    @property
    def is_active(self) -> bool:
        return self._timer.isActive()

    def eventFilter(self, _watched: QObject, event: QEvent) -> bool:  # noqa: N802 - API Qt
        if event.type() in _ACTIVITY_EVENTS and self._timer.isActive():
            self._timer.start()
        return False


class WindowsSessionWatcher(QObject, QAbstractNativeEventFilter):
    """Detecta bloqueio da sessão do Windows e suspensão do computador."""

    lock_requested = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        QObject.__init__(self, parent)
        QAbstractNativeEventFilter.__init__(self)

    def register(self, window_handle: int) -> None:
        if sys.platform != "win32":
            return
        app = QCoreApplication.instance()
        if app is not None:
            app.installNativeEventFilter(self)
        ctypes.windll.wtsapi32.WTSRegisterSessionNotification(
            window_handle, _NOTIFY_FOR_THIS_SESSION
        )

    def nativeEventFilter(  # noqa: N802 - API Qt
        self, event_type: QByteArray | bytes | bytearray | memoryview[int], message: int
    ) -> tuple[bool, int]:
        name = event_type.data() if isinstance(event_type, QByteArray) else bytes(event_type)
        if name != b"windows_generic_MSG" or not message:
            return False, 0
        from ctypes import wintypes

        msg = wintypes.MSG.from_address(int(message))
        if msg.message == _WM_WTSSESSION_CHANGE and msg.wParam == _WTS_SESSION_LOCK:
            self.lock_requested.emit("windows_lock")
        elif msg.message == _WM_POWERBROADCAST and msg.wParam == _PBT_APMSUSPEND:
            self.lock_requested.emit("suspend")
        return False, 0
