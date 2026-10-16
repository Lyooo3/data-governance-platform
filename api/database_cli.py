"""Local platform database management. Never connects to external business servers."""

import argparse
import json
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from . import config
from .storage import Store


def backup_raw_files(store, platform_backup):
    backup = Path(platform_backup).resolve()
    with sqlite3.connect(backup.as_uri() + "?mode=ro", uri=True) as db:
        if not db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='raw_snapshots'"
        ).fetchone():
            return {"rawSnapshots": 0}
        ids = [
            r[0]
            for r in db.execute("SELECT id FROM raw_snapshots WHERE status='SUCCESS'")
        ]
    if not ids:
        return {"rawSnapshots": 0}
    folder = backup.with_suffix(".raw")
    folder.mkdir(exist_ok=False)
    for key in ids:
        if str(uuid.UUID(key)) != key:
            raise ValueError("原始库标识异常，备份未完成")
        source = store.directory / "raw" / (key + ".sqlite3")
        if not source.is_file():
            raise ValueError("缺少已完成的原始库文件，备份未完成")
        target = folder / source.name
        shutil.copy2(source, target)
        if target.stat().st_size != source.stat().st_size:
            raise ValueError("原始库备份文件大小不一致")
    return {"rawSnapshots": len(ids), "rawDirectory": str(folder)}


def main():
    parser = argparse.ArgumentParser(description="治理平台本地SQLite管理")
    parser.add_argument("command", choices=("init", "status", "check", "backup"))
    parser.add_argument("--data-dir", type=Path, default=config.DATA_DIR)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    # Management of an existing file must not change execution state or auto-import.
    if args.command != "init" and not (args.data_dir / "platform.sqlite3").is_file():
        parser.error("本地数据库不存在，请先执行init")
    store = Store(args.data_dir, initialize=args.command == "init")
    try:
        if args.command in ("init", "status"):
            result = store.info()
        elif args.command == "check":
            result = store.check()
            if result["integrity"] != ["ok"] or result["foreignKeyViolations"]:
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 1
        else:
            path = args.output or args.data_dir / "backups" / (
                "platform-"
                + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
                + ".sqlite3"
            )
            result = {"backup": store.backup(path), "check": store.check()}
            result.update(backup_raw_files(store, result["backup"]))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
