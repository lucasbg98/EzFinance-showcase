"""Inicialização da interface."""

from __future__ import annotations

import sys

from PySide6.QtCore import QLocale
from PySide6.QtWidgets import QApplication

from appfin import __version__
from appfin.bootstrap import AppConfig, build_app
from appfin.infrastructure.app_logging import configure_logging, log_event
from appfin.infrastructure.paths import default_update_cache
from appfin.infrastructure.updater import Updater
from appfin.presentation.main_window import APP_TITLE, MainWindow
from appfin.presentation.single_instance import SingleInstance
from appfin.presentation.theme.style import apply_theme


def run(config: AppConfig | None = None) -> int:
    config = config or AppConfig()
    configure_logging(config.paths.log_dir)
    QLocale.setDefault(QLocale(QLocale.Language.Portuguese, QLocale.Country.Brazil))

    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setApplicationVersion(__version__)
    apply_theme(app)

    instance = SingleInstance(config.paths.lock_file)
    if not instance.acquire():
        log_event("app.second_instance", outcome="cancelled")
        return 0

    log_event("app.start", outcome="ok", app_version=__version__)
    updater = Updater.from_environment(default_update_cache())
    container = build_app(config)
    window = MainWindow(
        container.session, config.auto_lock_minutes, container.workspace_factory, updater
    )
    instance.activation_requested.connect(window.bring_to_front)
    window.show()
    window.register_native_events()
    try:
        return app.exec()
    finally:
        window.lock("app_exit")
        instance.release()
        log_event("app.stop", outcome="ok")
