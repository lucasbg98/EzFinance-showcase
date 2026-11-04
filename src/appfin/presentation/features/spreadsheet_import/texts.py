"""Textos do assistente de importação num só lugar."""

from __future__ import annotations

from appfin.application.spreadsheet_import import LineSource
from appfin.domain.enums import ImportSource, TransactionKind
from appfin.domain.spreadsheet_import import cash_flow_layout as layout
from appfin.domain.spreadsheet_import.monthly_matrix import IssueLevel, MonthStatus
from appfin.domain.spreadsheet_import.reconcile import ReconcileAction

ACTION_LABELS = {
    ReconcileAction.CREATE: "Novo",
    ReconcileAction.SKIP: "Já importado",
    ReconcileAction.REPLACE: "Substituir",
    ReconcileAction.KEEP: "Manter o do app",
    ReconcileAction.REMOVE: "Remover",
}
ACTION_COLORS = {
    ReconcileAction.CREATE: "#027A48",
    ReconcileAction.REPLACE: "#B54708",
    ReconcileAction.REMOVE: "#B42318",
    ReconcileAction.KEEP: "#475467",
}
SOURCE_LABELS = {
    LineSource.PROFILE: "Escolha salva",
    LineSource.CHOICE: "Escolhida agora",
    LineSource.RULE: "Regra do app",
    LineSource.BLOCK: "Sugerida pelo bloco: confira",
    LineSource.MISSING: "Escolha a categoria",
}
MONTH_STATUS_LABELS = {
    MonthStatus.REALIZED: "Realizado (pago)",
    MonthStatus.PROJECTION: "Projeção (pendente)",
    MonthStatus.EMPTY: "Fora da importação",
}
LEVEL_LABELS = {IssueLevel.ERROR: "Erro", IssueLevel.WARNING: "Aviso"}
KIND_LABELS = {TransactionKind.INCOME: "Receita", TransactionKind.EXPENSE: "Despesa"}
SOURCE_FILE_LABELS = {ImportSource.XLSX: "Excel (.xlsx)", ImportSource.CSV: "CSV"}
BLOCK_LABELS = {
    layout.REVENUE: "Receitas",
    layout.DENTISTS: "Dentistas",
    layout.PROSTHETICS: "Protéticos",
    layout.MISCELLANEOUS: "Diversos",
    layout.DENTAL_SUPPLIES: "Material odontológico",
    layout.FIXED: "Custos fixos",
    layout.SALARIES: "Salários",
    layout.TAXES: "Impostos",
    layout.INVESTMENTS: "Investimentos",
    layout.NON_OPERATING: "Não operacionais",
}
DRE_CHECK_LABELS = {
    "TOTAL DE IMPOSTOS": "(-) Impostos",
    "INVESTIMENTOS": "(-) Investimentos",
    "LUCRO TOTAL FINAL": "(=) Resultado do período",
}
TOTAL_LABELS = {
    "RECEITA TOTAL": "Receita total",
    "TOTAL DENTISTAS": "Total dentistas",
    "TOTAL PROTETICOS": "Total protéticos",
    "TOTAL DIVERSOS": "Total diversos",
    "TOTAL MATERIAL ODONTOLOGICO": "Total material odontológico",
    "CUSTOS VARIAVEIS": "Custos variáveis",
    "TOTAL SALARIOS": "Total salários",
    "TOTAL DE IMPOSTOS": "Total de impostos",
    "CUSTOS FIXOS": "Custos fixos",
    "INVESTIMENTOS": "Investimentos",
    "LUCRO TOTAL FINAL": "Lucro total final",
}
OK_MARK = "✓ confere"
FAIL_MARK = "✗ não confere"

INTRO = (
    'Importa a planilha "Fluxo de caixa" do consultório: cada valor mensal de uma linha vira um '
    "lançamento no último dia do mês (pago nos meses realizados e pendente nos de projeção). "
    "Os totais da própria planilha são conferidos antes de gravar."
)
FILE_HELP = (
    "Prefira o arquivo do Excel (.xlsx): ele traz os comentários das células, que viram a "
    "observação do lançamento. O .csv também funciona, mas sem os comentários. "
    "O arquivo só é lido: nada nele é executado nem alterado."
)
CATEGORIES_HELP = (
    'Confira a categoria de cada linha. Dê duplo clique (ou use "Alterar linha…") para trocar a '
    "categoria ou a descrição. As escolhas ficam salvas para as próximas importações."
)
PREVIEW_HELP = (
    "Nada foi gravado ainda. Substituições e remoções vêm marcadas: dê duplo clique numa delas "
    "para manter o lançamento que está no app."
)
UNDO_HELP = (
    "Desfazer exclui os lançamentos da importação e devolve os que ela substituiu. Só a "
    "importação mais recente de cada ano pode ser desfeita."
)


def block_label(block: str) -> str:
    return BLOCK_LABELS.get(block, block)
