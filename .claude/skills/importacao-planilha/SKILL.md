---
name: importacao-planilha
description: Regras da importação da planilha "Fluxo de caixa" do consultório (matriz mensal) — leitura segura de CSV/XLSX, layout por âncoras, perfil padrão linha → categoria, conferência dos totais e do DRE, reimportação sem duplicar, desfazer por lote e dados reais da planilha. Use ao mexer em domain/spreadsheet_import, infrastructure/importers, application/spreadsheet_import, na tela Importar planilha ou nos testes e fixtures de planilha.
---

# Importação de planilha

Decisões completas: plano de importação (P1–P21) e ADR-0009. Resumo para o projeto:
`docs/PROJETO.md` §8.4. Guia da usuária: `docs/IMPORTACAO.md`.

## Onde fica cada coisa

| Camada | Arquivo | Responsabilidade |
|---|---|---|
| infraestrutura | `infrastructure/importers/safe_reader.py` | Arquivo → `SpreadsheetFile` (grade de valores + comentários). Só limites e conversão de tipos, sem regra |
| domínio | `domain/spreadsheet_import/grid.py`, `parse.py` | Tipos da grade; pt-BR → `Decimal` → centavos; rótulos, meses, comentários, `cell_key` |
| domínio | `monthly_matrix.py` + `cash_flow_layout.py` | Layout por âncoras e blocos; linhas de detalhe, situação dos meses, conferência dos totais |
| domínio | `cash_flow_profile.py` | Perfil padrão: palavra-chave/bloco → categoria (nome + grupo do DRE), tipo da linha |
| domínio | `reconcile.py` | Criar / pular / substituir / manter / remover |
| aplicação | `application/spreadsheet_import.py` | Prévia, confirmação (backup + transação única), desfazer, histórico |
| interface | `presentation/features/spreadsheet_import/` | Assistente em página + histórico; `ImportWizardModel` sem Qt |

## Regras que não podem quebrar

1. **Nenhum dado real** (nome de pessoa/fornecedor, valor, comentário) em código, testes, docs ou
   logs. O perfil padrão só tem **rótulos genéricos**; o que é específico vai para o perfil no banco
   cifrado. Arquivos reais ficam em `local-data/planilhas/` (ignorado pelo git). Ao analisar um
   arquivo real, imprima **só contagens e números de linha**.
2. **Planilha é hostil** (skill `security` §6): `defusedxml` obrigatório; `openpyxl` com
   `read_only=True, data_only=True, keep_links=False, keep_vba=False`; limites de tamanho, de
   conteúdo descompactado, de abas, linhas, colunas, células e comentários; NUL e controles
   recusados; o nome do arquivo nunca vai para log nem para o banco (só o SHA-256).
3. **Dinheiro:** `float` do XLSX vira `Decimal(repr(float))` na borda; detalhe com mais de 2 casas
   (além do ruído < 0,000001) é erro; totais são arredondados para centavos só para comparar.
4. **"Sem erros":** célula inválida, total que não confere ou Resultado do DRE diferente da planilha
   **bloqueiam**. Nunca há importação parcial. Mensagens de erro não repetem o conteúdo da célula.
5. **Identidade da célula:** `import_row_key = sha256(perfil | ano-mês | chave da linha)`; a chave da
   linha é `bloco|RÓTULO NORMALIZADO` (+ linha "dona" se o rótulo se repete no bloco). Não dependa da
   posição da linha: inserir uma linha na planilha não pode mudar as chaves.
6. **O app nunca apaga trabalho feito nele:** "alterado no app" = recibo ou `version` acima de
   `untouched_version(restaurações)`. A reimportação mantém; o desfazer bloqueia.
7. **Confirmação:** recalcula a prévia dentro da unit of work e exige a mesma impressão digital;
   backup antes; lançamentos, categorias novas/movidas, perfil, lote, substituições e `outbox` numa
   só transação.
8. **Interface:** texto da planilha sempre `PlainText`; valores via `format_money` (respeita "Ocultar
   valores"); leitura do arquivo em worker; o banco só na thread da interface.

## Mudou a planilha?

- Linha nova com rótulo genérico → regra em `cash_flow_profile.py` (com teste em
  `tests/unit/domain/test_cash_flow_profile.py`).
- Linha com nome próprio → **não** vai para o código: a usuária escolhe no assistente.
- Total ou bloco novo → âncora em `cash_flow_layout.py` e a fixture sintética em
  `tests/spreadsheet_fixtures.py` (o layout completo de 106 linhas).
- Outro formato de planilha → novo `MatrixLayout` (ou o assistente genérico da §8.1, ainda não feito).

## Testes

- Fixture sintética com o layout completo (`cash_flow_fixture`, `write_xlsx`, `write_csv`,
  `sheet_file`, `with_unknown_line`); nomes, valores e comentários inventados.
- Casos de abuso no leitor (zip bomb, XML bomb em cada parte, XXE, `.xls` disfarçado, limites).
- Canário de log: nada da fixture (rótulos, valores, comentários, nome do arquivo) no log.
- Integração no SQLCipher real: DRE do app = linhas de Impostos, Investimentos e Lucro total final.
- Autoteste do executável (`self_test._check_spreadsheet_import`) lê uma planilha mínima.

## Skills relacionadas

`security`, `dominio-consultorio`, `repository-pattern`, `concurrency`, `frontend-architecture`.
