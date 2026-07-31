package com.tooldefect.business.quality.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.tooldefect.business.quality.domain.QualityMetrics;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.junit.jupiter.api.Test;

class QualityQueryServiceTest {

    @Test
    void returnsRepositoryMetricsAsContractShapedResponse() {
        QualityMetricsRepository repository = mock(QualityMetricsRepository.class);
        QualityQueryService service = new QualityQueryService(repository);
        Instant start = Instant.parse("2026-07-01T00:00:00Z");
        Instant end = Instant.parse("2026-08-01T00:00:00Z");
        UUID modelVersionId = UUID.fromString("019fb1b0-0000-7000-8000-000000000014");
        when(repository.summarize(start, end, modelVersionId)).thenReturn(new QualityMetrics(
            start,
            end,
            0.25,
            0.5,
            2,
            1,
            List.of(new QualityMetrics.Reason("MASK_REVISION", 2, 1.0)),
            4,
            true
        ));

        Map<String, Object> response = service.getMetricsResponse(start, end, modelVersionId);

        assertThat(response).containsKeys(
            "time_window",
            "auto_pass_fail_rate",
            "model_overturn_rate",
            "missed_detection_count",
            "false_positive_count",
            "mask_revision_reasons",
            "total_sample_count",
            "based_on_full_ground_truth"
        );
        assertThat(response).containsEntry("auto_pass_fail_rate", 0.25)
            .containsEntry("model_overturn_rate", 0.5)
            .containsEntry("total_sample_count", 4L)
            .containsEntry("based_on_full_ground_truth", true);
    }
}
