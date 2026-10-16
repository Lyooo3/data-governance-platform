CREATE TABLE IF NOT EXISTS raw_snapshots (
 id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES data_sources(id) ON DELETE RESTRICT,
 name TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('RUNNING','SUCCESS','FAILED','CANCELLED','INTERRUPTED')),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_raw_snapshots_source ON raw_snapshots(source_id,created_at);
CREATE TABLE IF NOT EXISTS raw_snapshot_tables (
 id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES raw_snapshots(id) ON DELETE CASCADE,
 schema_name TEXT NOT NULL, table_name TEXT NOT NULL, row_count INTEGER NOT NULL DEFAULT 0,
 payload_json TEXT NOT NULL, UNIQUE(snapshot_id,schema_name,table_name)
);
CREATE TABLE IF NOT EXISTS raw_dataset_links (
 dataset_id TEXT PRIMARY KEY REFERENCES datasets(id) ON DELETE CASCADE,
 snapshot_id TEXT NOT NULL REFERENCES raw_snapshots(id) ON DELETE RESTRICT,
 table_id TEXT NOT NULL REFERENCES raw_snapshot_tables(id) ON DELETE RESTRICT,
 created_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
