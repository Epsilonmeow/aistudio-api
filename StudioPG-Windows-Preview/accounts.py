"""Keep a separate Windows browser profile for each local account slot."""

import asyncio
import sqlite3
from contextlib import aclosing
from pathlib import Path

from browser_backend import MARKER, BrowserBackend
from protocol_api import BackendError


class AccountPool:
    model_id = BrowserBackend.model_id

    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(root / "accounts.sqlite3")
        with self._db:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS accounts ("
                "id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL, "
                "last_served INTEGER NOT NULL DEFAULT 0)"
            )
            # Slot 1 keeps the profile and connection key from the single-account release.
            self._db.execute("INSERT OR IGNORE INTO accounts (id, enabled) VALUES (1, 1)")
        self._active: tuple[int, BrowserBackend] | None = None
        self._editing: int | None = None
        self._generating = asyncio.Lock()

    def accounts(self) -> list[tuple[int, bool]]:
        rows = self._db.execute("SELECT id, enabled FROM accounts ORDER BY id")
        return [(number, bool(enabled)) for number, enabled in rows]

    def add(self) -> int:
        # The user signs in and explicitly enables the new slot when it is ready.
        with self._db:
            row = self._db.execute("INSERT INTO accounts (enabled) VALUES (0)")
        return row.lastrowid

    def set_enabled(self, number: int, enabled: bool):
        with self._db:
            updated = self._db.execute(
                "UPDATE accounts SET enabled=? WHERE id=?", (enabled, number)
            )
            if not updated.rowcount:
                raise ValueError("账号编号不存在。")
        if self._editing == number:
            self._editing = None

    def profile(self, number: int) -> Path:
        if number == 1:
            return self.root / "browser-profile"
        return self.root / "account-profiles" / str(number) / "browser-profile"

    async def _activate(self, number: int) -> BrowserBackend:
        if self._active and self._active[0] == number:
            return self._active[1]
        if self._active:
            # Let the browser finish writing updated cookies before opening another profile.
            await self._active[1].close()
        backend = BrowserBackend(self.profile(number))
        self._active = (number, backend)
        self._editing = None
        return backend

    async def open_login(self, number: int):
        enabled = dict(self.accounts())
        if number not in enabled:
            raise ValueError("账号编号不存在。")
        if self._generating.locked():
            raise BackendError(409, "有请求正在使用专用浏览器，请稍后再打开登录窗口。")
        async with self._generating:
            backend = await self._activate(number)
            await backend.open_login()
            if not enabled[number]:
                self._editing = number

    def _next_account(self) -> int:
        rows = self._db.execute(
            "SELECT id FROM accounts WHERE enabled=1 ORDER BY last_served, id"
        ).fetchall()
        if not rows:
            raise BackendError(503, "没有启用的账号。请在启动窗口按 M 查看账号。")
        for (number,) in rows:
            if (self.profile(number) / MARKER).is_file():
                return number
        raise BackendError(401, "请在启动窗口按 L，用自己的账号登录专用浏览器。")

    async def generate(self, prompt: str, max_tokens: int | None):
        if self._generating.locked():
            raise BackendError(503, "本机已有一个请求正在生成，请在结束后再试。")
        async with self._generating:
            number = self._next_account()
            if (
                self._editing is not None and self._editing != number
                and self._active and self._active[1].window_open
            ):
                raise BackendError(
                    409, f"正在登录账号 {self._editing}。完成后按 E 启用，或关闭该浏览器窗口再试。"
                )
            first = True
            try:
                backend = await self._activate(number)
                async with aclosing(backend.generate(prompt, max_tokens)) as reply:
                    async for text in reply:
                        if first and text:
                            # A stream stopped by the client after receiving text still counts.
                            with self._db:
                                self._db.execute(
                                    "UPDATE accounts SET last_served="
                                    "(SELECT MAX(last_served) + 1 FROM accounts) WHERE id=?",
                                    (number,),
                                )
                            first = False
                        yield text
            except BackendError as exc:
                raise BackendError(exc.status, f"账号 {number}：{exc.message}") from None

    async def close(self):
        try:
            async with self._generating:
                if self._active:
                    await self._active[1].close()
        finally:
            self._db.close()
