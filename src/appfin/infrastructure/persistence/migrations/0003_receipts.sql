-- 0003: recibos internos numerados (comprovante complementar; não substitui NFS-e).
-- Um recibo por lançamento; o número é sequencial e nunca reutilizado.

CREATE TABLE receipt (
    id             TEXT PRIMARY KEY,
    number         INTEGER NOT NULL UNIQUE CHECK (number >= 1),
    transaction_id TEXT NOT NULL UNIQUE REFERENCES financial_transaction (id),
    issued_on      TEXT NOT NULL CHECK (issued_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    version        INTEGER NOT NULL CHECK (version >= 1),
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
) STRICT;
