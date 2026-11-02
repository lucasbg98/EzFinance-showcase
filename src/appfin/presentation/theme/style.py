"""Design tokens e folha de estilo (QSS). Tema claro no MVP; escuro na fase 2."""

from __future__ import annotations

from typing import Final

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
    QPushButton#link {{
        border: none; background: transparent; color: {t["primary"]}; text-decoration: underline;
        padding: 2px;
    }}
    """
