package com.tooldefect.business.shared.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.security.SecureRandom;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;

import org.junit.jupiter.api.Test;

import com.tooldefect.business.shared.application.ReliabilityOperationsRepository.Action;
import com.tooldefect.business.shared.application.ReliabilityOperationsRepository.ActionType;
import com.tooldefect.business.shared.application.ReliabilityOperationsRepository.Issue;
import com.tooldefect.business.shared.application.ReliabilityOperationsRepository.IssueCandidate;
import com.tooldefect.business.shared.application.ReliabilityOperationsRepository.IssueType;
import com.tooldefect.business.shared.application.ReliabilityOperationsRepository.Severity;
import com.tooldefect.business.shared.domain.DomainViolation;

class ReliabilityOperationsServiceTest {
    private static final Instant NOW =
        Instant.parse("2026-07-30T10:00:00Z");
    private static final String TRACE = "a".repeat(32);

    @Test
    void scanIsIdempotentAndNeverMutatesOriginalFacts() {
        MemoryRepository repository = new MemoryRepository();
        repository.candidates.add(new IssueCandidate(
            IssueType.OUTBOX_DEAD,
            Severity.HIGH,
            "outbox_event",
            UUID.randomUUID().toString(),
            UUID.randomUUID(),
            Map.of("attempt_count", 3)
        ));
        ReliabilityOperationsService service = service(repository);

        assertThat(service.scanDatabase(10, "request-1", TRACE)).isEqualTo(1);
        assertThat(service.scanDatabase(10, "request-2", TRACE)).isZero();
        assertThat(repository.issues).hasSize(1);
        assertThat(repository.originalMutationCount).isZero();
    }

    @Test
    void deadLetterReplayRequiresPermissionAndReason() {
        MemoryRepository repository = new MemoryRepository();
        ReliabilityOperationsService service = service(repository);
        repository.candidates.add(new IssueCandidate(
            IssueType.OUTBOX_DEAD,
            Severity.HIGH,
            "outbox_event",
            UUID.randomUUID().toString(),
            UUID.randomUUID(),
            Map.of("last_error", "timeout")
        ));
        service.scanDatabase(10, "request-1", TRACE);
        UUID issueId = repository.issues.values().iterator().next().issueId();

        assertThatThrownBy(() -> service.decide(
            issueId,
            ActionType.RETRY_ORIGINAL,
            null,
            "operator-1",
            Set.of(),
            "确认网络恢复后回灌",
            "request-2",
            TRACE
        )).isInstanceOf(DomainViolation.class);
        assertThatThrownBy(() -> service.decide(
            issueId,
            ActionType.RETRY_ORIGINAL,
            null,
            "operator-1",
            Set.of(ReliabilityOperationsService.DEAD_LETTER_PERMISSION),
            "太短",
            "request-2",
            TRACE
        )).isInstanceOf(DomainViolation.class);

        UUID actionId = service.decide(
            issueId,
            ActionType.RETRY_ORIGINAL,
            null,
            "operator-1",
            Set.of(ReliabilityOperationsService.DEAD_LETTER_PERMISSION),
            "确认网络恢复后人工回灌",
            "request-2",
            TRACE
        );
        assertThat(repository.actions).singleElement()
            .extracting(Action::actionId)
            .isEqualTo(actionId);
        assertThat(repository.originalMutationCount).isEqualTo(1);
        assertThat(repository.issues).hasSize(1);
    }

    @Test
    void storageAndMessageActionsCannotCrossBoundaries() {
        MemoryRepository repository = new MemoryRepository();
        ReliabilityOperationsService service = service(repository);
        repository.candidates.add(new IssueCandidate(
            IssueType.STAGING_OBJECT_ORPHANED,
            Severity.HIGH,
            "image_object",
            UUID.randomUUID().toString(),
            UUID.randomUUID(),
            Map.of("state", "STAGING")
        ));
        service.scanDatabase(10, "request-1", TRACE);
        UUID issueId = repository.issues.values().iterator().next().issueId();

        assertThatThrownBy(() -> service.decide(
            issueId,
            ActionType.RETRY_ORIGINAL,
            null,
            "operator-1",
            Set.of(
                ReliabilityOperationsService.STORAGE_PERMISSION,
                ReliabilityOperationsService.DEAD_LETTER_PERMISSION
            ),
            "错误地尝试消息回灌",
            "request-2",
            TRACE
        )).isInstanceOf(DomainViolation.class);
    }

    private static ReliabilityOperationsService service(
            ReliabilityOperationsRepository repository) {
        Clock clock = Clock.fixed(NOW, ZoneOffset.UTC);
        return new ReliabilityOperationsService(
            repository,
            new Uuid7Generator(clock, new SecureRandom()),
            clock,
            Duration.ofHours(1)
        );
    }

    private static final class MemoryRepository
            implements ReliabilityOperationsRepository {
        private final List<IssueCandidate> candidates = new ArrayList<>();
        private final Map<UUID, Issue> issues = new LinkedHashMap<>();
        private final List<Action> actions = new ArrayList<>();
        private int originalMutationCount;

        @Override
        public List<IssueCandidate> discoverDatabaseIssues(
                Instant stagingBefore,
                int limit) {
            return candidates.stream().limit(limit).toList();
        }

        @Override
        public boolean appendIssue(Issue issue) {
            if (issues.values().stream().anyMatch(
                    existing -> existing.fingerprint().equals(
                        issue.fingerprint()
                    ))) {
                return false;
            }
            issues.put(issue.issueId(), issue);
            return true;
        }

        @Override
        public Optional<Issue> findIssue(UUID issueId) {
            return Optional.ofNullable(issues.get(issueId));
        }

        @Override
        public void applyAction(Issue issue, Action action) {
            actions.add(action);
            if (action.actionType() == ActionType.RETRY_ORIGINAL) {
                originalMutationCount++;
            }
        }
    }
}
