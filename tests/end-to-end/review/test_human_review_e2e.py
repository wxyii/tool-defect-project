from __future__ import annotations

import json
import unittest
from dataclasses import dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class ReviewRecord:
    reviewer: str
    decision: str
    round: int
    supersedes: int | None = None
    adjudication: bool = False


@dataclass
class ReviewScenario:
    requires_second: bool = False
    status: str = "PENDING"
    version: int = 0
    claimed_by: str | None = None
    claimed_from: str | None = None
    records: list[ReviewRecord] = field(default_factory=list)
    masks: list[str] = field(default_factory=list)
    disposition: str = "HOLD"
    audit: list[tuple[str, str]] = field(default_factory=list)
    revision_of: int | None = None
    training_approved: bool = False

    def claim(self, actor: str, expected_version: int, quality: bool = False) -> None:
        if expected_version != self.version:
            raise Conflict("版本冲突")
        if self.status not in {"PENDING", "SECOND_REVIEW_PENDING", "ESCALATED"}:
            raise Conflict("状态不可认领")
        if self.status == "ESCALATED" and not quality:
            raise Forbidden("只有质量负责人可裁决")
        if self.status == "SECOND_REVIEW_PENDING" and any(
            record.reviewer == actor for record in self.records
        ):
            raise Forbidden("首审人不可二审")
        self.claimed_from = self.status
        self.claimed_by = actor
        self.status = "CLAIMED"
        self.version += 1
        self.audit.append(("claim", actor))

    def submit(self, actor: str, decision: str, expected_version: int) -> None:
        if (
            self.status != "CLAIMED"
            or self.claimed_by != actor
            or expected_version != self.version
        ):
            raise Conflict("认领或版本已变化")
        phase = self.claimed_from
        if phase == "PENDING":
            self.records.append(ReviewRecord(actor, decision, 1))
            self.status = (
                "SECOND_REVIEW_PENDING" if self.requires_second else "RESOLVED"
            )
        elif phase == "SECOND_REVIEW_PENDING":
            first = self.records[0]
            if first.reviewer == actor:
                raise Forbidden("首审人不可二审")
            self.records.append(ReviewRecord(actor, decision, 2))
            self.status = "RESOLVED" if first.decision == decision else "ESCALATED"
        elif phase == "ESCALATED":
            self.records.append(
                ReviewRecord(actor, decision, len(self.records) + 1, adjudication=True)
            )
            self.status = "RESOLVED"
        else:
            raise Conflict("未知认领来源")
        self.version += 1
        self.claimed_by = None
        self.claimed_from = None
        self.disposition = decision if self.status == "RESOLVED" else "HOLD"
        self.audit.append(("submit", actor))

    def add_mask(self, object_id: str) -> None:
        if object_id in self.masks:
            raise Conflict("人工掩膜对象不可覆盖")
        self.masks.append(object_id)

    def open_revision(self) -> "ReviewScenario":
        if self.status != "RESOLVED" or not self.records:
            raise Conflict("只有已闭合记录可修订")
        return ReviewScenario(
            requires_second=self.requires_second,
            revision_of=len(self.records) - 1,
        )

    def use_for_training(self) -> None:
        if self.status != "RESOLVED" or not self.training_approved:
            raise Forbidden("复核关闭不等于训练批准")


class Conflict(RuntimeError):
    pass


class Forbidden(RuntimeError):
    pass


class HumanReviewEndToEndTest(unittest.TestCase):
    def test_single_review_forms_final_disposition_and_audit(self) -> None:
        task = ReviewScenario()
        task.claim("reviewer-a", 0)
        task.submit("reviewer-a", "PASS", 1)
        self.assertEqual("RESOLVED", task.status)
        self.assertEqual("PASS", task.disposition)
        self.assertEqual([("claim", "reviewer-a"), ("submit", "reviewer-a")], task.audit)

    def test_two_independent_reviews_agree(self) -> None:
        task = ReviewScenario(requires_second=True)
        task.claim("reviewer-a", 0)
        task.submit("reviewer-a", "FAIL", 1)
        task.claim("reviewer-b", 2)
        task.submit("reviewer-b", "FAIL", 3)
        self.assertEqual("RESOLVED", task.status)
        self.assertEqual(["reviewer-a", "reviewer-b"], [r.reviewer for r in task.records])

    def test_disagreement_stays_hold_until_quality_adjudication(self) -> None:
        task = ReviewScenario(requires_second=True)
        task.claim("reviewer-a", 0)
        task.submit("reviewer-a", "PASS", 1)
        task.claim("reviewer-b", 2)
        task.submit("reviewer-b", "FAIL", 3)
        self.assertEqual(("ESCALATED", "HOLD"), (task.status, task.disposition))
        with self.assertRaises(Forbidden):
            task.claim("ordinary-reviewer", 4)
        task.claim("quality-owner", 4, quality=True)
        task.submit("quality-owner", "FAIL", 5)
        self.assertTrue(task.records[-1].adjudication)
        self.assertEqual(("RESOLVED", "FAIL"), (task.status, task.disposition))

    def test_revision_preserves_closed_history(self) -> None:
        original = ReviewScenario()
        original.claim("reviewer-a", 0)
        original.submit("reviewer-a", "PASS", 1)
        revision = original.open_revision()
        revision.claim("reviewer-b", 0)
        revision.submit("reviewer-b", "FAIL", 1)
        self.assertEqual("PASS", original.records[0].decision)
        self.assertEqual(0, revision.revision_of)
        self.assertEqual("FAIL", revision.disposition)

    def test_scope_and_same_person_second_review_are_denied(self) -> None:
        task = ReviewScenario(requires_second=True)
        task.claim("reviewer-a", 0)
        task.submit("reviewer-a", "HOLD", 1)
        with self.assertRaises(Forbidden):
            task.claim("reviewer-a", 2)
        with self.assertRaises(Conflict):
            task.claim("reviewer-b", 1)

    def test_mask_revision_creates_new_objects_without_overwrite(self) -> None:
        task = ReviewScenario()
        task.add_mask("mask-v1")
        task.add_mask("mask-v2")
        with self.assertRaises(Conflict):
            task.add_mask("mask-v1")
        self.assertEqual(["mask-v1", "mask-v2"], task.masks)

    def test_training_is_blocked_until_separate_quality_approval(self) -> None:
        task = ReviewScenario()
        task.claim("reviewer-a", 0)
        task.submit("reviewer-a", "PASS", 1)
        with self.assertRaises(Forbidden):
            task.use_for_training()
        task.training_approved = True
        task.use_for_training()

    def test_contract_exposes_complete_human_review_network_path(self) -> None:
        contract = json.loads(
            (ROOT / "contracts/openapi/tool-defect-api-v1.json").read_text(
                encoding="utf-8"
            )
        )
        operations = {
            operation["operationId"]
            for path in contract["paths"].values()
            for operation in path.values()
            if isinstance(operation, dict) and "operationId" in operation
        }
        self.assertTrue(
            {
                "listReviewTasks",
                "getReviewWorkspace",
                "claimReviewTask",
                "releaseReviewTask",
                "submitReview",
                "createAnnotationUploadTicket",
                "completeReviewAnnotation",
            }.issubset(operations)
        )


if __name__ == "__main__":
    unittest.main()
