import os
import sys
from dataclasses import dataclass
from pathlib import Path


BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else BUNDLE_DIR
ASSET_DIR = BUNDLE_DIR / "ota_server"
DATA_DIR = BASE_DIR / "data"
FIRMWARE_DIR = BASE_DIR / "firmware"
DB_PATH = DATA_DIR / "ota_server.db"
OTA_URL_MAX_BYTES = 256
OTA_SLOT_SOFT_LIMIT = 0x300000


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int
    mqtt_host: str
    mqtt_port: int
    mqtt_username: str
    mqtt_password: str
    public_base_url: str


def get_config() -> ServerConfig:
    port = int(os.getenv("OTA_SERVER_PORT", "8080"))
    host = os.getenv("OTA_SERVER_HOST", "0.0.0.0")
    mqtt_host = os.getenv("OTA_MQTT_HOST", "192.168.1.125")
    mqtt_port = int(os.getenv("OTA_MQTT_PORT", "1883"))
    public_base_url = os.getenv("OTA_PUBLIC_BASE_URL", f"http://{mqtt_host}:{port}")
    return ServerConfig(
        host=host,
        port=port,
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port,
        mqtt_username=os.getenv("OTA_MQTT_USERNAME", ""),
        mqtt_password=os.getenv("OTA_MQTT_PASSWORD", ""),
        public_base_url=public_base_url.rstrip("/"),
    )


def ensure_runtime_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIRMWARE_DIR.mkdir(parents=True, exist_ok=True)
