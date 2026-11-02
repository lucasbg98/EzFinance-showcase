from appfin.self_test import run_self_test


def test_self_test_passes_in_development_environment() -> None:
    assert run_self_test() == 0
