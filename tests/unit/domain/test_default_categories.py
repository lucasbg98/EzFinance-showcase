import pytest

from appfin.domain.default_categories import default_categories
from appfin.domain.enums import CategoryKind, DreGroup, TaxRegime

# Bloco "Impostos" da planilha do consultório (plano de importação §4, decisão P19).
TAX_BLOCK = {
    "Outros impostos e taxas",
    "INSS e FGTS",
    "Contador",
    "CRO e anuidades",
    "Laudos e saúde ocupacional",
    "Tarifas bancárias",
    "Taxas de cartão/maquininha",
    "Controle de esterilização",
}


def _by_group(regime: TaxRegime) -> dict[DreGroup, set[str]]:
    return {dre: set(children) for _name, _kind, dre, children in default_categories(regime)}


@pytest.mark.parametrize("regime", list(TaxRegime))
def test_taxes_group_holds_the_whole_tax_block_in_every_regime(regime: TaxRegime) -> None:
    groups = _by_group(regime)

    assert groups[DreGroup.TAXES] >= TAX_BLOCK
    for dre, children in groups.items():
        if dre is not DreGroup.TAXES:
            assert not TAX_BLOCK & children, dre


def test_investments_group_exists_with_expense_categories() -> None:
    investments = [g for g in default_categories(TaxRegime.SIMPLES) if g[2] is DreGroup.INVESTMENTS]

    assert len(investments) == 1
    _name, kind, _dre, children = investments[0]
    assert kind is CategoryKind.EXPENSE
    assert "Cursos e capacitação" in children


@pytest.mark.parametrize("regime", list(TaxRegime))
def test_names_are_unique_and_fit_the_column(regime: TaxRegime) -> None:
    names = [name for name, *_ in default_categories(regime)]
    for _name, _kind, _dre, children in default_categories(regime):
        names.extend(children)

    assert len(names) == len(set(names))
    assert all(1 <= len(name) <= 60 for name in names)


def test_every_dre_group_has_a_default_group() -> None:
    used = {dre for _name, _kind, dre, _children in default_categories(TaxRegime.SIMPLES)}

    assert used == set(DreGroup)
