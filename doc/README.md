# AI Paper API 文档索引

本文档目录面向部署、对接、运维和二次开发。

## 文档列表

| 文档 | 内容 |
| --- | --- |
| [启动与部署](startup-and-deployment.md) | 本地启动、Docker 部署、进程角色、连接池和 public 挂载。 |
| [论文生成流程](thesis-generation.md) | 从大纲、扣费、队列、正文、图片、Word、存储到回调的完整流程。 |
| [AI 模型配置](ai-model-config.md) | 管理后台模型配置、用途、协议、默认模型和调用日志。 |
| [存储配置](storage-config.md) | local、七牛云、MinIO、腾讯云 COS 的配置和下载链接策略。 |
| [接口对接](api-integration.md) | 直连接口、订单接口、认证、幂等和回调。 |
| [运维与排查](operations.md) | 健康检查、Redis 队列、数据库、模型错误、Mermaid、存储和回调排查。 |

## 推荐阅读顺序

部署服务：

1. [启动与部署](startup-and-deployment.md)
2. [AI 模型配置](ai-model-config.md)
3. [存储配置](storage-config.md)
4. [运维与排查](operations.md)

对接业务系统：

1. [接口对接](api-integration.md)
2. [论文生成流程](thesis-generation.md)
3. [存储配置](storage-config.md)

二次开发：

1. [论文生成流程](thesis-generation.md)
2. [AI 模型配置](ai-model-config.md)
3. `services/thesis/content/README.md`
4. `services/thesis/image/README.md`
5. `services/thesis/storage/README.md`
