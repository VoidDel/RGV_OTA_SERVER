import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import DB_PATH, ensure_runtime_dirs


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def dict_from_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    ensure_runtime_dirs()
    conn = sqlite3.connect(Path(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS firmware_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT NOT NULL,
                filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL UNIQUE,
                file_size INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                image_digest TEXT DEFAULT '',
                description TEXT DEFAULT '',
                release_notes TEXT DEFAULT '',
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_firmware_version ON firmware_versions(version);
            CREATE INDEX IF NOT EXISTS idx_firmware_sha256 ON firmware_versions(sha256);

            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rgv_id TEXT NOT NULL UNIQUE,
                name TEXT DEFAULT '',
                current_version TEXT DEFAULT '',
                last_status TEXT DEFAULT '',
                last_progress INTEGER DEFAULT 0,
                last_code INTEGER DEFAULT 0,
                last_message TEXT DEFAULT '',
                last_seen_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS deployments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rgv_id TEXT NOT NULL,
                firmware_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                version TEXT DEFAULT '',
                force INTEGER DEFAULT 0,
                reboot INTEGER DEFAULT 1,
                mqtt_topic TEXT DEFAULT '',
                command_payload TEXT DEFAULT '',
                status TEXT DEFAULT 'queued',
                progress INTEGER DEFAULT 0,
                code INTEGER DEFAULT 0,
                message TEXT DEFAULT '',
                started_at TEXT NOT NULL,
                published_at TEXT,
                last_checked_at TEXT,
                delivery_attempts INTEGER DEFAULT 0,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY (firmware_id) REFERENCES firmware_versions(id)
            );
            CREATE INDEX IF NOT EXISTS idx_deployments_rgv ON deployments(rgv_id);
            CREATE INDEX IF NOT EXISTS idx_deployments_status ON deployments(status);
            CREATE INDEX IF NOT EXISTS idx_deployments_queue ON deployments(rgv_id, status, id);

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                rgv_id TEXT DEFAULT '',
                status TEXT DEFAULT '',
                progress INTEGER DEFAULT 0,
                code INTEGER DEFAULT 0,
                message TEXT DEFAULT '',
                topic TEXT DEFAULT '',
                payload TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
            """
        )
        migrate_db(conn)
        seed_default_settings(conn)


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def migrate_db(conn: sqlite3.Connection) -> None:
    migrations = {
        "published_at": "ALTER TABLE deployments ADD COLUMN published_at TEXT",
        "last_checked_at": "ALTER TABLE deployments ADD COLUMN last_checked_at TEXT",
        "delivery_attempts": "ALTER TABLE deployments ADD COLUMN delivery_attempts INTEGER DEFAULT 0",
    }
    for column, sql in migrations.items():
        if not column_exists(conn, "deployments", column):
            conn.execute(sql)
    # 设备侧校验口径的镜像摘要（hash_appended 时为 file[:-32] 的哈希）
    if not column_exists(conn, "firmware_versions", "image_digest"):
        conn.execute("ALTER TABLE firmware_versions ADD COLUMN image_digest TEXT DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_deployments_queue ON deployments(rgv_id, status, id)")


def seed_default_settings(conn: sqlite3.Connection) -> None:
    from .config import get_config

    cfg = get_config()
    defaults = {
        "mqtt_host": cfg.mqtt_host,
        "mqtt_port": str(cfg.mqtt_port),
        "mqtt_username": cfg.mqtt_username,
        "mqtt_password": cfg.mqtt_password,
        "public_base_url": cfg.public_base_url,
        "default_force": "0",
        "default_reboot": "1",
    }
    now = utc_now()
    for key, value in defaults.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings(key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, now),
        )


def get_settings(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {row["key"]: row["value"] for row in rows}


def set_settings(conn: sqlite3.Connection, values: dict[str, Any]) -> dict[str, str]:
    now = utc_now()
    for key, value in values.items():
        conn.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, str(value), now),
        )
    return get_settings(conn)


def add_event(conn: sqlite3.Connection, event: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO events(type, rgv_id, status, progress, code, message, topic, payload, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.get("type", "ota"),
            event.get("rgv_id", ""),
            event.get("status", ""),
            int(event.get("progress", 0) or 0),
            int(event.get("code", 0) or 0),
            event.get("message", ""),
            event.get("topic", ""),
            event.get("payload", ""),
            event.get("created_at", utc_now()),
        ),
    )
