# EzFinance — gestão financeira do consultório odontológico

App desktop Windows (Python 3.13 + PySide6 + SQLCipher) para um consultório odontológico pequeno (PJ),
usado por uma pessoa. **Segurança é a prioridade nº 1** (dados financeiros e de pacientes).

## Fonte da verdade

- **`docs/PROJETO.md`** — documento de projeto aprovado: escopo, arquitetura, modelo de dados,
  segurança, roadmap. Em caso de dúvida ou conflito, ele vence; se algo não estiver lá, **pergunte**.
- `docs/ANALISE_SKILLS.md` — decisões D1–D8 que alinharam as skills ao projeto.
- Skills em `.claude/skills/`: `security`, `backend-architecture`, `repository-pattern`,
  `frontend-architecture`, `concurrency`, `performance`, `clean-code`, `dominio-consultorio`,
  `importacao-planilha`.
  Carregue as relevantes antes de mexer na área correspondente.

## Regras que valem sempre

- Nunca enfraquecer um controle de segurança para "fazer funcionar" — pare e pergunte (skill `security`).
- Dinheiro só em centavos inteiros; nunca `float`.
- Nenhum segredo no código/repositório; nenhum dado real (financeiro ou de paciente) em testes, exemplos ou logs.
- Dados do usuário na interface sempre como `PlainText`.
- O app **não** é prontuário: nada de informação clínica.
- Não copiar código, ícones, textos ou marca do app de referência (app usado só como referência funcional).
- Implementar por fase (roadmap do `docs/PROJETO.md` §12); não adiantar funcionalidades de fases futuras.

## Comandos

```bash
uv sync --locked                        # ambiente a partir do uv.lock (hashes)
uv run pytest                           # todos os testes (QT_QPA_PLATFORM=offscreen para rodar sem janela)
uv run pytest -m "not slow"             # rápido (sem Argon2id de produção)
uv run ruff format . && uv run ruff check .
uv run mypy                             # estrito
uv run bandit -c pyproject.toml -r src
uv run pre-commit run --all-files       # gitleaks + ruff + mypy
APPFIN_DATA_DIR=./local-data uv run appfin   # abrir o app com dados de TESTE
```

Auditoria de dependências: ver o job `dependencies` em `.github/workflows/security.yml`
(`uv export` + `pip-audit --require-hashes`). Nesta máquina o `uv` foi instalado via pip e fica em
`%APPDATA%\Python\Python313\Scripts` (fora do PATH).

## Estrutura

Ver `docs/PROJETO.md` §9 (camadas `domain` / `application` / `infrastructure` / `presentation`,
interface organizada por funcionalidade em `src/appfin/presentation/features/`).
