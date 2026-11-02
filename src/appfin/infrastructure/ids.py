"""Gerador de IDs UUIDv7 (RFC 9562): ordenável por tempo e gerado offline em qualquer máquina.

Layout: timestamp (48 bits, ms) | versão 7 | 12 bits aleatórios | variante | 62 bits aleatórios.
"""

from __future__ import annotations

import secrets
import time
import uuid


def uuid7(now_ms: int | None = None) -> str:
    timestamp = (time.time_ns() // 1_000_000 if now_ms is None else now_ms) & ((1 << 48) - 1)
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    value = (timestamp << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return str(uuid.UUID(int=value))
