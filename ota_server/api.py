import json
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from . import db
from .config import OTA_URL_MAX_BYTES
from .mqtt_client import mqtt_client
from .storage import extract_esp_app_version, finalize_firmware_file, firmware_path, save_upload_temp, size_warning

router = APIRouter()


def row_to_dict(row: Any) -> dict[str, Any]:
    data = db.dict_from_row(row)
    if data is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    return data


def get_public_base_url(request: Request, settings: dict[str, str]) -> str:
    value = settings.get("public_base_url", "").strip().rstrip("/")
    if value:
        return value
    return str(request.base_url).rstrip("/")


def firmware_download_url(request: Request, stored_filename: str, settings: dict[str, str] | None = None) -> str:
    if settings is None:
        with db.connect() as conn:
            settings = db.get_settings(conn)
    base = get_public_base_url(request, settings)
    return urljoin(base + "/", f"firmware-files/{stored_filename}")


def validate_ota_url(url: str) -> None:
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="固件URL必须以 http:// 或 https:// 开头")
    if len(url.encode("utf-8")) > OTA_URL_MAX_BYTES:
        raise HTTPException(status_code=400, detail=f"固件URL超过 {OTA_URL_MAX_BYTES} 字节")


TERMINAL_DEPLOYMENT_STATUSES = {"success", "failed", "rebooting", "skipped"}
ACTIVE_DEPLOYMENT_STATUSES = {"queued", "published", "received", "downloading", "verifying", "writing"}


def deployment_payload(url: str, version: str, force: bool, reboot: bool) -> dict[str, Any]:
    return {"url": url, "version": version, "force": force, "reboot": reboot}


@router.get("/api/health")
def health() -> dict[str, Any]:
    with db.connect() as conn:
        settings = db.get_settings(conn)
    return {
        "ok": True,
        "server_time": db.utc_now(),
        "mqtt_connected": mqtt_client.connected,
        "mqtt_error": mqtt_client.last_error,
        "mqtt_broker": f"{settings.get('mqtt_host')}:{settings.get('mqtt_port')}",
    }


@router.get("/api/settings")
def get_settings() -> dict[str, str]:
    with db.connect() as conn:
        return db.get_settings(conn)


@router.put("/api/settings")
async def update_settings(request: Request) -> dict[str, str]:
    values = await request.json()
    allowed = {"mqtt_host", "mqtt_port", "mqtt_username", "mqtt_password", "public_base_url", "default_force", "default_reboot"}
    clean = {key: values[key] for key in values if key in allowed}
    with db.connect() as conn:
        updated = db.set_settings(conn, clean)
    if {"mqtt_host", "mqtt_port", "mqtt_username", "mqtt_password"} & clean.keys():
        mqtt_client.configure(updated)
    return updated


@router.get("/api/firmware")
def list_firmware(request: Request, active: str = "true", q: str = "") -> list[dict[str, Any]]:
    where = []
    params: list[Any] = []
    if active != "all":
        where.append("is_active=?")
        params.append(1 if active.lower() != "false" else 0)
    if q:
        where.append("(version LIKE ? OR filename LIKE ? OR description LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    sql = "SELECT * FROM firmware_versions"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC"
    with db.connect() as conn:
        settings = db.get_settings(conn)
        rows = conn.execute(sql, params).fetchall()
    result = []
    for row in rows:
        item = row_to_dict(row)
        item["download_url"] = firmware_download_url(request, item["stored_filename"], settings)
        item["warning"] = size_warning(item["file_size"])
        result.append(item)
    return result


@router.post("/api/firmware")
async def upload_firmware(
    request: Request,
    file: UploadFile = File(...),
    version: str = Form(""),
    description: str = Form(""),
    release_notes: str = Form(""),
) -> dict[str, Any]:
    version = version.strip()
    try:
        temp_path, file_size, sha256 = await save_upload_temp(file)
        if not version:
            version = extract_esp_app_version(temp_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not version:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="无法从固件中识别版本号，请手动填写")

    now = db.utc_now()
    with db.connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO firmware_versions(version, filename, stored_filename, file_size, sha256, description, release_notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (version, file.filename or "firmware.bin", "pending.bin", file_size, sha256, description, release_notes, now, now),
        )
        firmware_id = cursor.lastrowid
        stored_filename = finalize_firmware_file(temp_path, firmware_id, version, sha256)
        conn.execute("UPDATE firmware_versions SET stored_filename=?, updated_at=? WHERE id=?", (stored_filename, now, firmware_id))
        row = conn.execute("SELECT * FROM firmware_versions WHERE id=?", (firmware_id,)).fetchone()
        settings = db.get_settings(conn)

    item = row_to_dict(row)
    item["download_url"] = firmware_download_url(request, item["stored_filename"], settings)
    item["warning"] = size_warning(item["file_size"])
    return item


@router.get("/api/firmware/{firmware_id}")
def get_firmware(request: Request, firmware_id: int) -> dict[str, Any]:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM firmware_versions WHERE id=?", (firmware_id,)).fetchone()
        settings = db.get_settings(conn)
    item = row_to_dict(row)
    item["download_url"] = firmware_download_url(request, item["stored_filename"], settings)
    item["warning"] = size_warning(item["file_size"])
    return item


@router.put("/api/firmware/{firmware_id}")
async def update_firmware(firmware_id: int, request: Request) -> dict[str, Any]:
    values = await request.json()
    now = db.utc_now()
    with db.connect() as conn:
        conn.execute(
            """
            UPDATE firmware_versions SET version=COALESCE(?, version), description=COALESCE(?, description),
                release_notes=COALESCE(?, release_notes), is_active=COALESCE(?, is_active), updated_at=?
            WHERE id=?
            """,
            (values.get("version"), values.get("description"), values.get("release_notes"), values.get("is_active"), now, firmware_id),
        )
        row = conn.execute("SELECT * FROM firmware_versions WHERE id=?", (firmware_id,)).fetchone()
    return row_to_dict(row)


@router.delete("/api/firmware/{firmware_id}")
def archive_firmware(firmware_id: int) -> dict[str, Any]:
    with db.connect() as conn:
        conn.execute("UPDATE firmware_versions SET is_active=0, updated_at=? WHERE id=?", (db.utc_now(), firmware_id))
    return {"ok": True}


@router.get("/firmware-files/{stored_filename}")
def download_firmware(stored_filename: str) -> FileResponse:
    path = firmware_path(stored_filename)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="固件文件不存在")
    return FileResponse(path, media_type="application/octet-stream", filename=Path(stored_filename).name)


@router.get("/api/devices")
def list_devices() -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM devices ORDER BY updated_at DESC, id DESC").fetchall()
    return [row_to_dict(row) for row in rows]


@router.post("/api/devices")
async def create_device(request: Request) -> dict[str, Any]:
    values = await request.json()
    rgv_id = str(values.get("rgv_id", "")).strip()
    if not rgv_id:
        raise HTTPException(status_code=400, detail="RGV ID不能为空")
    name = str(values.get("name", "")).strip()
    now = db.utc_now()
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO devices(rgv_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)
            ON CONFLICT(rgv_id) DO UPDATE SET name=excluded.name, updated_at=excluded.updated_at
            """,
            (rgv_id, name, now, now),
        )
        row = conn.execute("SELECT * FROM devices WHERE rgv_id=?", (rgv_id,)).fetchone()
    return row_to_dict(row)


@router.put("/api/devices/{rgv_id}")
async def update_device(rgv_id: str, request: Request) -> dict[str, Any]:
    values = await request.json()
    with db.connect() as conn:
        conn.execute("UPDATE devices SET name=?, updated_at=? WHERE rgv_id=?", (values.get("name", ""), db.utc_now(), rgv_id))
        row = conn.execute("SELECT * FROM devices WHERE rgv_id=?", (rgv_id,)).fetchone()
    return row_to_dict(row)


@router.delete("/api/devices/{rgv_id}")
def delete_device(rgv_id: str) -> dict[str, Any]:
    with db.connect() as conn:
        conn.execute("DELETE FROM devices WHERE rgv_id=?", (rgv_id,))
    return {"ok": True}


@router.post("/api/deployments")
async def create_deployments(request: Request) -> dict[str, Any]:
    values = await request.json()
    firmware_id = int(values.get("firmware_id", 0) or 0)
    rgv_ids = values.get("rgv_ids") or []
    if isinstance(rgv_ids, str):
        rgv_ids = [rgv.strip() for rgv in rgv_ids.split(",") if rgv.strip()]
    force = bool(values.get("force", False))
    reboot = bool(values.get("reboot", True))
    if not firmware_id:
        raise HTTPException(status_code=400, detail="请选择固件")

    deployments = []
    with db.connect() as conn:
        if values.get("target") == "all":
            rgv_ids = [row["rgv_id"] for row in conn.execute("SELECT rgv_id FROM devices ORDER BY rgv_id").fetchall()]
        rgv_ids = list(dict.fromkeys(str(rgv_id).strip() for rgv_id in rgv_ids if str(rgv_id).strip()))
        if not rgv_ids:
            raise HTTPException(status_code=400, detail="请选择至少一个RGV")

        settings = db.get_settings(conn)
        fw = conn.execute("SELECT * FROM firmware_versions WHERE id=? AND is_active=1", (firmware_id,)).fetchone()
        if fw is None:
            raise HTTPException(status_code=404, detail="固件不存在或已归档")
        fw_item = row_to_dict(fw)
        url = firmware_download_url(request, fw_item["stored_filename"], settings)
        validate_ota_url(url)
        if not firmware_path(fw_item["stored_filename"]).exists():
            raise HTTPException(status_code=404, detail="固件文件不存在")

        for rgv_id in rgv_ids:
            now = db.utc_now()
            payload = deployment_payload(url, fw_item["version"], force, reboot)
            payload_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            cursor = conn.execute(
                """
                INSERT INTO deployments(rgv_id, firmware_id, url, version, force, reboot, mqtt_topic, command_payload, status, started_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, '', ?, 'queued', ?, ?)
                """,
                (rgv_id, firmware_id, url, fw_item["version"], int(force), int(reboot), payload_text, now, now),
            )
            deployment_id = cursor.lastrowid
            conn.execute(
                """
                INSERT INTO devices(rgv_id, created_at, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(rgv_id) DO UPDATE SET updated_at=excluded.updated_at
                """,
                (rgv_id, now, now),
            )

            result = {"id": deployment_id, "rgv_id": rgv_id, "payload": payload, "status": "queued"}
            try:
                topic, published_payload = mqtt_client.publish_ota(rgv_id, payload)
                published_at = db.utc_now()
                conn.execute(
                    """
                    UPDATE deployments
                    SET status='published', mqtt_topic=?, command_payload=?, published_at=?, updated_at=?, delivery_attempts=delivery_attempts+1
                    WHERE id=?
                    """,
                    (topic, published_payload, published_at, published_at, deployment_id),
                )
                result.update({"topic": topic, "status": "published"})
            except RuntimeError as exc:
                conn.execute("UPDATE deployments SET message=?, updated_at=? WHERE id=?", (str(exc), db.utc_now(), deployment_id))
                result.update({"message": str(exc)})
            deployments.append(result)
    return {"ok": True, "deployments": deployments}


@router.get("/api/ota/check")
def check_ota(request: Request, rgv_id: str, version: str = "") -> dict[str, Any]:
    rgv_id = rgv_id.strip()
    version = version.strip()
    if not rgv_id:
        raise HTTPException(status_code=400, detail="RGV ID不能为空")

    now = db.utc_now()
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO devices(rgv_id, current_version, last_seen_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(rgv_id) DO UPDATE SET
                current_version=CASE WHEN excluded.current_version != '' THEN excluded.current_version ELSE devices.current_version END,
                last_seen_at=excluded.last_seen_at,
                updated_at=excluded.updated_at
            """,
            (rgv_id, version, now, now, now),
        )

        # A boot-time check with the target version confirms the OTA reboot completed.
        rebooted_deployment = conn.execute(
            """
            SELECT id FROM deployments
            WHERE rgv_id=? AND lower(status)='rebooting' AND version=?
            ORDER BY id DESC LIMIT 1
            """,
            (rgv_id, version),
        ).fetchone()
        if rebooted_deployment is not None:
            message = "已确认重启并运行目标版本"
            conn.execute(
                """
                UPDATE devices
                SET last_status='success', last_progress=100, last_code=0,
                    last_message=?, last_seen_at=?, updated_at=?
                WHERE rgv_id=?
                """,
                (message, now, now, rgv_id),
            )
            conn.execute(
                """
                UPDATE deployments
                SET status='success', progress=100, code=0, message=?,
                    completed_at=?, last_checked_at=?, updated_at=?
                WHERE id=?
                """,
                (message, now, now, now, rebooted_deployment["id"]),
            )
            db.add_event(
                conn,
                {
                    "type": "ota",
                    "rgv_id": rgv_id,
                    "status": "success",
                    "progress": 100,
                    "code": 0,
                    "message": message,
                    "topic": "/api/ota/check",
                    "created_at": now,
                },
            )

        deployment = conn.execute(
            """
            SELECT d.*, f.stored_filename, f.is_active
            FROM deployments d JOIN firmware_versions f ON f.id=d.firmware_id
            WHERE d.rgv_id=? AND lower(d.status) IN ({})
            ORDER BY d.id DESC LIMIT 1
            """.format(",".join("?" for _ in ACTIVE_DEPLOYMENT_STATUSES)),
            (rgv_id, *ACTIVE_DEPLOYMENT_STATUSES),
        ).fetchone()
        if deployment is None:
            return {"update": False}

        item = row_to_dict(deployment)
        conn.execute("UPDATE deployments SET last_checked_at=?, updated_at=? WHERE id=?", (now, now, item["id"]))
        if version and item["version"] == version and not bool(item["force"]):
            conn.execute(
                "UPDATE deployments SET status='skipped', message='设备已是目标版本', completed_at=?, updated_at=? WHERE id=?",
                (now, now, item["id"]),
            )
            return {"update": False, "deployment_id": item["id"], "status": "skipped"}

        settings = db.get_settings(conn)
        url = firmware_download_url(request, item["stored_filename"], settings)
        validate_ota_url(url)
        return {
            "update": True,
            "deployment_id": item["id"],
            "version": item["version"],
            "url": url,
            "force": bool(item["force"]),
            "reboot": bool(item["reboot"]),
        }


@router.get("/api/deployments")
def list_deployments(rgv_id: str = "", status: str = "", limit: int = 100) -> list[dict[str, Any]]:
    where = []
    params: list[Any] = []
    if rgv_id:
        where.append("d.rgv_id=?")
        params.append(rgv_id)
    if status:
        where.append("d.status=?")
        params.append(status)
    sql = """
        SELECT d.*, f.version AS firmware_version, f.filename AS firmware_filename
        FROM deployments d JOIN firmware_versions f ON f.id=d.firmware_id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY d.id DESC LIMIT ?"
    params.append(limit)
    with db.connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [row_to_dict(row) for row in rows]


@router.get("/api/deployments/{deployment_id}")
def get_deployment(deployment_id: int) -> dict[str, Any]:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM deployments WHERE id=?", (deployment_id,)).fetchone()
    return row_to_dict(row)


@router.post("/api/deployments/{deployment_id}/retry")
def retry_deployment(deployment_id: int) -> dict[str, Any]:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM deployments WHERE id=?", (deployment_id,)).fetchone()
        item = row_to_dict(row)
        payload = json.loads(item["command_payload"])
        validate_ota_url(payload["url"])
        topic, payload_text = mqtt_client.publish_ota(item["rgv_id"], payload)
        now = db.utc_now()
        conn.execute(
            "UPDATE deployments SET status='published', progress=0, mqtt_topic=?, command_payload=?, updated_at=?, completed_at=NULL WHERE id=?",
            (topic, payload_text, now, deployment_id),
        )
    return {"ok": True, "topic": topic, "payload": payload}


@router.get("/api/events/recent")
def recent_events(limit: int = 50) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [row_to_dict(row) for row in rows]
