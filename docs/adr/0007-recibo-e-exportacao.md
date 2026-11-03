# ADR-0007 — Recibo em PDF e exportação CSV/Excel (fase 1, incremento 1.5)

- **Data:** 03/11/2026
- **Status:** aceito

## Decisões

1. **Dependências:** `reportlab` 5.0.1 (PDF) e `openpyxl` 3.1.5 (Excel; será reaproveitado na
   importação do incremento 1.7), versões exatas, com hashes no `uv.lock` e auditadas pelo
   pip-audit. O `Pillow` entra como dependência do reportlab e **precisa** ir no executável: o
   reportlab 5 o importa ao inicializar (tentamos excluí-lo para reduzir superfície; o autoteste
   do executável falhou e a exclusão foi desfeita).
2. **Recibo interno numerado:** tabela `receipt` (migração 0003) com número sequencial único, um
   recibo por lançamento. Reemitir gera a **2ª via com o mesmo número** (o rodapé indica "2ª via").
   Só lançamentos pagos/recebidos, nunca transferências. Exige os dados do consultório.
   - Diferença do modelo em `docs/PROJETO.md` §7: não guardamos `pdf_sha256`. O PDF é gerado de
     novo a cada emissão a partir do banco; um hash do primeiro arquivo não provaria nada sobre as
     vias seguintes. O que garante a unicidade é o número.
3. **Texto do recibo:** valor por extenso em pt-BR (`domain/amount_in_words.py`, testado com
   propriedades), "Recebemos de"/"Pagamos a", CPF/CNPJ do contato quando houver, forma de pagamento,
   NFS-e quando informada, assinatura do responsável e CRO. Rodapé deixa claro que **não substitui a
   NFS-e** (skill `dominio-consultorio`).
4. **Segurança do PDF:** só `drawString` com texto simples (nada de `Paragraph`, que interpreta
   marcação); metadados do PDF sem nome de paciente; `invariant=True` (sem data/ID aleatórios).
5. **Exportação CSV/Excel:**
   - Aviso antes de salvar: o arquivo sai **sem a criptografia do app** (ameaça T3).
   - CSV: `;`, UTF-8 com BOM, vírgula decimal (abre direto no Excel brasileiro); texto iniciado por
     `= + - @ TAB CR` recebe `'` (ameaça T10).
   - Excel: texto gravado explicitamente como texto (nunca vira fórmula, sem precisar do `'`);
     valores em reais como número com formato R$; datas como data; percentuais como número `0,0%`.
   - Exporta sempre os valores reais, mesmo com "Ocultar valores" ligado (ocultar é da tela).
   - Gravação atômica (arquivo temporário + troca).
6. **Formatação pt-BR sem Qt** movida para `appfin/br_format.py`, usada pela interface, pelo PDF e
   pelas planilhas.
7. O **autoteste do executável** agora também gera um recibo e uma planilha.
