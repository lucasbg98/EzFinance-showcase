# Política de segurança

Este app guarda dados financeiros de um consultório e dados de pacientes. O modelo de ameaças e os
controles estão em `docs/PROJETO.md` §7; as regras obrigatórias de desenvolvimento estão na skill
`.claude/skills/security/SKILL.md`.

## Resumo dos controles

- Banco local cifrado (SQLCipher 4, AES-256) com chave derivada da senha mestra (Argon2id via libsodium).
- Hierarquia de chaves: senha → chave mestra → KEK → chave de dados (DEK) aleatória; chave de recuperação.
- Bloqueio automático por inatividade e ao bloquear o Windows; chaves sobrescritas ao bloquear.
- Logs com lista de campos permitidos — nenhum dado financeiro ou pessoal.
- Sem telemetria.
- Dependências travadas com hashes (`uv.lock`), varridas por `pip-audit`; SAST (Bandit, ruff `S`, CodeQL).
- Atualizações assinadas (TUF/tufup) — em implementação na fase 0.

## Como reportar um problema

Repositório privado, mantido por uma pessoa. Problemas de segurança: contate o mantenedor
diretamente (não abra issue pública). Não inclua dados reais de pacientes ou financeiros no relato.

## Limitações conhecidas (aceitas)

- Malware rodando com o usuário do Windows enquanto o app está desbloqueado pode ler os dados.
- Python não permite apagar segredos da memória com garantia; mitigamos com `bytearray` sobrescrito no bloqueio.
- Perder a senha mestra **e** a chave de recuperação significa perder os dados (criptografia ponta a ponta).
- Instalador ainda sem assinatura Authenticode (decisão do projeto); conferir o SHA-256 publicado.

## Exceções ativas do scanner de dependências

| ID | Pacote | Por que não se aplica hoje | Ação | Revisar até |
|---|---|---|---|---|
| GHSA-qp9x-wp8f-qgjj | `tuf` 4.0.0 (via `tufup`) | Afeta a comparação de caminhos de **delegações** no Windows; nosso repositório TUF não usa delegações (só os papéis root/targets/snapshot/timestamp). A correção (tuf ≥ 7) é incompatível com o `tufup`, que trava `tuf==4.0.*`. | Substituir o `tufup` por `python-tuf` direto antes da 1ª instalação real (pendência P21) | 2026-12-31 |
