# 论文 Word 文档处理说明

本目录只负责“把已经生成好的论文内容加工成 Word 文档”。它不负责订单、数据库状态、支付、回调，也不直接调用大模型。

## 上游入口

论文生成主流程在 `services/thesis/generation/pipeline.py` 中：

1. 生成参考文献、正文、摘要、致谢。
2. 从正文中解析图片占位符。
3. 调用 `services/thesis/image` 渲染 Mermaid、图表或 AI 图片，得到 `image_paths`。
4. 调用 `document/docx_builder.py` 中的 `build_word_document(...)` 输出 `.docx` 文件。

因此文档层的核心输入是：

- `full_text`：Markdown 风格正文。
- `placeholders`：正文中的图片占位符列表。
- `image_paths`：图片占位符 index 到本地图片路径的映射。
- 封面、摘要、关键词、致谢、参考文献等元数据。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| `docx_builder.py` | Word 文档构建总入口，按页面顺序编排封面、声明页、摘要、目录、正文、参考文献和致谢。 |
| `styles.py` | 初始化全局页面设置、默认正文样式和标题样式。 |
| `sections.py` | 处理 Word section、页眉页脚、罗马页码和正文阿拉伯页码。 |
| `pages.py` | 生成固定页面：封面、诚信承诺书、版权授权书、中英文摘要、参考文献、致谢。 |
| `toc.py` | 预扫描正文标题，生成目录条目、书签和 PAGEREF 页码字段。 |
| `inline.py` | 处理正文中的 Markdown 内联语法、引用标注和 Markdown 表格。 |
| `figures.py` | 插入图片并限制最大宽高，避免图片破坏版式。 |
| `formatting.py` | 底层格式工具：字体、固定行距、页码字段参数等。 |
| `placeholder.py` | 对外复用 `schemas.thesis` 中的图片占位符解析能力。 |
| `utils.py` | 文档相关的小工具，例如安全文件名处理。 |

## Word 生成顺序

`build_word_document(...)` 当前按以下顺序生成文档：

1. 创建输出目录和空白 Word 文档。
2. 设置 A4 页面、页边距、默认字体、正文和标题样式。
3. 生成封面、诚信承诺书、版权使用授权书。这一段不显示页码。
4. 新建摘要 section，中文摘要从罗马页码 `I` 开始。
5. 新建英文摘要 section，罗马页码自然延续。
6. 预扫描正文标题，生成目录所需的标题、层级和书签信息。
7. 生成目录页，目录页继续使用罗马页码。
8. 新建正文 section，正文页码从阿拉伯数字 `1` 开始，并添加页眉。
9. 逐行解析正文：
   - `#`、`##`、`###` 转为 Word 标题，并写入目录书签。
   - Markdown 表格转为三线表。
   - `[1]` 这类引用标注转为上标。
   - 图片占位符位置插入对应图片和图题。
10. 生成参考文献页和致谢页，并为目录中的“参考文献”“致谢”绑定书签。
11. 修正文档核心属性后保存 `.docx`。

## 维护注意事项

- 业务状态、订单、支付和上传回调不要放到本目录，应放在 `business` 或 `generation` 目录。
- 大模型提示词、正文生成、摘要生成和参考文献生成不要放到本目录，应放在 `content` 目录。
- Mermaid、图表和 AI 图片生成不要放到本目录，应放在 `services/thesis/image`。
- 新增 Word 页面时，优先放到 `pages.py`；如果只是主流程顺序调整，再改 `docx_builder.py`。
- 新增段落、字体、行距、页码等底层格式能力时，优先放到 `formatting.py`。
- 新增 section、页眉、页脚、页码重启规则时，优先放到 `sections.py`。
- 修改目录逻辑时，同时关注 `_pre_scan_headings(...)`、`_add_toc_page(...)` 和正文标题处的 `_add_bookmark(...)`。
- 文档目录和页码大量依赖 Word OOXML 字段，改动后建议至少运行目录、封面、学校格式和参考文献相关测试。

## 建议验证命令

```bash
uv run ruff check services/thesis/document tests/thesis
uv run pytest tests/thesis/test_toc_structure.py \
  tests/thesis/test_cover_layout.py \
  tests/thesis/test_school_format_compliance.py \
  tests/thesis/test_reference_injection.py \
  tests/thesis/test_placeholder_image.py \
  tests/thesis/test_thesis_image_renderer.py -q
```
