CREATE TABLE IF NOT EXISTS alert_rules (
 id INTEGER PRIMARY KEY, workspace TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
 enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), threshold REAL NOT NULL,
 window_days INTEGER NOT NULL CHECK(window_days>0), severity TEXT NOT NULL,
 min_sample INTEGER NOT NULL CHECK(min_sample>0), version INTEGER NOT NULL DEFAULT 1,
 updated_at TEXT NOT NULL, UNIQUE(workspace,kind)
);
CREATE TABLE IF NOT EXISTS alert_rule_versions (
 rule_id INTEGER NOT NULL REFERENCES alert_rules(id), version INTEGER NOT NULL,
 snapshot_json TEXT NOT NULL, actor TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(rule_id,version)
);
CREATE TABLE IF NOT EXISTS alerts (
 id INTEGER PRIMARY KEY, workspace TEXT NOT NULL, rule_id INTEGER NOT NULL REFERENCES alert_rules(id),
 rule_version INTEGER NOT NULL, rule_snapshot TEXT NOT NULL,
 object_key TEXT NOT NULL, period_start TEXT NOT NULL, period_end TEXT NOT NULL,
 severity TEXT NOT NULL, metric_value REAL NOT NULL, threshold REAL NOT NULL,
 evidence_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT '待处理'
 CHECK(status IN ('待处理','处理中','已解决','已忽略')),
 first_detected TEXT NOT NULL, last_detected TEXT NOT NULL, detected_count INTEGER NOT NULL DEFAULT 1,
 current_triggered INTEGER NOT NULL DEFAULT 1, state_version INTEGER NOT NULL DEFAULT 0,
 UNIQUE(workspace,rule_id,rule_version,object_key,period_start,period_end)
);
CREATE INDEX IF NOT EXISTS alert_queue ON alerts(workspace,status,period_end);
CREATE TABLE IF NOT EXISTS alert_actions (
 id INTEGER PRIMARY KEY, alert_id INTEGER NOT NULL REFERENCES alerts(id),
 from_status TEXT NOT NULL, to_status TEXT NOT NULL, note TEXT NOT NULL,
 actor TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alert_detections (
 id INTEGER PRIMARY KEY, alert_id INTEGER NOT NULL REFERENCES alerts(id),
 metric_value REAL NOT NULL, evidence_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS record_revisions (
 id INTEGER PRIMARY KEY, workspace TEXT NOT NULL, record_id INTEGER NOT NULL REFERENCES records(id),
 base_hash TEXT NOT NULL, original_json TEXT NOT NULL, changes_json TEXT NOT NULL,
 reason TEXT NOT NULL, evidence_ref TEXT NOT NULL, applicant TEXT NOT NULL,
 created_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT '待审核'
 CHECK(status IN ('待审核','已批准','已驳回')), effective_at TEXT,
 anomaly_id INTEGER REFERENCES anomalies(id)
);
CREATE INDEX IF NOT EXISTS revision_effective ON record_revisions(workspace,record_id,status,id);
CREATE TABLE IF NOT EXISTS revision_reviews (
 id INTEGER PRIMARY KEY, revision_id INTEGER NOT NULL UNIQUE REFERENCES record_revisions(id),
 decision TEXT NOT NULL CHECK(decision IN ('已批准','已驳回')),
 actor TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS revision_approved_immutable BEFORE UPDATE ON record_revisions WHEN OLD.status!='待审核' BEGIN SELECT RAISE(ABORT,'approved/rejected revisions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS revisions_no_delete BEFORE DELETE ON record_revisions BEGIN SELECT RAISE(ABORT,'revision history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS revision_reviews_no_update BEFORE UPDATE ON revision_reviews BEGIN SELECT RAISE(ABORT,'revision reviews are append-only'); END;
CREATE TRIGGER IF NOT EXISTS revision_reviews_no_delete BEFORE DELETE ON revision_reviews BEGIN SELECT RAISE(ABORT,'revision reviews are append-only'); END;
CREATE TRIGGER IF NOT EXISTS alert_actions_no_update BEFORE UPDATE ON alert_actions BEGIN SELECT RAISE(ABORT,'alert actions are append-only'); END;
CREATE TRIGGER IF NOT EXISTS alert_actions_no_delete BEFORE DELETE ON alert_actions BEGIN SELECT RAISE(ABORT,'alert actions are append-only'); END;
CREATE TRIGGER IF NOT EXISTS rule_history_no_update BEFORE UPDATE ON alert_rule_versions BEGIN SELECT RAISE(ABORT,'rule versions are append-only'); END;
CREATE TRIGGER IF NOT EXISTS rule_history_no_delete BEFORE DELETE ON alert_rule_versions BEGIN SELECT RAISE(ABORT,'rule versions are append-only'); END;
CREATE TRIGGER IF NOT EXISTS detections_no_update BEFORE UPDATE ON alert_detections BEGIN SELECT RAISE(ABORT,'detection evidence is append-only'); END;
CREATE TRIGGER IF NOT EXISTS detections_no_delete BEFORE DELETE ON alert_detections BEGIN SELECT RAISE(ABORT,'detection evidence is append-only'); END;
