# Backup e restauração

Procedimento de referência do `docs/PROJETO.md` §7.9. A restauração deve ser **testada a cada
3 meses** numa máquina (ou VM) limpa, usando só o arquivo de backup e a **chave de recuperação**
em papel: um backup que nunca foi restaurado não é um backup confiável.

## Como os backups funcionam

- **Automáticos:** a cada 24 horas de uso, ao fechar o app, antes de restaurar um backup e antes de
  atualizar o esquema do banco (nova versão do app).
- **Manuais:** *Backup e segurança → Fazer backup agora*.
- **Onde ficam:**
  - sempre em `%APPDATA%\AppFinanceiro\backups`. Essa cópia protege contra erro humano, mas **não**
    contra disco estragado ou computador roubado;
  - numa **pasta extra** escolhida em *Backup e segurança*, que pode ser um pen drive ou uma pasta
    do OneDrive. **Configure a pasta extra.** O backup na nuvem do app chega na fase 2.
- **Arquivos:** `EzFinance-backup-AAAAMMDD-HHMMSS.afbkp` (os feitos antes da troca de nome,
  `AppFinanceiro-backup-…`, continuam valendo para a retenção e para restaurar). Ficam os 10 mais recentes e, além
  deles, um por dia (7 dias), um por semana (4 semanas) e um por mês (12 meses). Os outros arquivos
  da pasta nunca são tocados.
- **Segurança:**
  - cada arquivo é **cifrado** (XChaCha20-Poly1305 em blocos, chave derivada da chave de dados);
  - cada backup é **conferido logo depois de criado**: o app decifra, roda o teste de integridade
    do banco e compara as contagens;
  - um arquivo adulterado, corrompido ou incompleto é recusado.
- **Para abrir um backup** é preciso a **senha mestra da época do backup** ou a **chave de
  recuperação daquela época**.

## Restaurar no mesmo computador

1. *Backup e segurança → Restaurar de um backup…*
2. Escolha o arquivo `.afbkp` e digite a senha mestra (ou a chave de recuperação) da época do
   backup.
3. Clique em **Verificar backup**. O app decifra e confere o arquivo numa área separada, sem mudar
   nada, e mostra a data e o conteúdo do backup.
4. Clique em **Restaurar agora**. O app faz um backup do estado atual, troca os dados e volta para a
   tela de desbloqueio.
5. Entre com a senha mestra **da época do backup**.

Os arquivos substituídos ficam cifrados em `%APPDATA%\AppFinanceiro\restore-previous` até a próxima
restauração. Servem como desfazer de emergência; o caminho normal é restaurar o backup automático
feito no passo 4.

## Restaurar em outro computador (ou depois de reinstalar o Windows)

1. Instale o app. **Não crie** uma senha nova.
2. Na primeira tela, clique em **Já uso o app em outro computador: restaurar um backup**.
3. Siga os passos 2 a 5 acima.

## Teste trimestral (checklist)

- [ ] Copiar o backup mais recente da pasta extra para uma máquina ou VM limpa.
- [ ] Instalar o app e restaurar **usando a chave de recuperação em papel**, não a senha.
- [ ] Conferir se os totais do Início e o DRE do último mês batem com o computador do consultório.
- [ ] Apagar a VM ou os dados de teste ao terminar. São dados reais.
- [ ] Anotar a data do teste: ___/___/______

## Se algo der errado

- **"Senha incorreta para este backup":** use a senha da época em que o backup foi feito. Se ela
  mudou depois, tente a chave de recuperação daquela época.
- **"Backup incompleto", "adulterado" ou "corrompido":** use outro arquivo (outro dia ou a outra
  pasta).
- **Queda de energia durante a restauração:** abra o app de novo. Ele termina a troca sozinho antes
  de abrir os dados.
- **Gerou uma chave de recuperação nova:** a antiga não abre mais este computador, mas **continua
  abrindo os backups feitos antes da troca**. Guarde as duas até esses backups saírem da retenção
  (12 meses).
