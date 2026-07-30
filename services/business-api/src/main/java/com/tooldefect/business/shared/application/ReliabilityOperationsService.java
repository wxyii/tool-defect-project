package com.tooldefect.business.shared.application;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;

import com.tooldefect.business.shared.application.ReliabilityOperationsRepository.Action;
import com.tooldefect.business.shared.application.ReliabilityOperationsRepository.ActionType;
import com.tooldefect.business.shared.application.ReliabilityOperationsRepository.Issue;
import com.tooldefect.business.shared.application.ReliabilityOperationsRepository.IssueCandidate;
import com.tooldefect.business.shared.application.ReliabilityOperationsRepository.IssueType;
import com.tooldefect.business.shared.domain.DomainViolation;

/**
 * 受限维护面：扫描只追加问题事实；人工动作带权限、原因、请求和追踪标识。
 * 重试原任务只恢复可变投递投影，原问题和每次动作永久保留。
 */
public final class ReliabilityOperationsService {
    public static final String DEAD_LETTER_PERMISSION =
        "operations.dead-letter.manage";
    public static final String STORAGE_PERMISSION =
        "operations.storage.maintain";

    private final ReliabilityOperationsRepository repository;
    private final Uuid7Generator identifiers;
    private final Clock clock;
    private final Duration stagingAuditWindow;

    public ReliabilityOperationsService(
            ReliabilityOperationsRepository repository,
            Uuid7Generator identifiers,
            Clock clock,
            Duration stagingAuditWindow) {
        this.repository = Objects.requireNonNull(repository);
        this.identifiers = Objects.requireNonNull(identifiers);
        this.clock = Objects.requireNonNull(clock);
        if (stagingAuditWindow == null
                || stagingAuditWindow.compareTo(Duration.ofMinutes(5)) < 0
                || stagingAuditWindow.compareTo(Duration.ofDays(30)) > 0) {
            throw new DomainViolation("暂存对象审计窗口必须位于 5 分钟到 30 天");
        }
        this.stagingAuditWindow = stagingAuditWindow;
    }

    public int scanDatabase(int limit, String requestId, String traceId) {
        requireLimit(limit);
        requireContext(requestId, traceId);
        Instant detectedAt = clock.instant();
        int appended = 0;
        for (IssueCandidate candidate : repository.discoverDatabaseIssues(
                detectedAt.minus(stagingAuditWindow),
                limit)) {
            requireCandidate(candidate);
            Issue issue = new Issue(
                identifiers.next(),
                fingerprint(candidate),
                candidate.issueType(),
                candidate.severity(),
                candidate.resourceType(),
                candidate.resourceId(),
                candidate.captureId(),
                java.util.Collections.unmodifiableMap(
                    new LinkedHashMap<>(candidate.observedState())
                ),
                detectedAt,
                requestId,
                traceId
            );
            if (repository.appendIssue(issue)) {
                appended++;
            }
        }
        return appended;
    }

    public UUID decide(
            UUID issueId,
            ActionType actionType,
            String replacementResourceId,
            String actorId,
            Set<String> actorPermissions,
            String reason,
            String requestId,
            String traceId) {
        Objects.requireNonNull(issueId);
        Objects.requireNonNull(actionType);
        requireText(actorId, "处置人");
        requireContext(requestId, traceId);
        if (reason == null || reason.trim().length() < 8) {
            throw new DomainViolation("人工处置原因至少包含 8 个字符");
        }
        Issue issue = repository.findIssue(issueId)
            .orElseThrow(() -> new DomainViolation("可靠性问题不存在"));
        Set<String> permissions = actorPermissions == null
            ? Set.of()
            : Set.copyOf(actorPermissions);
        String requiredPermission = requiredPermission(
            issue.issueType(),
            actionType
        );
        if (!permissions.contains(requiredPermission)) {
            throw new DomainViolation("缺少可靠性人工处置权限");
        }
        if (actionType == ActionType.CREATE_NEW_TASK) {
            requireText(replacementResourceId, "替代任务标识");
        } else if (replacementResourceId != null) {
            throw new DomainViolation("只有新建任务处置可以关联替代任务");
        }
        Action action = new Action(
            identifiers.next(),
            identifiers.next(),
            issueId,
            actionType,
            replacementResourceId,
            actorId,
            permissions,
            reason.trim(),
            requestId,
            traceId,
            clock.instant()
        );
        repository.applyAction(issue, action);
        return action.actionId();
    }

    private static String requiredPermission(
            IssueType issueType,
            ActionType actionType) {
        boolean storageIssue = switch (issueType) {
            case AVAILABLE_OBJECT_MISSING,
                    OBJECT_INTEGRITY_MISMATCH,
                    STAGING_OBJECT_ORPHANED -> true;
            default -> false;
        };
        if (storageIssue) {
            if (actionType == ActionType.RETRY_ORIGINAL) {
                throw new DomainViolation("存储问题不能作为消息原任务回灌");
            }
            return STORAGE_PERMISSION;
        }
        if (actionType == ActionType.REATTACH_OBJECT
                || actionType == ActionType.QUARANTINE_OBJECT) {
            throw new DomainViolation("非存储问题不能执行对象处置");
        }
        return DEAD_LETTER_PERMISSION;
    }

    private static String fingerprint(IssueCandidate candidate) {
        String stable = candidate.issueType().name()
            + "\n"
            + candidate.resourceType()
            + "\n"
            + candidate.resourceId();
        try {
            return HexFormat.of().formatHex(
                MessageDigest.getInstance("SHA-256")
                    .digest(stable.getBytes(StandardCharsets.UTF_8))
            );
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("运行时缺少 SHA-256", impossible);
        }
    }

    private static void requireCandidate(IssueCandidate candidate) {
        Objects.requireNonNull(candidate);
        Objects.requireNonNull(candidate.issueType());
        Objects.requireNonNull(candidate.severity());
        requireText(candidate.resourceType(), "资源类型");
        requireText(candidate.resourceId(), "资源标识");
        Objects.requireNonNull(candidate.observedState());
    }

    private static void requireLimit(int limit) {
        if (limit < 1 || limit > 1_000) {
            throw new DomainViolation("可靠性扫描批量必须位于 1 到 1000");
        }
    }

    private static void requireContext(String requestId, String traceId) {
        requireText(requestId, "请求标识");
        if (traceId == null || !traceId.matches("[0-9a-f]{32}")) {
            throw new DomainViolation("追踪标识必须是 32 位小写十六进制");
        }
    }

    private static String requireText(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new DomainViolation(field + "不能为空");
        }
        return value;
    }
}
