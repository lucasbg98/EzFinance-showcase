# ADR-0001 — Decisões técnicas da fundação (fase 0)

- **Data:** 02/11/2026
- **Status:** aceito

## Contexto

O `docs/PROJETO.md` (v0.3) definiu Python + PySide6 + SQLCipher, local-first, com criptografia em
camadas. A fase 0 precisava confirmar na prática os pontos marcados como 🔶 e fixar as bibliotecas.

## Decisões

1. **SQLCipher via `sqlcipher3` 0.6.4** (pacote oficial; inclui SQLCipher 4.19 + OpenSSL, wheel para
   Windows/3.13). Verificado em teste: o arquivo não tem cabeçalho SQLite, o conteúdo não aparece
   em claro e uma chave errada é rejeitada. A alternativa `sqlcipher3-wheels` foi descartada.
2. **Chave do banco bruta** (`PRAGMA key = "x'…'"`), derivada da DEK via HKDF; sem o PBKDF2 interno do
   SQLCipher (a derivação forte é o Argon2id). `cipher_memory_security`, `secure_delete`,
   `foreign_keys` e WAL ligados.
3. **Criptografia com PyNaCl/libsodium** (Argon2id, XChaCha20-Poly1305) e **`cryptography`** (HKDF).
   Conferências automáticas: Argon2id igual ao da implementação de referência (`argon2-cffi`) e HKDF
   igual ao vetor do RFC 5869.
4. **Envelope do cofre (`vault.json`)** com duas cópias da DEK (senha e chave de recuperação). O AAD
   da cópia da senha inclui formato, versão, parâmetros e salt (adulteração → falha); o da cópia de
   recuperação não depende do Argon2, permitindo trocar a senha com salt novo. Parâmetros abaixo de
   64 MiB/3 iterações são recusados antes de derivar.
5. **Conexão aberta na thread de trabalho e entregue à UI**: permitido porque o SQLite embutido é
   `THREADSAFE=1` (serializado), verificado em teste. Depois da entrega, só a thread da UI usa a conexão.
6. **Logs por evento com lista de campos permitidos** (`app_logging.py`); exceções só pelo tipo;
   mensagens de bibliotecas de terceiros reduzidas à origem. Teste canário no CI.
7. **Cadeia de suprimentos:** `uv.lock` com hashes; `exclude-newer` no `pyproject.toml` (ignora
   versões com menos de ~2 semanas); GitHub Actions fixadas por SHA em versões com mais de 2 semanas;
   `pip-audit` sobre o lockfile exportado com `--require-hashes`. Na primeira execução ele apontou
   PYSEC-2026-1845 no `pytest` 8.4.2 → atualizado para 9.0.3.
8. **Interface:** `pyside6-essentials` (os addons, como QtCharts, entram na fase 1); todo texto dinâmico
   em `PlainText`; bloqueio por inatividade (3 min), por Win+L e por suspensão; instância única com
   `QLockFile` + `QLocalServer`.

## Consequências / pendências

- O Argon2id de produção (256 MiB, 3 iterações) leva ~0,26 s na máquina de desenvolvimento: abaixo da
  meta de ~1 s. Calibrar no PC do consultório (ver resumo da fase 0).
- Ainda faltam para fechar a fase 0: empacotamento (PyInstaller + Inno Setup), atualização assinada
  com tufup (chaves de teste) e o teste numa VM.
- Bloquear o Windows enquanto a chave de recuperação está na tela faz a chave sumir antes de ser
  anotada → "gerar nova chave de recuperação" entra na fase 1.
