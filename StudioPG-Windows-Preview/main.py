"""Local Windows entry point. Starting the listener does not open Google."""

from __future__ import annotations

import asyncio
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
from contextlib import suppress
from pathlib import Path

import uvicorn
from browser_backend import BrowserBackend
from fastapi.responses import PlainTextResponse
from protocol_api import BackendError, create_app
from starlette.middleware.trustedhost import TrustedHostMiddleware


def state_directory() -> Path:
    value = os.environ.get("LOCALAPPDATA", "")
    if not value or not Path(value).is_absolute():
        raise RuntimeError("找不到当前 Windows 用户的本地资料目录。")
    return Path(value) / "StudioPG-SinglePreview"


def local_key(root: Path) -> str:
    root.mkdir(parents=True, exist_ok=True)
    target = root / "local-key.txt"
    if target.exists():
        key = target.read_text(encoding="ascii").strip()
        if not re.fullmatch(r"[\w-]{43}", key, re.ASCII):
            raise RuntimeError(
                "本地密钥文件格式不正确。请关闭服务，将 local-key.txt 改名后再启动。"
            )
        return key
    key = secrets.token_urlsafe(32)
    with tempfile.NamedTemporaryFile(dir=root, delete=False) as temporary:
        temporary.write(key.encode("ascii"))
        name = Path(temporary.name)
    try:
        name.replace(target)
    finally:
        name.unlink(missing_ok=True)
    return key


def listen(port: int = 8080) -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", port))
        listener.listen()
        listener.setblocking(False)
        return listener
    except OSError:
        listener.close()
        raise


def build_app(backend: BrowserBackend, key: str):
    app = create_app(backend, key)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])

    async def home(_request):
        return PlainTextResponse(
            "本机 PG 服务已启动。回到启动窗口，按 L 打开专用登录窗口，"
            "按 K 复制酒馆连接密钥。登录状态以专用浏览器里的网页为准。"
        )

    app.add_route("/", home, methods=["GET"])

    return app


async def console(backend: BrowserBackend, key: str):
    import msvcrt

    async def login():
        try:
            await backend.open_login()
            print("请在专用浏览器里确认登录，并留意网页上选用的模型。", flush=True)
        except BackendError as exc:
            print(str(exc), flush=True)
        except Exception:
            print(
                "浏览器没有成功打开。请检查本机 Edge 或 Chrome，然后再按 L。",
                flush=True,
            )

    task = None
    try:
        while True:
            await asyncio.sleep(0.15)
            if not msvcrt.kbhit():
                continue
            command = msvcrt.getwch().lower()
            if command == "l" and (task is None or task.done()):
                task = asyncio.create_task(login())
            elif command == "k":
                try:
                    clip = Path(os.environ["SYSTEMROOT"]) / "System32" / "clip.exe"
                    await asyncio.to_thread(
                        subprocess.run,
                        [str(clip)],
                        input=key.encode("ascii"),
                        check=True,
                        timeout=3,
                    )
                    print("本地连接密钥已复制，可粘贴到酒馆或插件。", flush=True)
                except (OSError, subprocess.SubprocessError):
                    print(
                        "复制失败，可从 %LOCALAPPDATA%\\StudioPG-SinglePreview\\local-key.txt 复制。"
                    )
    finally:
        if task and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


async def serve(listener: socket.socket):
    root = state_directory()
    key = local_key(root)
    backend = BrowserBackend(root / "browser-profile")
    app = build_app(backend, key)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            access_log=False,
            log_level="warning",
            server_header=False,
            timeout_graceful_shutdown=8,
            proxy_headers=False,
        )
    )
    print(f"本机服务  http://127.0.0.1:{listener.getsockname()[1]}", flush=True)
    print("按 L 打开登录窗口，按 K 复制连接密钥，按 Ctrl+C 退出。", flush=True)
    task = asyncio.create_task(console(backend, key)) if sys.stdin.isatty() else None
    try:
        await server.serve(sockets=[listener])
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await backend.close()


def main() -> int:
    try:
        listener = listen()
    except OSError:
        print(
            "无法使用 127.0.0.1:8080。若已有服务在运行，请先保留现有服务，另选时间试用。"
        )
        return 1
    try:
        with listener:
            asyncio.run(serve(listener))
    except KeyboardInterrupt:
        pass
    except (OSError, RuntimeError, UnicodeError) as exc:
        print(f"启动失败：{exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
