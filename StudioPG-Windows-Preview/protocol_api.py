"""Local text API. The backend yields visible text increments for one page model."""

from __future__ import annotations

import json
import secrets
import time
import uuid
from collections.abc import AsyncGenerator
from typing import Literal, Protocol

import anyio
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator
from starlette.requests import ClientDisconnect


class BackendError(Exception):
    """The message must be safe for the client. Do not include page content or keys."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class TextBackend(Protocol):
    model_id: str

    def generate(
        self, prompt: str, max_tokens: int | None
    ) -> AsyncGenerator[str, None]: ...


class TextFields(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatPart(TextFields):
    type: Literal["text"]
    text: str


class ChatMessage(TextFields):
    role: Literal["system", "developer", "user", "assistant"]
    content: str | list[ChatPart]
    name: str | None = None
    tool_calls: list[object] | None = Field(default=None, max_length=0)
    function_call: None = None


class StreamOptions(TextFields):
    include_usage: Literal[False] = False


class ChatRequest(TextFields):
    model: str
    messages: list[ChatMessage] = Field(min_length=1)
    stream: bool = False
    max_tokens: int | None = Field(default=None, gt=0)
    max_completion_tokens: int | None = Field(default=None, gt=0)
    stop: str | list[str] | None = None
    response_format: dict[str, object] | None = None
    tools: list[object] | None = Field(default=None, max_length=0)
    functions: list[object] | None = Field(default=None, max_length=0)
    tool_choice: Literal["none", "auto"] | None = None
    function_call: Literal["none"] | None = None
    stream_options: StreamOptions | None = None
    n: Literal[1] | None = 1
    # Common SillyTavern sampling fields. Sampling is controlled in the page.
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    logit_bias: dict[str, object] | None = Field(default=None, max_length=0)
    seed: Literal[-1] | None = None
    logprobs: Literal[False] | None = None

    @field_validator("response_format")
    @classmethod
    def text_format(cls, value):
        if value is not None and value != {"type": "text"}:
            raise ValueError("Only text is supported")
        return value


class GeminiPart(TextFields):
    text: str
    thought: Literal[False] | None = None


class Content(TextFields):
    role: Literal["user", "model", "system"] | None = None
    parts: list[GeminiPart] = Field(min_length=1)


class GenerationConfig(TextFields):
    maxOutputTokens: int | None = Field(default=None, gt=0)
    stopSequences: list[str] | None = None
    candidateCount: Literal[1] = 1
    responseMimeType: Literal["text/plain"] | None = None
    responseSchema: None = None
    responseModalities: list[Literal["TEXT"]] | None = None
    temperature: float | None = None
    topP: float | None = None
    topK: int | None = None
    seed: Literal[-1] | None = None


class GeminiRequest(TextFields):
    contents: list[Content] = Field(min_length=1)
    systemInstruction: Content | None = Field(
        default=None,
        validation_alias=AliasChoices("systemInstruction", "system_instruction"),
    )
    generationConfig: GenerationConfig = Field(default_factory=GenerationConfig)
    tools: list[object] | None = Field(default=None, max_length=0)
    # Clients often attach their default array. The web page applies its own policy.
    safetySettings: list[dict[str, str]] | None = None


def _prompt(turns: list[dict[str, str]]) -> str:
    if not any(t["role"] == "user" and t["content"].strip() for t in turns):
        raise BackendError(400, "请提供至少一条非空用户消息。")
    if len(turns) == 1 and "name" not in turns[0]:
        return turns[0]["content"]
    return (
        "Continue the following conversation. Return the next assistant reply only.\n"
        + json.dumps(turns, ensure_ascii=False)
    )


def _stops(value: str | list[str] | None) -> list[str]:
    stops = [value] if isinstance(value, str) else value or []
    if len(stops) > 5 or any(not s or len(s) > 512 for s in stops):
        raise BackendError(400, "停止词须为非空文本，最多 5 个，每个不超过 512 字符。")
    return stops


async def _visible(source: AsyncGenerator[str, None], stops: list[str]):
    """Hold only a suffix that could grow into a stop sequence across chunks."""
    pending = ""
    try:
        async for text in source:
            if not isinstance(text, str):
                raise BackendError(502, "网页返回了无效的文字片段。")
            if not text:
                continue
            if not stops:
                yield text
                continue
            pending += text
            positions = [pos for stop in stops if (pos := pending.find(stop)) >= 0]
            if positions:
                # An initial stop sequence is a valid empty completion.
                yield pending[: min(positions)]
                return
            hold = max(
                (
                    n
                    for stop in stops
                    for n in range(1, min(len(stop), len(pending) + 1))
                    if pending.endswith(stop[:n])
                ),
                default=0,
            )
            if len(pending) > hold:
                yield pending[: len(pending) - hold]
            pending = pending[-hold:] if hold else ""
        if pending:
            yield pending
    finally:
        with anyio.CancelScope(shield=True):
            await source.aclose()


def _error(exc: BackendError, gemini: bool):
    status = exc.status
    if gemini:
        label = {
            400: "INVALID_ARGUMENT",
            401: "UNAUTHENTICATED",
            403: "PERMISSION_DENIED",
            404: "NOT_FOUND",
            409: "FAILED_PRECONDITION",
            429: "RESOURCE_EXHAUSTED",
            503: "UNAVAILABLE",
            504: "DEADLINE_EXCEEDED",
        }.get(status, "INTERNAL")
        return {"error": {"code": status, "status": label, "message": exc.message}}
    label = (
        "server_error"
        if status >= 500
        else {
            401: "authentication_error",
            403: "permission_error",
            429: "rate_limit_error",
        }.get(status, "invalid_request_error")
    )
    return {
        "error": {"message": exc.message, "type": label, "param": None, "code": status}
    }


def _candidate(text: str, finish: bool):
    candidate = {"index": 0, "content": {"role": "model", "parts": [{"text": text}]}}
    if finish:
        candidate["finishReason"] = "STOP"
    return {"candidates": [candidate]}


def _event(obj: dict) -> bytes:
    return ("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode()


class Completion(Response):
    """Send headers on first output; release the backend on client disconnect."""

    def __init__(
        self,
        backend: TextBackend,
        prompt: str,
        limit: int | None,
        stops: list[str],
        stream: bool,
        gemini: bool,
    ):
        super().__init__()
        self.backend, self.prompt, self.limit = backend, prompt, limit
        self.stops, self.stream, self.gemini = stops, stream, gemini

    async def __call__(self, scope, receive, send):
        async def write(message):
            try:
                await send(message)
            except (OSError, anyio.BrokenResourceError) as exc:
                raise ClientDisconnect from exc

        async def body(data, more=True):
            await write({"type": "http.response.body", "body": data, "more_body": more})

        meta = {
            "id": "chatcmpl-" + uuid.uuid4().hex,
            "created": int(time.time()),
            "model": self.backend.model_id,
        }

        def chunk(delta, finish=None):
            return {
                **meta,
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }

        async def deliver():
            source = None
            seen = started = False
            parts = []
            try:
                source = _visible(
                    self.backend.generate(self.prompt, self.limit), self.stops
                )
                async for text in source:
                    seen = True
                    if not self.stream:
                        parts.append(text)
                        continue
                    if not started:
                        await write(
                            {
                                "type": "http.response.start",
                                "status": 200,
                                "headers": [
                                    (
                                        b"content-type",
                                        b"text/event-stream; charset=utf-8",
                                    ),
                                    (b"cache-control", b"no-store"),
                                    (b"x-pg-settings-source", b"browser-page"),
                                    (
                                        b"x-pg-page-controls",
                                        b"sampling,safety,output-tokens",
                                    ),
                                ],
                            }
                        )
                        started = True
                        if not self.gemini:
                            await body(
                                _event(chunk({"role": "assistant", "content": ""}))
                            )
                    if text:
                        await body(
                            _event(
                                _candidate(text, False)
                                if self.gemini
                                else chunk({"content": text})
                            )
                        )
                if not seen:
                    raise BackendError(502, "网页没有返回可见回复。")
                if self.stream:
                    await body(
                        _event(
                            _candidate("", True) if self.gemini else chunk({}, "stop")
                        )
                    )
                    await body(b"" if self.gemini else b"data: [DONE]\n\n", False)
                else:
                    text = "".join(parts)
                    response = (
                        _candidate(text, True)
                        if self.gemini
                        else {
                            **meta,
                            "object": "chat.completion",
                            "choices": [
                                {
                                    "index": 0,
                                    "message": {"role": "assistant", "content": text},
                                    "finish_reason": "stop",
                                }
                            ],
                        }
                    )
                    await JSONResponse(
                        response,
                        headers={
                            "X-PG-Settings-Source": "browser-page",
                            "X-PG-Page-Controls": "sampling,safety,output-tokens",
                        },
                    )(scope, receive, write)
            except ClientDisconnect:
                return
            except Exception as err:
                exc = (
                    err
                    if isinstance(err, BackendError)
                    else BackendError(502, "网页连接中断，请检查专用窗口。")
                )
                if started:
                    await body(_event(_error(exc, self.gemini)))
                    await body(b"" if self.gemini else b"data: [DONE]\n\n", False)
                else:
                    await JSONResponse(
                        _error(exc, self.gemini), status_code=exc.status
                    )(scope, receive, write)
            finally:
                if source is not None:
                    with anyio.CancelScope(shield=True):
                        await source.aclose()

        async with anyio.create_task_group() as jobs:

            async def run():
                try:
                    await deliver()
                except ClientDisconnect:
                    pass
                finally:
                    jobs.cancel_scope.cancel()

            jobs.start_soon(run)
            while (await receive())["type"] != "http.disconnect":
                pass
            jobs.cancel_scope.cancel()


def create_app(backend: TextBackend, api_key: str) -> FastAPI:
    if not api_key:
        raise ValueError("A local API key is required")
    secret = api_key.encode()

    async def authorize(request: Request):
        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        keys = [
            token if scheme.lower() == "bearer" else "",
            request.headers.get("x-api-key", ""),
            request.headers.get("x-goog-api-key", ""),
            request.query_params.get("key", ""),
        ]
        if not any(secrets.compare_digest(key.encode(), secret) for key in keys):
            raise BackendError(401, "本地 API Key 不正确。")

    app = FastAPI(
        dependencies=[Depends(authorize)],
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.exception_handler(BackendError)
    async def backend_error(request: Request, exc: BackendError):
        return JSONResponse(
            _error(exc, request.url.path.startswith("/v1beta/")), status_code=exc.status
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, _exc: RequestValidationError):
        return await backend_error(
            request,
            BackendError(
                400, "请求格式不受支持。请使用文本消息，关闭工具、图片及结构化输出。"
            ),
        )

    def check_model(name: str):
        if name.removeprefix("models/") != backend.model_id:
            raise BackendError(404, "请选择本地模型列表中的网页模型。")

    def gemini_model():
        return {
            "name": "models/" + backend.model_id,
            "displayName": backend.model_id,
            "supportedGenerationMethods": ["generateContent", "streamGenerateContent"],
        }

    @app.get("/v1/models")
    async def openai_list():
        return {
            "object": "list",
            "data": [
                {
                    "id": backend.model_id,
                    "object": "model",
                    "created": 0,
                    "owned_by": "local",
                }
            ],
        }

    @app.get("/v1beta/models")
    async def gemini_list():
        return {"models": [gemini_model()]}

    @app.get("/v1beta/models/{model}")
    async def get_gemini(model: str):
        check_model(model)
        return gemini_model()

    @app.post("/v1/chat/completions")
    async def openai_chat(req: ChatRequest):
        check_model(req.model)
        turns = []
        for m in req.messages:
            text = (
                m.content
                if isinstance(m.content, str)
                else "".join(p.text for p in m.content)
            )
            turn = {"role": m.role, "content": text}
            if m.name:
                turn["name"] = m.name
            turns.append(turn)
        return Completion(
            backend,
            _prompt(turns),
            req.max_completion_tokens or req.max_tokens,
            _stops(req.stop),
            req.stream,
            False,
        )

    @app.post("/v1beta/models/{model}:{method}")
    async def gemini_chat(
        model: str, method: str, req: GeminiRequest, alt: str = "sse"
    ):
        check_model(model)
        if method not in ("generateContent", "streamGenerateContent"):
            raise BackendError(404, "未知的 Gemini 方法。")
        stream = method == "streamGenerateContent"
        if stream and alt != "sse":
            raise BackendError(400, "流式 Gemini 接口支持 alt=sse。")
        turns = []
        if req.systemInstruction:
            turns.append(
                {
                    "role": "system",
                    "content": "".join(p.text for p in req.systemInstruction.parts),
                }
            )
        for c in req.contents:
            if c.role == "system":
                raise BackendError(400, "系统指令请放在 systemInstruction。")
            turns.append(
                {
                    "role": "assistant" if c.role == "model" else "user",
                    "content": "".join(p.text for p in c.parts),
                }
            )
        cfg = req.generationConfig
        return Completion(
            backend,
            _prompt(turns),
            cfg.maxOutputTokens,
            _stops(cfg.stopSequences),
            stream,
            True,
        )

    return app
