# ADR-0002 — Instalador e atualizações assinadas

- **Data:** 02/11/2026
- **Status:** aceito (hospedagem das atualizações pendente)

## Decisões

1. **PyInstaller *onedir*** (sem UPX), excluindo módulos Qt não usados; **Inno Setup 6** com instalação
   por usuário (`PrivilegesRequired=lowest`) em `%LOCALAPPDATA%\Programs\AppFinanceiro`. Dados ficam em
   `%APPDATA%` e sobrevivem à desinstalação. Instalador: ~37 MB.
2. **Autoteste do executável** (`AppFinanceiro.exe --self-test`) roda no build e no CI: pegou um bug
   real — o `tufup/__init__.py` importa `tufup.repo`, que estava excluído do pacote e quebrava as
   atualizações só no executável.
3. **Atualizações via tufup (TUF)**: root confiável embutido; metadados assinados (Ed25519) com
   expiração (root 365 d, targets/snapshot 90 d, timestamp 30 d); proteção contra rollback.
   Ajustes de segurança sobre o comportamento padrão do tufup:
   - `refresh_required=True` (validação obrigatória). Como o tufup chama `sys.exit()` ao falhar, o
     `SystemExit` é capturado e vira `UpdateError` — o app continua aberto.
   - Extração com o filtro `data` do `tarfile` (bloqueia `..`, caminhos absolutos e links), mesmo com o
     pacote já verificado.
   - O script de troca dos arquivos preserva o desinstalador (`unins000.*`), roda sem janela e reabre o app.
   - HTTPS obrigatório; HTTP só para `127.0.0.1`/`localhost` (testes).
   - Download e verificação em segundo plano; **instalação só após confirmação** e **depois de bloquear
     a sessão**. Botões da confirmação em português, sem atalho de letra, padrão "Agora não".
4. **`release.py`** separa chaves/estado (fora do projeto) do `root.json` público (no app). O comando
   `keys` se recusa a sobrescrever chaves; `publish`/`refresh` carregam o repositório sem a rotina do
   tufup que oferece sobrescrever chaves.
5. **Configuração inicial recusa criar cofre se já existir banco** sem `vault.json` (achado do teste
   ponta a ponta): evita gerar uma chave que nunca abriria os dados existentes.

## Verificação

- Testes automatizados (repositório TUF real + servidor local): atualização legítima aceita; pacote
  adulterado rejeitado; metadados de outra chave rejeitados; sem atualização quando já está na última.
- Teste manual ponta a ponta no executável instalado (0.1.0 → 0.1.1): OK em ~7 s; desinstalador, cofre e
  banco preservados. Numa das rodadas a atualização foi confirmada sem clique registrado pelo script de
  automação; não se repetiu em duas novas tentativas (a caixa permaneceu aguardando). Mitigação aplicada:
  botões próprios sem atalho de letra e padrão "recusar".

## Pendências

- Hospedagem pública dos metadados/pacotes (ver `docs/RELEASE.md`). Até lá, atualização automática desligada.
- Chaves de produção cifradas e root offline, antes da primeira instalação real.
- Teste numa VM/Windows Sandbox limpa (o teste foi feito na máquina de desenvolvimento).
- Assinatura Authenticode (adiada por decisão do projeto).
