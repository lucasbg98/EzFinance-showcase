# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) · Versionamento: SemVer.

## [Não lançado]

## [0.2.1] — 02/11/2026

### Alterado
- Novo visual dos modais: cabeçalho com título e subtítulo, seções, rótulos acima dos campos,
  vários campos por linha, faixa de aviso (LGPD), rodapé com ações e destaque do campo com erro.
- Contato: tipos como "chips", endereço opcional recolhido, rótulo CPF/CNPJ conforme a pessoa.
- Categoria: o tipo acompanha o grupo escolhido.
- Listas: mensagem quando vazias, cabeçalho alinhado à esquerda, busca com lupa e limpar.
- Combos e datas com seta própria; checkbox com marca de seleção.

## [0.2.0] — 02/11/2026

### Adicionado (fase 1 — incrementos 1.1 e 1.2)
- Núcleo do domínio: empresa, contas, categorias, contatos, lançamentos, parcelamento (dias/meses),
  transferências em duas pernas, DRE caixa/competência, relatórios agregados no banco.
- Interface: menu lateral, dados do consultório no primeiro uso (cria categorias odontológicas e a
  conta caixa), cadastros de contas, categorias e contatos, "Ocultar valores" (Ctrl+H).
- Campo de valor em R$ estilo app de banco; formatação pt-BR centralizada; tema claro explícito.

### Corrigido
- Combos convertiam enums em texto (CNPJ válido recusado); botão Salvar dos formulários inerte.
- Caracteres invisíveis/bidi no código-fonte (Trojan Source) + teste de higiene.

## [0.1.0] — 02/11/2026

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
