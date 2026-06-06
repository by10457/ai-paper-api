# 论文文档存储说明

本目录只负责“论文生成产物 `.docx` 文件的存储与下载地址生成”。它不负责订单扣费、任务队列、业务回调、Word 文档生成，也不负责图片渲染。

## 上下游关系

论文生成主流程在 `services/thesis/generation/task_service.py` 中：

1. `services/thesis/generation/pipeline.py` 生成本地 `.docx` 文件。
2. `task_service` 调用 `storage/document_storage.py` 的 `store_document(...)`。
3. 本目录始终记录本地兜底文件，并按 `STORAGE_PROVIDER` 尝试上传远端对象存储。
4. `task_service` 将 `storage_provider`、`file_key`、`download_url`、`local_file_key`、`local_download_url` 写入任务状态和订单记录。
5. `services/thesis/business/order_callback.py` 负责把存储结果回调给上游业务系统。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| `document_storage.py` | 统一入口，负责校验本地文件、选择存储 provider、生成远端 object key、按存储类型生成下载地址。 |
| `local_storage.py` | 本地兜底存储结果、本地文件 key、本地静态下载地址和对象 key 编码工具。 |
| `qiniu_storage.py` | 七牛云上传、七牛私有空间下载链接生成。 |
| `minio_storage.py` | MinIO 上传、自动建桶、MinIO 预签名下载链接生成。 |
| `cos_storage.py` | 腾讯云 COS 上传、公有读或私有预签名下载链接生成。 |

## 核心数据

`store_document(...)` 返回 `StoredDocument`：

| 字段 | 含义 |
| --- | --- |
| `storage_provider` | 主存储类型，可能是 `local`、`qiniu`、`minio`、`cos`。远端失败时降级为 `local`。 |
| `file_key` | 主存储文件 key；本地模式下等于 `local_file_key`。 |
| `download_url` | 主存储下载地址；私有存储会按当前配置生成临时下载链接。 |
| `local_file_key` | 本地兜底文件 key，始终记录。 |
| `local_download_url` | 本地兜底下载地址，始终记录。 |

## 存储策略

- 本地文件是必然兜底：论文文件先生成到 `public/output/thesis/{task_id}`，再按配置上传远端。
- 远端上传失败不阻断论文完成：`document_storage.py` 会记录 warning，并返回本地存储结果。
- 下载链接按需生成：订单下载接口会根据 `storage_provider` 和 `file_key` 重新生成下载地址，避免长期使用过期的私有签名 URL。
- 远端 object key 使用 `STORAGE_OBJECT_PREFIX/{task_id}/{filename}`，文件名来自生成流程中的 `论文标题-task_id.docx`。

## 配置项

| 配置 | 作用 |
| --- | --- |
| `STORAGE_PROVIDER` | 主存储类型：`local`、`qiniu`、`minio`、`cos`。 |
| `STORAGE_OBJECT_PREFIX` | 远端对象 key 前缀。 |
| `STORAGE_DOWNLOAD_EXPIRES` | MinIO / COS 私有下载链接有效期，单位秒。 |
| `PUBLIC_BASE_URL` | 本地静态文件对外访问基础地址，用于生成 `local_download_url`。 |
| `QINIU_ACCESS_KEY` / `QINIU_SECRET_KEY` / `QINIU_BUCKET` / `QINIU_DOMAIN` | 七牛云上传和下载配置。 |
| `QINIU_DOWNLOAD_EXPIRES` | 七牛私有下载链接有效期，单位秒。 |
| `MINIO_ENDPOINT` / `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` / `MINIO_BUCKET` | MinIO 上传和下载配置。 |
| `MINIO_SECURE` | MinIO 是否使用 HTTPS。 |
| `MINIO_DOMAIN` | MinIO/CDN 自定义访问域名；为空时生成预签名链接。 |
| `COS_SECRET_ID` / `COS_SECRET_KEY` / `COS_BUCKET` / `COS_REGION` | 腾讯云 COS 上传和下载配置。 |
| `COS_DOMAIN` | COS/CDN 自定义访问域名；为空时按访问策略生成链接。 |
| `COS_ACCESS_POLICY` | COS 访问策略：`PRIVATE` 或 `PUBLIC_READ`。 |
| `COS_UPLOAD_ALLOW_PREFIX` | 允许上传的对象 key 前缀，默认 `*`。 |

## 能力边界

- 订单创建、扣费、退款、重试和订单状态回写放在 `services/thesis/business`。
- 生成完成回调放在 `services/thesis/business/order_callback.py`。
- 论文 `.docx` 生成放在 `services/thesis/document`。
- Mermaid、图表和 AI 插图生成放在 `services/thesis/image`。
- 任务队列、任务状态和生成流程编排放在 `services/thesis/generation`。

## 维护注意事项

- 新增对象存储 provider 时，优先新增独立 `xxx_storage.py`，再在 `document_storage.py` 增加分发分支。
- 不要在本目录处理业务订单状态、积分、回调 HTTP 请求或数据库事务。
- 不要把供应商 SDK 细节泄漏到业务层；业务层只使用 `store_document(...)` 和 `build_download_url(...)`。
- 私有下载地址可能过期，数据库应记录 `storage_provider`、`file_key` 和 `local_file_key`，由接口按需生成最新链接。
- 本地兜底是强约束，任何远端 provider 都必须保留 `local_file_key` 和 `local_download_url`。

## 建议验证命令

```bash
uv run ruff check services/thesis/storage tests/thesis/test_document_storage.py
uv run pytest tests/thesis/test_document_storage.py tests/thesis/test_paper_order_api.py -q
```
