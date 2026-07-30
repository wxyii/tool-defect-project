# 采集端与离线队列

本目录实现 P2-C01 至 P2-C03：

- SQLite WAL、本地状态投影、原子落盘、启动恢复、隔离与安全清理；
- 标准触发和相机端口、去抖、序列检查、多帧及确定性模拟器；
- 幂等同步、上传票据续期、退避抖动、批量对账、结果轮询和心跳；
- 真实 HTTPS JSON 传输、Bearer、可注入 mTLS 和签名对象流式 PUT。
- 通过仓库内生成的 `tool-defect-contracts` v1 包调用全部中心接口；
  当前契约源 SHA-256 为
  `6fc5d9465464faf374bfa54d8f20849623f912a6c3d88fdbe92ca47fba49e361`。

厂商相机或 PLC 软件开发包只能位于 `adapters/`，不得渗透到同步逻辑。
采集端只保存 SQLite 同步投影，不持久化或自行补充最终业务处置；最终处置
通过中心响应交给现场展示回调。未上传、重试中或中心状态未知的原图不会
自动删除。

`SyncService` 的最终结果与目录确认处理器均为必填，并且必须按
`capture_id` 幂等。身份或证书故障会持久化全局同步暂停；验证凭据恢复后
必须显式调用 `resume_after_auth_recovery()`。启动时应先调用
`AtomicCaptureStore.recover()`，再调用
`CaptureCoordinator.recover_incomplete_triggers()`；默认不会假设工件仍
可安全重拍。

上传票据中的 `X-Tool-Defect-Upload-Receipt` 是控制面回执，上传器会提取
并持久化，但绝不会把它转发到对象存储。对象 PUT 成功而确认超时会只重试
确认；若中心明确返回 `TD-STORAGE-EXPIRED-001`，才续票并重传。

当前 v1 状态响应没有中心确认时间或签名回执字段，因此本地清理保留期从
“观察到中心最终状态”的时间开始，属于更保守但精度有限的替代；清理审计
记录中心状态和文件哈希。严格中心回执仍需后续兼容契约扩展。

P2 轻量传输与图片校验相对目标 HTTPX/OpenCV 栈的边界和 G7 复审要求见
`Docs/decisions/ADR-0002-P2采集端轻量传输与图片校验边界.md`。

验证命令：

```text
make test-edge
```
