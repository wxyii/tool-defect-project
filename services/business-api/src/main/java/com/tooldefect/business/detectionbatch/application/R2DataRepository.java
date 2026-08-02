package com.tooldefect.business.detectionbatch.application;

public interface R2DataRepository {
    BackfillResult backfillLegacyCaptures();

    int captureShadowDifferences();

    ShadowSummary shadowSummary();

    record BackfillResult(int insertedBatches, int insertedItems, int heldCaptures) {
        public BackfillResult {
            if (insertedBatches < 0 || insertedItems < 0 || heldCaptures < 0) {
                throw new IllegalArgumentException("回填计数不能为负数");
            }
        }
    }

    record ShadowSummary(int unexplainedDifferences, int heldMigrations) {
        public ShadowSummary {
            if (unexplainedDifferences < 0 || heldMigrations < 0) {
                throw new IllegalArgumentException("差异计数不能为负数");
            }
        }

        public boolean safeToCutOver() {
            return unexplainedDifferences == 0 && heldMigrations == 0;
        }
    }
}
