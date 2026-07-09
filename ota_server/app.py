import socket

import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db
from .api import router
from .config import ASSET_DIR, get_config, ensure_runtime_dirs
from .mqtt_client import mqtt_client


templates = Jinja2Templates(directory=str(ASSET_DIR / "templates"))


def create_app() -> FastAPI:
    app = FastAPI(title="RGV OTA Server", version="1.0.0")
    app.mount("/static", StaticFiles(directory=str(ASSET_DIR / "static")), name="static")
    app.include_router(router)

    @app.on_event("startup")
    def on_startup() -> None:
        ensure_runtime_dirs()
        db.init_db()
        with db.connect() as conn:
            settings = db.get_settings(conn)
        mqtt_client.configure(settings)

    @app.on_event("shutdown")
    def on_shutdown() -> None:
        mqtt_client.stop()

    @app.get("/")
    def dashboard(request: Request):
        return templates.TemplateResponse("dashboard.html", {"request": request, "page": "dashboard"})

    @app.get("/firmware")
    def firmware(request: Request):
        return templates.TemplateResponse("firmware.html", {"request": request, "page": "firmware"})

    @app.get("/devices")
    def devices(request: Request):
        return templates.TemplateResponse("devices.html", {"request": request, "page": "devices"})

    @app.get("/deployments")
    def deployments(request: Request):
        return templates.TemplateResponse("deployments.html", {"request": request, "page": "deployments"})

    @app.get("/settings")
    def settings(request: Request):
        return templates.TemplateResponse("settings.html", {"request": request, "page": "settings"})

    return app


app = create_app()


def find_available_port(host: str, start_port: int) -> int:
    bind_host = "127.0.0.1" if host == "0.0.0.0" else host
    for port in range(start_port, start_port + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((bind_host, port))
            except OSError:
                continue
            return port
    return start_port


def run() -> None:
    cfg = get_config()
    port = find_available_port(cfg.host, cfg.port)
    if port != cfg.port:
        print(f"端口 {cfg.port} 已被占用，自动切换到 {port}")
        print(f"请在设置页把 Public Base URL 改为 http://<本机局域网IP>:{port}")
    print(f"RGV OTA Server: http://localhost:{port}")
    uvicorn.run("ota_server.app:app", host=cfg.host, port=port, reload=False)
