"""Design tokens e folha de estilo (QSS). Tema claro no MVP; escuro na fase 2."""

from __future__ import annotations

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
    "alternate": "#F1F5F5",
    "selection": "#CCE7E4",
    "success": "#027A48",
    "radius": "6px",
    "font_size": "10pt",
}


def build_stylesheet() -> str:
    t = TOKENS
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
    QComboBox, QDateEdit, QPlainTextEdit {{
        background: {t["surface"]}; border: 1px solid {t["border"]};
        border-radius: {t["radius"]}; padding: 5px 8px; min-height: 22px;
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
