---
name: dominio-consultorio
description: Regras de negócio específicas do consultório odontológico (PJ) — perfil do usuário, categorias e grupos do DRE padrão, regime de caixa x competência, parcelamento de tratamentos, recibo x NFS-e, papéis de contato (paciente/fornecedor/convênio) e minimização de dados de pacientes. Use ao criar ou alterar lançamentos, categorias, DRE, relatórios, recibos, contatos, importação de planilhas ou textos da interface, para não tratar o app como "finanças pessoais".
---

# Domínio: consultório odontológico

O app é a gestão financeira de **um consultório odontológico pequeno, pessoa jurídica**, usada por
**uma pessoa** (a dentista ou quem cuida do financeiro), num PC que pode ser compartilhado com a
recepção. **Não** é um app de finanças pessoais e **não** é prontuário clínico.
Referência: `docs/PROJETO.md` (seções 1, 6.5 e 7.12).

## Quem é quem

- **Empresa (`Company`)**: o consultório (PJ; PF continua possível no cadastro). Dados: razão social,
  nome fantasia, CNPJ, CRO do responsável, endereço, telefone, WhatsApp, e-mail, logotipo, regime
  tributário. Usados no cabeçalho de recibos e relatórios. **Nunca** enviados para fora do app.
- **Contatos (`Contact`)** com papéis (pode ter mais de um):
  - `PATIENT` — paga tratamentos (receitas);
  - `SUPPLIER` — dental, laboratório de prótese, aluguel, contador etc. (despesas);
  - `INSURER` — convênio odontológico (receitas, glosas);
  - `OTHER`.

## Dados de pacientes (LGPD — inegociável)

- Obrigatório só o **nome**. CPF apenas quando necessário para recibo; endereço opcional.
- **Nenhuma informação clínica** (procedimento, dente, diagnóstico) em descrição, observação ou
  palavra-chave. Padrão de descrição: `Tratamento — parcela 2/6`. O formulário mostra essa orientação.
- Pacientes aparecem em listas e relatórios só onde é necessário; o botão "Ocultar valores" vale para
  todas as telas.
- Exportar os dados de um paciente (direito de acesso) e anonimizar contatos inativos depois do prazo
  de retenção (mínimo 5 anos de registros financeiros).

## Lançamentos típicos

| Situação | Como modelar |
|---|---|
| Tratamento particular parcelado | `Income`, contato paciente, `InstallmentGroup` (N parcelas a cada X dias **ou** meses), **mesma `accrual_date`** (data da venda/início) em todas as parcelas |
| Pagamento à vista no Pix/dinheiro | `Income` já `PAID`, `paid_date` = hoje |
| Cartão de crédito na maquininha | MVP: `Income` com forma `credit`. Futuro: recebível com taxa e prazo de liquidação |
| Convênio | `Income`, contato convênio; glosa como dedução (categoria "Glosas de convênio") |
| Laboratório de prótese, materiais | `Expense`, contato fornecedor, grupo "Custos diretos" |
| Aluguel, contador, salários | `Expense` (recorrência na fase 2) |
| Mover dinheiro do caixa para o banco | **Transferência** (duas pernas), não é receita nem despesa |

Formas de pagamento: Dinheiro, **Pix**, Cartão de crédito, Cartão de débito, Boleto, Transferência,
Cheque, Outro.

## Categorias e DRE padrão (valores iniciais; editáveis; validar com o contador)

| Grupo DRE (`dre_group`) | Categorias padrão |
|---|---|
| `gross_revenue` (+) Receita bruta | Tratamentos particulares, Convênios odontológicos, Outras receitas operacionais |
| `deductions` (−) Deduções | Descontos concedidos, Glosas de convênio, Devoluções a pacientes |
| `taxes` (−) Impostos | Tributos do regime (ISS, Simples Nacional (DAS), IRPJ/CSLL/PIS/COFINS no Presumido) + Outros impostos e taxas, INSS e FGTS, Contador, CRO e anuidades, Laudos e saúde ocupacional, Tarifas bancárias, Taxas de cartão/maquininha, Controle de esterilização (segue o bloco de impostos da planilha do consultório — decisão P19) |
| `direct_costs` (−) Custos diretos | Materiais odontológicos, Laboratório de prótese, Descartáveis e esterilização, Repasse a dentista parceiro |
| `operating_expenses` (−) Despesas operacionais | Aluguel, Condomínio, Energia, Água, Internet/Telefone, Salários, Pró-labore, Software, Manutenção de equipamentos, Coleta de resíduos, Seguros |
| `investments` (−) Investimentos | Equipamentos e aquisições, Reformas, Kits para pacientes, Cursos e capacitação, Uniformes |
| `selling_expenses` (−) Despesas comerciais | Marketing, Redes sociais, Brindes |
| `other_results` (±) Resultado financeiro/diversos | Rendimentos, Juros, Outras |

Estrutura do DRE: Receita bruta − Deduções − Impostos = **Receita líquida** − Custos diretos =
**Lucro bruto** − Despesas operacionais − Despesas comerciais = **Resultado operacional** − Investimentos =
**Resultado após investimentos** ± Diversos = **Resultado do período**. Transferências nunca entram.

A planilha "Fluxo de caixa" do consultório é importada pela tela Importar planilha (skill
`importacao-planilha`): o DRE do app precisa bater com ela em Impostos, Investimentos e Resultado.

## Regime de caixa × competência

- DRE e relatório por categoria têm um **seletor "Caixa | Competência"** na hora de visualizar.
- **Caixa:** só lançamentos `PAID`, agrupados por `paid_date`.
- **Competência:** todos os não `CANCELLED`, agrupados por `accrual_date`.
- `accrual_date` padrão = data do atendimento/compra; no parcelamento é igual para todas as parcelas;
  na importação sem competência, usa o vencimento.

## Recibo × documento fiscal

- O consultório é **PJ**: o documento fiscal é a **NFS-e**, emitida **fora** do app.
- O recibo em PDF do app é **comprovante complementar**, numerado em sequência, com os dados da
  empresa. O texto do recibo **não** pode sugerir que ele substitui a nota fiscal.
- Campo opcional no lançamento para guardar o número da NFS-e (`official_receipt_ref`).
- Se um dentista PF emitir recibo de paciente, o oficial é o do app **Receita Saúde** (fora do app).

## Fora de escopo (não implementar sem decisão)

Prontuário, agenda, odontograma, emissão de NF-e/NFS-e, integração bancária automática, multiempresa,
app mobile.

## Skills relacionadas

`backend-architecture` (regras financeiras gerais), `security` (LGPD), `frontend-architecture`
(textos e orientação na interface), `clean-code` (glossário).
