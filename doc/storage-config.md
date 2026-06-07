# 存储配置

本文说明论文 Word 文件的本地兜底、远端上传和下载链接生成方式。

## 总体策略

论文文件一定先生成到本地：

```text
public/output/thesis/{task_id}/{论文标题}-{task_id}.docx
```

随后按 `STORAGE_PROVIDER` 上传远端：

```env
STORAGE_PROVIDER=local
```

可选值：

| provider | 说明 |
| --- | --- |
| `local` | 只使用本地静态文件。 |
| `qiniu` | 上传七牛云对象存储。 |
| `minio` | 上传 MinIO。 |
| `cos` | 上传腾讯云 COS。 |

远端上传失败时，系统会记录 warning 并返回本地下载链接，不会把论文任务标记失败。

## 本地存储

配置：

```env
STORAGE_PROVIDER=local
PUBLIC_BASE_URL=http://localhost:10462
THESIS_OUTPUT_ROOT=public/output/thesis
```

下载链接形态：

```text
{PUBLIC_BASE_URL}/output/thesis/{task_id}/{filename}.docx
```

如果 `PUBLIC_BASE_URL` 为空，则返回相对路径。

## 七牛云

配置：

```env
STORAGE_PROVIDER=qiniu
STORAGE_OBJECT_PREFIX=paper
QINIU_ACCESS_KEY=
QINIU_SECRET_KEY=
QINIU_BUCKET=
QINIU_DOMAIN=https://cdn.example.com
QINIU_DOWNLOAD_EXPIRES=3600
```

对象 key：

```text
paper/{task_id}/{filename}.docx
```

七牛默认按私有空间生成临时下载链接：

```text
https://cdn.example.com/paper/{task_id}/{filename}.docx?e=...&token=...
```

数据库中应保存 `storage_provider=qiniu` 和 `file_key`，不要长期依赖某一次生成的签名链接，因为签名可能过期。订单下载接口会按 `file_key` 重新生成链接。

## MinIO

配置：

```env
STORAGE_PROVIDER=minio
STORAGE_OBJECT_PREFIX=paper
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=
MINIO_SECRET_KEY=
MINIO_BUCKET=ai-paper
MINIO_SECURE=false
MINIO_DOMAIN=
STORAGE_DOWNLOAD_EXPIRES=3600
```

说明：

- `MINIO_DOMAIN` 为空时，返回预签名 URL。
- `MINIO_DOMAIN` 不为空时，可以按自定义域名拼接访问链接。

## 腾讯云 COS

配置：

```env
STORAGE_PROVIDER=cos
STORAGE_OBJECT_PREFIX=paper
COS_SECRET_ID=
COS_SECRET_KEY=
COS_BUCKET=example-1250000000
COS_REGION=ap-guangzhou
COS_DOMAIN=
COS_ACCESS_POLICY=PRIVATE
COS_UPLOAD_ALLOW_PREFIX=*
STORAGE_DOWNLOAD_EXPIRES=3600
```

访问策略：

| 策略 | 说明 |
| --- | --- |
| `PRIVATE` | 生成预签名下载链接。 |
| `PUBLIC_READ` | 返回公开访问链接。 |

`COS_UPLOAD_ALLOW_PREFIX` 可限制允许上传的对象前缀，默认 `*`。

## public 目录挂载

Docker 生产建议：

```env
HOST_PUBLIC_DIR=/data/server/ai-paper-api/public
CONTAINER_PUBLIC_DIR=/app/public
```

优势：

- 前端构建产物可直接放到宿主机 `public`。
- 本地兜底论文文件不会随容器重建丢失。
- 远端上传失败时仍可下载本地文件。

## 回调字段

生成完成后，回调业务系统的 payload 包含：

```json
{
  "task_id": "xxx",
  "file_key": "paper/xxx/demo.docx",
  "download_url": "https://...",
  "storage_provider": "qiniu",
  "local_file_key": "output/thesis/xxx/demo.docx",
  "local_download_url": "https://api.example.com/output/thesis/xxx/demo.docx",
  "status": "completed",
  "error_msg": ""
}
```

上游业务系统应优先保存：

- `storage_provider`
- `file_key`
- `local_file_key`

下载时再调用 ai-paper-api 获取最新下载链接，或者使用回调中的短期下载链接。

## 常见问题

### 远端上传失败但论文成功

这是预期行为。远端对象存储失败时会降级本地文件，用户仍可下载。

### 七牛链接过期

私有空间链接会过期。不要把一次性的 `download_url` 当永久链接；应保存 `file_key` 并按需重新生成。

### 本地下载链接打不开

检查：

- `PUBLIC_BASE_URL` 是否是用户能访问的地址。
- `public/output/thesis` 是否挂载到容器。
- 反向代理是否允许访问静态文件。
- 文件是否真实存在。
