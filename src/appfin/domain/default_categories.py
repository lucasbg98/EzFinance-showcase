"""Categorias padrão do consultório odontológico (skill ``dominio-consultorio``).

Valores iniciais, editáveis pela usuária; 🔶 a validar com o contador (P17).
Estrutura: (nome do grupo, tipo, grupo do DRE, [categorias]).
"""

from __future__ import annotations

from typing import Final

from appfin.domain.enums import CategoryKind, DreGroup, TaxRegime

DefaultGroup = tuple[str, CategoryKind, DreGroup, tuple[str, ...]]

_TAXES: Final[dict[TaxRegime, tuple[str, ...]]] = {
    TaxRegime.SIMPLES: ("Simples Nacional (DAS)", "ISS"),
    TaxRegime.PRESUMIDO: ("ISS", "PIS", "COFINS", "IRPJ", "CSLL"),
    TaxRegime.CARNE_LEAO: ("Carnê-leão", "ISS"),
    TaxRegime.OTHER: ("Impostos sobre serviços",),
}


def default_categories(regime: TaxRegime) -> list[DefaultGroup]:
    return [
        (
            "Receitas de atendimento",
            CategoryKind.INCOME,
            DreGroup.GROSS_REVENUE,
            ("Tratamentos particulares", "Convênios odontológicos", "Outras receitas"),
        ),
        (
            "Deduções",
            CategoryKind.EXPENSE,
            DreGroup.DEDUCTIONS,
            ("Descontos concedidos", "Glosas de convênio", "Taxas de cartão/maquininha"),
        ),
        ("Impostos", CategoryKind.EXPENSE, DreGroup.TAXES, _TAXES[regime]),
        (
            "Custos diretos",
            CategoryKind.EXPENSE,
            DreGroup.DIRECT_COSTS,
            (
                "Materiais odontológicos",
                "Laboratório de prótese",
                "Descartáveis e esterilização",
                "Repasse a dentista parceiro",
            ),
        ),
        (
            "Despesas operacionais",
            CategoryKind.EXPENSE,
            DreGroup.OPERATING_EXPENSES,
            (
                "Aluguel",
                "Condomínio",
                "Energia",
                "Água",
                "Internet e telefone",
                "Salários",
                "Pró-labore",
                "INSS e FGTS",
                "Contador",
                "Software",
                "Manutenção de equipamentos",
                "Coleta de resíduos",
                "CRO e anuidades",
                "Seguros",
            ),
        ),
        (
            "Despesas comerciais",
            CategoryKind.EXPENSE,
            DreGroup.SELLING_EXPENSES,
            ("Marketing", "Redes sociais", "Brindes"),
        ),
        (
            "Financeiro e diversos",
            CategoryKind.BOTH,
            DreGroup.OTHER_RESULTS,
            ("Rendimentos", "Juros e tarifas bancárias", "Outros"),
        ),
    ]
