---
name: security
description: Regras de segurança obrigatórias do app financeiro do consultório (dados financeiros e de pacientes). Use SEMPRE que for criar ou alterar autenticação, desbloqueio, autorização, criptografia, armazenamento local, sincronização/nuvem, regras do backend (RLS), importação/exportação de arquivos (planilhas, CSV, PDF, backup), logs, dependências, build, instalador ou atualização — e em qualquer revisão de código antes de um commit.
---

# Segurança — app financeiro do consultório

Este app guarda os dados financeiros de um **consultório odontológico (PJ)** e **dados de pacientes**
(nome, CPF, contato e histórico de pagamentos, que pode revelar tratamentos e por isso é tratado como
**dado de saúde**). **Segurança é a prioridade nº 1 e vence conveniência, prazo, desempenho e estética.**
Nenhum sistema tem garantia de zero falhas; por isso o objetivo é defesa em profundidade: várias camadas
independentes, cada uma verificada por testes. Referência completa: `docs/PROJETO.md`, seção 7.

## Regra de ouro

**Nunca enfraqueça um controle de segurança para "fazer funcionar".** Exemplos proibidos:
desligar a verificação de TLS, abrir regras do backend, desativar RLS, colocar uma chave no código
"temporariamente", silenciar um alerta do scanner de dependências sem justificativa, baixar os
parâmetros do Argon2id para "agilizar o teste" fora de testes. Se um controle está bloqueando o trabalho,
**pare e me pergunte**, explicando o problema e as alternativas seguras.

## 1. Segredos

- Nenhum segredo (senha, token, chave de criptografia, `service_role`, chaves privadas de assinatura
  TUF) no código, no repositório, no executável, em arquivos de configuração empacotados ou em logs.
- Tudo que vai no executável é **público**: qualquer pessoa pode extrair (PyInstaller é extraível).
  A URL do Supabase e a `anon key` só são aceitáveis porque a proteção real está no RLS (seção 3) e na
  criptografia ponta a ponta.
- `.env` e equivalentes no `.gitignore`; manter um `.env.example` sem valores.
- `gitleaks` no pre-commit e no CI.
- Se um segredo vazar no histórico do git: considere-o comprometido, **revogue e gere outro**.
  Reescrever o histórico não basta.

## 2. Desbloqueio, autenticação e sessão

- **Desbloqueio local = senha mestra** (decisão D1). A chave do banco é derivada dela; a senha do
  Windows **não** substitui a senha mestra. Windows Hello pode virar um atalho opcional no futuro,
  desligado por padrão.
- **Derivação de chave com Argon2id via libsodium (PyNaCl) é permitida e obrigatória.** O que é
  proibido é inventar hash de senha de login, emissão de token ou fluxo OAuth: a autenticação na nuvem
  é delegada ao Supabase Auth.
- A senha enviada ao Supabase é **derivada** da senha mestra (`HKDF(MK, "auth")`); o servidor nunca vê
  a senha mestra.
- Política de senha mestra: mín. 12 caracteres ou frase-senha de 4+ palavras, medidor de força,
  checagem opcional contra senhas vazadas (k-anonymity).
- MFA (TOTP) obrigatório para a conta na nuvem; RLS exige `aal2`.
- Tokens de sessão/refresh guardados **somente** no Windows Credential Manager/DPAPI. Nunca em
  arquivo, no banco ou em configuração.
- **Bloqueio automático** (decisão D2): padrão **3 min** de inatividade (configurável de 1 a 30), e
  **sempre** ao bloquear o Windows ou suspender (o PC do consultório pode ser compartilhado). Ao bloquear:
  sobrescrever as chaves em memória, fechar a conexão do banco e limpar o estado das telas.
- Atraso progressivo após tentativas erradas de desbloqueio (1, 2, 4… até 60 s).
- Mensagens de erro de login genéricas.

## 3. Autorização no backend (Supabase)

O cliente desktop é **não confiável**: pode ser modificado, depurado ou substituído por um script.
Toda regra de acesso é imposta **no servidor**.

- **Negar por padrão.** RLS **ativado em todas as tabelas**, nada liberado para `anon`.
- Cada usuário acessa **somente** os próprios dados: policy `user_id = auth.uid()` **e** `aal2`, com
  `WITH CHECK`. `user_id` com `DEFAULT auth.uid()` e imutável (trigger).
- O banco **local** não tem `owner_id` (decisão D3): é de uma única usuária e todo cifrado. O isolamento
  por usuário é responsabilidade do servidor.
- Validar no servidor o formato (tamanho máximo do `ciphertext`, `hlc` monotônico, cotas).
- Proibido no cliente: `service_role` ou qualquer credencial que ignore o RLS.
- **Regras são código e têm testes automatizados** (pgTAP via `supabase test db`) cobrindo, no mínimo:
  `anon` negado; sessão sem MFA negada; usuário A não lê nem escreve dados de B (tabelas e Storage);
  usuário não altera `user_id`; payload inválido rejeitado; **teste que falha se surgir tabela sem RLS**.
  Esses testes rodam no CI e bloqueiam o merge.

## 4. Criptografia

- **Nunca invente criptografia.** Bibliotecas aprovadas: **PyNaCl/libsodium** (Argon2id,
  XChaCha20-Poly1305, `crypto_secretstream`), **`cryptography`** (HKDF; AES-256-GCM se necessário),
  **SQLCipher** via `sqlcipher3`. Qualquer outra precisa de aprovação.
- Derivação de chave a partir de senha: **Argon2id** (mínimo 64 MiB e 3 iterações; o projeto usa
  ≈256 MiB, calibrado para ~1 s na máquina alvo), salt aleatório.
- Nonces sempre aleatórios de CSPRNG (`secrets`, `nacl.utils.random`), nunca reutilizados com a mesma
  chave. Nunca `random` para nada de segurança.
- Hierarquia de chaves: senha → MK → *KEK* → cifra a *DEK* aleatória. Trocar a senha não recifra os dados.
  Chave de recuperação cifra uma segunda cópia da DEK; perder senha **e** chave = perder os dados
  (aceito pelo projeto e explicado na interface).
- **Em repouso:** banco SQLCipher com chave derivada da DEK; DEK nunca gravada em texto claro.
- **Na nuvem:** só dados **já cifrados** no cliente (AAD = user_id‖record_id‖hlc‖key_version).
- **Em trânsito:** apenas HTTPS/TLS 1.2+ (`httpx` + `truststore`); verificação de certificado **sempre** ativa.
- Comparação de segredos/MACs em tempo constante (`hmac.compare_digest`).
- Limitação do Python: não há como apagar memória com garantia. Guardar chaves em `bytearray` e
  sobrescrever ao bloquear; nunca em `str`.

## 5. Dados locais e memória

- Arquivos temporários com dados sensíveis: evitar; se inevitável, cifrados e apagados ao fim.
- **Exportações em CSV, Excel e PDF saem SEM a proteção do app**: avisar a usuária antes de salvar.
  O backup exportado é sempre cifrado.
- Permissões de arquivo restritas ao usuário do Windows.
- **Instância única** do app sobre o mesmo banco (ver `concurrency`).
- Área de transferência limpa 30 s depois de copiar um valor.

## 6. Entrada não confiável

Trate como não confiável: **planilhas importadas**, CSV, backups, respostas da nuvem, área de
transferência, argumentos de linha de comando.

- Validar tipo, tamanho máximo, encoding e cada campo com as **mesmas** regras do formulário.
- **Importação parcial** só com prévia explícita (erro por linha), relatório de erros e confirmação da
  usuária; **nunca em silêncio**; gravação numa **única transação**; lote registrado e reversível.
- **Planilhas Excel:** `openpyxl` com `read_only=True` e `data_only=True`; `defusedxml` instalado
  (protege contra XXE e *billion laughs*); limites de tamanho do arquivo, do conteúdo descompactado
  (*zip bomb*) e de linhas/colunas; **macros nunca executadas** (`.xlsm` só valores, com aviso);
  o app nunca abre a planilha no Excel.
- Parsers XML (OFX, no futuro) sem entidades externas.
- Queries **sempre parametrizadas**; nunca concatenar strings em SQL.
- **CSV/Excel exportados:** neutralizar injeção de fórmula (prefixar `'` em células que começam com
  `=`, `+`, `-`, `@`, tab ou CR).
- Caminhos de arquivo normalizados; impedir path traversal ao restaurar backups.

## 7. Interface Qt (PySide6)

- Todo texto vindo do usuário, de planilhas ou da sincronização é exibido como **texto simples**:
  `setTextFormat(Qt.TextFormat.PlainText)` em `QLabel`, sem `setHtml` com dados. O Qt interpreta HTML
  automaticamente ("rich text"), que é o equivalente ao XSS aqui.
- Não usar `QWebEngine`. Não carregar conteúdo remoto.
- `QTextBrowser`/labels com `setOpenExternalLinks(False)`; links externos só via `QDesktopServices`,
  para URLs de uma lista de permissão.
- Mensagens de erro na tela sem detalhes técnicos (ver §8).

## 8. Logs e erros

- **Proibido logar:** valores, saldos, descrições de lançamentos, nomes de contas, **nomes de pacientes
  e contatos, CPF/CNPJ, telefones, e-mails**, conteúdo de planilhas importadas, tokens, senhas, chaves,
  caminhos com o nome do usuário do Windows.
- Logar eventos e IDs técnicos ("sync falhou: código X, entidade Y, id Z").
- Logging com **filtro de campos permitidos** + teste com dados canário que falha se algo sensível aparecer.
- Sem envio remoto de logs ou de relatórios de erro.
- Erro para a usuária: mensagem amigável + código para consultar no log local.
- Log de auditoria local (sem valores): desbloqueio OK/falha, troca de senha, exportação, importação
  (só contagens), restauração de backup, exclusões em lote.

## 9. Python: proibições específicas

- `pickle`/`marshal`/`shelve` com dados vindos de fora do processo.
- `eval`, `exec`, `compile` com dados externos.
- `yaml.load` sem `SafeLoader` (prefira não usar YAML).
- `subprocess` com `shell=True`.
- `tempfile.mktemp` (usar `NamedTemporaryFile`/`mkstemp`).
- `random` para tokens, nonces, chaves, IDs sensíveis.
- `assert` como verificação de segurança (é removido com `-O`).
- `except Exception: pass` ao redor de código de segurança.

## 10. Cadeia de suprimentos, build e distribuição

- Dependências com versão exata e `uv.lock` com hashes versionado; dependência nova exige justificativa
  (manutenção ativa, licença compatível, sem alternativa na biblioteca padrão).
- `pip-audit` + OSV-Scanner no CI + Dependabot. Vulnerabilidade alta/crítica bloqueia o release.
- SAST no CI: Bandit, Semgrep, CodeQL (Python), regras `S` do ruff.
- GitHub Actions fixadas por SHA, `permissions:` mínimas.
- **Atualizações sempre assinadas e verificadas** (TUF via `tufup`: Ed25519, chave *root* offline,
  proteção contra rollback). Sem assinatura válida, nada é instalado.
- **Authenticode (assinatura de código do instalador) está adiada** por decisão do projeto. Até ser
  habilitada: publicar o SHA-256 do instalador em cada release.
- **Build no CI** a partir de commit com tag, nunca da máquina de desenvolvimento. **Assinatura dos
  metadados TUF localmente**, com as chaves fora do CI e do repositório.

## 11. LGPD (dados de pacientes)

- **Minimização:** de paciente só o nome é obrigatório; CPF apenas quando necessário (recibo);
  endereço opcional. **Nenhuma informação clínica** em descrições ou observações (a interface orienta
  a usar "Tratamento — parcela 2/6"). O app **não é prontuário**.
- **Zero telemetria.**
- **Retenção:** registros financeiros e fiscais por no mínimo 5 anos; rotina de anonimização de
  contatos inativos depois do prazo.
- **Direitos do titular:** exportar os dados de um paciente; corrigir; anonimizar quando a retenção
  legal permitir.
- **Incidentes:** seguir `docs/INCIDENTES.md` (comunicação à ANPD e aos titulares quando houver risco
  relevante — prazo de 3 dias úteis).
- Excluir a conta da nuvem apaga os dados no servidor e os backups na nuvem.
- Dados de teste **sempre sintéticos**; nunca usar dados reais de pacientes em testes, exemplos ou issues.

## Checklist antes de cada commit que toque em área sensível

- [ ] Nenhum segredo novo no diff (gitleaks passou).
- [ ] RLS continua negando por padrão; testes pgTAP passam.
- [ ] Entradas novas validadas; queries parametrizadas.
- [ ] Dados do usuário exibidos como `PlainText`.
- [ ] Nada sensível em logs ou mensagens de erro (teste canário passa).
- [ ] Dependências novas justificadas e sem vulnerabilidades conhecidas.
- [ ] Criptografia só com as bibliotecas e primitivas aprovadas nesta skill.
- [ ] Testes cobrem o caso de abuso (acesso de outro usuário, arquivo/planilha malformada ou maliciosa).

## Checklist antes de cada release

Tudo acima, mais o checklist completo de `docs/PROJETO.md` §7.13: SAST e varredura de dependências
limpos; pgTAP passando; metadados TUF válidos e atualização testada numa VM; SHA-256 publicado;
restauração de backup testada; revisão de segurança (ex.: `/security-review`) no diff desde o último release.

## Adaptação à stack

- **Cripto:** PyNaCl (`nacl.pwhash.argon2id`, `nacl.bindings.crypto_aead_xchacha20poly1305_ietf_*`,
  `crypto_secretstream_*`), `cryptography` (HKDF).
- **Banco cifrado:** `sqlcipher3` (chave bruta derivada da DEK).
- **Cofre do SO:** `keyring` (Credential Manager) + DPAPI via `pywin32` (`win32crypt`).
- **Rede:** `httpx` + `truststore`.
- **Planilhas:** `openpyxl` + `defusedxml`.
- **Varreduras:** `uv run pip-audit`, `uv run bandit -r src`, Semgrep, CodeQL, `gitleaks`.
- **Testes de regras:** `supabase test db` (pgTAP).
- **Atualização:** `tufup`.
- *Versões exatas e comandos finais: preencher na fase 0.*

## Skills relacionadas

`backend-architecture` (onde cada controle mora), `repository-pattern` (queries parametrizadas),
`concurrency` (instância única, sync), `frontend-architecture` (bloqueio, ocultar valores, PlainText),
`dominio-consultorio` (minimização de dados de pacientes).
