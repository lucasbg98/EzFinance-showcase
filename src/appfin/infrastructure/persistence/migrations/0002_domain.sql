-- 0002: tabelas do domínio do consultório (fase 1).
-- Convenções (docs/PROJETO.md §6.1): ids UUIDv7 em texto; dinheiro em centavos (INTEGER);
-- datas de calendário 'AAAA-MM-DD'; timestamps UTC ISO-8601; soft delete por deleted_at;
-- version para concorrência otimista. Sem owner_id local (decisão D3).

CREATE TABLE company (
    id          TEXT PRIMARY KEY CHECK (id = 'company'),
    legal_type  TEXT NOT NULL CHECK (legal_type IN ('pf', 'pj')),
    name        TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    trade_name  TEXT NOT NULL DEFAULT '' CHECK (length(trade_name) <= 120),
    document    TEXT NOT NULL DEFAULT '' CHECK (document GLOB '*' AND length(document) IN (0, 11, 14)),
    cro_number  TEXT NOT NULL DEFAULT '' CHECK (length(cro_number) <= 20),
    responsible TEXT NOT NULL DEFAULT '' CHECK (length(responsible) <= 120),
    address     TEXT NOT NULL DEFAULT '' CHECK (length(address) <= 300),
    phone       TEXT NOT NULL DEFAULT '' CHECK (length(phone) <= 13),
    whatsapp    TEXT NOT NULL DEFAULT '' CHECK (length(whatsapp) <= 13),
    email       TEXT NOT NULL DEFAULT '' CHECK (length(email) <= 254),
    tax_regime  TEXT NOT NULL CHECK (tax_regime IN ('simples', 'presumido', 'carne_leao', 'other')),
    version     INTEGER NOT NULL CHECK (version >= 1),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
) STRICT;

CREATE TABLE account (
    id                    TEXT PRIMARY KEY,
    name                  TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 60),
    kind                  TEXT NOT NULL
                          CHECK (kind IN ('cash', 'checking', 'savings', 'card_acquirer', 'other')),
    opening_balance_cents INTEGER NOT NULL DEFAULT 0,
    currency              TEXT NOT NULL DEFAULT 'BRL' CHECK (length(currency) = 3),
    opening_date          TEXT CHECK (opening_date IS NULL OR opening_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    archived              INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    version               INTEGER NOT NULL CHECK (version >= 1),
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    deleted_at            TEXT
) STRICT;

CREATE TABLE category (
    id         TEXT PRIMARY KEY,
    parent_id  TEXT REFERENCES category (id),
    name       TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 60),
    kind       TEXT NOT NULL CHECK (kind IN ('income', 'expense', 'both')),
    dre_group  TEXT CHECK (dre_group IS NULL OR dre_group IN (
                   'gross_revenue', 'deductions', 'taxes', 'direct_costs',
                   'operating_expenses', 'selling_expenses', 'other_results')),
    archived   INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    version    INTEGER NOT NULL CHECK (version >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    CHECK (parent_id IS NULL OR parent_id <> id)
) STRICT;

CREATE TABLE contact (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    roles       TEXT NOT NULL CHECK (length(roles) BETWEEN 5 AND 60),
    person_type TEXT NOT NULL CHECK (person_type IN ('pf', 'pj')),
    document    TEXT NOT NULL DEFAULT '' CHECK (length(document) IN (0, 11, 14)),
    phone       TEXT NOT NULL DEFAULT '' CHECK (length(phone) <= 13),
    email       TEXT NOT NULL DEFAULT '' CHECK (length(email) <= 254),
    street      TEXT NOT NULL DEFAULT '' CHECK (length(street) <= 120),
    number      TEXT NOT NULL DEFAULT '' CHECK (length(number) <= 20),
    district    TEXT NOT NULL DEFAULT '' CHECK (length(district) <= 60),
    city        TEXT NOT NULL DEFAULT '' CHECK (length(city) <= 60),
    state       TEXT NOT NULL DEFAULT '' CHECK (length(state) IN (0, 2)),
    zip_code    TEXT NOT NULL DEFAULT '' CHECK (length(zip_code) IN (0, 8)),
    notes       TEXT NOT NULL DEFAULT '' CHECK (length(notes) <= 1000),
    archived    INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    version     INTEGER NOT NULL CHECK (version >= 1),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    deleted_at  TEXT
) STRICT;

CREATE TABLE installment_group (
    id             TEXT PRIMARY KEY,
    count          INTEGER NOT NULL CHECK (count BETWEEN 1 AND 360),
    interval_unit  TEXT NOT NULL CHECK (interval_unit IN ('day', 'month')),
    interval_value INTEGER NOT NULL CHECK (interval_value BETWEEN 1 AND 366),
    total_cents    INTEGER NOT NULL CHECK (total_cents > 0),
    version        INTEGER NOT NULL CHECK (version >= 1),
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    deleted_at     TEXT
) STRICT;

CREATE TABLE financial_transaction (
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
    import_batch_id      TEXT,
    version              INTEGER NOT NULL CHECK (version >= 1),
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    deleted_at           TEXT,
    CHECK ((status = 'paid') = (paid_date IS NOT NULL)),
    CHECK ((kind IN ('transfer_out', 'transfer_in')) = (transfer_id IS NOT NULL)),
    CHECK ((installment_group_id IS NULL) = (installment_number IS NULL))
) STRICT;

-- Fila de alterações para a sincronização (fase 2). Gravada na mesma transação da alteração.
CREATE TABLE outbox (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    entity     TEXT NOT NULL CHECK (length(entity) <= 40),
    record_id  TEXT NOT NULL,
    operation  TEXT NOT NULL CHECK (operation IN ('upsert', 'delete')),
    created_at TEXT NOT NULL
) STRICT;

-- Índices (skill `performance`)
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
CREATE INDEX idx_category_parent ON category (parent_id);
CREATE INDEX idx_contact_name ON contact (name COLLATE NOCASE);
