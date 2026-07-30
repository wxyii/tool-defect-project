# 业务后端骨架

首期采用 Java 25 与 Spring Boot 4.1 系列的模块化单体。应用默认不启用
RabbitMQ 与 S3 连接，部署必须显式注入数据库、消息、对象存储和身份配置，
且不提供默认账号或口令。

后续模块必须遵循：

```text
api -> application -> domain
infrastructure -> application/domain
```

领域层不得依赖 Spring、数据库或消息队列；模块不得直接访问其他模块的数据访问层。业务数据库迁移由本服务唯一拥有。

本模块消费冻结契约 `v1`，当前源文件 SHA-256 为
`6fc5d9465464faf374bfa54d8f20849623f912a6c3d88fdbe92ca47fba49e361`。
网络字段仍以 `contracts/` 及生成包为唯一来源，禁止在服务内手工维护平行 DTO。

验证入口统一使用仓库内 Maven Wrapper：

```text
cd services/business-api
./mvnw test
./mvnw verify
```

`test` 执行纯单元测试和 ArchUnit 边界测试，不需要外部服务。`verify` 还通过
Testcontainers 执行以下 `*IT`：

- PostgreSQL 空库和向前迁移、约束、`pg_dump`/`pg_restore` 隔离恢复；
- 完整应用启动、独立回环管理端口和最小健康信息；
- PostgreSQL + MinIO 的续签端点、短时签名上传、哈希/元数据确认；
- PostgreSQL + RabbitMQ 的发布确认、mandatory 退回、租约补发、收件箱幂等和单向死信。

续签票据中的 `X-Tool-Defect-Upload-Receipt` 是控制面不透明回执，不是对象
存储请求头。采集端必须大小写无关地提取并持久化该值，向 S3 兼容端点执行
`PUT` 时不得转发它；上传成功后，再把原值作为 `complete` 请求的
`upload_receipt` 提交。票据中其余签名头必须原样发送给对象存储。服务端以该
回执绑定组织、工位、采集、图片、对象键、大小和 SHA-256，并在确认时重新读取
对象验证实际哈希和图像尺寸，不能把 ETag 当作内容完整性证明。

签名地址始终为 HTTPS。`TD_S3_ENDPOINT` 是服务端访问对象存储的内部端点；
存在 TLS 终止代理时可用 `TD_S3_PUBLIC_ENDPOINT` 单独配置采集端可访问的 HTTPS
签名端点。完整性确认首次失败时，服务关闭失败会话并让图片保持不可引用的
`STAGING`，允许同一 `image_id` 受控续签重传一次；第二次失败才进入
`QUARANTINED`，防止无限覆盖或重试。

集成测试显式设置 `disabledWithoutDocker = false`。缺少 Docker 或兼容容器运行时
时，`./mvnw verify` 必须失败；不得将此状态记录为跳过或通过。生产连接、凭据和
JWT 解码器只能由环境或机密挂载注入，示例配置不提供默认秘密。
