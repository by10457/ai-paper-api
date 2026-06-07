# AI 模型配置

本文说明管理后台“模型配置”的用途、协议、字段和推荐配置方式。

## 配置来源

模型 API Key、Base URL 和模型名不再放在 `.env`，统一保存在数据库表：

```text
model_configs
```

管理页面：

```text
ai-paper-web -> 管理员菜单 -> 模型配置
```

代码读取入口：

```text
llm/client.py
```

读取规则：

1. 按 `config_type` 找启用配置。
2. 同一用途优先选择 `is_default=true`。
3. 文本模型允许回退到 `default`。
4. 图片模型 `figure` 不配置时使用本地占位图，不阻断论文生成。

## 用途 config_type

| 用途 | 业务含义 |
| --- | --- |
| `outline` | 论文大纲、摘要、致谢、参考文献关键词提取等短文本任务。 |
| `fulltext` | 论文正文长文本生成。 |
| `figure` | AI 插图生成。 |
| `default` | 文本模型兜底配置。 |

## 文本模型协议

### OpenAI 兼容协议

适用于 OpenAI、DeepSeek、Qwen、部分国内模型厂商和大多数第三方中转。

后台填写：

```text
provider=openai
model_name=<模型名>
api_base_url=<Base URL>
api_key=<API Key>
```

示例：

```text
provider=openai
model_name=deepseek-chat
api_base_url=https://api.deepseek.com
```

如果第三方中转商提供 OpenAI Chat Completions 兼容接口，只需要替换：

- `api_base_url`
- `api_key`
- `model_name`

### Anthropic Messages 协议

支持协议名：

```text
anthropic
claude
claude-messages
```

适用于 Claude 官方或严格兼容 Anthropic Messages 的中转。

### Gemini generateContent 协议

支持协议名：

```text
gemini
gemini-generate-content
google-generate-content
```

适用于 Google Gemini generateContent 或兼容接口。

注意：不要把 DeepSeek / Qwen 等 OpenAI 兼容模型配置成 Gemini 协议。后台会拦截明显错误，例如 DeepSeek 模型选择 Gemini 协议。

## 图片模型协议

图片用途 `figure` 支持：

| provider | 说明 |
| --- | --- |
| `gemini-generate-content` | Gemini generateContent 图片生成。 |
| `google-generate-content` | 同上。 |
| `openai-image-generations` | OpenAI Images API 或兼容图片生成接口。 |

如果未配置 `figure`，系统会生成空白占位图；如果 Mermaid 渲染成功，也不会读取图片模型配置。

## 温度和最大 token

后台不配置温度、最大 token、超时时间。

这些参数由不同业务环节在代码中按用途传入：

| 环节 | 用途 | 典型配置 |
| --- | --- | --- |
| 大纲生成 | `outline` | `temperature=0.4`, `max_tokens=2048` |
| 正文生成 | `fulltext` | `max_tokens=32768` |
| 摘要关键词 | `outline` | `temperature=0.3`, `max_tokens=2048` |
| 致谢 | `outline` | `temperature=0.7`, `max_tokens=1024` |
| 参考文献关键词 | `outline` | `temperature=0`, `max_tokens=512/768` |

这样后台只关心模型接入，生成策略由业务代码控制，避免不同流程互相影响。

## 推荐配置

最低可用配置：

| 用途 | 建议 |
| --- | --- |
| `outline` | 配一个短文本模型。 |
| `fulltext` | 配一个长上下文、长输出模型。 |
| `default` | 配一个文本兜底模型。 |
| `figure` | 可选；未配置时仍能生成论文，只是 AI 插图会降级。 |

生产建议：

- `outline` 和 `fulltext` 分开配置，避免长文本任务拖慢短文本响应。
- `fulltext` 使用输出能力更强的模型。
- `figure` 使用成本可控的图片模型；Mermaid 会作为主力图表方式，AI 插图主要作为兜底。
- 每个用途只保留一个默认启用配置，避免排查困难。

## 第三方中转兼容

可以使用第三方 API 中转，只要中转商严格遵循对应协议：

- OpenAI Chat Completions
- Anthropic Messages
- Gemini generateContent
- OpenAI Images API

接入时不要让代码根据模型名猜协议，后台选择的 `provider` 就是唯一协议来源。

## 调用日志

模型调用日志写入：

```text
model_call_logs
```

记录内容：

- 用户 ID
- 订单 ID
- 生成任务 ID
- 当前阶段
- 模型配置 ID
- 用途和调用类型
- 模型名、协议
- 输入/输出字符数
- 耗时
- 成功或失败信息

管理后台“日志”页面可用于排查模型配置、额度、认证和响应耗时问题。

## 常见错误

### 认证失败

现象：

```text
Authentication Fails
unauthorized
invalid api key
```

处理：

- 检查 `api_key`。
- 检查 `api_base_url` 是否属于对应协议。
- 检查模型名是否是当前平台支持的模型名。

### 额度不足

现象：

```text
insufficient_user_quota
额度不足
```

处理：

- 充值模型供应商账号。
- 切换到可用模型配置。
- 用户端不会展示第三方完整错误，只展示业务化错误。

### 协议不匹配

示例：

```text
DeepSeek 模型选择了 Gemini generateContent 协议
```

处理：

- DeepSeek/Qwen/OpenAI 兼容模型使用 `provider=openai`。
- Gemini 模型使用 `provider=gemini-generate-content`。
