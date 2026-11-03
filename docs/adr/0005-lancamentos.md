# ADR-0005 — Contas a receber e a pagar (fase 1, incremento 1.3)

- **Data:** 03/11/2026
- **Status:** aceito

## Decisões

1. **Uma página para receber e pagar** (`TransactionsPage`), parametrizada pelo tipo; textos em
   `labels.py`. Estado e regras de tela num **view model** (`TransactionsViewModel`), testável sem
   janela — cumpre a skill `frontend-architecture` para telas com regras.
2. **Filtros**: mês (navegador), conta, situação (todas/pendentes/vencidas/pagas) e busca (descrição,
   documento, contato). "Vencida" continua calculada. Resumo do mês em cartões que respeitam
   "Ocultar valores".
3. **Formulário de lançamento**: parcelamento com prévia ao vivo (mesma regra do domínio);
   competência padrão = hoje (data do atendimento/compra) e comum às parcelas; "já recebido/pago"
   quita a 1ª parcela; contato com busca por trecho e cadastro rápido; categorias filtradas pelo
   tipo, mostradas como "Grupo / Categoria". Na edição, só a parcela escolhida muda.
4. **Ações em lote**: receber/pagar (data + conta opcional), desfazer baixa e excluir (com
   confirmação). Atalhos: Ctrl+N, Delete e Enter.
5. **`SearchCombo`** recusa texto digitado que não existe na lista (evita gravar algo diferente do
   que a usuária vê).
6. **Modais com corpo rolável e ajuste à altura do conteúdo** (até 90% da tela): o Qt limita a
   altura automática a ~2/3 da tela e cortava o campo de observações.

## Problemas encontrados pela revisão visual

- Campo numérico invisível: `setButtonSymbols(NoButtons)` + regra do tema que zera a largura das
  setas deixavam o editor com 1 px. Mantida só a regra do tema; teste de regressão criado.
- Regra de borda/espaçamento dos campos de texto afetava o editor interno de combos e campos
  numéricos; neutralizada para os editores internos.
- Destaque de erro ia para o contêiner (combo + botão), sem borda visível; agora vai ao controle.
- Método `create` sobrescrevia `QWidget.create()` (apontado pelo mypy); renomeado.
