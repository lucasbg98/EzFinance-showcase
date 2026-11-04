-- appfin:foreign-keys-off
-- 0005: base da importação de planilhas (plano de importação §6 e §10).
-- - import_profile: mapeamento salvo (linha da planilha → categoria), só no banco cifrado;
-- - import_batch: um lote por confirmação, com contagens; o nome do arquivo NÃO é guardado
--   (pode conter nome de pessoa): o SHA-256 basta para reconhecer o arquivo;
-- - import_replacement: o que um lote substituiu/removeu, para "desfazer" restaurar;
-- - financial_transaction ganha import_row_key (identidade da célula, índice único entre os
--   não excluídos) e a FK de import_batch_id. Adicionar FK exige reconstruir a tabela
--   (procedimento oficial do SQLite; o migrator desliga as FKs só durante este script).

CREATE TABLE import_profile (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 60),
    layout     TEXT NOT NULL CHECK (layout IN ('monthly_matrix')),
    line_map   TEXT NOT NULL CHECK (json_valid(line_map) AND length(line_map) <= 200000),
    version    INTEGER NOT NULL CHECK (version >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
) STRICT;

CREATE UNIQUE INDEX ux_import_profile_name ON import_profile (name COLLATE NOCASE)
    WHERE deleted_at IS NULL;

CREATE TABLE import_batch (
    id             TEXT PRIMARY KEY,
    profile_id     TEXT NOT NULL REFERENCES import_profile (id),
    source         TEXT NOT NULL CHECK (source IN ('csv', 'xlsx')),
    file_sha256    TEXT NOT NULL
                   CHECK (length(file_sha256) = 64 AND file_sha256 NOT GLOB '*[^0-9a-f]*'),
    period_year    INTEGER NOT NULL CHECK (period_year BETWEEN 2000 AND 2100),
    created_count  INTEGER NOT NULL CHECK (created_count >= 0),
    replaced_count INTEGER NOT NULL CHECK (replaced_count >= 0),
    removed_count  INTEGER NOT NULL CHECK (removed_count >= 0),
    skipped_count  INTEGER NOT NULL CHECK (skipped_count >= 0),
    kept_count     INTEGER NOT NULL CHECK (kept_count >= 0),
    imported_at    TEXT NOT NULL,
    undone_at      TEXT,
    version        INTEGER NOT NULL CHECK (version >= 1),
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
) STRICT;

CREATE INDEX idx_import_batch_imported ON import_batch (imported_at);
CREATE INDEX idx_import_batch_profile ON import_batch (profile_id);

-- new_transaction_id NULL = célula que zerou na planilha: o lote só removeu o antigo.
CREATE TABLE import_replacement (
    batch_id           TEXT NOT NULL REFERENCES import_batch (id),
    old_transaction_id TEXT NOT NULL REFERENCES financial_transaction (id),
    new_transaction_id TEXT REFERENCES financial_transaction (id),
    PRIMARY KEY (batch_id, old_transaction_id),
    CHECK (new_transaction_id IS NULL OR new_transaction_id <> old_transaction_id)
) STRICT;

CREATE TABLE financial_transaction_new (
    id                   TEXT PRIMARY KEY,
    kind                 TEXT NOT NULL
                         CHECK (kind IN ('income', 'expense', 'transfer_out', 'transfer_in')),
    description          TEXT NOT NULL CHECK (length(description) BETWEEN 1 AND 200),
    amount_cents         INTEGER NOT NULL CHECK (amount_cents > 0),
    currency             TEXT NOT NULL DEFAULT 'BRL' CHECK (length(currency) = 3),
    accrual_date         TEXT NOT NULL CHECK (accrual_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    due_date             TEXT NOT NULL CHECK (due_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    paid_date            TEXT CHECK (paid_date IS NULL OR paid_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    status               TEXT NOT NULL CHECK (status IN ('pending', 'paid', 'cancelled')),
    account_id           TEXT NOT NULL REFERENCES account (id),
    category_id          TEXT REFERENCES category (id),
    contact_id           TEXT REFERENCES contact (id),
    payment_method       TEXT CHECK (payment_method IS NULL OR payment_method IN
                         ('cash', 'pix', 'debit', 'credit', 'boleto', 'transfer', 'check', 'other')),
    document_number      TEXT NOT NULL DEFAULT '' CHECK (length(document_number) <= 40),
    official_receipt_ref TEXT NOT NULL DEFAULT '' CHECK (length(official_receipt_ref) <= 60),
    notes                TEXT NOT NULL DEFAULT '' CHECK (length(notes) <= 1000),
    installment_group_id TEXT REFERENCES installment_group (id),
    installment_number   INTEGER CHECK (installment_number IS NULL OR installment_number BETWEEN 1 AND 360),
    transfer_id          TEXT,
    import_batch_id      TEXT REFERENCES import_batch (id),
    import_row_key       TEXT CHECK (import_row_key IS NULL OR
                         (length(import_row_key) = 64 AND import_row_key NOT GLOB '*[^0-9a-f]*')),
    version              INTEGER NOT NULL CHECK (version >= 1),
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    deleted_at           TEXT,
    CHECK ((status = 'paid') = (paid_date IS NOT NULL)),
    CHECK ((kind IN ('transfer_out', 'transfer_in')) = (transfer_id IS NOT NULL)),
    CHECK ((installment_group_id IS NULL) = (installment_number IS NULL)),
    CHECK (import_row_key IS NULL OR import_batch_id IS NOT NULL)
) STRICT;

INSERT INTO financial_transaction_new (
    id, kind, description, amount_cents, currency, accrual_date, due_date, paid_date, status,
    account_id, category_id, contact_id, payment_method, document_number, official_receipt_ref,
    notes, installment_group_id, installment_number, transfer_id, import_batch_id,
    import_row_key, version, created_at, updated_at, deleted_at
)
SELECT
    id, kind, description, amount_cents, currency, accrual_date, due_date, paid_date, status,
    account_id, category_id, contact_id, payment_method, document_number, official_receipt_ref,
    notes, installment_group_id, installment_number, transfer_id, import_batch_id,
    NULL, version, created_at, updated_at, deleted_at
FROM financial_transaction;

DROP TABLE financial_transaction;
ALTER TABLE financial_transaction_new RENAME TO financial_transaction;

-- Índices da 0002 (somem com o DROP) + a identidade da célula importada.
CREATE INDEX idx_tx_due ON financial_transaction (due_date) WHERE deleted_at IS NULL;
CREATE INDEX idx_tx_paid ON financial_transaction (paid_date) WHERE deleted_at IS NULL;
CREATE INDEX idx_tx_accrual ON financial_transaction (accrual_date) WHERE deleted_at IS NULL;
CREATE INDEX idx_tx_account_due ON financial_transaction (account_id, due_date);
CREATE INDEX idx_tx_category_accrual ON financial_transaction (category_id, accrual_date);
CREATE INDEX idx_tx_contact ON financial_transaction (contact_id);
CREATE INDEX idx_tx_status_due ON financial_transaction (status, due_date);
CREATE INDEX idx_tx_installment_group ON financial_transaction (installment_group_id);
CREATE INDEX idx_tx_transfer ON financial_transaction (transfer_id);
CREATE INDEX idx_tx_import_batch ON financial_transaction (import_batch_id);
CREATE UNIQUE INDEX ux_tx_import_row_key ON financial_transaction (import_row_key)
    WHERE deleted_at IS NULL AND import_row_key IS NOT NULL;
