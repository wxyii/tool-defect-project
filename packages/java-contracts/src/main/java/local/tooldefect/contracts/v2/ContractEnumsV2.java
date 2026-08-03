// 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。
// 契约主版本: 2；源哈希: b30eca1ebbb6b533902ed4ba897e07c0daebd02a7ecf931154f9d2fb3ae0fc8e
package local.tooldefect.contracts.v2;

public final class ContractEnumsV2 {
    public static final String SOURCE_SHA256 = "b30eca1ebbb6b533902ed4ba897e07c0daebd02a7ecf931154f9d2fb3ae0fc8e";
    public static final int MAJOR_VERSION = 2;
    private ContractEnumsV2() {}

    public enum AdminFeedbackLabel {
        CORRECT_DETECTION,
        FALSE_POSITIVE,
        FALSE_NEGATIVE,
        LOCALIZATION_INACCURATE,
        IMAGE_UNUSABLE,
        UNCONFIRMED
    }

    public enum AlgorithmOutcome {
        QUALIFIED,
        UNQUALIFIED,
        INCONCLUSIVE
    }

    public enum BatchItemStatus {
        PENDING_UPLOAD,
        UPLOADING,
        READY,
        QUEUED,
        PROCESSING,
        COMPLETED,
        QUALITY_REJECTED,
        FAILED,
        CANCELLED
    }

    public enum BatchSource {
        MANUAL_UPLOAD,
        PRODUCTION_CAPTURE
    }

    public enum BatchStatus {
        DRAFT,
        UPLOADING,
        READY,
        PROCESSING,
        COMPLETED,
        PARTIALLY_COMPLETED,
        FAILED,
        CANCELLED
    }

    public enum ExportJobStatus {
        QUEUED,
        RUNNING,
        SUCCEEDED,
        FAILED,
        EXPIRED
    }

    public enum ImageQualityCheckStatus {
        PASS,
        WARNING,
        FAIL,
        NOT_RUN
    }

    public enum ImageQualityCheckType {
        DECODABLE,
        BLADE_PRESENT,
        BLADE_COMPLETE,
        BLUR,
        EXPOSURE
    }

    public enum ImageQualityOverall {
        ACCEPTED,
        WARNING,
        REJECTED
    }

    public enum ModelUploadStatus {
        AWAITING_UPLOAD,
        UPLOADED,
        VALIDATING,
        VALIDATED,
        REJECTED,
        EXPIRED
    }

    public enum ModelValidationStatus {
        PASSED,
        FAILED,
        HOLD
    }

    public enum PersonRole {
        PRODUCTION_EMPLOYEE,
        ADMINISTRATOR
    }

    public enum QuickReviewDecision {
        DEFECT_CONFIRMED,
        NO_DEFECT_CONFIRMED,
        UNABLE_TO_DETERMINE
    }

    public enum SampleCandidateStatus {
        PENDING,
        INCLUDED,
        EXCLUDED,
        EXPORTED
    }

    public enum UsageStage {
        NEW_BLADE,
        AFTER_ONE_WHEEL,
        AFTER_TWO_WHEELS,
        AFTER_THREE_WHEELS,
        OTHER,
        UNSPECIFIED
    }

}
