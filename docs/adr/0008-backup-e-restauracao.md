# ADR-0008 — Backup cifrado, restauração e nova chave de recuperação (fase 1, incremento 1.6)

- **Data:** 03/11/2026
- **Status:** aceito

## Contexto

`docs/PROJETO.md` §7.6 e §7.9 especificam backup cifrado com `crypto_secretstream`, chave
`HKDF(DEK, "backup")`, verificação logo após criar, retenção 7/4/12, restauração com prévia e com
backup do estado atual, exigindo a senha mestra ou a chave de recuperação. O backup na nuvem
(Supabase Storage) fica para a fase 2 (P19).

## Decisões

1. **Formato `.afbkp` v1** (`infrastructure/backup/stream.py`):
   - `MAGIC` + cabeçalho JSON + `secretstream`;
   - a 1ª mensagem é o manifesto (data, versão do app e do esquema, contagens) e leva
     `MAGIC + cabeçalho` como dado associado, então o cabeçalho público é autenticado;
   - o banco vai em blocos de 1 MiB e o último bloco tem `TAG_FINAL`;
   - o leitor exige a `TAG_FINAL` e recusa dados extras, o que detecta truncamento;
   - há limites de tamanho antes de qualquer alocação.
2. **O cabeçalho leva o envelope do cofre** (só as cópias **cifradas** da DEK). Sem isso não daria
   para restaurar em outro computador, onde a DEK é outra. Consequência: o backup abre com a
   senha/chave de recuperação **da época do backup**, e depois da restauração vale essa senha.
3. **Sem dado em claro no disco:** a cópia consistente usa a API de backup do SQLite para um arquivo
   **SQLCipher** temporário com a mesma chave. O conteúdo cifrado no `.afbkp` já é o arquivo
   SQLCipher: na restauração ele volta direto como banco cifrado.
4. **Verificação na criação:** o app decifra o arquivo recém-gravado, roda `PRAGMA integrity_check`
   e confere as contagens antes de aceitar. As cópias para a pasta extra são conferidas por SHA-256.
   Uma pasta extra inacessível (pen drive ausente) não impede a cópia local, mas fica sinalizada na
   tela e na barra de status.
5. **Restauração em duas fases:**
   - **preparar:** decifra e confere em `restore-staging/` sem tocar nos dados;
   - **aplicar:** marca como pronto e troca os arquivos. A troca é **retomável e idempotente**
     (`complete_pending_restore`, chamado no início do app), então uma queda de energia no meio é
     concluída na próxima abertura;
   - o WAL antigo é sempre apagado antes de o banco restaurado entrar;
   - os arquivos substituídos vão para `restore-previous/` (cifrados).
6. **Retenção:** além de 7 diários, 4 semanais e 12 mensais, ficam os **10 mais recentes**. Só um
   por dia apagaria, por exemplo, o backup bom da manhã ao fechar o app com dados estragados.
   Diferença registrada em relação ao §7.9.
7. **Automático:** a cada 24 h de uso (conferido a cada 30 min e logo após desbloquear), ao fechar,
   antes de restaurar e **antes de migrar o esquema** (`before_migration`). Se o backup
   pré-migração falhar, a migração não acontece. O backup roda na thread da interface: o banco é
   pequeno e a conexão é de uso exclusivo dela (skill `concurrency`). Isso deve ser revisto se o
   banco crescer.
8. **Nova chave de recuperação:** exige a senha mestra de novo e é gerada **sem gravar**. Só depois
   que a usuária confirma o último grupo ela passa a valer. Um bloqueio antes disso não perde
   nada, e o bloqueio automático fica pausado enquanto a chave está na tela. Os backups antigos
   continuam abrindo com a chave antiga, o que é explicado na tela e no `docs/RESTAURACAO.md`.
9. **Primeiro uso em outro computador:** a tela de criação da senha oferece "restaurar um backup".
