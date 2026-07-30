package com.tooldefect.business.shared.application;

import com.tooldefect.business.shared.messaging.OutboxEvent;

public interface MessagePublisher {
    /** 只有收到发布者确认后才正常返回。 */
    void publishAndConfirm(OutboxEvent event);
}
