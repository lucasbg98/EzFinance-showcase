from appfin.domain.enums import DreGroup
from appfin.domain.income_statement import (
    UNCLASSIFIED,
    GroupTotals,
    LineType,
    build_income_statement,
)


def _amounts(lines: list) -> dict[str, int]:  # type: ignore[type-arg]
    return {line.label: line.amount.cents for line in lines}


def test_statement_structure_and_totals() -> None:
    lines = build_income_statement(
        {
            DreGroup.GROSS_REVENUE: GroupTotals(inflow_cents=1_000_000),
            DreGroup.DEDUCTIONS: GroupTotals(outflow_cents=20_000),
            DreGroup.TAXES: GroupTotals(outflow_cents=60_000),
            DreGroup.DIRECT_COSTS: GroupTotals(outflow_cents=150_000),
            DreGroup.OPERATING_EXPENSES: GroupTotals(outflow_cents=400_000),
            DreGroup.SELLING_EXPENSES: GroupTotals(outflow_cents=30_000),
            DreGroup.OTHER_RESULTS: GroupTotals(inflow_cents=5_000, outflow_cents=2_000),
        }
    )
    amounts = _amounts(lines)

    assert amounts["(=) Receita líquida"] == 920_000
    assert amounts["(=) Lucro bruto"] == 770_000
    assert amounts["(=) Resultado operacional"] == 340_000
    assert amounts["(=) Resultado do período"] == 343_000
    assert lines[-1].line_type is LineType.RESULT


def test_unclassified_appears_and_counts_only_when_present() -> None:
    without = _amounts(build_income_statement({}))
    assert "(±) Não classificados" not in without
    assert without["(=) Resultado do período"] == 0

    with_unclassified = _amounts(
        build_income_statement(
            {
                DreGroup.GROSS_REVENUE: GroupTotals(inflow_cents=500),
                UNCLASSIFIED: GroupTotals(outflow_cents=200),
            }
        )
    )
    assert with_unclassified["(±) Não classificados"] == -200
    assert with_unclassified["(=) Resultado do período"] == 300


def test_result_equals_all_inflows_minus_all_outflows() -> None:
    totals = {
        group: GroupTotals(inflow_cents=(i + 1) * 1000, outflow_cents=(7 - i) * 300)
        for i, group in enumerate(DreGroup)
    }
    expected = sum(t.inflow_cents - t.outflow_cents for t in totals.values())

    lines = build_income_statement(totals)

    assert lines[-1].amount.cents == expected


def test_investments_come_after_operating_result_and_before_other_results() -> None:
    lines = build_income_statement(
        {
            DreGroup.GROSS_REVENUE: GroupTotals(inflow_cents=100_000),
            DreGroup.OPERATING_EXPENSES: GroupTotals(outflow_cents=30_000),
            DreGroup.INVESTMENTS: GroupTotals(outflow_cents=20_000),
            DreGroup.OTHER_RESULTS: GroupTotals(inflow_cents=1_000),
        }
    )
    labels = [line.label for line in lines]
    amounts = _amounts(lines)

    assert labels.index("(=) Resultado operacional") < labels.index("(-) Investimentos")
    assert labels.index("(-) Investimentos") < labels.index("(=) Resultado após investimentos")
    assert labels.index("(=) Resultado após investimentos") < labels.index(
        "(±) Resultado financeiro e diversos"
    )
    assert amounts["(=) Resultado operacional"] == 70_000
    assert amounts["(-) Investimentos"] == -20_000
    assert amounts["(=) Resultado após investimentos"] == 50_000
    assert amounts["(=) Resultado do período"] == 51_000
