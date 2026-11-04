"""Estrutura da planilha "Fluxo de caixa" do consultório (plano de importação §2.3).

Só rótulos **genéricos** de total/indicador (nunca nomes de pessoas ou fornecedores: §5.3).
As linhas de detalhe são reconhecidas pelo bloco em que estão; a categoria vem do perfil (1.7.5).

Conferência: cada total abaixo deve ser igual à soma das linhas de detalhe dos blocos indicados,
mês a mês (a linha "Devolução de crédito" é subtraída da receita, como na fórmula da planilha).
O "Lucro total final" confere tudo (receitas menos todos os custos, mais as entradas e menos as
saídas não operacionais): é a única conferência que cobre o bloco não operacional. Os demais
indicadores (margem, %, lucros intermediários, ponto de equilíbrio) só delimitam blocos.
"""

from __future__ import annotations

from appfin.domain.spreadsheet_import.monthly_matrix import Anchor, Block, MatrixLayout

REVENUE = "receitas"
DENTISTS = "dentistas"
PROSTHETICS = "proteticos"
MISCELLANEOUS = "diversos"
DENTAL_SUPPLIES = "material_odontologico"
FIXED = "custos_fixos"
SALARIES = "salarios"
TAXES = "impostos"
INVESTMENTS = "investimentos"
NON_OPERATING = "nao_operacionais"

CREDIT_REFUND = "DEVOLUCAO DE CREDITO"
NON_OPERATING_EXITS = "SAIDAS NAO OPERACIONAIS"
EXPENSE_BLOCKS = (
    DENTISTS,
    PROSTHETICS,
    MISCELLANEOUS,
    DENTAL_SUPPLIES,
    FIXED,
    SALARIES,
    TAXES,
    INVESTMENTS,
)

CASH_FLOW_LAYOUT = MatrixLayout(
    name="Fluxo de caixa (matriz mensal)",
    first_block=REVENUE,
    revenue_block=REVENUE,
    blocks=(
        Block(REVENUE, subtract=frozenset({CREDIT_REFUND})),
        Block(DENTISTS),
        Block(PROSTHETICS),
        Block(MISCELLANEOUS),
        Block(DENTAL_SUPPLIES),
        Block(FIXED),
        Block(SALARIES),
        Block(TAXES),
        Block(INVESTMENTS),
        Block(NON_OPERATING, subtract=frozenset({NON_OPERATING_EXITS})),
    ),
    anchors=(
        Anchor("RECEITA TOTAL", checks=(REVENUE,)),
        Anchor("TOTAL DENTISTAS", opens=DENTISTS, checks=(DENTISTS,)),
        Anchor("TOTAL PROTETICOS", opens=PROSTHETICS, checks=(PROSTHETICS,)),
        Anchor("TOTAL DIVERSOS", opens=MISCELLANEOUS, checks=(MISCELLANEOUS,)),
        Anchor("TOTAL MATERIAL ODONTOLOGICO", opens=DENTAL_SUPPLIES, checks=(DENTAL_SUPPLIES,)),
        Anchor(
            "CUSTOS VARIAVEIS",
            checks=(DENTISTS, PROSTHETICS, MISCELLANEOUS, DENTAL_SUPPLIES),
        ),
        Anchor("MARGEM DE CONTRIBUICAO"),
        Anchor("%", opens=FIXED),  # custos fixos avulsos vêm logo depois da linha do %
        Anchor("TOTAL SALARIOS", opens=SALARIES, checks=(SALARIES,)),
        Anchor("TOTAL DE IMPOSTOS", opens=TAXES, checks=(TAXES,)),
        Anchor("CUSTOS FIXOS", checks=(FIXED, SALARIES, TAXES)),
        Anchor("LUCRO ANTES DOS INVESTIMENTOS", opens=INVESTMENTS),
        Anchor("INVESTIMENTOS", checks=(INVESTMENTS,)),
        Anchor("LUCRO OPERACIONAL", opens=NON_OPERATING),
        Anchor("LUCRO TOTAL FINAL", checks=(REVENUE, NON_OPERATING), minus=EXPENSE_BLOCKS),
        Anchor("PONTO DE EQUILIBRIO"),
    ),
)
