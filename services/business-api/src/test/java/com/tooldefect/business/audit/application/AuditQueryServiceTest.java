package com.tooldefect.business.audit.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.security.SecureRandom;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import com.tooldefect.business.audit.domain.AuditRecord;
import com.tooldefect.business.shared.application.Uuid7Generator;

class AuditQueryServiceTest {
    @Test
    void appendsAuditEvidenceAfterAReadOnlyQuery() {
        AuditQueryRepository repository = mock(AuditQueryRepository.class);
        AuditTrail trail = mock(AuditTrail.class);
        Instant now = Instant.parse("2026-08-01T05:00:00Z");
        Clock clock = Clock.fixed(now, ZoneOffset.UTC);
        Uuid7Generator identifiers = new Uuid7Generator(
            clock,
            new SecureRandom(new byte[] {1, 2, 3, 4})
        );
        Map<String, Object> expected = Map.of(
            "items", List.of(),
            "has_more", false
        );
        Instant start = now.minusSeconds(3_600);
        when(repository.list(
            start, now, null, 50, "operator", "review", null, null, "SUCCESS"
        )).thenReturn(expected);
        AuditQueryService service = new AuditQueryService(
            repository, trail, identifiers, clock
        );

        Map<String, Object> actual = service.list(
            start,
            now,
            null,
            50,
            "operator",
            "review",
            null,
            null,
            "SUCCESS",
            "auditor-id",
            "127.0.0.1",
            "request-1",
            "a".repeat(32)
        );

        assertThat(actual).isSameAs(expected);
        verify(repository).list(
            start, now, null, 50, "operator", "review", null, null, "SUCCESS"
        );
        ArgumentCaptor<AuditRecord> record = ArgumentCaptor.forClass(AuditRecord.class);
        verify(trail).append(record.capture());
        assertThat(record.getValue().auditId().version()).isEqualTo(7);
        assertThat(record.getValue().occurredAt()).isEqualTo(now);
        assertThat(record.getValue().actorId()).isEqualTo("auditor-id");
        assertThat(record.getValue().actorIp()).isEqualTo("127.0.0.1");
        assertThat(record.getValue().action()).isEqualTo("audit.records.query");
        assertThat(record.getValue().afterDigest()).matches("[0-9a-f]{64}");
        assertThat(record.getValue().result()).isEqualTo("SUCCESS");
    }
}
