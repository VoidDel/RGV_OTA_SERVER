import hashlib
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import UploadFile

from .config import FIRMWARE_DIR, OTA_SLOT_SOFT_LIMIT, ensure_runtime_dirs


_VERSION_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_version(version: str) -> str:
    cleaned = _VERSION_SAFE_RE.sub("_", version.strip())
    return cleaned[:32] or "unknown"


def validate_firmware_filename(filename: str) -> None:
    if not filename.lower().endswith(".bin"):
        raise ValueError("只允许上传 .bin 固件文件")


def _decode_c_string(data: bytes) -> str:
    return data.split(b"\0", 1)[0].decode("utf-8", errors="ignore").strip()


def extract_esp_app_version(path: Path) -> str:
    data = path.read_bytes()
    magic = (0xABCD5432).to_bytes(4, "little")
    offset = 0
    while True:
        index = data.find(magic, offset)
        if index < 0:
            return ""
        offset = index + 1
        if index + 128 > len(data):
            continue
        version = _decode_c_string(data[index + 16:index + 48])
        project_name = _decode_c_string(data[index + 48:index + 80])
        idf_version = _decode_c_string(data[index + 112:index + 144])
        if version and project_name and idf_version:
            return version


async def save_upload_temp(upload: UploadFile) -> tuple[Path, int, str]:
    validate_firmware_filename(upload.filename or "")
    ensure_runtime_dirs()
    sha = hashlib.sha256()
    size = 0
    with NamedTemporaryFile(delete=False, dir=FIRMWARE_DIR, suffix=".upload") as tmp:
        temp_path = Path(tmp.name)
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            sha.update(chunk)
            tmp.write(chunk)
    if size == 0:
        temp_path.unlink(missing_ok=True)
        raise ValueError("固件文件为空")
    return temp_path, size, sha.hexdigest()


def finalize_firmware_file(temp_path: Path, firmware_id: int, version: str, sha256: str) -> str:
    stored_filename = f"fw_{firmware_id}_{safe_version(version)}_{sha256[:8]}.bin"
    target = FIRMWARE_DIR / stored_filename
    if target.exists():
        target.unlink()
    temp_path.replace(target)
    return stored_filename


def firmware_path(stored_filename: str) -> Path:
    name = Path(stored_filename).name
    return FIRMWARE_DIR / name


def size_warning(file_size: int) -> str:
    if file_size > OTA_SLOT_SOFT_LIMIT:
        return f"固件大小超过 OTA 分区软限制 {OTA_SLOT_SOFT_LIMIT} 字节"
    return ""
