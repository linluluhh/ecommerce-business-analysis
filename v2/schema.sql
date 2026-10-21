PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS batches (
 id TEXT PRIMARY KEY, workspace TEXT NOT NULL, filename TEXT NOT NULL,
 sha256 TEXT NOT NULL, import_kind TEXT NOT NULL, raw_path TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('imported','duplicate','failed')),
 duplicate_of TEXT REFERENCES batches(id), row_count INTEGER NOT NULL DEFAULT 0,
 added_count INTEGER NOT NULL DEFAULT 0, duplicate_rows INTEGER NOT NULL DEFAULT 0,
 error TEXT, created_at TEXT NOT NULL, rule_version TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS batch_once ON batches(workspace,sha256,import_kind) WHERE status='imported';
CREATE TABLE IF NOT EXISTS records (
 id INTEGER PRIMARY KEY, workspace TEXT NOT NULL, batch_id TEXT NOT NULL REFERENCES batches(id),
 table_name TEXT NOT NULL, source_row INTEGER NOT NULL, business_key TEXT NOT NULL,
 fingerprint TEXT NOT NULL, raw_json TEXT NOT NULL,
 UNIQUE(workspace,table_name,fingerprint)
);
CREATE INDEX IF NOT EXISTS record_keys ON records(workspace,table_name,business_key);
CREATE TABLE IF NOT EXISTS anomalies (
 id INTEGER PRIMARY KEY, record_id INTEGER NOT NULL REFERENCES records(id),
 code TEXT NOT NULL, reason TEXT NOT NULL, fields TEXT NOT NULL, severity TEXT NOT NULL,
 scope TEXT NOT NULL CHECK(scope IN ('all','profit','none')),
 hard INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 status TEXT NOT NULL DEFAULT '待核实' CHECK(status IN ('待核实','确认','驳回')),
 version INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
 UNIQUE(record_id,code)
);
CREATE TABLE IF NOT EXISTS reviews (
 id INTEGER PRIMARY KEY, anomaly_id INTEGER NOT NULL REFERENCES anomalies(id),
 from_status TEXT NOT NULL, to_status TEXT NOT NULL CHECK(to_status IN ('待核实','确认','驳回')),
 note TEXT NOT NULL, reviewer TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operation_logs (
 id INTEGER PRIMARY KEY, workspace TEXT NOT NULL, action TEXT NOT NULL,
 target TEXT NOT NULL, actor TEXT NOT NULL, detail_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS immutable_records_update BEFORE UPDATE ON records BEGIN SELECT RAISE(ABORT,'records are immutable'); END;
CREATE TRIGGER IF NOT EXISTS immutable_records_delete BEFORE DELETE ON records BEGIN SELECT RAISE(ABORT,'records are immutable'); END;
CREATE TRIGGER IF NOT EXISTS immutable_reviews_update BEFORE UPDATE ON reviews BEGIN SELECT RAISE(ABORT,'reviews are append-only'); END;
CREATE TRIGGER IF NOT EXISTS immutable_reviews_delete BEFORE DELETE ON reviews BEGIN SELECT RAISE(ABORT,'reviews are append-only'); END;
CREATE TRIGGER IF NOT EXISTS immutable_logs_update BEFORE UPDATE ON operation_logs BEGIN SELECT RAISE(ABORT,'logs are append-only'); END;
CREATE TRIGGER IF NOT EXISTS immutable_logs_delete BEFORE DELETE ON operation_logs BEGIN SELECT RAISE(ABORT,'logs are append-only'); END;
