# 推理消息契约 v1

`inference-events-v1.json` 定义推理任务、事务发件箱和死信通道，明确：

- 持久交换机、持久消息和仲裁队列；
- 发布者确认、消费者手动确认；
- 至少一次投递与收件箱至多一次业务效果；
- `message_id` 和 `detection_task_id` 双重幂等；
- W3C `traceparent` 跨队列传播；
- 死信禁止自动无限回灌。
