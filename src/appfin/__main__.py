"""Ponto de entrada: ``python -m appfin`` ou ``uv run appfin``."""

from __future__ import annotations

import sys


def main() -> int:
    from appfin.presentation.app import run

    return run()


if __name__ == "__main__":
    sys.exit(main())
