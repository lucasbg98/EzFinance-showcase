"""Contêiner de segredo com apagamento explícito.

Limitação conhecida (docs/PROJETO.md §4.2): o CPython não garante apagar todas as cópias de um
segredo da memória. Mitigação: manter o segredo num ``bytearray`` mutável, minimizar cópias
imutáveis (``bytes``) e sobrescrever com zeros no bloqueio.
"""

from __future__ import annotations

from appfin.infrastructure.crypto.errors import SecretWipedError


class SecretBytes:
    """Bytes sensíveis (chaves). Nunca aparecem em ``repr``/``str``."""

    __slots__ = ("_buffer", "_wiped")

    def __init__(self, data: bytes | bytearray) -> None:
        self._buffer = bytearray(data)
        self._wiped = False
        if isinstance(data, bytearray):
            # A origem mutável também é apagada: o SecretBytes passa a ser o único dono.
            data[:] = b"\x00" * len(data)

    def __len__(self) -> int:
        return len(self._buffer)

    def __repr__(self) -> str:
        return "SecretBytes(<oculto>)"

    __str__ = __repr__

    @property
    def is_wiped(self) -> bool:
        return self._wiped

    def reveal(self) -> bytes:
        """Cópia imutável para APIs que exigem ``bytes`` (libsodium). Use e descarte logo."""
        if self._wiped:
            raise SecretWipedError("Segredo indisponível: o app está bloqueado.")
        return bytes(self._buffer)

    def wipe(self) -> None:
        """Sobrescreve o conteúdo com zeros. Idempotente."""
        for index in range(len(self._buffer)):
            self._buffer[index] = 0
        self._wiped = True

    def __enter__(self) -> SecretBytes:
        return self

    def __exit__(self, *_: object) -> None:
        self.wipe()
