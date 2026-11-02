"""Ponto de entrada: ``python -m appfin`` ou ``uv run appfin``."""

from __future__ import annotations

import sys


def main() -> int:
    if "--self-test" in sys.argv:
        from appfin.self_test import run_self_test

        return run_self_test()
    from appfin.presentation.app import run

    return run()


if __name__ == "__main__":
    sys.exit(main())
