package com.tooldefect.business.overview.application;

import java.time.Instant;
import java.util.Map;

/** 按人员数据范围读取总览聚合，仓储不得返回未授权工位的数据。 */
public interface OverviewQueryRepository {
    Map<String, Object> summarize(
        String actorId,
        Instant generatedAt,
        Instant currentStart,
        Instant currentEnd,
        Instant previousStart,
        Instant previousEnd,
        Instant heartbeatCutoff,
        long heartbeatFreshnessSeconds,
        String timezone
    );
}
