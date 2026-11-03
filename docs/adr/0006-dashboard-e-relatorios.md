# ADR-0006 — Início, DRE e relatórios (fase 1, incremento 1.4)

- **Data:** 03/11/2026
- **Status:** aceito

## Decisões

1. **Gráfico próprio (QPainter)** em vez do QtCharts: o QtCharts exige o pacote `pyside6-addons`,
   que aumentaria bastante o instalador e a superfície de dependências, para um gráfico de barras
   simples. O gráfico respeita "Ocultar valores" (eixo e dicas sem quantias) e usa só inteiros
   para escala e rótulos (sem `float` com dinheiro).
2. **Início**: cartões do mês (recebido, pago, saldo com cor pelo sinal, a receber, a pagar),
   gráfico de 12 meses (pagamentos efetivos), saldo das contas até hoje com total, e as vencidas a
   receber/pagar (até 8 itens, com total e atalho para a tela completa).
3. **Relatórios** em abas: DRE (mensal/anual, caixa ou competência, "% da receita bruta"),
   totais por categoria (quantidade, total e participação) e vencidas (dias de atraso, filtro).
4. **Percentuais com inteiros**, arredondando sobre o valor absoluto (a divisão inteira do Python
   arredonda negativos para baixo; o teste pegou "-5,1%" no lugar de "-5,0%").
