"""Use one ordinary, visible browser profile and the AI Studio web interface."""

import asyncio
import os
import re
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import BrowserContext, Error, Page, async_playwright
from protocol_api import BackendError

STUDIO_ORIGIN = "https://aistudio.google.com"
NEW_CHAT = STUDIO_ORIGIN + "/prompts/new_chat"
EDITOR = (
    "ms-prompt-box textarea:visible, ms-prompt-input-wrapper textarea:visible, "
    "ms-chunk-input textarea:visible, textarea[aria-label*='prompt' i]:visible"
)
RUN = (
    "ms-run-button button[type=submit]:visible, "
    "button.run-button[aria-label=Run]:visible, button.run-button[aria-label='运行']:visible"
)
MODEL = "ms-chat-turn:has(.model-prompt-container), ms-chat-turn:has(.chat-turn-container.model)"
STOP = (
    "ms-run-button button[aria-label*='stop' i]:visible, "
    "ms-run-button button[aria-label*='停止']:visible, .run-button .stoppable-spinner:visible"
)
FINISHED_ACTION = (
    "button[name=rerun-button]:visible:enabled, "
    "button[aria-label='Regenerate response']:visible:enabled"
)
MARKER = "pg-preview-browser.txt"
POLL_SECONDS = 0.25
EDITOR_TIMEOUT = 35
REPLY_TIMEOUT = 600


def _choose_channel() -> str:
    roots = [Path(v) for k in ("ProgramFiles(x86)", "ProgramFiles", "LocalAppData")
             if (v := os.environ.get(k))]
    for channel, path in (("msedge", "Microsoft/Edge/Application/msedge.exe"),
                          ("chrome", "Google/Chrome/Application/chrome.exe")):
        if any((root / path).is_file() for root in roots):
            return channel
    raise BackendError(503, "请先安装标准版 Microsoft Edge 或 Google Chrome。")


async def _check_page(page: Page):
    address = urlsplit(page.url)
    if address.hostname == "accounts.google.com":
        raise BackendError(401, "请在本机专用浏览器完成登录，再发起新请求。")
    if (address.scheme + "://" + address.netloc) != STUDIO_ORIGIN:
        raise BackendError(403, "页面已离开 AI Studio。请在专用窗口检查访问状态。")
    if not await page.evaluate("navigator.onLine"):
        raise BackendError(503, "网络已断开。连接恢复后可以重新发起请求。")
    if await page.locator("iframe[title*='challenge' i]:visible, #captcha-form:visible").count():
        raise BackendError(403, "网页要求人工验证，本次请求已停止。")
    for alert in await page.locator("[role=alert]:visible, ms-error-message:visible").all():
        notice = (await alert.inner_text(timeout=2000)).lower()
        if re.search(r"quota|rate limit|too many requests|额度|限流|配额", notice):
            raise BackendError(429, "网页提示已达用量限制。")
        if re.search(r"sign in|sign-in|重新登录|请登录", notice):
            raise BackendError(401, "请在本机专用浏览器检查登录状态。")
        if re.search(r"permission|access denied|not allowed|verification|拒绝|权限|验证", notice):
            raise BackendError(403, "网页拒绝访问或要求验证，本次请求已停止。")
        if re.search(r"error|failed|offline|network|went wrong|错误|失败|网络", notice):
            raise BackendError(502, "网页报告错误。本次请求已停止，浏览器资料保留。")


async def _navigate(page):
    response = await page.goto(NEW_CHAT, wait_until="domcontentloaded", timeout=45000)
    if response and response.status >= 400:
        status = response.status if response.status in (401, 403, 429) else 502
        raise BackendError(status, "网页未能打开。请在专用窗口检查访问状态。")


class BrowserBackend:
    model_id = "ai-studio-current"

    def __init__(self, profile_dir: Path):
        self._profile = Path(profile_dir).resolve()
        self._context: BrowserContext | None = None
        self._driver = None
        self._lock = asyncio.Lock()

    def _context_closed(self, context):
        if self._context is context:
            self._context = None

    async def _browser(self, *, first_run=False):
        if self._context is not None:
            return self._context
        marker = self._profile / MARKER
        if not marker.is_file():
            if not first_run:
                raise BackendError(401, "请先打开本机专用登录窗口，用自己的账号登录。")
            self._profile.mkdir(parents=True, exist_ok=True)
            if any(self._profile.iterdir()):
                raise BackendError(409, "该目录已有其他浏览器资料，请使用空的专用目录。")
            channel = _choose_channel()
            with marker.open("x", encoding="ascii") as out:
                out.write(channel)
        else:
            channel = marker.read_text(encoding="ascii").strip()
            if channel not in {"msedge", "chrome"}:
                raise BackendError(409, "专用浏览器的类型记录无效，请检查本机资料目录。")
        if self._driver is None:
            self._driver = await async_playwright().start()
        try:
            context = await self._driver.chromium.launch_persistent_context(
                user_data_dir=self._profile, channel=channel, headless=False,
                chromium_sandbox=True, accept_downloads=False, no_viewport=True,
                timeout=25000,
            )
        except Error:
            raise BackendError(503, "无法打开专用浏览器。请检查浏览器是否已安装，以及该目录是否已被另一个进程打开。") from None
        self._context = context
        context.on("close", self._context_closed)
        return context

    async def open_login(self):
        if self._lock.locked():
            raise BackendError(409, "有请求正在使用专用浏览器，请稍后再打开登录窗口。")
        async with self._lock:
            try:
                ctx = await self._browser(first_run=True)
                for page in ctx.pages:
                    if urlsplit(page.url).hostname in {urlsplit(STUDIO_ORIGIN).hostname, "accounts.google.com"}:
                        await page.bring_to_front()
                        return
                page = next((p for p in ctx.pages if p.url == "about:blank"), None)
                if page is None:
                    page = await ctx.new_page()
                await _navigate(page)
                await page.bring_to_front()
            except Error:
                raise BackendError(503, "专用浏览器未能打开登录页面，请检查网络和窗口状态。") from None

    async def close(self):
        async with self._lock:
            try:
                if self._context is not None:
                    await self._context.close()
            finally:
                self._context = None
                if self._driver is not None:
                    await self._driver.stop()
                    self._driver = None

    async def generate(self, prompt: str, max_tokens: int | None):
        # The Web UI determines the generation limit. It does not expose an
        # exact token count on its rendered incremental text.
        del max_tokens
        if self._lock.locked():
            raise BackendError(503, "本机已有一个请求正在生成，请在结束后再试。")
        async with self._lock:
            page = None
            try:
                ctx = await self._browser()
                page = await ctx.new_page()
                await _navigate(page)
                await self._submit_once(page, prompt)
                async for text in self._visible_reply(page):
                    yield text
            except Error:
                raise BackendError(503, "浏览器或网络连接中断。浏览器资料保留，本次请求不会自动重发。") from None
            finally:
                if page is not None and not page.is_closed():
                    with suppress(Error):
                        await page.close()

    async def _submit_once(self, page, prompt):
        clock = asyncio.get_running_loop()
        deadline = clock.time() + EDITOR_TIMEOUT
        editor, run = page.locator(EDITOR), page.locator(RUN)
        while clock.time() < deadline:
            await _check_page(page)
            if await editor.count() == 1 and await run.count() == 1:
                break
            if await page.get_by_role("button", name=re.compile(r"^(Sign in|登录)$", re.I)).count():
                raise BackendError(401, "请先在本机专用窗口登录。")
            await asyncio.sleep(POLL_SECONDS)
        else:
            raise BackendError(502, "没有找到可确认的网页输入框和运行按钮，请检查专用窗口。")
        if await page.locator("ms-chat-turn .user-prompt-container, " + MODEL).count():
            raise BackendError(409, "新对话已包含消息，本次未提交，以免混入旧对话。")
        # Hold handles to this document: a redirect must not retarget an
        # ordinary fill or click to an unrelated page.
        field = await editor.element_handle(timeout=2500)
        button = await run.element_handle(timeout=2500)
        for handle in (field, button):
            if not handle or await handle.evaluate("el => el.ownerDocument.location.origin") != STUDIO_ORIGIN:
                raise BackendError(403, "页面已切换，本次未提交。")
        await field.fill(prompt, timeout=5000)
        await button.click(timeout=5000)

    async def _visible_reply(self, page):
        clock = asyncio.get_running_loop()
        deadline = clock.time() + REPLY_TIMEOUT
        sent = ""
        terminal_text = None
        while clock.time() < deadline:
            await _check_page(page)
            turn = page.locator(MODEL)
            count = await turn.count()
            if count > 1:
                raise BackendError(502, "检测到多个模型回复，无法确定本次正文。")
            if count == 1:
                done = bool(await turn.locator(FINISHED_ACTION).count()) and not await page.locator(STOP).count()
                parts = turn.locator("ms-text-chunk > ms-cmark-node:visible")
                text = await parts.evaluate_all(r"""nodes => nodes.filter(n => !n.closest(
                    "ms-thought-accordion, ms-thought-chunk, [data-testid*='thinking'], [data-testid*='reasoning']"
                )).map(n => n.innerText).join('\n')""")
                if not text.startswith(sent):
                    raise BackendError(502, "网页修改了已显示的正文，无法继续准确传输。")
                if len(text) > len(sent):
                    delta, sent = text[len(sent):], text
                    yield delta
                if done and text == terminal_text:
                    if not sent:
                        raise BackendError(502, "网页已结束生成，但未找到可见正文。")
                    return
                terminal_text = text if done else None
            await asyncio.sleep(POLL_SECONDS)
        raise BackendError(504, "等待网页明确结束生成超时。可以检查网络和登录状态。")
