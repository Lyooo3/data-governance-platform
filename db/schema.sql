-- Governance platform schema v1. Executed only in the platform's local SQLite file.
-- Dates use UTC ISO-8601 text; IDs preserve existing application identifiers.
CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY, description TEXT NOT NULL, applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS platform_settings (
  key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS platform_users (
  id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL CHECK (role IN ('admin','reader')),
  password_hash TEXT NOT NULL, created_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS platform_sessions (
  token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES platform_users(id) ON DELETE CASCADE,
  expires_at REAL NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON platform_sessions(expires_at);
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, code TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS business_types (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, code TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS data_elements (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, code TEXT, field_name TEXT, data_type TEXT, version TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS qualifiers (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, code TEXT, version TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dictionaries (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, code TEXT, version TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dictionary_items (
  dictionary_id TEXT NOT NULL REFERENCES dictionaries(id) ON DELETE CASCADE,
  position INTEGER NOT NULL CHECK(position >= 0), code TEXT NOT NULL, name TEXT NOT NULL, payload_json TEXT NOT NULL,
  PRIMARY KEY(dictionary_id,position)
);
CREATE TABLE IF NOT EXISTS catalogs (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, code TEXT, version TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS data_sources (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, source_type TEXT, host TEXT, port INTEGER, database_name TEXT, user_name TEXT,
  status TEXT NOT NULL DEFAULT 'draft', created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS datasets (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT, is_demo INTEGER NOT NULL DEFAULT 0 CHECK(is_demo IN (0,1)),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dataset_rows (
  dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
  row_index INTEGER NOT NULL CHECK(row_index >= 0), data_json TEXT NOT NULL, PRIMARY KEY(dataset_id,row_index)
);
CREATE TABLE IF NOT EXISTS data_assets (
  id TEXT PRIMARY KEY, name TEXT NOT NULL,
  dataset_id TEXT REFERENCES datasets(id) ON DELETE RESTRICT,
  catalog_id TEXT REFERENCES catalogs(id) ON DELETE RESTRICT,
  level_name TEXT, source_system TEXT, region TEXT, status TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assets_dataset ON data_assets(dataset_id);
CREATE INDEX IF NOT EXISTS idx_assets_catalog ON data_assets(catalog_id);
CREATE TABLE IF NOT EXISTS quality_rules (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, field_name TEXT NOT NULL,
  rule_type TEXT NOT NULL CHECK(rule_type IN ('required','unique','range','regex','enum')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quality_tasks (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE RESTRICT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quality_task_rules (
  task_id TEXT NOT NULL REFERENCES quality_tasks(id) ON DELETE CASCADE,
  position INTEGER NOT NULL, rule_id TEXT NOT NULL REFERENCES quality_rules(id) ON DELETE RESTRICT,
  PRIMARY KEY(task_id,position), UNIQUE(task_id,rule_id)
);
CREATE TABLE IF NOT EXISTS governance_workflows (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_nodes (
  workflow_id TEXT NOT NULL REFERENCES governance_workflows(id) ON DELETE CASCADE,
  node_id TEXT NOT NULL, position INTEGER NOT NULL,
  node_type TEXT NOT NULL CHECK(node_type IN ('source','select','clean','filter','dedupe','quality','output')),
  label TEXT, x REAL NOT NULL DEFAULT 0, y REAL NOT NULL DEFAULT 0,
  dataset_id TEXT REFERENCES datasets(id) ON DELETE RESTRICT, config_json TEXT NOT NULL, payload_json TEXT NOT NULL,
  PRIMARY KEY(workflow_id,node_id), UNIQUE(workflow_id,position)
);
CREATE TABLE IF NOT EXISTS workflow_edges (
  workflow_id TEXT NOT NULL REFERENCES governance_workflows(id) ON DELETE CASCADE,
  position INTEGER NOT NULL, source_node_id TEXT NOT NULL, target_node_id TEXT NOT NULL, payload_json TEXT NOT NULL,
  PRIMARY KEY(workflow_id,position), UNIQUE(workflow_id,source_node_id,target_node_id),
  FOREIGN KEY(workflow_id,source_node_id) REFERENCES workflow_nodes(workflow_id,node_id) ON DELETE CASCADE,
  FOREIGN KEY(workflow_id,target_node_id) REFERENCES workflow_nodes(workflow_id,node_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS workflow_node_rules (
  workflow_id TEXT NOT NULL, node_id TEXT NOT NULL, position INTEGER NOT NULL,
  rule_id TEXT NOT NULL REFERENCES quality_rules(id) ON DELETE RESTRICT,
  PRIMARY KEY(workflow_id,node_id,position), UNIQUE(workflow_id,node_id,rule_id),
  FOREIGN KEY(workflow_id,node_id) REFERENCES workflow_nodes(workflow_id,node_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS metadata_tables (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, dataset_id TEXT REFERENCES datasets(id) ON DELETE RESTRICT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS metadata_columns (
  table_id TEXT NOT NULL REFERENCES metadata_tables(id) ON DELETE CASCADE, position INTEGER NOT NULL,
  name TEXT NOT NULL, data_type TEXT, payload_json TEXT NOT NULL, PRIMARY KEY(table_id,position)
);
CREATE TABLE IF NOT EXISTS alert_policies (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, severity TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job_runs (
  id TEXT PRIMARY KEY, name TEXT NOT NULL,
  workflow_id TEXT REFERENCES governance_workflows(id) ON DELETE SET NULL,
  task_id TEXT REFERENCES quality_tasks(id) ON DELETE SET NULL,
  actor_name TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('RUNNING','SUCCESS','FAILED','CANCELLED','TIMED_OUT','INTERRUPTED')),
  source_count INTEGER, output_count INTEGER, started_at TEXT NOT NULL, finished_at TEXT, error_message TEXT, payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_started ON job_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_status ON job_runs(status);
CREATE TABLE IF NOT EXISTS job_steps (
  run_id TEXT NOT NULL REFERENCES job_runs(id) ON DELETE CASCADE, position INTEGER NOT NULL,
  node_id TEXT, name TEXT, node_type TEXT, input_count INTEGER, output_count INTEGER, payload_json TEXT NOT NULL,
  PRIMARY KEY(run_id,position)
);
CREATE TABLE IF NOT EXISTS quality_reports (
  run_id TEXT NOT NULL REFERENCES job_runs(id) ON DELETE CASCADE, report_index INTEGER NOT NULL,
  node_id TEXT, node_name TEXT, total_rows INTEGER NOT NULL, invalid_rows INTEGER NOT NULL, valid_rows INTEGER NOT NULL,
  pass_rate REAL, payload_json TEXT NOT NULL, PRIMARY KEY(run_id,report_index)
);
CREATE TABLE IF NOT EXISTS quality_rule_results (
  run_id TEXT NOT NULL, report_index INTEGER NOT NULL, position INTEGER NOT NULL,
  rule_id TEXT, name TEXT NOT NULL, field_name TEXT, rule_type TEXT,
  total_rows INTEGER NOT NULL, failed_rows INTEGER NOT NULL, passed_rows INTEGER NOT NULL, failed_indexes_json TEXT NOT NULL, payload_json TEXT NOT NULL,
  PRIMARY KEY(run_id,report_index,position),
  FOREIGN KEY(run_id,report_index) REFERENCES quality_reports(run_id,report_index) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS job_result_rows (
  run_id TEXT NOT NULL REFERENCES job_runs(id) ON DELETE CASCADE, row_index INTEGER NOT NULL,
  data_json TEXT NOT NULL, PRIMARY KEY(run_id,row_index)
);
CREATE TABLE IF NOT EXISTS data_services (
  id TEXT PRIMARY KEY, name TEXT NOT NULL,
  dataset_id TEXT REFERENCES datasets(id) ON DELETE RESTRICT, run_id TEXT REFERENCES job_runs(id) ON DELETE RESTRICT,
  published INTEGER NOT NULL DEFAULT 0 CHECK(published IN (0,1)), api_key_hash TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_services_published ON data_services(published);
CREATE TABLE IF NOT EXISTS data_alerts (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES job_runs(id) ON DELETE CASCADE,
  name TEXT NOT NULL, field_name TEXT, failed_rows INTEGER NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('open','resolved')), created_at TEXT NOT NULL,
  resolved_at TEXT, resolved_by TEXT, note TEXT, failed_indexes_json TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alerts_status_date ON data_alerts(status,created_at DESC);
CREATE TABLE IF NOT EXISTS audit_logs (
  id TEXT PRIMARY KEY, actor_name TEXT NOT NULL, action TEXT NOT NULL, target TEXT,
  created_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action);
