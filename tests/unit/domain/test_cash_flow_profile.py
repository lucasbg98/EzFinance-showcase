"""Perfil padrão: cada linha da planilha sintética ganha uma categoria (plano de importação §4)."""

from __future__ import annotations

import pytest

from appfin.domain.enums import DreGroup, PaymentMethod, TransactionKind
from appfin.domain.spreadsheet_import.cash_flow_layout import CASH_FLOW_LAYOUT
from appfin.domain.spreadsheet_import.cash_flow_profile import (
    FROM_LABEL,
    RuleSource,
    line_kind,
    suggest,
)
from appfin.domain.spreadsheet_import.monthly_matrix import MatrixLine, read_monthly_matrix
from tests.spreadsheet_fixtures import cash_flow_fixture


def _lines() -> dict[str, MatrixLine]:
    reading = read_monthly_matrix(cash_flow_fixture().sheet(), CASH_FLOW_LAYOUT)
    return {line.key: line for line in reading.lines}


def _line(block: str, label: str) -> MatrixLine:
    return next(line for line in _lines().values() if line.block == block and line.label == label)


def test_every_line_of_the_layout_has_a_suggestion() -> None:
    missing = [line.row for line in _lines().values() if suggest(line) is None]

    assert missing == []


@pytest.mark.parametrize(
    ("block", "label", "name", "group", "method"),
    [
        (
            "receitas",
            "CARTÃO CRÉDITO",
            "Tratamentos particulares",
            DreGroup.GROSS_REVENUE,
            PaymentMethod.CREDIT,
        ),
        (
            "receitas",
            "CARTÃO DÉBITO",
            "Tratamentos particulares",
            DreGroup.GROSS_REVENUE,
            PaymentMethod.DEBIT,
        ),
        (
            "receitas",
            "PIX / DOC",
            "Tratamentos particulares",
            DreGroup.GROSS_REVENUE,
            PaymentMethod.PIX,
        ),
        (
            "receitas",
            "CHEQUES A PRAZO",
            "Tratamentos particulares",
            DreGroup.GROSS_REVENUE,
            PaymentMethod.CHECK,
        ),
        ("receitas", "DEVOLUÇÃO DE CRÉDITO", "Devoluções a pacientes", DreGroup.DEDUCTIONS, None),
        ("receitas", "DISTRIBUIÇÃO DE SOBRAS", "Rendimentos", DreGroup.OTHER_RESULTS, None),
        ("diversos", "TÁXI ENCOMENDA", "Correios e entregas", DreGroup.OPERATING_EXPENSES, None),
        ("custos_fixos", "MARKETING", "Marketing", DreGroup.SELLING_EXPENSES, None),
        ("impostos", "DAS / SIMPLES", "Simples Nacional (DAS)", DreGroup.TAXES, None),
        (
            "impostos",
            "TARIFA CARTÃO DE CRÉDITO",
            "Taxas de cartão/maquininha",
            DreGroup.TAXES,
            None,
        ),
        (
            "impostos",
            "ALUGUEL MÁQUINA DE CARTÃO",
            "Taxas de cartão/maquininha",
            DreGroup.TAXES,
            None,
        ),
        ("impostos", "TARIFAS BANCÁRIAS", "Tarifas bancárias", DreGroup.TAXES, None),
        ("impostos", "IMPOSTO DE RENDA FÍSICA", "IR pessoa física", DreGroup.TAXES, None),
        ("impostos", "CRO", "CRO e anuidades", DreGroup.TAXES, None),
        ("investimentos", "CURSOS", "Cursos e capacitação", DreGroup.INVESTMENTS, None),
        ("salarios", "PRÓ-LABORE SÓCIA FICTÍCIA", "Pró-labore", DreGroup.OPERATING_EXPENSES, None),
    ],
)
def test_keyword_rules(
    block: str, label: str, name: str, group: DreGroup, method: PaymentMethod | None
) -> None:
    suggestion = suggest(_line(block, label))

    assert suggestion is not None
    assert suggestion.source is RuleSource.RULE
    assert (suggestion.target.name, suggestion.target.dre_group) == (name, group)
    assert suggestion.target.payment_method is method


def test_homogeneous_blocks_suggest_by_block() -> None:
    suggestion = suggest(_line("dentistas", "DENTISTA FICTÍCIA A"))
    thirteenth = suggest(next(line for line in _lines().values() if "13O SALARIO" in line.key))

    assert suggestion is not None and suggestion.source is RuleSource.BLOCK
    assert suggestion.target.name == "Repasse a dentista parceiro"
    assert thirteenth is not None and thirteenth.target.name == "Salários"


def test_partner_lines_take_the_category_name_from_the_sheet() -> None:
    """§5.2: o nome da outra sócia nunca está no código; vem do rótulo da linha."""
    received = suggest(_line("receitas", "RECEBIDOS SÓCIA FICTÍCIA"))
    general = suggest(_line("diversos", "SÓCIA FICTÍCIA - GERAL"))

    assert received is not None and received.target.name == FROM_LABEL
    assert received.target.dre_group is DreGroup.OTHER_RESULTS
    assert general is not None and general.target.name == FROM_LABEL
    assert general.target.dre_group is DreGroup.DIRECT_COSTS


def test_unknown_line_in_a_mixed_block_has_no_suggestion() -> None:
    line = _line("diversos", "CORREIOS")
    unknown = MatrixLine(
        line.row,
        "ITEM DESCONHECIDO",
        "diversos|ITEM DESCONHECIDO",
        "diversos",
        "",
        1,
        line.amounts,
        line.comments,
    )

    assert suggest(unknown) is None


def test_kinds_follow_the_sheet_signs() -> None:
    assert line_kind(_line("receitas", "DINHEIRO")) is TransactionKind.INCOME
    assert line_kind(_line("receitas", "DEVOLUÇÃO DE CRÉDITO")) is TransactionKind.EXPENSE
    assert line_kind(_line("nao_operacionais", "ENTRADAS NÃO OPERACIONAIS")) is (
        TransactionKind.INCOME
    )
    assert line_kind(_line("nao_operacionais", "SAÍDAS NÃO OPERACIONAIS")) is (
        TransactionKind.EXPENSE
    )
    assert line_kind(_line("impostos", "CRO")) is TransactionKind.EXPENSE
