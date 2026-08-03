import json
import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class P7ReleaseChecks(unittest.TestCase):
    """验证 P7 上线就绪检查项，确保无遗漏、无伪造、无默认凭据。"""

    @classmethod
    def setUpClass(cls):
        cls.runbooks_dir = PROJECT_ROOT / "Docs" / "runbooks"
        cls.reports_dir = PROJECT_ROOT / "Docs" / "reports"
        cls.decisions_dir = PROJECT_ROOT / "Docs" / "decisions"

    # ── 决策关闭完整性 ──

    def test_decision_closure_completeness(self):
        """所有 22 个决策项在决策关闭文件中均有 closure_status。"""
        closure_path = self.decisions_dir / "production-decision-closure.json"
        closure = json.loads(closure_path.read_text(encoding="utf-8"))
        decisions = closure["decisions"]
        self.assertGreaterEqual(len(decisions), 22)
        for d in decisions:
            with self.subTest(decision_id=d["id"]):
                self.assertIn("closure_status", d)
                self.assertIn(
                    d["closure_status"],
                    {
                        "PENDING_SITE_SIGNOFF",
                        "CONFIRMED",
                        "CONFIRMED_DEFAULT",
                        "DEFERRED",
                    },
                )

    # ── 上线检查清单完整性 ──

    def test_checklist_completeness(self):
        """P7-go-live-checklist 包含全部 10 个必选段。"""
        checklist_path = self.reports_dir / "P7-go-live-checklist.json"
        checklist = json.loads(checklist_path.read_text(encoding="utf-8"))
        required_sections = {
            "SEC-01",
            "SEC-02",
            "SEC-03",
            "SEC-04",
            "SEC-05",
            "SEC-06",
            "SEC-07",
            "SEC-08",
            "SEC-09",
            "SEC-10",
        }
        actual = {s["id"] for s in checklist["sections"]}
        self.assertEqual(required_sections, actual)
        for section in checklist["sections"]:
            with self.subTest(section_id=section["id"]):
                self.assertGreater(len(section["items"]), 0)
            for item in section["items"]:
                with self.subTest(item_id=item["id"]):
                    self.assertIn("id", item)
                    self.assertIn("status", item)
                    self.assertIn("title", item)

    # ── 默认密码扫描 ──

    def test_no_default_passwords(self):
        """扫描所有 JSON 和 YAML 配置文件，确保无默认密码。"""
        config_globs = [
            list((PROJECT_ROOT / "configs").rglob("*.json")),
            list((PROJECT_ROOT / "configs").rglob("*.yaml")),
            list((PROJECT_ROOT / "configs").rglob("*.yml")),
            list((PROJECT_ROOT / "deploy").rglob("*.json")),
            list((PROJECT_ROOT / "deploy").rglob("*.yaml")),
            list((PROJECT_ROOT / "deploy").rglob("*.yml")),
        ]
        all_configs = []
        for g in config_globs:
            all_configs.extend(g)
        for p in all_configs:
            content = p.read_text(encoding="utf-8")
            self.assertNotRegex(
                content,
                r"(?i)(password\s*[:=]\s*['\"]?(admin|password|123456|root|test|default)[^a-z])",
                f"发现可疑默认密码字符串: {p.relative_to(PROJECT_ROOT)}",
            )

    # ── 回滚目标验证 ──

    def test_rollback_target_exists(self):
        """发布决策记录中声明了回滚目标模型版本。"""
        rdr_path = self.reports_dir / "P7-release-decision-record.json"
        rdr = json.loads(rdr_path.read_text(encoding="utf-8"))
        target = rdr.get("rollback_target", {})
        self.assertIsNotNone(target.get("model_version"))
        self.assertNotEqual("", target.get("model_version", ""))
        self.assertIsNotNone(target.get("model_registry_alias"))
        self.assertIsNotNone(target.get("procedure_ref"))

    # ── 监控告警覆盖 ──

    def test_monitoring_alerts_configured(self):
        """6 个关键告警项已在检查清单中确认。"""
        checklist_path = self.reports_dir / "P7-go-live-checklist.json"
        checklist = json.loads(checklist_path.read_text(encoding="utf-8"))
        sec_mon = None
        for s in checklist["sections"]:
            if s["id"] == "SEC-08":
                sec_mon = s
                break
        self.assertIsNotNone(sec_mon, "缺少第 8 段监控与告警")
        alert_count = len(sec_mon["items"])
        self.assertGreaterEqual(
            alert_count,
            6,
            f"关键告警项不足 6 个，当前 {alert_count}",
        )

    # ── 手册覆盖 ──

    def test_runbook_coverage(self):
        """每个关键告警在 ops-manual.md 中均有对应处置映射。"""
        ops_manual = self.runbooks_dir / "ops-manual.md"
        content = ops_manual.read_text(encoding="utf-8")
        expected_runbooks = [
            "01-disk-full.md",
            "02-network-outage.md",
            "03-dead-letter.md",
            "04-database-unwritable.md",
            "05-object-storage.md",
            "06-model-not-ready.md",
            "07-hash-conflict.md",
            "08-review-backlog.md",
            "09-backup-restore.md",
            "10-emergency-rollback.md",
        ]
        for rb in expected_runbooks:
            with self.subTest(runbook=rb):
                self.assertIn(rb, content, f"ops-manual.md 未引用手册 {rb}")

    # ── 签署必需字段 ──

    def test_signoff_required(self):
        """发布决策记录包含 4 个必需签署字段。"""
        rdr_path = self.reports_dir / "P7-release-decision-record.json"
        rdr = json.loads(rdr_path.read_text(encoding="utf-8"))
        approved = rdr.get("approved_by", {})
        required_signers = {"quality_lead", "process_lead", "algorithm_lead", "release_lead"}
        actual_signers = set(approved.keys())
        self.assertEqual(required_signers, actual_signers)
        for role in required_signers:
            with self.subTest(role=role):
                self.assertIn("name", approved[role])
                self.assertIn("status", approved[role])

    # ── 签署未完成禁止生产声明 ──

    def test_production_claim_denied(self):
        """签署未全部完成时不得声称 GO。"""
        rdr_path = self.reports_dir / "P7-release-decision-record.json"
        rdr = json.loads(rdr_path.read_text(encoding="utf-8"))
        self.assertEqual(rdr["status"], "BLOCKED")
        self.assertEqual(rdr["decision"], "NO_GO")
        all_signed = all(
            v["status"] == "SIGNED" for v in rdr["approved_by"].values()
        )
        if not all_signed:
            self.assertNotEqual(
                rdr["decision"],
                "GO",
                "签署未完成时决定不应为 GO",
            )

    # ── 角色手册存在性 ──

    def test_role_manuals_exist(self):
        """所有 4 个角色手册文件存在且包含核心章节。"""
        manuals = {
            "operator-manual.md": ["正常操作", "HOLD", "交班", "禁止操作"],
            "reviewer-manual.md": ["复核工作流", "标注指南", "原因代码", "升级"],
            "quality-lead-manual.md": ["质量看板", "样本导出", "推翻调查", "试运行"],
            "ops-manual.md": ["系统启停", "健康检查", "备份验证", "告警响应"],
        }
        for filename, keywords in manuals.items():
            path = self.runbooks_dir / filename
            self.assertTrue(path.exists(), f"缺少手册文件: {filename}")
            content = path.read_text(encoding="utf-8")
            for kw in keywords:
                with self.subTest(file=filename, keyword=kw):
                    self.assertIn(kw, content, f"{filename} 缺少核心章节: {kw}")

    # ── 应急演练场景完整性 ──

    def test_drill_scenarios_completeness(self):
        """应急演练场景至少 12 个，每个包含必要字段。"""
        drill_path = self.runbooks_dir / "emergency-drill-scenarios.json"
        drill = json.loads(drill_path.read_text(encoding="utf-8"))
        scenarios = drill["scenarios"]
        self.assertGreaterEqual(len(scenarios), 12)
        required_fields = {
            "id",
            "severity",
            "title",
            "description",
            "trigger",
            "expected_system_behavior",
            "recovery_steps",
            "success_criteria",
            "runbook_ref",
        }
        for sc in scenarios:
            with self.subTest(scenario_id=sc["id"]):
                self.assertTrue(
                    required_fields.issubset(sc.keys()),
                    f"场景 {sc['id']} 缺少字段: {required_fields - set(sc.keys())}",
                )
                self.assertIn(
                    sc["severity"],
                    {"S1", "S2", "S3"},
                    f"场景 {sc['id']} 的严重级别无效",
                )

    # ── 紧急联系人模板字段 ──

    def test_emergency_contacts_template_structure(self):
        """紧急联系人模板包含所有必需角色。"""
        contacts_path = self.runbooks_dir / "emergency-contacts.template.json"
        contacts = json.loads(contacts_path.read_text(encoding="utf-8"))
        required_roles = {
            "ops_lead",
            "security_lead",
            "quality_lead",
            "edge_lead",
            "infra_lead",
            "algorithm_lead",
            "release_lead",
            "process_lead",
        }
        actual_roles = set(contacts["roles"].keys())
        self.assertEqual(required_roles, actual_roles)
        for role_key, role_data in contacts["roles"].items():
            with self.subTest(role=role_key):
                for field in ["title", "name", "phone", "email", "responsibilities"]:
                    self.assertIn(field, role_data)
                self.assertGreater(len(role_data["responsibilities"]), 0)
        self.assertIn("escalation_chain", contacts)
        self.assertEqual(contacts["status"], "PENDING_SITE_FILL")

    # ── 不需要密码扫描就能看到──

    def test_configs_dont_contain_secrets(self):
        """递归扫描 configs/ 和 deploy/ 目录，禁止出现 secret、token 或 private 字面量。"""
        banned_patterns = [
            (r'(?i)secret_key\s*[:=]\s*["\'](?!\$\{|\$\()[\w]+["\']', "疑似密钥字面量"),
            (r'(?i)access_token\s*[:=]\s*["\'](?!\$\{|\$\()[\w\-\.]+["\']', "疑似令牌字面量"),
            (r'(?i)private_key\s*[:=]\s*["\'](?!\$\{|\$\()[\s\S]{20,}["\']', "疑似私钥字面量"),
        ]
        for root_dir in ["configs", "deploy"]:
            dir_path = PROJECT_ROOT / root_dir
            if not dir_path.exists():
                continue
            for p in dir_path.rglob("*"):
                if not p.is_file() or p.suffix not in {".json", ".yaml", ".yml", ".py", ".env", ".toml", ".ini", ".conf"}:
                    continue
                content = p.read_text(encoding="utf-8")
                for pattern, desc in banned_patterns:
                    self.assertIsNone(
                        re.search(pattern, content),
                        f"{p.relative_to(PROJECT_ROOT)}: {desc}",
                    )


if __name__ == "__main__":
    unittest.main()
