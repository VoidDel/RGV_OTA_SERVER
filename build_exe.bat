@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    set "PY_CMD=py -3"
) else (
    set "PY_CMD=python"
)

if not exist .venv (
    %PY_CMD% -m venv .venv
    if errorlevel 1 goto :error
)

call .venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto :error
call .venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :error
call .venv\Scripts\pyinstaller.exe --clean --noconfirm ota_server.spec
if errorlevel 1 goto :error

echo.
echo 打包完成: %CD%\dist\RGV_OTA_Server.exe
if not defined CI pause
exit /b 0

:error
echo.
echo 打包失败，请检查上方错误信息。
if not defined CI pause
exit /b 1
