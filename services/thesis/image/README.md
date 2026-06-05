# 论文图片生成与渲染说明

本目录负责把论文正文中的图片占位符渲染为本地图片文件，不负责 Word 文档排版和图片插入。

## 上下游关系

论文生成主流程在 `services/thesis/generation/pipeline.py` 中：

1. `content` 生成正文，正文中可能包含 `<<FIGURE>>...<</FIGURE>>` 图片占位符。
2. `generation` 解析占位符，并根据后台模型配置选择图片生成器。
3. 本目录将 Mermaid、结构化图表或 AI 插图渲染为本地 PNG。
4. `document` 接收本地图片路径，把图片插入 Word 文档。

## 当前文件职责

| 文件 | 职责 |
| --- | --- |
| `renderer.py` | 图片占位符批量调度入口，负责按 `render_method` 分发、重试和并发控制。 |
| `ai_generator.py` | 图片生成器抽象接口、OpenAI Images API / Gemini generateContent 图片生成器和纯白占位图生成器。 |
| `mermaid_renderer.py` | Mermaid CLI、Chromium/Puppeteer 配置和 Mermaid 语法兼容处理。 |
| `chart_renderer.py` | matplotlib 图表渲染、中文字体探测和图表样式。 |
| `utils.py` | 渲染错误压缩、图片白边裁剪等通用工具。 |

## 能力边界

- Mermaid CLI、Chromium、matplotlib、Pillow、AI 生图 API、图片裁剪、图片渲染并发控制放在本目录。
- Word 中图片插入、尺寸限制和图题排版放在 `services/thesis/document`。
- 图片占位符协议定义和解析复用 `schemas.thesis`，由 `services/thesis/document/placeholder.py` 对外转发。
- 图片模型配置读取和生成流程编排放在 `services/thesis/generation`。

## 并发控制

图片渲染使用进程内全局并发槽，配置来自环境变量：

| 配置 | 作用 |
| --- | --- |
| `MERMAID_RENDER_CONCURRENCY` | Mermaid/Chromium 本地渲染并发上限。 |
| `CHART_RENDER_CONCURRENCY` | matplotlib 本地图表渲染并发上限。 |
| `AI_IMAGE_RENDER_CONCURRENCY` | AI 插图渲染流程并发上限。 |
| `IMAGE_MODEL_CONCURRENCY` | 第三方图片模型 API 调用并发上限。 |

`AI_IMAGE_RENDER_CONCURRENCY` 控制进入 AI 插图流程的任务数量，`IMAGE_MODEL_CONCURRENCY` 控制真正打到第三方模型接口的请求数量。Mermaid 失败后转 AI 兜底时，会先释放 Mermaid 槽位，再进入 AI 插图槽位。

## 维护注意事项

- 优化图片生成速度、并发、重试、模型协议和渲染环境时，优先修改本目录。
- 后台图片模型协议当前支持 `openai-image-generations`、`google-generate-content` 和 `gemini-generate-content`。
- 修改 Word 中图片尺寸、位置、图题样式时，不要改本目录，应修改 `services/thesis/document/figures.py` 或文档构建逻辑。
- 如果 `renderer.py` 后续继续膨胀，可按 Mermaid、chart、AI generator、dispatch 继续拆分。
