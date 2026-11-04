"""Release do EzFinance: chaves TUF, build (PyInstaller + Inno Setup), publicação e teste local.

Uso (sempre via uv, na raiz do projeto):

    uv run python packaging/release.py keys        # 1x: cria chaves + root.json confiável
    uv run python packaging/release.py build       # executável + instalador + SHA-256
    uv run python packaging/release.py publish     # assina e publica a versão no repositório TUF
    uv run python packaging/release.py refresh     # renova a validade dos metadados (mensal)
    uv run python packaging/release.py serve       # serve o repositório em 127.0.0.1 (só teste)

Segurança (docs/PROJETO.md §7.10 a 7.11):
- Chaves privadas e o estado do repositório ficam FORA do projeto, em ``APPFIN_RELEASE_HOME``
  (padrão: ``%USERPROFILE%\\.appfin-release-test``). Nunca versionar.
- Só o ``root.json`` (público) entra no app, em ``src/appfin/resources/tuf_root.json``.
- As chaves geradas sem ``--encrypted`` são de TESTE. Para produção: ``keys --encrypted`` (pede
  senha), e a pasta com a chave *root* deve ficar offline (pen drive cifrado).
"""

from __future__ import annotations

import argparse
import hashlib
import http.server
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
PRODUCT_NAME = "EzFinance"  # nome visível (igual a appfin.PRODUCT_NAME)
EXE_NAME = f"{PRODUCT_NAME}.exe"
BUNDLE = DIST / PRODUCT_NAME
ROOT_METADATA_FILE = ROOT / "src" / "appfin" / "resources" / "tuf_root.json"
# Identificador nas atualizações assinadas (TUF): nome antigo de propósito (updater.APP_NAME).
APP_NAME = "AppFinanceiro"
EXPIRATION_DAYS = {"root": 365, "targets": 90, "snapshot": 90, "timestamp": 30}
ISCC_CANDIDATES = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
]


def release_home() -> Path:
    default = Path.home() / ".appfin-release-test"
    home = Path(os.environ.get("APPFIN_RELEASE_HOME", default)).resolve()
    if home == ROOT or ROOT in home.parents:
        sys.exit("APPFIN_RELEASE_HOME não pode ficar dentro do projeto (chaves privadas!).")
    return home


def app_version() -> str:
    sys.path.insert(0, str(ROOT / "src"))
    from appfin import __version__

    return __version__


def _repository(encrypted: bool):  # type: ignore[no-untyped-def]
    from tufup.repo import Repository

    home = release_home()
    home.mkdir(parents=True, exist_ok=True)
    os.chdir(home)  # o tufup grava .tufup-repo-config no diretório atual
    return Repository(
        app_name=APP_NAME,
        repo_dir=home / "repository",
        keys_dir=home / "keys",
        encrypted_keys=["root", "targets"] if encrypted else [],
        expiration_days=EXPIRATION_DAYS,
    )


def _existing_repository(encrypted: bool):  # type: ignore[no-untyped-def]
    """Carrega chaves e metadados SEM criar chaves (``initialize`` oferece sobrescrevê-las)."""
    if not (release_home() / "keys").exists():
        sys.exit("Sem chaves. Rode primeiro: release.py keys")
    repo = _repository(encrypted)
    repo._load_keys_and_roles(create_keys=False)  # API interna do tufup; sem alternativa pública
    return repo


# ---------------------------------------------------------------------- comandos
def cmd_keys(args: argparse.Namespace) -> None:
    if (release_home() / "keys").exists():
        sys.exit("Já existem chaves em APPFIN_RELEASE_HOME. Recriar invalidaria o app instalado.")
    repo = _repository(args.encrypted)
    repo.initialize()
    ROOT_METADATA_FILE.write_bytes((repo.metadata_dir / "root.json").read_bytes())
    print(f"Chaves e repositório em: {release_home()}")
    print(f"root.json confiável copiado para: {ROOT_METADATA_FILE.relative_to(ROOT)}")
    if not args.encrypted:
        print("ATENÇÃO: chaves de TESTE (sem senha). Não use em produção.")


def cmd_build(args: argparse.Namespace) -> None:
    version = app_version()
    if not ROOT_METADATA_FILE.exists():
        sys.exit("Falta o root.json confiável. Rode primeiro: release.py keys")
    if BUNDLE.exists():
        shutil.rmtree(BUNDLE)
    DIST.mkdir(exist_ok=True)
    _write_version_info(version)
    _run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(DIST),
            "--workpath",
            str(ROOT / "build"),
            str(ROOT / "packaging" / "appfin.spec"),
        ]
    )
    if not (BUNDLE / EXE_NAME).is_file():
        sys.exit("PyInstaller não gerou o executável.")
    _self_test()
    if args.no_installer:
        return
    iscc = next((path for path in ISCC_CANDIDATES if path.is_file()), None)
    if iscc is None:
        sys.exit("Inno Setup 6 (ISCC.exe) não encontrado.")
    _run([str(iscc), f"/DAppVersion={version}", str(ROOT / "packaging" / "installer.iss")])
    installer = DIST / "installer" / f"{PRODUCT_NAME}-Setup-{version}.exe"
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    checksum = installer.with_name(installer.name + ".sha256")
    checksum.write_text(f"{digest}  {installer.name}\n", encoding="ascii")
    print(f"\nInstalador: {installer.relative_to(ROOT)}\nSHA-256:    {digest}")


def cmd_publish(args: argparse.Namespace) -> None:
    version = app_version()
    if not (BUNDLE / EXE_NAME).is_file():
        sys.exit("Rode primeiro: release.py build")
    repo = _existing_repository(args.encrypted)
    repo.add_bundle(new_bundle_dir=BUNDLE, new_version=version, skip_patch=True)
    repo.publish_changes(private_key_dirs=[repo.keys_dir])
    print(f"Versão {version} assinada e publicada em {repo.repo_dir}")
    print("Envie o conteúdo de 'metadata/' e 'targets/' para a hospedagem de atualizações.")


def cmd_refresh(args: argparse.Namespace) -> None:
    repo = _existing_repository(args.encrypted)
    for role in ("targets", "snapshot", "timestamp"):
        repo.refresh_expiration_date(role, days=EXPIRATION_DAYS[role])
    repo.publish_changes(private_key_dirs=[repo.keys_dir])
    print("Validade dos metadados renovada.")


def cmd_serve(args: argparse.Namespace) -> None:
    directory = release_home() / "repository"
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(  # noqa: E731
        *a, directory=str(directory), **k
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"Servindo {directory} em http://127.0.0.1:{args.port}/ (Ctrl+C para parar)")
    print(f"No app de teste: set APPFIN_UPDATE_URL=http://127.0.0.1:{args.port}")
    server.serve_forever()


# ---------------------------------------------------------------------- auxiliares
def _self_test() -> None:
    """Roda o executável empacotado em modo autoteste: pega módulos/arquivos faltando no build."""
    result = subprocess.run(  # noqa: S603 - executável recém-gerado pelo próprio build
        [str(BUNDLE / EXE_NAME), "--self-test"], cwd=ROOT, timeout=120, check=False
    )
    if result.returncode != 0:
        sys.exit("Autoteste do executável FALHOU: o build está incompleto.")
    print("Autoteste do executável: OK")


def _run(command: list[str]) -> None:
    print("$", " ".join(command))
    subprocess.run(command, check=True, cwd=ROOT)  # noqa: S603 - comandos fixos do build


def _write_version_info(version: str) -> None:
    parts = [int(p) for p in version.split(".")[:3]] + [0]
    numbers = ", ".join(str(p) for p in parts[:4])
    (DIST / "version_info.txt").write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({numbers}), prodvers=({numbers}), mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041604B0', [
      StringStruct('CompanyName', 'Uso interno do consultório'),
      StringStruct('FileDescription', '{PRODUCT_NAME}'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', '{PRODUCT_NAME}'),
      StringStruct('OriginalFilename', '{EXE_NAME}'),
      StringStruct('ProductName', '{PRODUCT_NAME}'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1046, 1200])])
  ]
)
""",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("keys", "publish", "refresh"):
        command = sub.add_parser(name)
        command.add_argument(
            "--encrypted", action="store_true", help="chaves root/targets com senha"
        )
    build = sub.add_parser("build")
    build.add_argument("--no-installer", action="store_true", help="só executável + autoteste (CI)")
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    {
        "keys": cmd_keys,
        "build": cmd_build,
        "publish": cmd_publish,
        "refresh": cmd_refresh,
        "serve": cmd_serve,
    }[args.command](args)


if __name__ == "__main__":
    main()
