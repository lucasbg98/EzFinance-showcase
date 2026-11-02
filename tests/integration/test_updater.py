"""Atualização assinada ponta a ponta: repositório TUF de teste + servidor HTTP local."""

from __future__ import annotations

import functools
import http.server
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from tufup.repo import Repository

from appfin.infrastructure.updater import APP_NAME, EXE_NAME, UpdateError, Updater


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """O tufup grava ``.tufup-repo-config`` no diretório atual: manter fora do projeto."""
    monkeypatch.chdir(tmp_path)


@dataclass
class UpdateRepo:
    root_json: bytes
    repo_dir: Path
    base_url: str


def _make_bundle(directory: Path, version: str) -> Path:
    bundle = directory / f"bundle-{version}"
    bundle.mkdir()
    (bundle / EXE_NAME).write_bytes(f"executavel ficticio {version}".encode())
    (bundle / "_internal").mkdir()
    (bundle / "_internal" / "lib.txt").write_text(version, encoding="utf-8")
    return bundle


def _publish(tmp: Path, name: str, versions: list[str]) -> tuple[Path, bytes]:
    repo_dir = tmp / f"{name}-repo"
    keys_dir = tmp / f"{name}-keys"
    repo = Repository(
        app_name=APP_NAME,
        repo_dir=repo_dir,
        keys_dir=keys_dir,
        expiration_days={"root": 365, "targets": 30, "snapshot": 30, "timestamp": 30},
    )
    repo.initialize()
    for version in versions:
        repo.add_bundle(
            _make_bundle(tmp, f"{name}-{version}"), new_version=version, skip_patch=True
        )
        repo.publish_changes(private_key_dirs=[keys_dir])
    return repo_dir, (repo_dir / "metadata" / "root.json").read_bytes()


@pytest.fixture
def served(tmp_path: Path) -> Iterator[UpdateRepo]:
    repo_dir, root_json = _publish(tmp_path, "oficial", ["0.1.0", "0.2.0"])
    handler = functools.partial(_QuietHandler, directory=str(repo_dir))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield UpdateRepo(root_json, repo_dir, f"http://127.0.0.1:{server.server_address[1]}")
    server.shutdown()
    server.server_close()


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


def _updater(
    tmp_path: Path, served: UpdateRepo, current: str, root: bytes | None = None
) -> Updater:
    install = tmp_path / "install"
    install.mkdir(exist_ok=True)
    return Updater(
        served.base_url,
        install_dir=install,
        cache_dir=tmp_path / f"cache-{current}",
        root_metadata=root if root is not None else served.root_json,
        current_version=current,
    )


def test_legitimate_update_is_found_downloaded_and_verified(
    tmp_path: Path, served: UpdateRepo
) -> None:
    updater = _updater(tmp_path, served, "0.1.0")

    available = updater.check()
    assert available is not None and available.version == "0.2.0"

    prepared = updater.download()

    assert prepared.version == "0.2.0"
    assert (prepared.source_dir / EXE_NAME).read_bytes() == b"executavel ficticio oficial-0.2.0"
    assert prepared.install_dir == tmp_path / "install"


def test_no_update_when_already_on_latest(tmp_path: Path, served: UpdateRepo) -> None:
    assert _updater(tmp_path, served, "0.2.0").check() is None


def test_tampered_package_is_rejected(tmp_path: Path, served: UpdateRepo) -> None:
    archive = next((served.repo_dir / "targets").glob("*0.2.0*.tar.gz"))
    content = bytearray(archive.read_bytes())
    content[len(content) // 2] ^= 0xFF
    archive.write_bytes(bytes(content))
    updater = _updater(tmp_path, served, "0.1.0")
    assert updater.check() is not None

    with pytest.raises(UpdateError):
        updater.download()

    assert not (tmp_path / "cache-0.1.0" / "extract" / EXE_NAME).exists()


def test_metadata_signed_by_other_keys_is_rejected(tmp_path: Path, served: UpdateRepo) -> None:
    """Simula servidor hostil: o app confia num root diferente do que assinou o repositório."""
    _, attacker_root = _publish(tmp_path, "atacante", ["9.9.9"])

    with pytest.raises(UpdateError):
        _updater(tmp_path, served, "0.1.0", root=attacker_root).check()


def test_plain_http_is_refused_except_local_tests(tmp_path: Path) -> None:
    with pytest.raises(UpdateError):
        Updater("http://exemplo.com/updates", tmp_path, tmp_path / "c", b"{}")


def test_download_requires_previous_check(tmp_path: Path, served: UpdateRepo) -> None:
    with pytest.raises(UpdateError):
        _updater(tmp_path, served, "0.1.0").download()


def test_disabled_outside_installed_app(tmp_path: Path) -> None:
    assert Updater.from_environment(tmp_path) is None
