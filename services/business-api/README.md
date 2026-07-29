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

验证入口：

```text
mvn -B -f services/business-api/pom.xml test
mvn -B -f services/business-api/pom.xml verify
```

`test` 执行单元、架构和应用上下文测试；`verify` 还执行依赖
PostgreSQL、RabbitMQ 与 S3 兼容容器的 `*IT` 集成测试。缺少容器运行时应视为
集成门禁未运行，不能当作通过。
