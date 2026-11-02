# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) · Versionamento: SemVer.

## [Não lançado]

### Adicionado (fase 0 — fundação)
- Projeto Python 3.13 com `uv` (lockfile com hashes e janela de 2 semanas para versões novas).
- Núcleo de criptografia: Argon2id, HKDF, XChaCha20-Poly1305, cofre com chave de recuperação.
- Banco local cifrado (SQLCipher 4) com migrações numeradas e auditoria local de eventos.
- Sessão: configuração inicial, desbloqueio (senha ou chave de recuperação), bloqueio com
  atraso progressivo após erros.
- Interface PySide6: telas de senha mestra, chave de recuperação e desbloqueio; bloqueio
  automático por inatividade, Win+L e suspensão; instância única.
- Logs com lista de campos permitidos (nenhum dado sensível).
- Qualidade e segurança: ruff (com regras de segurança), mypy estrito, pytest/pytest-qt/hypothesis,
  Bandit, pip-audit, gitleaks, pre-commit; workflows de CI, segurança (CodeQL) e Dependabot.

### Adicionado (fase 0 — instalador e atualizações)
- Executável (PyInstaller onedir) com autoteste `--self-test` no build e no CI.
- Instalador Inno Setup por usuário, sem administrador; dados preservados na desinstalação.
- Atualizações assinadas com TUF (tufup): verificação após o desbloqueio, confirmação explícita,
  bloqueio da sessão antes de instalar, reabertura automática na nova versão.
- `packaging/release.py`: chaves, build, publicação, renovação de metadados e servidor de teste.
- Documentos: `docs/RELEASE.md`, `docs/INSTALACAO.md`, ADR-0002.

### Corrigido
- Configuração inicial não cria mais um cofre novo quando já existe banco sem `vault.json`.

### Segurança
- `pytest` 8.4.2 → 9.0.3 (PYSEC-2026-1845, dependência só de desenvolvimento).
- Extração dos pacotes de atualização com filtro `data` do `tarfile`.
