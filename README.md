# 在 Windows 上用 SillyTavern 连接自己的 AI Studio（多账号预览版）

用自己的 Google 账号登录专用浏览器，就可以尝试把酒馆正文、剧情推进或填表接到本机的 `8080`。一个账号就能用。有多个账号时，每个账号单独保存登录状态，新的生成请求会在已启用的账号间轮换。酒馆和插件可以一直使用同一个本地密钥。

## 第一次安装

1. 下载 Windows 多账号预览版（`0.2.0a1`），右键 ZIP，选择「全部解压」。[下载 ZIP](./StudioPG-Windows-Multi-Preview.zip?raw=true) · [SHA-256 校验文件](./SHA256SUMS.txt)
2. 准备好 Edge 或 Chrome，按说明装好 uv，再双击解压目录里的 **启动.cmd**。第一次启动会自动准备运行环境。[新手安装说明](./StudioPG-Windows-Preview/README.md)
3. 在启动窗口按 **L** 登录自己的 Google 账号，按 **K** 复制本机生成的连接密钥。酒馆和服务装在同一台电脑时，按下表填写。

| 想怎么用 | 在哪里填 | 地址 |
| --- | --- | --- |
| 酒馆正文走 Gemini | 酒馆插头 → Chat Completion → Google AI Studio → 反向代理 | `http://127.0.0.1:8080` |
| 酒馆正文走 OpenAI 兼容接口 | 酒馆插头 → Chat Completion → Custom (OpenAI-compatible) → API URL | `http://127.0.0.1:8080/v1` |
| 只让剧情推进或填表走本机 | 插件的「API 与连接」→ 关闭「使用主 API」→ API 基础 URL | `http://127.0.0.1:8080/v1` |

在密码或 API Key 栏粘贴刚复制的密钥，加载模型列表，选择 `ai-studio-current`。普通文本和流式回复都可以用。实际生成使用你在专用浏览器里登录的账号额度。

要加入第二个账号，在启动窗口按 **A** 新建，按 **L** 登录，确认网页右上角显示的是第二个账号，再按 **E** 启用。按 **M** 可查看哪些账号参与轮换。正文和插件共用这套顺序。同一条消息遇到错误时不会换号重发。

## 登录能保持多久？

维护者曾在此前的本机自用版上观察到，真实 Google 账号的登录状态持续了数周。**这个多账号预览版尚未用真实 Google 账号验证跨小时保持登录。**

本版在 Windows 上使用真实 Edge 和本机模拟站点做了测试。两个模拟账号各登录一次，网站更新登录信息后，完全关闭并重启服务，两者仍能轮流收到请求。酒馆正文、剧情推进和填表的普通与流式回复均通过了这次测试。真实 Google 首次登录和当前 AI Studio 网页上的实际生成仍待独立账号确认。

## 以前的单账号预览版

需要之前发布的单账号版本时，可以继续使用它的固定下载。[单账号版 ZIP（v0.1.0-preview.1）](https://github.com/Epsilonmeow/aistudio-api/releases/download/v0.1.0-preview.1/StudioPG-Windows-Preview.zip) · [该版本的 SHA-256 校验文件](https://github.com/Epsilonmeow/aistudio-api/releases/download/v0.1.0-preview.1/SHA256SUMS.txt)

## 已有旧版反代，想单独加装酒馆适配？

如果你已在运行上游 `99c38ba` 的 Gemini 服务，可以继续用原来的独立补丁给它增加 OpenAI 兼容接口。上面的 Windows 预览版已经自带两种接口，首次安装只需下载 ZIP。[原补丁使用说明](./README-patch.md) · [原适配补丁](./sillytavern-openai.patch)
