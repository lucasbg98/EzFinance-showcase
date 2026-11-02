---
name: concurrency
description: Regras de concorrência do app financeiro do consultório — thread de UI (Qt) vs trabalho em segundo plano, acesso concorrente ao SQLCipher, instância única, sincronização entre máquinas (fase 2), conflitos, idempotência e cancelamento. Use ao escrever código em background (QThreadPool/QThread), sincronização, importação de planilhas, backup, agendamentos ou qualquer coisa que rode em paralelo com a interface.
---

# Concorrência

Há concorrência real: a interface rodando junto com tarefas longas (importação de planilha, relatório,
backup, Argon2id no desbloqueio) e, na fase 2, a sincronização em segundo plano e duas máquinas editando
os mesmos dados. Erros aqui causam o pior tipo de bug financeiro: lançamento duplicado ou perdido em silêncio.

## 1. Thread de UI

- A thread de UI **nunca** faz I/O (disco, rede), criptografia pesada (Argon2id ≈ 1 s) ou cálculo longo.
  Tudo isso vai para `QThreadPool`/`QRunnable` (ou um `QThread` com worker) e devolve o resultado por **signal**.
- Widgets só são tocados na thread de UI (signals/slots com conexão enfileirada).
- Tarefas longas mostram progresso e aceitam **cancelamento cooperativo** (flag verificada entre lotes);
  cancelar não deixa dados pela metade (a unit of work faz rollback).
- Não misturar `asyncio` com Qt na v1 (complexidade desnecessária).

## 2. Banco local

- **Uma conexão `sqlcipher3` por thread** (conexões não são compartilhadas entre threads).
- Um único escritor serializado; leituras podem ser concorrentes. Modo WAL + `busy_timeout`.
- Toda operação composta acontece dentro de uma transação (ver `repository-pattern`, Unit of Work).
- Transações curtas: nunca segurar transação aberta esperando rede ou a usuária.
- No bloqueio do app, as conexões são fechadas em todas as threads antes de sobrescrever as chaves.

## 3. Instância única

- Só uma instância do app pode abrir o mesmo banco: `QLockFile` no diretório de dados + `QLocalServer`/
  `QLocalSocket` para a segunda instância apenas trazer a primeira janela para frente e sair.

## 4. Concorrência otimista (edição do mesmo dado)

- Toda entidade tem `version`. Atualizar exige a versão lida; se mudou, o repositório lança
  `ConcurrencyConflict`.
- Na interface: avisar que o dado mudou (por outra tela ou sincronização), mostrar o valor atual e
  deixar a usuária decidir. Nunca sobrescrever em silêncio.

## 5. Sincronização entre máquinas (fase 2)

- Alterações locais entram na **outbox** na mesma transação da alteração.
- O envio é **idempotente**: cada alteração tem um `change_id` único; reenviar após queda de rede não
  duplica nada no servidor (upsert por `record_id` só se o `hlc` for maior).
- Uma única rotina de sincronização ativa por vez (trava); disparos extras são agrupados (debounce).
- Recebimento incremental por **`server_seq`**; alterações remotas aplicadas em transação local.
- Conflitos: **last-writer-wins por registro** (`hlc`); se valor, datas ou conta divergirem, a versão
  perdedora vai para `sync_conflict` ("Conflitos para revisar"). Coberto por testes.
- Exclusão sincroniza como *tombstone* (`deleted_at`), para a outra máquina não "ressuscitar" o registro.
- Falhas de rede: retry com backoff exponencial + jitter e limite de tentativas; o app continua offline.

## 6. Tarefas agendadas

- Backup automático, geração de recorrências e lembretes são idempotentes: rodar duas vezes no mesmo
  dia (ou em duas máquinas) não duplica nada. Chave determinística (`recurrence_id + data_da_ocorrência`).
- Agendamento com `QTimer`; nada de laço com `sleep`.

## 7. Estado compartilhado em memória

- Evitar estado global mutável. Caches compartilhados são imutáveis ou protegidos por lock e
  invalidados após alterações.
- Nada de "dormir e torcer" (`time.sleep` para esperar outra tarefa); usar signals, `QWaitCondition`
  ou eventos explícitos.

## Testes

- Testar: duas atualizações concorrentes da mesma entidade; reenvio da mesma alteração; sincronização
  interrompida no meio; recorrência gerada em duas máquinas; **cancelamento de importação no meio**;
  bloqueio do app durante uma tarefa em background.
- Testes determinísticos (relógio e agendador fake; `qtbot.waitSignal` no pytest-qt), sem depender de timing real.

## Adaptação à stack

- PySide6: `QThreadPool` + `QRunnable` + signals; `QLockFile` + `QLocalServer`; `QTimer`.
- SQLCipher: `PRAGMA journal_mode=WAL`, `PRAGMA busy_timeout=5000`.
- Testes: `pytest-qt`.

## Skills relacionadas

`repository-pattern`, `backend-architecture`, `frontend-architecture`, `performance`, `security`.
