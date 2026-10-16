-- Local governance extensions. No connections to other databases or servers.
CREATE TABLE IF NOT EXISTS governance_reports (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, operation_type TEXT NOT NULL,
 dataset_id TEXT REFERENCES datasets(id) ON DELETE SET NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS governance_approvals (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, target_kind TEXT NOT NULL, target_id TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','withdrawn')),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_approvals_target ON governance_approvals(target_kind,target_id,status);
CREATE TABLE IF NOT EXISTS local_schedules (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, workflow_id TEXT NOT NULL REFERENCES governance_workflows(id) ON DELETE RESTRICT,
 enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), interval_seconds REAL NOT NULL CHECK(interval_seconds>=60),
 next_run_at REAL, last_run_id TEXT REFERENCES job_runs(id) ON DELETE SET NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_schedules_due ON local_schedules(enabled,next_run_at);
CREATE TABLE IF NOT EXISTS local_views (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE RESTRICT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS local_applications (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, owner_id TEXT NOT NULL REFERENCES platform_users(id) ON DELETE RESTRICT,
 enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), api_key_hash TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS application_service_grants (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, app_id TEXT NOT NULL REFERENCES local_applications(id) ON DELETE CASCADE,
 service_id TEXT NOT NULL REFERENCES data_services(id) ON DELETE CASCADE,
 status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','revoked')),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_active_grant ON application_service_grants(app_id,service_id) WHERE status IN ('pending','approved');
CREATE TABLE IF NOT EXISTS interface_adapters (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE RESTRICT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS local_push_channels (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS data_subscriptions (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE RESTRICT,
 channel_id TEXT REFERENCES local_push_channels(id) ON DELETE SET NULL,
 enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), interval_seconds REAL NOT NULL CHECK(interval_seconds>=60), next_run_at REAL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_due ON data_subscriptions(enabled,next_run_at);
CREATE TABLE IF NOT EXISTS subscription_snapshots (
 subscription_id TEXT PRIMARY KEY REFERENCES data_subscriptions(id) ON DELETE CASCADE,
 rows_json TEXT NOT NULL, captured_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS subscription_events (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, subscription_id TEXT NOT NULL REFERENCES data_subscriptions(id) ON DELETE CASCADE,
 change_type TEXT NOT NULL CHECK(change_type IN ('insert','update','delete')),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS event_deliveries (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, event_id TEXT NOT NULL REFERENCES subscription_events(id) ON DELETE CASCADE,
 channel_id TEXT NOT NULL REFERENCES local_push_channels(id) ON DELETE RESTRICT,
 status TEXT NOT NULL CHECK(status IN ('pending','delivered','failed')),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL,
 UNIQUE(event_id,channel_id)
);
CREATE TABLE IF NOT EXISTS local_inbox_messages (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, delivery_id TEXT NOT NULL UNIQUE REFERENCES event_deliveries(id) ON DELETE CASCADE,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
