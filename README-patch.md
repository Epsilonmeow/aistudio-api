# 用本机 8080 连接 SillyTavern

这个分支提供一个补丁，适合电脑上已经运行 `DeconstructedCube/aistudio-api`、能通过 Gemini 接口生成回复的用户。安装后，同一个本地服务会多出 OpenAI 兼容的文本接口。酒馆正文和剧情推进、填表等插件都可以使用。

**先看版本。** 补丁已在上游 `99c38ba` 的干净副本上通过接口测试。2026 年 11 月 19 日核对上游 `fcdc53e` 时，安装前检查在 `app.py` 注册接口的位置失败，这一版需要单独适配。[已验证版本](https://github.com/DeconstructedCube/aistudio-api/commit/99c38baefc84d8cb66b05c28ede8a49ce050bfb2) · [新版代码](https://github.com/DeconstructedCube/aistudio-api/blob/fcdc53ee753a9e160686193ac9841bdf97b7227f/src/aistudio_api/api/app.py)

**账号功能来自你自己的服务。** 在已验证的 `99c38ba` 上，原服务会在加载 Cookie 时尝试刷新登录状态，也支持多账号轮换。公开补丁只增加酒馆接口和相关测试。维护者自用版额外做了登录状态的定期保存和断线恢复，这些改动保留在本地完整版里。实际能保持登录多久，取决于各自的服务和账号会话。

## 在酒馆里填什么

下表按酒馆和服务在同一台电脑上填写。`127.0.0.1` 指向使用者自己的电脑。

| 用途 | 在哪里设置 | 基础 URL |
| --- | --- | --- |
| 正文走 Gemini 原生接口 | 酒馆插头 → Chat Completion → Google AI Studio → 反向代理 | `http://127.0.0.1:8080` |
| 正文走 OpenAI 兼容接口 | 酒馆插头 → Chat Completion → Custom (OpenAI-compatible) → API URL | `http://127.0.0.1:8080/v1` |
| 只让剧情推进、填表走本机 | 插件「API 与连接」→ 关闭「使用主 API」→ API 基础 URL | `http://127.0.0.1:8080/v1` |

**Key** 填本地服务设置的 API Key。服务没有设 Key 时可以留空。如果这时客户端要求必填，可以填 `local`。插件里加载模型列表、选择文本模型并保存。若剧情推进有单独的 API 预设，再到那里选中刚保存的预设。

## 什么时候需要安装

如果本机的 `GET /v1/models` 已返回带 `data` 数组的模型列表，而且酒馆能用上述地址生成正文，可以直接使用现有配置。

如果你用的是 `99c38ba`，需要添加 OpenAI 兼容接口，请打开补丁文件，在 GitHub 文件页选择 **Download raw file**，保存到现有服务的源码根目录。[打开补丁文件](./sillytavern-openai.patch)

在该目录打开 PowerShell，运行以下命令。第一行检查文件是否匹配，通过后第二行才会应用补丁。

```powershell
git apply --check ./sillytavern-openai.patch
if ($LASTEXITCODE -eq 0) { git apply ./sillytavern-openai.patch }
```

应用成功后重启本机服务，回到酒馆连接。

## 支持哪些请求

- `GET /v1/models` 列出文本模型。
- `POST /v1/chat/completions` 支持普通文本和流式回复。流式回复会在生成过程中分段显示。
- 目前支持文本消息和 `response_format: {"type":"text"}`。要求 JSON Schema、图片输入或工具调用的插件不在本版支持范围内。

补丁中包含接口测试。已安装开发依赖的服务可以运行 `python -m pytest -q tests/unit/test_openai_compat.py` 验证这两个接口。测试使用模拟模型回复。
