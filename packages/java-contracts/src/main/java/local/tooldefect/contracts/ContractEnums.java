// 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。
// 契约主版本: 1；源哈希: 159efe83cd0f071d155864372a56d28b72668271b4f6b4e4a4b3d895f9193540
package local.tooldefect.contracts;

public final class ContractEnums {
    public static final String SOURCE_SHA256 = "159efe83cd0f071d155864372a56d28b72668271b4f6b4e4a4b3d895f9193540";
    public static final int MAJOR_VERSION = 1;
    private ContractEnums() {}

    public enum AlgorithmOutcome {
        QUALIFIED,
        UNQUALIFIED,
        INCONCLUSIVE
    }

    public enum AttemptStatus {
        RUNNING,
        SUCCEEDED,
        FAILED
    }

    public enum BusinessDisposition {
        PASS,
        FAIL,
        HOLD
    }

    public enum CaptureStatus {
        CREATED,
        UPLOADING,
        READY,
        SUBMITTED,
        PROCESSING,
        REVIEW_PENDING,
        FINALIZED,
        FAILED
    }

    public enum ExecutionStatus {
        QUEUED,
        RUNNING,
        SUCCEEDED,
        RETRY_WAIT,
        DEAD
    }

    public enum ImageKind {
        RAW,
        THUMBNAIL,
        DEFECT_MASK,
        HEATMAP,
        OVERLAY,
        POLAR,
        REVIEW_MASK
    }

    public enum LocalQueueStatus {
        PENDING,
        UPLOADING,
        UPLOADED,
        SUBMITTED,
        WAIT_RESULT,
        DONE,
        RETRY_WAIT,
        LOCAL_DEAD
    }

    public enum ModelStatus {
        DRAFT,
        VALIDATING,
        APPROVED,
        SHADOW,
        CANARY,
        PRODUCTION,
        REJECTED,
        QUARANTINED,
        RETIRED
    }

    public enum ObjectState {
        STAGING,
        AVAILABLE,
        QUARANTINED,
        DELETED
    }

    public enum PreprocessQualityStatus {
        OK,
        WARNING,
        REJECTED
    }

    public enum ReviewStatus {
        PENDING,
        CLAIMED,
        SECOND_REVIEW_PENDING,
        ESCALATED,
        RESOLVED,
        CANCELLED
    }

}
