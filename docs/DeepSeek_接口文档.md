# DeepSeek API 开发说明（与本项目相关）

官方文档以 [DeepSeek API 文档](https://api-docs.deepseek.com/) 为准。本项目通过 **HTTPS + JSON** 调用，**不使用官方 SDK**。

---

## 1. 鉴权

| 项目 | 说明 |
|------|------|
| 方式 | `Authorization: Bearer <API_KEY>` |
| Key 获取 | [DeepSeek 开放平台](https://platform.deepseek.com/) |
| 配置 | 写入 `backend/.env` 的 `DEEPSEEK_API_KEY`（勿提交到 Git） |

---

## 2. 端点（OpenAI 兼容 Chat Completions）

| 项目 | 值 |
|------|-----|
| 方法 | `POST` |
| URL（默认） | `https://api.deepseek.com/v1/chat/completions` |
| `Content-Type` | `application/json` |

---

## 3. 本项目用法：结构化 JSON 输出

为从 ASR 文本中稳定抽取两个地址字段，请求体使用：

- `model`：如 `deepseek-chat`
- `messages`：`system`（抽取规则）+ `user`（识别文本）
- `stream`：`false`
- `response_format`：`{"type": "json_object"}`（要求模型仅输出 JSON 对象）

响应与 OpenAI 兼容：从 `choices[0].message.content` 取字符串，再 `json.loads` 得到  
`address_a`、`address_b`、`notes` 等字段。

---

## 3b. 第二次调用：整合高德结果（纯文本）

在 **高德中点相遇** 返回后，将「识别原文 + 抽取的两地 + 地图结构化摘要」再发给 **同一 Chat Completions 端点**，**不使用** `response_format`，让模型输出 **一段口语化中文**（供用户阅读与 TTS）。

- 模型：默认与第一次相同，可通过 `DEEPSEEK_COMPOSE_MODEL` 单独指定。
- `temperature`：由 `DEEPSEEK_COMPOSE_TEMPERATURE` 控制（通常略高于抽取阶段）。

---

## 4. 参数与限制（摘要）

- `temperature`：本项目默认较低（如 `0.2`），减少随机性。
- 超时、URL、模型名均在 `backend/.env` 中配置，见 `backend/.env.example`。

---

## 5. 安全与代理

- **勿**在前端暴露 API Key。
- 发起请求前会 **清除进程内代理相关环境变量**，且 `httpx` 使用 `trust_env=False`，避免误走系统代理（与百炼调用策略一致）。

---

## 6. 参考链接

- [Create Chat Completion](https://api-docs.deepseek.com/api/create-chat-completion)
- [JSON Output / response_format](https://api-docs.deepseek.com/guides/json_mode)（以官网当前说明为准）
