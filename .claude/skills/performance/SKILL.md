---
name: performance
description: Metas e práticas de desempenho do app financeiro do consultório (Python + PySide6 + SQLCipher) — inicialização, listas grandes, consultas e índices, agregações de relatórios/DRE, importação de planilhas, sincronização incremental, memória e tamanho do instalador. Use ao criar telas com listas ou gráficos, consultas ao banco, relatórios, importação, sincronização, ou ao investigar lentidão.
---

# Performance

## Princípio

**Medir antes de otimizar.** Nenhuma otimização sem uma medição antes e depois. E nenhuma otimização
pode enfraquecer a segurança (ex.: cache decifrado no disco, pular validação, desligar a cifra do banco,
baixar os parâmetros do Argon2id).

## Metas (referência, no PC do consultório, com 10 anos de dados ≈ 50 mil lançamentos)

| Situação | Meta |
|---|---|
| Abrir o app até a tela de desbloqueio | < 2 s (justo para Python + PyInstaller: medir na fase 0) |
| Desbloquear até o painel principal | < 1,5 s (excluindo o tempo proposital do Argon2id) |
| Abrir lista de lançamentos de um mês | < 200 ms |
| Rolar lista grande | fluido, sem travadas visíveis |
| Salvar um lançamento (inclusive parcelado em 24x) | < 100 ms percebido |
| DRE / relatório anual por categoria (caixa ou competência) | < 1 s |
| Importar planilha de 5 mil linhas: prévia | < 3 s |
| Importar planilha de 5 mil linhas: gravação | < 2 s |
| Sincronização incremental típica (fase 2) | segundos, em background, sem travar a UI |

Se uma mudança piora uma dessas metas, avisar.

## Banco e consultas

- Índices para os filtros comuns: `(due_date)`, `(paid_date)`, `(accrual_date)`,
  `(account_id, due_date)`, `(category_id, accrual_date)`, `(contact_id)`, `(status, due_date)`,
  `(installment_group_id)`, `(transfer_id)`, `(import_batch_id)`. Conferir `EXPLAIN QUERY PLAN` das
  consultas principais. (Sem `owner_id` local; a sync usa a `outbox`, não índice por `updated_at`.)
- Agregar no banco (`SUM`, `GROUP BY`), não carregando tudo para somar em Python.
- Evitar N+1: carregar relacionados em lote (`JOIN` ou `IN (...)` parametrizado).
- Paginação em toda lista que cresce.
- Escritas em lote (importação, parcelamento, baixa em lote) numa única transação, com `executemany`.
- Saldos e totais mensais podem ter cache materializado, **desde que** recalculável a partir dos
  lançamentos e invalidado a cada alteração.

## Interface

- `QAbstractTableModel` + `QTableView` (virtualizado) com `fetchMore`; nunca `QTableWidget` grande.
- Telas e gráficos carregados sob demanda, não tudo na inicialização.
- Debounce em busca e filtros digitados (`QTimer` single-shot).
- Nada pesado na thread de UI (ver `concurrency`).

## Sincronização e rede (fase 2)

- Sempre incremental (cursor `server_seq`), em lotes de tamanho limitado.
- Não sincronizar a cada tecla: agrupar alterações (debounce) e respeitar backoff.

## Memória, inicialização e instalador

- Não manter todos os lançamentos em memória.
- Inicialização mínima: abrir a janela de desbloqueio; o resto carrega depois.
- **Imports pesados só quando usados** (`reportlab`, `openpyxl`, `PySide6.QtCharts`): import dentro da
  função/caso de uso, não no topo do módulo de inicialização.
- PyInstaller *onedir*, excluindo módulos Qt não usados (QtWebEngine, Qml, 3D etc.) para reduzir tamanho
  e tempo de início.

## Como investigar lentidão

1. Reproduzir com uma base sintética grande (`scripts/gen_synthetic_db.py`, ~50 mil lançamentos,
   dados **fictícios**).
2. Medir com `cProfile`/`py-spy` e logs de tempo (sem dados sensíveis).
3. Atacar o maior gargalo, medir de novo, registrar o ganho no commit.

## Testes

- Benchmark automatizado (`pytest-benchmark`) para as consultas principais, DRE e importação, sobre a
  base sintética; alertar se regredir de forma significativa.

## Adaptação à stack

- Profiler: `cProfile` + `snakeviz`, `py-spy` (inclusive no executável).
- Benchmark: `pytest-benchmark`.
- Base sintética: `uv run python scripts/gen_synthetic_db.py --rows 50000`.
- *Comandos finais: confirmar na fase 0.*

## Skills relacionadas

`concurrency`, `repository-pattern`, `frontend-architecture`, `security`.
