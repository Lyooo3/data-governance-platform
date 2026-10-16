"""Fixed-table repository for local governance extensions."""

import json
import uuid
from pathlib import Path
from .storage import encoded, now

TABLES = {
    "reports": "governance_reports",
    "approvals": "governance_approvals",
    "schedules": "local_schedules",
    "views": "local_views",
    "apps": "local_applications",
    "grants": "application_service_grants",
    "adapters": "interface_adapters",
    "channels": "local_push_channels",
    "subscriptions": "data_subscriptions",
    "events": "subscription_events",
    "deliveries": "event_deliveries",
    "inbox": "local_inbox_messages",
}
FIELDS = {
    "reports": {"operation": "operation_type", "datasetId": "dataset_id"},
    "approvals": {
        "targetKind": "target_kind",
        "targetId": "target_id",
        "status": "status",
    },
    "schedules": {
        "workflowId": "workflow_id",
        "enabled": "enabled",
        "intervalSeconds": "interval_seconds",
        "nextRunAt": "next_run_at",
        "lastRunId": "last_run_id",
    },
    "views": {"datasetId": "dataset_id"},
    "apps": {"ownerId": "owner_id", "enabled": "enabled", "apiKeyHash": "api_key_hash"},
    "grants": {"appId": "app_id", "serviceId": "service_id", "status": "status"},
    "adapters": {"datasetId": "dataset_id"},
    "channels": {"enabled": "enabled"},
    "subscriptions": {
        "datasetId": "dataset_id",
        "channelId": "channel_id",
        "enabled": "enabled",
        "intervalSeconds": "interval_seconds",
        "nextRunAt": "next_run_at",
    },
    "events": {"subscriptionId": "subscription_id", "changeType": "change_type"},
    "deliveries": {
        "eventId": "event_id",
        "channelId": "channel_id",
        "status": "status",
    },
    "inbox": {"deliveryId": "delivery_id"},
}


def upgrade(store):
    store.db.executescript(
        (Path(__file__).resolve().parent.parent / "db/schema-v2.sql").read_text(
            encoding="utf8"
        )
    )
    with store.transaction():
        if "view_id" not in {
            r[1] for r in store.db.execute("PRAGMA table_info(data_services)")
        }:
            store.db.execute(
                "ALTER TABLE data_services ADD COLUMN view_id TEXT REFERENCES local_views(id) ON DELETE RESTRICT"
            )
        store.db.execute(
            "INSERT OR IGNORE INTO schema_migrations VALUES (2,?,?)",
            ("local governance modules", now()),
        )


class LocalStore:
    def __init__(self, store):
        self.store = store

    def unpack(self, kind, row):
        if row is None:
            return None
        value = json.loads(row["payload_json"])
        value.update(
            id=row["id"],
            name=row["name"],
            createdAt=row["created_at"],
            updatedAt=row["updated_at"],
        )
        for key, col in FIELDS[kind].items():
            value[key] = bool(row[col]) if key == "enabled" else row[col]
        return value

    def all(self, kind):
        table = TABLES[kind]
        with self.store.lock:
            return [
                self.unpack(kind, r)
                for r in self.store.db.execute(
                    f"SELECT * FROM {table} ORDER BY created_at DESC,id"
                )
            ]

    def get(self, kind, key):
        with self.store.lock:
            return self.unpack(
                kind,
                self.store.db.execute(
                    f"SELECT * FROM {TABLES[kind]} WHERE id=?", (key,)
                ).fetchone(),
            )

    def save(self, kind, value, key=None):
        with self.store.transaction():
            key = key or str(uuid.uuid4())
            old = self.get(kind, key) or {}
            value = {
                **old,
                **value,
                "id": key,
                "createdAt": old.get("createdAt") or now(),
                "updatedAt": now(),
            }
            cols = ["id", "name", "created_at", "updated_at", "payload_json"] + list(
                FIELDS[kind].values()
            )
            vals = [
                key,
                value["name"],
                value["createdAt"],
                value["updatedAt"],
                encoded(value),
            ]
            vals += [
                (
                    int(bool(value.get(k)))
                    if k == "enabled"
                    else value.get(k) or (None if k.endswith("Id") else value.get(k))
                )
                for k in FIELDS[kind]
            ]
            self.store._insert(TABLES[kind], cols, vals, ("id",))
            return self.get(kind, key)

    def remove(self, kind, key):
        with self.store.transaction():
            self.store.db.execute(f"DELETE FROM {TABLES[kind]} WHERE id=?", (key,))

    def snapshot(self, key):
        with self.store.lock:
            row = self.store.db.execute(
                "SELECT rows_json FROM subscription_snapshots WHERE subscription_id=?",
                (key,),
            ).fetchone()
            return json.loads(row[0]) if row else None

    def save_snapshot(self, key, rows):
        with self.store.transaction():
            self.store.db.execute(
                "INSERT INTO subscription_snapshots VALUES (?,?,?) ON CONFLICT(subscription_id) DO UPDATE SET rows_json=excluded.rows_json,captured_at=excluded.captured_at",
                (key, encoded(rows), now()),
            )


def public(record):
    return {k: v for k, v in record.items() if k not in ("apiKeyHash",)}
