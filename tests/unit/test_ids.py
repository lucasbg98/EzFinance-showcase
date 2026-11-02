import uuid

from appfin.infrastructure.ids import uuid7


def test_uuid7_format_and_time_ordering() -> None:
    first = uuid7(now_ms=1_700_000_000_000)
    later = uuid7(now_ms=1_700_000_000_001)

    parsed = uuid.UUID(first)
    assert parsed.version == 7
    assert parsed.variant == uuid.RFC_4122
    assert first < later


def test_uuid7_is_unique() -> None:
    assert len({uuid7(now_ms=0) for _ in range(5000)}) == 5000
