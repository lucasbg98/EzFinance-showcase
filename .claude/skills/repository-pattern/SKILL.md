---
name: repository-pattern
description: Como implementar o acesso a dados do app financeiro do consultório com Repository Pattern e Unit of Work sobre SQLCipher. Use ao criar ou alterar repositórios, queries, mapeamento entre banco e entidades, transações de banco, migrações, filtros/paginação ou fakes de teste.
---

# Repository Pattern

O repositório é a **única** porta entre o domínio e o armazenamento (SQLCipher local; Supabase na
fase 2, só pelo adaptador de sync). O resto do app trabalha com entidades do domínio e não sabe se os
dados vêm do SQLite ou de uma lista em memória.

## Regras

1. **Interface no domínio/aplicação, implementação na infraestrutura.**
   `domain/repositories/transaction_repository.py` define o contrato (`Protocol`);
   `infrastructure/persistence/sqlite_transaction_repository.py` implementa.
2. **Um repositório por agregado**, não por tabela. MVP: `CompanyRepository`, `AccountRepository`,
   `CategoryRepository`, `ContactRepository`, `TransactionRepository` (inclui grupos de parcelas e
   pernas de transferência), `ReceiptRepository`, `ImportBatchRepository` (inclui perfis de mapeamento),
   `SettingRepository`. Depois: `RecurrenceRepository`, `CardStatementRepository`, `BudgetRepository`.
3. **Entra e sai entidade do domínio.** Nunca retornar `sqlite3.Row`, tupla ou `dict` cru.
   O mapeamento fica dentro do repositório.
4. **Sem regra de negócio.** Repositório salva, busca e remove. Calcular saldo, gerar parcelas,
   montar o DRE é do domínio/caso de uso.
5. **Métodos com intenção clara**, nada de repositório genérico que expõe query livre:
   ```
   get_by_id(id) -> Transaction | None
   list_by_period(filter: TransactionFilter, page: PageRequest) -> Page[Transaction]
   list_by_installment_group(group_id) -> list[Transaction]
   add(transaction) / update(transaction) / soft_delete(id)
   ```
   Filtros compostos usam um objeto de critérios tipado (`TransactionFilter`: tipo, período, regime
   caixa/competência, conta, categoria, contato, situação, texto), não strings.
6. **Sem `owner_id` local.** O banco local pertence a uma única usuária e é todo cifrado (decisão D3);
   o isolamento por usuário é feito no servidor (RLS).
7. **Queries 100% parametrizadas.** Proibido montar SQL concatenando texto, inclusive em `ORDER BY`
   (usar uma lista fechada de colunas permitidas).
8. **Soft delete por padrão.** Consultas normais ignoram `deleted_at IS NOT NULL`; existe método
   explícito para incluir excluídos (usado pela sincronização e por "desfazer importação").
9. **Concorrência otimista.** `update` exige a `version` lida (`WHERE id = ? AND version = ?`); se
   nenhuma linha mudar, lança `ConcurrencyConflict` em vez de sobrescrever (ver `concurrency`).
10. **Paginação obrigatória** para listas que podem crescer (lançamentos, contatos, histórico).
11. **Dinheiro** persistido como inteiro em centavos + código da moeda; datas de calendário como
    `YYYY-MM-DD`; timestamps em UTC. Nunca converter dinheiro via float no mapeamento.

## Unit of Work (transações)

Operações que tocam mais de um registro são atômicas: transferência (duas pernas), parcelamento
(grupo + N parcelas), baixa em lote, importação de planilha, desfazer importação, restauração de backup.

- O caso de uso abre uma *unit of work*, usa os repositórios dela e faz `commit`; qualquer erro faz
  `rollback` completo.
- A unit of work grava as entradas da **outbox de sincronização** na mesma transação (já desde o MVP,
  para a fase 2 não exigir migração de dados).
- Repositórios não fazem `commit` sozinhos.

```python
with uow:                                 # UnitOfWork é um context manager
    uow.transactions.add(out_leg)
    uow.transactions.add(in_leg)
    uow.outbox.enqueue(changes)
    uow.commit()                          # sem commit → rollback ao sair
```

## Nuvem

- O cliente Supabase só aparece dentro de `infrastructure/sync`. Trocar de provedor muda só o adaptador.
- Cifrar/decifrar acontece no adaptador de sincronização, não espalhado pelos repositórios.

## Testes

- Cada interface tem um **fake em memória** (`tests/fakes/`) usado nos testes de casos de uso.
- **Testes de contrato:** a mesma bateria roda contra o fake e contra a implementação SQLCipher
  (`pytest` parametrizado), garantindo o mesmo comportamento (soft delete, paginação, conflito de versão).

## Anti-padrões a evitar

- Repositório genérico `Repository[T]` com `query(sql)` exposto.
- Caso de uso ou tela importando `sqlcipher3`/`sqlite3`.
- Método `save()` que decide sozinho entre inserir/atualizar e engole conflito.
- Carregar todos os lançamentos para filtrar ou somar em memória.
- Lazy loading escondido que dispara N+1 consultas.

## Adaptação à stack

- **SQL puro** com a API DB-API do `sqlcipher3` (compatível com `sqlite3`) + mapeadores manuais. Sem ORM.
- Uma conexão por thread; escritor único (ver `concurrency`).
- Migrações: arquivos `.sql` numerados + `PRAGMA user_version`, executados no desbloqueio, com backup antes.
- Paginação na interface com `QAbstractTableModel` + `canFetchMore`/`fetchMore`.
- *Exemplo real de repositório e do teste de contrato: acrescentar na fase 0.*

## Skills relacionadas

`backend-architecture`, `security`, `concurrency`, `performance`.
