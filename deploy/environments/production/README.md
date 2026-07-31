# 生产环境部署指南

## 前置条件

- Docker Engine ≥ 24.0 及 Docker Compose ≥ 2.20
- mTLS 证书体系已就绪（服务端证书、CA 证书链、设备证书）
- 外部密钥管理服务（HashiCorp Vault 或等效）已配置并可访问
- 对象存储端点、消息队列端点、身份提供方地址均已确认
- 工控机操作系统、相机 SDK、PLC 协议驱动均已就绪
- 18 项"上线阻断"决策已获得现场签字确认（参见 `Docs/decisions/production-decision-closure.json`）

## 目录布局

```
deploy/environments/production/
├── README.md                            ← 本文件
├── .env.example                         ← Compose 非机密环境变量示例
├── docker-compose.production.yml        ← 生产 Compose 编排
├── site-config.yaml                     ← 现场参数配置模板
├── evidence/
│   └── README.md                        ← 现场证据契约；真实输出通过受控挂载提供
├── secrets/
│   └── README.md                        ← 密钥管理指南
└── checklists/
    ├── pre-flight.json                  ← 起飞前检查清单
    ├── validate_config.py               ← 决策、配置和技术清单验证
    ├── validate_env.py                  ← 环境与镜像摘要验证
    ├── validate_model_hash.py           ← 生产模型供应链重新验签
    ├── smoke_test_model.py              ← 真实模型冒烟证据验证
    └── validate_preflight.py            ← 结构化预检结果聚合
```

关联文件:
- `deploy/compose/production-security-baseline.yml` — 安全基线（上游引用）
- `Docs/decisions/site-parameter-decisions.json` — 22 项现场参数决策
- `Docs/decisions/production-decision-closure.json` — 进入关闭记录

## 部署步骤

### 1. 核实决策关闭状态
确保 `Docs/decisions/production-decision-closure.json` 中所有 18 项"上线阻断"决策的状态均为 `CONFIRMED`，且每项都有可复算 SHA-256 的签字证据。不得使用“至少若干项”的部分关闭规则。

### 2. 准备密钥
按 `secrets/README.md` 中的分类清单，从外部密钥管理服务拉取所有生产密钥到 Docker secret 存储。验证密钥审计日志。

### 3. 填充环境变量
复制 `.env.example` 为 `.env`，只填写 Compose 实际消费的发布标识、镜像仓库和镜像摘要。现场决策参数只写入 `site-config.yaml`，不得在两处重复维护；密钥只通过外部 secret 注入。

### 4. 填充现场配置
按 `site-config.yaml` 模板填入所有 `config_key` 的实际值。将所有 `PENDING_SITE_SIGNOFF` 替换为现场确认值。

### 5. 准备证书目录
```
/secrets/certificates/
├── gateway/
│   ├── tls.crt
│   └── tls.key
├── device-ca/
│   ├── ca.crt
│   └── ca.crl
├── service-ca/
│   ├── ca.crt
│   └── ca.crl
├── inference-service/
│   ├── service.crt
│   └── service.key
├── rabbitmq/
│   ├── tls.crt
│   └── tls.key
├── object-storage/
│   ├── tls.crt
│   └── tls.key
└── telemetry/
    ├── ca.crt
    ├── server.crt
    ├── server.key
    ├── business.crt
    ├── business.key
    ├── inference.crt
    └── inference.key
```

### 6. 执行起飞前检查清单
```bash
python deploy/environments/production/checklists/validate_preflight.py \
  --checklist deploy/environments/production/checklists/pre-flight.json \
  --results /受控证据挂载/preflight-results.json
```

聚合器不会执行清单里的 Shell；现场执行器必须按 `evidence/README.md` 生成逐项结构化记录。返回 `0` 才表示全部必检项真实通过，返回 `1` 表示输入或实现错误，返回 `2` 表示现场前置未满足。

### 7. 启动服务
```bash
docker compose \
  -f deploy/compose/production-security-baseline.yml \
  -f deploy/environments/production/docker-compose.production.yml \
  --env-file deploy/environments/production/.env \
  up -d
```

### 8. 验证部署
```bash
docker compose \
  -f deploy/compose/production-security-baseline.yml \
  -f deploy/environments/production/docker-compose.production.yml \
  ps
```

## 健康检查

| 服务 | 端点 | 预期状态 |
|------|------|----------|
| gateway | `https://<host>:443/health` | 200 OK |
| business-api | `https://gateway:9443/actuator/health` | 200, status UP |
| inference-service | `https://gateway:9443/inference/health` | 200, status UP |
| postgres | `pg_isready -h postgres` | accepting connections |
| rabbitmq | `rabbitmq-diagnostics check_running` | OK |
| object-storage | `https://object-storage:9443/minio/health/live` | 200 OK |
| telemetry | `https://telemetry:4317/health` | 200 OK |

全量检查命令:
```bash
curl -f https://<host>:443/health && echo "gateway OK"
curl -f https://<host>:443/actuator/health && echo "business-api OK"
curl -f https://<host>:443/inference/health && echo "inference-service OK"
```

## 回滚流程

1. **立即停止**: `docker compose -f deploy/compose/production-security-baseline.yml -f deploy/environments/production/docker-compose.production.yml down`
2. **恢复数据卷快照**: 从最近的备份快照恢复 `postgres-data`、`rabbitmq-data`、`object-data` 卷
3. **切换镜像标签**: 将 `.env` 文件中的 `TD_RELEASE_ID` 回滚到最近已知良好版本
4. **重新启动**: 按部署步骤 7 重新启动
5. **验证**: 执行健康检查，确认所有端点和业务功能正常
6. **通知**: 将回滚原因、影响范围和决议通知所有利益相关方

紧急回滚详细流程参见: `Docs/runbooks/10-emergency-rollback.md`

## 紧急联系人

| 角色 | 职责 | 当前负责人 |
|------|------|-----------|
| 现场运维负责人 | 工控机、网络、磁盘 | PENDING_ONBOARD |
| 采集与设备负责人 | PLC、相机、传感器 | PENDING_ONBOARD |
| 质量负责人 | 处置阈值、抽检、复核 | PENDING_ONBOARD |
| 工艺负责人 | 节拍、延迟、服务目标 | PENDING_ONBOARD |
| 基础设施负责人 | 服务器、消息队列、恢复 | PENDING_ONBOARD |
| 存储负责人 | 对象存储、保留策略 | PENDING_ONBOARD |
| 身份与安全负责人 | 统一身份、证书 | PENDING_ONBOARD |
| 可观测与运维负责人 | 监控、告警 | PENDING_ONBOARD |
| 架构负责人 | 部署平台、技术选型 | PENDING_ONBOARD |
| 法务负责人 | 数据保留、合规 | PENDING_ONBOARD |

## 重要提示

- 18 项"上线阻断"决策需要逐项现场签字确认，详见 `Docs/decisions/site-parameter-decisions.json`
- 在全部"上线阻断"决策获得签字前，生产环境整体保持禁用
- 所有密钥通过外部密钥管理服务注入，**严禁**在 `.env` 或配置文件中包含真实密码
- 首次部署必须完成 `checklists/pre-flight.json` 所有必检项
