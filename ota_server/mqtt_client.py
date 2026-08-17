import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import paho.mqtt.client as mqtt

from . import db


@dataclass
class MqttSettings:
    host: str
    port: int
    username: str = ""
    password: str = ""


class OtaMqttClient:
    def __init__(self) -> None:
        self._client: mqtt.Client | None = None
        self._settings: MqttSettings | None = None
        self._connected = False
        self._lock = threading.Lock()
        self._last_error = ""

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def last_error(self) -> str:
        return self._last_error

    def configure(self, settings: dict[str, str]) -> None:
        mqtt_settings = MqttSettings(
            host=settings.get("mqtt_host", "192.168.1.125"),
            port=int(settings.get("mqtt_port", "1883") or 1883),
            username=settings.get("mqtt_username", ""),
            password=settings.get("mqtt_password", ""),
        )
        with self._lock:
            self._settings = mqtt_settings
        self.reconnect()

    def reconnect(self) -> None:
        with self._lock:
            if self._client is not None:
                try:
                    self._client.loop_stop()
                    self._client.disconnect()
                except Exception:
                    pass
                self._client = None
                self._connected = False

            if self._settings is None:
                return

            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="rgv_ota_server")
            if self._settings.username:
                client.username_pw_set(self._settings.username, self._settings.password)
            client.on_connect = self._on_connect
            client.on_disconnect = self._on_disconnect
            client.on_message = self._on_message
            self._client = client

            try:
                client.connect_async(self._settings.host, self._settings.port, keepalive=30)
                client.loop_start()
                self._last_error = ""
            except Exception as exc:
                self._last_error = str(exc)
                self._connected = False

    def stop(self) -> None:
        with self._lock:
            if self._client is None:
                return
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None
            self._connected = False

    def publish_ota(self, rgv_id: str, payload: dict[str, Any]) -> tuple[str, str]:
        if not self._client or not self._connected:
            raise RuntimeError("MQTT未连接")
        topic = f"rgv/rcs/{rgv_id}/issue/otaUpdate"
        payload_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        info = self._client.publish(topic, payload_text, qos=1, retain=False)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT发布失败: {info.rc}")
        return topic, payload_text

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any = None) -> None:
        rc = getattr(reason_code, "value", reason_code)
        self._connected = int(rc) == 0
        if self._connected:
            self._last_error = ""
            client.subscribe("rgv/rcs/+/report/otaStatus", qos=1)
            client.subscribe("rgv/rcs/+/report/status", qos=1)
            self._record_event({"type": "mqtt", "status": "connected", "message": "MQTT已连接"})
        else:
            self._last_error = f"connect rc={reason_code}"
            self._record_event({"type": "mqtt", "status": "failed", "message": self._last_error})

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, disconnect_flags: Any, reason_code: Any, properties: Any = None) -> None:
        self._connected = False
        self._last_error = f"disconnect rc={reason_code}"
        self._record_event({"type": "mqtt", "status": "disconnected", "message": self._last_error})

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        topic = msg.topic
        parts = topic.split("/")
        rgv_id = parts[2] if len(parts) >= 5 else ""
        payload_text = msg.payload.decode("utf-8", errors="replace")
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            payload = {"status": "invalid_json", "message": payload_text}

        if topic.endswith("/report/status"):
            self._record_device_seen(rgv_id, payload_text)
            self._publish_queued_deployment(rgv_id)
            return

        status = str(payload.get("status", "unknown"))
        version = str(payload.get("version", ""))
        progress = int(payload.get("progress", 0) or 0)
        code = int(payload.get("code", 0) or 0)
        message = str(payload.get("message", ""))
        now = db.utc_now()

        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO devices(rgv_id, current_version, last_status, last_progress, last_code, last_message, last_seen_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(rgv_id) DO UPDATE SET
                    current_version=CASE WHEN excluded.current_version != '' THEN excluded.current_version ELSE devices.current_version END,
                    last_status=excluded.last_status,
                    last_progress=excluded.last_progress,
                    last_code=excluded.last_code,
                    last_message=excluded.last_message,
                    last_seen_at=excluded.last_seen_at,
                    updated_at=excluded.updated_at
                """,
                (rgv_id, version, status, progress, code, message, now, now, now),
            )
            # 只归因到"进行中"的 deployment：终态(success/failed/rebooting/skipped)
            # 不被迟到/重复的 otaStatus 覆盖；无进行中记录时仅更新设备与事件。
            deployment = conn.execute(
                """
                SELECT id FROM deployments
                WHERE rgv_id=? AND lower(status) NOT IN ('success','failed','rebooting','skipped')
                ORDER BY id DESC LIMIT 1
                """,
                (rgv_id,),
            ).fetchone()
            if deployment:
                completed_at = now if status.lower() in {"success", "failed", "rebooting"} else None
                conn.execute(
                    """
                    UPDATE deployments SET status=?, progress=?, code=?, message=?, updated_at=?, completed_at=COALESCE(?, completed_at)
                    WHERE id=?
                    """,
                    (status, progress, code, message, now, completed_at, deployment["id"]),
                )
            db.add_event(
                conn,
                {
                    "type": "ota",
                    "rgv_id": rgv_id,
                    "status": status,
                    "progress": progress,
                    "code": code,
                    "message": message,
                    "topic": topic,
                    "payload": payload_text,
                    "created_at": now,
                },
            )
        self._publish_queued_deployment(rgv_id)

    # 设备重新上线判定阈值：超过该时长未见到状态上报才记录 online 事件，
    # 避免 1Hz 心跳每秒写一行 events 导致数据库无界膨胀。
    ONLINE_EVENT_GAP_SECONDS = 120

    def _record_device_seen(self, rgv_id: str, payload_text: str) -> None:
        now = db.utc_now()
        with db.connect() as conn:
            existing = conn.execute(
                "SELECT last_seen_at FROM devices WHERE rgv_id=?", (rgv_id,)
            ).fetchone()
            conn.execute(
                """
                INSERT INTO devices(rgv_id, last_seen_at, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(rgv_id) DO UPDATE SET last_seen_at=excluded.last_seen_at, updated_at=excluded.updated_at
                """,
                (rgv_id, now, now, now),
            )
            # ISO8601 UTC 字符串可直接按字典序比较
            came_online = (
                existing is None
                or existing["last_seen_at"] is None
                or (datetime.now(timezone.utc) - datetime.fromisoformat(existing["last_seen_at"])).total_seconds()
                    > self.ONLINE_EVENT_GAP_SECONDS
            )
            if came_online:
                db.add_event(
                    conn,
                    {
                        "type": "status",
                        "rgv_id": rgv_id,
                        "status": "online",
                        "message": "设备上线",
                        "topic": f"rgv/rcs/{rgv_id}/report/status",
                        "created_at": now,
                    },
                )

    def _publish_queued_deployment(self, rgv_id: str) -> None:
        if not rgv_id or not self._client or not self._connected:
            return
        with db.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM deployments
                WHERE rgv_id=? AND lower(status)='queued'
                ORDER BY id DESC LIMIT 1
                """,
                (rgv_id,),
            ).fetchone()
            if row is None:
                return
            # 优先使用创建时存储的完整 payload（含 sha256 等字段）；
            # 旧记录无 command_payload 时退化为按列重建。
            try:
                payload = json.loads(row["command_payload"]) if row["command_payload"] else None
            except json.JSONDecodeError:
                payload = None
            if not isinstance(payload, dict) or not payload.get("url"):
                payload = {"url": row["url"], "version": row["version"], "force": bool(row["force"]), "reboot": bool(row["reboot"])}
            try:
                topic, payload_text = self.publish_ota(rgv_id, payload)
                now = db.utc_now()
                conn.execute(
                    """
                    UPDATE deployments
                    SET status='published', mqtt_topic=?, command_payload=?, published_at=?, updated_at=?, delivery_attempts=delivery_attempts+1, message=''
                    WHERE id=?
                    """,
                    (topic, payload_text, now, now, row["id"]),
                )
                db.add_event(conn, {"type": "ota", "rgv_id": rgv_id, "status": "published", "message": "queued OTA 已补发", "topic": topic, "payload": payload_text, "created_at": now})
            except RuntimeError as exc:
                conn.execute("UPDATE deployments SET message=?, updated_at=? WHERE id=?", (str(exc), db.utc_now(), row["id"]))

    def _record_event(self, event: dict[str, Any]) -> None:
        with db.connect() as conn:
            db.add_event(conn, event)


mqtt_client = OtaMqttClient()
