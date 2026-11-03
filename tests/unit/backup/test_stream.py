"""Formato .afbkp: ida e volta, e recusa de arquivo adulterado, truncado ou com chave errada."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from appfin.infrastructure.backup import stream
from appfin.infrastructure.crypto.secret import SecretBytes

KEY = bytes(range(32))
VAULT = {"format": "appfin-vault", "wrapped_dek": "fictício"}
MANIFEST = {"created_at": "2026-03-15T12:00:00+00:00", "counts": {"contact": 2}}


def _backup(tmp_path: Path, size: int = stream.CHUNK_SIZE * 2 + 123) -> tuple[bytes, bytes]:
    database = tmp_path / "db.bin"
    content = bytes(index % 251 for index in range(size))
    database.write_bytes(content)
    out = io.BytesIO()
    stream.write_backup(out, stream.encode_header(VAULT), MANIFEST, database, SecretBytes(KEY))
    return out.getvalue(), content


def _read(data: bytes, key: bytes = KEY) -> tuple[dict[str, object], bytes]:
    source = io.BytesIO(data)
    header = stream.read_header(source)
    out = io.BytesIO()
    manifest = stream.read_backup(source, header, SecretBytes(key), out)
    return manifest, out.getvalue()


@pytest.mark.parametrize("size", [0, 1, stream.CHUNK_SIZE, stream.CHUNK_SIZE * 2 + 123])
def test_round_trip(tmp_path: Path, size: int) -> None:
    data, content = _backup(tmp_path, size)

    manifest, restored = _read(data)

    assert manifest == MANIFEST and restored == content
    assert stream.read_header(io.BytesIO(data)).vault == VAULT
    if size >= 64:
        assert content[:64] not in data, "o banco não pode aparecer em claro"


def test_wrong_key_is_refused(tmp_path: Path) -> None:
    data, _ = _backup(tmp_path)

    with pytest.raises(stream.BackupFormatError, match="adulterado"):
        _read(data, bytes(32))


def test_tampered_public_header_is_detected(tmp_path: Path) -> None:
    data, _ = _backup(tmp_path)
    tampered = data.replace("fictício".encode(), b"ficticiO" + b"X", 1)
    tampered = (
        tampered[:8] + (len(stream.encode_header(VAULT)) + 1).to_bytes(4, "big") + tampered[12:]
    )

    with pytest.raises(stream.BackupFormatError):
        _read(tampered)


@pytest.mark.parametrize("position", [0.3, 0.6, 0.99])
def test_flipped_byte_in_ciphertext_is_detected(tmp_path: Path, position: float) -> None:
    data, _ = _backup(tmp_path)
    index = int(len(data) * position)
    tampered = data[:index] + bytes([data[index] ^ 1]) + data[index + 1 :]

    with pytest.raises(stream.BackupFormatError):
        _read(tampered)


@pytest.mark.parametrize("cut", [1, 17, stream.CHUNK_SIZE // 2])
def test_truncated_file_is_detected(tmp_path: Path, cut: int) -> None:
    data, _ = _backup(tmp_path)

    with pytest.raises(stream.BackupFormatError):
        _read(data[:-cut])


def test_dropping_the_last_chunk_is_detected(tmp_path: Path) -> None:
    """Remover a mensagem final inteira deixa um arquivo "bem formado", mas sem a TAG_FINAL."""
    data, _ = _backup(tmp_path, stream.CHUNK_SIZE + 10)
    last_length = 10 + 17 + 4

    with pytest.raises(stream.BackupFormatError, match="truncado"):
        _read(data[:-last_length])


def test_extra_data_after_end_is_refused(tmp_path: Path) -> None:
    data, _ = _backup(tmp_path)

    with pytest.raises(stream.BackupFormatError, match="extras"):
        _read(data + b"lixo")


@pytest.mark.parametrize(
    "data",
    [b"", b"PK\x03\x04 planilha", b"AFBACKUP", b"AFBACKUP\xff\xff\xff\xff"],
)
def test_not_a_backup(data: bytes) -> None:
    with pytest.raises(stream.BackupFormatError):
        stream.read_header(io.BytesIO(data))


def test_unknown_format_version(tmp_path: Path) -> None:
    header = stream.encode_header(VAULT).replace(b'"version":1', b'"version":9')
    data = stream.MAGIC + len(header).to_bytes(4, "big") + header

    with pytest.raises(stream.BackupFormatError, match="desconhecida"):
        stream.read_header(io.BytesIO(data))
