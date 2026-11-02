---
name: backend-architecture
description: Arquitetura do núcleo do app financeiro do consultório (domínio, casos de uso, infraestrutura, sincronização e backend na nuvem) e as regras de domínio financeiro (dinheiro, datas de competência/vencimento/pagamento, parcelas, transferências, recorrências). Use ao criar ou mudar entidades, regras de negócio, casos de uso, migrações de banco, sincronização ou qualquer código fora da interface.
---

# Arquitetura do backend / núcleo

"Backend" aqui é tudo que não é tela: o núcleo do app desktop (domínio + casos de uso +
infraestrutura) e a parte na nuvem (Supabase: tabelas cifradas, RLS, Storage). Referência:
`docs/PROJETO.md`, seções 5 e 6. Regras específicas do consultório: skill `dominio-consultorio`.

## Camadas e regra de dependência

```
presentation  →  application  →  domain
      ↘               ↑
        infrastructure (implementa interfaces de application/domain)
```

| Camada | Contém | Não pode |
|---|---|---|
| `domain` | Entidades, value objects (`Money`, `DateRange`), regras de negócio puras, interfaces de repositório | Importar banco, rede, UI, SDK de nuvem, relógio do sistema, I/O |
| `application` | Casos de uso (`CreateTransaction`, `CreateInstallmentPlan`, `MarkAsPaid`, `ImportSpreadsheet`, `IssueReceipt`, `BuildIncomeStatement`, `CreateTransfer`), DTOs (pydantic), interfaces de serviços (`Clock`, `UnitOfWork`, `Crypto`, `SyncGateway`) | Conter regra de negócio que pertence ao domínio; depender de detalhes de infraestrutura |
| `infrastructure` | Repositórios concretos, SQLCipher, criptografia, cofre do SO, cliente Supabase, leitor de planilhas, PDF | Ser importada por `domain` ou `application` (só através de interfaces) |
| `presentation` | Telas e view models (ver `frontend-architecture`) | Acessar banco/nuvem diretamente; chamar repositório sem passar por caso de uso |

- Dependências apontam **para dentro**. Domínio não conhece ninguém.
- A montagem (injeção de dependências) acontece num único ponto: `appfin/bootstrap.py`.
- Cada caso de uso é uma unidade pequena, com uma responsabilidade, testável com fakes.

## Regras de domínio financeiro (inegociáveis)

**Dinheiro**
- Nunca `float`. Valor em **centavos inteiros (int64)** dentro de `Money(amount_cents, currency)`;
  moeda padrão `BRL`. `Decimal` só na conversão de entrada (texto/planilha → centavos).
- Operações entre moedas diferentes são erro.
- Divisões (parcelas, rateios) distribuem o resto em centavos de forma determinística, nas
  **primeiras** parcelas (ex.: R$ 100,00 em 3x → 33,34 + 33,33 + 33,33), e a soma sempre fecha com o total.
- Arredondamento definido em um único lugar.

**Datas**
- Timestamps técnicos (`created_at`, `updated_at`) em UTC, ISO-8601.
- Datas do lançamento são **datas de calendário** (sem hora/fuso).
- Três datas distintas: `accrual_date` (competência), `due_date` (vencimento), `paid_date` (pagamento).
  - Regime de **caixa** usa `paid_date` (só pagos); regime de **competência** usa `accrual_date`
    (todos os não cancelados). Relatórios recebem o regime como parâmetro.
  - Num parcelamento, **todas as parcelas herdam a mesma `accrual_date`** (data da venda/atendimento);
    só o vencimento varia.
- O relógio é injetado (`Clock`), nunca chamado direto no domínio.

**Lançamentos e saldos**
- Saldo é **derivado** dos lançamentos (ou de um cache recalculável e verificável), nunca um número
  editado à mão sem um lançamento de ajuste.
- Situação "vencida" é **calculada** (pendente + vencimento < hoje), nunca gravada.
- **Transferência** entre contas = **duas pernas** (`transfer_out` e `transfer_in`) ligadas pelo mesmo
  `transfer_id`, gravadas na mesma transação atômica; editar ou apagar uma altera a outra.
  Transferências não entram no DRE nem em relatórios de receita/despesa.
- **Parcelamento:** `InstallmentGroup` (N parcelas, intervalo em dias **ou** meses) + N lançamentos ligados.
- **Recorrências (fase 2):** regra (frequência, início, fim) separada das ocorrências geradas;
  editar "só esta" vs "esta e as próximas" é explícito.
- **Cartões (futuro):** recebíveis de maquininha (taxa + prazo de liquidação) e faturas de cartão da
  clínica (`CardStatement`) seguem a mesma ideia: lançamentos ligados ao agrupador, pagos por transferência.
- Excluir é **soft delete** (`deleted_at`) para permitir sincronização e desfazer;
  exclusão definitiva só por rotina explícita.

**Identidade e metadados** (em toda entidade persistida)
`id` (UUIDv7 gerado no cliente), `version` (inteiro incrementado a cada alteração — concorrência
otimista local), `hlc` (relógio lógico híbrido — ordem na sincronização), `origin_device_id`,
`created_at`, `updated_at`, `deleted_at`.
**Não há `owner_id` no banco local** (uma única usuária, banco todo cifrado); no servidor, `user_id` + RLS.

## Erros

- Erros de domínio são tipos explícitos (`InvalidAmount`, `CurrencyMismatch`, `InvalidInstallmentPlan`,
  `ConcurrencyConflict`…), não strings nem exceções genéricas.
- Validar na fronteira (caso de uso) e garantir invariantes no construtor da entidade:
  uma entidade inválida não deve conseguir existir.
- Falhas de infraestrutura (rede, disco) viram erros de aplicação com mensagem amigável; detalhe
  técnico só no log (sem dados sensíveis — ver `security`).

## Persistência e migrações

- Acesso a dados somente via repositórios (ver `repository-pattern`).
- Schema versionado com migrações `.sql` numeradas (`PRAGMA user_version`), testadas em banco
  sintético; **backup automático antes de migrar**.
- Migração nunca apaga dados sem um passo de backup e confirmação.

## Sincronização com a nuvem (fase 2)

- Local é a fonte primária para a interface; a sincronização roda em segundo plano (ver `concurrency`).
- Envio por **outbox** gravada na mesma transação da alteração; operações **idempotentes**.
- Recebimento incremental por **`server_seq`** (sequência do servidor), **nunca** pelo relógio do cliente.
- Conflitos: **last-writer-wins por registro** (pelo `hlc`). Se as versões divergirem em **valor, datas
  ou conta**, a versão perdedora vai para `sync_conflict` e aparece em "Conflitos para revisar" para a
  usuária decidir. Nada se perde em silêncio.
- A arquitetura é **ponta a ponta**: a cifragem acontece **antes** do envio, no adaptador de sync; o
  servidor só vê dados cifrados + metadados mínimos. O cliente **revalida** tudo o que recebe antes de aplicar.

## Backend na nuvem

- O cliente é não confiável: autorização e validação de formato no servidor (RLS, constraints,
  triggers) — detalhes na skill `security`.
- Funções de servidor só se forem indispensáveis; finas, validando tudo e com testes.
- Ambientes separados: desenvolvimento (Supabase local via CLI) vs produção. Nunca testar com dados reais.

## Testes

- Domínio: testes unitários puros cobrindo regras e casos-limite (centavos, fim de mês, 29/02,
  parcela que cai no dia 31, parcela única, caixa × competência).
- Casos de uso: com repositórios fake em memória.
- Infraestrutura: testes de integração contra SQLCipher real e Supabase local.

## Adaptação à stack

- Composição manual em `src/appfin/bootstrap.py` (sem framework de DI).
- Migrações: `src/appfin/infrastructure/persistence/migrations/NNNN_descricao.sql` + `PRAGMA user_version`.
- Cliente Supabase: `httpx` direto na API REST (fase 2), sem o SDK `supabase-py`.
- Testes: `uv run pytest`.
- *Comandos finais: confirmar na fase 0.*

## Skills relacionadas

`dominio-consultorio`, `repository-pattern`, `security`, `concurrency`, `clean-code`, `performance`.
