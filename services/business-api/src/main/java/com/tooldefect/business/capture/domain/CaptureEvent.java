package com.tooldefect.business.capture.domain;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

import com.tooldefect.business.shared.domain.DomainViolation;

/**
 * 当前状态是投影；处置历史由独立追加记录保存。
 */
public final class CaptureEvent {
    private final UUID captureId;
    private final UUID stationId;
    private final long clientSequence;
    private final Instant capturedAt;
    private CaptureStatus status;
    private BusinessDisposition currentDisposition;
    private UUID currentDispositionId;
    private long recordVersion;

    public CaptureEvent(
            UUID captureId,
            UUID stationId,
            long clientSequence,
            Instant capturedAt) {
        this.captureId = Objects.requireNonNull(captureId);
        this.stationId = Objects.requireNonNull(stationId);
        if (clientSequence < 0) {
            throw new DomainViolation("clientSequence 不能为负数");
        }
        this.clientSequence = clientSequence;
        this.capturedAt = Objects.requireNonNull(capturedAt);
        this.status = CaptureStatus.CREATED;
        this.recordVersion = 0;
    }

    public void transition(CaptureStatus target) {
        status.requireTransitionTo(Objects.requireNonNull(target));
        if (target == CaptureStatus.FINALIZED
                && (currentDisposition == null || currentDispositionId == null)) {
            throw new DomainViolation("FINALIZED 必须引用追加的处置记录");
        }
        this.status = target;
        this.recordVersion++;
    }

    public void projectDisposition(UUID dispositionId, BusinessDisposition disposition) {
        this.currentDispositionId = Objects.requireNonNull(dispositionId);
        this.currentDisposition = Objects.requireNonNull(disposition);
        this.recordVersion++;
    }

    public UUID captureId() {
        return captureId;
    }

    public UUID stationId() {
        return stationId;
    }

    public long clientSequence() {
        return clientSequence;
    }

    public Instant capturedAt() {
        return capturedAt;
    }

    public CaptureStatus status() {
        return status;
    }

    public BusinessDisposition currentDisposition() {
        return currentDisposition;
    }

    public UUID currentDispositionId() {
        return currentDispositionId;
    }

    public long recordVersion() {
        return recordVersion;
    }
}
