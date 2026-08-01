package com.tooldefect.business.overview.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.Instant;
import java.util.Map;

import org.junit.jupiter.api.Test;

class OverviewQueryServiceTest {
    @Test
    void delegatesEveryWindowAndScopeInputWithoutWideningIt() {
        OverviewQueryRepository repository = mock(OverviewQueryRepository.class);
        OverviewQueryService service = new OverviewQueryService(repository);
        Instant generatedAt = Instant.parse("2026-08-01T04:30:00Z");
        Instant currentStart = Instant.parse("2026-07-31T16:00:00Z");
        Instant previousStart = Instant.parse("2026-07-30T16:00:00Z");
        Instant previousEnd = Instant.parse("2026-07-31T04:30:00Z");
        Instant heartbeatCutoff = Instant.parse("2026-08-01T04:28:00Z");
        Map<String, Object> expected = Map.of(
            "generated_at", generatedAt.toString()
        );
        when(repository.summarize(
            "019fbcf9-0000-7000-8000-000000000001",
            generatedAt,
            currentStart,
            generatedAt,
            previousStart,
            previousEnd,
            heartbeatCutoff,
            120,
            "Asia/Shanghai"
        )).thenReturn(expected);

        Map<String, Object> actual = service.getOverview(
            "019fbcf9-0000-7000-8000-000000000001",
            generatedAt,
            currentStart,
            generatedAt,
            previousStart,
            previousEnd,
            heartbeatCutoff,
            120,
            "Asia/Shanghai"
        );

        assertThat(actual).isSameAs(expected);
        verify(repository).summarize(
            "019fbcf9-0000-7000-8000-000000000001",
            generatedAt,
            currentStart,
            generatedAt,
            previousStart,
            previousEnd,
            heartbeatCutoff,
            120,
            "Asia/Shanghai"
        );
    }
}
