-- 0001: base técnica. As tabelas de domínio (contas, categorias, contatos, lançamentos…)
-- entram na fase 1, junto com as entidades e seus testes.

-- Preferências não sensíveis (chave/valor).
CREATE TABLE setting (
    key        TEXT PRIMARY KEY CHECK (length(key) BETWEEN 1 AND 100),
    value      TEXT NOT NULL CHECK (length(value) <= 10000),
    updated_at TEXT NOT NULL
) STRICT;

-- Auditoria local de eventos de segurança. Nunca guarda valores, nomes ou dados de pacientes:
-- só o código do evento e o resultado.
CREATE TABLE audit_event (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    event       TEXT NOT NULL CHECK (event GLOB '[a-z]*' AND length(event) <= 64),
    outcome     TEXT NOT NULL CHECK (outcome IN ('ok', 'failed', 'cancelled'))
) STRICT;

CREATE INDEX idx_audit_event_occurred_at ON audit_event (occurred_at);
