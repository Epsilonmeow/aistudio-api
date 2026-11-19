# 在 Windows 上用 SillyTavern 连接自己的 AI Studio

用自己的 Google 账号登录专用浏览器，就可以尝试把酒馆正文、剧情推进或填表插件接到本机的 `8080`。正文和插件可以分别选择接口，也可以只让插件使用本机服务。

## 第一次安装

1. [下载 Windows 单账号预览版 ZIP（v0.1.0-preview.1）](https://github.com/Epsilonmeow/aistudio-api/releases/download/v0.1.0-preview.1/StudioPG-Windows-Preview.zip) · [校验文件 SHA256SUMS.txt](https://github.com/Epsilonmeow/aistudio-api/releases/download/v0.1.0-preview.1/SHA256SUMS.txt)。右键下载的 ZIP，选择「全部解压」。
2. 准备好 Edge 或 Chrome，按[新手安装说明](./StudioPG-Windows-Preview/README.md)装好 uv，再双击解压目录里的 **启动.cmd**。第一次启动会自动准备运行环境。
3. 在启动窗口按 **L** 登录自己的 Google 账号，按 **K** 复制本机生成的连接密钥。酒馆和服务装在同一台电脑时，按下表填写。

| 想怎么用 | 在哪里填 | 地址 |
| --- | --- | --- |
| 酒馆正文走 Gemini | 酒馆插头 → Chat Completion → Google AI Studio → 反向代理 | `http://127.0.0.1:8080` |
| 酒馆正文走 OpenAI 兼容接口 | 酒馆插头 → Chat Completion → Custom (OpenAI-compatible) → API URL | `http://127.0.0.1:8080/v1` |
| 只让剧情推进或填表走本机 | 插件的「API 与连接」→ 关闭「使用主 API」→ API 基础 URL | `http://127.0.0.1:8080/v1` |

在密码或 API Key 栏粘贴刚复制的密钥，加载模型列表，选择 `ai-studio-current`。普通文本和流式回复都可以用。实际生成使用你在专用浏览器里登录的账号额度。

## 登录能保持多久？

专用浏览器会把网站更新的登录信息保存在自己的电脑上，下次启动会打开同一份资料。我们用本地模拟站点验证过，网站更新会话后，关闭并重开浏览器仍能继续使用。

**真实 Google 账号跨小时保持登录尚未验证。** 预览版还需要用独立账号确认首次登录、当前 AI Studio 网页的实际生成，以及超过原先一两小时后能否继续使用。酒馆两种接口的普通和流式回复已用本地模拟回复测过。

## 已有旧版反代，想单独加装酒馆适配？

如果你已在运行上游 `99c38ba` 的 Gemini 服务，可以继续用原来的独立补丁给它增加 OpenAI 兼容接口。上面的 Windows 预览版已经自带两种接口，首次安装只需下载 ZIP。[原补丁使用说明](./README-patch.md) · [原适配补丁](./sillytavern-openai.patch)
