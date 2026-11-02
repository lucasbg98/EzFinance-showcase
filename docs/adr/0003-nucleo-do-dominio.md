# ADR-0003 — Núcleo do domínio (fase 1, incremento 1.1)

- **Data:** 02/11/2026
- **Status:** aceito

## Decisões

1. **Entidades imutáveis com invariantes no construtor** (`domain/entities.py`): textos normalizados
   (NFC, sem caracteres de controle/invisíveis), CPF/CNPJ com dígito verificador, UF/CEP/telefone,
   regras de lançamento (pago ⇔ data de pagamento; transferência ⇔ `transfer_id`, sem categoria;
   parcela ⇔ parcelamento). `id = ""` significa "ainda não salvo"; o caso de uso atribui um UUIDv7 e
   os repositórios recusam gravar sem id.
2. **Parcelamento** por dias ou meses; em meses o dia é calculado sempre a partir do 1º vencimento
   (31/01 → 28/02 → 31/03). Todas as parcelas herdam a mesma competência. "Receber/Pagar agora"
   quita só a 1ª parcela.
3. **Transferência = duas pernas** com o mesmo `transfer_id` (D5); excluir uma exclui as duas;
   não entra em receitas, despesas nem DRE.
4. **Relatórios agregados no banco** (`queries.py`): saldos, resumo do período, fluxo mensal, DRE por
   regime (caixa: pagos por data de pagamento; competência: não cancelados por competência), totais
   por categoria. Grupo do DRE: o da categoria ou, se vazio, o do grupo-pai; sem grupo →
   "Não classificados" (o DRE sempre fecha).
5. **Outbox desde já**: toda escrita entra na fila de sincronização na mesma transação (fase 2 não
   precisará migrar dados).
6. **SQL montado só com fragmentos fixos**; todo valor externo é parâmetro, inclusive na busca
   (`LIKE` com escape de `%`, `_` e `\`). Testado com textos hostis.

## Desvio consciente da skill `repository-pattern`

A skill pede *fakes* em memória para cada repositório + testes de contrato. Neste incremento os
testes de casos de uso rodam contra o **SQLCipher real** em arquivo temporário (rápido: ~1 s para
todos), o que testa também SQL, constraints e transações. Os fakes ficam para quando houver
casos de uso cuja lógica valha testar isolada do banco (revisar no incremento 1.3).

## Achado de segurança durante o incremento

O Bandit (B613, *Trojan Source*) detectou **caracteres invisíveis/bidirecionais reais** no
código-fonte: as sequências de escape escritas para a regex de limpeza de texto foram gravadas
como os próprios caracteres. Corrigido montando a classe de caracteres a partir de códigos
numéricos (`chr(0x200B)`), e criado `tests/unit/test_source_hygiene.py`, que reprova qualquer
caractere desse tipo em todos os arquivos do projeto (o Bandit só cobre `src/`).
