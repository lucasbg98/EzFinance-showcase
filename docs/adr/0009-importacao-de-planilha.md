# ADR-0009 — Importação da planilha "Fluxo de caixa" (fase 1, incremento 1.7)

- **Data:** 04/11/2026
- **Status:** aceito

## Contexto

O consultório controla as finanças numa planilha "Fluxo de caixa" em **matriz mensal** (linhas de
receita/despesa × 12 meses), não numa lista de lançamentos. Ela é a carga inicial de 2026 e pode
precisar ser reimportada até o app substituí-la. O plano aprovado (P1–P21) está em
plano de importação; o resumo para o projeto, em `docs/PROJETO.md` §8.4. A planilha é
entrada não confiável (T4) e contém nomes de pessoas e valores reais.

## Decisões

1. **Importador de matriz mensal, não genérico.** A estrutura da planilha é descrita como dados
   (`cash_flow_layout.py`: âncoras de total e blocos, só rótulos genéricos). O assistente genérico
   por colunas (§8.1 a 8.3) fica para depois.
2. **A própria planilha prova a importação.** Os 11 totais são recalculados e comparados mês a mês,
   assim como o DRE do app (Impostos, Investimentos e Resultado). Qualquer erro bloqueia: não há
   importação parcial. Impostos e Investimentos diferentes só geram aviso, porque dependem do grupo
   do DRE que a usuária pode trocar por orientação do contador.
3. **Nada de dado real no código.** O perfil padrão casa palavras-chave genéricas e blocos; o que é
   específico (linhas com nomes próprios) a usuária escolhe uma vez, e a escolha fica no perfil, no
   banco cifrado. O nome do arquivo não é guardado nem logado; o conteúdo é identificado pelo
   SHA-256.
4. **Leitura segura em duas partes.** `openpyxl` em `read_only` + `data_only` para os valores, com
   `defusedxml` obrigatório; como o modo `read_only` não lê comentários, uma segunda leitura (também
   com `defusedxml`, sem DTD, com limites) pega só os comentários e detecta fórmulas sem valor
   calculado. Limites de tamanho, de conteúdo descompactado, de linhas, colunas e comentários.
5. **Identidade de cada célula** (`import_row_key` = SHA-256 de perfil | ano-mês | chave da linha),
   com índice único entre os lançamentos não excluídos: a mesma célula nunca entra duas vezes.
6. **O app nunca apaga trabalho feito nele.** Lançamento com recibo ou com `version` acima da de
   importação é mantido na reimportação e impede o desfazer. Desfazer uma substituição (exclusão
   lógica + restauração) soma 2 à versão sem a usuária mexer; isso é descontado.
7. **Desfazer por lote**, com o registro do que cada lote substituiu (`import_replacement`); só a
   importação mais recente de cada ano pode ser desfeita.
8. **Prévia e confirmação na thread da interface.** A conexão do banco é única e só a thread da
   interface a usa (skill `concurrency`); a leitura do arquivo, que é a parte pesada, roda num
   worker. A confirmação recebe a impressão digital da prévia e recalcula tudo dentro da transação.
9. **Assistente como página**, não modal: ao bloquear o app, a tela é destruída com a planilha em
   memória e nada é gravado.

## Consequências

- Reimportar a planilha corrigida é seguro e idempotente; a usuária vê antes o que muda.
- Uma planilha de outro formato não é aceita: exige um novo layout (ou o assistente genérico).
- Nova dependência `defusedxml` (versão exata, hash no `uv.lock`).
- Gravação de ~5 mil células leva ~2 s (inserção no banco cifrado com índices); a planilha real tem
  ~400 células.
