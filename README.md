# AppFinanceiro

Gestão financeira de um consultório odontológico: app desktop Windows, **local-first** e **cifrado**
(Python 3.13 + PySide6 + SQLCipher).

- Projeto completo: [`docs/PROJETO.md`](docs/PROJETO.md)
- Política de segurança: [`SECURITY.md`](SECURITY.md)
- Decisões de arquitetura: [`docs/adr/`](docs/adr/)

## Estado

**Fase 0 — Fundação** (em andamento). Ver o roadmap em `docs/PROJETO.md` §12.

## Ambiente de desenvolvimento

Pré-requisitos: Python 3.13 e [uv](https://docs.astral.sh/uv/).

```bash
uv sync --locked                 # cria .venv a partir do uv.lock (com hashes)
uv run pre-commit install        # ganchos: ruff, mypy, gitleaks
uv run pytest                    # testes
uv run ruff check . && uv run ruff format --check .
uv run mypy                      # tipagem estrita
uv run pip-audit                 # vulnerabilidades conhecidas nas dependências
uv run bandit -c pyproject.toml -r src
uv run appfin                    # abre o app
```

Para usar um diretório de dados de teste (nunca o real): defina `APPFIN_DATA_DIR`
(ex.: `APPFIN_DATA_DIR=./local-data uv run appfin`). A pasta `local-data/` é ignorada pelo git.

## Regras que valem sempre

Ver `CLAUDE.md` e as skills em `.claude/skills/`. Em resumo: segurança antes de tudo, dinheiro só
em centavos inteiros, nenhum segredo no repositório e nenhum dado real em testes.
