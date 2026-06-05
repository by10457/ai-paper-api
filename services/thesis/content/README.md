# 论文内容生成说明

本目录负责生成论文 Word 文档所需的内容材料，不负责订单、积分、任务状态、文件上传，也不负责 Word 排版和文档保存。

## 上下游关系

论文生成主流程在 `services/thesis/generation/pipeline.py` 中编排：

1. 调用本目录生成参考文献、正文、摘要和致谢。
2. 从正文内容中解析图片占位符。
3. 调用 `services/thesis/document` 渲染图片并组装 Word 文档。

因此，本目录的输出应该是可被文档层消费的文本、结构化大纲或参考文献字符串。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| `outline_service.py` | 根据论文题目和写作配置生成结构化论文大纲。 |
| `fulltext_service.py` | 根据大纲、参考文献和写作要求生成论文正文。 |
| `abstract_service.py` | 根据正文生成中英文摘要、关键词和致谢。 |
| `reference_service.py` | 参考文献生成统一入口，按配置选择万方、SerpAPI 或混合模式。 |
| `reference_service_wfapi.py` | 使用万方开放平台检索、解析并格式化参考文献。 |
| `reference_service_serpapi.py` | 使用 SerpAPI 检索、CrossRef 补全并格式化参考文献。 |

## 能力边界

- 大模型调用、外部文献 API 调用、参考文献格式化可以放在本目录。
- Markdown 正文、Markdown 表格、图片占位符等内容形态可以由本目录生成。
- Word 页面、字体、行距、目录、页码、表格渲染、图片插入应放在 `services/thesis/document`。
- Mermaid、结构化图表和 AI 插图渲染应放在 `services/thesis/image`。
- 论文生成顺序、失败降级、输出路径和图片模型选择应放在 `services/thesis/generation`。
- 订单、积分、支付、任务幂等和回调应放在 `services/thesis/business` 或任务层。

## 表格与图片的关系

论文正文中的表格由正文生成模型输出为 Markdown 表格，例如：

```markdown
表 4.3 CIFAR-10 各类别准确率对比

| 类别 | ResNet-18 准确率 | 改进模型准确率 |
| --- | --- | --- |
| 飞机 | 93.51% | 95.20% |
```

这类表格不是图片，也不经过 `services/thesis/image`。文档层会在 `docx_builder.py` 中识别 `|` 开头的 Markdown 表格行，并调用 `inline.py` 转成 Word 三线表。

`services/thesis/image` 只处理图片类占位符，包括 Mermaid 图、结构化图表和 AI 插图。只有正文里出现 `<<FIGURE>>...<</FIGURE>>` 这类图片占位符时，才会进入图片渲染流程。

## 维护注意事项

- 新增一种内容生成能力时，优先判断它输出的是“内容材料”还是“文档格式”。前者放本目录，后者放 `document`。
- 参考文献 provider 可以继续独立拆分，但统一入口应保持在 `reference_service.py`。
- 本目录不应保存第三方平台 HTML 文档、截图或临时资料；这类资料建议放到项目文档目录。
