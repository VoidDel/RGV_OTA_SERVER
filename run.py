try:
    from ota_server.app import run
except ModuleNotFoundError as exc:
    missing = exc.name or "依赖包"
    raise SystemExit(
        f"缺少依赖: {missing}\n"
        "请先安装 OTA_SERVER 依赖:\n"
        "  .venv/Scripts/python -m pip install -r Tools/OTA_SERVER/requirements.txt\n"
        "然后重新运行:\n"
        "  .venv/Scripts/python Tools/OTA_SERVER/run.py"
    ) from exc


if __name__ == "__main__":
    run()
