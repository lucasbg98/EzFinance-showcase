# Análise das skills do projeto (`skills/`)

> Revisão de 02/11/2026 contra o `docs/PROJETO.md` v0.3. **Nenhuma skill foi alterada.** Este documento
> só aponta problemas e propõe ajustes para você validar.

## 1. Veredito geral

As 7 skills (`backend-architecture`, `clean-code`, `concurrency`, `frontend-architecture`, `performance`,
`repository-pattern`, `security`) são **boas e fazem sentido para o projeto**: são objetivas, têm regras
verificáveis, se referenciam entre si e já preveem uma seção "Adaptação à stack". Recomendo **manter
todas**, com 3 tipos de ajuste:

1. **Contexto desatualizado.** Foram escritas para um "app financeiro **pessoal**" genérico (com
   menções a Firebase, Tauri, Electron, faturas de cartão e orçamentos como núcleo). O projeto agora é um
   **consultório odontológico PJ**, com **dados de pacientes** (a LGPD se aplica de verdade) e
   **Python + PySide6**.
2. **Conflitos com o PROJETO.md.** Há 8 pontos em que a skill e o documento dizem coisas diferentes.
   A IA vai seguir a skill no dia a dia, então cada conflito precisa de uma decisão (seção 3).
3. **Lacunas.** Faltam regras específicas de Qt/Python e do domínio do consultório (seção 4).

**Instalação:** o Claude Code só carrega skills de projeto em `.claude/skills/<nome>/SKILL.md`. Quando
aprovarmos, a pasta `skills/` vai para `.claude/skills/` (mantendo o formato atual, que já está correto:
frontmatter com `name` e `description`). Sugiro também um `CLAUDE.md` curto na raiz, apontando para o
`docs/PROJETO.md` e as skills, com os comandos do projeto (testes, lint, build).

## 2. Análise por skill

### 2.1 `security` — manter, com ajustes (a mais importante)

| # | Ponto | Problema | Proposta |
|---|---|---|---|
| S1 | Abertura: "dados financeiros pessoais" | Agora há **dados de pacientes** (CPF, contato, histórico que pode revelar tratamento = dado de saúde) | Reescrever o contexto. Incluir dados de pacientes como ativo crítico |
| S2 | §5: "Exportações (CSV, PDF, backup) avisam que o arquivo **sai protegido pelo app**" | **Erro de sentido:** CSV e PDF saem **sem** proteção | "avisam que o arquivo sai **sem** a proteção do app (exceto o backup, que é cifrado)" |
| S3 | §2: "Desbloqueio exige senha/PIN/biometria **do SO**" | Conflito: no PROJETO o desbloqueio exige a **senha mestra** (é dela que sai a chave do banco). Windows Hello fica como opcional futuro | Ver decisão D1 |
| S4 | §2: bloqueio padrão 5 min; "ao minimizar/bloquear a tela, **se o usuário ativar**" | PROJETO: 3 min e bloqueio **sempre** ao bloquear o Windows (PC compartilhado no consultório) | Ver decisão D2 |
| S5 | §2: "Nunca implemente hash de senha" | Correto para login, mas pode confundir: a senha mestra local **é** derivada por nós com Argon2id (via libsodium) | Esclarecer: "derivação de chave com Argon2id via libsodium é permitida e obrigatória; o que é proibido é inventar hash/token de autenticação" |
| S6 | §6: "rejeitar o arquivo inteiro em vez de importar parcialmente sem avisar" | O PROJETO prevê **prévia com erro por linha** e importação só das linhas válidas, com confirmação | Ajustar: "importação parcial só com prévia explícita, relatório de erros e confirmação; nunca em silêncio; sempre numa única transação" |
| S7 | §6: entrada não confiável | Faltam riscos de **planilha Excel**: macros, *zip bomb*, *XML bomb* | Acrescentar: openpyxl `read_only` + `data_only`, `defusedxml` instalado, limites de tamanho/linhas, macros nunca executadas |
| S8 | §7 só cobre Electron/Tauri | A stack é **Qt**. O risco equivalente ao XSS é o QLabel interpretar HTML automaticamente | Nova §7 "Interface Qt": `Qt.PlainText` para todo dado do usuário; nada de QWebEngine; links externos só via `QDesktopServices` com lista de permissão |
| S9 | §8: lista do que é proibido logar | Faltam **nome de paciente, CPF/CNPJ, telefone** | Acrescentar |
| S10 | §9: "Instalador e executável **assinados**" | 🗣️ Você adiou a assinatura de código (P7). A regra bloquearia toda release | "Atualizações **sempre** assinadas (TUF/tufup). Authenticode quando for habilitado; até lá, publicar o SHA-256 do instalador" |
| S11 | §9: "Builds no CI, nunca na máquina de desenvolvimento" | OK, mas no PROJETO a **assinatura TUF** é feita localmente (chaves offline) | "Build no CI; assinatura dos metadados TUF localmente, com as chaves fora do CI" |
| S12 | §10 LGPD "básico" | Insuficiente com dados de saúde | Ampliar: minimização (sem informação clínica nas descrições), retenção mínima de 5 anos, direitos do titular (exportar/anonimizar paciente), resposta a incidentes |
| S13 | Faltam proibições específicas de Python | — | `pickle`/`marshal` com dados externos, `eval`/`exec`, `yaml.load` inseguro, `subprocess(shell=True)`, `random` para segurança, `tempfile.mktemp` |
| S14 | §3 e checklist citam Firebase/emulador | O backend é Supabase | Trocar por Supabase + pgTAP; manter o Firebase só se quiser a skill genérica |

### 2.2 `backend-architecture` — manter, com ajustes

| # | Ponto | Problema | Proposta |
|---|---|---|---|
| B1 | Metadados: `owner_id`, `version`, `device_id` | PROJETO usa `hlc` + `origin_device_id` e não tem `owner_id` local | Ver decisões D3 e D4 |
| B2 | Transferência = **duas pernas** com `transfer_id` | PROJETO usa **uma linha** com `to_account_id` | Ver decisão D5. Recomendo adotar a skill (duas pernas) |
| B3 | Sync: "recebimento incremental por `updated_at`/cursor" | Com E2EE o servidor não vê o `updated_at` real, e relógios de máquinas diferentes divergem | "Cursor = `server_seq` (sequência do servidor); nunca relógio do cliente" |
| B4 | Conflitos: "último a escrever vence **por campo**; valor/data vão para o usuário decidir" | PROJETO: LWW **por registro** | Ver decisão D6 |
| B5 | Exemplos de casos de uso: `PayInvoice`, `ImportOfx` | Não são do MVP | Trocar por `ImportSpreadsheet`, `IssueReceipt`, `BuildIncomeStatement` (DRE) |
| B6 | Regras de cartão de crédito como "inegociáveis" | Para o consultório, o mais relevante é o **recebível de maquininha** (taxa + prazo D+30/antecipação), não a fatura de cartão da clínica | Manter a regra de cartão (fase 3) e acrescentar recebíveis de cartão |
| B7 | Datas: "distinguir competência, vencimento e pagamento" | ✅ Alinhado com a P13 (seletor caixa/competência) | Acrescentar a regra do PROJETO: parcelas herdam a mesma competência |
| B8 | Arredondamento de parcelas (resto nas primeiras) | ✅ Igual ao PROJETO | — |

### 2.3 `repository-pattern` — manter, com ajustes

| # | Ponto | Problema | Proposta |
|---|---|---|---|
| R1 | "Sempre filtrar pelo `owner_id`, também localmente" | O banco local é de **uma** usuária e todo cifrado. O `owner_id` local não protege nada e polui todas as consultas | Ver decisão D3 |
| R2 | Menciona "Firestore" e "Firebase" | Backend é Supabase | Trocar |
| R3 | Lista de repositórios (CreditCard, Budget…) | MVP precisa de `CompanyRepository`, `ContactRepository`, `ReceiptRepository`, `ImportBatchRepository` | Atualizar a lista |
| R4 | Não define biblioteca | — | Proposta: **SQL puro** parametrizado (API do `sqlite3`, compatível com o `sqlcipher3`) + mapeadores manuais; migrações numeradas em `.sql` + `PRAGMA user_version`. Sem ORM: menos dependências e controle total sobre a cifra |
| R5 | Paginação obrigatória | ✅ Combina com `QAbstractTableModel` + `canFetchMore`/`fetchMore` | Citar na adaptação |

### 2.4 `concurrency` — manter, com pequenos ajustes

Bem escrita e muito adequada. Ajustes:
- **C1:** registrar o modelo da stack: `QThreadPool`/`QRunnable` (ou `QThread` com worker) + **signals** para devolver o resultado à UI; sem `asyncio` misturado com Qt na v1 (menos complexidade).
- **C2:** conexão `sqlcipher3` **por thread** (não compartilhar conexões), um único escritor serializado; `busy_timeout` e WAL.
- **C3:** instância única com `QLockFile` + `QLocalServer`/`QLocalSocket` para trazer a janela existente para frente.
- **C4:** Argon2id (≈1 s) roda em background; a tela de desbloqueio mostra progresso.
- **C5:** a política de conflito precisa bater com a decisão D6.
- **C6:** a sincronização só existe na fase 2. Até lá valem as seções 1–4 e 6.

### 2.5 `frontend-architecture` — manter, com ajustes

| # | Ponto | Problema | Proposta |
|---|---|---|---|
| F1 | Pastas **por funcionalidade** (`features/credit-cards/`…) | O PROJETO §9 organiza por tipo (`ui/screens`, `viewmodels`). Em Python o hífen é inválido em nome de pacote | Ver decisão D7. Recomendo adotar a skill: `features/transactions/`, `contacts/`, `categories/`, `accounts/`, `reports/`, `income_statement/`, `receipts/`, `spreadsheet_import/`, `company/`, `settings/` |
| F2 | Não menciona Qt | Faltam: **model/view do Qt** (`QAbstractTableModel` é virtualizado; evitar `QTableWidget` com muitos itens), QSS centralizado como *design tokens*, `QtCharts`, `Qt.PlainText` | Acrescentar uma seção "Qt" |
| F3 | "Ocultar valores" global | ✅ Ótimo. No PROJETO estava na fase 2 | Ver decisão D8 (subir para o MVP, já que o PC é compartilhado) |
| F4 | Testes de UI: "transferir, pagar fatura" | Fora do MVP | Trocar por: lançamento parcelado, marcar como recebido, emitir recibo, importar planilha, DRE caixa × competência, bloquear/desbloquear |
| F5 | Feriados no locale | Útil para lembretes (fase 2) | Manter |

### 2.6 `performance` — manter, com pequenos ajustes

- **P1:** as metas são realistas, mas "abrir o app em < 2 s" com Python + PyInstaller *onedir* é **justo**. Adiar imports pesados (reportlab, openpyxl, QtCharts) até o uso e medir na fase 0.
- **P2:** índices com `owner_id` dependem da decisão D3. Índices sugeridos para o MVP: `(due_date)`, `(paid_date)`, `(accrual_date)`, `(account_id, due_date)`, `(category_id, accrual_date)`, `(contact_id)`, `(status, due_date)`.
- **P3:** "(updated_at) para sync" → a sync usa a `outbox`; o índice não é necessário.
- **P4:** registrar as ferramentas: `cProfile`/`py-spy`, `pytest-benchmark` e um gerador de base sintética (`scripts/gen_synthetic_db.py`).
- **P5:** a importação de planilha grande entra nas metas (ex.: 5 mil linhas com prévia em < 3 s).

### 2.7 `clean-code` — manter, com ajustes no glossário

**Glossário: acrescentar**

| Português (UI) | Código |
|---|---|
| Paciente / Fornecedor / Convênio (papéis de contato) | `Contact` + `ContactRole.PATIENT / SUPPLIER / INSURER` |
| Empresa (dados do consultório) | `Company` |
| Recibo | `Receipt` |
| DRE | `IncomeStatement` |
| Regime de caixa / competência | `CashBasis` / `AccrualBasis` |
| Forma de pagamento | `PaymentMethod` |
| Situação (pendente/pago/cancelado) | `TransactionStatus` |
| Importação / lote importado | `SpreadsheetImport` / `ImportBatch` |
| Conta caixa | `Account` (já existe) |

**Ajustar:** "Fatura" → `Invoice` é **ambíguo** num consultório PJ ("invoice" também lembra nota fiscal).
Sugiro `CardStatement` para fatura de cartão e reservar `ServiceInvoice` para NFS-e, se um dia existir
(o PROJETO já usa `card_statement`).

**Outros:**
- O commit `security:` não faz parte do Conventional Commits padrão. Tudo bem, mas é preciso configurar no commitlint, se usarmos.
- "Nunca meus dados financeiros reais" → acrescentar "**nem dados de pacientes**".
- Definição de pronto: acrescentar "migração testada com backup prévio" quando houver mudança de esquema.

## 3. Conflitos que precisam da sua decisão

| # | Tema | Skill diz | PROJETO diz | Minha recomendação |
|---|---|---|---|---|
| **D1** | Desbloqueio | Senha/PIN/biometria do SO | Senha mestra (a chave do banco sai dela) | **PROJETO.** A senha do Windows não protege o banco se o PC for roubado e o disco copiado. Windows Hello fica como atalho opcional futuro | D: Projeto
| **D2** | Bloqueio automático | 5 min; ao bloquear a tela só se ativado | 3 min; sempre ao bloquear o Windows | **PROJETO** (PC compartilhado no consultório) | D: Projeto
| **D3** | `owner_id` local | Em toda entidade e toda consulta | Só no servidor (`user_id`) | **PROJETO:** sem `owner_id` local (o banco inteiro é de uma usuária e é cifrado); `user_id` obrigatório no servidor com RLS | D: Projeto
| **D4** | Versão do registro | `version` inteiro | `hlc` | **Ambos:** `version` para concorrência otimista local (a skill está certa) + `hlc` para ordenar na sincronização (fase 2) | D: ambos, como recomendado
| **D5** | Transferência | Duas pernas com `transfer_id` | Uma linha com `to_account_id` | **Skill:** duas pernas deixam consultas por conta e saldos mais simples e robustos. Atualizo o PROJETO | D: skill, como sugerido
| **D6** | Conflito de sync | LWW por campo; valor/data/conta → usuário decide | LWW por registro | **Meio-termo:** LWW por registro, mas se valor, data ou conta divergirem, a versão perdedora vai para uma lista de "Conflitos para revisar". Sem perda silenciosa e mais simples que mesclar por campo | D: como sugerido
| **D7** | Organização da UI | Pastas por funcionalidade | Por tipo (`screens`/`viewmodels`) | **Skill** (por funcionalidade). Atualizo o PROJETO §9 | D: skill, como sugerido
| **D8** | "Ocultar valores" | Sem fase definida | Fase 2 ("modo privacidade") | **Subir para o MVP:** é barato e protege dados na tela de um PC compartilhado | D: faça como sugerido

## 4. Skills novas sugeridas (opcionais)

| Skill | Conteúdo | Quando criar |
|---|---|---|
| `dominio-consultorio` | Glossário do consultório, categorias e grupos do DRE padrão, regra caixa × competência, parcelamento de tratamento, recibo × NFS-e, minimização de dados de pacientes (sem informação clínica) | Agora (evita que a IA trate o app como "finanças pessoais") |
| `importacao-planilha` | Formato da planilha do consultório, mapeamento, regras de conversão e dedupe, casos de teste | Quando chegar o modelo (P12) |
| `release` | Passo a passo de release: build no CI, assinatura TUF local, SHA-256, checklist do PROJETO §7.13, teste de atualização numa VM | Fase 0 |

Não sugiro criar mais skills além dessas. Mais regras = mais contexto e menos foco.

## 5. "Adaptação à stack" — conteúdo proposto (para preencher depois da aprovação)

| Skill | Conteúdo |
|---|---|
| Todas | Python 3.13, PySide6, `uv` (`uv run pytest`, `uv run ruff check`, `uv run mypy --strict src`) |
| `security` | PyNaCl (Argon2id, XChaCha20-Poly1305, secretstream), `cryptography` (HKDF), `sqlcipher3`, `keyring` + DPAPI, `truststore`, `defusedxml`; pip-audit, Bandit, Semgrep, CodeQL, gitleaks; pgTAP (`supabase test db`); tufup |
| `backend-architecture` | Composição manual de dependências em `appfin/bootstrap.py` (sem framework de DI); migrações `.sql` numeradas + `PRAGMA user_version`; cliente Supabase com `httpx` (fase 2) |
| `repository-pattern` | SQL puro + mapeadores; `UnitOfWork` como *context manager*; fakes em `tests/fakes/`; testes de contrato com `pytest` parametrizado (fake × SQLCipher) |
| `concurrency` | `QThreadPool` + signals; uma conexão por thread; `QLockFile` + `QLocalServer` |
| `frontend-architecture` | MVVM com QObject/signals; `QAbstractTableModel`; QSS com tokens; QtCharts; pytest-qt |
| `performance` | `cProfile`, `py-spy`, `pytest-benchmark`, `scripts/gen_synthetic_db.py` |
| `clean-code` | ruff (lint + format), mypy `--strict`, pytest + hypothesis, pre-commit |

## 6. Situação (02/11/2026)

✅ **D1–D8 aprovadas conforme a recomendação** e aplicadas:
1. Skills ajustadas gravadas em **`.claude/skills/`** (S1–S14, B1–B8, R1–R5, C1–C6, F1–F5, P1–P5,
   glossário, "Adaptação à stack" preenchida com o previsto). A pasta original `skills/` **foi mantida
   intacta** para você comparar. Depois de revisar, ela pode ser apagada.
2. Nova skill **`dominio-consultorio`** criada.
3. `PROJETO.md` atualizado: `version` + `hlc` (D4), transferência em duas pernas (D5), lista de
   conflitos (D6), pastas por funcionalidade (D7), "Ocultar valores" no MVP (D8), sem `owner_id` local (D3).
4. **`CLAUDE.md`** criado na raiz.

Pendente: skill `release` (fase 0). A skill `importacao-planilha` foi criada na v0.7.0.
