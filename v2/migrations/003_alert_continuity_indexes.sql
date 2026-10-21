CREATE INDEX IF NOT EXISTS ongoing_alert_objects ON alerts(workspace,rule_id,rule_version,object_key,status);
CREATE INDEX IF NOT EXISTS detection_period_lookup ON alert_detections(alert_id,json_extract(evidence_json,'$.period.start'),json_extract(evidence_json,'$.period.end'));
