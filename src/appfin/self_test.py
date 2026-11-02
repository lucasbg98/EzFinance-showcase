"""Autoteste do executável empacotado (``AppFinanceiro.exe --self-test``).

Rodado pelo script de release logo após o build: garante que o PyInstaller incluiu tudo o que o
app precisa em produção (cripto, banco cifrado, migrações, interface, cliente de atualização e o
``root.json`` confiável). Retorna 0 se tudo estiver OK. Não toca em dados reais.
"""

from __future__ import annotations

import tempfile
from pathlib import Path


def run_self_test() -> int:
    try:
        _check_crypto_and_database()
        _check_update_client()
        _check_ui_modules()
    except Exception:  # noqa: BLE001 - qualquer falha = build inválido
        return 1
    return 0


def _check_crypto_and_database() -> None:
    from appfin.infrastructure.crypto.kdf import KdfParams
    from appfin.infrastructure.crypto.vault import create_vault, unlock_with_password
    from appfin.infrastructure.persistence.database import open_encrypted
    from appfin.infrastructure.persistence.migrator import migrate

    fast = KdfParams(opslimit=1, memlimit=8 * 1024)
    created = create_vault("autoteste do executavel", fast)
    dek = unlock_with_password(created.envelope, "autoteste do executavel", minimum=fast)
    with tempfile.TemporaryDirectory() as directory:
        connection = open_encrypted(Path(directory) / "selftest.db", dek)
        try:
            if migrate(connection) < 1:
                raise RuntimeError("migrações não encontradas no pacote")
        finally:
            connection.close()


def _check_update_client() -> None:
    import tufup.client  # noqa: F401 - só verifica que o import funciona no executável

    from appfin.infrastructure.updater import bundled_root_metadata

    if not bundled_root_metadata():
        raise RuntimeError("root.json confiável ausente do pacote")


def _check_ui_modules() -> None:
    import PySide6.QtNetwork
    import PySide6.QtWidgets  # noqa: F401
    import zxcvbn  # noqa: F401
