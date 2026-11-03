import json
from pathlib import Path

import pytest

from appfin.infrastructure.crypto.errors import InvalidCredentialError, VaultFormatError
from appfin.infrastructure.crypto.kdf import MINIMUM_SECURE_PARAMS, KdfParams
from appfin.infrastructure.crypto.vault import (
    change_password,
    create_vault,
    format_recovery_key,
    load_envelope,
    parse_recovery_key,
    save_envelope,
    unlock_with_password,
    unlock_with_recovery_key,
)
from tests.support import FAST_MINIMUM, FAST_PARAMS

PASSWORD = "cavalo bateria grampo correto 42"


def test_unlock_with_password_returns_same_dek() -> None:
    created = create_vault(PASSWORD, FAST_PARAMS)

    dek = unlock_with_password(created.envelope, PASSWORD, minimum=FAST_MINIMUM)

    assert dek.reveal() == created.dek.reveal()


def test_wrong_password_is_rejected() -> None:
    created = create_vault(PASSWORD, FAST_PARAMS)

    with pytest.raises(InvalidCredentialError):
        unlock_with_password(created.envelope, "senha errada qualquer", minimum=FAST_MINIMUM)


def test_recovery_key_unlocks_and_tolerates_formatting() -> None:
    created = create_vault(PASSWORD, FAST_PARAMS)
    messy = "  " + created.recovery_key.lower().replace("-", " ") + "\n"

    dek = unlock_with_recovery_key(created.envelope, messy, minimum=FAST_MINIMUM)

    assert dek.reveal() == created.dek.reveal()


def test_wrong_recovery_key_is_rejected() -> None:
    created = create_vault(PASSWORD, FAST_PARAMS)
    other = format_recovery_key(bytes(32))

    with pytest.raises(InvalidCredentialError):
        unlock_with_recovery_key(created.envelope, other, minimum=FAST_MINIMUM)


@pytest.mark.parametrize("text", ["", "ABCD-EFGH", "1" * 52, "!" * 52])
def test_malformed_recovery_key_is_rejected(text: str) -> None:
    with pytest.raises(InvalidCredentialError):
        parse_recovery_key(text)


def test_recovery_key_format() -> None:
    key = format_recovery_key(bytes(range(32)))

    assert len(key.split("-")) == 13
    assert parse_recovery_key(key) == bytes(range(32))


def test_change_password_keeps_dek_and_recovery() -> None:
    created = create_vault(PASSWORD, FAST_PARAMS)

    new_envelope = change_password(
        created.envelope, created.dek, "nova frase bem longa 99", FAST_PARAMS
    )

    assert new_envelope.salt != created.envelope.salt
    dek = unlock_with_password(new_envelope, "nova frase bem longa 99", minimum=FAST_MINIMUM)
    assert dek.reveal() == created.dek.reveal()
    with pytest.raises(InvalidCredentialError):
        unlock_with_password(new_envelope, PASSWORD, minimum=FAST_MINIMUM)
    recovered = unlock_with_recovery_key(new_envelope, created.recovery_key, minimum=FAST_MINIMUM)
    assert recovered.reveal() == created.dek.reveal()


def test_envelope_roundtrip_on_disk(tmp_path: Path) -> None:
    created = create_vault(PASSWORD, FAST_PARAMS)
    path = tmp_path / "vault.json"

    save_envelope(created.envelope, path)
    loaded = load_envelope(path)

    assert loaded == created.envelope
    assert unlock_with_password(loaded, PASSWORD, minimum=FAST_MINIMUM).reveal() == (
        created.dek.reveal()
    )


def test_envelope_file_contains_no_secret(tmp_path: Path) -> None:
    created = create_vault(PASSWORD, FAST_PARAMS)
    path = tmp_path / "vault.json"
    save_envelope(created.envelope, path)
    content = path.read_bytes()

    assert PASSWORD.encode() not in content
    assert created.dek.reveal() not in content
    assert created.recovery_key.encode() not in content


def test_tampered_kdf_params_fail_authentication(tmp_path: Path) -> None:
    """Mudar os parâmetros no arquivo (mesmo para valores válidos) invalida o envelope."""
    created = create_vault(PASSWORD, FAST_PARAMS)
    path = tmp_path / "vault.json"
    save_envelope(created.envelope, path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["kdf"]["opslimit"] = FAST_PARAMS.opslimit + 1
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(InvalidCredentialError):
        unlock_with_password(load_envelope(path), PASSWORD, minimum=FAST_MINIMUM)


def test_params_below_secure_minimum_are_refused_before_derivation() -> None:
    created = create_vault(PASSWORD, FAST_PARAMS)

    with pytest.raises(VaultFormatError):
        unlock_with_password(created.envelope, PASSWORD, minimum=MINIMUM_SECURE_PARAMS)


@pytest.mark.parametrize(
    "content",
    ["", "{}", "não é json", '{"format": "outro", "version": 1}', "[1, 2]"],
)
def test_corrupted_envelope_is_rejected(tmp_path: Path, content: str) -> None:
    path = tmp_path / "vault.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(VaultFormatError):
        load_envelope(path)


def test_missing_envelope_is_reported(tmp_path: Path) -> None:
    with pytest.raises(VaultFormatError):
        load_envelope(tmp_path / "inexistente.json")


@pytest.mark.slow
def test_production_params_work() -> None:
    from appfin.infrastructure.crypto.kdf import PRODUCTION_PARAMS

    created = create_vault(PASSWORD, PRODUCTION_PARAMS)

    assert unlock_with_password(created.envelope, PASSWORD).reveal() == created.dek.reveal()


def test_fast_params_are_only_for_tests() -> None:
    assert not FAST_PARAMS.is_at_least(MINIMUM_SECURE_PARAMS)
    assert KdfParams(3, 64 * 1024 * 1024).is_at_least(MINIMUM_SECURE_PARAMS)


def test_replace_recovery_key_invalidates_only_the_old_key() -> None:
    from appfin.infrastructure.crypto.vault import replace_recovery_key

    created = create_vault("girassol trator piano nuvem", FAST_PARAMS)
    envelope, new_key = replace_recovery_key(created.envelope, created.dek)

    assert new_key != created.recovery_key
    with pytest.raises(InvalidCredentialError):
        unlock_with_recovery_key(envelope, created.recovery_key, FAST_MINIMUM)
    assert (
        unlock_with_recovery_key(envelope, new_key, FAST_MINIMUM).reveal() == created.dek.reveal()
    )
    assert (
        unlock_with_password(envelope, "girassol trator piano nuvem", FAST_MINIMUM).reveal()
        == created.dek.reveal()
    )
