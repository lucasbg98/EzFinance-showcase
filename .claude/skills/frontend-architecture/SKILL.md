---
name: frontend-architecture
description: Arquitetura da interface desktop (PySide6/Qt Widgets) do app financeiro do consultório — telas por funcionalidade, MVVM, estado, formulários, formatação pt-BR, tabelas model/view, gráficos QtCharts, tema, acessibilidade e UX de dados sensíveis (ocultar valores, bloqueio). Use ao criar ou alterar qualquer tela, widget, view model, navegação, formulário, tabela ou gráfico.
---

# Arquitetura do frontend (interface desktop Qt)

## Princípio central

**A tela só mostra e coleta dados.** Regra de negócio fica no domínio, orquestração nos casos de uso
(ver `backend-architecture`). A interface nunca acessa banco, nuvem, arquivos ou criptografia diretamente.

```
View (QWidget)  ←→  ViewModel (QObject + signals)  →  caso de uso (application)
  só layout          estado da tela, validação          regra e persistência
                     de formulário, formatação
```

## Organização

- Padrão **MVVM**: cada tela tem uma view sem lógica e um view model (`QObject` com propriedades e
  signals) testável sem abrir janela.
- Pastas **por funcionalidade** (decisão D7), em `src/appfin/presentation/features/`:
  `dashboard/`, `transactions/`, `contacts/`, `categories/`, `accounts/`, `company/`,
  `income_statement/` (DRE), `reports/`, `receipts/`, `spreadsheet_import/`, `backup/`, `lock/`,
  `settings/` — cada uma com suas views, view models e componentes próprios.
  Componentes reutilizáveis em `presentation/shared/ui/`. Nomes de pacote em `snake_case`.
- Navegação centralizada (`presentation/navigation.py`), não telas abrindo telas diretamente.
  Janela principal com menu lateral + abas.

## Estado

- Uma fonte da verdade por dado: o estado da tela vem do view model, que vem dos casos de uso.
- Depois de uma alteração, atualizar a partir do resultado do caso de uso (ou de um signal
  "dados mudaram"), não "adivinhar" o novo estado na tela.
- Toda tela trata explicitamente quatro estados: **carregando, vazio, erro e com dados**.
- Operações demoradas (importar planilha, gerar PDF/relatório, backup) nunca travam a interface:
  rodam fora da thread de UI com progresso e opção de cancelar (ver `concurrency`).

## Formulários e entrada de valores

- Validação imediata e amigável no view model (obrigatório, valor > 0, data válida, CPF/CNPJ com
  dígito verificador); a validação definitiva continua no domínio/caso de uso.
- Campo de dinheiro (`MoneyEdit`) com máscara pt-BR (`R$ 1.234,56`), convertendo para centavos
  inteiros sem passar por float.
- Datas no formato `dd/mm/aaaa` (`DateEdit` com calendário); locale pt-BR.
- Atalhos de teclado para as ações frequentes (novo lançamento, salvar, buscar, **bloquear `Ctrl+L`**)
  e navegação completa só com teclado.
- Ações destrutivas (excluir em lote, desfazer importação, restaurar backup) pedem confirmação e,
  quando possível, oferecem **desfazer**.
- O parcelamento é calculado pelo **caso de uso**; o formulário só mostra a prévia que ele devolve.

## Formatação

- Toda formatação de moeda, número, data e porcentagem passa por um único módulo (`shared/formatting.py`,
  locale pt-BR). Nada de formatar "na mão" dentro dos widgets.
- Despesas/valores negativos com cor **e** sinal ou ícone (não depender só de cor).

## Dados sensíveis na interface

- **Botão global "Ocultar valores"** (mostra `R$ •••••`) **já no MVP** (decisão D8), com opção de abrir o
  app com os valores ocultos. Implementado no módulo de formatação, para valer em todas as telas,
  gráficos e tooltips.
- Bloqueio automático (3 min, ao bloquear o Windows e ao suspender) leva para a tela de desbloqueio e
  **limpa** o estado das telas e os modelos de tabela (ver `security`).
- **Todo texto de dados (usuária, planilha, sync) é exibido como `Qt.TextFormat.PlainText`.** Nunca
  `setHtml` ou rich text com dados.
- Nunca exibir tokens, chaves ou detalhes técnicos de erro; mostrar mensagem amigável e um código de
  erro para consultar no log.
- Orientar a não colocar informação clínica nas descrições (texto de ajuda no formulário).

## Tabelas e listas

- Usar **model/view** do Qt: `QAbstractTableModel` + `QTableView` (renderiza só as linhas visíveis).
  **Não** usar `QTableWidget` para listas que crescem.
- Carregamento paginado com `canFetchMore`/`fetchMore`; ordenação e filtro pelo caso de uso
  (no banco), não em memória com milhares de linhas.

## Gráficos e relatórios

- Gráficos com **QtCharts**; recebem dados já agregados pelo caso de uso.
- Sempre com título, legenda, eixos rotulados, valores formatados em pt-BR e tooltip.
- Paleta consistente por categoria e contraste adequado nos temas claro e escuro.
- DRE e relatório por categoria com seletor **Caixa | Competência**.

## Visual e acessibilidade

- Design tokens centralizados (`presentation/theme/`: cores, espaçamentos, tipografia, raios) aplicados
  via QSS; tema claro (MVP) e escuro (fase 2). Ícones SVG próprios (nada copiado do app de referência).
- Contraste mínimo WCAG AA; foco visível; fontes escaláveis; `accessibleName` nos controles.

## Testes

- View models com testes unitários (estados, validação, formatação, ocultar valores).
- Testes de interface (pytest-qt) para os fluxos críticos: criar lançamento parcelado, marcar como
  recebido em lote, emitir recibo, importar planilha (prévia com erros), DRE caixa × competência,
  ocultar valores, bloquear/desbloquear.

## Anti-padrões a evitar

- Query ao banco ou chamada à nuvem dentro de widget.
- Regra de negócio duplicada na tela (ex.: calcular parcelas no formulário).
- `float` para valores digitados.
- Rich text/HTML com dados do usuário.
- `QTableWidget` com milhares de itens.

## Adaptação à stack

- PySide6 (Qt Widgets) + QSS; QtCharts; pytest-qt (`QT_QPA_PLATFORM=offscreen` no CI).
- *Componentes base (MoneyEdit, DateEdit, MonthNavigator, HideValuesToggle) e comando dos testes de UI:
  confirmar na fase 0.*

## Skills relacionadas

`backend-architecture`, `security`, `performance`, `concurrency`, `clean-code`, `dominio-consultorio`.
