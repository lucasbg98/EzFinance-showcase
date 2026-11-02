"""Design tokens e folha de estilo (QSS). Tema claro no MVP; escuro na fase 2."""

from __future__ import annotations

from importlib import resources
from typing import Final

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

TOKENS: Final = {
    "primary": "#0F766E",
    "primary_hover": "#115E59",
    "on_primary": "#FFFFFF",
    "background": "#F6F8F8",
    "surface": "#FFFFFF",
    "text": "#1F2933",
    "text_muted": "#52606D",
    "border": "#CBD2D9",
    "danger": "#B42318",
    "alternate": "#F7F9F9",
    "selection": "#D7ECE9",
    "info_bg": "#EAF5F3",
    "info_border": "#B9DCD6",
    "success": "#027A48",
    "radius": "6px",
    "font_size": "10pt",
}


def _icon(name: str) -> str:
    """Caminho do ícone SVG embutido, no formato aceito pelo QSS (barras normais)."""
    path = resources.files("appfin.resources").joinpath("icons", name)
    return str(path).replace("\\", "/")


def build_stylesheet() -> str:
    t = TOKENS
    check, chevron = _icon("check.svg"), _icon("chevron-down.svg")
    return f"""
    QWidget {{ font-size: {t["font_size"]}; color: {t["text"]}; }}
    QMainWindow, QStackedWidget > QWidget {{ background: {t["background"]}; }}
    QFrame#card {{
        background: {t["surface"]}; border: 1px solid {t["border"]}; border-radius: 10px;
    }}
    QLabel#title {{ font-size: 16pt; font-weight: 600; }}
    QLabel#muted {{ color: {t["text_muted"]}; }}
    QLabel#error {{ color: {t["danger"]}; }}
    QLabel#ok {{ color: {t["success"]}; }}
    QLabel#recoveryKey {{
        font-family: "Cascadia Mono", "Consolas", monospace; font-size: 14pt;
        background: {t["background"]}; border: 1px dashed {t["border"]};
        border-radius: {t["radius"]}; padding: 12px;
    }}
    QLineEdit {{
        background: {t["surface"]}; border: 1px solid {t["border"]};
        border-radius: {t["radius"]}; padding: 6px 8px;
    }}
    QLineEdit:focus {{ border: 2px solid {t["primary"]}; }}
    QPushButton {{
        border: 1px solid {t["border"]}; border-radius: {t["radius"]};
        padding: 7px 16px; background: {t["surface"]};
    }}
    QPushButton#primary {{
        background: {t["primary"]}; color: {t["on_primary"]}; border: none; font-weight: 600;
    }}
    QPushButton#primary:hover {{ background: {t["primary_hover"]}; }}
    QPushButton:disabled {{ color: {t["text_muted"]}; background: {t["background"]}; }}
    QToolBar {{
        background: {t["surface"]}; border: none; border-bottom: 1px solid {t["border"]};
        spacing: 6px; padding: 4px 8px;
    }}
    QToolBar QToolButton {{ padding: 5px 10px; border-radius: {t["radius"]}; }}
    QToolBar QToolButton:hover {{ background: {t["background"]}; }}
    QToolBar QToolButton:checked {{ background: {t["selection"]}; color: {t["text"]}; }}
    QComboBox, QDateEdit {{
        background: {t["surface"]}; border: 1px solid {t["border"]};
        border-radius: {t["radius"]}; padding: 5px 8px; min-height: 22px;
    }}
    QPlainTextEdit {{
        background: {t["surface"]}; border: 1px solid {t["border"]};
        border-radius: {t["radius"]}; padding: 4px 6px; min-height: 64px;
    }}
    QComboBox:focus, QDateEdit:focus, QPlainTextEdit:focus {{ border: 2px solid {t["primary"]}; }}
    QListWidget#sideMenu {{
        background: {t["surface"]}; border: none; border-right: 1px solid {t["border"]};
        padding: 8px 0; font-size: 11pt; outline: 0;
    }}
    QListWidget#sideMenu::item {{ padding: 9px 16px; }}
    QListWidget#sideMenu::item:selected {{
        background: {t["background"]}; color: {t["primary"]}; font-weight: 600;
        border-left: 3px solid {t["primary"]};
    }}
    QLabel#monthLabel {{ font-size: 12pt; font-weight: 600; }}
    QTableView, QTreeWidget {{
        background: {t["surface"]}; alternate-background-color: {t["alternate"]};
        border: 1px solid {t["border"]}; border-radius: {t["radius"]};
        gridline-color: {t["border"]}; outline: 0;
        selection-background-color: {t["selection"]}; selection-color: {t["text"]};
    }}
    QHeaderView::section {{
        background: {t["background"]}; padding: 6px; border: none;
        border-bottom: 1px solid {t["border"]}; font-weight: 600;
    }}
    QCheckBox::indicator {{
        width: 15px; height: 15px; border: 1px solid {t["text_muted"]};
        border-radius: 3px; background: {t["surface"]};
    }}
    QCheckBox::indicator:checked {{ background: {t["primary"]}; border-color: {t["primary"]}; }}
    QCheckBox:focus {{ color: {t["primary"]}; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    QComboBox::down-arrow {{ image: url({chevron}); width: 14px; height: 14px; }}
    QDateEdit::drop-down {{ border: none; width: 26px; }}
    QDateEdit::down-arrow {{ image: url({chevron}); width: 14px; height: 14px; }}
    QCheckBox::indicator:checked {{ image: url({check}); }}
    QLineEdit#search {{ min-width: 280px; }}
    QLineEdit[invalid="true"], QLineEdit[invalid="true"]:focus,
    QComboBox[invalid="true"], QComboBox[invalid="true"]:focus,
    QDateEdit[invalid="true"], QDateEdit[invalid="true"]:focus,
    QPlainTextEdit[invalid="true"], QPlainTextEdit[invalid="true"]:focus {{
        border: 2px solid {t["danger"]}; background: #FEF3F2;
    }}

    QDialog#formDialog {{ background: {t["surface"]}; }}
    QFrame#dialogHeader {{ background: {t["surface"]}; border-bottom: 1px solid {t["border"]}; }}
    QLabel#dialogTitle {{ font-size: 14pt; font-weight: 600; }}
    QFrame#dialogFooter {{ background: {t["background"]}; border-top: 1px solid {t["border"]}; }}
    QLabel#sectionTitle {{
        font-size: 9pt; font-weight: 700; color: {t["primary"]}; letter-spacing: 0.5px;
        padding-top: 6px;
    }}
    QLabel#fieldLabel {{ font-size: 9pt; font-weight: 600; color: {t["text_muted"]}; }}
    QFrame#infoBanner {{
        background: {t["info_bg"]}; border: 1px solid {t["info_border"]};
        border-radius: {t["radius"]};
    }}
    QLabel#bannerText {{ color: {t["text"]}; }}
    QPushButton#chip {{
        border: 1px solid {t["border"]}; border-radius: 15px; padding: 5px 14px;
        background: {t["surface"]}; color: {t["text"]};
    }}
    QPushButton#chip:hover {{ border-color: {t["primary"]}; }}
    QPushButton#chip:checked {{
        background: {t["selection"]}; border: 1px solid {t["primary"]};
        color: {t["primary_hover"]}; font-weight: 600;
    }}
    QPushButton#ghost {{
        border: 1px dashed {t["border"]}; background: transparent; color: {t["primary"]};
        text-align: left; padding: 7px 12px;
    }}
    QPushButton#ghost:hover {{ border-color: {t["primary"]}; }}
    QLabel#emptyState {{ color: {t["text_muted"]}; font-size: 11pt; }}
    QPushButton#link {{
        border: none; background: transparent; color: {t["primary"]}; text-decoration: underline;
        padding: 2px;
    }}
    """


def apply_theme(app: QApplication) -> None:
    """Tema claro **explícito**: o app não herda o modo escuro do Windows (que deixava tabelas e
    barras ilegíveis com o estilo Fusion). O tema escuro próprio entra na fase 2.
    """
    t = TOKENS
    app.setStyle("Fusion")
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: t["background"],
        QPalette.ColorRole.WindowText: t["text"],
        QPalette.ColorRole.Base: t["surface"],
        QPalette.ColorRole.AlternateBase: t["alternate"],
        QPalette.ColorRole.Text: t["text"],
        QPalette.ColorRole.Button: t["surface"],
        QPalette.ColorRole.ButtonText: t["text"],
        QPalette.ColorRole.Highlight: t["selection"],
        QPalette.ColorRole.HighlightedText: t["text"],
        QPalette.ColorRole.ToolTipBase: t["surface"],
        QPalette.ColorRole.ToolTipText: t["text"],
        QPalette.ColorRole.PlaceholderText: t["text_muted"],
        QPalette.ColorRole.Link: t["primary"],
    }
    for role, value in colors.items():
        palette.setColor(role, QColor(value))
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.WindowText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(t["text_muted"]))
    app.setPalette(palette)
    app.setStyleSheet(build_stylesheet())
