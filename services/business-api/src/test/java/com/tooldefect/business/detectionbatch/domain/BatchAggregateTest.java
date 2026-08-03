package com.tooldefect.business.detectionbatch.domain;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.List;

import org.junit.jupiter.api.Test;

class BatchAggregateTest {
    @Test
    void rebuildsPartialCompletionWithoutTurningFailuresIntoSuccess() {
        var aggregate = BatchAggregate.rebuild(List.of(
            item(BatchItemSnapshot.Status.COMPLETED, BatchItemSnapshot.Outcome.QUALIFIED),
            item(BatchItemSnapshot.Status.COMPLETED, BatchItemSnapshot.Outcome.UNQUALIFIED),
            item(BatchItemSnapshot.Status.COMPLETED, BatchItemSnapshot.Outcome.INCONCLUSIVE),
            item(BatchItemSnapshot.Status.QUALITY_REJECTED, null),
            item(BatchItemSnapshot.Status.FAILED, null)
        ));

        assertThat(aggregate.status()).isEqualTo(BatchAggregate.Status.PARTIALLY_COMPLETED);
        assertThat(aggregate.counts()).isEqualTo(
            new BatchAggregate.Counts(5, 5, 1, 1, 1, 1, 1)
        );
    }

    @Test
    void keepsNonTerminalBatchProcessing() {
        var aggregate = BatchAggregate.rebuild(List.of(
            item(BatchItemSnapshot.Status.COMPLETED, BatchItemSnapshot.Outcome.QUALIFIED),
            item(BatchItemSnapshot.Status.PROCESSING, null)
        ));

        assertThat(aggregate.status()).isEqualTo(BatchAggregate.Status.PROCESSING);
        assertThat(aggregate.counts().completed()).isEqualTo(1);
    }

    @Test
    void rejectsOutcomeOnNonCompletedItem() {
        assertThatThrownBy(() -> item(
            BatchItemSnapshot.Status.FAILED,
            BatchItemSnapshot.Outcome.QUALIFIED
        )).isInstanceOf(IllegalArgumentException.class);
    }

    private static BatchItemSnapshot item(
            BatchItemSnapshot.Status status,
            BatchItemSnapshot.Outcome outcome) {
        return new BatchItemSnapshot(status, outcome);
    }
}
