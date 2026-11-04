# Importar a planilha "Fluxo de caixa"

A tela **Importar planilha** (menu lateral) traz os valores mensais da planilha do consultório para
o app. Cada valor de uma linha num mês vira **um lançamento** no último dia do mês: **pago** nos meses
realizados (com receita) e **pendente** nos meses de projeção. O comentário da célula no Excel vira
a observação do lançamento.

Nada é gravado antes de você conferir a prévia e confirmar. Antes de gravar, o app faz um backup
automático.

## Passo a passo

1. **Arquivo:** escolha o `.xlsx` (recomendado: traz os comentários) ou o `.csv` exportado pelo
   Excel. O arquivo só é lido; nada nele é executado nem alterado.
2. **Período e destino:** confira o ano (sugerido pelo nome da aba ou do arquivo) e a conta. Cada mês
   aparece como **Realizado**, **Projeção** ou **Fora da importação**; troque se precisar.
3. **Categorias** (só quando há algo a decidir): confira a categoria de cada linha. Dê duplo clique
   para trocar a categoria, criar uma nova ou mudar a descrição. Linhas marcadas "Escolha a
   categoria" precisam de uma escolha; ela fica salva e não é perguntada de novo.
4. **Prévia e conferência:**
   - **Lançamentos:** o que será criado, substituído ou removido;
   - **Planilha versus app:** cada total da planilha, mês a mês, comparado com a soma do app, e o
     DRE (Impostos, Investimentos e Resultado do período);
   - **Problemas:** erros e avisos com a linha e o mês da planilha.

   "Confirmar importação" só fica disponível quando não há erros e todos os totais conferem.
5. **Confirmar:** o app faz o backup e grava tudo de uma vez.

## Importar de novo (planilha atualizada)

Repita o passo a passo com o arquivo novo. O app não duplica nada:

| Na planilha | O que o app faz |
|---|---|
| Valor novo | Cria o lançamento |
| Igual ao já importado | Pula |
| Valor ou comentário mudou, ou o mês passou de projeção para realizado | **Substitui** (o antigo é excluído) |
| Mudou, mas você já alterou o lançamento no app (editou, pagou, emitiu recibo) | **Mantém o do app** e só avisa |
| Célula zerada | **Remove** o lançamento importado antes |

Na prévia, dê duplo clique numa substituição ou remoção para manter o lançamento que está no app.

## Desfazer

Na aba **Histórico**, escolha a importação e clique em **Desfazer importação…**. Os lançamentos dela
são excluídos e os que ela substituiu voltam a valer. Só a importação mais recente de cada ano pode
ser desfeita, e não dá para desfazer se algum lançamento dela foi alterado no app (a tela mostra
quais).

## Quando a importação é bloqueada

- **Total que não confere:** a fórmula da planilha não soma todas as linhas do bloco (ou uma linha
  foi digitada errada). Corrija a planilha, salve e importe de novo.
- **"Total sem valor calculado":** abra a planilha no Excel, salve e importe de novo.
- **Valor com mais de 2 casas decimais, negativo ou texto numa linha de valores:** corrija a célula
  indicada.
- **Linha nova que o app não conhece:** escolha a categoria no passo 3.

## Privacidade

A planilha tem nomes e valores reais: eles ficam só no banco cifrado do app. O nome do arquivo não é
guardado e nada da planilha vai para o registro (log) do app, que guarda só as contagens.
