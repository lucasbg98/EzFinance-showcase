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

### Segurança
- `pytest` 8.4.2 → 9.0.3 (PYSEC-2026-1845, dependência só de desenvolvimento).
