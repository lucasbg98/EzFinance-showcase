-- appfin:foreign-keys-off
-- 0004: grupo "investments" no DRE (plano de importação §7.1).
-- O SQLite não altera CHECK; a tabela category é reconstruída pelo procedimento oficial
-- (https://sqlite.org/lang_altertable.html#otheralter): o migrator desliga as chaves estrangeiras,
-- roda este script numa transação, confere PRAGMA foreign_key_check e só então faz o commit.
-- Ids, colunas e dados são copiados sem alteração; só o CHECK de dre_group muda.

CREATE TABLE category_new (
    id         TEXT PRIMARY KEY,
    parent_id  TEXT REFERENCES category (id),
    name       TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 60),
    kind       TEXT NOT NULL CHECK (kind IN ('income', 'expense', 'both')),
    dre_group  TEXT CHECK (dre_group IS NULL OR dre_group IN (
                   'gross_revenue', 'deductions', 'taxes', 'direct_costs',
                   'operating_expenses', 'selling_expenses', 'investments', 'other_results')),
    archived   INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    version    INTEGER NOT NULL CHECK (version >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    CHECK (parent_id IS NULL OR parent_id <> id)
) STRICT;

INSERT INTO category_new
    (id, parent_id, name, kind, dre_group, archived, version, created_at, updated_at, deleted_at)
SELECT id, parent_id, name, kind, dre_group, archived, version, created_at, updated_at, deleted_at
FROM category;

DROP TABLE category;
ALTER TABLE category_new RENAME TO category;

CREATE INDEX idx_category_parent ON category (parent_id);
