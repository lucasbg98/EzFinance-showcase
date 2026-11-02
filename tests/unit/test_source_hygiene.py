"""Nenhum arquivo do projeto pode conter caracteres invisíveis ou de controle bidirecional.

Eles permitem que o código exibido difira do executado ("Trojan Source", CVE-2021-42574).
O Bandit (B613) cobre só ``src/``; este teste cobre todo o projeto.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUFFIXES = {".py", ".sql", ".md", ".toml", ".yml", ".yaml", ".iss", ".spec", ".json", ".txt"}
SKIP = {".venv", ".git", "build", "dist", "skills", "referencias", "local-data"}
FORBIDDEN = (
    set(range(0x200B, 0x2010))
    | set(range(0x202A, 0x202F))
    | set(range(0x2066, 0x206A))
    | {0xFEFF, 0x00AD}
)


def test_no_invisible_or_bidi_characters_in_project_files() -> None:
    problems = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in SUFFIXES:
            continue
        if SKIP.intersection(path.relative_to(ROOT).parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            found = sorted({f"U+{ord(ch):04X}" for ch in line if ord(ch) in FORBIDDEN})
            if found:
                problems.append(f"{path.relative_to(ROOT)}:{number} {found}")

    assert not problems, "\n".join(problems)
