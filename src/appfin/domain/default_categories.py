"""Categorias padrão do consultório odontológico (skill ``dominio-consultorio``).

Valores iniciais, editáveis pela usuária; 🔶 a validar com o contador (P17).
Estrutura: (nome do grupo, tipo, grupo do DRE, [categorias]).

O grupo "Impostos" segue o bloco de impostos da planilha de fluxo de caixa do consultório
(decisão P19 em plano de importação): além dos tributos, reúne encargos, contador, tarifas
e taxas de maquininha, para o DRE gerencial bater com a planilha.
"""

from __future__ import annotations

from typing import Final

from appfin.domain.enums import CategoryKind, DreGroup, TaxRegime

DefaultGroup = tuple[str, CategoryKind, DreGroup, tuple[str, ...]]

_REGIME_TAXES: Final[dict[TaxRegime, tuple[str, ...]]] = {
    TaxRegime.SIMPLES: ("Simples Nacional (DAS)", "ISS"),
    TaxRegime.PRESUMIDO: ("ISS", "PIS", "COFINS", "IRPJ", "CSLL"),
    TaxRegime.CARNE_LEAO: ("Carnê-leão", "ISS"),
    TaxRegime.OTHER: ("Impostos sobre serviços",),
}

_TAXES_AND_CHARGES: Final[tuple[str, ...]] = (
    "Outros impostos e taxas",
    "INSS e FGTS",
    "Contador",
    "CRO e anuidades",
    "Laudos e saúde ocupacional",
    "Tarifas bancárias",
    "Taxas de cartão/maquininha",
    "Controle de esterilização",
)


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
            ("Descontos concedidos", "Glosas de convênio", "Devoluções a pacientes"),
        ),
        (
            "Impostos",
            CategoryKind.EXPENSE,
            DreGroup.TAXES,
            _REGIME_TAXES[regime] + _TAXES_AND_CHARGES,
        ),
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
                "Software",
                "Manutenção de equipamentos",
                "Coleta de resíduos",
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
            "Investimentos",
            CategoryKind.EXPENSE,
            DreGroup.INVESTMENTS,
            (
                "Equipamentos e aquisições",
                "Reformas",
                "Kits para pacientes",
                "Cursos e capacitação",
                "Uniformes",
            ),
        ),
        (
            "Financeiro e diversos",
            CategoryKind.BOTH,
            DreGroup.OTHER_RESULTS,
            ("Rendimentos", "Juros", "Outros"),
        ),
    ]
