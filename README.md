# 用本机 8080 连接 SillyTavern

这个补丁给已经运行在本机的 Gemini 格式服务增加 OpenAI 兼容的文本接口。酒馆可以用它生成正文，剧情推进、填表等插件也可以单独使用。两种接口共用现有服务和端口。

## 在酒馆里填什么

| 用途 | 在哪里设置 | 基础 URL |
| --- | --- | --- |
| 正文走 Gemini 原生接口 | 酒馆插头 → Chat Completion → Google AI Studio → 反向代理 | `http://127.0.0.1:8080` |
| 正文走 OpenAI 兼容接口 | 酒馆插头 → Chat Completion → Custom (OpenAI-compatible) → API URL | `http://127.0.0.1:8080/v1` |
| 只让剧情推进、填表走本机 | 插件「API 与连接」→ 关闭「使用主 API」→ API 基础 URL | `http://127.0.0.1:8080/v1` |

**Key** 填本地服务设置的 API Key。服务没有设 Key 时可以留空。如果这时客户端要求必填，可以填 `local`。插件里加载模型列表、选择文本模型并保存。若剧情推进有单独的 API 预设，再到那里选中刚保存的预设。

## 什么时候需要安装

如果本机的 `GET /v1/models` 已返回带 `data` 数组的模型列表，而且酒馆能用上述地址生成正文，可以直接使用现有配置。如果你的服务只有 Gemini 原生接口，可以安装补丁。

补丁按 `DeconstructedCube/aistudio-api` 的 [`99c38ba` 版本](https://github.com/DeconstructedCube/aistudio-api/commit/99c38baefc84d8cb66b05c28ede8a49ce050bfb2) 制作。将 [sillytavern-openai.patch](./sillytavern-openai.patch) 下载到现有服务的源码根目录，在该目录打开 PowerShell，运行以下命令。第一行检查文件是否匹配，通过后第二行才会应用补丁。

```powershell
git apply --check ./sillytavern-openai.patch
if ($LASTEXITCODE -eq 0) { git apply ./sillytavern-openai.patch }
```

应用成功后重启本机服务，回到酒馆连接。代码结构不同的版本需要单独验证。

## 支持哪些请求

- `GET /v1/models` 列出文本模型。
- `POST /v1/chat/completions` 支持普通文本和流式回复。流式回复会在生成过程中分段显示。
- 目前支持文本消息和 `response_format: {"type":"text"}`。要求 JSON Schema、图片输入或工具调用的插件不在本版支持范围内。

补丁中包含接口测试。已安装开发依赖的服务可以运行 `python -m pytest -q tests/unit/test_openai_compat.py` 验证这两个接口。测试使用模拟模型回复。
