package com.tooldefect.business.shared.application;

/** 业务效果必须使用与 InboxProcessingService 相同的数据源事务。 */
@FunctionalInterface
public interface BusinessMessageHandler {
    void handle(String payloadJson);
}
