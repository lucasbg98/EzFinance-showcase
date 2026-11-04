"""Perfil padrão da planilha "Fluxo de caixa": linha → categoria (plano de importação §4 e §5).

Puro e **só com rótulos genéricos** (§5.3): nomes de pessoas e fornecedores nunca aparecem aqui.
Como cada linha de detalhe é reconhecida, nesta ordem (§5.1):

1. **regra por palavra-chave** dentro do bloco (aluguel, DAS, FGTS, cartão crédito, cursos…);
   a palavra casa com o início de uma palavra do rótulo normalizado, então pequenas variações
   ("CONSERTOS"/"CONSERTO", sufixos, ano no texto) não atrapalham;
2. **sugestão pelo bloco**, nos blocos homogêneos cujas linhas são nomes de pessoas/empresas
   (dentistas, protéticos, material odontológico, salários, impostos): vale, mas aparece com aviso;
3. **sem regra** (linha desconhecida num bloco misto): a usuária escolhe a categoria.

O alvo de uma regra é o **nome** de uma categoria (com grupo do DRE): o caso de uso procura a
categoria pelo nome e, se não existir, propõe criá-la ("(nova)" na §4). Duas regras criam a
categoria com o **rótulo da própria linha** (linhas da outra sócia, §5.2): o nome só existe no
banco cifrado, nunca no código.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from appfin.domain.enums import DreGroup, PaymentMethod, TransactionKind
from appfin.domain.spreadsheet_import import cash_flow_layout as layout
from appfin.domain.spreadsheet_import.monthly_matrix import MatrixLine

PROFILE_NAME = "Fluxo de caixa"
INCOME_BLOCKS = frozenset({layout.REVENUE, layout.NON_OPERATING})
FROM_LABEL = ""  # alvo cujo nome é o rótulo da linha (lido em tempo de execução)
_WORD = re.compile(r"[A-Z0-9]+")


class RuleSource(StrEnum):
    RULE = "rule"  # regra por palavra-chave
    BLOCK = "block"  # sugerido pelo bloco (aviso, não bloqueia)


@dataclass(frozen=True, slots=True)
class CategoryTarget:
    """Categoria sugerida: nome (ou ``FROM_LABEL``) e grupo do DRE da categoria."""

    name: str
    dre_group: DreGroup
    payment_method: PaymentMethod | None = None


@dataclass(frozen=True, slots=True)
class Suggestion:
    target: CategoryTarget
    source: RuleSource


@dataclass(frozen=True, slots=True)
class _Rule:
    keywords: tuple[str, ...]  # todas precisam aparecer (início de palavra)
    target: CategoryTarget


def _rule(*keywords: str, name: str, group: DreGroup, method: PaymentMethod | None = None) -> _Rule:
    return _Rule(keywords, CategoryTarget(name, group, method))


_REVENUE = DreGroup.GROSS_REVENUE
_DEDUCTIONS = DreGroup.DEDUCTIONS
_TAXES = DreGroup.TAXES
_DIRECT = DreGroup.DIRECT_COSTS
_OPEX = DreGroup.OPERATING_EXPENSES
_SELLING = DreGroup.SELLING_EXPENSES
_INVEST = DreGroup.INVESTMENTS
_OTHER = DreGroup.OTHER_RESULTS
_TREATMENTS = "Tratamentos particulares"

# A ordem importa: a primeira regra que casa vence (ex.: "devolução de crédito" antes de "crédito").
_RULES: dict[str, tuple[_Rule, ...]] = {
    layout.REVENUE: (
        _rule("DEVOLUC", name="Devoluções a pacientes", group=_DEDUCTIONS),
        _rule("CHEQUE", name=_TREATMENTS, group=_REVENUE, method=PaymentMethod.CHECK),
        _rule("CREDITO", name=_TREATMENTS, group=_REVENUE, method=PaymentMethod.CREDIT),
        _rule("DEBITO", name=_TREATMENTS, group=_REVENUE, method=PaymentMethod.DEBIT),
        _rule("DINHEIRO", name=_TREATMENTS, group=_REVENUE, method=PaymentMethod.CASH),
        _rule("PIX", name=_TREATMENTS, group=_REVENUE, method=PaymentMethod.PIX),
        _rule("DOC", name=_TREATMENTS, group=_REVENUE, method=PaymentMethod.PIX),
        _rule("SOBRAS", name="Rendimentos", group=_OTHER),
        _rule("ESTORNO", name="Outras receitas", group=_REVENUE),
        _rule("RECEBID", name=FROM_LABEL, group=_OTHER),  # recebidos da outra sócia (§5.2)
    ),
    layout.MISCELLANEOUS: (
        _rule("ENTREGA", name="Correios e entregas", group=_OPEX),
        _rule("TAXI", name="Correios e entregas", group=_OPEX),
        _rule("CORREIO", name="Correios e entregas", group=_OPEX),
        _rule("PAPELARIA", name="Material de escritório", group=_OPEX),
        _rule("GRAFICA", name="Material de escritório", group=_OPEX),
        _rule("UTILIDADE", name="Material de escritório", group=_OPEX),
        _rule("SUPERMERCADO", name="Copa e confraternizações", group=_OPEX),
        _rule("BOLACHA", name="Copa e confraternizações", group=_OPEX),
        _rule("CONFRATERNIZ", name="Copa e confraternizações", group=_OPEX),
        _rule("TEMPORARI", name="Mão de obra temporária", group=_OPEX),
        _rule("GERAL", name=FROM_LABEL, group=_DIRECT),  # repasse da outra sócia (§5.2)
    ),
    layout.DENTAL_SUPPLIES: (
        _rule("FARMACIA", name="Descartáveis e esterilização", group=_DIRECT),
        _rule("CONSUMO", name="Descartáveis e esterilização", group=_DIRECT),
        _rule("ESCANEA", name="Escaneamento", group=_DIRECT),
    ),
    layout.FIXED: (
        _rule("ALUGUEL", name="Aluguel", group=_OPEX),
        _rule("CONDOMINIO", name="Condomínio", group=_OPEX),
        _rule("LIXO", name="Coleta de resíduos", group=_OPEX),
        _rule("INTERNET", name="Internet e telefone", group=_OPEX),
        _rule("TELEFON", name="Internet e telefone", group=_OPEX),
        _rule("MARKETING", name="Marketing", group=_SELLING),
        _rule("CONSERTO", name="Manutenção de equipamentos", group=_OPEX),
        _rule("MANUTEN", name="Manutenção de equipamentos", group=_OPEX),
        _rule("SOFTWARE", name="Software", group=_OPEX),
    ),
    layout.SALARIES: (_rule("LABORE", name="Pró-labore", group=_OPEX),),
    layout.TAXES: (
        _rule("SIMPLES", name="Simples Nacional (DAS)", group=_TAXES),
        _rule("DAS", name="Simples Nacional (DAS)", group=_TAXES),
        _rule("RENDA", name="IR pessoa física", group=_TAXES),
        _rule("FGTS", name="INSS e FGTS", group=_TAXES),
        _rule("GPS", name="INSS e FGTS", group=_TAXES),
        _rule("INSS", name="INSS e FGTS", group=_TAXES),
        _rule("CONTADOR", name="Contador", group=_TAXES),
        _rule("CONTABI", name="Contador", group=_TAXES),
        _rule("PGRSS", name="Laudos e saúde ocupacional", group=_TAXES),
        _rule("ENGENH", name="Laudos e saúde ocupacional", group=_TAXES),
        _rule("ATESTADO", name="Laudos e saúde ocupacional", group=_TAXES),
        _rule("PCMSO", name="Laudos e saúde ocupacional", group=_TAXES),
        _rule("CRO", name="CRO e anuidades", group=_TAXES),
        _rule("CARTAO", name="Taxas de cartão/maquininha", group=_TAXES),
        _rule("MAQUIN", name="Taxas de cartão/maquininha", group=_TAXES),
        _rule("BANCARI", name="Tarifas bancárias", group=_TAXES),
        _rule("SENSOR", name="Controle de esterilização", group=_TAXES),
        _rule("DARF", name="Outros impostos e taxas", group=_TAXES),
        _rule("FEDERAL", name="Outros impostos e taxas", group=_TAXES),
        _rule("PREFEITURA", name="Outros impostos e taxas", group=_TAXES),
        _rule("TRIBUTO", name="Outros impostos e taxas", group=_TAXES),
    ),
    layout.INVESTMENTS: (
        _rule("AQUISIC", name="Equipamentos e aquisições", group=_INVEST),
        _rule("EQUIPAMENT", name="Equipamentos e aquisições", group=_INVEST),
        _rule("REFORMA", name="Reformas", group=_INVEST),
        _rule("KIT", name="Kits para pacientes", group=_INVEST),
        _rule("CURSO", name="Cursos e capacitação", group=_INVEST),
        _rule("UNIFORME", name="Uniformes", group=_INVEST),
    ),
    layout.NON_OPERATING: (
        _rule("ENTRADA", name="Outros", group=_OTHER),
        _rule("SAIDA", name="Outros", group=_OTHER),
    ),
}

# Blocos homogêneos (linhas = nomes de pessoas ou empresas): a categoria vem do próprio bloco.
_BLOCK_DEFAULTS: dict[str, CategoryTarget] = {
    layout.DENTISTS: CategoryTarget("Repasse a dentista parceiro", _DIRECT),
    layout.PROSTHETICS: CategoryTarget("Laboratório de prótese", _DIRECT),
    layout.DENTAL_SUPPLIES: CategoryTarget("Materiais odontológicos", _DIRECT),
    layout.SALARIES: CategoryTarget("Salários", _OPEX),
    layout.TAXES: CategoryTarget("Outros impostos e taxas", _TAXES),
}


def line_kind(line: MatrixLine) -> TransactionKind:
    """Receita: linhas de receita e entradas não operacionais. O que a planilha subtrai: despesa."""
    if line.block in INCOME_BLOCKS and line.sign > 0:
        return TransactionKind.INCOME
    return TransactionKind.EXPENSE


def suggest(line: MatrixLine) -> Suggestion | None:
    """Categoria sugerida para a linha, ou ``None`` (a usuária precisa escolher)."""
    words = _WORD.findall(line.key.rsplit("|", 1)[-1].split("#", 1)[0])
    for rule in _RULES.get(line.block, ()):
        if all(any(word.startswith(keyword) for word in words) for keyword in rule.keywords):
            return Suggestion(rule.target, RuleSource.RULE)
    target = _BLOCK_DEFAULTS.get(line.block)
    return Suggestion(target, RuleSource.BLOCK) if target else None
