"""Atualizações assinadas com TUF (via ``tufup``) — docs/PROJETO.md §7.11 e §11.

Garantias (do TUF): metadados assinados com Ed25519, chave *root* confiável embutida no app
(``resources/tuf_root.json``), expiração de metadados, proteção contra *rollback*/*freeze* e
verificação de hash de cada arquivo antes de usar. Sem assinatura válida, nada é instalado.

Fluxo em três etapas, para respeitar as threads do Qt:
1. ``check()`` — segundo plano: baixa e valida os metadados.
2. ``download()`` — segundo plano: baixa o pacote, confere hash/assinatura e extrai.
3. ``install_and_exit()`` — thread principal, **depois** de bloquear a sessão: copia os arquivos
   para a pasta de instalação (script ``robocopy``), reabre o app e encerra o processo atual.

Os dados da usuária ficam em ``%APPDATA%`` e não são tocados: só a pasta de instalação é trocada.
"""

from __future__ import annotations

import os
import shutil

# subprocess: só a constante CREATE_NO_WINDOW; quem executa o script é o tufup.
import subprocess  # nosec B404
import sys
import tarfile
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Final

from appfin import __version__

# Identificador do app nas atualizações assinadas (TUF): é o nome antigo de propósito; trocar faria
# as versões instaladas deixarem de reconhecer os pacotes. O nome visível é ``PRODUCT_NAME``.
APP_NAME: Final = "AppFinanceiro"
EXE_NAME: Final = "EzFinance.exe"
# URL pública onde ficam ``metadata/`` e ``targets/``. Vazia = atualização desativada até a
# hospedagem ser escolhida. Mesmo apontando para um servidor hostil, nada sem assinatura é aceito.
DEFAULT_UPDATE_URL: Final = ""
UPDATE_URL_ENV: Final = "APPFIN_UPDATE_URL"
_ROOT_METADATA_RESOURCE: Final = "tuf_root.json"
# Arquivos do desinstalador do Inno Setup não podem ser apagados pela atualização.
_KEEP_ON_PURGE: Final = ["unins000.exe", "unins000.dat"]
_INSTALL_SCRIPT: Final = (
    "@echo off\n"
    "{log_lines}\n"
    "timeout /t 2 /nobreak >nul\n"
    'robocopy "{src_dir}" "{dst_dir}" {robocopy_options}\n'
    'start "" "{dst_dir}\\' + EXE_NAME + '"\n'
    "{delete_self}\n"
)


class UpdateError(Exception):
    """Falha ao verificar ou baixar atualização (rede, assinatura, hash, metadados expirados)."""


@dataclass(frozen=True, slots=True)
class AvailableUpdate:
    version: str


@dataclass(frozen=True, slots=True)
class PreparedUpdate:
    version: str
    source_dir: Path
    install_dir: Path


def bundled_root_metadata() -> bytes | None:
    """``root.json`` confiável embutido no app (público). ``None`` se ainda não foi gerado."""
    resource = resources.files("appfin.resources").joinpath(_ROOT_METADATA_RESOURCE)
    return resource.read_bytes() if resource.is_file() else None


class Updater:
    def __init__(
        self,
        base_url: str,
        install_dir: Path,
        cache_dir: Path,
        root_metadata: bytes,
        current_version: str = __version__,
    ) -> None:
        if not base_url.startswith("https://") and not _is_local_test_url(base_url):
            raise UpdateError("O endereço de atualização precisa usar HTTPS.")
        self._base_url = base_url.rstrip("/") + "/"
        self._install_dir = install_dir
        self._cache_dir = cache_dir
        self._current_version = current_version
        self._metadata_dir = cache_dir / "metadata"
        self._targets_dir = cache_dir / "targets"
        self._extract_dir = cache_dir / "extract"
        self._metadata_dir.mkdir(parents=True, exist_ok=True)
        self._targets_dir.mkdir(parents=True, exist_ok=True)
        root_file = self._metadata_dir / "root.json"
        if not root_file.exists():
            # Só na primeira vez; depois o TUF atualiza o root com segurança (cadeia assinada).
            root_file.write_bytes(root_metadata)
        self._client: Any = None
        self._available: AvailableUpdate | None = None

    @classmethod
    def from_environment(cls, cache_dir: Path) -> Updater | None:
        """Updater do app instalado; ``None`` em desenvolvimento, sem URL ou sem root confiável."""
        if not getattr(sys, "frozen", False):
            return None
        base_url = os.environ.get(UPDATE_URL_ENV) or DEFAULT_UPDATE_URL
        root_metadata = bundled_root_metadata()
        if not base_url or root_metadata is None:
            return None
        return cls(base_url, Path(sys.executable).parent, cache_dir, root_metadata)

    # ------------------------------------------------------------------ etapa 1
    def check(self) -> AvailableUpdate | None:
        try:
            from tufup.client import Client

            self._client = Client(
                app_name=APP_NAME,
                app_install_dir=self._install_dir,
                current_version=self._current_version,
                metadata_dir=self._metadata_dir,
                metadata_base_url=self._base_url + "metadata/",
                target_dir=self._targets_dir,
                target_base_url=self._base_url + "targets/",
                extract_dir=self._extract_dir,
                # Obrigatório validar a cadeia root → timestamp → snapshot → targets. Quando falha
                # (rede, assinatura, expiração, rollback), o tufup chama sys.exit(): o SystemExit é
                # capturado abaixo e vira UpdateError — o app continua aberto.
                refresh_required=True,
            )
            target = self._client.check_for_updates(patch=False)
        except (Exception, SystemExit) as exc:  # erros de rede/TUF de várias bibliotecas
            raise UpdateError("Não foi possível verificar atualizações.") from exc
        self._available = AvailableUpdate(str(target.version)) if target else None
        return self._available

    # ------------------------------------------------------------------ etapa 2
    def download(self) -> PreparedUpdate:
        if self._client is None or self._available is None:
            raise UpdateError("Nenhuma atualização verificada para baixar.")
        if self._extract_dir.exists():
            shutil.rmtree(self._extract_dir)
        self._extract_dir.mkdir(parents=True)
        # Defesa em profundidade: mesmo com o pacote já verificado pelo TUF, a extração usa o filtro
        # "data" (bloqueia caminhos absolutos, "..", links e arquivos especiais).
        tarfile.TarFile.extraction_filter = staticmethod(tarfile.data_filter)
        captured: dict[str, Path] = {}

        def capture(src_dir: str | Path, dst_dir: str | Path, **_: object) -> None:
            captured["src"] = Path(src_dir)
            captured["dst"] = Path(dst_dir)

        try:
            self._client.download_and_apply_update(skip_confirmation=True, install=capture)
        except (Exception, SystemExit) as exc:
            raise UpdateError("Falha ao baixar ou verificar a atualização.") from exc
        if "src" not in captured:
            # O tufup aborta sem exceção quando o hash/assinatura do pacote não confere.
            raise UpdateError("O pacote de atualização não passou na verificação.")
        if not (captured["src"] / EXE_NAME).is_file():
            raise UpdateError("Pacote de atualização incompleto.")
        return PreparedUpdate(self._available.version, captured["src"], captured["dst"])

    # ------------------------------------------------------------------ etapa 3
    @staticmethod
    def install_and_exit(prepared: PreparedUpdate) -> None:
        """Troca os arquivos da instalação e reabre o app. Encerra o processo atual."""
        from tufup.utils.platform_specific import install_update

        install_update(
            src_dir=prepared.source_dir,
            dst_dir=prepared.install_dir,
            purge_dst_dir=True,
            exclude_from_purge=_KEEP_ON_PURGE,
            batch_template=_INSTALL_SCRIPT,
            process_creation_flags=subprocess.CREATE_NO_WINDOW,
        )


def _is_local_test_url(url: str) -> bool:
    """HTTP só para servidor local de teste (127.0.0.1/localhost)."""
    return url.startswith(("http://127.0.0.1:", "http://localhost:"))
