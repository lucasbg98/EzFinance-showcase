# PyInstaller — build "onedir" (sem UPX), docs/PROJETO.md §11.
# Uso: uv run python packaging/release.py build   (não chamar o pyinstaller direto)
# ruff: noqa
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH é injetado pelo PyInstaller

# Módulos que o app não usa: menos código empacotado = menor superfície e inicialização mais rápida.
EXCLUDES = [
    "tkinter",
    "unittest",
    "pydoc",
    "pytest",
    "IPython",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
    "PySide6.QtUiTools",
    "PySide6.QtXml",
    "PySide6.QtHelp",
    "PySide6.QtOpenGLWidgets",
    # Não excluir "PIL": o reportlab 5 importa o Pillow ao inicializar (o autoteste pegou).
    # Não excluir "tufup.repo": o tufup/__init__.py o importa (quebraria as atualizações).
]

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src")],
    datas=collect_data_files("appfin", includes=["**/*.sql", "**/*.json", "**/*.svg"]),
    hiddenimports=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,  # manter asserts/docstrings não muda segurança (não usamos assert para validar)
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EzFinance",
    console=False,
    upx=False,
    version=str(ROOT / "dist" / "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="EzFinance")
