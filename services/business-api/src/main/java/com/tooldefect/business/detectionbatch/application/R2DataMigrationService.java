package com.tooldefect.business.detectionbatch.application;

import java.util.Objects;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** 显式运行回填和影子对账；发现未知映射时保持 HOLD。 */
@Service
public class R2DataMigrationService {
    private final R2DataRepository repository;

    public R2DataMigrationService(R2DataRepository repository) {
        this.repository = Objects.requireNonNull(repository);
    }

    @Transactional
    public RunResult runOnce() {
        var backfill = repository.backfillLegacyCaptures();
        int newDifferences = repository.captureShadowDifferences();
        var shadow = repository.shadowSummary();
        return new RunResult(backfill, newDifferences, shadow);
    }

    public record RunResult(
        R2DataRepository.BackfillResult backfill,
        int newDifferences,
        R2DataRepository.ShadowSummary shadow
    ) {
        public RunResult {
            Objects.requireNonNull(backfill);
            Objects.requireNonNull(shadow);
            if (newDifferences < 0) {
                throw new IllegalArgumentException("新增差异数不能为负数");
            }
        }

        public boolean safeToCutOver() {
            return shadow.safeToCutOver();
        }
    }
}
