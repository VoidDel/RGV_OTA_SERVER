# RGV OTA Server

本工具用于管理 RGV 固件版本，并通过 MQTT 向 RGV 推送 OTA 更新。

## 功能

- 上传和管理 `.bin` 固件版本
- 生成 RGV 可下载的 HTTP 固件 URL
- 管理 RGV 设备 ID
- 通过 MQTT 发布 OTA 指令
- 订阅 OTA 状态并显示进度
- 提供浏览器前端管理界面

## 安装

```bash
cd Tools/OTA_SERVER
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
```

## 运行

```bash
.venv/Scripts/python run.py
```

## 打包 Windows exe

在 Windows 上运行：

```bat
build_exe.bat
```

产物位于：

```text
dist\RGV_OTA_Server.exe
```

exe 运行时会在同目录自动创建 `data` 和 `firmware` 目录，用于保存数据库和固件文件。

打开浏览器：

```text
http://localhost:8080
```

默认监听地址为 `0.0.0.0:8080`，RGV 需要通过局域网 IP 下载固件。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `OTA_SERVER_HOST` | `0.0.0.0` | HTTP监听地址 |
| `OTA_SERVER_PORT` | `8080` | HTTP端口 |
| `OTA_MQTT_HOST` | `192.168.1.125` | MQTT Broker地址 |
| `OTA_MQTT_PORT` | `1883` | MQTT Broker端口 |
| `OTA_MQTT_USERNAME` | 空 | MQTT用户名 |
| `OTA_MQTT_PASSWORD` | 空 | MQTT密码 |
| `OTA_PUBLIC_BASE_URL` | `http://{OTA_MQTT_HOST}:8080` | 下发给RGV的固件下载基址 |

`OTA_PUBLIC_BASE_URL` 必须是 RGV 能访问的地址，例如：

```text
http://192.168.1.125:8080
```

不要使用 `localhost` 或 `127.0.0.1` 作为 OTA 下载地址。

## OTA 协议

服务器向设备发布：

```text
rgv/rcs/{RGVID}/issue/otaUpdate
```

Payload：

```json
{
  "url": "http://192.168.1.125:8080/firmware-files/fw_1_1.0.1_abcd1234.bin",
  "version": "1.0.1",
  "force": false,
  "reboot": true
}
```

设备状态上报：

```text
rgv/rcs/{RGVID}/report/otaStatus
```

Payload：

```json
{
  "type": "ota",
  "status": "downloading",
  "version": "1.0.1",
  "progress": 42,
  "code": 0,
  "message": ""
}
```

## 使用流程

1. 在“设置”页面确认 MQTT 和 Public Base URL。
2. 在“固件版本”页面上传 `.pio/build/GOTION_RGV/firmware.bin`。
3. 在“RGV设备”页面添加设备 ID，例如 `RGV-654745`。
4. 在“总览”或“推送历史”中选择固件和设备，点击推送。
5. 查看 OTA 状态和进度。

## 运行数据

运行时会生成：

- `data/ota_server.db`
- `firmware/*.bin`

这些文件是本地运行数据，不建议提交到 Git。
