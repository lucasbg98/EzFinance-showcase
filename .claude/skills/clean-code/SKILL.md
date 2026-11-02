---
name: clean-code
description: Padrões de código limpo do app financeiro do consultório (Python) — nomes, glossário do domínio, funções, tipos, erros, comentários, testes, commits e definição de pronto. Use ao escrever, refatorar ou revisar qualquer código do projeto.
---

# Clean Code

Código escrito para ser lido e alterado com segurança daqui a meses, por mim ou por uma IA.

## Idioma e glossário

- **Código em inglês** (nomes, comentários técnicos, commits). **Interface e documentação em
  português (pt-BR).**
- Usar sempre os mesmos termos do domínio. Glossário oficial:

| Português (UI) | Código |
|---|---|
| Empresa (dados do consultório) | `Company` |
| Conta / Conta caixa | `Account` |
| Lançamento | `Transaction` |
| Receita / Despesa | `Income` / `Expense` |
| Transferência (pernas de saída/entrada) | `Transfer` (`TRANSFER_OUT` / `TRANSFER_IN`) |
| Situação (pendente / pago / cancelado) | `TransactionStatus` (`PENDING` / `PAID` / `CANCELLED`) |
| Forma de pagamento | `PaymentMethod` |
| Categoria / Subcategoria | `Category` / `Subcategory` |
| Contato (paciente / fornecedor / convênio) | `Contact` + `ContactRole` (`PATIENT` / `SUPPLIER` / `INSURER` / `OTHER`) |
| Recibo | `Receipt` |
| DRE | `IncomeStatement` |
| Regime de caixa / competência | `CashBasis` / `AccrualBasis` |
| Data de competência / vencimento / pagamento | `accrual_date` / `due_date` / `paid_date` |
| Parcela / Parcelamento | `Installment` / `InstallmentGroup` |
| Recorrência | `Recurrence` |
| Importação de planilha / lote importado | `SpreadsheetImport` / `ImportBatch` |
| Saldo | `Balance` |
| Cartão de crédito / Fatura do cartão | `CreditCard` / `CardStatement` (não `Invoice`: evita confusão com nota fiscal) |
| Nota fiscal de serviço (NFS-e) | `ServiceInvoice` (só se um dia existir) |
| Orçamento / Meta | `Budget` / `Goal` |

Termo novo do domínio entra nesta tabela antes de aparecer no código. Caixa dos nomes segue o Python:
`snake_case` para funções/variáveis/módulos, `PascalCase` para classes, `UPPER_CASE` para constantes e
membros de `Enum`.

## Nomes

- Nomes revelam intenção: `mark_as_paid`, `monthly_expenses_by_category`;
  evitar `data`, `info`, `manager`, `helper`, `utils`, `tmp`, `x`.
- Booleanos como pergunta: `is_paid`, `has_installments`.
- Sem abreviações obscuras; sem números mágicos (`DEFAULT_AUTO_LOCK_MINUTES = 3`).

## Funções e classes

- Uma responsabilidade por função; se precisa de "e" para descrever, divida.
- Funções curtas (referência: até ~30 linhas) e com poucos parâmetros (até 3–4; mais que isso, use
  um objeto de parâmetros / dataclass).
- Sem efeitos colaterais escondidos: uma função chamada `get_` não grava nada.
- Retornos antecipados em vez de `if` aninhado.
- Prefira composição a herança; no domínio, `@dataclass(frozen=True, slots=True)`.

## Tipos

- `mypy --strict` sem exceções globais; `Any` só com justificativa em comentário.
- Value objects para conceitos do domínio (`Money`, `AccountId`, `DateRange`) em vez de primitivos
  soltos — evita trocar centavos por reais ou um ID por outro (`NewType` para IDs).
- `Enum` (`StrEnum`) para conjuntos fechados (situação, forma de pagamento, papel do contato).
- Nunca `float` para dinheiro (ver `backend-architecture`).

## Erros

- Erros explícitos e tipados; nunca engolir exceção (`except: pass` e `except Exception: pass` proibidos).
- Tratar o erro no nível que sabe o que fazer com ele; nos demais, deixar subir.
- Mensagens de erro úteis, sem dados sensíveis (ver `security`).

## Comentários

- O código explica o *quê*; comentário explica o *porquê* (regra de negócio, decisão, limitação externa).
- Sem código comentado, sem comentário que repete o código.
- `TODO` só com contexto e referência (`TODO(#12): ...`).

## Simplicidade

- YAGNI: não criar abstração para uma necessidade que ainda não existe — **exceto** as definidas nas
  skills de arquitetura (camadas, repositórios, unit of work, outbox), que são decisões do projeto.
- Sem código morto; sem duplicação de regra de negócio.
- Mudanças pequenas e focadas; refatoração separada de mudança de comportamento.

## Testes

- Toda regra de negócio nova vem com teste. Bug corrigido vem com teste que reproduzia o bug.
- Estrutura Arrange / Act / Assert; um comportamento por teste.
- Nome do teste descreve o comportamento: `test_installments_sum_equals_total_when_amount_not_divisible`.
- Testes rápidos, determinísticos, sem rede e sem relógio real (usar `Clock` fake).
- Dados de teste sintéticos — **nunca** dados financeiros reais **nem dados de pacientes**.
- `hypothesis` para regras com muitas combinações (parcelas, arredondamento, datas de fim de mês).

## Ferramentas

- Formatador e linter rodando no pre-commit e no CI; o CI falha se houver aviso.
- Commits no padrão **Conventional Commits** (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`,
  `chore:`, `security:`), um assunto por commit. (`security:` é um tipo extra do projeto; se usarmos
  commitlint, ele precisa estar na configuração.)

## Definição de pronto

- [ ] Roda, sem avisos de ruff e mypy.
- [ ] Testes novos e antigos passando.
- [ ] Segue as skills de arquitetura e o checklist de `security` quando aplicável.
- [ ] Sem segredos, sem dados reais, sem código morto.
- [ ] Mudança de esquema: migração testada, com backup prévio automático.
- [ ] Documentação/glossário atualizados se o comportamento mudou.

## Adaptação à stack

- `uv run ruff format` + `uv run ruff check` (incluindo regras `S`, `B`, `UP`, `SIM`, `N`).
- `uv run mypy --strict src`.
- `uv run pytest` (+ `pytest-qt`, `hypothesis`, `pytest-cov`).
- `pre-commit` com ruff, mypy, gitleaks.
- *Configuração exata no `pyproject.toml`: definir na fase 0.*

## Skills relacionadas

`backend-architecture`, `frontend-architecture`, `repository-pattern`, `security`, `dominio-consultorio`.
