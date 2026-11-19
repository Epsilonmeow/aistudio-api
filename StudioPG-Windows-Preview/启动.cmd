@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
where uv >nul 2>nul
if errorlevel 1 goto need_uv
set "UV_PROJECT_ENVIRONMENT=%~dp0.venv"
set "UV_LINK_MODE=copy"
echo 正在检查 Python 和软件依赖，首次使用可能需要下载。
uv sync --no-config --default-index https://pypi.org/simple --frozen --no-dev --python 3.12
if errorlevel 1 goto failed
"%UV_PROJECT_ENVIRONMENT%\Scripts\python.exe" -E -s -B "%~dp0main.py"
if errorlevel 1 goto failed
exit /b 0
:need_uv
echo 请先按照 README.md 安装 uv，然后重开这个文件。
goto finish
:failed
echo 启动没有完成，请查看上方提示。
:finish
if /i not "%~1"=="--no-pause" pause
exit /b 1
