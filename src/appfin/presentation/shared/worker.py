"""Execução em segundo plano: nada pesado roda na thread da interface (skill ``concurrency``)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Signals(QObject):
    succeeded = Signal(object)
    failed = Signal(object)


class _Task(QRunnable):
    def __init__(self, function: Callable[[], Any], signals: _Signals) -> None:
        super().__init__()
        self._function = function
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = self._function()
        except Exception as error:  # noqa: BLE001 - repassado intacto para a thread da UI tratar
            self._signals.failed.emit(error)
            return
        self._signals.succeeded.emit(result)


def run_in_background(
    function: Callable[[], Any],
    on_success: Callable[[Any], None],
    on_error: Callable[[Exception], None],
    parent: QObject,
) -> None:
    """Roda ``function`` no pool de threads e entrega o resultado na thread da UI (via signal)."""
    signals = _Signals(parent)
    signals.succeeded.connect(on_success)
    signals.failed.connect(on_error)
    signals.succeeded.connect(signals.deleteLater)
    signals.failed.connect(signals.deleteLater)
    QThreadPool.globalInstance().start(_Task(function, signals))


# Executor injetável: as telas recebem um ``Runner`` para os testes poderem rodar tudo em sequência.
Runner = Callable[[Callable[[], Any], Callable[[Any], None], Callable[[Exception], None]], None]


def qt_runner(parent: QObject) -> Runner:
    def run(
        work: Callable[[], Any], ok: Callable[[Any], None], fail: Callable[[Exception], None]
    ) -> None:
        run_in_background(work, ok, fail, parent=parent)

    return run
